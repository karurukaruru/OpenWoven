package com.adaptive.companion.data

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withTimeoutOrNull

/** A signal arriving during a database read remains available for the next wait. */
class TurnWakeups {
    private val signals = Channel<Unit>(Channel.CONFLATED)

    fun signal() { signals.trySend(Unit) }

    suspend fun await(waitMillis: Long? = null) {
        if (waitMillis == null) signals.receive()
        else withTimeoutOrNull(waitMillis.coerceAtLeast(1)) { signals.receive() }
    }
}
