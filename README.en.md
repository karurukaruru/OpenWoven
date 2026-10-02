# OpenWoven

[中文](README.md)

An Android chat app with long-term memory and proactive messages. Connect your own model API to chat.

## Where it came from

I wanted to try making a chat partner that gradually gets to know how you like to talk.

An earlier project, ASM (Agent Software Map), let an agent remember how to use software. While working on an interactive plush-toy project, I tried applying the same idea to people: remember their communication preferences and adjust over time.

I called that part AUL, AI User Learning. The name is informal. The idea is simply to learn from conversations rather than keep the same settings forever.

## What it does

Setup starts with ten questions about you and the character you would like to talk to. There are fifty questions if you want to add more. Unanswered questions can stay unanswered.

The interview is a starting point, not a permanent label. If you initially ask for detailed replies and later find them too long, that should be easy to change. Clear requests and feedback such as “too long” or “too many questions” help adjust future replies. The character's settings and previously mentioned background are also kept for continuity.

Everyday replies are split into separate short messages with a little time between them. If you are still composing, the app waits before replying.

It can also start a conversation. You can schedule a message or have the model generate a topic when it is due. Frequency limits and quiet hours are configurable, and Android notifications are supported. Phone background restrictions can still delay delivery.

Conversation history is organized into daily, weekly and monthly records while keeping the originals. Date and keyword searches can bring back relevant excerpts without putting the entire history into every request.

There is also model switching, image sending and chat feedback. Images need a model that supports vision.

## Using it

Android 8.0 or newer.

Complete the initial questions, then configure the endpoint, model and your own API key in Settings. You can ask the model to suggest a character and nickname, review them, and start chatting. Allow notifications if you want proactive messages.

API calls may cost money, and relevant conversation context is sent to your chosen provider. There is no official APK download in the repository yet; see [building from source](CONTRIBUTING.md#android).

To try the preference-learning demo without an API key, use Python 3.11+:

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
```

The demo uses sample replies, not a real model.

## Current state

The Android app is working, but it is still rough. I have not used it extensively, so I do not yet know how much AUL helps or how well the memory holds up over time.

I am putting it out here to try it, fix things and see what happens. Issues are welcome; please leave out API keys and private conversations.

More detail: [AUL](AUL_DESIGN.md) · [Memory](MEMORY_DESIGN.md) · [Architecture](ARCHITECTURE.md). Licensed under [MIT](LICENSE).
