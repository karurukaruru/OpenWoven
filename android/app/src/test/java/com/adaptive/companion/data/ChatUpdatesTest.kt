package com.adaptive.companion.data

import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.yield
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class ChatUpdatesTest {
    @Test fun noSubscriberDoesNotAcknowledgeForegroundDelivery() {
        assertFalse(ChatUpdates.notifyMessage("nobody_can_display_this"))
    }

    @Test fun fullUiBufferCanRetryTheMissingHint() = runBlocking {
        val release = CompletableDeferred<Unit>()
        val received = mutableListOf<String>()
        val subscription = launch(start = CoroutineStart.UNDISPATCHED) {
            ChatUpdates.messages.collect { received += it; release.await() }
        }
        try {
            assertTrue(ChatUpdates.notifyMessage("first"))
            yield()
            repeat(16) { assertTrue(ChatUpdates.notifyMessage("buffer_$it")) }
            assertFalse(ChatUpdates.notifyMessage("retry_this"))
            release.complete(Unit)
            withTimeout(2000) { while (received.size < 17) yield() }
            assertTrue(ChatUpdates.notifyMessage("retry_this"))
            withTimeout(2000) { while (received.size < 18) yield() }
            assertEquals("retry_this", received.last())
        } finally { subscription.cancelAndJoin() }
    }

    @Test fun scheduledMessageHintsReachAnActiveCollectorInOrder() = runBlocking {
        val received = mutableListOf<String>()
        val subscription = launch(start = CoroutineStart.UNDISPATCHED) {
            ChatUpdates.messages.take(2).toList(received)
        }
        ChatUpdates.notifyMessage("scheduled_first")
        ChatUpdates.notifyMessage("scheduled_second")
        withTimeout(2000) { subscription.join() }
        assertEquals(listOf("scheduled_first", "scheduled_second"), received)
    }
}
