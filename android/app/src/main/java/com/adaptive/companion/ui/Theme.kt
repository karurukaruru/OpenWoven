package com.adaptive.companion.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFF405F69),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD6E4E8),
    surface = Color(0xFFF8FAFA),
    surfaceContainer = Color(0xFFEEF2F2),
    surfaceContainerHigh = Color(0xFFE5EBEB),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFAFCBD3),
    primaryContainer = Color(0xFF294851),
    surface = Color(0xFF101415),
    surfaceContainer = Color(0xFF1A2022),
    surfaceContainerHigh = Color(0xFF242C2E),
)

@Composable
fun CompanionTheme(dark: Boolean? = null, content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (dark ?: isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
