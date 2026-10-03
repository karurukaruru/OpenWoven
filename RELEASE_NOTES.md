# OpenWoven v0.2.0

An AI chat app that gets to know you over time.

## Download

The Android APK is an experimental Debug build for Android 8.0+, supporting arm64-v8a and x86_64. Configure your own model API in Settings. API calls may incur charges.

This version includes conversation memory, model-written weekly summaries, separate paced messages, proactive openings, scheduled messages and image input for vision-capable models.

New: create, import, export and switch characters with separate chats and memory. Role-only ZIPs work in both Android and the new local Web client. Common JSON/PNG character cards support basic text conversion, not complete or lossless compatibility.

To run the Web client, install the source with Python 3.11+ (`python -m pip install -e .`) and run `python -m openwoven.web`. Open `http://127.0.0.1:8765`. This is a local text client, not a hosted public service; image input and OS notifications remain Android-only. API keys stay in Web server memory, and scheduled delivery requires the process to keep running.

Daily, monthly and rolling structured archives remain local. Originals are retained. Weekly model summaries use bounded excerpts and recorded signals; failed requests are retried later without deleting the conversation.

## Notes

- This is a prerelease, not a production-signed or app-store build.
- Battery and background restrictions may delay scheduled messages.
- Model quality and physical-device behavior have not been validated with real API calls in this release check.
- Debug signing keys may differ between builds; uninstalling the app removes local data.
- Relevant conversation context is sent to the provider you configure.

The download includes SHA256 checksums and third-party notices. Project source is MIT-licensed; dependencies retain their own licenses.

中文：新增角色导入、导出与切换，各角色的聊天和记忆独立保存；提供共用 Core 的本地 Web 客户端。角色包不含用户资料、聊天或 Key。该版本仍为实验性 Debug 构建。
