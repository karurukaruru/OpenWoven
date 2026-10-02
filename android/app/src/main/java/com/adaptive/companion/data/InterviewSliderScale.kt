package com.adaptive.companion.data

/** All interview sliders keep the Core's existing 0..1 scale. UI labels are keys. */
fun interviewSliderEndpoints(id: String): Pair<String, String> = when (id) {
    "q21" -> "Slider short" to "Slider detailed"
    "q22" -> "Slider reserved" to "Slider warm"
    "q23" -> "Slider serious" to "Slider humorous"
    "q24" -> "Slider no teasing" to "Slider gentle teasing"
    "q25" -> "Slider tactful" to "Slider direct"
    "q26" -> "Slider rational" to "Slider empathetic"
    "q27" -> "Slider few questions" to "Slider more questions"
    "q28" -> "Slider wait for me" to "Slider start topics"
    "q29" -> "Slider listen first" to "Slider more advice"
    "q30" -> "Slider no emoji" to "Slider frequent emoji"
    else -> "Low" to "High"
}

fun shouldFollowChat(previousRows: Int, lastVisibleRow: Int, newestIsLocalUser: Boolean): Boolean =
    previousRows == 0 || lastVisibleRow >= previousRows - 2 || newestIsLocalUser
