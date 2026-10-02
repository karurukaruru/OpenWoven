package com.adaptive.companion.scheduler

import android.content.Context
import androidx.work.Data
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.adaptive.companion.data.ScheduledIntent
import java.time.Duration
import java.time.OffsetDateTime
import java.util.concurrent.TimeUnit

object WorkScheduler {
    fun schedule(context: Context, item: ScheduledIntent, requireNetwork: Boolean = false) {
        val delay = runCatching {
            Duration.between(OffsetDateTime.now(), OffsetDateTime.parse(item.scheduledAt)).toMillis()
        }.getOrDefault(0L).coerceAtLeast(0L)
        val constraints = Constraints.Builder().apply {
            if (scheduledTaskNeedsNetwork(item.topic, requireNetwork)) setRequiredNetworkType(NetworkType.CONNECTED)
        }.build()
        val request = OneTimeWorkRequestBuilder<ProactiveWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setConstraints(constraints)
            .setInputData(Data.Builder().putString(ProactiveWorker.KEY_ID, item.id).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "proactive_${item.id}", ExistingWorkPolicy.REPLACE, request,
        )
    }

    fun cancel(context: Context, id: String) {
        WorkManager.getInstance(context).cancelUniqueWork("proactive_$id")
    }

    fun scheduleMemoryMaintenance(context: Context) {
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "calendar_memory_maintenance", ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<MemoryMaintenanceWorker>(12, TimeUnit.HOURS).build(),
        )
    }
}
