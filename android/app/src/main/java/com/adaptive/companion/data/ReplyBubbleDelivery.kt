package com.adaptive.companion.data

import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Relative waits, not deadlines measured from generation/start of the whole reply. */
fun bubbleDelayMillis(message: ChatMessage, index: Int, settings: AppSettings): Long {
    if (!settings.naturalTiming || message.role != "assistant") return 0
    val planned = message.deliveryParts.getOrNull(index)?.delayMs
    val maximum = settings.maxDelayMs.coerceIn(0, 5_000).toLong()
    if (index == 0) return (planned ?: 0).coerceIn(0, minOf(900L, maximum))
    val minimum = settings.minDelayMs.toLong().coerceIn(0, maximum)
    val text = message.deliveryParts.getOrNull(index)?.text ?: message.content
    // Old queued plans may still have zero/sub-minimum gaps. Rebuild those gaps
    // from the current settings without adding another model/API request.
    val fallback = settings.baseDelayMs.toLong() +
        text.codePointCount(0, text.length) * settings.delayPerCharacterMs.toLong()
    return (planned?.takeIf { it >= minimum } ?: fallback).coerceIn(minimum, maximum)
}

/** Main-dispatcher confined. Normal delivery and retries share one reveal lane. */
class ReplyBubbleDelivery {
    private val lane = Mutex()
    private val active = mutableSetOf<String>()

    fun mergeHistory(saved: List<ChatMessage>, visible: List<ChatMessage>): List<ChatMessage> {
        val visibleIds = visible.mapTo(mutableSetOf()) { it.id }
        // Only filter persisted candidates: never resurrect a deleted transient
        // assistant bubble from the old UI snapshot.
        val revealed = saved.filter { it.role != "assistant" || it.persistedId() !in active || it.id in visibleIds }
        return mergeChatHistory(revealed, visible)
    }

    suspend fun present(
        messageId: String,
        load: suspend () -> ChatMessage?,
        settings: () -> AppSettings,
        isCurrent: () -> Boolean,
        isVisible: (ChatMessage) -> Boolean,
        awaitComposer: suspend () -> Unit,
        publish: (ChatMessage, ChatMessage) -> Unit,
    ) {
        // Register before waiting for the lane or loading history, so a refresh
        // cannot expose a queued reply while a different reply is still showing.
        // Execution and foreground outbox flushing can report the same ID.
        // An in-flight hint needs neither another lease nor another DB load.
        if (!active.add(messageId)) return
        try {
            lane.withLock {
                if (!isCurrent()) return@withLock
                val message = load() ?: return@withLock
                if (message.role != "assistant") {
                    if (isCurrent()) publish(message, message)
                    return@withLock
                }
                for ((index, bubble) in message.bubbles().withIndex()) {
                    if (!isCurrent()) break
                    if (isVisible(bubble)) continue
                    val wait = bubbleDelayMillis(message, index, settings())
                    if (wait > 0) delay(wait)
                    if (!isCurrent()) break
                    awaitComposer()
                    if (!isCurrent()) break
                    if (!isVisible(bubble)) publish(message, bubble)
                }
            }
        } finally {
            active.remove(messageId)
        }
    }
}
