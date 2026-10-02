package com.adaptive.companion.scheduler

object BackgroundPolicy {
    const val SYSTEM = "system"
    const val RESIDENT = "resident"
    fun defaultMode(@Suppress("UNUSED_PARAMETER") isFull: Boolean) = RESIDENT
    fun sanitize(mode: String) = if (mode == RESIDENT) RESIDENT else SYSTEM
}
