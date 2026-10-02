package com.adaptive.companion.notifications

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.adaptive.companion.MainActivity
import com.adaptive.companion.R
import com.adaptive.companion.ui.UiStrings

object NotificationHelper {
    fun cancelMessage(context: Context, messageId: String) {
        val manager = NotificationManagerCompat.from(context)
        manager.cancel(messageId, 0)
        manager.cancel(messageId.hashCode()) // Remove notifications from older builds too.
    }

    fun clearMessages(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.activeNotifications.filter { it.notification.channelId?.startsWith("companion_messages_") == true }
            .forEach { manager.cancel(it.tag, it.id) }
    }

    fun createChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        val language = UiStrings.language(context)
        listOf(true, false).forEach { sound ->
            listOf(true, false).forEach { vibration ->
                val channel = NotificationChannel(
                    channelId(sound, vibration),
                    "OpenWoven · " + UiStrings.text(language, "Notifications") + " · " +
                        UiStrings.text(language, "Sound") + (if (sound) " ✓" else " −") + " · " +
                        UiStrings.text(language, "Vibration") + (if (vibration) " ✓" else " −"),
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = UiStrings.text(language, "Notifications description")
                    enableVibration(vibration)
                    if (!sound) setSound(null, null)
                }
                manager.createNotificationChannel(channel)
            }
        }
    }

    fun canNotify(context: Context, sound: Boolean, vibration: Boolean): Boolean {
        val granted = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val manager = context.getSystemService(NotificationManager::class.java)
        return canUseMessageChannel(granted, NotificationManagerCompat.from(context).areNotificationsEnabled(),
            manager.getNotificationChannel(channelId(sound, vibration))?.importance)
    }

    /** True means submitted to Android, not delivered to or read by the user. */
    fun show(context: Context, messageId: String, text: String, sound: Boolean, vibration: Boolean): Boolean {
        if (!canNotify(context, sound, vibration)) return false
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_chat", true)
        }
        val pending = PendingIntent.getActivity(
            context, 1, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, channelId(sound, vibration))
            .setSmallIcon(R.drawable.ic_companion)
            .setContentTitle("OpenWoven")
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .build()
        return try {
            // Stable, collision-free identity also updates a replayed submission.
            NotificationManagerCompat.from(context).notify(messageId, 0, notification)
            true
        } catch (_: SecurityException) {
            false // Permission can change between the check and submission.
        }
    }

    private fun channelId(sound: Boolean, vibration: Boolean) =
        "companion_messages_${if (sound) "sound" else "silent"}_${if (vibration) "vibrate" else "still"}"
}
