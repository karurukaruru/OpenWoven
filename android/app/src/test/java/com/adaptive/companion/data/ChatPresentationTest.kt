package com.adaptive.companion.data

import com.adaptive.companion.ui.UiStrings
import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ChatPresentationTest {
    @Test fun waitingMessageShowsOnlyNormalSentMarkNotRuntimeExplanation() {
        assertEquals("✓", chatStatusKey("waiting"))
        assertEquals("✓", chatStatusKey("sent"))
        assertEquals("Sending", chatStatusKey("pending"))
        assertEquals("Failed", chatStatusKey("failed"))
    }

    @Test fun providerDiagnosticsStayOutOfTalkButImageErrorsRemainActionable() {
        listOf("API key or provider access was rejected.", "Selected model does not support images",
            "The request timed out. Your message was saved; you can retry.").forEach {
            assertEquals("Chat action failed", chatErrorKey(it))
        }
        listOf("Image could not be opened", "At most four images per turn").forEach {
            assertEquals(it, chatErrorKey(it))
        }
    }

    @Test fun presentationKeysHaveFourTranslations() {
        listOf("Chat action failed", "Reply again").forEach { key ->
            val translations = UiStrings.catalog.getValue(key)
            assertEquals(4, translations.size)
            assertTrue(translations.all { it.isNotBlank() })
            UiStrings.languages.filter { it != "en-US" }.forEach { language ->
                assertNotEquals(key, UiStrings.text(language, key))
            }
        }
    }

    @Test fun talkDoesNotRenderTimersPreparationOrAutomaticFeedback() {
        val source = File("src/main/java/com/adaptive/companion/ui/ChatScreen.kt").readText()
        val main = source.substringBefore("private fun MessageBubble")
        listOf("Waiting for draft", "Waiting for turn", "turnIdleSeconds", "Preparing a reply",
            "Image upload notice", "notification_permission", "PeriodicFeedbackDialog(").forEach { assertFalse(it, main.contains(it)) }
        assertFalse(source.contains("稍后回复（后台可能延后）"))
    }

    @Test fun settingsRetainDisclosurePermissionAndImageCostNotices() {
        val settings = File("src/main/java/com/adaptive/companion/ui/SettingsScreens.kt").readText()
        listOf("Role transparency", "Notification permission hint", "Image upload notice", "Turn wait help").forEach {
            assertTrue(it, settings.substringBefore("fun AboutScreen").contains("tr(\"$it\")"))
        }
        assertTrue(UiStrings.text("zh-CN", "Role transparency").contains("AI"))
    }

    @Test fun manualScheduledExecutionUsesTheSameNotificationAndBubbleFlow() {
        val source = File("src/main/java/com/adaptive/companion/ui/CompanionViewModel.kt").readText()
        val runNow = source.substringAfter("fun runScheduled(id: String)").substringBefore("fun cancelScheduled")
        assertTrue(runNow.contains("ScheduledDelivery.execute(context, bridge, id, force = true)"))
        assertFalse(runNow.contains("initialize()"))
        val delivery = File("src/main/java/com/adaptive/companion/scheduler/ScheduledDelivery.kt").readText()
        assertTrue(delivery.contains("bridge.executeScheduled(id, force)"))
    }

    @Test fun settingsTaskChangesDoNotRestartCoreAndHistoryRefreshesAreVersionGuarded() {
        val source = File("src/main/java/com/adaptive/companion/ui/CompanionViewModel.kt").readText()
        val taskChanges = source.substringAfter("fun cancelScheduled(id: String)").substringBefore("fun clearError")
        assertFalse(taskChanges.contains("initialize()"))
        assertTrue(taskChanges.contains("launchUiOperation"))
        assertTrue(taskChanges.contains("ChatUpdates.history.publishIfCurrent(token)"))
        assertTrue(taskChanges.contains("replyDelivery.mergeHistory"))
        val initialize = source.substringAfter("suspend fun initialize()").substringBefore("fun send(text:")
        assertTrue(initialize.contains("ChatUpdates.history.token() ?: return"))
        assertTrue(initialize.contains("ChatUpdates.history.publishIfCurrent(token)"))
    }
}
