from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .models import Evidence, Message


class Observer(Protocol):
    def observe(self, message: Message) -> list[Evidence]: ...


class RuleBasedObserver:
    """Deterministic MVP observer. It records observations, never beliefs."""

    def observe(self, message: Message) -> list[Evidence]:
        # Preserve raw chat verbatim in storage, but only learn from assertions.
        # Quoted examples and hypothetical/third-person reports are not a user's
        # own high-confidence identity or preference statements.
        text = self._asserted_text(message.content.strip())
        evidence: list[Evidence] = []

        def add(
            type_: str, key: str, value=None, direction: str | None = None,
            strength: float = 0.7, confidence: float = 0.9,
            importance: float = 0.6, signal: str = "explicit",
            expires_days: int | None = None,
        ) -> None:
            expires = None
            if expires_days:
                occurred = datetime.fromisoformat(message.timestamp)
                if occurred.tzinfo is None:
                    occurred = occurred.replace(tzinfo=UTC)
                expires = (occurred + timedelta(days=expires_days)).isoformat()
            evidence.append(Evidence(
                id=f"ev_{uuid.uuid4().hex}", type=type_, key=key, value=value,
                direction=direction, strength=strength, confidence=confidence,
                importance=importance, source_message_id=message.id,
                expires_at=expires, signal=signal,
            ))

        lower = text.lower()

        # Explicit interaction corrections carry high weight.
        rejects_short = bool(re.search(r"(?:不要|别|不喜欢|不想|不用|不需要).{0,5}(?:太短|短点|短一点|简短|精简)|(?:don't|do not).{0,8}(?:concise|short)", lower))
        rejects_detail = bool(re.search(r"(?:不要|别|不喜欢|不想|不用|不需要).{0,5}(?:详细|展开|多解释)|(?:don't|do not).{0,8}(?:detailed|verbose|detail)", lower))
        if rejects_detail and not rejects_short:
            add("interaction_preference", "interaction.reply_length", direction="decrease",
                strength=0.95, confidence=0.98, importance=0.9, signal="correction")
        elif not rejects_short and not rejects_detail and re.search(r"(短点|短一点|简短|精简|别扯(这么)?多|太长|less verbose|shorter|concise)", lower):
            correction = bool(re.search(r"别|太长|最近|shorter", lower))
            add("interaction_preference", "interaction.reply_length", direction="decrease",
                strength=0.95 if correction else 0.72,
                confidence=0.99 if correction else 0.94,
                importance=0.9, signal="correction" if correction else "explicit")
        if rejects_short and not rejects_detail:
            add("interaction_preference", "interaction.reply_length", direction="increase",
                strength=0.9, confidence=0.98, importance=0.9, signal="correction")
        elif not rejects_detail and not rejects_short and re.search(r"(详细(一点|解释)?|展开(说|讲)|多解释|more detail|detailed)", lower):
            add("interaction_preference", "interaction.reply_length", direction="increase",
                strength=0.82, confidence=0.96, importance=0.8, signal="explicit")
        if re.search(r"(别|不要).{0,8}(每句|总是|老是|一直).{0,5}(问|问题)|don't.{0,12}(always|keep).{0,8}(ask|question)", lower):
            add("interaction_preference", "interaction.question_frequency", direction="decrease",
                strength=1.0, confidence=0.995, importance=1.0, signal="correction")
        elif re.search(r"(少问|别追问|不要追问|fewer questions|don't ask)", lower):
            add("interaction_preference", "interaction.question_frequency", direction="decrease",
                strength=0.9, confidence=0.98, importance=0.9, signal="correction")
        if re.search(r"(直接点|直说|开门见山|be direct)", lower):
            add("interaction_preference", "interaction.directness", direction="increase",
                strength=0.85, confidence=0.97, importance=0.85)
        if re.search(r"(别给建议|不要建议|只想吐槽|don't give advice)", lower):
            add("interaction_preference", "interaction.advice_frequency", direction="decrease",
                strength=0.95, confidence=0.98, importance=0.9, signal="correction")
        if re.search(r"(多给建议|给我建议|建议多一点|give me advice)", lower):
            add("interaction_preference", "interaction.advice_frequency", direction="increase",
                strength=0.8, confidence=0.95)
        if re.search(r"(别用表情|不要表情|no emoji)", lower):
            add("interaction_preference", "interaction.emoji_frequency", direction="decrease",
                strength=0.95, confidence=0.99, signal="correction")
        if re.search(r"(幽默点|开点玩笑|more humor|be funny)", lower):
            add("interaction_preference", "interaction.humor", direction="increase",
                strength=0.75, confidence=0.93)
        if re.search(r"(温柔点|暖一点|more empathetic|warmer)", lower):
            add("interaction_preference", "interaction.warmth", direction="increase",
                strength=0.75, confidence=0.93)

        # Stable profile facts.
        patterns = [
            (r"(?:我叫|我的名字是)\s*([\w\u4e00-\u9fff·]{1,30})", "profile_fact", "profile.name"),
            (r"我(?:现在)?是\s*([^，。,.]{2,30})专业", "profile_fact", "profile.major"),
            (r"我的专业是\s*([^，。,.]{2,30})", "profile_fact", "profile.major"),
            (r"我住在\s*([^，。,.]{2,30})", "profile_fact", "profile.location"),
            (r"我在\s*([^，。,.]{2,40})\s*(?:上学|读书)", "profile_fact", "profile.school"),
            (r"我的工作是\s*([^，。,.]{2,40})", "profile_fact", "profile.job"),
        ]
        for pattern, type_, key in patterns:
            match = re.search(pattern, text)
            if match:
                add(type_, key, match.group(1).strip(), strength=0.95,
                    confidence=0.98, importance=0.8)

        # Stable preferences and short-lived state are deliberately separate.
        like_match = re.search(r"我(?:一直)?(?:很)?喜欢\s*([^，。,.!?！？]{1,40})", text)
        if like_match:
            value = like_match.group(1).strip()
            add("preference", "profile.likes", value, strength=0.8,
                confidence=0.94, importance=0.7)
        dislike_match = re.search(r"我(?:一直)?(?:很)?不喜欢\s*([^，。,.!?！？]{1,40})", text)
        if dislike_match and "最近" not in text:
            add("dislike", "profile.dislikes", dislike_match.group(1).strip(),
                strength=0.8, confidence=0.94, importance=0.7)
        recent_avoid = re.search(r"我最近(?:不想|不太想|不愿意)\s*([^，。,.!?！？]{1,40})", text)
        if recent_avoid:
            add("current_state", "current.recent_avoidance", recent_avoid.group(1).strip(),
                strength=0.85, confidence=0.95, importance=0.65, expires_days=14)

        mood_patterns = {
            "stressed": r"(压力很大|焦虑|烦死|崩溃|stressed|anxious)",
            "sad": r"(难过|伤心|低落|sad)",
            "happy": r"(很开心|太好了|兴奋|happy|excited)",
            "tired": r"(好累|很累|疲惫|tired|exhausted)",
        }
        for mood, pattern in mood_patterns.items():
            if any(not re.search(r"不|没|not|never", lower[max(0, match.start() - 5):match.start()])
                   for match in re.finditer(pattern, lower)):
                add("current_state", "current.mood", mood, strength=0.8,
                    confidence=0.9, importance=0.7, expires_days=3)
                break

        goal = re.search(r"(?:我的目标是|我打算|我准备|I plan to)\s*([^。.!！?？]{2,80})", text, re.I)
        if goal:
            add("goal", "profile.goals", goal.group(1).strip(), strength=0.75,
                confidence=0.9, importance=0.85)
            add("current_state", "current.current_goal", goal.group(1).strip(),
                strength=0.75, confidence=0.9, importance=0.8, expires_days=90)

        event = re.search(r"(?:今天|昨天|刚刚|上周|最近)([^。.!！?？]{3,100})(?:了|完成|发生|结束)", text)
        if event:
            add("event", "current.recent_events", event.group(0).strip(), strength=0.7,
                confidence=0.82, importance=0.75, expires_days=30)
        if re.search(r"(?:项目|目标|任务|考试).{0,12}(?:完成了|结束了|通过了)|(?:project|goal|task).{0,12}(?:done|finished)", lower):
            add("state_change", "current.current_goal", None, strength=0.9,
                confidence=0.94, importance=0.85, signal="explicit")

        # A one-word acknowledgement is intentionally not preference evidence.
        return evidence

    @staticmethod
    def _asserted_text(text: str) -> str:
        text = re.sub(r'```[\s\S]*?```|`[^`\n]*`|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"', '。', text)
        text = re.sub(r"(?<![a-zA-Z0-9_])'[^'\n]+'(?![a-zA-Z0-9_])", '。', text)
        clauses = re.split(r'([。！？!?；;\n])', text)
        for index in range(0, len(clauses), 2):
            clause = clauses[index]
            # Conservative abstention is cheaper than a confidently false belief.
            if (re.search(r'假如|假设|如果|例如|比如|(?:朋友|同学|同事|别人|他|她)(?:说|表示|告诉我)|不是说|不代表', clause)
                    or re.match(r'^\s*(?:我(?:的)?|一个)?(?:朋友|同学|同事|别人|他|她)', clause)):
                clauses[index] = ' '
        return ''.join(clauses)
