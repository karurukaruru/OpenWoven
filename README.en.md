# OpenWoven

[中文](README.md)

## What is OpenWoven?

OpenWoven is an AI chat app. You can talk to an LLM through it, while the app gradually records your preferences and communication habits to guide later replies.

The user-learning system is called AUL, AI User Learning. The app also has conversation memory, separate short messages and proactive messaging. An Android client is available in the source.

## Quick start

The Android app requires Android 8.0 or newer and your own model API.

1. Complete the initial questions to establish basic user and character settings.
2. Enter your endpoint, API key and model in Settings.
3. Optionally ask the current model to suggest a character and nickname, then review and confirm them.
4. Allow notifications if you want proactive messages, and adjust frequency and quiet hours.

API calls may cost money, and relevant conversation context goes to your chosen provider.

An APK has not yet been attached to [Releases](https://github.com/karurukaruru/OpenWoven/releases). For now, follow the [source build instructions](CONTRIBUTING.md#android); a download link will be added when a package is published.

## What is AUL?

AUL is a user-learning system for AI. Its idea grew out of my earlier [ASM (Agent Software Map)](https://github.com/karurukaruru/agent-software-map) project.

ASM records what an agent needs to know when using software. Here, the subject becomes the user: what they like, what they dislike, and how they want someone to talk to them.

The app also keeps the character that the LLM should portray. “Who should the character be?” and “Who is the user, and how do they like to talk?” are recorded separately.

For example, someone may prefer short replies, enjoy a little banter, and dislike repeated advice when they are upset. Those preferences can gradually be recorded and used alongside the current conversation.

AUL starts with an initial state. Preferences, dislikes and clear feedback such as “too long” or “stop asking so many questions” become signals that update it. The next conversation reads the updated AUL, and the process continues.

That is the basic idea: start with a little knowledge, adjust it after talking, and use it next time. AUL is a kind of memory focused on the user's profile and communication habits.

### Where does the initial AUL come from?

Setup starts with ten questions: five about the user and five about the desired character. The full interview has fifty questions, which can be completed later. Uncertain answers can stay unanswered.

There is no rigorous scientific basis for the number fifty. I chose it as a way to get an initial AUL together. I did not write every question myself; I described the general direction and had GPT and Codex organize the questions.

The interview is only a starting point. Users can edit their information, give feedback and correct assumptions in conversation. Character settings and previously mentioned background are also retained to help keep things consistent.

## How does Memory work?

Conversation records are organized by day, week and month. The app summarizes the day, then the completed week and month. These follow calendar periods, rather than assuming every month has thirty days.

Original messages are kept too. Date and keyword searches can find related summaries and original excerpts without sending the entire history with every request.

The current summaries are assembled by the app from recorded information and original excerpts. They do not make an extra daily LLM call. Model-written summaries may be considered later if needed.

## Talk: everyday messaging

Talk is a simple chat screen. I mainly took inspiration from casual messaging in mainland China and Hong Kong, where people often send a thought across several short messages rather than writing everything in one long paragraph.

### Waiting until the user has finished

Several consecutive messages are understood as one turn.

Replies pause while there is unfinished text or IME composition in the input box. Once messages have been sent and the user stops typing or interacting with the composer, the app waits twenty seconds by default before requesting a reply. This is adjustable from ten to sixty seconds.

Only this app's composer is observed, not keyboards in other apps.

### Sending replies as separate messages

Casual replies are split into separate message bubbles, not just spaced-out text inside one message.

Messages usually arrive about a second or two apart, with slightly longer pauses for longer sentences. Everyday replies default to brief, conversational wording; length is adjustable. Code, technical explanations and explicitly requested long documents are not forced into this style.

### Greeting delays and proactive messages

There is an optional greeting delay. A standalone “are you there” can wait one to three minutes before a reply. It is off by default, and does not add that delay to every message.

The app can also message first. After some conversation, it can schedule a light opening based on recent topics, interests and the initiative preference. When due, it generates and sends the message if the opening has not been cancelled by new conversation and the delivery conditions still hold.

This is not a fixed “send after ten minutes” rule. Frequency, spacing and quiet hours affect scheduling. New user messages cancel old casual openings, and unanswered openings are not repeatedly sent. Proactive openings use separate short bubbles too.

You can also explicitly schedule original text or ask the model to discuss a topic at a chosen time.

Google FCM is not integrated. Android background services and system work handle scheduling and notifications; phone background and battery restrictions can affect delivery time.

## Images and settings

Model settings let you declare whether the selected model supports vision. If it actually does, images can be selected and sent from the chat composer.

Users can send images, but the character cannot send images back yet. Image generation is not integrated. It may be added later; the focus for now is text chat.

Reply length, initiative, waiting time and learning parameters can be adjusted. A standalone AUL import/export feature is not implemented yet.

## Core mechanism

Conversation and learning form a loop:

```text
Read AUL, character settings and relevant memory → choose reply guidance → LLM reply
Save conversation and feedback → extract preference/state signals → update AUL → read it next time
```

Clear preferences and corrections are primarily extracted through rules and feedback. Optional model analysis can add signals. Signals are saved and aggregated into AUL, rather than asking a model to rewrite the entire profile after every message. Model weights are not changed.

Conversation records, user preferences and character background are stored separately. Each request includes the relevant parts for this conversation.

Implementation details: [AUL](AUL_DESIGN.md), [Memory](MEMORY_DESIGN.md) and [Architecture](ARCHITECTURE.md).

To try the learning demo without an API key, use Python 3.11+:

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
```

The demo uses sample replies, not a real model.

## Project structure

```text
android/                  Android chat, settings and notifications
src/openwoven/            Python entry points
src/adaptive_companion/    AUL, memory, reply guidance and message scheduling
prompts/                  Character-generation prompts
examples/                 Memory and retrieval demos
tests/                    Core regression tests
```

The app is broadly working, but I have not used it extensively. How much AUL helps and how well memory holds up over time still need actual use.

Licensed under [MIT](LICENSE). Issues are welcome; please leave out API keys and private conversations.
