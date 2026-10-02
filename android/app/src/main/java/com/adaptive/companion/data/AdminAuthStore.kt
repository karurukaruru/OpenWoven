package com.adaptive.companion.data

import android.content.Context
import android.util.Base64
import androidx.core.content.edit
import java.security.SecureRandom
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

class AdminAuthStore(context: Context) {
    private val preferences = context.getSharedPreferences("admin_auth", Context.MODE_PRIVATE)

    init {
        // The Locked edition ships with a known administrative gate. Store only
        // the fixed PBKDF2 material, never the plaintext password in the APK.
        if (!preferences.contains("hash")) {
            preferences.edit {
                putString("salt", DEFAULT_SALT)
                putString("hash", DEFAULT_HASH)
            }
        }
    }

    val hasPassword: Boolean get() = preferences.contains("hash")

    fun create(password: CharArray) {
        try {
            require(password.size >= 6) { "Administrator password must contain at least 6 characters" }
            val salt = ByteArray(16).also(SecureRandom()::nextBytes)
            val hash = derive(password, salt)
            preferences.edit {
                putString("salt", Base64.encodeToString(salt, Base64.NO_WRAP))
                putString("hash", Base64.encodeToString(hash, Base64.NO_WRAP))
            }
        } finally {
            password.fill('\u0000')
        }
    }

    fun verify(password: CharArray): Boolean {
        return try {
            val salt = preferences.getString("salt", null)?.let { Base64.decode(it, Base64.NO_WRAP) }
                ?: return false
            val expected = preferences.getString("hash", null)?.let { Base64.decode(it, Base64.NO_WRAP) }
                ?: return false
            java.security.MessageDigest.isEqual(expected, derive(password, salt))
        } finally {
            password.fill('\u0000')
        }
    }

    private fun derive(password: CharArray, salt: ByteArray): ByteArray =
        SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
            .generateSecret(PBEKeySpec(password, salt, 120_000, 256)).encoded

    private companion object {
        const val DEFAULT_SALT = "T25ib2FyZGluZ0F1bDI2MA=="
        const val DEFAULT_HASH = "DkLW/YwfKgmn1cZgpfqWejLkhq7eYCNd1YOXqWg4UME="
    }
}
