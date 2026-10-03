# OpenWoven

An AI chat app that gets to know you over time.

[中文](README.md)

OpenWoven records preferences, communication habits and relevant experiences through ongoing conversations and feedback, then uses that information to guide future replies. You can configure a chat character; character details and conversation memory help maintain continuity.

Android and local Web clients are available, using your own model API.

## Quick start

1. [Download the APK](https://github.com/karurukaruru/OpenWoven/releases/download/v0.2.0/OpenWoven-0.2.0-debug.apk) and install it on Android 8.0 or newer.
2. Enter your endpoint, API key and model name in Settings.
3. Complete the initial questions to set up user information and a chat character. You can also ask the model to suggest a character and nickname, then review them before use.
4. Enable proactive messages and allow notifications if desired.

Setup starts with ten questions; the full fifty-question interview can be completed later. It establishes a starting point, not a psychological assessment. Conversation, feedback and settings can refine it over time.

API calls may incur charges, and relevant conversation context is sent to your chosen provider. You can also [build the app from source](CONTRIBUTING.md#android).

## Features

- AUL (AI User Learning): a user-learning system adapted from the idea behind ASM ([Agent Software Map](https://github.com/karurukaruru/agent-software-map)). Initial questions establish user information and a character; conversation and feedback provide evidence to refine preferences for later replies. This is memory and conversation guidance, not model training or a fixed personality assessment.
- Character management: create and switch characters with separate conversations and memory. Export character settings and backstory as a ZIP for use in either client, without user profiles, chats or API keys. Common JSON/PNG character cards can be converted to basic settings with a preview; complete compatibility with every application's format is not guaranteed.
- Conversation memory: records are archived by day, week and calendar month. With a model configured, completed weeks receive LLM-written summaries; daily and monthly archives retain structured highlights and source links. Failed weekly requests leave original messages intact for later retries. Date and keyword retrieval adds relevant context without sending the entire history.
- Message pacing: consecutive user messages are treated as one turn. The default wait after input stops is twenty seconds, adjustable from ten to sixty seconds. Everyday replies arrive as separate short messages, usually one or two seconds apart. Length is adjustable; code and requested long documents are not forcibly split. Only the app's own composer is observed, not keyboards in other apps.
- Proactive messages: the app schedules openings based on recent topics, or sends exact text or model-generated messages at a chosen time. Openings are limited to one to three short messages rather than unsolicited essays. Frequency, spacing, quiet hours and greeting delays are configurable. Android background services and system work handle notifications; battery management may affect delivery time.
- Images and settings: mark a model as vision-capable to select and send images. Character image replies and image generation are not currently supported. The interface supports Simplified Chinese, Traditional Chinese, Japanese and English. Models, reply preferences and learning parameters can be adjusted in Settings.

## Local Web client

Run with Python 3.11+ on Windows, macOS or Linux:

```sh
python -m pip install -e .
python -m openwoven.web
```

Open `http://127.0.0.1:8765` and configure your model endpoint in Settings. Text chat, input-aware waiting, paced bubbles, role packages and scheduled messages use the same Core. Image input and OS notifications are not available in this Web version. The API key stays in server memory and must be entered again after restart. Keep the process running for scheduled delivery.

This is a local client, not a public server. Role packages can be exchanged, but chats and user information are not automatically synchronized. See [Role packages](ROLE_PACKAGES.md) for compatibility details.

## Implementation and development

User preferences, character details and conversation records are stored separately. Each turn uses relevant memory to guide a reply, then saves conversation and feedback to refine later interactions. Model weights are not modified.

See [Memory design](MEMORY_DESIGN.md), [Architecture](ARCHITECTURE.md) and [Contributing](CONTRIBUTING.md).

To run the core demo without an API key, use Python 3.11+:

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
```

The demo uses local sample replies and does not call a real model.

This is an experimental project. Long-term memory quality and background behavior on physical devices still need validation. Issues and suggestions are welcome; please omit API keys and private conversations.

Project source is licensed under [MIT](LICENSE). Third-party components retain their own licenses.
