package com.adaptive.companion.data

/** Focus alone isn't an indefinite typing lock. Only this app's composer counts. */
fun composerReady(hasDraft: Boolean, lastActivityMs: Long, nowMs: Long, idleSeconds: Int): Boolean =
    composerWaitMillis(hasDraft, lastActivityMs, nowMs, idleSeconds) == 0L

/** null means wait for a real input event, not an endless polling timer. */
fun composerWaitMillis(hasDraft: Boolean, lastActivityMs: Long, nowMs: Long, idleSeconds: Int): Long? =
    if (hasDraft) null else (idleSeconds.coerceIn(10, 60) * 1000L -
        (nowMs - lastActivityMs).coerceAtLeast(0)).coerceAtLeast(0)

fun canSendImage(providerConfigured: Boolean, modelSupportsVision: Boolean): Boolean =
    providerConfigured && modelSupportsVision
