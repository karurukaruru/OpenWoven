package com.adaptive.companion.data

/** Sent means accepted locally, not read by a real person or already answered. */
fun chatStatusKey(status: String): String = when (status) {
    "pending" -> "Sending"
    "failed" -> "Failed"
    else -> "✓"
}

/** Detailed provider/runtime diagnostics stay available in settings. */
fun chatErrorKey(diagnostic: String): String = when (diagnostic) {
    "Image could not be opened", "At most four images per turn" -> diagnostic
    else -> "Chat action failed"
}
