package com.adaptive.companion.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import android.net.Uri
import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.util.UUID

object PickedImageStore {
    suspend fun import(context: Context, uri: Uri): String = withContext(Dispatchers.IO) {
        val bytes = context.contentResolver.openInputStream(uri)?.use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                require(output.size() + count <= 20_000_000) { "Image is too large" }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
            ?: error("Image could not be opened")
        require(bytes.size <= 20_000_000) { "Image is too large" }
        val bitmap = if (Build.VERSION.SDK_INT >= 28) {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(ByteBuffer.wrap(bytes))) { decoder, info, _ ->
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                val scale = minOf(1.0, 1536.0 / maxOf(info.size.width, info.size.height))
                decoder.setTargetSize(maxOf(1, (info.size.width * scale).toInt()), maxOf(1, (info.size.height * scale).toInt()))
            }
        } else {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Image could not be opened" }
            val options = BitmapFactory.Options().apply {
                inSampleSize = 1
                while (maxOf(bounds.outWidth, bounds.outHeight) / inSampleSize > 1536) inSampleSize *= 2
            }
            val decoded = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options) ?: error("Image could not be opened")
            val orientation = runCatching { ExifInterface(ByteArrayInputStream(bytes)).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1) }.getOrDefault(1)
            val transform = Matrix().apply {
                when (orientation) {
                    2 -> setScale(-1f, 1f)
                    3 -> setRotate(180f)
                    4 -> setScale(1f, -1f)
                    5 -> { setRotate(90f); postScale(-1f, 1f) }
                    6 -> setRotate(90f)
                    7 -> { setRotate(270f); postScale(-1f, 1f) }
                    8 -> setRotate(270f)
                }
            }
            Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, transform, true).also {
                if (it !== decoded) decoded.recycle()
            }
        }
        val directory = File(context.filesDir, "chat_images").apply { mkdirs() }
        val target = File(directory, UUID.randomUUID().toString() + ".jpg")
        try {
            target.outputStream().use { require(bitmap.compress(Bitmap.CompressFormat.JPEG, 82, it)) }
            require(target.length() in 1..2_000_000) { "Image is too large" }
            currentCoroutineContext().ensureActive()
            target.absolutePath
        } catch (error: Exception) {
            target.delete()
            throw error
        } finally { bitmap.recycle() }
    }

    fun removeDraft(context: Context, path: String) {
        val target = File(path).canonicalFile
        if (target.parentFile == File(context.filesDir, "chat_images").canonicalFile && target.extension == "jpg") target.delete()
    }
}
