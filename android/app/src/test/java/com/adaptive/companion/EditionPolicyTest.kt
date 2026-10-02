package com.adaptive.companion

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test
import com.adaptive.companion.ui.Screen

class EditionPolicyTest {
    @Test fun fullEditionAlwaysShowsAdvancedSettings() {
        assertTrue(EditionPolicy.advancedSettingsVisible(true, false))
    }

    @Test fun lockedEditionRequiresAdminUnlock() {
        assertFalse(EditionPolicy.advancedSettingsVisible(false, false))
        assertTrue(EditionPolicy.advancedSettingsVisible(false, true))
    }

    @Test fun restoredAdvancedScreensCannotBypassTheLockedGate() {
        for (screen in listOf(Screen.PROVIDER, Screen.AUL, Screen.MEMORY, Screen.SCHEDULER, Screen.ADVANCED)) {
            assertEquals(Screen.SETTINGS, EditionPolicy.resolveScreen(screen, false, false))
            assertEquals(screen, EditionPolicy.resolveScreen(screen, false, true))
            assertEquals(screen, EditionPolicy.resolveScreen(screen, true, false))
        }
        assertEquals(Screen.ABOUT, EditionPolicy.resolveScreen(Screen.ABOUT, false, false))
    }

    @Test fun usersCanInspectTheirOwnCalendarWithoutAdministratorAccess() {
        assertEquals(Screen.ARCHIVES, EditionPolicy.resolveScreen(Screen.ARCHIVES, false, false))
    }
}
