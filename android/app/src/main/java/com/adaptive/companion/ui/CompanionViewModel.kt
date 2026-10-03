package com.adaptive.companion.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.adaptive.companion.data.*
import com.adaptive.companion.scheduler.WorkScheduler
import com.adaptive.companion.scheduler.ScheduledDelivery
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
import android.os.SystemClock
import android.net.Uri

data class CompanionUiState(
    val ready: Boolean = false,
    val messages: List<ChatMessage> = emptyList(),
    val preparingReply: Boolean = false,
    val error: String? = null,
    val feedbackTarget: ChatMessage? = null,
    val periodicFeedbackDue: Boolean = false,
    val settings: AppSettings = AppSettings(),
    val onboarding: OnboardingStatus? = null,
    val onboardingVisible: Boolean = false,
    val savingPersona: Boolean = false,
    val mutatingHistory: Boolean = false,
    val modelConfigured: Boolean = false,
    val pendingImage: String? = null,
    val loadingImage: Boolean = false,
    val draftText: String = "",
)

class CompanionViewModel(application: Application) : AndroidViewModel(application) {
    private val context: Application get() = getApplication()
    val settingsStore = SettingsStore(context)
    val secrets = SecureSecretStore(context)
    val bridge = CoreBridge(context)
    private val _state = MutableStateFlow(CompanionUiState())
    val state: StateFlow<CompanionUiState> = _state.asStateFlow()
    private var sendJob: Job? = null
    private var turnRunner: Job? = null
    private var imageJob: Job? = null
    private val enqueueJobs = mutableSetOf<Job>()
    private var composerDraft = false
    private var composerActivity = 0L
    private val turnWakeups = TurnWakeups()
    private val replyDelivery = ReplyBubbleDelivery()

    fun cacheDraft(text: String) { _state.value = _state.value.copy(draftText = text) }

    fun composerChanged(hasDraft: Boolean) {
        composerDraft = hasDraft
        composerActivity = SystemClock.elapsedRealtime()
        bridge.noteComposer(hasDraft)
        turnWakeups.signal()
    }

    fun pickImage(uri: Uri) {
        if (!canSendImage(_state.value.modelConfigured, _state.value.settings.modelSupportsVision) || _state.value.loadingImage) return
        _state.value = _state.value.copy(loadingImage = true)
        composerChanged(true)
        imageJob = viewModelScope.launch {
            try {
                val path = PickedImageStore.import(context, uri)
                _state.value.pendingImage?.let { PickedImageStore.removeDraft(context, it) }
                _state.value = _state.value.copy(pendingImage = path)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { _state.value = _state.value.copy(error = "Image could not be opened") }
            finally { _state.value = _state.value.copy(loadingImage = false) }
        }
    }

    fun removeImage() {
        _state.value.pendingImage?.let { PickedImageStore.removeDraft(context, it) }
        _state.value = _state.value.copy(pendingImage = null)
    }

    init {
        viewModelScope.launch {
            ChatUpdates.messages.collect { id ->
                val token = ChatUpdates.history.token() ?: return@collect
                // Accept hints promptly; the shared presenter keeps replies in
                // order and protects queued replies from full-history refreshes.
                launch {
                    presentReply(id, token) {
                        try { bridge.message(id) }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { null }
                    }
                }
            }
        }
        viewModelScope.launch {
            settingsStore.flow.collectLatest { settings ->
                _state.value = _state.value.copy(settings = settings)
                turnWakeups.signal()
            }
        }
        viewModelScope.launch { initialize() }
    }

    suspend fun initialize() {
        val token = ChatUpdates.history.token() ?: return
        runCatching {
            settingsStore.upgradeConversationDefaults()
            val settings = settingsStore.snapshot()
            bridge.initialize(settings, secrets.readApiKey())
            val messages = bridge.messages()
            val onboarding = bridge.onboardingStatus()
            val requireNetwork = secrets.readApiKey().isNotBlank()
            bridge.scheduled("pending").forEach { WorkScheduler.schedule(context, it, requireNetwork) }
            if (settings.personaConfigured && requireNetwork) planConversationCheckIn()
            WorkScheduler.scheduleMemoryMaintenance(context)
            val feedbackDue = settings.feedbackEnabled && bridge.feedbackDue()
            if (!ChatUpdates.history.publishIfCurrent(token) {
                _state.value = _state.value.copy(
                    ready = true,
                    messages = replyDelivery.mergeHistory(messages, _state.value.messages),
                    onboarding = onboarding,
                    onboardingVisible = messages.none { it.role == "user" } && !onboarding.finished,
                    periodicFeedbackDue = feedbackDue,
                    error = null,
                    modelConfigured = requireNetwork,
                )
            }) return@runCatching
            ScheduledDelivery.flushNotifications(context, bridge)
            startTurnRunner()
        }.onFailure {
            if (it is CancellationException) throw it
            ChatUpdates.history.publishIfCurrent(token) {
                _state.value = _state.value.copy(ready = true, error = readableError(it))
            }
        }
    }

    fun send(text: String) {
        val clean = text.trim()
        val image = _state.value.pendingImage
        if ((clean.isEmpty() && image == null) || _state.value.mutatingHistory || _state.value.loadingImage) return
        if (image != null && !canSendImage(_state.value.modelConfigured, _state.value.settings.modelSupportsVision)) {
            _state.value = _state.value.copy(error = "Selected model does not support images")
            return
        }
        composerChanged(false)
        val pending = ChatMessage(
            id = "msg_${UUID.randomUUID().toString().replace("-", "")}", conversationId = "default", role = "user",
            content = clean, timestamp = Instant.now().toString(), status = "pending", transient = true, imagePath = image,
        )
        _state.value = _state.value.copy(
            messages = _state.value.messages + pending,
            pendingImage = null,
            draftText = "",
            error = null,
        )
        val job = viewModelScope.launch {
            try {
                bridge.queueUserTurn(clean, pending.id, image.orEmpty())
                bridge.message(pending.id)?.let { saved ->
                    _state.value = _state.value.copy(messages = _state.value.messages.map { if (it.id == pending.id) saved else it })
                }
                bridge.scheduled("pending").forEach { WorkScheduler.schedule(context, it, _state.value.modelConfigured) }
                startTurnRunner()
            }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) {
                var saved: List<ChatMessage>? = null
                try {
                    // A schedule may already be saved even when dialogue generation fails.
                    bridge.scheduled("pending").forEach { item ->
                        WorkScheduler.schedule(context, item, secrets.readApiKey().isNotBlank())
                    }
                    saved = bridge.messages()
                } catch (cancelled: CancellationException) { throw cancelled }
                catch (_: Exception) { /* Preserve the visible message if recovery also fails. */ }
                val visible = _state.value.messages.map { if (it.id == pending.id) it.copy(status = "failed") else it }
                _state.value = _state.value.copy(messages = saved?.let { replyDelivery.mergeHistory(it, visible) } ?: visible,
                    error = readableError(error))
            }
        }
        enqueueJobs += job
        job.invokeOnCompletion { enqueueJobs.remove(job); turnWakeups.signal() }
    }

    private fun startTurnRunner() {
        turnWakeups.signal()
        if (turnRunner?.isActive == true) return
        turnRunner = viewModelScope.launch {
            while (true) {
                if (enqueueJobs.any { it.isActive } || sendJob?.isActive == true || _state.value.mutatingHistory) {
                    turnWakeups.await()
                    continue
                }
                val idleWait = composerWaitMillis(composerDraft, composerActivity,
                    SystemClock.elapsedRealtime(), _state.value.settings.turnIdleSeconds)
                if (idleWait != 0L) {
                    turnWakeups.await(idleWait)
                    continue
                }
                val pending = try { bridge.scheduled("pending").filter { it.topic.startsWith("reply:") } }
                catch (cancelled: CancellationException) { throw cancelled }
                catch (error: Exception) {
                    _state.value = _state.value.copy(error = readableError(error), preparingReply = false)
                    turnWakeups.await(15 * 60_000L)
                    continue
                }
                if (pending.isEmpty()) {
                    turnWakeups.await()
                    continue
                }
                val due = pending.minBy { java.time.OffsetDateTime.parse(it.scheduledAt).toInstant() }
                val dueWait = java.time.Duration.between(Instant.now(), java.time.OffsetDateTime.parse(due.scheduledAt).toInstant()).toMillis()
                if (dueWait > 0) {
                    // A bounded clock check also handles a manual wall-clock change.
                    turnWakeups.await(dueWait.coerceAtMost(60_000))
                    continue
                }
                try {
                    _state.value = _state.value.copy(preparingReply = true)
                    ScheduledDelivery.execute(context, bridge, due.id)
                } catch (cancelled: CancellationException) { throw cancelled }
                catch (error: Exception) {
                    _state.value = _state.value.copy(error = readableError(error), preparingReply = false)
                    // Preserve queued work, but do not hot-loop a failing provider.
                    turnWakeups.await(15 * 60_000L)
                } finally { _state.value = _state.value.copy(preparingReply = false) }
                turnWakeups.await(1000)
            }
        }
    }

    private suspend fun presentReply(id: String, token: Long, load: suspend () -> ChatMessage?) {
        replyDelivery.present(
            messageId = id, load = load, settings = { _state.value.settings },
            isCurrent = { ChatUpdates.history.token() == token },
            isVisible = { bubble -> _state.value.messages.any { it.id == bubble.id } },
            awaitComposer = {
                while (ChatUpdates.history.token() == token && !composerReady(composerDraft, composerActivity,
                        SystemClock.elapsedRealtime(), _state.value.settings.turnIdleSeconds)) delay(500)
            },
            publish = { message, bubble ->
                ChatUpdates.history.publishIfCurrent(token) {
                    val current = _state.value.messages.map { existing ->
                        when {
                            message.role == "user" && existing.id == message.id -> message
                            existing.id == message.replyToId || existing.id in message.replySourceIds -> existing.copy(status = "sent", error = null)
                            else -> existing
                        }
                    }
                    _state.value = _state.value.copy(messages =
                        if (current.none { it.id == bubble.id }) current + bubble else current)
                }
            },
        )
    }

    private suspend fun deliver(result: ChatResult, replacedMessageId: String? = null) {
        result.scheduledMessageId?.let { id ->
            bridge.scheduled("pending").firstOrNull { it.id == id }?.let {
                WorkScheduler.schedule(context, it, secrets.readApiKey().isNotBlank())
            }
        }
        if (result.deferred) {
            replacedMessageId?.let { bridge.deleteMessage(it) }
            val persisted = bridge.messages()
            _state.value = _state.value.copy(messages = replyDelivery.mergeHistory(persisted, _state.value.messages), preparingReply = false)
            return
        }
        val token = ChatUpdates.history.token() ?: return
        presentReply(result.assistantMessageId, token) {
            // Reserve the new reply before any suspending delete/refresh, so it
            // cannot leak into the UI before the first paced publication.
            replacedMessageId?.let { bridge.deleteMessage(it) }
            planConversationCheckIn()
            val persisted = bridge.messages()
            _state.value = _state.value.copy(
                messages = replyDelivery.mergeHistory(persisted, _state.value.messages), preparingReply = true)
            ChatMessage(
                id = result.assistantMessageId, conversationId = "default",
                role = "assistant", content = result.response, timestamp = Instant.now().toString(),
                replyToId = result.userMessageId, transient = true,
                persistedMessageId = result.assistantMessageId,
                deliveryParts = result.deliveryParts.ifEmpty { listOf(DeliveryPart(result.response, 0)) },
            )
        }
        _state.value = _state.value.copy(
            preparingReply = false,
            periodicFeedbackDue = _state.value.settings.feedbackEnabled && bridge.feedbackDue(),
        )
    }

    fun retry(message: ChatMessage) {
        if (sendJob?.isActive == true || _state.value.mutatingHistory) return
        if (message.transient && message.role == "user") {
            sendJob = launchUiOperation {
                composerChanged(composerDraft)
                bridge.queueUserTurn(message.content, message.id, message.imagePath.orEmpty())
                val saved = bridge.message(message.id) ?: return@launchUiOperation
                _state.value = _state.value.copy(messages = _state.value.messages.map { if (it.id == message.id) saved else it })
                bridge.scheduled("pending").forEach { WorkScheduler.schedule(context, it, _state.value.modelConfigured) }
                startTurnRunner()
            }
            sendJob?.invokeOnCompletion { turnWakeups.signal() }
            return
        }
        val target = if (message.role == "user") message.id else message.replyToId ?: return
        _state.value = _state.value.copy(preparingReply = true, feedbackTarget = null, error = null)
        sendJob = viewModelScope.launch {
            try {
                val result = bridge.retryMessage(target)
                deliver(result, message.takeIf { it.role == "assistant" }?.persistedId())
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { _state.value = _state.value.copy(error = readableError(error)) }
            finally { _state.value = _state.value.copy(preparingReply = false) }
        }
        sendJob?.invokeOnCompletion { turnWakeups.signal() }
    }

    fun delete(message: ChatMessage) {
        mutateHistory {
            if (message.transient && message.role == "user" && bridge.message(message.id) == null) {
                message.imagePath?.let { PickedImageStore.removeDraft(context, it) }
                _state.value = _state.value.copy(messages = _state.value.messages.filterNot { it.id == message.id })
                return@mutateHistory
            }
            run {
                val result = bridge.deleteMessage(message.persistedId())
                val scheduled = result.optJSONArray("scheduled_ids")
                repeat(scheduled?.length() ?: 0) { index ->
                    WorkScheduler.cancel(context, scheduled!!.getString(index))
                }
                val removed = result.optJSONArray("message_ids")
                repeat(removed?.length() ?: 0) { index ->
                    com.adaptive.companion.notifications.NotificationHelper.cancelMessage(context, removed!!.getString(index))
                }
            }
            _state.value = _state.value.copy(messages = bridge.messages())
        }
    }

    private fun mutateHistory(action: suspend () -> Unit) {
        if (_state.value.mutatingHistory) return
        _state.value = _state.value.copy(mutatingHistory = true, feedbackTarget = null, periodicFeedbackDue = false)
        ChatUpdates.history.beginChange()
        viewModelScope.launch {
            try {
                sendJob?.cancelAndJoin()
                sendJob = null
                turnRunner?.cancelAndJoin()
                turnRunner = null
                imageJob?.cancelAndJoin()
                imageJob = null
                enqueueJobs.toList().forEach { it.cancelAndJoin() }
                action()
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { _state.value = _state.value.copy(error = readableError(error)) }
            finally {
                ChatUpdates.history.endChange()
                _state.value = _state.value.copy(mutatingHistory = false, preparingReply = false)
                if (_state.value.ready) startTurnRunner()
            }
        }
    }

    fun selectMessage(message: ChatMessage?) { _state.value = _state.value.copy(feedbackTarget = message) }

    fun closeInterview() { _state.value = _state.value.copy(onboardingVisible = false) }

    fun switchRole(item: JSONObject, onSaved: () -> Unit = {}) {
        mutateHistory {
            val previous = settingsStore.snapshot()
            val oldWork = bridge.scheduled("pending")
            bridge.roles() // Preserve the old role's latest canon before switching.
            oldWork.forEach { WorkScheduler.cancel(context, it.id) }
            oldWork.filter { it.topic.startsWith("reply:") }.forEach { bridge.cancelScheduled(it.id) }
            removeImage()
            composerChanged(false)
            val role = PersonaSettings.parse(item.getJSONObject("role").toString()).copy(characterId = item.getString("id"))
            try {
                bridge.initialize(previous.copy(persona = role, personaConfigured = true), secrets.readApiKey())
                val status = bridge.skipOnboarding()
                val history = bridge.messages()
                settingsStore.savePersona(role)
                _state.value = _state.value.copy(settings = previous.copy(persona = role, personaConfigured = true),
                    messages = history, draftText = "", onboarding = status,
                    onboardingVisible = false, error = null)
            } catch (error: Exception) {
                bridge.initialize(previous, secrets.readApiKey())
                bridge.scheduled("pending").forEach { WorkScheduler.schedule(context, it, _state.value.modelConfigured) }
                throw error
            }
            // Once settings commit, OS failures must not revert only the backend.
            com.adaptive.companion.notifications.NotificationHelper.clearMessages(context)
            bridge.scheduled("pending").forEach { WorkScheduler.schedule(context, it, _state.value.modelConfigured) }
            onSaved()
        }
    }

    fun retryInitialization() { viewModelScope.launch { initialize() } }

    fun feedback(kind: String) {
        val target = _state.value.feedbackTarget ?: return
        _state.value = _state.value.copy(feedbackTarget = null)
        viewModelScope.launch {
            runCatching { bridge.feedback(target.persistedId(), kind) }
                .onFailure { _state.value = _state.value.copy(error = readableError(it)) }
        }
    }

    fun dismissPeriodicFeedback() {
        _state.value = _state.value.copy(periodicFeedbackDue = false)
        viewModelScope.launch { bridge.dismissFeedback() }
    }

    fun submitPeriodicFeedback(natural: Int, comfort: Int, length: String, initiative: String) {
        val assistant = _state.value.messages.lastOrNull { it.role == "assistant" }
        _state.value = _state.value.copy(periodicFeedbackDue = false)
        viewModelScope.launch {
            if (assistant != null) {
                val id = assistant.persistedId()
                if (length == "too_short") bridge.feedback(id, "too_short")
                if (length == "too_long") bridge.feedback(id, "too_long")
                if (initiative == "too_much") bridge.feedback(id, "too_much_initiative")
                if (initiative == "too_little") bridge.feedback(id, "too_little_initiative")
                if (comfort <= 2) bridge.feedback(id, "too_cold")
                if (natural >= 4 && comfort >= 4 && length == "just_right") bridge.feedback(id, "good")
            }
            bridge.completePeriodicFeedback()
        }
    }

    fun saveProvider(settings: AppSettings, apiKey: String) {
        launchUiOperation {
            secrets.saveApiKey(apiKey)
            settingsStore.saveProvider(settings)
            bridge.initialize(settingsStore.snapshot(), secrets.readApiKey())
            _state.value = _state.value.copy(error = null, modelConfigured = apiKey.isNotBlank())
            if (apiKey.isNotBlank()) planConversationCheckIn()
        }
    }

    fun updateToggle(name: String, value: Boolean) {
        launchUiOperation {
            settingsStore.setBoolean(name, value)
            if (toggleRequiresCoreRestart(name)) {
                bridge.initialize(settingsStore.snapshot(), secrets.readApiKey())
            }
            if (name == "feedback" && !value) {
                _state.value = _state.value.copy(periodicFeedbackDue = false)
            }
        }
    }

    fun setDarkTheme(value: Boolean) = viewModelScope.launch { settingsStore.setDarkTheme(value) }

    fun setLanguage(code: String) = launchUiOperation {
            settingsStore.setLanguage(code)
            bridge.initialize(settingsStore.snapshot(), secrets.readApiKey())
            com.adaptive.companion.notifications.NotificationHelper.createChannel(context)
    }

    fun savePersona(persona: PersonaSettings, onSaved: () -> Unit = {}) {
        if (_state.value.savingPersona) return
        _state.value = _state.value.copy(savingPersona = true, error = null)
        viewModelScope.launch {
            try {
                val previous = settingsStore.snapshot()
                bridge.initialize(previous.copy(persona = persona.sanitized(), personaConfigured = true), secrets.readApiKey())
                settingsStore.savePersona(persona)
                // User profile questions are optional; never block chat on the old questionnaire.
                val status = if (!previous.personaConfigured) bridge.skipOnboarding() else bridge.onboardingStatus()
                _state.value = _state.value.copy(onboarding = status, onboardingVisible = false)
                onSaved()
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Exception) {
                _state.value = _state.value.copy(error = "Role save failed")
            } finally { _state.value = _state.value.copy(savingPersona = false) }
        }
    }

    suspend fun saveInterviewDraft(answers: Map<String, Any?>, resumeIndex: Int, fullInterview: Boolean) {
        val status = bridge.submitOnboarding(answers, false, resumeIndex, fullInterview)
        _state.value = _state.value.copy(onboarding = status)
    }

    suspend fun previewInterview(answers: Map<String, Any?>, name: String = ""): JSONObject {
        val settings = settingsStore.snapshot()
        val draft = bridge.previewInterview(answers, settings.language, name)
        val proposed = PersonaSettings.parse(draft.getJSONObject("persona").toString())
        val retained = if (settings.personaConfigured) retainGeneratedCharacter(settings.persona, proposed, name) else null
        if (retained != null) {
            draft.put("persona", retained.json(settings.language))
            draft.put("method", "saved model character")
        }
        return draft
    }

    suspend fun generateInterview(answers: Map<String, Any?>, name: String = ""): JSONObject =
        bridge.generateInterview(answers, settingsStore.snapshot().language, name)

    fun saveInterview(answers: Map<String, Any?>, name: String, proposal: String?, onSaved: () -> Unit) {
        if (_state.value.savingPersona || !requiredInterviewComplete(answers)) return
        _state.value = _state.value.copy(savingPersona = true, error = null)
        viewModelScope.launch {
            try {
                val previous = settingsStore.snapshot()
                // Preview validates the required ten and makes no provider request.
                val draft = previewInterview(answers, name)
                val foundation = PersonaSettings.parse(draft.getJSONObject("persona").toString())
                val selectedProposal = proposal?.let(::JSONObject)
                val selected = selectedProposal?.optJSONObject("persona")?.let { PersonaSettings.parse(it.toString()) }
                // A confirmed model draft may change character text, never the
                // interview/user data or learned preference baseline.
                val persona = confirmGeneratedCharacter(foundation, selected, name).copy(characterId = previous.persona.characterId)
                val status = bridge.submitOnboarding(answers, true)
                if (selected?.generationMethod == "model" && selectedProposal.has("distillation_basis")) {
                    bridge.applyInterviewDistillation(selectedProposal.toString())
                }
                bridge.initialize(previous.copy(persona = persona, personaConfigured = true), secrets.readApiKey())
                settingsStore.savePersona(persona)
                _state.value = _state.value.copy(onboarding = status, onboardingVisible = false)
                onSaved()
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Exception) { _state.value = _state.value.copy(error = "Role save failed")
            } finally { _state.value = _state.value.copy(savingPersona = false) }
        }
    }

    fun setBackgroundMode(mode: String) = viewModelScope.launch { settingsStore.setBackgroundMode(mode) }

    fun saveConversation(seconds: Int, zone: String, length: Float) = launchUiOperation {
        settingsStore.saveConversation(seconds, zone, length)
        bridge.initialize(settingsStore.snapshot(), secrets.readApiKey())
        bridge.setPreference("reply_length", length)
    }

    fun saveAdvanced(settings: AppSettings) {
        launchUiOperation {
            settingsStore.saveAdvanced(settings)
            bridge.initialize(settingsStore.snapshot(), secrets.readApiKey())
        }
    }

    fun clearUserData() {
        mutateHistory {
            removeImage()
            _state.value.messages.filter { it.transient && it.role == "user" }.forEach { message ->
                message.imagePath?.let { PickedImageStore.removeDraft(context, it) }
            }
            bridge.scheduled().forEach { WorkScheduler.cancel(context, it.id) }
            bridge.clearUserData()
            com.adaptive.companion.notifications.NotificationHelper.clearMessages(context)
            val onboarding = bridge.onboardingStatus()
            _state.value = _state.value.copy(
                messages = emptyList(), onboarding = onboarding,
                draftText = "",
                onboardingVisible = true, error = null,
            )
            composerChanged(false)
        }
    }

    fun startOnboarding() {
        viewModelScope.launch {
            val onboarding = bridge.beginOnboarding()
            _state.value = _state.value.copy(onboarding = onboarding, onboardingVisible = true)
        }
    }

    fun submitOnboarding(answers: Map<String, Any?>, finish: Boolean) {
        viewModelScope.launch {
            runCatching { bridge.submitOnboarding(answers, finish) }
                .onSuccess { status ->
                    _state.value = _state.value.copy(
                        onboarding = status,
                        onboardingVisible = status.state != "completed",
                    )
                }
                .onFailure { _state.value = _state.value.copy(error = readableError(it)) }
        }
    }

    fun skipOnboarding() {
        viewModelScope.launch {
            val status = bridge.skipOnboarding()
            _state.value = _state.value.copy(onboarding = status, onboardingVisible = false)
        }
    }

    suspend fun testConnection(settings: AppSettings, apiKey: String): String {
        if (apiKey.isBlank() || settings.baseUrl.isBlank()) return "Base URL and API key are required"
        return try {
            val result = bridge.testConnection(settings, apiKey)
            if (result.optBoolean("ok")) "Connection successful" else "Connection failed"
        } catch (cancelled: CancellationException) { throw cancelled
        } catch (_: Exception) { "Connection failed" }
    }

    suspend fun aulJson(): String = bridge.aulJson()
    suspend fun debugJson(kind: String): String = bridge.debugJson(kind)
    suspend fun maintainMemory() = bridge.maintainMemory()
    suspend fun archives(kind: String) = bridge.archives(kind)
    suspend fun archiveDetail(id: String, offset: Int) = bridge.archiveDetail(id, offset)
    suspend fun searchMemory(query: String) = bridge.searchMemory(query)
    suspend fun scheduled(status: String = ""): List<ScheduledIntent> = bridge.scheduled(status)
    fun setPreference(key: String, value: Float) = viewModelScope.launch { bridge.setPreference(key, value) }
    fun runScheduled(id: String) = launchUiOperation {
        ScheduledDelivery.execute(context, bridge, id, force = true)
    }
    fun cancelScheduled(id: String) = launchUiOperation {
        bridge.cancelScheduled(id)
        WorkScheduler.cancel(context, id)
        refreshScheduledHistory()
    }
    fun deleteScheduled(id: String) = launchUiOperation {
        bridge.deleteScheduled(id)
        WorkScheduler.cancel(context, id)
        refreshScheduledHistory()
    }
    private suspend fun refreshScheduledHistory() {
        val token = ChatUpdates.history.token() ?: return
        val saved = bridge.messages()
        ChatUpdates.history.publishIfCurrent(token) {
            _state.value = _state.value.copy(messages = replyDelivery.mergeHistory(saved, _state.value.messages))
        }
        turnWakeups.signal()
    }
    fun clearError() { _state.value = _state.value.copy(error = null) }
    fun reportBackgroundError(text: String) { _state.value = _state.value.copy(error = text) }

    private fun launchUiOperation(action: suspend () -> Unit) = viewModelScope.launch {
        try { action() }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (error: Exception) { _state.value = _state.value.copy(error = readableError(error)) }
    }

    private suspend fun planConversationCheckIn() {
        try {
            bridge.planCheckIn()?.let { WorkScheduler.schedule(context, it, requireNetwork = true) }
        } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { /* Housekeeping must not turn a successful reply into a failure. */ }
    }

    private fun readableError(error: Throwable): String {
        val text = error.message.orEmpty()
        return when {
            "four images" in text -> "At most four images per turn"
            "support images" in text -> "Selected model does not support images"
            "401" in text || "403" in text -> "API key or provider access was rejected."
            "429" in text -> "The provider is busy or rate-limited. Try again shortly."
            "timeout" in text.lowercase() -> "The request timed out. Your message was saved; you can retry."
            "network" in text.lowercase() || "resolve host" in text.lowercase() -> "No network connection. Your message was saved."
            else -> "Something went wrong. Your chat history is safe."
        }
    }

    suspend fun createScheduledMessage(text: String, whenAt: String, generate: Boolean): JSONObject {
        val result = bridge.scheduleCustom(text, whenAt, generate)
        parseScheduled("[$result]").firstOrNull()
            ?.let { WorkScheduler.schedule(context, it, generate) }
        return result
    }

    companion object {
        fun factory(application: Application) = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                CompanionViewModel(application) as T
        }
    }
}
