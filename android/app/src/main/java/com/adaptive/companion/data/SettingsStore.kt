package com.adaptive.companion.data

import android.content.Context
import androidx.core.content.edit
import com.adaptive.companion.BuildConfig
import com.adaptive.companion.scheduler.BackgroundPolicy
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.settingsDataStore by preferencesDataStore("companion_settings")

data class AppSettings(
    val language: String = "zh-CN",
    val persona: PersonaSettings = PersonaSettings(),
    val personaConfigured: Boolean = false,
    val modelChoices: List<ModelChoice> = emptyList(),
    val modelSupportsVision: Boolean = false,
    val turnIdleSeconds: Int = 20,
    val timeZone: String = "",
    val dailyReplyLength: Float = 0.30f,
    val baseUrl: String = "https://api.openai.com/v1",
    val dialogueModel: String = "gpt-4.1-mini",
    val observerModel: String = "gpt-4.1-mini",
    val memoryModel: String = "gpt-4.1-mini",
    val temperature: Float = 0.7f,
    val topP: Float = 1f,
    val maxTokens: Int = 800,
    val timeoutSeconds: Int = 60,
    val retryCount: Int = 2,
    val observerEnabled: Boolean = false,
    val learningEnabled: Boolean = true,
    val weakEvidenceRate: Float = 0.025f,
    val explicitEvidenceRate: Float = 0.11f,
    val correctionEvidenceRate: Float = 0.36f,
    val notificationsEnabled: Boolean = true,
    val proactiveEnabled: Boolean = true,
    val naturalTiming: Boolean = true,
    val greetingDelayEnabled: Boolean = false,
    val backgroundMode: String = BackgroundPolicy.defaultMode(BuildConfig.IS_FULL),
    val sound: Boolean = true,
    val vibration: Boolean = true,
    val quietStart: Int = 22,
    val quietEnd: Int = 8,
    val maxProactivePerDay: Int = 1,
    val proactiveMinimumHours: Int = 8,
    val proactiveThreshold: Float = 0.68f,
    val contextBudget: Int = 5400,
    val summaryMessageThreshold: Int = 12,
    val summaryTokenThreshold: Int = 5400,
    val baseDelayMs: Int = 750,
    val delayPerCharacterMs: Int = 30,
    val jitterMs: Int = 150,
    val splitProbability: Float = 0.32f,
    val minDelayMs: Int = 800,
    val maxDelayMs: Int = 2500,
    val feedbackEnabled: Boolean = true,
    val darkTheme: Boolean? = null,
)

/** Reset only generation knobs, preserving account, models, learning and app state. */
fun AppSettings.resetGenerationParameters(): AppSettings = copy(
    temperature = 0.7f, topP = 1f, maxTokens = 800, timeoutSeconds = 60, retryCount = 2,
)

/** Upgrade only the complete old stock tuple; retain custom timing and toggles. */
fun AppSettings.upgradeLegacyBubbleTiming(): AppSettings =
    if (baseDelayMs == 250 && delayPerCharacterMs == 12 && jitterMs == 180 &&
        minDelayMs == 120 && maxDelayMs == 1800) {
        val defaults = AppSettings()
        copy(baseDelayMs = defaults.baseDelayMs, delayPerCharacterMs = defaults.delayPerCharacterMs,
            jitterMs = defaults.jitterMs, minDelayMs = defaults.minDelayMs, maxDelayMs = defaults.maxDelayMs)
    } else this

/** UI/notification toggles are read from DataStore; they do not configure Python. */
fun toggleRequiresCoreRestart(name: String): Boolean = when (name) {
    "proactive", "timing", "greeting_delay" -> true
    "notifications", "sound", "vibration", "feedback" -> false
    else -> error("Unknown setting $name")
}

fun AppSettings.sanitized(): AppSettings {
    val safeMinDelay = minDelayMs.coerceIn(0, 2_000)
    return copy(
        language = language.takeIf { it in listOf("zh-CN", "zh-TW", "ja", "en-US") } ?: "zh-CN",
        persona = persona.sanitized(),
        turnIdleSeconds = turnIdleSeconds.coerceIn(10, 60),
        timeZone = timeZone.trim().takeIf { it.isEmpty() || runCatching { java.time.ZoneId.of(it) }.isSuccess } ?: "",
        dailyReplyLength = (dailyReplyLength.takeIf { it.isFinite() } ?: 0.30f).coerceIn(0f, 1f),
        modelChoices = (modelChoices.filter { it.model.isNotBlank() }.map { it.copy(model = it.model.trim().take(120)) }
            + ModelChoice(dialogueModel.trim().take(120).ifBlank { "gpt-4.1-mini" }, modelSupportsVision)).associateBy { it.model }.values.toList().takeLast(20),
        backgroundMode = BackgroundPolicy.sanitize(backgroundMode),
        baseUrl = baseUrl.trim(),
        dialogueModel = dialogueModel.trim().take(120).ifBlank { "gpt-4.1-mini" },
        observerModel = observerModel.trim().take(120).ifBlank { dialogueModel.trim().take(120).ifBlank { "gpt-4.1-mini" } },
        temperature = (temperature.takeIf { it.isFinite() } ?: 0.7f).coerceIn(0f, 2f),
        topP = (topP.takeIf { it.isFinite() } ?: 1f).coerceIn(0.01f, 1f),
        maxTokens = maxTokens.coerceIn(96, 8_192),
        timeoutSeconds = timeoutSeconds.coerceIn(5, 180),
        retryCount = retryCount.coerceIn(0, 5),
        weakEvidenceRate = (weakEvidenceRate.takeIf { it.isFinite() } ?: 0.025f).coerceIn(0.005f, 0.08f),
        explicitEvidenceRate = (explicitEvidenceRate.takeIf { it.isFinite() } ?: 0.11f).coerceIn(0.05f, 0.25f),
        correctionEvidenceRate = (correctionEvidenceRate.takeIf { it.isFinite() } ?: 0.36f).coerceIn(0.15f, 0.45f),
        quietStart = quietStart.coerceIn(0, 23),
        quietEnd = quietEnd.coerceIn(0, 23),
        maxProactivePerDay = maxProactivePerDay.coerceIn(1, 5),
        proactiveMinimumHours = proactiveMinimumHours.coerceIn(1, 168),
        proactiveThreshold = (proactiveThreshold.takeIf { it.isFinite() } ?: 0.68f).coerceIn(0f, 1f),
        contextBudget = contextBudget.coerceIn(512, 16_000),
        summaryMessageThreshold = summaryMessageThreshold.coerceIn(4, 100),
        summaryTokenThreshold = summaryTokenThreshold.coerceIn(200, 10_000),
        baseDelayMs = baseDelayMs.coerceIn(0, 2_000),
        delayPerCharacterMs = delayPerCharacterMs.coerceIn(0, 50),
        jitterMs = jitterMs.coerceIn(0, 2_000),
        splitProbability = (splitProbability.takeIf { it.isFinite() } ?: 0.32f).coerceIn(0f, 1f),
        minDelayMs = safeMinDelay,
        maxDelayMs = maxDelayMs.coerceIn(safeMinDelay, 5_000),
    )
}

class SettingsStore(private val context: Context) {
    suspend fun upgradeConversationDefaults() = context.settingsDataStore.edit { p ->
        val upgraded = booleanPreferencesKey("conversation_defaults_5400")
        if (p[upgraded] != true) {
            if (p[Keys.contextBudget] == 1800) p[Keys.contextBudget] = 5400
            if (p[Keys.summaryTokens] == 600) p[Keys.summaryTokens] = 5400
            p[upgraded] = true
        }
        val paced = booleanPreferencesKey("bubble_timing_defaults_v2")
        if (p[paced] != true) {
            val old = AppSettings(baseDelayMs = p[Keys.baseDelay] ?: 250,
                delayPerCharacterMs = p[Keys.charDelay] ?: 12, jitterMs = p[Keys.jitter] ?: 180,
                minDelayMs = p[Keys.minDelay] ?: 120, maxDelayMs = p[Keys.maxDelay] ?: 1800)
            val next = old.upgradeLegacyBubbleTiming()
            if (next != old) {
                p[Keys.baseDelay] = next.baseDelayMs
                p[Keys.charDelay] = next.delayPerCharacterMs
                p[Keys.jitter] = next.jitterMs
                p[Keys.minDelay] = next.minDelayMs
                p[Keys.maxDelay] = next.maxDelayMs
            }
            p[paced] = true
        }
    }
    private object Keys {
        val turnIdle = intPreferencesKey("turn_idle_seconds")
        val timeZone = stringPreferencesKey("time_zone")
        val dailyLength = floatPreferencesKey("daily_reply_length")
        val language = stringPreferencesKey("language")
        val persona = stringPreferencesKey("persona")
        val personaConfigured = booleanPreferencesKey("persona_configured")
        val models = stringPreferencesKey("model_choices")
        val vision = booleanPreferencesKey("model_vision")
        val baseUrl = stringPreferencesKey("base_url")
        val dialogueModel = stringPreferencesKey("dialogue_model")
        val observerModel = stringPreferencesKey("observer_model")
        val memoryModel = stringPreferencesKey("memory_model")
        val temperature = floatPreferencesKey("temperature")
        val topP = floatPreferencesKey("top_p")
        val maxTokens = intPreferencesKey("max_tokens")
        val timeout = intPreferencesKey("timeout")
        val retry = intPreferencesKey("retry")
        val observer = booleanPreferencesKey("observer_enabled")
        val learning = booleanPreferencesKey("learning_enabled")
        val weakRate = floatPreferencesKey("weak_evidence_rate")
        val explicitRate = floatPreferencesKey("explicit_evidence_rate")
        val correctionRate = floatPreferencesKey("correction_evidence_rate")
        val notifications = booleanPreferencesKey("notifications")
        val proactive = booleanPreferencesKey("proactive")
        val timing = booleanPreferencesKey("natural_timing")
        val greetingDelay = booleanPreferencesKey("greeting_delay")
        val backgroundMode = stringPreferencesKey("background_mode")
        val sound = booleanPreferencesKey("sound")
        val vibration = booleanPreferencesKey("vibration")
        val quietStart = intPreferencesKey("quiet_start")
        val quietEnd = intPreferencesKey("quiet_end")
        val maxProactive = intPreferencesKey("max_proactive")
        val minimumHours = intPreferencesKey("minimum_hours")
        val proactiveThreshold = floatPreferencesKey("proactive_threshold")
        val contextBudget = intPreferencesKey("context_budget")
        val summaryMessages = intPreferencesKey("summary_messages")
        val summaryTokens = intPreferencesKey("summary_tokens")
        val baseDelay = intPreferencesKey("base_delay")
        val charDelay = intPreferencesKey("char_delay")
        val jitter = intPreferencesKey("jitter")
        val splitProbability = floatPreferencesKey("split_probability")
        val minDelay = intPreferencesKey("min_delay")
        val maxDelay = intPreferencesKey("max_delay")
        val feedback = booleanPreferencesKey("feedback")
        val darkTheme = intPreferencesKey("dark_theme")
    }

    val flow: Flow<AppSettings> = context.settingsDataStore.data.map(::decode)
    suspend fun snapshot(): AppSettings = flow.first()

    suspend fun saveConversation(seconds: Int, zone: String, length: Float) {
        val safe = AppSettings(turnIdleSeconds = seconds, timeZone = zone, dailyReplyLength = length).sanitized()
        update {
            this[Keys.turnIdle] = safe.turnIdleSeconds
            this[Keys.timeZone] = safe.timeZone
            this[Keys.dailyLength] = safe.dailyReplyLength
        }
    }

    suspend fun update(block: MutablePreferences.() -> Unit) {
        context.settingsDataStore.edit(block)
    }

    suspend fun saveProvider(settings: AppSettings) {
        val safe = settings.sanitized()
        update {
        this[Keys.baseUrl] = safe.baseUrl
        this[Keys.dialogueModel] = safe.dialogueModel
        this[Keys.observerModel] = safe.observerModel
        this[Keys.memoryModel] = safe.memoryModel
        this[Keys.temperature] = safe.temperature
        this[Keys.topP] = safe.topP
        this[Keys.maxTokens] = safe.maxTokens
        this[Keys.timeout] = safe.timeoutSeconds
        this[Keys.retry] = safe.retryCount
        this[Keys.observer] = safe.observerEnabled
        this[Keys.learning] = safe.learningEnabled
        this[Keys.models] = ModelChoice.encode(safe.modelChoices)
        this[Keys.vision] = safe.modelSupportsVision
        }
    }

    suspend fun setBoolean(name: String, value: Boolean) = update {
        val key = when (name) {
            "notifications" -> Keys.notifications
            "proactive" -> Keys.proactive
            "timing" -> Keys.timing
            "greeting_delay" -> Keys.greetingDelay
            "sound" -> Keys.sound
            "vibration" -> Keys.vibration
            "feedback" -> Keys.feedback
            else -> error("Unknown setting $name")
        }
        this[key] = value
    }

    suspend fun setDarkTheme(value: Boolean) = update { this[Keys.darkTheme] = if (value) 1 else 0 }

    suspend fun savePersona(persona: PersonaSettings) = update {
        this[Keys.persona] = persona.json("zh-CN").toString()
        this[Keys.personaConfigured] = true
    }
    suspend fun setLanguage(code: String) {
        val safe = code.takeIf { it in listOf("zh-CN", "zh-TW", "ja", "en-US") } ?: "zh-CN"
        context.getSharedPreferences("app_language", Context.MODE_PRIVATE).edit { putString("code", safe) }
        update { this[Keys.language] = safe }
    }

    suspend fun setBackgroundMode(mode: String) = update {
        this[Keys.backgroundMode] = BackgroundPolicy.sanitize(mode)
    }

    suspend fun saveAdvanced(settings: AppSettings) {
        val safe = settings.sanitized()
        update {
        this[Keys.quietStart] = safe.quietStart
        this[Keys.quietEnd] = safe.quietEnd
        this[Keys.maxProactive] = safe.maxProactivePerDay
        this[Keys.minimumHours] = safe.proactiveMinimumHours
        this[Keys.proactiveThreshold] = safe.proactiveThreshold
        this[Keys.contextBudget] = safe.contextBudget
        this[Keys.summaryMessages] = safe.summaryMessageThreshold
        this[Keys.summaryTokens] = safe.summaryTokenThreshold
        this[Keys.baseDelay] = safe.baseDelayMs
        this[Keys.charDelay] = safe.delayPerCharacterMs
        this[Keys.jitter] = safe.jitterMs
        this[Keys.splitProbability] = safe.splitProbability
        this[Keys.minDelay] = safe.minDelayMs
        this[Keys.maxDelay] = safe.maxDelayMs
        this[Keys.weakRate] = safe.weakEvidenceRate
        this[Keys.explicitRate] = safe.explicitEvidenceRate
        this[Keys.correctionRate] = safe.correctionEvidenceRate
        }
    }

    private fun decode(p: Preferences) = AppSettings(
        turnIdleSeconds = p[Keys.turnIdle] ?: 20,
        timeZone = p[Keys.timeZone] ?: "",
        dailyReplyLength = p[Keys.dailyLength] ?: 0.30f,
        language = p[Keys.language] ?: "zh-CN",
        persona = PersonaSettings.parse(p[Keys.persona] ?: "{}"),
        personaConfigured = p[Keys.personaConfigured] ?: false,
        modelChoices = ModelChoice.parseList(p[Keys.models] ?: "[]"),
        modelSupportsVision = p[Keys.vision] ?: false,
        baseUrl = p[Keys.baseUrl] ?: AppSettings().baseUrl,
        dialogueModel = p[Keys.dialogueModel] ?: AppSettings().dialogueModel,
        observerModel = p[Keys.observerModel] ?: AppSettings().observerModel,
        memoryModel = p[Keys.memoryModel] ?: AppSettings().memoryModel,
        temperature = p[Keys.temperature] ?: 0.7f,
        topP = p[Keys.topP] ?: 1f,
        maxTokens = p[Keys.maxTokens] ?: 800,
        timeoutSeconds = p[Keys.timeout] ?: 60,
        retryCount = p[Keys.retry] ?: 2,
        observerEnabled = p[Keys.observer] ?: false,
        learningEnabled = p[Keys.learning] ?: true,
        weakEvidenceRate = p[Keys.weakRate] ?: 0.025f,
        explicitEvidenceRate = p[Keys.explicitRate] ?: 0.11f,
        correctionEvidenceRate = p[Keys.correctionRate] ?: 0.36f,
        notificationsEnabled = p[Keys.notifications] ?: true,
        proactiveEnabled = p[Keys.proactive] ?: true,
        naturalTiming = p[Keys.timing] ?: true,
        greetingDelayEnabled = p[Keys.greetingDelay] ?: false,
        backgroundMode = p[Keys.backgroundMode] ?: BackgroundPolicy.defaultMode(BuildConfig.IS_FULL),
        sound = p[Keys.sound] ?: true,
        vibration = p[Keys.vibration] ?: true,
        quietStart = p[Keys.quietStart] ?: 22,
        quietEnd = p[Keys.quietEnd] ?: 8,
        maxProactivePerDay = p[Keys.maxProactive] ?: 1,
        proactiveMinimumHours = p[Keys.minimumHours] ?: 8,
        proactiveThreshold = p[Keys.proactiveThreshold] ?: 0.68f,
        contextBudget = p[Keys.contextBudget] ?: 5400,
        summaryMessageThreshold = p[Keys.summaryMessages] ?: 12,
        summaryTokenThreshold = p[Keys.summaryTokens] ?: 5400,
        baseDelayMs = p[Keys.baseDelay] ?: AppSettings().baseDelayMs,
        delayPerCharacterMs = p[Keys.charDelay] ?: AppSettings().delayPerCharacterMs,
        jitterMs = p[Keys.jitter] ?: AppSettings().jitterMs,
        splitProbability = p[Keys.splitProbability] ?: 0.32f,
        minDelayMs = p[Keys.minDelay] ?: AppSettings().minDelayMs,
        maxDelayMs = p[Keys.maxDelay] ?: AppSettings().maxDelayMs,
        feedbackEnabled = p[Keys.feedback] ?: true,
        darkTheme = when (p[Keys.darkTheme]) { 0 -> false; 1 -> true; else -> null },
    ).sanitized()
}
