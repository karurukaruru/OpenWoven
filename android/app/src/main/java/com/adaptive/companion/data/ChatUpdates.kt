package com.adaptive.companion.data

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/** UI hint only; the database remains the durable source after process death. */
object ChatUpdates {
    val history = HistoryChangeGuard()
    private val updates = MutableSharedFlow<String>(extraBufferCapacity = 16)
    val messages = updates.asSharedFlow()
    // A foreground outbox item must remain pending if nobody can accept its hint.
    fun notifyMessage(id: String): Boolean = updates.subscriptionCount.value > 0 && updates.tryEmit(id)
}
