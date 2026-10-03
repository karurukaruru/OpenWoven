package com.adaptive.companion.data

import org.junit.Assert.*
import org.junit.Test

class RoleIdentityTest {
    @Test fun legacyInstallationPathsNeverMove() {
        for (id in listOf("", "legacy", "../outside", "C:\\private", "invalid")) {
            val persona = PersonaSettings(characterId = id)
            assertEquals("adaptive_companion.db", roleDatabaseName(persona))
            assertEquals("chat_images", roleImageDirectory(persona))
        }
    }

    @Test fun newRolesUseValidatedSeparateDatabaseAndImagePaths() {
        val id = "a".repeat(32)
        val persona = PersonaSettings(characterId = id)
        assertEquals("role_$id.db", roleDatabaseName(persona))
        assertEquals("role_images/$id", roleImageDirectory(persona))
        assertEquals(id, persona.copy(name = "new nickname").sanitized().characterId)
    }

    @Test fun confirmedModelDraftKeepsTheSelectedLocalIdentity() {
        val id = "b".repeat(32)
        val foundation = PersonaSettings(characterId = id)
        val model = foundation.copy(generationMethod = "model", description = "model role")
        assertEquals(id, confirmGeneratedCharacter(foundation, model, "Case").characterId)
    }
}
