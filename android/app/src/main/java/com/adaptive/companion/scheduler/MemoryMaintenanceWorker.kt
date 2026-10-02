package com.adaptive.companion.scheduler

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.adaptive.companion.data.CoreBridge
import com.adaptive.companion.data.SecureSecretStore
import com.adaptive.companion.data.SettingsStore
import kotlinx.coroutines.CancellationException

/** Local, rebuildable housekeeping. No network or zero-o'clock wakeup needed. */
class MemoryMaintenanceWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        return try {
        val bridge = CoreBridge(applicationContext)
        val settingsStore = SettingsStore(applicationContext)
        bridge.ensureInitialized(settingsStore, SecureSecretStore(applicationContext))
        if (settingsStore.snapshot().personaConfigured) {
            bridge.planCheckIn()?.let { WorkScheduler.schedule(applicationContext, it, requireNetwork = true) }
        }
        var remaining = 0
        repeat(4) {
            val result = bridge.maintainMemory()
            remaining = result.optInt("remaining")
            if (remaining == 0) return Result.success()
            if (result.optInt("daily") + result.optInt("weekly") + result.optInt("monthly") == 0) {
                return Result.retry() // Learning is still running; avoid a tight loop.
            }
        }
        if (remaining > 0) Result.retry() else Result.success()
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        if (runAttemptCount < 3) Result.retry() else Result.failure()
    }
    }
}
