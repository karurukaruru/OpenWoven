package com.adaptive.companion.data

/** Prevent late presentation/notifications from a pre-deletion history snapshot. */
class HistoryChangeGuard {
    private val lock = Any()
    private var epoch = 0L
    private var changes = 0

    fun token(): Long? = synchronized(lock) { if (changes > 0) null else epoch }
    fun beginChange() = synchronized(lock) { epoch++; changes++ }
    fun endChange() = synchronized(lock) { changes = (changes - 1).coerceAtLeast(0) }
    fun publishIfCurrent(token: Long, action: () -> Unit): Boolean = synchronized(lock) {
        if (changes > 0 || token != epoch) false else { action(); true }
    }
}
