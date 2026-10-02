package com.adaptive.companion.scheduler

import kotlinx.coroutines.CancellationException

/** Fixed text and local reminders must remain offline even when an API is configured. */
fun scheduledTaskNeedsNetwork(topic: String, providerConfigured: Boolean): Boolean =
    providerConfigured && !topic.startsWith("reminder:") && !topic.startsWith("custom:text:")

enum class NotificationAction { DISABLED, FOREGROUND, BLOCKED, SUBMIT }

fun scheduledQuietHour(hour: Int, start: Int, end: Int): Boolean = when {
    start == end -> false
    start > end -> hour >= start || hour < end
    else -> hour >= start && hour < end
}

fun notificationAction(enabled: Boolean, foreground: Boolean, channelAllowed: Boolean): NotificationAction = when {
    foreground -> NotificationAction.FOREGROUND
    !enabled -> NotificationAction.DISABLED
    !channelAllowed -> NotificationAction.BLOCKED
    else -> NotificationAction.SUBMIT
}

/** Local housekeeping after any runner saves a user reply, not just the visible chat. */
suspend fun <T> planDeliveredReplyCheckIn(
    sent: Boolean,
    userMessageId: String?,
    isCurrent: () -> Boolean,
    plan: suspend () -> T?,
    schedule: (T) -> Unit,
) {
    if (!sent || userMessageId.isNullOrBlank() || userMessageId == "null" || !isCurrent()) return
    try {
        val next = plan() ?: return
        if (isCurrent()) schedule(next)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        // A check-in failure cannot turn an already-saved reply into a failed turn.
    }
}
