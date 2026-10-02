package com.adaptive.companion.scheduler

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.adaptive.companion.data.CoreBridge
import com.adaptive.companion.data.SecureSecretStore
import com.adaptive.companion.data.SettingsStore
import kotlinx.coroutines.CancellationException

class ProactiveWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getString(KEY_ID) ?: return Result.failure()
        return try {
            val settingsStore = SettingsStore(applicationContext)
            val bridge = CoreBridge(applicationContext)
            bridge.ensureInitialized(settingsStore, SecureSecretStore(applicationContext))
            val result = ScheduledDelivery.execute(applicationContext, bridge, id)
            if (result.optBoolean("notification_pending")) {
                Result.retry()
            } else if (result.optBoolean("sent")) {
                Result.success()
            } else if (result.optString("reason") in setOf(
                    "not due", "quiet hours", "daily limit", "minimum interval", "history change", "notifications unavailable", "composer active", "composer changed"
                )) {
                Result.retry()
            } else {
                Result.success()
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }

    companion object { const val KEY_ID = "scheduled_message_id" }
}
