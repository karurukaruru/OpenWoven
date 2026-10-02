package com.adaptive.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.adaptive.companion.data.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonaSetupScreen(settings: AppSettings, status: OnboardingStatus, error: String?, saving: Boolean,
    modelConfigured: Boolean,
    onLanguage: (String) -> Unit, onDraft: suspend (Map<String, Any?>, Int, Boolean) -> Unit,
    onPreview: suspend (Map<String, Any?>, String) -> JSONObject,
    onGenerate: suspend (Map<String, Any?>, String) -> JSONObject,
    onSave: (Map<String, Any?>, String, String?) -> Unit, onBack: (() -> Unit)? = null) {
    val initialPosition = interviewPosition(status)
    var full by rememberSaveable { mutableStateOf(initialPosition.full) }
    var page by rememberSaveable { mutableIntStateOf(initialPosition.page) }
    var answersJson by rememberSaveable { mutableStateOf(JSONObject(status.answers).toString()) }
    var name by rememberSaveable { mutableStateOf(editableCharacterName(settings.persona, settings.personaConfigured)) }
    var busy by remember { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    var previewJson by rememberSaveable { mutableStateOf<String?>(null) }
    var previewBasis by rememberSaveable { mutableStateOf("") }
    val preview = previewJson?.let(::JSONObject)
    var showPrompt by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val scrollState = rememberScrollState()
    LaunchedEffect(page, full) { scrollState.scrollTo(0) }
    val json = JSONObject(answersJson)
    val answers = json.keys().asSequence().associateWith { json.opt(it).takeUnless { value -> value == JSONObject.NULL } }
    val complete = requiredInterviewComplete(answers, status.recommendedIds)
    val questions = if (full) status.questions else status.recommendedIds.mapNotNull { id -> status.questions.firstOrNull { it.id == id } }
    val pageCount = ((questions.size + 4) / 5).coerceAtLeast(1)
    val reviewing = page >= pageCount
    val pageQuestions = questions.drop(page * 5).take(5)
    val requiredPageComplete = pageQuestions.filter { it.id in status.recommendedIds }.all {
        requiredInterviewComplete(answers, listOf(it.id))
    }
    LaunchedEffect(reviewing, answersJson, settings.language) {
        val basis = settings.language + "\n" + answersJson
        if (reviewing && complete && (previewJson == null || previewBasis != basis)) {
            previewJson = null
            localError = null
            try { previewJson = onPreview(answers, name).toString(); previewBasis = basis }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { localError = "Role save failed" }
        }
    }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Interview title")) }, navigationIcon = {
        if (onBack != null) TextButton(enabled = !saving && !busy, onClick = onBack) { Text(tr("Back")) }
    }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(20.dp).verticalScroll(scrollState),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(tr("Language"), style = MaterialTheme.typography.titleSmall)
            LanguagePicker(settings.language) { if (!saving && !busy) onLanguage(it) }
            Text(tr("Interview introduction"))
            Text(tr("Interview base character"), style = MaterialTheme.typography.bodySmall)
            if (!reviewing) {
                LinearProgressIndicator(progress = { page.toFloat() / pageCount }, modifier = Modifier.fillMaxWidth())
                Text(tr("Interview page {0} of {1}", page + 1, pageCount))
                Text(tr(when {
                    page == 0 -> "Interview first five user"
                    page == 1 -> "Interview first five character"
                    page < 6 -> "Interview extra user"
                    else -> "Interview extra character"
                }), style = MaterialTheme.typography.titleMedium)
                pageQuestions.forEach { question ->
                    InterviewQuestionEditor(question, answers[question.id], question.id in status.recommendedIds) { value ->
                        if (!saving && !busy) {
                            json.put(question.id, value ?: JSONObject.NULL)
                            answersJson = json.toString()
                        }
                    }
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (page > 0) OutlinedButton(enabled = !busy && !saving, onClick = { page-- }) { Text(tr("Back")) }
                    Button(enabled = !busy && !saving && requiredPageComplete, onClick = {
                        busy = true
                        localError = null
                        scope.launch {
                            try { onDraft(answers, (page + 1) * 5, full); page++ }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (_: Exception) { localError = "Role save failed" }
                            finally { busy = false }
                        }
                    }) { Text(tr("Interview save next")) }
                }
                if (full && complete && page >= 2) TextButton(enabled = !busy && !saving, onClick = {
                    busy = true
                    scope.launch {
                        try { onDraft(answers, questions.size, full); page = pageCount }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { localError = "Role save failed" }
                        finally { busy = false }
                    }
                }) {
                    Text(tr("Interview use answered"))
                }
            } else {
                Text(tr("Interview draft title"), style = MaterialTheme.typography.titleMedium)
                Text(tr(if (preview?.optString("method") == "model draft; confirmation required") "Interview model draft notice"
                    else if (preview?.optString("method") == "saved model character") "Interview saved model notice"
                    else "Interview draft notice"), style = MaterialTheme.typography.bodySmall)
                Button(enabled = modelConfigured && complete && !busy && !saving, onClick = {
                    busy = true
                    localError = null
                    scope.launch {
                        try {
                            val generated = onGenerate(answers, name)
                            previewJson = generated.toString()
                            previewBasis = settings.language + "\n" + answersJson
                            if (name.isBlank()) name = generated.getJSONObject("persona").optString("name")
                        } catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { localError = "Character generation failed" }
                        finally { busy = false }
                    }
                }) { Text(tr("Generate character with model")) }
                Text(tr(if (modelConfigured) "Character generation cost" else "Connect model for character"), style = MaterialTheme.typography.bodySmall)
                if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (preview == null && localError == null) LinearProgressIndicator(Modifier.fillMaxWidth())
                preview?.let { result ->
                    Text(result.getJSONObject("persona").optString("description"))
                    val boundaries = result.getJSONObject("persona").optString("boundaries")
                    if (boundaries.isNotBlank()) {
                        Text(tr("Boundaries"), style = MaterialTheme.typography.titleSmall)
                        Text(boundaries)
                    }
                    val candidates = result.optJSONArray("nickname_candidates")
                    OutlinedTextField(name, { name = it.take(40) }, Modifier.fillMaxWidth(), enabled = !saving && !busy,
                        label = { Text(tr("AI name")) }, placeholder = { Text(tr("Interview automatic name")) })
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        repeat(candidates?.length() ?: 0) { index ->
                            val candidate = candidates!!.getString(index)
                            FilterChip(selected = name == candidate, onClick = { if (!saving && !busy) name = candidate },
                                label = { Text(candidate) })
                        }
                    }
                    if ((candidates?.length() ?: 0) > 0) {
                        TextButton(enabled = !saving && !busy, onClick = { name = candidates?.optString(0).orEmpty() }) {
                            Text(tr("Interview generate nickname"))
                        }
                    }
                    val assumptions = result.optJSONArray("tentative_assumptions")
                    val distilled = result.optJSONArray("user_distillation")
                    if ((distilled?.length() ?: 0) > 0) {
                        Text(tr("Distilled user profile"), style = MaterialTheme.typography.titleSmall)
                        repeat(distilled!!.length()) { index ->
                            val note = distilled.getJSONObject(index)
                            val questionLabel = "Question " + note.getString("question_id")
                            Text(tr(questionLabel) + "：" + note.getString("summary"), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    if ((assumptions?.length() ?: 0) > 0) {
                        Text(tr("Suggested fictional details"), style = MaterialTheme.typography.titleSmall)
                        repeat(assumptions!!.length()) { Text(assumptions.getString(it), style = MaterialTheme.typography.bodySmall) }
                    }
                    TextButton(onClick = { showPrompt = !showPrompt }) { Text(tr("Interview generation prompt")) }
                    if (showPrompt) Text(result.optString("generation_prompt"), style = MaterialTheme.typography.bodySmall)
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(enabled = !saving && !busy, onClick = { page = 0 }) { Text(tr("Interview edit answers")) }
                    OutlinedButton(enabled = !saving && !busy, onClick = { page = (pageCount - 1).coerceAtLeast(0) }) { Text(tr("Back")) }
                    if (!full) OutlinedButton(enabled = !saving && !busy, onClick = {
                        busy = true
                        scope.launch {
                            try { onDraft(answers, 10, true); full = true; page = 2 }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (_: Exception) { localError = "Role save failed" }
                            finally { busy = false }
                        }
                    }) {
                        Text(tr("Interview continue fifty"))
                    }
                    Button(enabled = complete && preview != null && !saving && !busy, onClick = { onSave(answers, name, preview?.toString()) }) {
                        Text(tr("Interview confirm start"))
                    }
                }
            }
            Text(tr("Interview gradual adaptation"), style = MaterialTheme.typography.bodySmall)
            if (!settings.personaConfigured) Text(tr("主动关心默认每天最多一次，可在设置关闭。") +
                tr(if (settings.backgroundMode == "resident") "此版本默认带持续通知的常驻模式；可在设置或常驻通知中停止，仍可能被系统限制。"
                    else "此版本默认省电调度，后台消息可能延后。"), style = MaterialTheme.typography.bodySmall)
            (localError ?: error)?.let { Text(tr(it), color = MaterialTheme.colorScheme.error) }
        }
    }
}
