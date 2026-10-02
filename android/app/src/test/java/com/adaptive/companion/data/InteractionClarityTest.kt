package com.adaptive.companion.data

import com.adaptive.companion.ui.UiStrings
import org.junit.Assert.*
import org.junit.Test

class InteractionClarityTest {
    @Test fun allTenSlidersHaveDistinctTranslatedEndpoints() {
        (21..30).forEach {
            val endpoints = interviewSliderEndpoints("q$it")
            assertNotEquals(endpoints.first, endpoints.second)
            listOf(endpoints.first, endpoints.second).forEach { key ->
                UiStrings.languages.forEach { language -> assertNotEquals(key, UiStrings.text(language, key)) }
            }
        }
        assertEquals("Slider short" to "Slider detailed", interviewSliderEndpoints("q21"))
        assertEquals("Slider wait for me" to "Slider start topics", interviewSliderEndpoints("q28"))
    }

    @Test fun automaticPermissionRequestIsOnceOnlyAndOnlyOnAndroid13Plus() {
        assertTrue(shouldAutoRequestNotifications(33, false, false))
        assertFalse(shouldAutoRequestNotifications(32, false, false))
        assertFalse(shouldAutoRequestNotifications(36, true, false))
        assertFalse(shouldAutoRequestNotifications(36, false, true))
    }

    @Test fun newMessagesDoNotDragSomeoneReadingOlderHistoryToBottom() {
        assertTrue(shouldFollowChat(0, -1, false))
        assertTrue(shouldFollowChat(30, 29, false))
        assertFalse(shouldFollowChat(30, 10, false))
        assertTrue(shouldFollowChat(30, 10, true))
    }

    @Test fun modelDraftConfirmationPreservesBoundariesAndNeverReplacesUserData() {
        val foundation = PersonaSettings(name = "Companion", boundaries = "no guilt",
            choices = mapOf("support" to "listen"), interview = mapOf("q36" to "calm"), generationMethod = "pending")
        val model = foundation.copy(name = "River", description = "fictional librarian", boundaries = "weaker",
            choices = mapOf("support" to "solutions"), generationMethod = "model")
        val confirmed = confirmGeneratedCharacter(foundation, model, "Sky")
        assertEquals("Sky", confirmed.name)
        assertEquals("fictional librarian", confirmed.description)
        assertEquals("no guilt", confirmed.boundaries)
        assertEquals(foundation.choices, confirmed.choices)
        assertEquals(foundation.interview, confirmed.interview)
        assertEquals(foundation, confirmGeneratedCharacter(foundation, model.copy(interview = emptyMap()), "Sky"))
    }

    @Test fun reopeningKeepsGeneratedProfileAndExplicitPendingName() {
        val model = PersonaSettings(name = "River", description = "saved profile", interview = mapOf("q36" to "calm"),
            generationMethod = "model")
        assertEquals(model, retainGeneratedCharacter(model, model.copy(description = "local fallback"), ""))
        assertNull(retainGeneratedCharacter(model, model.copy(interview = emptyMap()), ""))
        assertEquals("", editableCharacterName(model.copy(name = "Companion", generationMethod = "pending"), true))
        assertEquals("MyName", editableCharacterName(model.copy(name = "MyName", generationMethod = "pending"), true))
        assertEquals("River", editableCharacterName(model, true))
    }
}
