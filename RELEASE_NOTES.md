# OpenWoven v0.1.0

An AI chat app that gets to know you over time.

## Download

The Android APK is an experimental Debug build for Android 8.0+, supporting arm64-v8a and x86_64. Configure your own model API in Settings. API calls may incur charges.

This version includes conversation memory, model-written weekly summaries, separate paced messages, proactive openings, scheduled messages and image input for vision-capable models.

Daily, monthly and rolling structured archives remain local. Originals are retained. Weekly model summaries use bounded excerpts and recorded signals; failed requests are retried later without deleting the conversation.

## Notes

- This is a prerelease, not a production-signed or app-store build.
- Battery and background restrictions may delay scheduled messages.
- Model quality and physical-device behavior have not been validated with real API calls in this release check.
- Debug signing keys may differ between builds; uninstalling the app removes local data.
- Relevant conversation context is sent to the provider you configure.

The download includes SHA256 checksums and third-party notices. Project source is MIT-licensed; dependencies retain their own licenses.

中文：本次提供 Android 体验版 APK。配置模型后即可使用；周摘要由 LLM 生成，消息分条与主动发送保留。该版本仍为实验性 Debug 构建。
