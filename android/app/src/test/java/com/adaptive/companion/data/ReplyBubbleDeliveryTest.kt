package com.adaptive.companion.data

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ReplyBubbleDeliveryTest {
    private fun reply(id: String = "reply", first: Long = 0) = ChatMessage(
        id, "default", "assistant", "整段回复", "2026-10-01T00:00:00Z",
        deliveryParts = listOf(DeliveryPart("好呀", first), DeliveryPart("明天见", 1000), DeliveryPart("长一点的第三句", 2000)),
    )

    @Test fun bubblesAppearOneByOneWithRelativeWaits() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val seen = mutableListOf<Pair<String, Long>>()
        launch {
            delivery.present(message.id, { message }, { AppSettings() }, { true },
                { bubble -> seen.any { it.first == bubble.id } }, {},
                { _, bubble -> seen += bubble.id to testScheduler.currentTime })
        }
        runCurrent()
        assertEquals(listOf("reply_0" to 0L), seen)
        advanceTimeBy(999); runCurrent()
        assertEquals(1, seen.size)
        advanceTimeBy(1); runCurrent()
        assertEquals("reply_1" to 1000L, seen.last())
        advanceTimeBy(1999); runCurrent()
        assertEquals(2, seen.size)
        advanceTimeBy(1); runCurrent()
        assertEquals("reply_2" to 3000L, seen.last())
    }

    @Test fun proactiveBackgroundHintUsesTheSamePacedLaneAndDoesNotExposeWholeText() = runTest {
        val delivery = ReplyBubbleDelivery()
        // A proactive opening has no user reply target. Worker/resident/outbox
        // hints still enter the exact same persisted-message delivery lane.
        val opening = reply("proactive").copy(replyToId = null, replySourceIds = emptyList(),
            content = "最近怎么样？\n那本书看完了吗？\n有空再聊",
            deliveryParts = listOf(DeliveryPart("最近怎么样？", 0),
                DeliveryPart("那本书看完了吗？", 1100), DeliveryPart("有空再聊", 900)))
        var visible = emptyList<ChatMessage>()
        launch {
            delivery.present(opening.id, { opening }, { AppSettings() }, { true },
                { bubble -> visible.any { it.id == bubble.id } }, {},
                { _, bubble -> visible = visible + bubble })
        }
        runCurrent()
        visible = delivery.mergeHistory(opening.bubbles(), visible)
        assertEquals(listOf("最近怎么样？"), visible.map { it.content })
        advanceTimeBy(1099); runCurrent()
        assertEquals(1, visible.size)
        advanceTimeBy(1); runCurrent()
        assertEquals(listOf("最近怎么样？", "那本书看完了吗？"), visible.map { it.content })
        advanceTimeBy(900); runCurrent()
        assertEquals(opening.bubbles(), visible)
        assertTrue(visible.all { it.persistedId() == opening.id })
    }

    @Test fun retryRefreshCannotRevealAnyNewBubbleBeforeItsWait() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply(first = 350)
        var visible = emptyList<ChatMessage>()
        launch {
            delivery.present(message.id, {
                visible = delivery.mergeHistory(message.bubbles(), visible)
                message
            }, { AppSettings() }, { true }, { bubble -> visible.any { it.id == bubble.id } }, {},
                { _, bubble -> visible = visible + bubble })
        }
        runCurrent()
        assertTrue(visible.isEmpty())
        advanceTimeBy(350); runCurrent()
        assertEquals(listOf("reply_0"), visible.map { it.id })
        visible = delivery.mergeHistory(message.bubbles(), visible)
        assertEquals(listOf("reply_0"), visible.map { it.id })
        advanceTimeBy(999); runCurrent()
        assertEquals(1, visible.size)
        advanceTimeBy(1); runCurrent()
        assertEquals(listOf("reply_0", "reply_1"), visible.map { it.id })
        advanceTimeBy(2000); runCurrent()
        assertEquals(message.bubbles(), visible)
    }

    @Test fun queuedReplyIsHiddenAndDifferentDeliveryPathsDoNotInterleave() = runTest {
        val delivery = ReplyBubbleDelivery()
        val first = reply("a")
        val second = reply("b")
        var visible = emptyList<ChatMessage>()
        val saved = first.bubbles() + second.bubbles()
        for (message in listOf(first, second)) launch {
            delivery.present(message.id, { message }, { AppSettings() }, { true },
                { bubble -> visible.any { it.id == bubble.id } }, {}, { _, bubble -> visible = visible + bubble })
        }
        runCurrent()
        visible = delivery.mergeHistory(saved, visible)
        assertEquals(listOf("a_0"), visible.map { it.id })
        advanceTimeBy(3000); runCurrent()
        assertEquals(listOf("a_0", "a_1", "a_2", "b_0"), visible.map { it.id })
        visible = delivery.mergeHistory(saved, visible)
        assertEquals(4, visible.size)
        advanceTimeBy(3000); runCurrent()
        assertEquals(saved, visible)
    }

    @Test fun typingPausesPublicationAndLaterGapStartsAfterActualPublication() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val gate = CompletableDeferred<Unit>()
        val seen = mutableListOf<Pair<String, Long>>()
        launch {
            delivery.present(message.id, { message }, { AppSettings() }, { true }, { false },
                { if (seen.size == 1) gate.await() },
                { _, bubble -> seen += bubble.id to testScheduler.currentTime })
        }
        runCurrent()
        advanceTimeBy(3000); runCurrent()
        assertEquals(listOf("reply_0" to 0L), seen)
        gate.complete(Unit); runCurrent()
        assertEquals("reply_1" to 3000L, seen.last())
        advanceTimeBy(1999); runCurrent()
        assertEquals(2, seen.size)
        advanceTimeBy(1); runCurrent()
        assertEquals("reply_2" to 5000L, seen.last())
    }

    @Test fun duplicateHintsDoNotRepeatBubbles() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val seen = mutableListOf<ChatMessage>()
        var loads = 0
        repeat(2) { launch {
            delivery.present(message.id, { loads++; message }, { AppSettings() }, { true },
                { bubble -> seen.any { it.id == bubble.id } }, {}, { _, bubble -> seen += bubble })
        } }
        advanceTimeBy(3000); runCurrent()
        assertEquals(message.bubbles(), seen)
        assertEquals(1, loads)
    }

    @Test fun historyDeletionDuringGapNeverPublishesOrResurrectsTheTail() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val history = HistoryChangeGuard()
        val token = history.token()
        var visible = emptyList<ChatMessage>()
        launch {
            delivery.present(message.id, { message }, { AppSettings() }, { history.token() == token },
                { false }, {}, { _, bubble -> visible = visible + bubble })
        }
        runCurrent()
        history.beginChange()
        visible = delivery.mergeHistory(emptyList(), visible)
        history.endChange()
        advanceTimeBy(3000); runCurrent()
        assertTrue(visible.isEmpty())
    }

    @Test fun cancellingQueuedHintDoesNotLeaveHistoryPermanentlyMasked() = runTest {
        val delivery = ReplyBubbleDelivery()
        val a = reply("a")
        val b = reply("b")
        val first = launch { delivery.present(a.id, { a }, { AppSettings() }, { true }, { false }, {}, { _, _ -> }) }
        val queued = launch { delivery.present(b.id, { b }, { AppSettings() }, { true }, { false }, {}, { _, _ -> }) }
        runCurrent()
        assertTrue(delivery.mergeHistory(b.bubbles(), emptyList()).isEmpty())
        queued.cancelAndJoin()
        assertEquals(b.bubbles(), delivery.mergeHistory(b.bubbles(), emptyList()))
        first.cancelAndJoin()
        assertEquals(a.bubbles(), delivery.mergeHistory(a.bubbles(), emptyList()))
    }

    @Test fun disabledTimingKeepsSeparateBubblesWithoutWaits() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val seen = mutableListOf<ChatMessage>()
        launch { delivery.present(message.id, { message }, { AppSettings(naturalTiming = false) },
            { true }, { false }, {}, { _, bubble -> seen += bubble }) }
        runCurrent()
        assertEquals(message.bubbles(), seen)
        assertEquals(0L, testScheduler.currentTime)
    }

    @Test fun missingOrLegacyGapsUseCurrentTextLengthWithoutDelayingFirstBubble() {
        val message = reply().copy(deliveryParts = listOf(
            DeliveryPart("好呀", 0), DeliveryPart("明天见", 0), DeliveryPart("明".repeat(40), 200)))
        assertEquals(0L, bubbleDelayMillis(message, 0, AppSettings()))
        assertEquals(840L, bubbleDelayMillis(message, 1, AppSettings()))
        assertEquals(1950L, bubbleDelayMillis(message, 2, AppSettings()))
    }

    @Test fun customGapLimitsAndTimingOffAreRespected() {
        val message = reply(first = 20_000)
        assertEquals(900L, bubbleDelayMillis(message, 0, AppSettings()))
        assertEquals(2500L, bubbleDelayMillis(message.copy(deliveryParts = listOf(
            DeliveryPart("first", 0), DeliveryPart("second", 20_000))), 1, AppSettings()))
        assertEquals(350L, bubbleDelayMillis(message, 1, AppSettings(minDelayMs = 100, maxDelayMs = 350)))
        assertEquals(0L, bubbleDelayMillis(message, 1, AppSettings(naturalTiming = false)))
        assertEquals(0L, bubbleDelayMillis(message, 1, AppSettings(baseDelayMs = 0, delayPerCharacterMs = 0,
            jitterMs = 0, minDelayMs = 0, maxDelayMs = 0)))
    }

    @Test fun oldStockTupleUpgradesWithoutChangingOtherPreferences() {
        val old = AppSettings(baseDelayMs = 250, delayPerCharacterMs = 12, jitterMs = 180,
            minDelayMs = 120, maxDelayMs = 1800, naturalTiming = false, turnIdleSeconds = 30, contextBudget = 8000)
        val upgraded = old.upgradeLegacyBubbleTiming()
        assertEquals(750, upgraded.baseDelayMs)
        assertEquals(30, upgraded.delayPerCharacterMs)
        assertEquals(150, upgraded.jitterMs)
        assertEquals(800, upgraded.minDelayMs)
        assertEquals(2500, upgraded.maxDelayMs)
        assertFalse(upgraded.naturalTiming)
        assertEquals(30, upgraded.turnIdleSeconds)
        assertEquals(8000, upgraded.contextBudget)
        listOf(old.copy(baseDelayMs = 251), old.copy(delayPerCharacterMs = 13), old.copy(jitterMs = 181),
            old.copy(minDelayMs = 121), old.copy(maxDelayMs = 1801)).forEach { custom ->
            assertEquals(custom, custom.upgradeLegacyBubbleTiming())
        }
    }

    @Test fun pendingUserSendsSurviveAFilteredHistoryRefresh() = runTest {
        val delivery = ReplyBubbleDelivery()
        val message = reply()
        val pending = ChatMessage("pending", "default", "user", "再补一句", "now", transient = true)
        var visible = listOf(pending)
        val job = launch { delivery.present(message.id, { message }, { AppSettings() }, { true }, { false }, {},
            { _, bubble -> visible = visible + bubble }) }
        runCurrent()
        val merged = delivery.mergeHistory(message.bubbles(), visible)
        assertEquals(listOf("reply_0", "pending"), merged.map { it.id })
        job.cancelAndJoin()
    }
}
