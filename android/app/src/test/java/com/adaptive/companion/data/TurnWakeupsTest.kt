package com.adaptive.companion.data

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class TurnWakeupsTest {
    @Test fun signalDuringStaleEmptyReadIsNotLost() = runTest {
        val wakeups = TurnWakeups()
        wakeups.signal() // Enqueue finished before the old query returned empty.
        val waiting = async { wakeups.await() }
        runCurrent()
        assertTrue(waiting.isCompleted)
    }

    @Test fun idleDraftWaitsWithoutPollingUntilInputChanges() = runTest {
        val wakeups = TurnWakeups()
        val waiting = async { wakeups.await() }
        advanceTimeBy(86_400_000)
        runCurrent()
        assertFalse(waiting.isCompleted)
        wakeups.signal()
        runCurrent()
        assertTrue(waiting.isCompleted)
    }

    @Test fun typingInterruptsTimer() = runTest {
        val wakeups = TurnWakeups()
        val waiting = async { wakeups.await(20_000) }
        advanceTimeBy(10_000)
        wakeups.signal()
        runCurrent()
        assertTrue(waiting.isCompleted)
    }

    @Test fun bufferedBurstSignalsCoalesceAndIdleTimerExpires() = runTest {
        val wakeups = TurnWakeups()
        repeat(50) { wakeups.signal() }
        wakeups.await()
        val next = async { wakeups.await(20_000) }
        runCurrent()
        assertFalse(next.isCompleted)
        advanceTimeBy(20_000)
        runCurrent()
        assertTrue(next.isCompleted)
    }

    @Test fun remainingIdleTimeHonorsDraftAndNewTouches() {
        assertNull(composerWaitMillis(true, 0, Long.MAX_VALUE, 20))
        assertEquals(15_000L, composerWaitMillis(false, 5_000, 10_000, 20))
        assertEquals(0L, composerWaitMillis(false, 5_000, 25_000, 20))
        assertEquals(20_000L, composerWaitMillis(false, 10_000, 5_000, 20))
    }
}
