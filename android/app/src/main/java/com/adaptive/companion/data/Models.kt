package com.adaptive.companion.data

import org.json.JSONArray
import org.json.JSONObject

data class ChatMessage(
    val id: String,
    val conversationId: String,
    val role: String,
    val content: String,
    val timestamp: String,
    val status: String = "sent",
    val error: String? = null,
    val replyToId: String? = null,
    val learningStatus: String = "not_applicable",
    val transient: Boolean = false,
    val deliveryParts: List<DeliveryPart> = emptyList(),
    val persistedMessageId: String? = null,
    val imagePath: String? = null,
    val replySourceIds: List<String> = emptyList(),
)

fun ChatMessage.persistedId(): String = persistedMessageId ?: if (transient && role == "assistant") id.substringBeforeLast("_") else id

fun ChatMessage.bubbles(): List<ChatMessage> = if (role != "assistant" || deliveryParts.isEmpty()) listOf(this) else
    deliveryParts.mapIndexed { index, part -> copy(id = "${id}_$index", content = part.text,
        deliveryParts = emptyList(), persistedMessageId = id) }

/** A history refresh must not erase a send still queued behind the model mutex. */
fun mergeChatHistory(saved: List<ChatMessage>, visible: List<ChatMessage>): List<ChatMessage> {
    val savedIds = saved.mapTo(mutableSetOf()) { it.id }
    return saved + visible.filter { it.transient && it.role == "user" && it.id !in savedIds }
}

data class DeliveryPart(val text: String, val delayMs: Long)

data class ChatResult(
    val response: String,
    val userMessageId: String,
    val assistantMessageId: String,
    val deliveryParts: List<DeliveryPart>,
    val scheduledMessageId: String?,
    val deferred: Boolean = false,
)

data class ScheduledIntent(
    val id: String,
    val conversationId: String,
    val scheduledAt: String,
    val topic: String,
    val draftIntent: String,
    val reason: String,
    val importance: Double,
    val status: String,
    val notificationStatus: String = "",
)

data class OnboardingQuestion(
    val id: String,
    val prompt: String,
    val kind: String,
    val section: String,
    val defaultValue: Float?,
    val target: String = "user",
    val options: List<String> = emptyList(),
)

data class OnboardingStatus(
    val state: String,
    val answered: Int,
    val total: Int,
    val nextIndex: Int,
    val answers: Map<String, Any?>,
    val questions: List<OnboardingQuestion>,
    val recommendedIds: List<String> = FIRST_TEN_IDS,
    val resumeIndex: Int = nextIndex,
    val fullInterview: Boolean = false,
) {
    val finished: Boolean get() = state == "completed" || state == "skipped"
    val firstTenComplete: Boolean get() = requiredInterviewComplete(answers, recommendedIds)
}

val FIRST_TEN_IDS = listOf("q01", "q06", "q07", "q11", "q19", "q36", "q37", "q38", "q39", "q40")

data class InterviewPosition(val full: Boolean, val page: Int)

fun interviewPosition(status: OnboardingStatus): InterviewPosition {
    val full = status.fullInterview && status.firstTenComplete
    val count = if (full) status.questions.size else status.recommendedIds.size
    val index = if (status.firstTenComplete) status.resumeIndex else status.recommendedIds.indexOfFirst {
        !requiredInterviewComplete(status.answers, listOf(it))
    }.coerceAtLeast(0)
    return InterviewPosition(full, (index / 5).coerceIn(0, ((count + 4) / 5).coerceAtLeast(1)))
}

fun requiredInterviewComplete(answers: Map<String, Any?>, required: List<String> = FIRST_TEN_IDS): Boolean =
    required.all { key -> when (val value = answers[key]) {
        is String -> value.isNotBlank()
        is Number -> value.toDouble().isFinite()
        else -> false
    } }

fun parseMessages(raw: String): List<ChatMessage> {
    val array = JSONArray(raw)
    return buildList {
        repeat(array.length()) { index ->
            val item = array.getJSONObject(index)
            addAll(parseMessageObject(item).bubbles())
        }
    }
}

fun parseMessage(raw: String): ChatMessage? =
    if (raw == "null") null else parseMessageObject(JSONObject(raw))

private fun parseMessageObject(item: JSONObject) = ChatMessage(
    id = item.getString("id"),
    conversationId = item.getString("conversation_id"),
    role = item.getString("role"),
    content = item.getString("content"),
    timestamp = item.getString("timestamp"),
    status = item.optString("status", "sent"),
    error = item.optNullableString("error"),
    replyToId = item.optNullableString("reply_to_id"),
    learningStatus = item.optString("learning_status", "not_applicable"),
    imagePath = item.optNullableString("image_path"),
    replySourceIds = item.optJSONArray("reply_source_ids")?.let { ids -> (0 until ids.length()).map { ids.getString(it) } }.orEmpty(),
    deliveryParts = item.optJSONObject("delivery_plan")?.optJSONArray("parts")?.let { parts ->
        (0 until parts.length()).map { i -> parts.getJSONObject(i).let { DeliveryPart(it.getString("text"), it.optLong("delay_ms")) } }
    }.orEmpty(),
)

fun parseChatResult(raw: String): ChatResult {
    val root = JSONObject(raw)
    val plan = root.getJSONObject("delivery_plan").getJSONArray("parts")
    val parts = buildList {
        repeat(plan.length()) { index ->
            val item = plan.getJSONObject(index)
            add(DeliveryPart(item.getString("text"), item.getLong("delay_ms")))
        }
    }
    return ChatResult(
        response = root.getString("response"),
        userMessageId = root.getString("user_message_id"),
        assistantMessageId = root.getString("assistant_message_id"),
        deliveryParts = parts,
        scheduledMessageId = root.optNullableString("scheduled_message"),
        deferred = root.optBoolean("deferred", false),
    )
}

fun parseScheduled(raw: String): List<ScheduledIntent> {
    val array = JSONArray(raw)
    return buildList {
        repeat(array.length()) { index ->
            val item = array.getJSONObject(index)
            add(ScheduledIntent(
                id = item.getString("id"),
                conversationId = item.getString("conversation_id"),
                scheduledAt = item.getString("scheduled_at"),
                topic = item.getString("topic"),
                draftIntent = item.getString("draft_intent"),
                reason = item.getString("reason"),
                importance = item.getDouble("importance"),
                status = item.getString("status"),
                notificationStatus = item.optString("notification_status").takeUnless { it == "null" }.orEmpty(),
            ))
        }
    }
}

fun parseOnboarding(raw: String): OnboardingStatus {
    val root = JSONObject(raw)
    val answerObject = root.getJSONObject("answers")
    val answers = answerObject.keys().asSequence().associateWith { key ->
        answerObject.opt(key).takeUnless { it == JSONObject.NULL }
    }
    val array = root.getJSONArray("questions")
    val questions = buildList {
        repeat(array.length()) { index ->
            val item = array.getJSONObject(index)
            add(OnboardingQuestion(
                id = item.getString("id"),
                prompt = item.getString("prompt"),
                kind = item.getString("kind"),
                section = item.getString("section"),
                defaultValue = if (item.isNull("default")) null else item.optDouble("default").toFloat(),
                target = item.optString("target", "user"),
                options = item.optJSONArray("options")?.let { options -> (0 until options.length()).map { options.getString(it) } } ?: emptyList(),
            ))
        }
    }
    return OnboardingStatus(
        state = root.getString("state"),
        answered = root.getInt("answered"),
        total = root.getInt("total"),
        nextIndex = root.getInt("next_index"),
        answers = answers,
        questions = questions,
        recommendedIds = root.optJSONArray("recommended_ids")?.let { ids -> (0 until ids.length()).map { ids.getString(it) } } ?: FIRST_TEN_IDS,
        resumeIndex = root.optInt("resume_index", root.getInt("next_index")),
        fullInterview = root.optBoolean("full_interview", false),
    )
}

private fun JSONObject.optNullableString(key: String): String? =
    if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() && it != "null" }
