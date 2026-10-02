package com.adaptive.companion

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.content.Intent
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import androidx.core.app.NotificationManagerCompat
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.adaptive.companion.scheduler.CompanionResidentService
import com.adaptive.companion.data.AdminAuthStore
import com.adaptive.companion.data.shouldAutoRequestNotifications
import com.adaptive.companion.ui.*

class MainActivity : ComponentActivity() {
    private var notificationsAllowed by mutableStateOf(false)
    private val permissionHistory by lazy { getSharedPreferences("permission_requests", MODE_PRIVATE) }
    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { notificationsAllowed = NotificationManagerCompat.from(this).areNotificationsEnabled() }

    override fun onResume() {
        super.onResume()
        notificationsAllowed = NotificationManagerCompat.from(this).areNotificationsEnabled()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notificationsAllowed = NotificationManagerCompat.from(this).areNotificationsEnabled()
        enableEdgeToEdge()
        setContent {
            val viewModel: CompanionViewModel = viewModel(
                factory = CompanionViewModel.factory(application as Application)
            )
            val state by viewModel.state.collectAsStateWithLifecycle()
            val latestState by rememberUpdatedState(state)
            fun applyBackgroundMode() {
                val current = latestState
                if (current.onboardingVisible || !current.settings.personaConfigured || current.savingPersona || current.mutatingHistory || !notificationsAllowed) {
                    CompanionResidentService.applyFromVisibleActivity(this, "system")
                    return
                }
                if (current.ready && !current.onboardingVisible && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
                    CompanionResidentService.applyFromVisibleActivity(this, current.settings.backgroundMode)
                        ?.let(viewModel::reportBackgroundError)
                }
            }
            DisposableEffect(lifecycle) {
                val observer = LifecycleEventObserver { _, event ->
                    if (event == Lifecycle.Event.ON_RESUME) applyBackgroundMode()
                }
                lifecycle.addObserver(observer)
                onDispose { lifecycle.removeObserver(observer) }
            }
            LaunchedEffect(state.ready, state.onboardingVisible, state.settings.personaConfigured, state.savingPersona, state.mutatingHistory, state.settings.backgroundMode, state.settings.language, notificationsAllowed) { applyBackgroundMode() }
            LaunchedEffect(state.ready, state.onboardingVisible, state.settings.personaConfigured, state.savingPersona, state.settings.notificationsEnabled) {
                if (state.ready && state.settings.personaConfigured && !state.savingPersona && !state.onboardingVisible && state.settings.notificationsEnabled) {
                    requestNotificationsIfNeeded()
                }
            }
            CompositionLocalProvider(LocalUiLanguage provides state.settings.language) {
                CompanionTheme(state.settings.darkTheme) {
                    CompanionApp(viewModel, state, notificationsAllowed) {
                        requestNotificationsIfNeeded(userInitiated = true)?.let(viewModel::reportBackgroundError)
                    }
                }
            }
        }
    }

    private fun requestNotificationsIfNeeded(userInitiated: Boolean = false): String? {
        if (Build.VERSION.SDK_INT >= 33) {
            val granted = ContextCompat.checkSelfPermission(this,
                Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            val asked = permissionHistory.getBoolean("notifications_asked", false)
            val shouldAsk = shouldAutoRequestNotifications(Build.VERSION.SDK_INT, granted, asked) ||
                (userInitiated && !granted && shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS))
            if (shouldAsk) {
                permissionHistory.edit { putBoolean("notifications_asked", true) }
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                return null
            }
        }
        if (userInitiated) {
            val opened = runCatching {
                startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
            }.recoverCatching {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, "package:$packageName".toUri()))
            }
            if (opened.isFailure) return "Notification settings unavailable"
        }
        return null
    }
}

@Composable
private fun CompanionApp(viewModel: CompanionViewModel, state: CompanionUiState,
    notificationsAllowed: Boolean, onNotificationSettings: () -> Unit) {
    var screen by rememberSaveable { mutableStateOf(Screen.CHAT) }
    var adminUnlocked by remember { mutableStateOf(false) }
    if (!state.ready || state.mutatingHistory) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                if (state.mutatingHistory) Text(tr("Updating chat history"))
            }
        }
        return
    }
    val advancedVisible = EditionPolicy.advancedSettingsVisible(BuildConfig.IS_FULL, adminUnlocked)
    val visibleScreen = EditionPolicy.resolveScreen(screen, BuildConfig.IS_FULL, adminUnlocked)
    val onboarding = state.onboarding
    if (!state.settings.personaConfigured || state.savingPersona || state.onboardingVisible || visibleScreen == Screen.PERSONA) {
        BackHandler(enabled = state.settings.personaConfigured && !state.savingPersona) {
            viewModel.closeInterview()
            screen = Screen.SETTINGS
        }
        if (onboarding == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                if (state.error == null) CircularProgressIndicator()
                else Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(tr(state.error))
                    TextButton(onClick = viewModel::retryInitialization) { Text(tr("Retry")) }
                }
            }
            return
        }
        PersonaSetupScreen(state.settings, onboarding, state.error, state.savingPersona, state.modelConfigured,
            onLanguage = viewModel::setLanguage,
            onDraft = viewModel::saveInterviewDraft,
            onPreview = viewModel::previewInterview,
            onGenerate = viewModel::generateInterview,
            onSave = { answers, name, proposal -> viewModel.saveInterview(answers, name, proposal) { screen = Screen.CHAT } },
            onBack = if (state.settings.personaConfigured) ({ viewModel.closeInterview(); screen = Screen.SETTINGS }) else null)
        return
    }
    BackHandler(enabled = visibleScreen != Screen.CHAT) {
        screen = if (visibleScreen == Screen.SETTINGS) Screen.CHAT else Screen.SETTINGS
    }
    if (visibleScreen != Screen.CHAT && state.error != null) AlertDialog(
        onDismissRequest = viewModel::clearError,
        title = { Text(tr("Settings")) }, text = { Text(tr(state.error)) },
        confirmButton = { TextButton(onClick = viewModel::clearError) { Text(tr("Cancel")) } },
    )
    if (visibleScreen == Screen.SETTINGS && state.settings.feedbackEnabled && state.periodicFeedbackDue && state.error == null) {
        PeriodicFeedbackDialog(viewModel::dismissPeriodicFeedback, viewModel::submitPeriodicFeedback)
    }
    when (visibleScreen) {
        Screen.CHAT -> ChatScreen(
            state = state,
            onSend = viewModel::send,
            onComposerActivity = viewModel::composerChanged,
            onPickImage = viewModel::pickImage,
            onRemoveImage = viewModel::removeImage,
            onDraftText = viewModel::cacheDraft,
            onSettings = { screen = Screen.SETTINGS },
            onSelect = viewModel::selectMessage,
            onRetry = viewModel::retry,
            onDelete = viewModel::delete,
            onFeedback = viewModel::feedback,
        )
        Screen.SETTINGS -> SettingsScreen(
            onConversation = viewModel::saveConversation,
            settings = state.settings,
            onboardingProgress = onboarding?.let { "${it.answered}/${it.total}" } ?: tr("Not loaded"),
            advancedVisible = advancedVisible,
            onBack = { screen = Screen.CHAT },
            onNavigate = { screen = it },
            onToggle = viewModel::updateToggle,
            onTheme = viewModel::setDarkTheme,
            onClear = { viewModel.clearUserData(); screen = Screen.CHAT },
            onOnboarding = viewModel::startOnboarding,
            onBackgroundMode = viewModel::setBackgroundMode,
            onLanguage = viewModel::setLanguage,
            notificationsAllowed = notificationsAllowed,
            onNotificationSettings = onNotificationSettings,
        )
        Screen.ABOUT -> AboutScreen(
            adminAuth = AdminAuthStore(viewModel.getApplication()),
            onBack = { screen = Screen.SETTINGS },
            onUnlocked = { adminUnlocked = true; screen = Screen.SETTINGS },
        )
        Screen.PROVIDER -> ProviderSettingsScreen(
            initial = state.settings,
            initialApiKey = viewModel.secrets.readApiKey(),
            onBack = { screen = Screen.SETTINGS },
            onSave = { settings, key -> viewModel.saveProvider(settings, key); screen = Screen.SETTINGS },
            onTest = viewModel::testConnection,
        )
        Screen.AUL -> AulInspectorScreen(viewModel) { screen = Screen.SETTINGS }
        Screen.MEMORY -> DebugMemoryScreen(viewModel) { screen = Screen.SETTINGS }
        Screen.ARCHIVES -> ArchiveBrowserScreen(viewModel) { screen = Screen.SETTINGS }
        Screen.SCHEDULER -> SchedulerDebugScreen(viewModel) { screen = Screen.SETTINGS }
        Screen.SCHEDULE_MESSAGES -> ScheduledMessagesScreen(viewModel, state) { screen = Screen.SETTINGS }
        Screen.ADVANCED -> AdvancedSettingsScreen(
            state.settings,
            onBack = { screen = Screen.SETTINGS },
            onSave = { viewModel.saveAdvanced(it); screen = Screen.SETTINGS },
        )
        Screen.PERSONA -> Unit
    }
}
