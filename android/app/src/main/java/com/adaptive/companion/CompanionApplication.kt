package com.adaptive.companion

import android.app.Activity
import android.app.Application
import android.os.Bundle
import com.adaptive.companion.notifications.NotificationHelper
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class CompanionApplication : Application(), Application.ActivityLifecycleCallbacks {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        NotificationHelper.createChannel(this)
        registerActivityLifecycleCallbacks(this)
    }

    override fun onActivityStarted(activity: Activity) { AppVisibility.started++ }
    override fun onActivityStopped(activity: Activity) { AppVisibility.started = (AppVisibility.started - 1).coerceAtLeast(0) }
    override fun onActivityCreated(activity: Activity, state: Bundle?) = Unit
    override fun onActivityResumed(activity: Activity) = Unit
    override fun onActivityPaused(activity: Activity) = Unit
    override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) = Unit
    override fun onActivityDestroyed(activity: Activity) = Unit
}

object AppVisibility {
    @Volatile var started: Int = 0
    val isForeground: Boolean get() = started > 0
}
