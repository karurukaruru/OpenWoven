package com.adaptive.companion.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsValidationTest {
    @Test fun displayTogglesDoNotRestartCoreButCoreTogglesDo() {
        listOf("notifications", "sound", "vibration", "feedback").forEach {
            assertEquals(false, toggleRequiresCoreRestart(it))
        }
        listOf("proactive", "timing", "greeting_delay").forEach {
            assertEquals(true, toggleRequiresCoreRestart(it))
        }
    }

    @Test(expected = IllegalStateException::class)
    fun unknownToggleCannotSilentlySkipConfiguration() {
        toggleRequiresCoreRestart("unknown")
    }

    @Test fun invalidProviderValuesAreClamped() {
        val safe = AppSettings(
            temperature = -4f, topP = 8f, maxTokens = -1,
            timeoutSeconds = 0, retryCount = 99,
        ).sanitized()
        assertEquals(0f, safe.temperature)
        assertEquals(1f, safe.topP)
        assertEquals(96, safe.maxTokens)
        assertEquals(5, safe.timeoutSeconds)
        assertEquals(5, safe.retryCount)
    }

    @Test fun timingRangeCannotInvert() {
        val safe = AppSettings(minDelayMs = 1_500, maxDelayMs = 20).sanitized()
        assertTrue(safe.minDelayMs <= safe.maxDelayMs)
        assertEquals(1_500, safe.maxDelayMs)
    }
}
