package com.adaptive.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.mapSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.adaptive.companion.BuildConfig
import com.adaptive.companion.data.AdminAuthStore
import com.adaptive.companion.data.AppSettings
import com.adaptive.companion.data.ModelChoice
import com.adaptive.companion.data.resetGenerationParameters
import com.adaptive.companion.data.NumericSettingsDrafts
import com.adaptive.companion.data.NumericInputKind
import com.adaptive.companion.data.validNumericInput
import com.adaptive.companion.data.ScheduledIntent
import com.adaptive.companion.scheduler.BackgroundPolicy
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CancellationException
import org.json.JSONObject

enum class Screen { CHAT, SETTINGS, ABOUT, PROVIDER, AUL, MEMORY, ARCHIVES, SCHEDULER, ADVANCED, PERSONA, SCHEDULE_MESSAGES }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    settings: AppSettings,
    onboardingProgress: String,
    advancedVisible: Boolean,
    onBack: () -> Unit,
    onNavigate: (Screen) -> Unit,
    onToggle: (String, Boolean) -> Unit,
    onTheme: (Boolean) -> Unit,
    onClear: () -> Unit,
    onOnboarding: () -> Unit,
    onBackgroundMode: (String) -> Unit,
    onLanguage: (String) -> Unit,
    notificationsAllowed: Boolean,
    onNotificationSettings: () -> Unit,
    onConversation: (Int, String, Float) -> Unit,
) {
    var confirmClear by remember { mutableStateOf(false) }
    var explainGoogle by remember { mutableStateOf(false) }
    var confirmResident by remember { mutableStateOf(false) }
    var seconds by remember(settings.turnIdleSeconds) { mutableIntStateOf(settings.turnIdleSeconds) }
    var zone by remember(settings.timeZone) { mutableStateOf(settings.timeZone) }
    var dailyLength by remember(settings.dailyReplyLength) { mutableFloatStateOf(settings.dailyReplyLength) }
    val validZone = zone.isBlank() || runCatching { java.time.ZoneId.of(zone.trim()) }.isSuccess
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Settings")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()),
        ) {
            Section("Language")
            LanguagePicker(settings.language, onLanguage)
            Text(tr("Language help"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            SettingRow("Companion role", if (settings.persona.generationMethod == "pending") tr("Character awaiting model")
                else settings.persona.name.ifBlank { tr("Companion") }) { onNavigate(Screen.PERSONA) }
            Text(tr("Role transparency"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            Section("Conversation")
            Column(Modifier.padding(horizontal = 18.dp)) {
                Text(tr("Turn wait seconds", seconds))
                Slider(seconds.toFloat(), { seconds = it.toInt() }, valueRange = 10f..60f, steps = 49)
                Text(tr("Turn wait help"), style = MaterialTheme.typography.bodySmall)
                Text(tr("Daily reply length"))
                Slider(dailyLength, { dailyLength = it })
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(tr("Short")); Text(tr("Long"))
                }
                Text(tr("Daily length help"), style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(zone, { zone = it }, Modifier.fillMaxWidth(), label = { Text(tr("Time zone")) },
                    isError = !validZone, singleLine = true)
                Text(tr("Time zone help"), style = MaterialTheme.typography.bodySmall)
                Button(onClick = { onConversation(seconds, zone.trim(), dailyLength) }, enabled = validZone) { Text(tr("Save conversation settings")) }
            }
            SettingSwitch("Humanized reply timing", settings.naturalTiming) { onToggle("timing", it) }
            Text(tr("Reply timing help"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            SettingSwitch("开场白稍后回复（目标1–3分钟）", settings.greetingDelayEnabled) { onToggle("greeting_delay", it) }
            Text(tr("仅独立的‘在吗／有空吗’。正在聊天、求助或含实际问题时不额外等待；可关闭。"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            Text(tr("Image upload notice"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            SettingSwitch("Feedback", settings.feedbackEnabled) { onToggle("feedback", it) }
            SettingRow("Build or update my AUL", onboardingProgress, onOnboarding)
            SettingRow("记忆日历", "按日、周、月查看；搜索过去的聊天") { onNavigate(Screen.ARCHIVES) }
            Section("Notifications")
            SettingSwitch("Notifications", settings.notificationsEnabled) { onToggle("notifications", it) }
            if (settings.notificationsEnabled && !notificationsAllowed) {
                Text(tr("Notification permission hint"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            }
            SettingRow("System notification settings", if (notificationsAllowed) tr("Notifications allowed")
                else tr("Notifications blocked"), onNotificationSettings)
            SettingSwitch("Sound", settings.sound) { onToggle("sound", it) }
            SettingSwitch("Vibration", settings.vibration) { onToggle("vibration", it) }
            SettingSwitch("Proactive messages", settings.proactiveEnabled) { onToggle("proactive", it) }
            SettingRow("Scheduled messages", "Schedule messages help") { onNavigate(Screen.SCHEDULE_MESSAGES) }
            SettingRow("Quiet hours", "${settings.quietStart}:00 – ${settings.quietEnd}:00") {
                if (advancedVisible) onNavigate(Screen.ADVANCED)
            }
            Section("后台运行")
            SettingSwitch("常驻后台", settings.backgroundMode == BackgroundPolicy.RESIDENT) {
                if (it) confirmResident = true else onBackgroundMode(BackgroundPolicy.SYSTEM)
            }
            Text(tr("关闭后使用系统省电调度，可能延后。常驻会显示持续通知、额外耗电，仍可能被系统停止；重开应用会按选择恢复。"), Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
            SettingRow("Google 推送（FCM）", "尚未接入：需要 Firebase 项目和可信服务端，不会自动检测Google服务") { explainGoogle = true }
            if (advancedVisible) {
                Section(if (BuildConfig.IS_FULL) "Developer" else "Administrator")
                SettingRow("Provider and models", settings.dialogueModel) { onNavigate(Screen.PROVIDER) }
                SettingRow("AUL inspector", "Profile, state and preferences") { onNavigate(Screen.AUL) }
                SettingRow("Memory and audit", "Raw, Evidence, summaries, policy") { onNavigate(Screen.MEMORY) }
                SettingRow("Scheduler debug", "Pending, sent, cancelled, expired") { onNavigate(Screen.SCHEDULER) }
                SettingRow("Core and timing", "Budgets, thresholds and delivery") { onNavigate(Screen.ADVANCED) }
            }
            Section("App")
            SettingSwitch("Dark theme", settings.darkTheme == true, onTheme)
            SettingRow("Clear chat", "Deletes local chat, memory and learned profile") { confirmClear = true }
            SettingRow("About", "Version and privacy") { onNavigate(Screen.ABOUT) }
        }
    }
    if (confirmResident) AlertDialog(
        onDismissRequest = { confirmResident = false }, title = { Text(tr("启用可停止的常驻模式？")) },
        text = { Text(tr("应用会显示常驻通知并等待已保存的回复／关心待办。不是防杀保活，也不保证准点。你可以在设置或常驻通知里随时停止。")) },
        confirmButton = { TextButton(onClick = { confirmResident = false; onBackgroundMode(BackgroundPolicy.RESIDENT) }) { Text(tr("启用")) } },
        dismissButton = { TextButton(onClick = { confirmResident = false }) { Text(tr("取消")) } },
    )
    if (explainGoogle) AlertDialog(
        onDismissRequest = { explainGoogle = false }, title = { Text(tr("为什么还没有 Google 推送？")) },
        text = { Text(tr("FCM只负责将服务端消息送到手机。记忆、计时和AI回复还需要在线服务端，并处理设备令牌、认证和数据同步。目前是本地运行版本，没有这些服务，所以先提供省电调度和常驻两种模式。")) },
        confirmButton = { TextButton(onClick = { explainGoogle = false }) { Text(tr("明白")) } },
    )
    if (confirmClear) AlertDialog(
        onDismissRequest = { confirmClear = false },
        title = { Text(tr("Clear all companion data?")) },
        text = { Text(tr("Chat, memory, scheduled messages and learned preferences will be deleted. Provider and app settings are kept.")) },
        confirmButton = { TextButton(onClick = { confirmClear = false; onClear() }) { Text(tr("Clear")) } },
        dismissButton = { TextButton(onClick = { confirmClear = false }) { Text(tr("Cancel")) } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutScreen(
    adminAuth: AdminAuthStore,
    onBack: () -> Unit,
    onUnlocked: () -> Unit,
) {
    var taps by remember { mutableIntStateOf(0) }
    var showPassword by remember { mutableStateOf(false) }
    var password by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var verifying by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Scaffold(topBar = { TopAppBar(title = { Text(tr("About")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(24.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Text(tr("OpenWoven"), style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            Text(tr("OpenWoven is an AI system, not a human. It can remember information you share and adapt its conversation style. Natural delivery timing does not represent a real person typing."))
            Text(tr("Your conversation database stays in this app's private storage unless your configured AI provider receives a prompt."))
            Text(
                tr("Version {0}", BuildConfig.VERSION_NAME),
                modifier = Modifier.clickable {
                    taps++
                    if (!BuildConfig.IS_FULL && taps >= 7) showPassword = true
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    if (showPassword) {
        AlertDialog(
            onDismissRequest = { if (!verifying) { showPassword = false; password = "" } },
            title = { Text(tr("Administrator access")) },
            text = {
                Column {
                    OutlinedTextField(
                        value = password, onValueChange = { password = it },
                        label = { Text(tr("Password")) }, visualTransformation = PasswordVisualTransformation(),
                    )
                    error?.let { Text(tr(it), color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = {
                TextButton(enabled = !verifying, onClick = {
                    val candidate = password.toCharArray()
                    password = ""
                    verifying = true
                    scope.launch {
                        try {
                            val valid = withContext(Dispatchers.Default) {
                                adminAuth.verify(candidate)
                            }
                            if (valid) { showPassword = false; onUnlocked() }
                            else error = "Incorrect password"
                        } catch (exception: Exception) {
                            if (exception is CancellationException) throw exception
                            error = "Password verification failed"
                        } finally {
                            candidate.fill('\u0000')
                            verifying = false
                        }
                    }
                }) { Text(tr(if (verifying) "Checking…" else "Unlock")) }
            },
            dismissButton = { TextButton(enabled = !verifying, onClick = { showPassword = false; password = "" }) { Text(tr("Cancel")) } },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderSettingsScreen(
    initial: AppSettings,
    initialApiKey: String,
    onBack: () -> Unit,
    onSave: (AppSettings, String) -> Unit,
    onTest: suspend (AppSettings, String) -> String,
) {
    // An unrelated preference refresh must not overwrite an in-progress form.
    var settings by remember { mutableStateOf(initial) }
    var numbers by rememberSaveable(stateSaver = NumericDraftSaver) {
        mutableStateOf(NumericSettingsDrafts.provider(initial))
    }
    var key by remember { mutableStateOf(initialApiKey) }
    var connectionResult by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Provider")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(tr("No API demo"), style = MaterialTheme.typography.bodySmall)
            Field("Base URL", settings.baseUrl) { settings = settings.copy(baseUrl = it) }
            OutlinedTextField(
                value = key, onValueChange = { key = it }, modifier = Modifier.fillMaxWidth(),
                label = { Text(tr("API key")) }, visualTransformation = PasswordVisualTransformation(),
            )
            ParameterHelp("API key")
            Field("Dialogue model", settings.dialogueModel) { model ->
                settings = settings.copy(dialogueModel = model,
                    modelSupportsVision = settings.modelChoices.firstOrNull { it.model == model.trim() }?.vision ?: false)
            }
            Text(tr("Saved models"), style = MaterialTheme.typography.titleSmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                settings.modelChoices.forEach { entry ->
                    FilterChip(selected = settings.dialogueModel == entry.model,
                        onClick = { settings = settings.copy(dialogueModel = entry.model, modelSupportsVision = entry.vision) },
                        label = { Text(entry.model) })
                }
            }
            SettingSwitch("Vision capability", settings.modelSupportsVision) { settings = settings.copy(modelSupportsVision = it) }
            Text(tr("Vision help"), style = MaterialTheme.typography.bodySmall)
            Text(tr("Image upload notice"), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = {
                val model = settings.dialogueModel.trim()
                if (model.isNotBlank()) settings = settings.copy(modelChoices =
                    (settings.modelChoices.filterNot { it.model == model } + ModelChoice(model, settings.modelSupportsVision)).takeLast(20))
            }) { Text(tr("Save model entry")) }
            Field("Observer model", settings.observerModel) { settings = settings.copy(observerModel = it) }
            Text(tr("Memory summaries use the local deterministic pipeline (no additional model call)."),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            NumericSettingsDrafts.PROVIDER_FIELDS.forEach { (label, kind) ->
                NumberField(label, numbers.text(label), kind) { numbers = numbers.edit(label, it) }
            }
            SettingSwitch("Semantic Observer", settings.observerEnabled) { settings = settings.copy(observerEnabled = it) }
            ParameterHelp("Semantic Observer")
            SettingSwitch("Learning enabled", settings.learningEnabled) { settings = settings.copy(learningEnabled = it) }
            ParameterHelp("Learning enabled")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = numbers.providerValid, onClick = {
                    if (numbers.providerValid) onSave(numbers.applyProvider(settings), key)
                }) { Text(tr("Save")) }
                OutlinedButton(enabled = numbers.providerValid && !testing, onClick = {
                    if (numbers.providerValid && !testing) {
                        // Capture a valid form before suspension; later editing
                        // may intentionally leave a field incomplete again.
                        val candidate = numbers.applyProvider(settings)
                        val candidateKey = key
                        testing = true
                        scope.launch {
                            try { connectionResult = onTest(candidate, candidateKey) }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (_: Exception) { connectionResult = "Connection failed" }
                            finally { testing = false }
                        }
                    }
                }) { Text(tr(if (testing) "Checking…" else "Test connection")) }
                OutlinedButton(onClick = {
                    settings = settings.resetGenerationParameters()
                    numbers = NumericSettingsDrafts.provider(settings)
                }) { Text(tr("Reset")) }
            }
            connectionResult?.let { Text(tr(it), style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AulInspectorScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    var raw by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { raw = viewModel.aulJson() }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("AUL inspector")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp)) {
            val root = raw?.let { runCatching { JSONObject(it) }.getOrNull() }
            if (root == null) CircularProgressIndicator() else {
                Text(tr("Stable profile"), style = MaterialTheme.typography.titleMedium)
                JsonBlock(root.optJSONObject("profile")?.toString(2).orEmpty())
                Text(tr("Current state"), style = MaterialTheme.typography.titleMedium)
                JsonBlock(root.optJSONObject("current")?.toString(2).orEmpty())
                Text(tr("Relationship"), style = MaterialTheme.typography.titleMedium)
                JsonBlock(root.optJSONObject("relationship")?.toString(2).orEmpty())
                Text(tr("Interaction preferences"), style = MaterialTheme.typography.titleMedium)
                Text(tr("Preference help"), style = MaterialTheme.typography.bodySmall)
                val interaction = root.getJSONObject("interaction")
                interaction.keys().asSequence().toList().sorted().forEach { key ->
                    val item = interaction.getJSONObject(key)
                    var value by remember(raw, key) { mutableFloatStateOf(item.getDouble("value").toFloat()) }
                    Text(tr("Preference $key") + "  ${"%.2f".format(value)}")
                    Slider(value = value, onValueChange = { value = it }, onValueChangeFinished = {
                        viewModel.setPreference(key, value)
                        scope.launch { raw = viewModel.aulJson() }
                    })
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugMemoryScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    var kind by remember { mutableStateOf("evidence") }
    var content by remember { mutableStateOf("") }
    LaunchedEffect(kind) { content = viewModel.debugJson(kind) }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Memory and audit")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(12.dp)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("raw", "evidence", "metrics", "rolling", "daily", "weekly", "monthly", "long_term", "policy", "audit").forEach {
                    FilterChip(selected = kind == it, onClick = { kind = it }, label = { Text(tr("Data $it")) })
                }
            }
            Text(content, Modifier.weight(1f).verticalScroll(rememberScrollState()), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SchedulerDebugScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    var items by remember { mutableStateOf<List<ScheduledIntent>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun refresh() { items = viewModel.scheduled() }
    suspend fun refreshSafely() {
        try { refresh(); error = null }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { error = "Schedule load failed" }
    }
    fun runAction(action: () -> kotlinx.coroutines.Job) {
        if (busy) return
        busy = true
        error = null
        viewModel.clearError()
        scope.launch {
            try {
                action().join()
                val operationError = viewModel.state.value.error
                refreshSafely()
                // Joining a handled failure still returns normally. A refreshed
                // queue must not clear the actual operation failure.
                if (operationError != null) error = operationError
            }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { error = "Something went wrong. Your chat history is safe." }
            finally { busy = false }
        }
    }
    fun reload() {
        if (busy) return
        busy = true
        scope.launch { try { refreshSafely() } finally { busy = false } }
    }
    LaunchedEffect(Unit) { busy = true; try { refreshSafely() } finally { busy = false } }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Scheduled messages")) }, navigationIcon = { BackButton(onBack) },
        actions = { TextButton(enabled = !busy, onClick = { reload() }) { Text(tr("Refresh")) } }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(12.dp)) {
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { Text(tr(it), color = MaterialTheme.colorScheme.error) }
            items.forEach { item ->
                ElevatedCard(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(item.draftIntent, fontWeight = FontWeight.SemiBold)
                        Text(item.scheduledAt, style = MaterialTheme.typography.bodySmall)
                        Text(tr("Status ${item.status}") + " · " + item.reason, style = MaterialTheme.typography.bodySmall)
                        Row {
                            TextButton(enabled = !busy, onClick = { runAction { viewModel.runScheduled(item.id) } }) { Text(tr("Run now")) }
                            TextButton(enabled = !busy, onClick = { runAction { viewModel.cancelScheduled(item.id) } }) { Text(tr("Cancel")) }
                            TextButton(enabled = !busy, onClick = { runAction { viewModel.deleteScheduled(item.id) } }) { Text(tr("Delete")) }
                        }
                    }
                }
            }
            if (items.isEmpty()) Text(tr("No scheduled messages"), Modifier.padding(20.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdvancedSettingsScreen(initial: AppSettings, onBack: () -> Unit, onSave: (AppSettings) -> Unit) {
    var s by remember { mutableStateOf(initial) }
    var numbers by rememberSaveable(stateSaver = NumericDraftSaver) {
        mutableStateOf(NumericSettingsDrafts.advanced(initial))
    }
    @Composable fun IntDraft(label: String) {
        NumberField(label, numbers.text(label), NumericInputKind.INTEGER) { numbers = numbers.edit(label, it) }
    }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Core and timing")) }, navigationIcon = { BackButton(onBack) }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Section("Memory")
            IntDraft("Context budget")
            IntDraft("Summary message threshold")
            IntDraft("Summary token threshold")
            Section("Learning")
            Text(tr("Weak evidence rate") + "  ${"%.3f".format(s.weakEvidenceRate)}")
            ParameterHelp("Weak evidence rate")
            Slider(s.weakEvidenceRate, { s = s.copy(weakEvidenceRate = it) }, valueRange = 0.005f..0.08f)
            Text(tr("Explicit evidence rate") + "  ${"%.2f".format(s.explicitEvidenceRate)}")
            ParameterHelp("Explicit evidence rate")
            Slider(s.explicitEvidenceRate, { s = s.copy(explicitEvidenceRate = it) }, valueRange = 0.05f..0.25f)
            Text(tr("Correction evidence rate") + "  ${"%.2f".format(s.correctionEvidenceRate)}")
            ParameterHelp("Correction evidence rate")
            Slider(s.correctionEvidenceRate, { s = s.copy(correctionEvidenceRate = it) }, valueRange = 0.15f..0.45f)
            Section("Proactive messages")
            IntDraft("Maximum per day")
            IntDraft("Minimum interval hours")
            IntDraft("Quiet starts")
            IntDraft("Quiet ends")
            Text(tr("Importance threshold") + "  ${"%.2f".format(s.proactiveThreshold)}")
            ParameterHelp("Importance threshold")
            Slider(s.proactiveThreshold, { s = s.copy(proactiveThreshold = it) })
            Section("Humanized delivery")
            IntDraft("Base delay ms")
            IntDraft("Per character ms")
            IntDraft("Random jitter ms")
            IntDraft("Minimum delay ms")
            IntDraft("Maximum delay ms")
            Text(tr("Split probability") + "  ${"%.2f".format(s.splitProbability)}")
            ParameterHelp("Split probability")
            Slider(s.splitProbability, { s = s.copy(splitProbability = it) })
            Button(enabled = numbers.advancedValid, onClick = {
                if (numbers.advancedValid) onSave(numbers.applyAdvanced(s))
            }) { Text(tr("Save")) }
        }
    }
}

@Composable private fun SettingRow(title: String, subtitle: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 18.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Text(tr(title)); Text(tr(subtitle), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        Text(tr("›"), style = MaterialTheme.typography.titleLarge)
    }
}

@Composable private fun SettingSwitch(title: String, value: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(tr(title), Modifier.weight(1f)); Switch(value, onChange)
    }
}

@Composable private fun Section(title: String) { Text(tr(title), Modifier.padding(start = 18.dp, top = 20.dp, bottom = 5.dp), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge) }
@Composable private fun BackButton(onBack: () -> Unit) { TextButton(onClick = onBack) { Text(tr("‹ Back")) } }
@Composable private fun Field(label: String, value: String, onValue: (String) -> Unit) { Column { OutlinedTextField(value, onValue, Modifier.fillMaxWidth(), label = { Text(tr(label)) }, singleLine = true); ParameterHelp(label) } }
private val NumericDraftSaver = mapSaver(
    save = { draft: NumericSettingsDrafts -> draft.values },
    restore = { values -> NumericSettingsDrafts(values.mapValues { (_, value) -> value as String }) },
)

@Composable private fun NumberField(label: String, value: String, kind: NumericInputKind, onValue: (String) -> Unit) {
    Column {
        OutlinedTextField(value, onValue, Modifier.fillMaxWidth(), label = { Text(tr(label)) }, singleLine = true,
            isError = !validNumericInput(value, kind),
            keyboardOptions = KeyboardOptions(keyboardType = if (kind == NumericInputKind.DECIMAL) KeyboardType.Decimal else KeyboardType.Number))
        ParameterHelp(label)
    }
}
@Composable private fun JsonBlock(text: String) { Surface(Modifier.fillMaxWidth().padding(vertical = 8.dp), color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.medium) { Text(text, Modifier.padding(10.dp), style = MaterialTheme.typography.bodySmall) } }

@Composable private fun ParameterHelp(label: String) { Text(tr("Help $label"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
