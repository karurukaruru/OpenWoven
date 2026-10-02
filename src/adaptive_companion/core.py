from __future__ import annotations

import json
import hashlib
import math
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .context import ContextBuilder, estimate_tokens
from .aggregator import AggregationConfig, EvidenceAggregator
from .delivery import DeliveryPlanner, DeliverySettings
from .delayed_replies import DelayedReplies
from .feedback import FeedbackService
from .learning import LearningLoop
from .llm import LLMProvider, LocalCompanionProvider, compile_dialogue_prompt
from .memory import MemoryManager
from .models import DEFAULT_PERSONA, DEFAULT_INTERACTION, INTERACTION_KEYS, Evidence
from .onboarding import OnboardingService
from .observer import Observer
from .policy import InteractionPolicyBuilder
from .proactive import ProactiveMessagePlanner, ProactiveSettings
from .retrieval import MemoryRetriever
from .storage import SQLiteStore
from .localization import local_text
from .attachments import Attachments
from .turns import composer_gate
from .character_book import CharacterBook, CharacterBookFull, CharacterMetadataError, parse_character_response, normalized as normalized_character_fact


class CompanionCore:
    """Facade for the two-loop adaptive companion runtime."""

    def __init__(
        self, database: str | Path = "companion.db", provider: LLMProvider | None = None,
        persona: dict[str, Any] | None = None, context_budget: int = 5400,
        summary_message_threshold: int = 12, summary_token_threshold: int = 5400,
        observer: Observer | None = None,
        delivery_settings: DeliverySettings | None = None,
        proactive_settings: ProactiveSettings | None = None,
        aggregation_config: AggregationConfig | None = None,
        learning_enabled: bool = True,
        memory_utc_offset_minutes: int | None = None,
        memory_zone_name: str | None = None,
        turn_idle_seconds: int = 20, attachment_root: str | None = None,
        supports_vision: bool = False,
    ):
        self.store = SQLiteStore(database, memory_utc_offset_minutes, memory_zone_name)
        self.store.recover_interrupted_messages()
        self.provider = provider or LocalCompanionProvider()
        self.policy_builder = InteractionPolicyBuilder((persona or {}).get('initial_style'))
        self.retriever = MemoryRetriever(self.store)
        self.context_builder = ContextBuilder(persona or DEFAULT_PERSONA)
        self.character_book = CharacterBook(self.store, self.context_builder.persona)
        # A first weak signal must refine the chosen starting style, not jump
        # back to a generic .5. Learned preference seeds survive role switches.
        saved_seeds = self.store.get_metadata('persona_style_seeds')
        try:
            seeds = {**DEFAULT_INTERACTION, **(json.loads(saved_seeds) if saved_seeds else {})}
        except (ValueError, TypeError):
            seeds = dict(DEFAULT_INTERACTION)
        initial_style = (persona or {}).get('initial_style', {})
        previous = self.store.get_aul()['interaction']
        for key, value in initial_style.items():
            if key in DEFAULT_INTERACTION and not previous[key].get('evidence_count'):
                seeds[key] = value
        if initial_style:
            self.store.set_metadata('persona_style_seeds', json.dumps(seeds))
        self.memory = MemoryManager(
            self.store, message_threshold=summary_message_threshold,
            token_threshold=summary_token_threshold,
            weekly_generate=self._generate_weekly_summary if type(self.provider).generate_memory_summary is not LLMProvider.generate_memory_summary else None,
        )
        self.learning = LearningLoop(
            self.store, observer=observer,
            aggregator=EvidenceAggregator(self.store, aggregation_config, seeds),
            on_completed=lambda message: self._maintain_conversation(message.conversation_id),
        )
        self.feedback = FeedbackService(self.store, self.learning.aggregator)
        self.onboarding = OnboardingService(self.store, self.learning.aggregator)
        changed = {f'interaction.{key}' for key in initial_style
                   if key in previous and not previous[key].get('evidence_count') and previous[key]['value'] != seeds[key]}
        if changed:
            self.learning.aggregator.aggregate(force_keys=changed)
        self.delivery = DeliveryPlanner(delivery_settings)
        self.delayed_replies = DelayedReplies(self.store, turn_idle_seconds)
        self.attachments = Attachments(self.store, attachment_root)
        self.supports_vision = supports_vision
        self.proactive = ProactiveMessagePlanner(self.store, proactive_settings)
        self.context_budget = context_budget
        self.learning_enabled = learning_enabled
        if self.learning_enabled:
            self.learning.recover_pending()
        self.learning.submit_background(self.memory.maintain)

    def chat(self, user_message: str, conversation_id: str = "default") -> str:
        return self.chat_result(user_message, conversation_id)["response"]

    def queue_user_turn(self, text: str, message_id: str | None = None, image_path: str = '',
                        conversation_id: str = 'default') -> dict:
        if image_path:
            if not self.supports_vision or isinstance(self.provider, LocalCompanionProvider):
                raise ValueError('Selected model does not support images')
            self.attachments.checked(image_path)
            pending_ids = [key for item in self.store.list_scheduled_messages('pending', limit=None)
                           if item.conversation_id == conversation_id and item.topic.startswith('reply:')
                           for key in item.source_memory_ids]
            if sum(bool(self.attachments.path(key)) for key in set(pending_ids)) >= 4:
                raise ValueError('At most four images per turn')
        if not text.strip() and not image_path:
            raise ValueError('Empty message')
        recent = self.store.list_messages(conversation_id, limit=8)
        last_reply = next((m for m in reversed(recent) if m.role == 'assistant'), None)
        active = last_reply and datetime.now().astimezone() - datetime.fromisoformat(last_reply.timestamp) < timedelta(minutes=5)
        greeting_seconds = 0 if active else self.delivery.greeting_wait_seconds(text, message_id or text)
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            message = self.store.save_message(conversation_id, 'user', text.strip() or '[Image]',
                status='waiting', message_id=message_id,
                learning_status='pending' if self.learning_enabled else 'disabled', connection=conn)
            if image_path:
                conn.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',
                             ('attachment:' + message.id, str(self.attachments.checked(image_path))))
            item = self.delayed_replies.enqueue_turn(message, greeting_seconds, connection=conn)
            conn.commit()
        event = self.proactive.observe_user_message(message)
        if self.learning_enabled:
            self.learning.submit(message.id)
        self._cleanup_cached_turns('superseded user turn')
        return {'scheduled_message': item.id, 'user_message_id': message.id,
                'event_schedule': event.id if event else None}

    def chat_result(self, user_message: str, conversation_id: str = "default",
                    message_id: str | None = None) -> dict[str, Any]:
        self.delayed_replies.cancel_for_conversation(conversation_id)
        # Durably save and freeze a committed snapshot for this turn.
        message = self.store.save_message(
            conversation_id, "user", user_message, status="pending",
            learning_status="pending" if self.learning_enabled else "disabled",
            message_id=message_id,
        )
        scheduled = self.proactive.observe_user_message(message)
        # Synchronously expire stale current-state beliefs and apply any evidence
        # left committed by a previously interrupted learning worker.
        aul = self.learning.aggregator.aggregate()
        policy = self.policy_builder.build(user_message, aul)
        self.store.set_metadata("last_policy", json.dumps(policy, ensure_ascii=False))
        retrieval_query = self._retrieval_query(user_message, aul)
        retrieval_limit = 5 if policy["context"] in {"asking_for_advice", "serious_discussion"} else 3
        memories = self.retriever.retrieve(retrieval_query, limit=retrieval_limit, exclude_message_ids={message.id})
        recent = self.store.list_messages(conversation_id, limit=64)
        context = self.context_builder.build(
            aul, policy, user_message, recent, memories, self.context_budget,
            current_message_id=message.id,
            **self._character_context(user_message, recent),
        )
        if self.attachments.path(message.id):
            if not self.supports_vision:
                raise ValueError('Selected model does not support images')
            context['current_images'] = self.attachments.for_turn([message.id])

        # Learning overlaps the expensive model call, but cannot change this turn's
        # frozen context. Its committed result is visible on the next turn.
        if self.learning_enabled:
            self.learning.submit(message.id)

        wait = self.delivery.greeting_wait_seconds(user_message, message.id)
        last_reply = next((m for m in reversed(recent) if m.role == "assistant"), None)
        active_chat = last_reply and datetime.now().astimezone() - datetime.fromisoformat(last_reply.timestamp) < timedelta(minutes=5)
        if wait and not active_chat:
            queued = self.delayed_replies.enqueue(message, wait)
            return {
                "response": "", "user_message_id": message.id, "assistant_message_id": "",
                "delivery_plan": {"mode": "queued", "parts": []}, "deferred": True,
                "scheduled_message": queued.id, "aul_version_used": aul["version"],
            }

        # Dialogue provider is independent of observer/memory providers.
        try:
            response, metric = self._generate(context, "chat", message.id)
        except Exception as exc:
            self.store.update_message_status(message.id, "failed", str(exc)[:500])
            raise
        if scheduled and scheduled.topic.startswith("reminder:"):
            when = datetime.fromisoformat(scheduled.scheduled_at).strftime("%Y-%m-%d %H:%M")
            quiet_note = self._local_text("quiet_note") if "moved outside quiet hours" in scheduled.reason else ""
            response += "\n\n" + self._local_text("scheduled", when=when, note=quiet_note)
        elif self.proactive.settings.enabled and self.proactive.events.clarification:
            question = self.proactive.events.clarification
            if match := re.fullmatch(r"(.+)是哪天、几点结束？", question):
                question = self._local_text("exam_day", title=match[1])
            elif match := re.fullmatch(r"那(.+)大概几点结束？", question):
                question = self._local_text("exam_time", title=match[1])
            # This local confirmation is necessary even when a model overlooks it.
            if question not in response:
                response += "\n\n" + question
        plan = self.delivery.plan(response, message.id, policy, metric["latency_ms"]).to_dict()
        try:
            assistant = self.store.complete_reply(message.id, response, plan,
                character_update=metric.get('character_update'))
        except Exception as exc:
            self.store.update_message_status(message.id, 'failed', str(exc)[:500])
            metric.update(status='failed', error=str(exc))
            self._record_generation(metric, None)
            raise
        self._record_generation(metric, assistant.id)
        self._queue_memory_maintenance(conversation_id)
        return {
            "response": response,
            "user_message_id": message.id,
            "assistant_message_id": assistant.id,
            "delivery_plan": plan,
            "scheduled_message": scheduled.id if scheduled else None,
            "aul_version_used": aul["version"],
        }

    def retry_message(self, message_id: str) -> dict[str, Any]:
        message = self.store.get_message(message_id)
        if not message or message.role != "user":
            raise ValueError("retry target must be a saved user message")
        sources = [message.id]
        for item in sorted(self.store.list_scheduled_messages(limit=None), key=lambda value: value.created_at, reverse=True):
            if item.reason.startswith('batched user turn') and message_id in item.source_memory_ids:
                sources = [key for key in item.source_memory_ids if self.store.get_message(key)]
                break
        if sources:
            message = self.store.get_message(sources[-1])
        self.delayed_replies.cancel_for_source(message_id)
        self._cleanup_cached_turns('manual retry')
        user_text = '\n'.join(self.store.get_message(key).content for key in sources)
        self.store.update_message_status(message.id, "pending")
        aul = self.learning.aggregator.aggregate()
        policy = self.policy_builder.build(user_text, aul)
        memories = self.retriever.retrieve(self._retrieval_query(user_text, aul), limit=3, exclude_message_ids=set(sources))
        recent = [m for m in self.store.list_messages_before(sources[0], limit=64) if m.id not in sources]
        context = self.context_builder.build(
            aul, policy, user_text, recent, memories, self.context_budget,
            current_message_id=message.id,
            **self._character_context(user_text, recent),
        )
        try:
            if any(self.attachments.path(key) for key in sources):
                if not self.supports_vision:
                    raise ValueError('Selected model does not support images')
                context['current_images'] = self.attachments.for_turn(sources)
            response, metric = self._generate(context, "retry", message.id)
        except Exception as exc:
            self.store.update_turn_status(sources, 'failed', str(exc)[:500])
            raise
        plan = self.delivery.plan(response, message.id, policy, metric["latency_ms"]).to_dict()
        try:
            assistant = self.store.complete_reply(message.id, response, plan, source_message_ids=sources,
                character_update=metric.get('character_update'))
        except Exception as exc:
            self.store.update_turn_status(sources, 'failed', str(exc)[:500])
            metric.update(status='failed', error=str(exc))
            self._record_generation(metric, None)
            raise
        self._record_generation(metric, assistant.id)
        self._queue_memory_maintenance(message.conversation_id)
        return {
            "response": response, "user_message_id": message.id,
            "assistant_message_id": assistant.id,
            "delivery_plan": plan,
            "scheduled_message": None, "aul_version_used": aul["version"],
        }

    def submit_feedback(self, message_id: str, kind: str, value: Any = None) -> dict[str, Any]:
        return self.feedback.submit(message_id, kind, value)

    def delete_message(self, message_id: str) -> dict[str, Any]:
        target = self.store.get_message(message_id)
        if not target:
            return {"deleted": False, "message_ids": [], "scheduled_ids": []}
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM messages WHERE id=? OR reply_to_id=?",
                (message_id, message_id),
            ).fetchall()
        message_ids = [row["id"] for row in rows]
        initial_ids = set(message_ids)
        related_scheduled = [
            item for item in self.store.list_scheduled_messages(limit=None)
            if any(source in initial_ids for source in item.source_memory_ids)
            or item.sent_message_id in initial_ids
        ]
        scheduled_ids = [item.id for item in related_scheduled]
        message_ids.extend(
            item.sent_message_id for item in related_scheduled
            if item.sent_message_id and item.sent_message_id not in message_ids
        )
        placeholders = ",".join("?" for _ in message_ids)
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            affected = {
                row["key"] for row in conn.execute(
                    f"SELECT DISTINCT key FROM evidence WHERE source_message_id IN ({placeholders})",
                    message_ids,
                ).fetchall()
            }
            # Remove derived copies as well as raw messages. Legacy summaries
            # have no complete provenance, so invalidate them conservatively.
            conn.execute(
                f"""DELETE FROM memories WHERE id IN (
                SELECT memory_id FROM memory_sources WHERE source_message_id IN ({placeholders})
                ) OR NOT EXISTS (SELECT 1 FROM memory_sources WHERE memory_id=memories.id)""",
                message_ids,
            )
            conn.execute(
                "DELETE FROM metadata WHERE key=?", (f"rolling_last:{target.conversation_id}",),
            )
            conn.execute(f"DELETE FROM audit_log WHERE source_message_id IN ({placeholders})", message_ids)
            conn.execute(f"DELETE FROM feedback WHERE message_id IN ({placeholders})", message_ids)
            conn.execute(f"DELETE FROM evidence WHERE source_message_id IN ({placeholders})", message_ids)
            conn.execute(
                f"""DELETE FROM generation_metrics
                WHERE source_id IN ({placeholders}) OR result_message_id IN ({placeholders})""",
                message_ids + message_ids,
            )
            if scheduled_ids:
                schedule_placeholders = ",".join("?" for _ in scheduled_ids)
                conn.execute(
                    f"DELETE FROM generation_metrics WHERE source_id IN ({schedule_placeholders})",
                    scheduled_ids,
                )
                conn.execute(
                    f"DELETE FROM scheduled_messages WHERE id IN ({schedule_placeholders})",
                    scheduled_ids,
                )
                for item in related_scheduled:
                    conn.execute('DELETE FROM metadata WHERE key=?', ('turn_reply:' + item.id,))
                    if item.topic.startswith('reply:'):
                        for key in item.source_memory_ids:
                            if key not in message_ids:
                                conn.execute("UPDATE messages SET status='failed',error=? WHERE id=? AND status='waiting'",
                                             ('Part of the turn was deleted; retry remaining text', key))
            conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", message_ids)
            # Keep the store lock while rebuilding. Audit old/new values can
            # themselves contain forgotten facts, including on later sources.
            self.learning.aggregator.aggregate(force_keys=affected, connection=conn)
            for field in affected:
                conn.execute("DELETE FROM audit_log WHERE field=?", (field,))
            conn.commit()
        self.attachments.remove(message_ids)
        return {
            "deleted": True,
            "message_ids": message_ids,
            "scheduled_ids": scheduled_ids,
        }

    def set_preference_baseline(
        self, key: str, value: float, reason: str = "Administrator manual override",
    ) -> dict[str, Any]:
        if key not in INTERACTION_KEYS:
            raise ValueError(f"unknown interaction preference: {key}")
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError('interaction preference must be a finite number')
        target = max(0.0, min(1.0, float(value)))
        source = self.store.save_message(
            "__admin__", "system", f"{reason}: interaction.{key}",
        )
        self.store.save_evidence([Evidence(
            id=f"ev_{uuid.uuid4().hex}", type="interaction_preference",
            key=f"interaction.{key}", value=target, strength=1.0,
            confidence=1.0, importance=1.0, source_message_id=source.id,
            signal="baseline",
        )])
        return self.learning.aggregator.aggregate(force_keys={f"interaction.{key}"})

    def execute_scheduled(self, item_id: str, force: bool = False, allow_casual: bool = True) -> dict[str, Any]:
        item = self.store.get_scheduled_message(item_id)
        if not item:
            return {"sent": False, "reason": "not found"}
        delayed = item.topic.startswith("reply:")
        generated_proactive = not delayed and not item.topic.startswith(('custom:text:', 'reminder:'))
        batched = delayed and item.reason.startswith('batched user turn')
        revision = composer_gate.revision(item.conversation_id)
        fingerprint = hashlib.sha256(json.dumps([self.context_builder.persona,
            type(self.provider).__name__, getattr(self.provider, 'model', None), getattr(self.provider, 'base_url', None)],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        cached = json.loads(self.store.get_metadata('turn_reply:' + item.id) or 'null') if batched else None
        if cached and (cached.get('fingerprint') != fingerprint or time.time() - cached.get('generated_at', 0) > 300):
            self._discard_cached_turn(item.id, 'provider/character changed or held reply expired')
            cached = None
        source_id = item.topic[6:] if delayed else None
        revalidate = self.delayed_replies.revalidate if delayed else self.proactive.revalidate
        valid, reason = revalidate(item_id)
        if not valid:
            current = self.store.get_scheduled_message(item_id)
            if batched and current and current.status != 'pending':
                self._discard_cached_turn(item_id, reason)
            return {"sent": False, "reason": reason, "status": current.status if current else "missing", "user_message_id": source_id}
        if not force and datetime.fromisoformat(item.earliest_at) > datetime.now().astimezone():
            return {"sent": False, "reason": "not due", "status": "pending"}
        if item.topic.startswith(('checkin:', 'custom:topic:')) and not allow_casual:
            return {'sent': False, 'reason': 'notifications unavailable', 'status': 'pending'}
        aul = self.learning.aggregator.aggregate()
        instruction = item.draft_intent if delayed else f"Write a brief proactive opening, not a complete answer. Intent: {item.draft_intent}."
        policy = self.policy_builder.build(instruction, aul)
        if generated_proactive:
            # The saved topic is not a fresh request for advice/a document.
            policy.update(proactive=True, reply_length=min(policy['reply_length'], .30),
                          question_frequency=min(policy['question_frequency'], .40),
                          advice_frequency=min(policy['advice_frequency'], .10))
            policy.pop('message_format', None)
        self.store.set_metadata('last_policy', json.dumps(policy, ensure_ascii=False))
        memories = self.retriever.retrieve(item.draft_intent, limit=3, exclude_message_ids=set(item.source_memory_ids) if delayed else None)
        recent = self.store.list_messages(item.conversation_id, limit=64 if batched else 8)
        if batched:
            recent = [message for message in recent if message.id not in item.source_memory_ids]
        intent = None if delayed else item.draft_intent
        if not delayed and isinstance(self.provider, LocalCompanionProvider) and item.topic.startswith('exam:'):
            intent = 'ask how the exam went'
        context = self.context_builder.build(
            aul, policy, instruction if delayed else 'Write the saved scheduled message now.', recent, memories, self.context_budget,
            current_message_id=source_id,
            proactive_intent=intent,
            **self._character_context(instruction, recent),
        )
        try:
            if delayed and any(self.attachments.path(key) for key in item.source_memory_ids):
                if not self.supports_vision:
                    raise ValueError('Selected model does not support images')
                context['current_images'] = self.attachments.for_turn(item.source_memory_ids)
        except Exception as exc:
            self.store.update_turn_status(item.source_memory_ids or [source_id], 'failed', str(exc)[:500])
            raise
        if cached:
            response, metric = cached['response'], cached['metric']
        elif item.topic.startswith('custom:text:'):
            response, metric = item.draft_intent, None
        elif item.topic.startswith("reminder:"):
            response, metric = self._local_text("remind", text=item.draft_intent), None
        else:
            try:
                response, metric = self._generate(context, "delayed_reply" if delayed else "proactive", item.id)
            except Exception as exc:
                if source_id:
                    self.store.update_turn_status(item.source_memory_ids or [source_id], 'failed', str(exc)[:500])
                raise
        if batched and not cached:
            # Preserve the deterministic receipt for a reminder requested in any
            # of the sent bubbles, even if a provider omits the acknowledgment.
            reminder = next((entry for entry in self.store.list_scheduled_messages('pending', limit=None)
                if entry.topic.startswith('reminder:') and set(entry.source_memory_ids) & set(item.source_memory_ids)), None)
            if reminder:
                when = datetime.fromisoformat(reminder.scheduled_at).strftime('%Y-%m-%d %H:%M')
                quiet_note = self._local_text('quiet_note') if 'moved outside quiet hours' in reminder.reason else ''
                response += '\n\n' + self._local_text('scheduled', when=when, note=quiet_note)
        # Model generation can take a minute. Re-check cancellations, quiet hours
        # and rate limits immediately before the atomic delivery commit.
        # Wait for database maintenance BEFORE taking the input gate. Otherwise
        # Android's tiny main-thread typing update could wait behind an archive.
        with self.store.connection(), composer_gate.lock:
            valid, reason = revalidate(item_id)
            if batched and revision != composer_gate.revision(item.conversation_id):
                valid, reason = False, 'composer changed'
            if not valid:
                if metric:
                    current = self.store.get_scheduled_message(item_id)
                    if batched and current and current.status == 'pending' and reason in {'composer active', 'composer changed'}:
                        # Hold a generated reply during unsent typing, reusing it
                        # after idle. A newly SENT bubble cancels this task/cache.
                        self.store.set_metadata('turn_reply:' + item.id, json.dumps(
                            {'response': response, 'metric': metric, 'fingerprint': fingerprint,
                             'generated_at': cached.get('generated_at', time.time()) if cached else time.time()}, ensure_ascii=False))
                    else:
                        metric.update(status="discarded", error=reason)
                        self._record_generation(metric, None)
                        self._remove_cached_turn(item.id)
                return {"sent": False, "reason": reason}
            delivery_policy = {'context': 'serious_discussion'} if item.topic.startswith('custom:text:') else policy
            plan = self.delivery.plan(response, item.id, delivery_policy, metric["latency_ms"] if metric else 0).to_dict()
            if generated_proactive:
                if not plan['parts']:
                    plan = self.delivery.plan(self._local_text('proactive_opening'), item.id, delivery_policy).to_dict()
                visible_response = '\n'.join(part['text'] for part in plan['parts'])
                if metric and metric.get('character_update'):
                    # Omitted text cannot become a remembered role experience.
                    visible_facts = normalized_character_fact(visible_response)
                    update = metric['character_update']
                    update['facts'] = [fact for fact in update['facts']
                                       if normalized_character_fact(fact['value']) in visible_facts]
                response = visible_response
            try:
                assistant = self.store.complete_scheduled_delivery(item.id, response, reply_to_id=source_id,
                    delivery_plan=plan, character_update=metric.get('character_update') if metric else None)
            except Exception as exc:
                if source_id:
                    self.store.update_turn_status(item.source_memory_ids or [source_id], 'failed', str(exc)[:500])
                if metric:
                    metric.update(status='failed', error=str(exc))
                    self._record_generation(metric, None)
                self._remove_cached_turn(item.id)
                raise
            if metric:
                self._record_generation(metric, assistant.id)
            self._remove_cached_turn(item.id)
        self._queue_memory_maintenance(item.conversation_id)
        return {
            "sent": True, "reason": "delivered", "status": "sent",
            "message_id": assistant.id, "conversation_id": item.conversation_id,
            "text": response,
            "delivery_plan": plan,
            "user_message_id": source_id,
            "user_message_ids": item.source_memory_ids if delayed else [],
        }

    def _maintain_conversation(self, conversation_id: str) -> None:
        # Learning may finish before OR after delivery. Either completion retries
        # the rolling summary; a pending observer never loses the summary trigger.
        self.memory.maybe_create_rolling_summary(conversation_id)
        self.memory.maintain(limit=32)

    def _queue_memory_maintenance(self, conversation_id: str) -> None:
        self.learning.submit_background(lambda: self._maintain_conversation(conversation_id))

    def _remove_cached_turn(self, item_id: str) -> None:
        with self.store.connection() as conn:
            conn.execute('DELETE FROM metadata WHERE key=?', ('turn_reply:' + item_id,))
            conn.commit()

    def _discard_cached_turn(self, item_id: str, reason: str) -> None:
        raw = self.store.get_metadata('turn_reply:' + item_id)
        if raw:
            metric = json.loads(raw)['metric']
            metric.update(status='discarded', error=reason)
            self._record_generation(metric, None)
            self._remove_cached_turn(item_id)

    def _cleanup_cached_turns(self, reason: str) -> None:
        with self.store.connection() as conn:
            keys = [row['key'] for row in conn.execute("SELECT key FROM metadata WHERE key LIKE 'turn_reply:%'").fetchall()]
        for key in keys:
            item_id = key.removeprefix('turn_reply:')
            item = self.store.get_scheduled_message(item_id)
            if not item or item.status != 'pending':
                self._discard_cached_turn(item_id, reason)

    def schedule_custom(self, text: str, when: str, generate: bool = False, conversation_id: str = 'default') -> dict:
        if generate and isinstance(self.provider, LocalCompanionProvider):
            raise ValueError('Configure a model provider first')
        return self.proactive.schedule_custom(text, when, generate, conversation_id)

    def learn_now(self, user_message: str, conversation_id: str = "default") -> dict[str, Any]:
        message = self.store.save_message(
            conversation_id, "user", user_message, learning_status="pending",
        )
        return self.learning.process(message.id)

    def _local_text(self, key: str, **args: str) -> str:
        return local_text(self.context_builder.persona.get("language", "Simplified Chinese"), key, **args)

    def wait_for_learning(self) -> None:
        self.learning.wait()

    def aul(self) -> dict[str, Any]:
        return self.store.get_aul()

    def current_policy(self, text: str = "") -> dict[str, Any]:
        stored = self.store.get_metadata("last_policy")
        if stored and not text:
            return json.loads(stored)
        return self.policy_builder.build(text, self.aul())

    @staticmethod
    def _retrieval_query(user_message: str, aul: dict[str, Any]) -> str:
        query = user_message
        # Resolve short/anaphoric follow-ups using only the active goal; avoid polluting
        # clear standalone queries with unrelated profile history.
        if any(word in user_message for word in ("那个", "之前", "后来", "它", "还记得")) or user_message.strip() in {
            "继续", "接着说", "然后呢", "怎么办", "下一步呢", "continue", "what next",
        }:
            goal = aul.get("current", {}).get("current_goal")
            if isinstance(goal, dict) and goal.get("value"):
                query += " " + str(goal["value"])
        return query

    def _character_context(self, query: str, recent: list) -> dict:
        # Carry the last user's topic only for elliptical follow-ups, rather
        # than re-injecting unrelated chapters on every subsequent turn.
        if query.strip().casefold() in {'然后呢', '后来呢', '那后来呢', '还记得吗', 'and then?', 'what happened next?', 'それから？'}:
            previous = next((x.content for x in reversed(recent) if x.role == 'user' and x.content != query), '')
            query += ' ' + previous
        return {'character_entries': self.character_book.retrieve(query),
                'character_book_enabled': not isinstance(self.provider, LocalCompanionProvider)}

    def _generate(
        self, context: dict[str, Any], kind: str, source_id: str,
    ) -> tuple[str, dict[str, Any]]:
        prompt_estimate = estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens(
            context["current_user_message"]
        )
        raw, metric = self._run_generation(lambda: self.provider.generate(context), prompt_estimate, kind, source_id)
        if not context.get('character_book_enabled'):
            return raw, metric
        try:
            try:
                response, facts = parse_character_response(raw, allow_plain=True)
            except CharacterMetadataError as exc:
                # Optional bookkeeping must not spoil a valid chat reply.
                # Keep an actionable diagnostic outside Talk, never save bad
                # facts or leak raw protocol fields into a bubble.
                response, facts = exc.reply, []
                metric['error'] = 'Character archive skipped: ' + str(exc)
            try:
                update = self.character_book.update(facts)
            except CharacterBookFull as exc:
                metric['error'] = 'Character archive skipped: ' + str(exc)
                update = {'character_id': self.character_book.character_id, 'facts': []}
        except Exception as exc:
            # A paid response with invalid JSON/conflicting canon is still a
            # completed model request. Preserve its usage; do not record zero
            # completion tokens merely because it cannot safely be displayed.
            metric.update(status='failed', error=str(exc))
            self._record_generation(metric, None)
            raise
        if update['facts']:
            metric['character_update'] = update
        return response, metric

    def generate_character(self, answers: dict[str, Any], language: str, name: str = '') -> dict[str, Any]:
        from .character_interview import bounded_character_prompt, validated_character_draft
        if isinstance(self.provider, LocalCompanionProvider):
            raise ValueError('Configure a model provider first')
        prompt, truncated = bounded_character_prompt(answers, language, self.context_budget - 20)
        response, metric = self._run_generation(lambda: self.provider.generate_character(prompt),
            estimate_tokens(prompt) + 20, 'character_setup', 'character_' + uuid.uuid4().hex)
        try:
            result = validated_character_draft(response, answers, language, name)
        except ValueError:
            metric.update(status='failed', error='invalid character blueprint')
            self._record_generation(metric, None)
            raise
        self._record_generation(metric, None)
        result.update(generation_prompt=prompt, answers_truncated=truncated)
        return result

    def _run_generation(self, generate, prompt_estimate: int, kind: str, source_id: str) -> tuple[str, dict[str, Any]]:
        started = time.perf_counter()
        provider_name = type(self.provider).__name__
        model = getattr(self.provider, "model", None)
        try:
            response = generate()
            if not isinstance(response, str) or not response.strip():
                raise ValueError("model returned an empty or non-text response")
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000)
            usage = getattr(self.provider, 'request_usage', {}) if kind == 'memory_summary' else {}
            self.store.record_generation_metric(
                kind=kind, source_id=source_id, result_message_id=None,
                provider=provider_name, model=model,
                prompt_tokens=usage.get('prompt_tokens', prompt_estimate), completion_tokens=usage.get('completion_tokens', 0),
                latency_ms=latency, status="failed", error=type(exc).__name__ if kind == 'memory_summary' else str(exc),
            )
            raise
        latency = round((time.perf_counter() - started) * 1000)
        usage = getattr(self.provider, "request_usage", getattr(self.provider, "last_usage", {})) or {}
        usage = usage if isinstance(usage, dict) else {}
        reported = {
            key: value for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and math.isfinite(value)
            and key in {"prompt_tokens", "completion_tokens"}
        }
        prompt = int(reported.get("prompt_tokens", prompt_estimate))
        completion = int(reported.get("completion_tokens", estimate_tokens(response)))
        return response, {
            "kind": kind, "source_id": source_id, "provider": provider_name,
            "model": model, "prompt_tokens": prompt, "completion_tokens": completion,
            "latency_ms": latency, "status": "success", "error": None,
            "usage_source": "provider" if len(reported) == 2 else "mixed" if reported else "estimated",
        }

    def _generate_weekly_summary(self, prompt: str, source_id: str) -> str:
        response, metric = self._run_generation(lambda: self.provider.generate_memory_summary(prompt),
            estimate_tokens(prompt) + 180, 'memory_summary', source_id)
        if len(response) > 6000:
            metric.update(status='failed', error='memory summary exceeded character limit')
            self._record_generation(metric, None)
            raise ValueError('memory summary exceeded character limit')
        self._record_generation(metric, None)
        return response.strip()

    def _record_generation(self, metric: dict[str, Any], result_message_id: str | None) -> None:
        # The sidecar may live in a held-turn cache, never in metrics or Talk.
        values = {key: value for key, value in metric.items() if key != 'character_update'}
        self.store.record_generation_metric(result_message_id=result_message_id, **values)

    def close(self) -> None:
        try:
            self.learning.close()
        finally:
            self.store.close()

    def __enter__(self) -> "CompanionCore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
