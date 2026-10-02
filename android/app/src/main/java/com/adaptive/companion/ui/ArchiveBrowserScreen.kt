package com.adaptive.companion.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import org.json.JSONArray
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArchiveBrowserScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    var kind by remember { mutableStateOf("daily") }
    var query by remember { mutableStateOf("") }
    var search by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<String?>(null) }
    val trail = remember { mutableStateListOf<String>() }
    var offset by remember { mutableIntStateOf(0) }
    var revision by remember { mutableIntStateOf(0) }
    var rows by remember { mutableStateOf(emptyList<JSONObject>()) }
    var detail by remember { mutableStateOf<JSONObject?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun goBack() {
        if (selected == null) onBack() else {
            selected = if (trail.isEmpty()) null else trail.removeAt(trail.lastIndex)
            offset = 0
        }
    }
    fun open(id: String) {
        selected?.let { trail.add(it) }
        selected = id
        offset = 0
    }
    BackHandler(enabled = selected != null) { goBack() }
    LaunchedEffect(kind, search, selected, offset, revision) {
        loading = true
        error = null
        detail = null
        rows = emptyList()
        try {
            val id = selected
            if (id != null) {
                detail = viewModel.archiveDetail(id, offset)
                if (detail == null) error = "这份归档已被删除或正在重新整理，请返回后刷新。"
            } else {
                viewModel.maintainMemory()
                rows = (if (search.isBlank()) viewModel.archives(kind) else viewModel.searchMemory(search)).objects()
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            error = "暂时无法读取记忆，请稍后刷新。"
        } finally {
            loading = false
        }
    }
    Scaffold(topBar = {
        TopAppBar(title = { Text(tr("记忆日历")) }, navigationIcon = {
            TextButton(onClick = { goBack() }) { Text(tr("返回")) }
        }, actions = { TextButton(onClick = { revision++ }) { Text(tr("刷新")) } })
    }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (selected == null) {
                item {
                    Text(tr("日期结束后自动归档，原话始终保留。休眠期间未完成的整理会在下次打开时补做。"),
                        style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("daily" to "日", "weekly" to "周", "monthly" to "月").forEach { (value, label) ->
                            FilterChip(selected = kind == value && search.isBlank(),
                                onClick = { kind = value; search = ""; query = "" }, label = { Text(tr(label)) })
                        }
                    }
                    OutlinedTextField(value = query, onValueChange = { query = it }, modifier = Modifier.fillMaxWidth(),
                        label = { Text(tr("关键词或日期，例如 2026-07-11")) }, singleLine = true)
                    Row {
                        TextButton(onClick = { search = query.trim(); revision++ }) { Text(tr("搜索")) }
                        TextButton(onClick = { query = ""; search = "" }) { Text(tr("清除")) }
                    }
                    if (search.contains("第")) Text(tr("序号月份从首次聊天所在月份起算；月内第 2 周第 3 天指该月 10 日。"),
                        style = MaterialTheme.typography.bodySmall)
                }
            }
            if (loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            error?.let { message -> item { Text(tr(message), color = MaterialTheme.colorScheme.error) } }
            val archive = detail
            if (archive != null) {
                item {
                    Text(archive.periodLabel(), style = MaterialTheme.typography.titleLarge)
                    Text(tr("Original messages {0}", archive.optInt("message_count")) + " · " + archive.optString("kind").kindLabel())
                    val content = archive.optJSONObject("content")
                    content?.optString("summary")?.takeIf { it.isNotBlank() }?.let { Text(it) }
                    if (content?.optBoolean("learning_incomplete") == true) Text(tr("部分消息未完成学习；下面仍可查看原话。"))
                    content?.optJSONArray("highlights")?.objects()?.forEach { Text(tr("Excerpt {0}", it.optString("text"))) }
                }
                items(archive.optJSONArray("children").objects(), key = { it.optString("memory_id") }) { child ->
                    OutlinedButton(onClick = { open(child.getString("memory_id")) }, modifier = Modifier.fillMaxWidth()) {
                        Text("${child.optString("kind").kindLabel()} · ${child.periodLabel()}")
                    }
                }
                item { Text(tr("原始聊天"), style = MaterialTheme.typography.titleMedium) }
                items(archive.optJSONArray("messages").objects(), key = { it.getString("id") }) { message ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text(tr(if (message.optString("role") == "user") "You" else "AI") + " · " + message.optString("local_day"),
                                style = MaterialTheme.typography.labelMedium)
                            Text(message.optString("content"))
                        }
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        TextButton(enabled = !loading && offset > 0, onClick = { offset = (offset - 50).coerceAtLeast(0) }) { Text(tr("上一页")) }
                        Text(tr("Page {0}", offset / 50 + 1))
                        TextButton(enabled = !loading && offset + 50 < archive.optInt("message_count"), onClick = { offset += 50 }) { Text(tr("下一页")) }
                    }
                }
            } else if (!loading && error == null) {
                if (rows.isEmpty()) item { Text(tr(if (search.isBlank()) "还没有已结束的归档。今天的聊天明天会出现在这里。" else "未找到匹配内容。可以换关键词或直接输入日期；目前不是语义搜索。")) }
                items(rows, key = { it.optString("memory_id", it.optString("id")) }) { row ->
                    val archiveId = if (row.has("memory_id")) row.optString("memory_id") else row.optString("archive_id").takeUnless { it == "null" }.orEmpty()
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(if (search.isBlank()) row.periodLabel() else row.optString("local_day", tr("历史记录")).takeUnless { it == "null" } ?: tr("历史记录"),
                                style = MaterialTheme.typography.titleMedium)
                            if (search.isNotBlank()) Text(row.optString("text")) else {
                                Text(tr("Messages {0}", row.optInt("message_count")))
                                row.optJSONObject("content")?.optString("summary")?.takeIf { it.isNotBlank() }?.let {
                                    Text(it, maxLines = 4)
                                }
                                row.optJSONObject("content")?.optJSONArray("highlights")?.objects()?.take(3)?.forEach {
                                    Text(it.optString("text"), maxLines = 3)
                                }
                            }
                            if (archiveId.isNotBlank()) TextButton(onClick = { open(archiveId) }) { Text(tr("查看摘要和原话")) }
                        }
                    }
                }
            }
            item { Spacer(Modifier.height(16.dp)) }
        }
    }
}

private fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else
    (0 until length()).mapNotNull { optJSONObject(it) }

private fun JSONObject.periodLabel(): String = optString("period_start").let { start ->
    if (optString("period_end") == start) start else "$start – ${optString("period_end")}" }

@Composable
private fun String.kindLabel(): String = tr(when (this) { "monthly" -> "月归档"; "weekly" -> "周归档"; else -> "日归档" })
