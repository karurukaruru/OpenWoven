package com.adaptive.companion

import com.adaptive.companion.scheduler.BackgroundPolicy
import com.adaptive.companion.data.AppSettings
import com.adaptive.companion.data.sanitized
import org.junit.Assert.*
import org.junit.Test

class BackgroundPolicyTest {
    @Test fun editionDefaultsMatchTheRequestedModes() {
        assertEquals(BackgroundPolicy.RESIDENT, BackgroundPolicy.defaultMode(true))
        assertEquals(BackgroundPolicy.RESIDENT, BackgroundPolicy.defaultMode(false))
    }
    @Test fun unknownModeCannotSilentlyEnableBackgroundOrGoogle() {
        assertEquals(BackgroundPolicy.SYSTEM, AppSettings(backgroundMode = "fcm").sanitized().backgroundMode)
        assertEquals(BackgroundPolicy.RESIDENT, AppSettings(backgroundMode = "resident").sanitized().backgroundMode)
    }
}
