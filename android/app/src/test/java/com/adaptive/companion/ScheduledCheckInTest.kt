package com.adaptive.companion

import com.adaptive.companion.scheduler.planDeliveredReplyCheckIn
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ScheduledCheckInTest {
    @Test fun successfulBackgroundReplyPlansAndSchedulesOneLocalCheckIn() = runTest {
        var plans = 0
        val scheduled = mutableListOf<String>()
        planDeliveredReplyCheckIn(true, "msg_synthetic", { true }, {
            plans++
            "checkin_synthetic"
        }, { scheduled += it })
        assertEquals(1, plans)
        assertEquals(listOf("checkin_synthetic"), scheduled)
    }

    @Test fun proactiveMessagesUnsentRepliesAndChangedHistoryDoNotPlan() = runTest {
        for ((sent, source, current) in listOf(
            Triple(false, "msg_synthetic", true), Triple(true, null, true),
            Triple(true, "", true), Triple(true, "null", true),
            Triple(true, "msg_synthetic", false),
        )) {
            var plans = 0
            planDeliveredReplyCheckIn(sent, source, { current }, { plans++; "checkin" }, {
                fail("Ineligible replies must not schedule a check-in")
            })
            assertEquals(0, plans)
        }
    }

    @Test fun plannerCanDeclineAndAnInvalidatedPlanIsNotScheduled() = runTest {
        planDeliveredReplyCheckIn<String>(true, "msg_synthetic", { true }, { null }, {
            fail("A declined check-in must not be scheduled")
        })
        var current = true
        planDeliveredReplyCheckIn(true, "msg_synthetic", { current }, {
            current = false
            "checkin_synthetic"
        }, { fail("A history mutation invalidates scheduling") })
    }

    @Test fun housekeepingErrorsDoNotFailTheSavedReply() = runTest {
        planDeliveredReplyCheckIn<String>(true, "msg_synthetic", { true }, {
            throw IllegalStateException("synthetic planner failure")
        }, { fail("Failed planning cannot schedule") })
        planDeliveredReplyCheckIn(true, "msg_synthetic", { true }, { "checkin" }, {
            throw IllegalStateException("synthetic scheduler failure")
        })
    }

    @Test fun cancellationStillPropagates() = runTest {
        val cancellation = CancellationException("synthetic cancellation")
        try {
            planDeliveredReplyCheckIn<String>(true, "msg_synthetic", { true }, { throw cancellation }, {})
            fail("Cancellation must propagate")
        } catch (caught: CancellationException) {
            assertSame(cancellation, caught)
        }
    }

    @Test fun allScheduledRunnersUseTheSharedPostReplyPlanner() {
        val delivery = File("src/main/java/com/adaptive/companion/scheduler/ScheduledDelivery.kt").readText()
        assertTrue(delivery.contains("planDeliveredReplyCheckIn("))
        assertTrue(delivery.contains("isCurrent = { ChatUpdates.history.token() == token }"))
        assertTrue(delivery.contains("plan = { bridge.planCheckIn() }"))
        assertTrue(delivery.contains("schedule = { WorkScheduler.schedule(context, it, requireNetwork = true) }"))
        listOf("ProactiveWorker", "CompanionResidentService").forEach { runner ->
            val source = File("src/main/java/com/adaptive/companion/scheduler/$runner.kt").readText()
            assertTrue(source.contains("ScheduledDelivery.execute("))
        }
    }
}
