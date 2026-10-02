"""Small JSON boundary used by the Android/Chaquopy layer."""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import asdict
from typing import Any

from .core import CompanionCore
from .aggregator import AggregationConfig
from .delivery import DeliverySettings
from .llm import LocalCompanionProvider, OpenAICompatibleProvider
from .proactive import ProactiveSettings
from .persona import build_persona
from .models import utc_now
from .character_interview import pending_persona, character_generation_prompt, clean_answers
from .semantic_observer import HybridObserver, OpenAICompatibleEvidenceObserver
from .turns import composer_gate


_lock = threading.RLock()
_core: CompanionCore | None = None
_clock: str = ''


def note_composer(has_draft: bool, conversation_id: str = 'default') -> None:
    # Must remain independent of the serialized model call / SQLite connection.
    composer_gate.note(conversation_id, has_draft)


def set_clock(local_iso: str, zone: str) -> None:
    from datetime import datetime
    datetime.fromisoformat(local_iso)
    global _clock
    _clock = local_iso + ' [' + zone[:100] + ']'


def initialize(database_path: str, config_json: str = "{}") -> str:
    global _core
    config = json.loads(config_json or "{}")
    if not isinstance(config, dict) or any(not isinstance(config.get(key, {}), dict)
                                          for key in ('provider', 'delivery', 'proactive', 'learning')):
        raise ValueError('Core configuration and its sections must be JSON objects')
    with _lock:
        previous, _core = _core, None
        if previous is not None:
            previous.close()
        provider_config = config.get("provider", {})
        api_key = provider_config.get("api_key", "")
        if api_key:
            provider = OpenAICompatibleProvider(
                base_url=provider_config.get("base_url", "https://api.openai.com/v1"),
                api_key=api_key,
                model=provider_config.get("dialogue_model", "gpt-4.1-mini"),
                temperature=float(provider_config.get("temperature", 0.7)),
                top_p=float(provider_config.get("top_p", 1.0)),
                max_tokens=int(provider_config.get("max_tokens", 800)),
                timeout=int(provider_config.get("timeout", 60)),
                retry=int(provider_config.get("retry", 2)),
            )
        else:
            provider = LocalCompanionProvider()

        observer = None
        if config.get("observer_enabled") and api_key:
            observer = HybridObserver(OpenAICompatibleEvidenceObserver(
                base_url=provider_config.get("base_url", "https://api.openai.com/v1"),
                api_key=api_key,
                model=provider_config.get("observer_model") or provider_config.get("dialogue_model", "gpt-4.1-mini"),
                timeout=int(provider_config.get("timeout", 60)),
            ))
        timing = config.get("delivery", {})
        proactive = config.get("proactive", {})
        learning = config.get("learning", {})
        persona = build_persona(config.get('persona'))
        persona_config = config.get('persona')
        persona_config = persona_config if isinstance(persona_config, dict) else {}
        length_answer = clean_answers(persona_config.get('interview')).get('q21')
        if not isinstance(length_answer, (int, float)) and 'detail' not in persona['scenario_choices']:
            persona['initial_style']['reply_length'] = max(0, min(1, float(config.get('daily_reply_length', .30))))
        _core = CompanionCore(
            database_path,
            provider=provider,
            persona=persona,
            observer=observer,
            context_budget=int(config.get("context_budget", 5400)),
            summary_message_threshold=int(config.get("summary_message_threshold", 12)),
            summary_token_threshold=int(config.get("summary_token_threshold", 5400)),
            delivery_settings=DeliverySettings(
                enabled=bool(timing.get("enabled", True)),
                greeting_delay_enabled=bool(timing.get("greeting_delay_enabled", False)),
                base_delay_ms=int(timing.get("base_delay_ms", 750)),
                delay_per_character_ms=int(timing.get("delay_per_character_ms", 30)),
                random_jitter_ms=int(timing.get("random_jitter_ms", 150)),
                split_probability=float(timing.get("split_probability", 0.32)),
                minimum_delay_ms=int(timing.get("minimum_delay_ms", 800)),
                maximum_delay_ms=int(timing.get("maximum_delay_ms", 2500)),
            ),
            proactive_settings=ProactiveSettings(
                enabled=bool(proactive.get("enabled", True)),
                max_per_day=int(proactive.get("max_per_day", 1)),
                minimum_interval_hours=int(proactive.get("minimum_interval_hours", 8)),
                quiet_start_hour=int(proactive.get("quiet_start_hour", 22)),
                quiet_end_hour=int(proactive.get("quiet_end_hour", 8)),
                importance_threshold=float(proactive.get("importance_threshold", 0.68)),
            ),
            aggregation_config=AggregationConfig(
                weak_rate=float(learning.get("weak_rate", 0.025)),
                explicit_rate=float(learning.get("explicit_rate", 0.11)),
                correction_rate=float(learning.get("correction_rate", 0.36)),
            ),
            learning_enabled=bool(learning.get("enabled", True)),
            memory_utc_offset_minutes=config.get("memory_utc_offset_minutes"),
            memory_zone_name=config.get("memory_zone_name"),
            turn_idle_seconds=int(config.get('turn_idle_seconds', 20)),
            attachment_root=config.get('attachment_root'),
            supports_vision=bool(provider_config.get('supports_vision', False)),
        )
        _core.context_builder.clock = lambda: _clock
        return _json({"ready": True, "database": database_path})


def send_message(text: str, conversation_id: str = "default", message_id: str = '') -> str:
    return _json(_require_core().chat_result(text, conversation_id, message_id=message_id or None))


def queue_user_turn(text: str, message_id: str = '', image_path: str = '') -> str:
    return _json(_require_core().queue_user_turn(text, message_id or None, image_path))


def preview_interview(answers_json: str, language: str = 'zh-CN', name: str = '') -> str:
    submitted = json.loads(answers_json or '{}')
    if not isinstance(submitted, dict):
        raise ValueError('onboarding answers must be a JSON object')
    answers = {**_require_core().onboarding.status()['answers'], **submitted}
    return _json({'persona': pending_persona(answers, language, name),
                  'nickname_candidates': [],
                  'generation_prompt': character_generation_prompt(answers, language),
                  'method': 'local draft; no model call'})

def generate_interview(answers_json: str, language: str = 'zh-CN', name: str = '') -> str:
    submitted = json.loads(answers_json or '{}')
    if not isinstance(submitted, dict):
        raise ValueError('onboarding answers must be a JSON object')
    core = _require_core()
    answers = {**core.onboarding.status()['answers'], **submitted}
    return _json(core.generate_character(answers, language, name))

def plan_check_in(conversation_id: str = 'default') -> str:
    core = _require_core()
    if isinstance(core.provider, LocalCompanionProvider):
        return 'null'
    item = core.proactive.plan_check_in(conversation_id)
    return _json(asdict(item) if item else None)


def retry_message(message_id: str) -> str:
    return _json(_require_core().retry_message(message_id))


def list_messages(conversation_id: str = "default", limit: int = 200) -> str:
    messages = _require_core().store.list_messages(conversation_id, limit)
    plans = _require_core().store.delivery_plans_for([item.id for item in messages])
    sources = _require_core().store.reply_sources_for([item.id for item in messages])
    return _json([{**asdict(item), 'delivery_plan': plans.get(item.id),
                  'image_path': _require_core().attachments.path(item.id),
                  **({'reply_source_ids': sources[item.id]} if item.id in sources else {})} for item in messages])


def get_message(message_id: str) -> str:
    """One delivery update, independent of the chat window's history limit."""
    message = _require_core().store.get_message(message_id)
    sources = _require_core().store.reply_sources_for([message_id]).get(message_id, []) if message else []
    return _json({**asdict(message), 'delivery_plan': _require_core().store.delivery_plans_for([message.id]).get(message.id),
                  'image_path': _require_core().attachments.path(message.id),
                  **({'reply_source_ids': sources} if sources else {})} if message else None)


def get_character_book() -> str:
    """Separate diagnostic/export view; never injected wholesale into Talk."""
    core = _require_core()
    return _json({'character_id': core.character_book.character_id, 'chapters': core.character_book.tree()})


def schedule_custom(text: str, when: str, generate: bool = False, conversation_id: str = 'default') -> str:
    return _json(_require_core().schedule_custom(text, when, generate, conversation_id))


def scheduled_queue(limit: int = 50) -> str:
    with _require_core().store.connection() as conn:
        rows = conn.execute("""SELECT s.*,n.status AS notification_status FROM scheduled_messages s
            LEFT JOIN notification_outbox n ON n.message_id=s.sent_message_id WHERE s.topic NOT LIKE 'reply:%'
            ORDER BY CASE WHEN s.status='pending' THEN 0 ELSE 1 END,
            CASE WHEN s.status='pending' THEN s.scheduled_at END ASC,
            CASE WHEN s.status!='pending' THEN s.created_at END DESC LIMIT ?""", (max(1, min(100, int(limit))),)).fetchall()
    return _json([{**asdict(_require_core().store._scheduled_from_row(row)),
                   'notification_status': row['notification_status']} for row in rows])


def apply_interview_distillation(proposal_json: str) -> str:
    proposal = json.loads(proposal_json)
    if not isinstance(proposal, dict):
        raise ValueError('Invalid interview proposal')
    return _json(_require_core().onboarding.apply_distillation(proposal))


def delete_message(message_id: str) -> str:
    return _json(_require_core().delete_message(message_id))


def submit_feedback(message_id: str, kind: str, value_json: str = "null") -> str:
    value = json.loads(value_json or "null")
    return _json(_require_core().submit_feedback(message_id, kind, value))


def feedback_due() -> bool:
    return _require_core().feedback.should_request_periodic()


def dismiss_feedback() -> None:
    _require_core().feedback.dismiss_periodic()


def complete_periodic_feedback() -> None:
    _require_core().feedback.complete_periodic()


def get_aul() -> str:
    return _json(_require_core().aul())


def onboarding_status() -> str:
    return _json(_require_core().onboarding.status())


def begin_onboarding() -> str:
    return _json(_require_core().onboarding.begin())


def submit_onboarding(answers_json: str, finish: bool = False, progress_json: str = '{}') -> str:
    answers = json.loads(answers_json or "{}")
    if not isinstance(answers, dict):
        raise ValueError("onboarding answers must be a JSON object")
    return _json(_require_core().onboarding.submit(answers, finish, json.loads(progress_json or '{}')))


def skip_onboarding() -> str:
    return _json(_require_core().onboarding.skip())


def set_preference(key: str, value: float) -> str:
    return _json(_require_core().set_preference_baseline(
        key, value, "Developer/Admin manual override",
    ))


def get_debug(kind: str) -> str:
    core = _require_core()
    values: Any
    if kind == "evidence":
        values = [asdict(item) for item in core.store.list_evidence()]
    elif kind == "audit":
        values = core.store.list_audit()
    elif kind in {"rolling", "daily", "weekly", "monthly", "long_term"}:
        values = core.store.list_memories(kind)
    elif kind == "raw":
        values = [asdict(item) for item in core.store.list_messages(limit=500)]
    elif kind == "policy":
        values = core.current_policy()
    elif kind == "metrics":
        values = core.store.list_generation_metrics()
    else:
        values = core.store.list_memories()
    return _json(values)


def list_scheduled(status: str = "") -> str:
    return _json([asdict(item) for item in _require_core().store.list_scheduled_messages(status or None)])


def maintain_memory() -> str:
    return _json(_require_core().memory.maintain())


def list_archives(kind: str = "daily", limit: int = 50) -> str:
    return _json(_require_core().memory.archives.list(kind, limit))


def archive_detail(memory_id: str, offset: int = 0, limit: int = 50) -> str:
    return _json(_require_core().memory.archives.detail(memory_id, offset, limit))


def search_memory(query: str, limit: int = 20) -> str:
    return _json(_require_core().retriever.retrieve(query, limit))


def execute_scheduled(item_id: str, force: bool = False, allow_casual: bool = True) -> str:
    return _json(_require_core().execute_scheduled(item_id, force, allow_casual))


def pending_notifications(limit: int = 20) -> str:
    return _json(_require_core().store.pending_notifications(limit))


def finish_notification(message_id: str, status: str) -> bool:
    return _require_core().store.finish_notification(message_id, status)


def cancel_scheduled(item_id: str) -> str:
    store = _require_core().store
    with store.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        item = store.get_scheduled_message(item_id)
        if item and item.status == 'pending':
            conn.execute("UPDATE scheduled_messages SET status='cancelled',updated_at=? WHERE id=? AND status='pending'",
                         (utc_now(), item_id))
            if item.topic.startswith('reply:'):
                for key in item.source_memory_ids:
                    conn.execute("UPDATE messages SET status='failed',error=? WHERE id=? AND status='waiting'",
                                 ('Delayed reply stopped; tap Retry for an immediate reply', key))
        conn.commit()
    _require_core()._discard_cached_turn(item_id, 'user cancelled')
    current = store.get_scheduled_message(item_id)
    return _json({'id': item_id, 'status': current.status if current else 'missing'})


def delete_scheduled(item_id: str) -> str:
    # Deleting queued work must also settle every batched source and account for
    # a paid reply held during typing, not leave it orphaned in metadata.
    cancel_scheduled(item_id)
    _require_core().store.delete_scheduled_message(item_id)
    return _json({"id": item_id, "deleted": True})


def clear_user_data() -> str:
    core = _require_core()
    # Privacy reset still drains all workers when an observer previously failed.
    # Otherwise one learning error could block deletion or allow late writes.
    core.learning.wait(raise_errors=False)
    with core.store.connection() as conn:
        ids = [row['id'] for row in conn.execute('SELECT id FROM messages').fetchall()]
    core.attachments.remove(ids)
    core.store.clear_user_data()
    # Keep the chosen AI role while deleting the learned user layer.
    style = core.context_builder.persona.get('initial_style', {})
    if style:
        core.learning.aggregator.interaction_defaults.update(style)
        core.store.set_metadata('persona_style_seeds', json.dumps(style))
        core.learning.aggregator.aggregate(force_keys={f'interaction.{key}' for key in style})
    return _json({"cleared": True})


def test_connection(config_json: str) -> str:
    config = json.loads(config_json)
    base_url = str(config.get("base_url", "")).rstrip("/")
    api_key = str(config.get("api_key", ""))
    if not base_url or not api_key:
        return _json({"ok": False, "message": "Base URL and API key are required"})
    request = urllib.request.Request(
        base_url + "/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=int(config.get("timeout", 30))) as response:
            return _json({"ok": 200 <= response.status < 300, "status": response.status})
    except Exception as exc:
        return _json({"ok": False, "message": str(exc)[:300]})


def close() -> None:
    global _core
    with _lock:
        if _core is not None:
            _core.close()
            _core = None


def _require_core() -> CompanionCore:
    if _core is None:
        raise RuntimeError("Android Core bridge is not initialized")
    return _core


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
