package com.adaptive.companion.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import org.json.JSONArray
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoleLibraryScreen(viewModel: CompanionViewModel, state: CompanionUiState, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var roles by remember { mutableStateOf(JSONArray()) }
    var preview by remember { mutableStateOf<JSONObject?>(null) }
    var creating by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf(false) }
    var exportBytes by remember { mutableStateOf<ByteArray?>(null) }
    fun operation(action: suspend () -> Unit) {
        if (busy) return
        busy = true; error = false
        scope.launch {
            try { action() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { error = true }
            finally { busy = false }
        }
    }
    LaunchedEffect(Unit) {
        try { roles = viewModel.bridge.roles() } catch (_: Exception) { error = true }
    }
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        val bytes = exportBytes; exportBytes = null
        if (uri != null && bytes != null) operation {
            withContext(Dispatchers.IO) { context.contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: throw java.io.IOException("Cannot write role package") }
        }
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) operation {
            val bytes = withContext(Dispatchers.IO) {
                context.contentResolver.openInputStream(uri)?.use { stream ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        val count = stream.read(buffer)
                        if (count < 0) break
                        require(output.size() + count <= 8 * 1024 * 1024)
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                } ?: throw java.io.IOException("Cannot read role package")
            }
            preview = viewModel.bridge.previewRole(bytes)
        }
    }
    Scaffold(topBar = { TopAppBar(title = { Text(tr("Role library")) }, navigationIcon = { TextButton(onClick = onBack) { Text(tr("Back")) } }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(18.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(tr("Role package privacy"), style = MaterialTheme.typography.bodySmall)
            Text(tr("Inactive role scheduling is paused"), style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = !busy, onClick = { pick.launch(arrayOf("application/zip", "application/json", "image/png", "application/octet-stream")) }) { Text(tr("Import role")) }
                OutlinedButton(enabled = !busy, onClick = { name = ""; description = ""; creating = true }) { Text(tr("New role")) }
            }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (error) Text(tr("Role package operation failed"), color = MaterialTheme.colorScheme.error)
            repeat(roles.length()) { index ->
                val item = roles.getJSONObject(index)
                val role = item.getJSONObject("role")
                val id = item.getString("id")
                val active = id == state.settings.persona.characterId.ifBlank { "legacy" }
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(role.optString("name").ifBlank { tr("Companion") }, style = MaterialTheme.typography.titleMedium)
                        Text(role.optString("description"), style = MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(enabled = !busy && !active, onClick = { viewModel.switchRole(item, onBack) }) { Text(tr(if (active) "Current role" else "Switch role")) }
                            TextButton(enabled = !busy, onClick = { operation {
                                exportBytes = viewModel.bridge.exportRole(id)
                                save.launch("OpenWoven-role.zip")
                            } }) { Text(tr("Export role")) }
                        }
                    }
                }
            }
        }
    }
    preview?.let { item -> AlertDialog(onDismissRequest = { if (!busy) preview = null },
        title = { Text(tr("Import role")) }, text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            Text(item.getJSONObject("role").optString("name"))
            Text(item.getJSONObject("role").optString("description"))
            if ((item.optJSONArray("warnings")?.length() ?: 0) > 0) Text(tr("Role card conversion warning"))
            Text(tr("Role package privacy"))
        } }, confirmButton = { TextButton(enabled = !busy, onClick = { operation {
            viewModel.bridge.addRole(item); roles = viewModel.bridge.roles(); preview = null
        } }) { Text(tr("Import role")) } }, dismissButton = { TextButton(enabled = !busy, onClick = { preview = null }) { Text(tr("Cancel")) } }) }
    if (creating) AlertDialog(onDismissRequest = { if (!busy) creating = false }, title = { Text(tr("New role")) },
        text = { Column {
            OutlinedTextField(name, { name = it.take(40) }, label = { Text(tr("Nickname")) })
            OutlinedTextField(description, { description = it.take(600) }, label = { Text(tr("Role description")) })
        } }, confirmButton = { TextButton(enabled = !busy && name.isNotBlank() && description.isNotBlank(), onClick = { operation {
            viewModel.bridge.addRole(JSONObject().put("role", JSONObject().put("name", name).put("description", description).put("preset", "custom")).put("facts", JSONArray()))
            roles = viewModel.bridge.roles(); creating = false
        } }) { Text(tr("Save")) } }, dismissButton = { TextButton(enabled = !busy, onClick = { creating = false }) { Text(tr("Cancel")) } })
}
