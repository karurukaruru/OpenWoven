package com.adaptive.companion.data

enum class NumericInputKind { INTEGER, DECIMAL }

/** Editing a number is text editing: empty and partial values must not snap back. */
data class NumericSettingsDrafts(val values: Map<String, String>) {
    fun text(label: String): String = values.getValue(label)

    fun edit(label: String, text: String): NumericSettingsDrafts {
        require(label in values)
        return copy(values = values + (label to text))
    }

    fun isValid(label: String, kind: NumericInputKind): Boolean =
        validNumericInput(text(label), kind)

    val providerValid: Boolean get() = values.keys == PROVIDER_FIELDS.keys &&
        PROVIDER_FIELDS.all { (label, kind) -> isValid(label, kind) }

    val advancedValid: Boolean get() = values.keys == ADVANCED_FIELDS.toSet() &&
        ADVANCED_FIELDS.all { isValid(it, NumericInputKind.INTEGER) }

    fun applyProvider(settings: AppSettings): AppSettings {
        require(providerValid)
        return settings.copy(
            temperature = text("Temperature").trim().toFloat(),
            topP = text("Top P").trim().toFloat(),
            maxTokens = text("Max tokens").trim().toInt(),
            timeoutSeconds = text("Timeout seconds").trim().toInt(),
            retryCount = text("Retry").trim().toInt(),
        )
    }

    fun applyAdvanced(settings: AppSettings): AppSettings {
        require(advancedValid)
        fun number(label: String) = text(label).trim().toInt()
        return settings.copy(
            contextBudget = number("Context budget"),
            summaryMessageThreshold = number("Summary message threshold"),
            summaryTokenThreshold = number("Summary token threshold"),
            maxProactivePerDay = number("Maximum per day"),
            proactiveMinimumHours = number("Minimum interval hours"),
            quietStart = number("Quiet starts"), quietEnd = number("Quiet ends"),
            baseDelayMs = number("Base delay ms"),
            delayPerCharacterMs = number("Per character ms"),
            jitterMs = number("Random jitter ms"),
            minDelayMs = number("Minimum delay ms"),
            maxDelayMs = number("Maximum delay ms"),
        )
    }

    companion object {
        val PROVIDER_FIELDS = linkedMapOf(
            "Temperature" to NumericInputKind.DECIMAL,
            "Top P" to NumericInputKind.DECIMAL,
            "Max tokens" to NumericInputKind.INTEGER,
            "Timeout seconds" to NumericInputKind.INTEGER,
            "Retry" to NumericInputKind.INTEGER,
        )
        val ADVANCED_FIELDS = listOf(
            "Context budget", "Summary message threshold", "Summary token threshold",
            "Maximum per day", "Minimum interval hours", "Quiet starts", "Quiet ends",
            "Base delay ms", "Per character ms", "Random jitter ms", "Minimum delay ms", "Maximum delay ms",
        )

        fun provider(settings: AppSettings) = NumericSettingsDrafts(linkedMapOf(
            "Temperature" to settings.temperature.toString(), "Top P" to settings.topP.toString(),
            "Max tokens" to settings.maxTokens.toString(), "Timeout seconds" to settings.timeoutSeconds.toString(),
            "Retry" to settings.retryCount.toString(),
        ))

        fun advanced(settings: AppSettings) = NumericSettingsDrafts(linkedMapOf(
            "Context budget" to settings.contextBudget.toString(),
            "Summary message threshold" to settings.summaryMessageThreshold.toString(),
            "Summary token threshold" to settings.summaryTokenThreshold.toString(),
            "Maximum per day" to settings.maxProactivePerDay.toString(),
            "Minimum interval hours" to settings.proactiveMinimumHours.toString(),
            "Quiet starts" to settings.quietStart.toString(), "Quiet ends" to settings.quietEnd.toString(),
            "Base delay ms" to settings.baseDelayMs.toString(),
            "Per character ms" to settings.delayPerCharacterMs.toString(), "Random jitter ms" to settings.jitterMs.toString(),
            "Minimum delay ms" to settings.minDelayMs.toString(), "Maximum delay ms" to settings.maxDelayMs.toString(),
        ))
    }
}

fun validNumericInput(text: String, kind: NumericInputKind): Boolean = when (kind) {
    NumericInputKind.INTEGER -> text.trim().toIntOrNull() != null
    NumericInputKind.DECIMAL -> text.trim().toFloatOrNull()?.isFinite() == true
}
