package com.adaptive.companion.notifications

/** An app-wide grant does not imply that this particular message channel is open. */
fun canUseMessageChannel(permissionGranted: Boolean, appAllowed: Boolean, importance: Int?): Boolean =
    permissionGranted && appAllowed && importance != null && importance > 0
