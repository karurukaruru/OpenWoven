package com.adaptive.companion.data

import com.adaptive.companion.EditionPolicy
import com.adaptive.companion.ui.Screen
import com.adaptive.companion.ui.UiStrings
import org.junit.Assert.*
import org.junit.Test
import java.time.ZoneId

class ScheduledChatTest {
    @Test fun publicSchedulingIsNotHiddenBehindTheAdministratorGate() {
        assertEquals(Screen.SCHEDULE_MESSAGES, EditionPolicy.resolveScreen(Screen.SCHEDULE_MESSAGES, false, false))
        assertEquals(Screen.SETTINGS, EditionPolicy.resolveScreen(Screen.SCHEDULER, false, false))
    }

    @Test fun chosenClockUsesDeviceZoneAndRejectsInvalidDates() {
        assertEquals("2026-10-02T12:30+08:00", scheduledLocalTime("2026-10-02", "12:30", ZoneId.of("Asia/Shanghai")))
        listOf("2026-02-30" to "12:30", "2026-10-02" to "25:30", "2026-1-2" to "12:30").forEach {
            assertTrue(runCatching { scheduledLocalTime(it.first, it.second) }.isFailure)
        }
    }

    @Test fun nonexistentAndAmbiguousDstClocksAreNotSilentlyShifted() {
        val zone = ZoneId.of("America/New_York")
        assertTrue(runCatching { scheduledLocalTime("2026-03-08", "02:30", zone) }.isFailure)
        assertTrue(runCatching { scheduledLocalTime("2026-11-01", "01:30", zone) }.isFailure)
    }

    @Test fun restoredBubblesKeepOnePersistedIdentityForDeleteAndFeedback() {
        val original = ChatMessage("msg_synthetic", "default", "assistant", "好呀。明天见。", "2026-10-01T00:00:00Z",
            deliveryParts = listOf(DeliveryPart("好呀", 0), DeliveryPart("明天见", 250)))
        val bubbles = original.bubbles()
        assertEquals(listOf("好呀", "明天见"), bubbles.map { it.content })
        assertEquals(listOf("msg_synthetic_0", "msg_synthetic_1"), bubbles.map { it.id })
        assertTrue(bubbles.all { it.persistedId() == original.id && !it.transient })
        assertEquals(bubbles, bubbles.flatMap { it.bubbles() })
    }

    @Test fun userMessagesAndLegacyWholeRepliesAreNotExpanded() {
        val user = ChatMessage("msg_user", "default", "user", "hi", "2026-10-01T00:00:00Z")
        assertEquals(listOf(user), user.bubbles())
        assertEquals(user.id, user.persistedId())
        val oldAssistant = user.copy(role = "assistant")
        assertEquals(listOf(oldAssistant), oldAssistant.bubbles())
    }

    @Test fun newDefaultsAndPublicQueueLabelsMatchAllFourLanguages() {
        assertEquals(5400, AppSettings().contextBudget)
        assertEquals(5400, AppSettings().summaryTokenThreshold)
        listOf("Scheduled messages", "Schedule exact text", "Schedule model topic", "Schedule save", "Distilled user profile").forEach { key ->
            assertTrue(UiStrings.catalog.containsKey(key))
            UiStrings.languages.forEach { assertTrue(UiStrings.text(it, key).isNotBlank()) }
        }
    }
}
