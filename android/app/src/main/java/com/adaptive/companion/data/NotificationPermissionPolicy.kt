package com.adaptive.companion.data

fun shouldAutoRequestNotifications(sdk: Int, granted: Boolean, askedBefore: Boolean): Boolean =
    sdk >= 33 && !granted && !askedBefore
