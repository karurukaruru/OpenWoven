package com.adaptive.companion.data

import org.junit.Assert.*
import org.junit.Test

class NumericSettingsDraftsTest {
    @Test fun clearingAnIntegerKeepsTheDraftAndBlocksSavingThePreviousValue() {
        val draft = NumericSettingsDrafts.provider(AppSettings()).edit("Max tokens", "")
        assertEquals("", draft.text("Max tokens"))
        assertFalse(draft.providerValid)
        assertTrue(runCatching { draft.applyProvider(AppSettings()) }.isFailure)
    }

    @Test fun decimalEditingDoesNotReformatTheTextAfterEveryKeystroke() {
        var draft = NumericSettingsDrafts.provider(AppSettings()).edit("Temperature", "0.")
        assertEquals("0.", draft.text("Temperature"))
        draft = draft.edit("Temperature", "0.35")
        assertEquals("0.35", draft.text("Temperature"))
        assertTrue(draft.providerValid)
        assertEquals(0.35f, draft.applyProvider(AppSettings()).temperature)
    }

    @Test fun partialAndOverflowInputsAreNotSavedAsOldNumbers() {
        listOf("", "-", ".", "text", "NaN", "Infinity", "1e100").forEach { text ->
            val draft = NumericSettingsDrafts.provider(AppSettings()).edit("Temperature", text)
            assertEquals(text, draft.text("Temperature"))
            assertFalse("$text must be invalid", draft.providerValid)
        }
        listOf("-", "2.5", "2147483648", "1e3").forEach { text ->
            assertFalse(NumericSettingsDrafts.advanced(AppSettings()).edit("Context budget", text).advancedValid)
        }
    }

    @Test fun resetReplacesEvenAnInvalidDraftWithoutChangingAccountOrModels() {
        val source = AppSettings(dialogueModel = "synthetic-model", baseUrl = "https://example.invalid/v1",
            temperature = 1.1f, observerEnabled = true)
        val invalid = NumericSettingsDrafts.provider(source).edit("Temperature", "-")
        assertFalse(invalid.providerValid)
        val resetSettings = source.resetGenerationParameters()
        val resetDraft = NumericSettingsDrafts.provider(resetSettings)
        val restored = resetDraft.applyProvider(resetSettings)
        assertEquals("0.7", resetDraft.text("Temperature"))
        assertEquals(source.dialogueModel, restored.dialogueModel)
        assertEquals(source.baseUrl, restored.baseUrl)
        assertTrue(restored.observerEnabled)
    }

    @Test fun restoredNumericDraftsOverrideAnUnrelatedBackendSnapshotOnlyForNumericFields() {
        val draft = NumericSettingsDrafts.provider(AppSettings()).edit("Max tokens", "1024")
        val restored = NumericSettingsDrafts(draft.values.toMap())
        val refreshed = AppSettings(dialogueModel = "refreshed-model", retryCount = 4)
        val saved = restored.applyProvider(refreshed)
        assertEquals(1024, saved.maxTokens)
        assertEquals("refreshed-model", saved.dialogueModel)
        assertEquals(2, saved.retryCount)
    }

    @Test fun advancedDraftsCommitTogetherAndKeepExistingSanitization() {
        val original = AppSettings(weakEvidenceRate = .035f, splitProbability = .7f)
        val draft = NumericSettingsDrafts.advanced(original)
            .edit("Context budget", "7200")
            .edit("Minimum delay ms", "1500")
            .edit("Maximum delay ms", "100")
            .edit("Quiet starts", "99")
        val saved = draft.applyAdvanced(original).sanitized()
        assertEquals(7200, saved.contextBudget)
        assertEquals(1500, saved.maxDelayMs)
        assertEquals(23, saved.quietStart)
        assertEquals(original.weakEvidenceRate, saved.weakEvidenceRate)
        assertEquals(original.splitProbability, saved.splitProbability)
    }

    @Test fun whitespaceIsRetainedWhileParsedNumbersRemainFinite() {
        val draft = NumericSettingsDrafts.provider(AppSettings()).edit("Top P", " 0.8 ")
        assertEquals(" 0.8 ", draft.text("Top P"))
        assertTrue(draft.providerValid)
        assertEquals(.8f, draft.applyProvider(AppSettings()).topP)
    }

    @Test fun incompleteSchemasAndUnknownFieldsCannotSilentlyDropAnEditedValue() {
        val draft = NumericSettingsDrafts.provider(AppSettings())
        assertTrue(runCatching { draft.edit("unknown", "100") }.isFailure)
        assertFalse(NumericSettingsDrafts(draft.values - "Retry").providerValid)
        assertFalse(NumericSettingsDrafts(draft.values + ("Extra" to "1")).providerValid)
    }
}
