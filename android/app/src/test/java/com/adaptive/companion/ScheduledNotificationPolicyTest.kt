package com.adaptive.companion

import com.adaptive.companion.notifications.canUseMessageChannel
import com.adaptive.companion.scheduler.*
import com.adaptive.companion.ui.UiStrings
import org.junit.Assert.*
import org.junit.Test

class ScheduledNotificationPolicyTest {
    @Test fun fixedContentStaysOfflineWhenRestoredWithAConfiguredProvider() {
        assertFalse(scheduledTaskNeedsNetwork("custom:text:synthetic", true))
        assertFalse(scheduledTaskNeedsNetwork("reminder:synthetic", true))
    }

    @Test fun GeneratedJobsUseNetworkOnlyWithAConfiguredProvider() {
        listOf("custom:topic:test", "checkin:test", "reply:msg_test", "exam:test").forEach {
            assertTrue(scheduledTaskNeedsNetwork(it, true))
            assertFalse(scheduledTaskNeedsNetwork(it, false))
        }
    }

    @Test fun bothEditionsDefaultToStoppableResidentMode() {
        assertEquals(BackgroundPolicy.RESIDENT, BackgroundPolicy.defaultMode(true))
        assertEquals(BackgroundPolicy.RESIDENT, BackgroundPolicy.defaultMode(false))
        assertEquals(BackgroundPolicy.SYSTEM, BackgroundPolicy.sanitize("system"))
    }

    @Test fun runtimeGrantAndAppSwitchDoNotOverrideABlockedChannel() {
        assertFalse(canUseMessageChannel(true, true, 0))
        assertFalse(canUseMessageChannel(true, true, null))
        assertFalse(canUseMessageChannel(false, true, 3))
        assertFalse(canUseMessageChannel(true, false, 3))
        assertTrue(canUseMessageChannel(true, true, 1))
    }

    @Test fun disabledNotificationsAreHandledRatherThanReplayedAfterOptIn() {
        assertEquals(NotificationAction.DISABLED, notificationAction(false, false, true))
        // Disabling OS notifications must not suppress foreground chat updates.
        assertEquals(NotificationAction.FOREGROUND, notificationAction(false, true, true))
        assertEquals(NotificationAction.FOREGROUND, notificationAction(false, true, false))
    }

    @Test fun foregroundDoesNotNeedNotificationPermissionOrAVisibleChannel() {
        assertEquals(NotificationAction.FOREGROUND, notificationAction(true, true, false))
        assertEquals(NotificationAction.FOREGROUND, notificationAction(true, true, true))
    }

    @Test fun backgroundBlockedChannelsRemainPendingAndOpenChannelsSubmit() {
        assertEquals(NotificationAction.BLOCKED, notificationAction(true, false, false))
        assertEquals(NotificationAction.SUBMIT, notificationAction(true, false, true))
    }

    @Test fun eachNotificationStateHasFourNonemptyTranslations() {
        listOf("pending", "submitted", "foreground", "disabled", "expired").forEach { state ->
            val key = "Schedule notification $state"
            assertTrue(UiStrings.catalog.containsKey(key))
            UiStrings.languages.forEach { assertTrue(UiStrings.text(it, key).isNotBlank()) }
        }
    }

    @Test fun replayHonorsOvernightQuietHoursAndDisabledQuietHours() {
        assertTrue(scheduledQuietHour(23, 22, 8))
        assertTrue(scheduledQuietHour(7, 22, 8))
        assertFalse(scheduledQuietHour(8, 22, 8))
        assertFalse(scheduledQuietHour(12, 22, 8))
        assertTrue(scheduledQuietHour(10, 9, 12))
        assertFalse(scheduledQuietHour(12, 9, 12))
        assertFalse(scheduledQuietHour(23, 0, 0))
    }
}
