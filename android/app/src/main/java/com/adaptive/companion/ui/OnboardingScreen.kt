package com.adaptive.companion.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.adaptive.companion.data.OnboardingQuestion
import com.adaptive.companion.data.interviewSliderEndpoints
import java.util.Locale

@Composable
fun InterviewQuestionEditor(question: OnboardingQuestion, value: Any?, required: Boolean, onAnswer: (Any?) -> Unit) {
    val unsure = value == "__unsure__"
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(tr(if (question.target == "user") "Interview user section" else "Interview character section"),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text(tr("Question ${question.id}"), style = MaterialTheme.typography.titleSmall)
            when (question.kind) {
                "choice" -> FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    question.options.forEach { option ->
                        FilterChip(selected = value == option, onClick = { onAnswer(option) },
                            label = { Text(tr("Interview choice $option")) })
                    }
                }
                "slider" -> {
                    val amount = ((value as? Number)?.toFloat() ?: question.defaultValue ?: .5f)
                        .takeIf { it.isFinite() }?.coerceIn(0f, 1f) ?: .5f
                    val endpoints = interviewSliderEndpoints(question.id)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(tr("Slider left {0}", tr(endpoints.first)), style = MaterialTheme.typography.bodySmall)
                        Text(tr("Slider right {0}", tr(endpoints.second)), style = MaterialTheme.typography.bodySmall)
                    }
                    Slider(amount, { onAnswer(it) }, valueRange = 0f..1f)
                    Text(tr("Slider value {0}", String.format(Locale.ROOT, "%.2f", amount)))
                    Text(tr(if (value is Number) "Interview selected level" else "Interview untouched slider"), style = MaterialTheme.typography.bodySmall)
                    if (value !is Number) TextButton(onClick = { onAnswer(amount) }) { Text(tr("这个程度就好")) }
                }
                else -> OutlinedTextField(value = if (unsure) "" else value?.toString().orEmpty(),
                    onValueChange = { onAnswer(it.take(300)) }, modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text(tr("Interview keyword hint")) }, minLines = 1, maxLines = 4)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = unsure, onClick = { onAnswer("__unsure__") },
                    label = { Text(tr("Interview unsure")) })
                if (value != null) TextButton(onClick = { onAnswer(null) }) { Text(tr("Clear choice")) }
            }
            if (required) Text(tr("Interview required hint"), style = MaterialTheme.typography.bodySmall)
        }
    }
}
