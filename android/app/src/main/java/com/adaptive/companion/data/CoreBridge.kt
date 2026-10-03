package com.adaptive.companion.data

import android.content.Context
import com.adaptive.companion.AppVisibility
import com.adaptive.companion.notifications.NotificationHelper
import com.chaquo.python.Python
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.util.TimeZone

class CoreBridge(private val context: Context) {
    private val module get() = Python.getInstance().getModule("adaptive_companion.android_bridge")

    suspend fun initialize(settings: AppSettings, apiKey: String) = pythonCall { initializeLocked(settings, apiKey) }

    private fun initializeLocked(settings: AppSettings, apiKey: String) {
        globalInitialized = false
        val provider = JSONObject()
            .put("base_url", settings.baseUrl)
            .put("api_key", apiKey)
            .put("dialogue_model", settings.dialogueModel)
            .put("observer_model", settings.observerModel)
            .put("memory_model", settings.memoryModel)
            .put("temperature", settings.temperature.toDouble())
            .put("top_p", settings.topP.toDouble())
            .put("max_tokens", settings.maxTokens)
            .put("timeout", settings.timeoutSeconds)
            .put("retry", settings.retryCount)
            .put("supports_vision", settings.modelSupportsVision)
        val config = JSONObject()
            .put("role_library", File(context.filesDir, "roles").absolutePath)
            .put("persona", settings.persona.json(settings.language))
            .put("memory_utc_offset_minutes", TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60000)
            .put("memory_zone_name", TimeZone.getDefault().id)
            .put("provider", provider)
            .put("turn_idle_seconds", settings.turnIdleSeconds)
            .put("attachment_root", File(context.filesDir, roleImageDirectory(settings.persona)).absolutePath)
            .put("daily_reply_length", settings.dailyReplyLength.toDouble())
            .put("observer_enabled", settings.observerEnabled)
            .put("learning", JSONObject()
                .put("enabled", settings.learningEnabled)
                .put("weak_rate", settings.weakEvidenceRate.toDouble())
                .put("explicit_rate", settings.explicitEvidenceRate.toDouble())
                .put("correction_rate", settings.correctionEvidenceRate.toDouble()))
            .put("context_budget", settings.contextBudget)
            .put("summary_message_threshold", settings.summaryMessageThreshold)
            .put("summary_token_threshold", settings.summaryTokenThreshold)
            .put("delivery", JSONObject()
                .put("enabled", settings.naturalTiming)
                .put("greeting_delay_enabled", settings.greetingDelayEnabled)
                .put("base_delay_ms", settings.baseDelayMs)
                .put("delay_per_character_ms", settings.delayPerCharacterMs)
                .put("random_jitter_ms", settings.jitterMs)
                .put("split_probability", settings.splitProbability.toDouble())
                .put("minimum_delay_ms", settings.minDelayMs)
                .put("maximum_delay_ms", settings.maxDelayMs))
            .put("proactive", JSONObject()
                .put("enabled", settings.proactiveEnabled)
                .put("max_per_day", settings.maxProactivePerDay)
                .put("minimum_interval_hours", settings.proactiveMinimumHours)
                .put("quiet_start_hour", settings.quietStart)
                .put("quiet_end_hour", settings.quietEnd)
                .put("importance_threshold", settings.proactiveThreshold.toDouble()))
        val database = File(context.filesDir, roleDatabaseName(settings.persona)).absolutePath
        module.callAttr("initialize", database, config.toString())
        globalInitialized = true
        latestComposerDraft?.let { module.callAttr("note_composer", it) }
    }

    suspend fun ensureInitialized(settingsStore: SettingsStore, secrets: SecureSecretStore) {
        if (globalInitialized) return
        val settings = settingsStore.snapshot()
        val apiKey = secrets.readApiKey()
        pythonCall { if (!globalInitialized) initializeLocked(settings, apiKey) }
    }

    suspend fun sendMessage(text: String, conversationId: String = "default", messageId: String = ""): ChatResult =
        pythonCall {
            parseChatResult(module.callAttr("send_message", text, conversationId, messageId).toString())
        }

    suspend fun retryMessage(messageId: String): ChatResult = pythonCall {
        parseChatResult(module.callAttr("retry_message", messageId).toString())
    }

    fun noteComposer(hasDraft: Boolean) {
        // This tiny in-memory call deliberately bypasses the model mutex.
        latestComposerDraft = hasDraft
        if (globalInitialized) module.callAttr("note_composer", hasDraft)
    }

    suspend fun queueUserTurn(text: String, messageId: String, imagePath: String): JSONObject = pythonCall {
        JSONObject(module.callAttr("queue_user_turn", text, messageId, imagePath).toString())
    }

    suspend fun messages(conversationId: String = "default"): List<ChatMessage> =
        pythonCall {
            parseMessages(module.callAttr("list_messages", conversationId, 300).toString())
        }

    suspend fun roles(): JSONArray = pythonCall { JSONArray(module.callAttr("list_roles").toString()) }
    suspend fun previewRole(bytes: ByteArray): JSONObject = pythonCall {
        JSONObject(module.callAttr("preview_role", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)).toString())
    }
    suspend fun addRole(preview: JSONObject): JSONObject = pythonCall {
        JSONObject(module.callAttr("add_role", preview.toString()).toString())
    }
    suspend fun exportRole(id: String): ByteArray = pythonCall {
        android.util.Base64.decode(module.callAttr("export_role", id).toString(), android.util.Base64.DEFAULT)
    }

    suspend fun message(messageId: String): ChatMessage? = pythonCall {
        parseMessage(module.callAttr("get_message", messageId).toString())
    }

    suspend fun deleteMessage(messageId: String): JSONObject = pythonCall {
        JSONObject(module.callAttr("delete_message", messageId).toString())
    }

    suspend fun feedback(messageId: String, kind: String) = pythonCall {
        module.callAttr("submit_feedback", messageId, kind, "null")
    }

    suspend fun feedbackDue(): Boolean = pythonCall {
        module.callAttr("feedback_due").toBoolean()
    }

    suspend fun dismissFeedback() = pythonCall {
        module.callAttr("dismiss_feedback")
    }

    suspend fun completePeriodicFeedback() = pythonCall {
        module.callAttr("complete_periodic_feedback")
    }

    suspend fun aulJson(): String = pythonCall {
        module.callAttr("get_aul").toString()
    }

    suspend fun onboardingStatus(): OnboardingStatus = pythonCall {
        parseOnboarding(module.callAttr("onboarding_status").toString())
    }

    suspend fun beginOnboarding(): OnboardingStatus = pythonCall {
        parseOnboarding(module.callAttr("begin_onboarding").toString())
    }

    suspend fun submitOnboarding(answers: Map<String, Any?>, finish: Boolean,
        resumeIndex: Int? = null, fullInterview: Boolean? = null): OnboardingStatus =
        pythonCall {
            val payload = JSONObject().apply { answers.forEach { (key, value) -> put(key, value ?: JSONObject.NULL) } }
            val progress = JSONObject().apply {
                resumeIndex?.let { put("resume_index", it) }
                fullInterview?.let { put("full_interview", it) }
            }
            parseOnboarding(module.callAttr("submit_onboarding", payload.toString(), finish, progress.toString()).toString())
        }

    suspend fun skipOnboarding(): OnboardingStatus = pythonCall {
        parseOnboarding(module.callAttr("skip_onboarding").toString())
    }

    suspend fun previewInterview(answers: Map<String, Any?>, language: String, name: String = ""): JSONObject = pythonCall {
        val payload = JSONObject().apply { answers.forEach { (key, value) -> put(key, value ?: JSONObject.NULL) } }
        JSONObject(module.callAttr("preview_interview", payload.toString(), language, name).toString())
    }

    suspend fun generateInterview(answers: Map<String, Any?>, language: String, name: String = ""): JSONObject = pythonCall {
        val payload = JSONObject().apply { answers.forEach { (key, value) -> put(key, value ?: JSONObject.NULL) } }
        JSONObject(module.callAttr("generate_interview", payload.toString(), language, name).toString())
    }

    suspend fun applyInterviewDistillation(proposal: String) = pythonCall {
        module.callAttr("apply_interview_distillation", proposal)
    }

    suspend fun scheduleCustom(text: String, whenAt: String, generate: Boolean): JSONObject = pythonCall {
        JSONObject(module.callAttr("schedule_custom", text, whenAt, generate).toString())
    }

    suspend fun scheduledQueue(): List<ScheduledIntent> = pythonCall {
        parseScheduled(module.callAttr("scheduled_queue").toString())
    }

    suspend fun planCheckIn(): ScheduledIntent? = pythonCall {
        val raw = module.callAttr("plan_check_in").toString()
        if (raw == "null") null else parseScheduled("[$raw]").firstOrNull()
    }

    suspend fun setPreference(key: String, value: Float): String = pythonCall {
        module.callAttr("set_preference", key, value.toDouble()).toString()
    }

    suspend fun debugJson(kind: String): String = pythonCall {
        module.callAttr("get_debug", kind).toString()
    }

    suspend fun maintainMemory(): JSONObject = pythonCall {
        JSONObject(module.callAttr("maintain_memory").toString())
    }

    suspend fun archives(kind: String): JSONArray = pythonCall {
        JSONArray(module.callAttr("list_archives", kind, 100).toString())
    }

    suspend fun archiveDetail(id: String, offset: Int = 0): JSONObject? = pythonCall {
        val value = module.callAttr("archive_detail", id, offset, 50).toString()
        if (value == "null") null else JSONObject(value)
    }

    suspend fun searchMemory(query: String): JSONArray = pythonCall {
        JSONArray(module.callAttr("search_memory", query, 20).toString())
    }

    suspend fun scheduled(status: String = ""): List<ScheduledIntent> = pythonCall {
        parseScheduled(module.callAttr("list_scheduled", status).toString())
    }

    suspend fun executeScheduled(id: String, force: Boolean = false): JSONObject {
        val settings = SettingsStore(context).snapshot()
        val allowCasual = force || AppVisibility.isForeground ||
            (settings.notificationsEnabled && NotificationHelper.canNotify(context, settings.sound, settings.vibration))
        return pythonCall { JSONObject(module.callAttr("execute_scheduled", id, force, allowCasual).toString()) }
    }

    suspend fun pendingNotifications(limit: Int = 20): JSONArray = pythonCall {
        JSONArray(module.callAttr("pending_notifications", limit).toString())
    }

    suspend fun finishNotification(messageId: String, status: String): Boolean = pythonCall {
        module.callAttr("finish_notification", messageId, status).toBoolean()
    }

    suspend fun cancelScheduled(id: String) = pythonCall {
        module.callAttr("cancel_scheduled", id)
    }

    suspend fun deleteScheduled(id: String) = pythonCall {
        module.callAttr("delete_scheduled", id)
    }

    suspend fun clearUserData() = pythonCall {
        module.callAttr("clear_user_data")
        // Also remove abandoned private drafts after a prior process death.
        File(context.filesDir, "chat_images").listFiles().orEmpty()
            .filter { it.isFile && it.extension == "jpg" }
            .forEach { PickedImageStore.removeDraft(context, it.absolutePath) }
    }

    suspend fun testConnection(settings: AppSettings, apiKey: String): JSONObject =
        pythonCall {
            val config = JSONObject()
                .put("base_url", settings.baseUrl)
                .put("api_key", apiKey)
                .put("timeout", settings.timeoutSeconds)
            JSONObject(module.callAttr("test_connection", config.toString()).toString())
        }

    private suspend fun <T> pythonCall(block: () -> T): T = withContext(Dispatchers.IO) {
        pythonMutex.withLock {
            val zoneName = SettingsStore(context).snapshot().timeZone
            val zone = runCatching { java.time.ZoneId.of(zoneName) }.getOrElse { java.time.ZoneId.systemDefault() }
            module.callAttr("set_clock", java.time.ZonedDateTime.now(zone).toOffsetDateTime().toString(), zone.id)
            block()
        }
    }

    companion object {
        private val pythonMutex = Mutex()
        @Volatile private var globalInitialized = false
        @Volatile private var latestComposerDraft: Boolean? = null
    }
}
