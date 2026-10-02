package com.adaptive.companion.scheduler

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.adaptive.companion.MainActivity
import com.adaptive.companion.R
import com.adaptive.companion.data.CoreBridge
import com.adaptive.companion.data.SecureSecretStore
import com.adaptive.companion.data.SettingsStore
import com.adaptive.companion.ui.UiStrings
import kotlinx.coroutines.*
import java.time.OffsetDateTime

/** User-visible, opt-out local scheduling. No wake lock, boot receiver or kill-proof claim. */
class CompanionResidentService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var runner: Job? = null

    override fun onCreate() {
        super.onCreate()
        showForegroundNotification()
    }

    private fun showForegroundNotification() {
        val language = UiStrings.language(this)
        val channel = NotificationChannel(CHANNEL, UiStrings.text(language, "Resident notification"), NotificationManager.IMPORTANCE_LOW)
            .apply { description = UiStrings.text(language, "Resident confirmation"); setSound(null, null) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        val open = PendingIntent.getActivity(this, 40, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 41, Intent(this, javaClass).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_companion).setContentTitle(UiStrings.text(language, "Resident notification"))
            .setContentText(UiStrings.text(language, "Resident notification body"))
            .setContentIntent(open).setOngoing(true).setSilent(true)
            .addAction(0, UiStrings.text(language, "Stop resident"), stop).build()
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification,
            if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            runner?.cancel()
            scope.launch {
                try { SettingsStore(this@CompanionResidentService).setBackgroundMode(BackgroundPolicy.SYSTEM) }
                finally { stopSelf() }
            }
            return START_NOT_STICKY
        }
        showForegroundNotification()
        if (runner?.isActive != true) runner = scope.launch { runScheduler() }
        // A user/system stop remains a stop. Reopening the app can start the chosen mode.
        return START_NOT_STICKY
    }

    private suspend fun runScheduler() {
        val settingsStore = SettingsStore(this)
        val bridge = CoreBridge(this)
        val retryAfter = mutableMapOf<String, Long>()
        while (currentCoroutineContext().isActive) {
            try {
                if (settingsStore.snapshot().backgroundMode != BackgroundPolicy.RESIDENT) {
                    stopSelf(); return
                }
                bridge.ensureInitialized(settingsStore, SecureSecretStore(this))
                ScheduledDelivery.flushNotifications(this, bridge)
                val now = OffsetDateTime.now()
                val pending = bridge.scheduled("pending")
                retryAfter.keys.retainAll(pending.map { it.id }.toSet())
                pending.filter { item ->
                    runCatching { !OffsetDateTime.parse(item.scheduledAt).isAfter(now) }.getOrDefault(false)
                        && (retryAfter[item.id] ?: 0L) <= SystemClock.elapsedRealtime()
                }.take(2).forEach { item ->
                    // No rapid paid-model retry loop when offline or rate-limited.
                    retryAfter[item.id] = SystemClock.elapsedRealtime() + 15 * 60_000L
                    try {
                        val result = ScheduledDelivery.execute(this, bridge, item.id)
                        if (result.optBoolean("sent") || result.optString("status") in setOf("sent", "cancelled", "expired", "missing") ||
                            result.optString("reason") in setOf("composer active", "composer changed", "not due")) retryAfter.remove(item.id)
                    } catch (cancelled: CancellationException) { throw cancelled }
                    catch (_: Exception) { /* Durable job remains available to WorkManager/reopening. */ }
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { /* Back off below; don't restart or spin. */ }
            delay(30_000)
        }
    }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL = "companion_resident"
        private const val NOTIFICATION_ID = 4101
        private const val ACTION_STOP = "com.adaptive.companion.STOP_RESIDENT"
        /** Start only from a visible Activity. Background callers may only stop. */
        fun applyFromVisibleActivity(context: Context, mode: String): String? = try {
            val intent = Intent(context, CompanionResidentService::class.java)
            if (mode == BackgroundPolicy.RESIDENT) ContextCompat.startForegroundService(context, intent)
            else context.stopService(intent)
            null
        } catch (_: Exception) { "Background start failed" }
    }
}
