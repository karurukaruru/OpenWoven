package com.adaptive.companion.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.text.input.TextFieldValue
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adaptive.companion.data.ChatMessage
import com.adaptive.companion.data.shouldFollowChat
import com.adaptive.companion.data.chatLocalTime
import com.adaptive.companion.data.chatStatusKey
import com.adaptive.companion.data.chatErrorKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import android.graphics.BitmapFactory

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    state: CompanionUiState,
    onSend: (String) -> Unit,
    onSettings: () -> Unit,
    onSelect: (ChatMessage?) -> Unit,
    onRetry: (ChatMessage) -> Unit,
    onDelete: (ChatMessage) -> Unit,
    onFeedback: (String) -> Unit,
    onComposerActivity: (Boolean) -> Unit,
    onPickImage: (android.net.Uri) -> Unit,
    onRemoveImage: () -> Unit,
    onDraftText: (String) -> Unit,
) {
    var input by rememberSaveable(stateSaver = TextFieldValue.Saver) { mutableStateOf(TextFieldValue(state.draftText)) }
    val currentActivity by rememberUpdatedState(onComposerActivity)
    val draft = input.text.isNotEmpty() || input.composition != null || state.pendingImage != null || state.loadingImage
    val currentDraft by rememberUpdatedState(draft)
    LaunchedEffect(draft, state.ready) { if (state.ready) currentActivity(draft) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let(onPickImage)
        currentActivity(currentDraft)
    }
    val listState = rememberLazyListState()
    var previousRows by remember { mutableIntStateOf(0) }
    LaunchedEffect(state.messages.size, state.error) {
        val count = state.messages.size + (if (state.error != null) 1 else 0)
        val newest = state.messages.lastOrNull()
        val follow = shouldFollowChat(previousRows, listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1,
            newest?.role == "user" && newest.transient)
        previousRows = count
        if (count > 0 && follow && !listState.isScrollInProgress) listState.scrollToItem(count - 1)
    }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(state.settings.persona.name.ifBlank { tr("Companion") }, fontWeight = FontWeight.SemiBold)
                    }
                },
                actions = { TextButton(onClick = onSettings) { Text(tr("Settings")) } },
            )
        },
        bottomBar = {
            Surface(tonalElevation = 2.dp) {
                Column {
                state.pendingImage?.let { path ->
                    Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        LocalChatImage(path, Modifier.size(72.dp))
                        TextButton(onClick = onRemoveImage) { Text(tr("Remove image")) }
                    }
                }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .imePadding()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    TextButton(
                        onClick = { currentActivity(currentDraft); picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                        enabled = state.modelConfigured && state.settings.modelSupportsVision && !state.loadingImage && !state.mutatingHistory,
                        contentPadding = PaddingValues(6.dp),
                    ) { Text(tr("Add image")) }
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it; onDraftText(it.text); currentActivity(it.text.isNotEmpty() || it.composition != null || state.pendingImage != null) },
                        modifier = Modifier.weight(1f)
                            .onFocusChanged { if (it.isFocused) currentActivity(currentDraft) }
                            .pointerInput(Unit) { awaitEachGesture { awaitFirstDown(requireUnconsumed = false); currentActivity(currentDraft) } },
                        placeholder = { Text(tr("Message…")) },
                        maxLines = 5,
                        shape = RoundedCornerShape(24.dp),
                    )
                    Button(
                        onClick = { val value = input.text; input = TextFieldValue(); onDraftText(""); currentActivity(false); onSend(value) },
                        enabled = (input.text.isNotBlank() || state.pendingImage != null) && !state.loadingImage && !state.mutatingHistory && (state.pendingImage == null || state.settings.modelSupportsVision),
                        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 14.dp),
                    ) { Text(tr("Send")) }
                }
                }
            }
        },
    ) { padding ->
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(state.messages, key = { it.id }) { message ->
                MessageBubble(message = message, onLongPress = { onSelect(message) }, onRetry = { onRetry(message) })
            }
            state.error?.let { error ->
                item("error") {
                    Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(12.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text(tr(chatErrorKey(error)), color = MaterialTheme.colorScheme.onErrorContainer)
                            TextButton(onClick = onSettings) { Text(tr("Settings")) }
                        }
                    }
                }
            }
        }
    }

    state.feedbackTarget?.let { message ->
        MessageActionsSheet(
            message = message,
            onDismiss = { onSelect(null) },
            onRetry = { onRetry(message) },
            onDelete = { onDelete(message) },
            onFeedback = onFeedback,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageBubble(message: ChatMessage, onLongPress: () -> Unit, onRetry: () -> Unit) {
    val user = message.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (user) Arrangement.End else Arrangement.Start,
    ) {
        Column(horizontalAlignment = if (user) Alignment.End else Alignment.Start) {
            Surface(
                color = if (user) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerHigh,
                shape = RoundedCornerShape(
                    topStart = 18.dp, topEnd = 18.dp,
                    bottomStart = if (user) 18.dp else 4.dp,
                    bottomEnd = if (user) 4.dp else 18.dp,
                ),
                modifier = Modifier.widthIn(max = 320.dp).combinedClickable(onClick = {}, onLongClick = onLongPress),
            ) {
                Column {
                    message.imagePath?.let { LocalChatImage(it, Modifier.padding(8.dp).sizeIn(maxWidth = 280.dp, maxHeight = 240.dp)) }
                    if (message.content.isNotBlank() && message.content != "[Image]") Text(message.content, modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp), fontSize = 16.sp)
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(formatTime(message.timestamp), fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (user) Text("  ${statusText(message.status)}", fontSize = 10.sp, color = statusColor(message.status))
                if (message.status == "failed") {
                    TextButton(onClick = onRetry, contentPadding = PaddingValues(horizontal = 6.dp)) { Text(tr("Retry"), fontSize = 11.sp) }
                }
            }
        }
    }
}

@Composable
private fun LocalChatImage(path: String, modifier: Modifier) {
    var bitmap by remember(path) { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(path) { bitmap = withContext(Dispatchers.IO) {
        runCatching { BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = 2 }) }.getOrNull()
    } }
    bitmap?.let { Image(it.asImageBitmap(), tr("Selected image"), modifier, contentScale = ContentScale.Fit) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MessageActionsSheet(
    message: ChatMessage,
    onDismiss: () -> Unit,
    onRetry: () -> Unit,
    onDelete: () -> Unit,
    onFeedback: (String) -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
            Text(tr("Message"), style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { clipboard.setText(AnnotatedString(message.content)); onDismiss() }) { Text(tr("Copy")) }
                TextButton(onClick = onDelete) { Text(tr("Delete")) }
                if (message.role == "assistant" || message.status == "failed") {
                    TextButton(onClick = onRetry) { Text(tr("Reply again")) }
                }
            }
            if (message.role == "assistant") {
                HorizontalDivider()
                Text(tr("Feedback"), modifier = Modifier.padding(top = 14.dp), style = MaterialTheme.typography.labelLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AssistChip(onClick = { onFeedback("thumb_up") }, label = { Text(tr("👍 Good")) })
                    AssistChip(onClick = { onFeedback("thumb_down") }, label = { Text(tr("👎")) })
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(
                        "too_long" to "Too long", "too_short" to "Too short",
                        "too_many_questions" to "Too many questions", "too_cold" to "Too cold",
                        "too_verbose" to "Too verbose", "too_serious" to "Too serious",
                        "too_playful" to "Too playful", "too_much_initiative" to "Too proactive",
                        "too_little_initiative" to "Be more proactive",
                    ).forEach { (key, label) ->
                        AssistChip(onClick = { onFeedback(key) }, label = { Text(tr(label)) })
                    }
                }
            }
        }
    }
}

@Composable
fun PeriodicFeedbackDialog(onDismiss: () -> Unit, onSubmit: (Int, Int, String, String) -> Unit) {
    var natural by remember { mutableIntStateOf(4) }
    var comfort by remember { mutableIntStateOf(4) }
    var length by remember { mutableStateOf("just_right") }
    var initiative by remember { mutableStateOf("just_right") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(tr("How did that conversation feel?")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(tr("Naturalness") + "  $natural / 5")
                Slider(natural.toFloat(), { natural = it.toInt() }, valueRange = 1f..5f, steps = 3)
                Text(tr("Comfort") + "  $comfort / 5")
                Slider(comfort.toFloat(), { comfort = it.toInt() }, valueRange = 1f..5f, steps = 3)
                Text(tr("Reply length"))
                SingleChoiceSegmentedButtonRow {
                    listOf("too_short" to "Short", "just_right" to "Good", "too_long" to "Long").forEachIndexed { i, item ->
                        SegmentedButton(selected = length == item.first, onClick = { length = item.first }, shape = SegmentedButtonDefaults.itemShape(i, 3)) { Text(tr(item.second)) }
                    }
                }
                Text(tr("Initiative"))
                SingleChoiceSegmentedButtonRow {
                    listOf("too_little" to "Low", "just_right" to "Good", "too_much" to "High").forEachIndexed { i, item ->
                        SegmentedButton(selected = initiative == item.first, onClick = { initiative = item.first }, shape = SegmentedButtonDefaults.itemShape(i, 3)) { Text(tr(item.second)) }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSubmit(natural, comfort, length, initiative) }) { Text(tr("Send")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(tr("Skip")) } },
    )
}

private fun formatTime(value: String): String = chatLocalTime(value)

@Composable
private fun statusText(status: String) = tr(chatStatusKey(status))

@Composable
private fun statusColor(status: String): Color =
    if (status == "failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
