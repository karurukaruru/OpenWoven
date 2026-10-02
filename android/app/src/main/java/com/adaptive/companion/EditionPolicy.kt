package com.adaptive.companion

import com.adaptive.companion.ui.Screen

object EditionPolicy {
    fun advancedSettingsVisible(isFullEdition: Boolean, adminUnlocked: Boolean): Boolean =
        isFullEdition || adminUnlocked

    fun resolveScreen(screen: Screen, isFullEdition: Boolean, adminUnlocked: Boolean): Screen =
        if (!advancedSettingsVisible(isFullEdition, adminUnlocked) && screen in setOf(
                Screen.PROVIDER, Screen.AUL, Screen.MEMORY, Screen.SCHEDULER, Screen.ADVANCED,
            )) Screen.SETTINGS else screen
}
