package com.adaptive.companion.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.adaptive.companion.data.ScheduledIntent
import com.adaptive.companion.data.scheduledLocalTime
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduledMessagesScreen(viewModel: CompanionViewModel, state: CompanionUiState, onBack: () -> Unit) {
    val initial = remember { ZonedDateTime.now().plusHours(1).truncatedTo(ChronoUnit.MINUTES) }
    var date by rememberSaveable { mutableStateOf(initial.toLocalDate().toString()) }
    var time by rememberSaveable { mutableStateOf(initial.toLocalTime().toString()) }
    var content by rememberSaveable { mutableStateOf("") }
    var generate by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var savedAt by rememberSaveable { mutableStateOf("") }
    var quietAdjusted by rememberSaveable { mutableStateOf(false) }
    var jobs by remember { mutableStateOf<List<ScheduledIntent>>(emptyList()) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    suspend fun refresh() { jobs = viewModel.bridge.scheduledQueue() }
    LaunchedEffect(state.messages.size) {
        try { refresh() } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { error = "Schedule load failed" }
    }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Scheduled messages")) }, navigationIcon = {
        TextButton(enabled = !busy, onClick = onBack) { Text(tr("Back")) }
    }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(20.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(tr("Schedule app scope"), style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !generate, enabled = !busy, onClick = { generate = false }, label = { Text(tr("Schedule exact text")) })
                FilterChip(selected = generate, enabled = !busy && state.modelConfigured, onClick = { generate = true }, label = { Text(tr("Schedule model topic")) })
            }
            Text(tr(if (generate) "Schedule topic help" else "Schedule text help"), style = MaterialTheme.typography.bodySmall)
            if (!state.modelConfigured) Text(tr("Schedule no model"), style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(content, { content = it.take(1000) }, Modifier.fillMaxWidth(), enabled = !busy,
                label = { Text(tr(if (generate) "Schedule topic" else "Schedule content")) }, minLines = 2, maxLines = 6)
            Text(tr("Schedule local time"), style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(enabled = !busy, onClick = {
                    val current = LocalDate.parse(date)
                    DatePickerDialog(context, { _, year, month, day -> date = LocalDate.of(year, month + 1, day).toString() },
                        current.year, current.monthValue - 1, current.dayOfMonth).show()
                }) { Text(date) }
                OutlinedButton(enabled = !busy, onClick = {
                    val current = LocalTime.parse(time)
                    TimePickerDialog(context, { _, hour, minute -> time = String.format(Locale.ROOT, "%02d:%02d", hour, minute) },
                        current.hour, current.minute, true).show()
                }) { Text(time) }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(10L to "Schedule in ten minutes", 60L to "Schedule in one hour", 1440L to "Schedule tomorrow").forEach { (minutes, key) ->
                    TextButton(enabled = !busy, onClick = {
                        val next = ZonedDateTime.now().plusMinutes(minutes).truncatedTo(ChronoUnit.MINUTES)
                        date = next.toLocalDate().toString(); time = next.toLocalTime().toString()
                    }) { Text(tr(key)) }
                }
            }
            Text(tr("Schedule timing help"), style = MaterialTheme.typography.bodySmall)
            Button(enabled = !busy && content.isNotBlank() && (!generate || state.modelConfigured), onClick = {
                scope.launch {
                    busy = true; error = null; savedAt = ""
                    try {
                        val whenAt = scheduledLocalTime(date, time)
                        if (!OffsetDateTime.parse(whenAt).isAfter(OffsetDateTime.now()) ||
                            OffsetDateTime.parse(whenAt).isAfter(OffsetDateTime.now().plusDays(366))) {
                            error = "Schedule future time required"
                        } else {
                            val result = viewModel.createScheduledMessage(content, whenAt, generate)
                            savedAt = OffsetDateTime.parse(result.getString("scheduled_at")).atZoneSameInstant(java.time.ZoneId.systemDefault())
                                .toLocalDateTime().toString().replace('T', ' ')
                            quietAdjusted = result.optBoolean("quiet_adjusted")
                            content = ""; refresh()
                        }
                    } catch (cancelled: CancellationException) { throw cancelled }
                    catch (_: Exception) { error = "Schedule create failed" }
                    finally { busy = false }
                }
            }) { Text(tr("Schedule save")) }
            if (savedAt.isNotBlank()) Text(tr(if (quietAdjusted) "Schedule saved outside quiet hours {0}" else "Schedule saved for {0}", savedAt))
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { Text(tr(it), color = MaterialTheme.colorScheme.error) }
            HorizontalDivider()
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(tr("Schedule queue"), style = MaterialTheme.typography.titleMedium)
                TextButton(enabled = !busy, onClick = { scope.launch {
                    try { refresh(); error = null } catch (cancelled: CancellationException) { throw cancelled }
                    catch (_: Exception) { error = "Schedule load failed" }
                } }) { Text(tr("Refresh")) }
            }
            if (jobs.isEmpty()) Text(tr("Schedule empty"))
            jobs.sortedBy { it.status != "pending" }.take(50).forEach { job ->
                Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.medium) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(if (job.topic.startsWith("custom:topic:")) job.draftIntent.substringAfter("TOPIC: ")
                            else if (job.topic.startsWith("custom:text:")) job.draftIntent else tr("Schedule automatic followup"))
                        Text(runCatching { OffsetDateTime.parse(job.scheduledAt).atZoneSameInstant(java.time.ZoneId.systemDefault())
                            .toLocalDateTime().toString().replace('T', ' ') }.getOrDefault(job.scheduledAt), style = MaterialTheme.typography.bodySmall)
                        val statusLabel = "Schedule status " + job.status
                        Text(tr(statusLabel), style = MaterialTheme.typography.bodySmall)
                        if (job.status == "sent" && job.notificationStatus.isNotBlank()) {
                            val notificationLabel = "Schedule notification " + job.notificationStatus
                            Text(tr(notificationLabel), style = MaterialTheme.typography.bodySmall)
                        }
                        if (job.status == "pending") TextButton(enabled = !busy, onClick = { scope.launch {
                            busy = true
                            try { viewModel.bridge.cancelScheduled(job.id); com.adaptive.companion.scheduler.WorkScheduler.cancel(context, job.id); refresh() }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (_: Exception) { error = "Schedule cancel failed" }
                            finally { busy = false }
                        } }) { Text(tr("Schedule cancel")) }
                    }
                }
            }
        }
    }
}
