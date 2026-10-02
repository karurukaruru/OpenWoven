package com.adaptive.companion.data

import org.json.JSONArray
import org.json.JSONObject

data class PersonaSettings(
    val preset: String = "companion",
    val name: String = "",
    val description: String = "",
    val boundaries: String = "",
    val choices: Map<String, String> = emptyMap(),
    val interview: Map<String, String> = emptyMap(),
    val blueprintVersion: Int = 1,
    val generationMethod: String = "",
) {
    fun sanitized() = copy(
        preset = preset.takeIf { it in PRESETS } ?: "companion",
        name = name.trim().take(40), description = description.trim().take(600),
        boundaries = boundaries.trim().take(300),
        choices = choices.filter { (key, value) -> value in (CHOICES[key] ?: emptyList()) },
        interview = interview.filterKeys { it in INTERVIEW_IDS }.mapValues { it.value.trim().take(300) },
        blueprintVersion = if (blueprintVersion == 2) 2 else 1,
        generationMethod = generationMethod.takeIf { it in listOf("", "pending", "model") } ?: "",
    )
    fun json(language: String): JSONObject = sanitized().let { p -> JSONObject()
        .put("preset", p.preset).put("name", p.name).put("description", p.description)
        .put("boundaries", p.boundaries).put("choices", JSONObject(p.choices)).put("language", language)
        .put("interview", JSONObject(p.interview)).put("blueprint_version", p.blueprintVersion)
        .put("generation_method", p.generationMethod) }
    companion object {
        val PRESETS = listOf("companion", "listener", "playful", "coach", "custom")
        val INTERVIEW_IDS = ((21..30) + (36..50)).map { "q" + it.toString().padStart(2, '0') }.toSet()
        val CHOICES = linkedMapOf(
            "support" to listOf("listen", "solutions"), "disagreement" to listOf("gentle", "direct"),
            "playfulness" to listOf("quiet", "playful"), "detail" to listOf("short", "detailed"),
            "initiative" to listOf("wait", "topics"), "closeness" to listOf("reserved", "warm"),
        )
        fun parse(raw: String): PersonaSettings = runCatching {
            val root = JSONObject(raw)
            val choices = root.optJSONObject("choices") ?: JSONObject()
            val interview = root.optJSONObject("interview") ?: JSONObject()
            PersonaSettings(root.optString("preset", "companion"), root.optString("name"),
                root.optString("description"), root.optString("boundaries"),
                choices.keys().asSequence().associateWith { choices.optString(it) },
                interview.keys().asSequence().associateWith { interview.optString(it) },
                root.optInt("blueprint_version", 1), root.optString("generation_method")).sanitized()
        }.getOrDefault(PersonaSettings())
    }
}

/** Pending describes model generation, not whether an explicit nickname exists. */
fun editableCharacterName(persona: PersonaSettings, configured: Boolean): String =
    if (!configured || (persona.generationMethod == "pending" &&
        persona.name in setOf("聊天伙伴", "聊天夥伴", "話し相手", "Companion"))) "" else persona.name

fun retainGeneratedCharacter(existing: PersonaSettings, proposed: PersonaSettings, name: String): PersonaSettings? =
    if (existing.generationMethod == "model" && existing.interview == proposed.interview)
        existing.copy(name = name.ifBlank { existing.name }).sanitized() else null

fun confirmGeneratedCharacter(foundation: PersonaSettings, selected: PersonaSettings?, name: String): PersonaSettings =
    if (selected?.generationMethod == "model" && selected.interview == foundation.interview)
        foundation.copy(name = name.ifBlank { selected.name }, description = selected.description,
            boundaries = foundation.boundaries.ifBlank { selected.boundaries }, generationMethod = "model").sanitized()
    else foundation

/** Capability is explicitly declared by the owner, not inferred from a model name. */
data class ModelChoice(val model: String, val vision: Boolean = false) {
    companion object {
        fun parseList(raw: String): List<ModelChoice> = runCatching {
            val array = JSONArray(raw)
            (0 until array.length()).mapNotNull { i ->
                val item = array.optJSONObject(i) ?: return@mapNotNull null
                val name = item.optString("model").trim().take(120)
                if (name.isBlank()) null else ModelChoice(name, item.optBoolean("vision"))
            }.distinctBy { it.model }.take(20)
        }.getOrDefault(emptyList())
        fun encode(items: List<ModelChoice>): String = JSONArray().apply {
            items.distinctBy { it.model }.take(20).forEach { put(JSONObject().put("model", it.model).put("vision", it.vision)) }
        }.toString()
    }
}
