package com.adaptive.companion.scheduler

import android.content.Context
import com.adaptive.companion.AppVisibility
import com.adaptive.companion.data.ChatUpdates
import com.adaptive.companion.data.CoreBridge
import com.adaptive.companion.data.SettingsStore
import com.adaptive.companion.notifications.NotificationHelper
import org.json.JSONObject
import java.time.LocalTime
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Both runners share one serialized bridge and an atomic database delivery commit. */
object ScheduledDelivery {
    private val notificationMutex = Mutex()

    suspend fun execute(context: Context, bridge: CoreBridge, id: String, force: Boolean = false): JSONObject {
        val token = ChatUpdates.history.token()
            ?: return JSONObject().put("sent", false).put("reason", "history change")
        val result = try { bridge.executeScheduled(id, force) }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (error: Exception) {
            bridge.scheduled().firstOrNull { it.id == id && it.topic.startsWith("reply:") }
                ?.let { ChatUpdates.history.publishIfCurrent(token) { ChatUpdates.notifyMessage(it.topic.removePrefix("reply:")) } }
            throw error
        }
        result.optString("user_message_id").takeIf { it.isNotBlank() && it != "null" }
            ?.let { ChatUpdates.history.publishIfCurrent(token) { ChatUpdates.notifyMessage(it) } }
        if (result.optBoolean("sent")) {
            ChatUpdates.history.publishIfCurrent(token) {
                ChatUpdates.notifyMessage(result.getString("message_id"))
            }
        }
        planDeliveredReplyCheckIn(
            sent = result.optBoolean("sent"),
            userMessageId = result.optString("user_message_id"),
            isCurrent = { ChatUpdates.history.token() == token },
            plan = { bridge.planCheckIn() },
            schedule = { WorkScheduler.schedule(context, it, requireNetwork = true) },
        )
        result.put("notification_pending", flushNotifications(context, bridge))
        return result
    }

    /** Retry only notification submission, never the already-committed model reply. */
    suspend fun flushNotifications(context: Context, bridge: CoreBridge): Boolean = notificationMutex.withLock {
        val token = ChatUpdates.history.token() ?: return@withLock true
        val pending = bridge.pendingNotifications()
        for (index in 0 until pending.length()) {
            val item = pending.getJSONObject(index)
            val settings = SettingsStore(context).snapshot()
            val id = item.getString("message_id")
            val action = notificationAction(settings.notificationsEnabled, AppVisibility.isForeground,
                !scheduledQuietHour(LocalTime.now().hour, settings.quietStart, settings.quietEnd) &&
                    NotificationHelper.canNotify(context, settings.sound, settings.vibration))
            var submitted = false
            var foregroundAccepted = false
            val current = ChatUpdates.history.publishIfCurrent(token) {
                when (action) {
                    NotificationAction.SUBMIT -> submitted = NotificationHelper.show(context, id,
                        item.getString("text"), settings.sound, settings.vibration)
                    NotificationAction.FOREGROUND -> foregroundAccepted = ChatUpdates.notifyMessage(id)
                    else -> Unit
                }
            }
            if (!current) return@withLock true
            val status = when (action) {
                NotificationAction.DISABLED -> "disabled"
                NotificationAction.FOREGROUND -> if (foregroundAccepted) "foreground" else null
                NotificationAction.SUBMIT -> if (submitted) "submitted" else null
                NotificationAction.BLOCKED -> null
            }
            if (status != null) bridge.finishNotification(id, status)
        }
        bridge.pendingNotifications(1).length() > 0
    }
}
