from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .aggregator import EvidenceAggregator
from .models import DEFAULT_INTERACTION, Evidence
from .storage import SQLiteStore


@dataclass(frozen=True, slots=True)
class OnboardingQuestion:
    id: str
    prompt: str
    kind: str
    section: str
    key: str
    default: float | None = None
    prefix: str = ""
    multiple: bool = False
    options: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("key")
        value.pop("prefix")
        value.pop("multiple")
        value['target'] = 'persona' if self.key.startswith(('persona.', 'interaction.')) else 'user'
        return value


def _text(
    number: int, prompt: str, section: str, key: str, *, prefix: str = "",
    multiple: bool = False,
) -> OnboardingQuestion:
    return OnboardingQuestion(f"q{number:02d}", prompt, "text", section, key, prefix=prefix, multiple=multiple)


def _slider(number: int, prompt: str, key: str) -> OnboardingQuestion:
    short = key.split(".", 1)[1]
    return OnboardingQuestion(
        f"q{number:02d}", prompt, "slider", "交流方式", key,
        default=DEFAULT_INTERACTION[short],
    )


QUESTIONS: tuple[OnboardingQuestion, ...] = (
    _text(1, "你希望我怎么称呼你？昵称就可以。", "关于你（选填）", "profile.name"),
    _text(2, "愿意的话，说说你的年龄段；不需要生日或证件信息。", "关于你（选填）", "profile.age"),
    _text(3, "你通常在哪个城市或地区生活？不需要详细地址。", "关于你（选填）", "profile.location"),
    _text(4, "你目前在怎样的学习环境里？不用提供真实校名。", "关于你（选填）", "profile.school"),
    _text(5, "你正在学什么专业或科目？", "关于你（选填）", "profile.major"),
    _text(6, "你平时做哪一类工作或活动？", "关于你（选填）", "profile.job"),
    _text(7, "最近你对哪些事最感兴趣？", "兴趣", "profile.interests", multiple=True),
    _text(8, "哪些活动会让你真心开心？", "兴趣", "profile.likes", multiple=True),
    _text(9, "有哪些事让你明显不喜欢？", "兴趣", "profile.dislikes", multiple=True),
    _text(10, "你有哪些重要的习惯或固定安排？", "兴趣", "profile.habits", multiple=True),
    _text(11, "你目前最想完成什么？", "目标", "profile.goals", prefix="Current goal: ", multiple=True),
    _text(12, "长期来看，你想做到什么或过怎样的生活？", "目标", "profile.goals", prefix="Long-term: ", multiple=True),
    _text(13, "有哪些话题，你愿意经常和我聊？", "目标", "relationship.common_topics", multiple=True),
    _text(14, "你喜欢哪些书、游戏、电影、动漫或节目？", "喜好", "profile.likes", prefix="Media: ", multiple=True),
    _text(15, "你喜欢什么音乐或歌手？", "喜好", "profile.likes", prefix="Music: ", multiple=True),
    _text(16, "你喜欢哪些食物或饮料？", "喜好", "profile.likes", prefix="Food: ", multiple=True),
    _text(17, "哪些价值观或原则对你比较重要？", "喜好", "profile.interests", prefix="Value: ", multiple=True),
    _text(18, "聊到什么，会让你更舒服或觉得被理解？", "边界", "relationship.common_topics", prefix="Comfort: ", multiple=True),
    _text(19, "有哪些话题、称呼或说话方式，你不希望我使用？", "边界", "profile.dislikes", prefix="Avoid: ", multiple=True),
    _text(20, "你的日常作息，还有什么希望我记住？", "边界", "profile.habits", multiple=True),
    _slider(21, "平时回复你更喜欢简短，还是详细？（少＝简短，多＝详细）", "interaction.reply_length"),
    _slider(22, "你希望交流有多温暖、亲近？", "interaction.warmth"),
    _slider(23, "你喜欢多大程度的幽默？", "interaction.humor"),
    _slider(24, "你能接受多少善意的调侃？", "interaction.teasing"),
    _slider(25, "你希望我说话有多直接？", "interaction.directness"),
    _slider(26, "你希望我多大程度地回应你的情绪？", "interaction.empathy"),
    _slider(27, "你希望我多常追问？（少＝少反问，多＝多了解）", "interaction.question_frequency"),
    _slider(28, "聊天时，你希望我多主动带动话题？", "interaction.initiative"),
    _slider(29, "倾诉时，你希望我多常给建议？（少＝先听你说，多＝一起想办法）", "interaction.advice_frequency"),
    _slider(30, "你喜欢我多常使用表情？", "interaction.emoji_frequency"),
    _text(31, "最近最投入的学习、工作或项目是什么？", "关于你（补充）", "current.current_activity"),
    _text(32, "哪些情况容易让你有压力？", "关于你（补充）", "profile.dislikes", prefix="Stress trigger: ", multiple=True),
    _text(33, "心情低落时，你通常怎样恢复？", "关于你（补充）", "profile.habits", prefix="Recovery: ", multiple=True),
    _text(34, "相处时，你最看重哪些原则？", "关于你（补充）", "profile.interests", prefix="Relationship value: ", multiple=True),
    _text(35, "有什么话题希望以后继续聊下去？", "关于你（补充）", "relationship.common_topics", multiple=True),
    _text(36, "你希望这个陪伴者给你什么感觉？用几个关键词即可，比如温柔、活泼、沉稳、有主见。", "陪伴者是什么样", "persona.temperament"),
    OnboardingQuestion("q37", "角色是女性、男性，还是不指定？自定义身份可填在角色介绍中。", "choice", "陪伴者是什么样", "persona.presentation", options=("female", "male", "neutral")),
    _text(38, "你希望你们怎样相处？像朋友、亲近的搭档、一起学习的人，还是别的关系？", "陪伴者是什么样", "persona.relationship"),
    OnboardingQuestion("q39", "当你说今天很累时，你更希望它先倾听、一起想办法，还是兼顾两者？", "choice", "陪伴者是什么样", "persona.support", options=("listen", "solutions", "mixed")),
    _text(40, "这个角色有哪些绝对不要的表现？比如说教、黏人、挖苦、总是顺着你。", "陪伴者是什么样", "persona.boundaries"),
    _text(41, "希望它叫什么昵称？没有想法可以自动取名。", "陪伴者（补充）", "persona.name"),
    _text(42, "除了第一印象，你希望它有哪些稳定的性格特点？", "陪伴者（补充）", "persona.character"),
    _text(43, "希望它愿意和你一起了解哪些领域？不要求它假装有真实经历。", "陪伴者（补充）", "persona.interests"),
    _text(44, "意见不同时，你喜欢它怎样表达和解释？", "陪伴者（补充）", "persona.disagreement"),
    _text(45, "哪种玩笑让你舒服，哪种玩笑不要开？", "陪伴者（补充）", "persona.humor"),
    _text(46, "喜欢它使用怎样的称呼、口头禅或措辞？", "陪伴者（补充）", "persona.voice"),
    _text(47, "你成功或失落时，希望它分别怎么回应？", "陪伴者（补充）", "persona.reactions"),
    _text(48, "你忙或暂时不回消息时，希望它如何保持分寸？", "陪伴者（补充）", "persona.space"),
    _text(49, "希望它怎样支持你成长，而不是替你做决定？", "陪伴者（补充）", "persona.growth"),
    _text(50, "有没有特别喜欢或讨厌的一种回应？举个简短例子。", "陪伴者（补充）", "persona.examples"),
)

# Stable old IDs preserve existing answers/evidence. Display order is now 5 + 5,
# followed by 20 user questions + 20 character questions.
RECOMMENDED_IDS = ("q01", "q06", "q07", "q11", "q19", "q36", "q37", "q38", "q39", "q40")
_by_id = {q.id: q for q in QUESTIONS}
QUESTIONS = tuple(_by_id[key] for key in RECOMMENDED_IDS) + tuple(
    q for q in QUESTIONS if q.id not in RECOMMENDED_IDS and not q.key.startswith(('persona.', 'interaction.'))
) + tuple(q for q in QUESTIONS if q.id not in RECOMMENDED_IDS and q.key.startswith(('persona.', 'interaction.')))
UNSURE = '__unsure__'


class OnboardingService:
    """Builds a real initial AUL without spending LLM tokens."""

    def __init__(self, store: SQLiteStore, aggregator: EvidenceAggregator):
        self.store = store
        self.aggregator = aggregator

    def status(self) -> dict[str, Any]:
        answers = self._answers()
        state = self.store.get_metadata("onboarding_state") or "not_started"
        seen = set(answers)
        next_index = next((i for i, q in enumerate(QUESTIONS) if q.id not in seen), len(QUESTIONS))
        try:
            resume_index = int(self.store.get_metadata('onboarding_resume_index') or next_index)
        except (TypeError, ValueError):
            resume_index = next_index
        return {
            "state": state,
            "answered": len(seen),
            "total": len(QUESTIONS),
            "next_index": next_index,
            "resume_index": max(0, min(len(QUESTIONS), resume_index)),
            "full_interview": self.store.get_metadata('onboarding_full_interview') == '1',
            "answers": answers,
            "questions": [q.public() for q in QUESTIONS],
            "recommended_ids": list(RECOMMENDED_IDS),
            "required_complete": all(self._answered(answers.get(key)) for key in RECOMMENDED_IDS),
        }

    def begin(self) -> dict[str, Any]:
        self.store.set_metadata("onboarding_state", "in_progress")
        return self.status()

    def skip(self) -> dict[str, Any]:
        self.store.set_metadata("onboarding_state", "skipped")
        return self.status()

    def submit(self, submitted: dict[str, Any], finish: bool = False,
               progress: dict[str, Any] | None = None) -> dict[str, Any]:
        known = {q.id: q for q in QUESTIONS}
        clean: dict[str, Any] = {}
        for key, value in submitted.items():
            key = str(key)
            if key not in known:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                clean[key] = None  # Explicitly clearing an answer withdraws its evidence.
            elif value == UNSURE:
                clean[key] = UNSURE
            elif known[key].kind == "choice":
                if isinstance(value, str) and value.strip() in known[key].options:
                    clean[key] = value.strip()
            elif known[key].kind == "slider":
                try:
                    number = float(value)
                except (ValueError, TypeError):
                    continue
                if not isinstance(value, bool) and math.isfinite(number):
                    clean[key] = max(0.0, min(1.0, number))
            elif isinstance(value, str):
                clean[key] = value.strip()[:1000]
        answers = self._answers()
        # The UI resends the whole draft each page. Unchanged answers must retain
        # their original evidence/time, rather than overwriting later corrections.
        clean = {key: value for key, value in clean.items() if value != answers.get(key)}
        progress_updates = self._progress_updates(progress, finish)
        if not clean:
            if finish or progress_updates:
                with self.store.connection() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    updates = progress_updates + ([("onboarding_state", "completed")] if finish else [])
                    conn.executemany('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)', updates)
                    conn.commit()
            return self.status()

        source = self.store.save_message(
            "__onboarding__", "system", "AUL onboarding answers: " + ",".join(sorted(clean)),
        )
        evidence_index = self._evidence_index()
        old_ids = [evidence_id for question_id in clean for evidence_id in evidence_index.get(question_id, [])]
        affected: set[str] = set()
        evidence: list[Evidence] = []
        for question_id, answer in clean.items():
            question_evidence = self._to_evidence(known[question_id], answer, source.id)
            evidence.extend(question_evidence)
            evidence_index[question_id] = [item.id for item in question_evidence]
            affected.update(item.key for item in question_evidence)
        for key, value in clean.items():
            if value is None:
                answers.pop(key, None)
            else:
                answers[key] = value
        # Evidence, the rebuilt AUL and progress must move together on a crash.
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            distilled = json.loads(self.store.get_metadata('onboarding_distillation') or '{}')
            for key in clean:
                distilled.pop(key, None)
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                affected.update(row["key"] for row in conn.execute(
                    f"SELECT DISTINCT key FROM evidence WHERE id IN ({placeholders})", old_ids
                ).fetchall())
                conn.execute(f"DELETE FROM evidence WHERE id IN ({placeholders})", old_ids)
            self.store.save_evidence(evidence, connection=conn)
            if affected:
                self.aggregator.aggregate(force_keys=affected, connection=conn)
            complete = finish or len(answers) >= len(QUESTIONS)
            conn.executemany("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", [
                ("onboarding_answers", json.dumps(answers, ensure_ascii=False)),
                ("onboarding_evidence", json.dumps(evidence_index, ensure_ascii=False)),
                ("onboarding_distillation", json.dumps(distilled, ensure_ascii=False)),
                ("onboarding_state", "completed" if complete else "in_progress"),
            ] + progress_updates)
            conn.commit()
        return self.status()

    def _progress_updates(self, progress: Any, finish: bool) -> list[tuple[str, str]]:
        progress = progress if isinstance(progress, dict) else {}
        result = []
        full = progress.get('full_interview')
        if isinstance(full, bool):
            result.append(('onboarding_full_interview', '1' if full else '0'))
        else:
            full = self.store.get_metadata('onboarding_full_interview') == '1'
        index = progress.get('resume_index')
        if finish:
            index = len(QUESTIONS) if full else len(RECOMMENDED_IDS)
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= len(QUESTIONS):
            result.append(('onboarding_resume_index', str(index)))
        return result

    def apply_distillation(self, proposal: dict) -> dict:
        """User-confirmed model keywords replace only the corresponding old answers'
        evidence. Keep original source time so later chat corrections still win.
        Original questionnaire answers remain intact for editing and withdrawal.
        """
        from .character_interview import validated_character_draft
        basis = proposal.get('distillation_basis', {})
        # Revalidate at confirmation, not only when the network request returned.
        validated = validated_character_draft(json.dumps({
            'name': proposal.get('persona', {}).get('name'),
            'description': proposal.get('persona', {}).get('description'),
            'boundaries': proposal.get('persona', {}).get('boundaries', ''),
            'nickname_candidates': proposal.get('nickname_candidates'),
            'tentative_assumptions': proposal.get('tentative_assumptions', []),
            'user_distillation': proposal.get('user_distillation', []),
        }), basis, proposal.get('persona', {}).get('language', 'zh-CN'))
        notes = validated['user_distillation']
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            answers = self._answers()
            index = self._evidence_index()
            previous = json.loads(self.store.get_metadata('onboarding_distillation') or '{}')
            affected = set()
            for note in notes:
                key, summary = note['question_id'], note['summary']
                if answers.get(key) != basis.get(key):
                    raise ValueError('Questionnaire changed since the draft was generated')
                marker = {'answer': answers[key], 'summary': summary}
                if previous.get(key) == marker:
                    continue
                old_ids = index.get(key, [])
                marks = ','.join('?' for _ in old_ids)
                old = [self.store._evidence_from_row(row) for row in conn.execute(
                    f'SELECT * FROM evidence WHERE id IN ({marks})', old_ids)] if old_ids else []
                if not old:
                    raise ValueError('Distillation source no longer exists')
                question = next(q for q in QUESTIONS if q.id == key)
                evidence = self._to_evidence(question, summary, old[0].source_message_id)
                for item in evidence:
                    original = next((e for e in old if e.key == item.key), old[0])
                    item.created_at, item.expires_at = original.created_at, original.expires_at
                conn.execute(f'DELETE FROM evidence WHERE id IN ({marks})', old_ids)
                self.store.save_evidence(evidence, connection=conn)
                index[key] = [item.id for item in evidence]
                affected.update(item.key for item in old + evidence)
                previous[key] = marker
            if affected:
                self.aggregator.aggregate(force_keys=affected, connection=conn)
            conn.executemany('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)', [
                ('onboarding_evidence', json.dumps(index)),
                ('onboarding_distillation', json.dumps(previous, ensure_ascii=False)),
            ])
            conn.commit()
        return self.store.get_aul()

    def _answers(self) -> dict[str, Any]:
        raw = self.store.get_metadata("onboarding_answers")
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _evidence_index(self) -> dict[str, list[str]]:
        raw = self.store.get_metadata("onboarding_evidence")
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            return {
                str(key): [str(item) for item in items]
                for key, items in value.items() if isinstance(items, list)
            } if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _answered(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip()) or (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))

    def require_first_ten(self, submitted: dict[str, Any] | None = None) -> dict[str, Any]:
        answers = {**self._answers(), **(submitted or {})}
        missing = [key for key in RECOMMENDED_IDS if not self._answered(answers.get(key))]
        if missing:
            raise ValueError('First ten answers are required: ' + ','.join(missing))
        return answers

    @staticmethod
    def _to_evidence(question: OnboardingQuestion, answer: Any, source_id: str) -> list[Evidence]:
        if answer == UNSURE or question.key.startswith('persona.'):
            return []  # Character details are never user facts. Unknown is not a fact either.
        if question.kind == "slider":
            try:
                number = float(answer)
            except (TypeError, ValueError):
                return []
            if isinstance(answer, bool) or not math.isfinite(number):
                return []
            target = max(0.0, min(1.0, number))
            return [Evidence(
                id=f"ev_{uuid.uuid4().hex}", type="interaction_preference",
                key=question.key, value=target, strength=1.0, confidence=0.98,
                importance=0.9, source_message_id=source_id, signal="baseline",
            )]

        text = str(answer or "").strip()
        if not text:
            return []
        values = [text]
        if question.multiple:
            values = [item.strip() for item in re.split(r"[,，;；\n]", text) if item.strip()][:12]
        type_ = "relationship_context" if question.key.startswith("relationship.") else "current_state" if question.key.startswith('current.') else "profile_fact"
        if question.key.endswith(("interests", "likes", "dislikes", "habits", "goals")):
            type_ = "preference"
        result = [Evidence(
            id=f"ev_{uuid.uuid4().hex}", type=type_, key=question.key,
            value=question.prefix + value, strength=0.9, confidence=0.97,
            importance=0.75, source_message_id=source_id, signal="explicit",
            expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat() if question.key.startswith('current.') else None,
        ) for value in values]
        if question.id == "q11":
            # The current goal is useful immediately, while the stable goal list
            # remains as durable history. Expiry prevents cold-start data from
            # pretending to be current forever.
            result.append(Evidence(
                id=f"ev_{uuid.uuid4().hex}", type="current_state",
                key="current.current_goal", value=text, strength=0.9,
                confidence=0.97, importance=0.9, source_message_id=source_id,
                expires_at=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
                signal="explicit",
            ))
        return result
