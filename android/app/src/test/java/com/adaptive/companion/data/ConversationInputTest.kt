package com.adaptive.companion.data

import com.adaptive.companion.ui.UiStrings
import org.junit.Assert.*
import org.junit.Test

class ConversationInputTest {
    @Test fun refreshRetainsUncommittedTextAndImageSends() {
        val pending = ChatMessage("pending", "default", "user", "正在排队", "2026-10-01T00:00:00Z",
            transient = true, status = "pending", imagePath = "private.jpg")
        val saved = pending.copy(id = "saved", transient = false, status = "sent")
        assertEquals(listOf(saved, pending), mergeChatHistory(listOf(saved), listOf(pending)))
        assertEquals(listOf(saved), mergeChatHistory(listOf(saved), listOf(saved.copy(transient = true))))
    }

    @Test fun refreshDoesNotResurrectDiscardedAssistantAnimation() {
        val old = ChatMessage("old", "default", "assistant", "旧回复", "2026-10-01T00:00:00Z", transient = true)
        assertTrue(mergeChatHistory(emptyList(), listOf(old)).isEmpty())
    }

    @Test fun messageClockUsesDeviceZoneNotStoredUtcHour() {
        assertEquals("08:30", chatLocalTime("2026-10-01T00:30:00Z", java.time.ZoneId.of("Asia/Shanghai")))
        assertEquals("20:30", chatLocalTime("2026-10-01T00:30:00Z", java.time.ZoneId.of("America/New_York")))
        assertEquals("", chatLocalTime("not-a-date"))
    }
    @Test fun emptyComposerWaitsTwentySecondsAfterTouch() {
        assertFalse(composerReady(false, 5000, 24999, 20))
        assertTrue(composerReady(false, 5000, 25000, 20))
        assertFalse(composerReady(false, 24000, 25000, 20))
    }

    @Test fun unsentTextAndImeCompositionNeverTimeOutIntoReply() {
        assertFalse(composerReady(true, 0, Long.MAX_VALUE, 20))
        assertTrue(composerReady(false, 0, 30000, 30))
    }

    @Test fun visionFlagAloneDoesNotAllowUpload() {
        assertFalse(canSendImage(false, true))
        assertFalse(canSendImage(true, false))
        assertTrue(canSendImage(true, true))
    }
    @Test fun idleAndTimezoneDefaultsAreSafe() {
        val defaults = AppSettings()
        assertEquals(20, defaults.turnIdleSeconds)
        assertEquals("", defaults.timeZone)
        assertEquals(.30f, defaults.dailyReplyLength)
        assertFalse(defaults.greetingDelayEnabled)
        val safe = defaults.copy(turnIdleSeconds = 500, timeZone = "not-a-zone", dailyReplyLength = Float.NaN).sanitized()
        assertEquals(60, safe.turnIdleSeconds)
        assertEquals("", safe.timeZone)
        assertEquals(.30f, safe.dailyReplyLength)
    }

    @Test fun standardZonesAndDstZonesAreAccepted() {
        for (zone in listOf("Asia/Shanghai", "Asia/Hong_Kong", "America/New_York", "UTC", "")) {
            assertEquals(zone, AppSettings(timeZone = zone).sanitized().timeZone)
        }
        assertEquals(10, AppSettings(turnIdleSeconds = -1).sanitized().turnIdleSeconds)
    }

    @Test fun shortAssistantPartsHaveDistinctStableBubbleIds() {
        val saved = ChatMessage("root", "default", "assistant", "好呀 明天见", "2026-10-01T00:00:00Z",
            deliveryParts = listOf(DeliveryPart("好呀", 0), DeliveryPart("明天见", 0)))
        val bubbles = saved.bubbles()
        assertEquals(listOf("好呀", "明天见"), bubbles.map { it.content })
        assertEquals(listOf("root_0", "root_1"), bubbles.map { it.id })
        assertEquals(listOf("root", "root"), bubbles.map { it.persistedId() })
    }

    @Test fun roleLabelsAreConcreteAndHelpExplainsPrivacy() {
        assertEquals("女性角色", UiStrings.text("zh-CN", "Interview choice female"))
        assertEquals("男性角色", UiStrings.text("zh-CN", "Interview choice male"))
        assertTrue(UiStrings.text("zh-CN", "Turn wait help").contains("不读取其他应用"))
        assertTrue(UiStrings.text("zh-CN", "Time zone help").contains("默认留空"))
    }
}
