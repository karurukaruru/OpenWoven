package com.adaptive.companion.data

import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

fun chatLocalTime(value: String, zone: ZoneId = ZoneId.systemDefault()): String = runCatching {
    OffsetDateTime.parse(value).atZoneSameInstant(zone).format(DateTimeFormatter.ofPattern("HH:mm"))
}.getOrDefault("")

/** ISO fields are interpreted in the device zone, not as a UTC clock. */
fun scheduledLocalTime(date: String, time: String, zone: ZoneId = ZoneId.systemDefault()): String {
    require(date.matches(Regex("\\d{4}-\\d{2}-\\d{2}")) && time.matches(Regex("\\d{2}:\\d{2}")))
    val local = LocalDateTime.parse("${date}T$time")
    val offsets = zone.rules.getValidOffsets(local)
    require(offsets.size == 1) { "Choose an unambiguous local time" }
    return ZonedDateTime.ofStrict(local, offsets.single(), zone).toOffsetDateTime().toString()
}
