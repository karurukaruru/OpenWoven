package com.adaptive.companion

import com.adaptive.companion.data.*
import com.adaptive.companion.ui.UiStrings
import com.adaptive.companion.ui.Screen
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class CompanionSetupTest {
    @Test fun productBrandingIsOpenWovenInEveryLanguageWithoutRenamingTheRole() {
        UiStrings.languages.forEach { language ->
            assertEquals("OpenWoven", UiStrings.text(language, "OpenWoven"))
            assertTrue(UiStrings.text(language, "Resident notification").startsWith("OpenWoven"))
            val disclosure = UiStrings.catalog.keys.single { it.startsWith("OpenWoven is an AI system") }
            assertTrue(UiStrings.text(language, disclosure).startsWith("OpenWoven"))
        }
        assertEquals("My nickname", PersonaSettings(name = "My nickname").sanitized().name)
    }

    @Test fun fullInterviewResumesSavedPageEvenWhenOptionalAnswersAreSkipped() {
        val questions = (1..50).map { OnboardingQuestion("q" + it.toString().padStart(2, '0'), "", "text", "", null) }
        val status = OnboardingStatus("in_progress", 10, 50, 10, FIRST_TEN_IDS.associateWith { "__unsure__" },
            questions, resumeIndex = 35, fullInterview = true)
        assertEquals(InterviewPosition(true, 7), interviewPosition(status))
        assertEquals(InterviewPosition(false, 2), interviewPosition(status.copy(fullInterview = false)))
        assertEquals(InterviewPosition(false, 0), interviewPosition(status.copy(answers = emptyMap())))
    }

    @Test fun initialInterviewNeedsTenResponsesButAllowsExplicitUnknown() {
        val complete = FIRST_TEN_IDS.associateWith { "__unsure__" }
        assertEquals(10, FIRST_TEN_IDS.size)
        assertTrue(requiredInterviewComplete(complete))
        FIRST_TEN_IDS.forEach { key ->
            assertFalse(requiredInterviewComplete(complete - key))
            assertFalse(requiredInterviewComplete(complete + (key to "  ")))
            assertFalse(requiredInterviewComplete(complete + (key to Float.NaN)))
            assertFalse(requiredInterviewComplete(complete + (key to true)))
        }
    }

    @Test fun interviewStoresOnlyTheTwentyFiveCharacterAnswers() {
        val p = PersonaSettings(interview = mapOf("q01" to "user", "q36" to "calm",
            "q29" to "0.1", "q99" to "ignored", "q50" to "x".repeat(900)), blueprintVersion = 2).sanitized()
        assertEquals(25, PersonaSettings.INTERVIEW_IDS.size)
        assertEquals(setOf("q36", "q29", "q50"), p.interview.keys)
        assertEquals("0.1", p.interview["q29"])
        assertEquals(300, p.interview["q50"]!!.length)
        assertEquals(2, p.blueprintVersion)
    }

    @Test fun allFiftyQuestionsAndRequiredChoicesHaveFourTranslations() {
        val questions = (1..50).map { "Question q" + it.toString().padStart(2, '0') }
        val choices = listOf("female", "male", "neutral", "listen", "solutions", "mixed").map { "Interview choice $it" }
        (questions + choices).forEach { key ->
            assertTrue(key, UiStrings.catalog.containsKey(key))
            UiStrings.languages.forEach { assertNotEquals(key, UiStrings.text(it, key)) }
        }
    }

    @Test fun providerResetDoesNotEraseAccountRoleOrEnableLearning() {
        val previous = AppSettings(baseUrl = "https://example.invalid/v1", dialogueModel = "chosen-model",
            persona = PersonaSettings("listener"), language = "ja", learningEnabled = false,
            observerEnabled = true, modelSupportsVision = true, temperature = 1.2f)
        val reset = previous.resetGenerationParameters()
        assertEquals(previous.copy(temperature = .7f, topP = 1f, maxTokens = 800, timeoutSeconds = 60, retryCount = 2), reset)
    }

    @Test fun staticUiLabelsCannotSilentlyFallBackToUntranslatedText() {
        val directory = File("src/main/java/com/adaptive/companion/ui")
        assertTrue("UI sources must be accessible", directory.isDirectory)
        val literals = Regex("(?:tr|Section|SettingRow|SettingSwitch|Field|NumberField|IntSetting)\\(\"([^\"$]+)\"")
        val allowedBrandingAndSymbols = setOf("Companion", "›", "👎")
        directory.listFiles()!!.filter { it.extension == "kt" && it.name != "Localization.kt" }.forEach { file ->
            literals.findAll(file.readText()).forEach { match ->
                val key = match.groupValues[1]
                assertTrue("${file.name}: $key", key in allowedBrandingAndSymbols || UiStrings.catalog.containsKey(key))
            }
        }
    }

    @Test fun everyUiStringHasFourNonemptyTranslations() {
        UiStrings.catalog.forEach { (key, translations) ->
            assertEquals(key, 4, translations.size)
            assertTrue(key, translations.all { it.isNotBlank() })
            val placeholders = Regex("\\{[0-9]+\\}")
            val expected = placeholders.findAll(translations[0]).map { it.value }.toSet()
            translations.forEach { assertEquals(key, expected, placeholders.findAll(it).map { m -> m.value }.toSet()) }
        }
    }

    @Test fun scenarioRoleAndPreferenceLabelsExistInEveryLanguage() {
        val keys = PersonaSettings.PRESETS.flatMap { listOf("Role $it", "Role description $it") } +
            PersonaSettings.CHOICES.flatMap { (key, values) -> listOf("Scenario $key") + values.map { "Choice $it" } } +
            listOf("Preference help", "Language help", "Vision help", "Role transparency")
        keys.forEach { key ->
            assertTrue(key, UiStrings.catalog.containsKey(key))
            UiStrings.languages.forEach { language -> assertNotEquals(key, UiStrings.text(language, key)) }
        }
    }

    @Test fun formattingPreservesUserDataAndLanguageSwitchChangesLabels() {
        assertEquals("Settings", UiStrings.text("en-US", "Settings"))
        assertEquals("設定", UiStrings.text("ja", "Settings"))
        assertEquals("第 3 頁", UiStrings.text("zh-TW", "Page {0}", 3))
        assertEquals("my original words", UiStrings.text("ja", "my original words"))
    }

    @Test fun invalidPersonaIsBoundedAndUnknownChoicesAreDiscarded() {
        val p = PersonaSettings("unknown", "x".repeat(100), "x".repeat(1000), "x".repeat(900),
            mapOf("support" to "listen", "detail" to "invalid", "other" to "listen")).sanitized()
        assertEquals("companion", p.preset)
        assertEquals(40, p.name.length)
        assertEquals(600, p.description.length)
        assertEquals(300, p.boundaries.length)
        assertEquals(mapOf("support" to "listen"), p.choices)
        assertEquals(Screen.PERSONA, EditionPolicy.resolveScreen(Screen.PERSONA, false, false))
    }

    @Test fun finiteDefaultsAreRestoredAndModelCapabilitiesRemainPerModel() {
        val s = AppSettings(language = "invalid", temperature = Float.NaN, topP = Float.POSITIVE_INFINITY,
            weakEvidenceRate = Float.NaN, splitProbability = Float.NaN,
            dialogueModel = " model-b ", modelSupportsVision = false,
            modelChoices = listOf(ModelChoice("model-a", true), ModelChoice("model-b", true))).sanitized()
        assertEquals("zh-CN", s.language)
        assertEquals(.7f, s.temperature)
        assertEquals(1f, s.topP)
        assertEquals(.025f, s.weakEvidenceRate)
        assertEquals(.32f, s.splitProbability)
        assertEquals(listOf(ModelChoice("model-a", true), ModelChoice("model-b", false)), s.modelChoices)
    }

    @Test fun everyNumericParameterHasHelpWithItsDefault() {
        val timing = AppSettings()
        val defaults = mapOf("Temperature" to "0.7", "Top P" to "1", "Max tokens" to "800",
            "Timeout seconds" to "60", "Retry" to "2", "Context budget" to "5400",
            "Summary message threshold" to "12", "Summary token threshold" to "5400",
            "Weak evidence rate" to "0.025", "Explicit evidence rate" to "0.11", "Correction evidence rate" to "0.36",
            "Maximum per day" to "1", "Minimum interval hours" to "8", "Quiet starts" to "22", "Quiet ends" to "8",
            "Importance threshold" to "0.68", "Base delay ms" to timing.baseDelayMs.toString(), "Per character ms" to timing.delayPerCharacterMs.toString(),
            "Random jitter ms" to timing.jitterMs.toString(), "Minimum delay ms" to timing.minDelayMs.toString(),
            "Maximum delay ms" to timing.maxDelayMs.toString(), "Split probability" to "0.32")
        defaults.forEach { (name, default) ->
            UiStrings.languages.forEach { language -> assertTrue(name, UiStrings.text(language, "Help $name").contains(default)) }
        }
    }
}
