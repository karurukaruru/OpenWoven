package com.adaptive.companion.data

import org.junit.Assert.*
import org.junit.Test

class HistoryChangeGuardTest {
    @Test fun lateRepliesCannotReappearDuringOrAfterDeletion() {
        val guard = HistoryChangeGuard()
        val old = guard.token()!!
        var published = 0
        assertTrue(guard.publishIfCurrent(old) { published++ })
        guard.beginChange()
        assertNull(guard.token())
        assertFalse(guard.publishIfCurrent(old) { published++ })
        guard.endChange()
        assertFalse(guard.publishIfCurrent(old) { published++ })
        assertTrue(guard.publishIfCurrent(guard.token()!!) { published++ })
        assertEquals(2, published)
    }

    @Test fun sequentialMutationsInvalidateAllPriorTokens() {
        val guard = HistoryChangeGuard()
        val first = guard.token()!!
        guard.beginChange(); guard.endChange()
        val second = guard.token()!!
        guard.beginChange(); guard.endChange()
        assertFalse(guard.publishIfCurrent(first) { fail("old") })
        assertFalse(guard.publishIfCurrent(second) { fail("old") })
        assertTrue(guard.publishIfCurrent(guard.token()!!) { })
    }

    @Test fun overlappingMutationsStayBlockedUntilBothFinish() {
        val guard = HistoryChangeGuard()
        guard.beginChange(); guard.beginChange()
        guard.endChange()
        assertNull(guard.token())
        guard.endChange()
        assertNotNull(guard.token())
    }
}
