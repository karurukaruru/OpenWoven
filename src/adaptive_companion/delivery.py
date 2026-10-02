from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class DeliveryPart:
    text: str
    delay_ms: int


@dataclass(slots=True)
class DeliveryPlan:
    mode: str
    parts: list[DeliveryPart]

    def to_dict(self) -> dict:
        return {"mode": self.mode, "parts": [asdict(part) for part in self.parts]}


@dataclass(slots=True)
class DeliverySettings:
    enabled: bool = True
    base_delay_ms: int = 750
    delay_per_character_ms: int = 30
    random_jitter_ms: int = 150
    split_probability: float = 0.32
    minimum_delay_ms: int = 800
    maximum_delay_ms: int = 2500
    maximum_parts: int = 6
    greeting_delay_enabled: bool = False


class DeliveryPlanner:
    def __init__(self, settings: DeliverySettings | None = None):
        self.settings = settings or DeliverySettings()

    def greeting_wait_seconds(self, text: str, seed: str = "") -> int:
        if not self.settings.enabled or not self.settings.greeting_delay_enabled:
            return 0
        if not re.fullmatch(r"\s*(?:在吗|在不在|有空吗|are you there)[？?！!。\s]*", text, re.I):
            return 0
        return random.Random(seed or text).randint(60, 180)

    def plan(self, text: str, seed: str = "", policy: dict | None = None,
             generation_latency_ms: int = 0) -> DeliveryPlan:
        clean = text.strip()
        if not clean:
            return DeliveryPlan("immediate", [])
        rng = random.Random(seed or clean)
        # A small rhythm for casual chat only; a slow model has already supplied
        # the wait. Never delay distress/technical answers or split code blocks.
        casual = policy and policy.get("context") in {"casual_chat", "bored", "sharing_good_news"}
        protected = "```" in clean or (policy and not casual)
        protected = protected or len(clean) > 600 or bool(policy and policy.get('message_format') == 'document')
        protected = protected or bool(re.search(r'(?m)^\s*(?:#{1,6}\s|[-*]\s|\d+[.)]\s)|https?://|\|.+\|', clean))
        first_delay = max(0, min(900, self.settings.maximum_delay_ms,
            self.settings.base_delay_ms + min(40, len(clean)) * self.settings.delay_per_character_ms
            + rng.randint(0, max(0, self.settings.random_jitter_ms))) - max(0, generation_latency_ms)) if self.settings.enabled and casual and not protected else 0
        chinese_chat = bool(casual and not protected and re.search(r'[\u3400-\u9fff]', clean))
        candidates = self._chat_chunks(clean) if chinese_chat else [part.strip() for part in re.split(r"(?<=[。！？!?])\s*|\n+", clean) if part.strip()]
        candidates = self._fit_parts(candidates)
        should_split = (
            2 <= len(candidates) <= self.settings.maximum_parts
            and (chinese_chat or len(clean) >= 20 and rng.random() < self.settings.split_probability)
            and not protected
        )
        parts = candidates if should_split or chinese_chat else [clean]
        if not should_split:
            return DeliveryPlan("delayed" if first_delay else "immediate", [DeliveryPart(parts[0], first_delay)])
        planned = []
        for index, part in enumerate(parts):
            raw = (
                self.settings.base_delay_ms
                + len(part) * self.settings.delay_per_character_ms
                + rng.randint(0, max(0, self.settings.random_jitter_ms))
            )
            planned.append(DeliveryPart(part, (first_delay if index == 0 else self._clamp_delay(raw)) if self.settings.enabled else 0))
        return DeliveryPlan("split", planned)

    @staticmethod
    def _chat_chunks(text: str) -> list[str]:
        """Conservative Chinese chat boundaries; no blind comma/character chopping."""
        if re.search(r'[“”「」『』"]', text):
            return [text]  # A quotation is content, not a set of send boundaries.
        # Spaces between Han phrases are common model-generated send boundaries;
        # keep English names, numbers and mixed-language tokens untouched.
        sentences = re.split(r'(?<=[。！？!?])\s*|\n+|(?<=[\u3400-\u9fff！？!?])\s+(?=[\u3400-\u9fff])', text)
        result = []
        for sentence in sentences:
            sentence = sentence.strip().rstrip('。')
            if not sentence:
                continue
            # A connector is a natural new message. Keep short comma phrases,
            # enumerations, quoted speech and numbers intact.
            clauses = [sentence] if re.search(r'[“”「」『』"\d]', sentence) else re.split(
                r'[，,]\s*(?=(?:然后|然後|不过|不過|另外|对了|對了|所以|但是|而且))', sentence)
            for clause in clauses:
                clause = clause.strip().rstrip('。')
                if clause:
                    # Prefer meaningful commas when a casual bubble is too long.
                    if len(clause) > 48 and '，' in clause:
                        group = ''
                        for phrase in clause.split('，'):
                            if group and len(group) + len(phrase) > 48:
                                result.append(group)
                                group = phrase
                            else:
                                group = group + '，' + phrase if group else phrase
                        if group:
                            result.append(group)
                    else:
                        result.append(clause)
        return result or [text]

    def _fit_parts(self, parts: list[str]) -> list[str]:
        maximum = max(1, self.settings.maximum_parts)
        # Bound bubble count without dropping any text from a long answer.
        if len(parts) > maximum:
            parts = parts[:maximum - 1] + ['\n'.join(parts[maximum - 1:])]
        return parts

    def validate(self, plan: DeliveryPlan) -> DeliveryPlan:
        parts = []
        bounded = plan.parts[:max(1, self.settings.maximum_parts)]
        if len(plan.parts) > len(bounded):
            bounded[-1] = DeliveryPart('\n'.join(p.text for p in plan.parts[len(bounded)-1:]), bounded[-1].delay_ms)
        for part in bounded:
            if part.text.strip():
                delay = 0 if not self.settings.enabled else (
                    max(0, min(900, self.settings.maximum_delay_ms, int(part.delay_ms)))
                    if not parts else self._clamp_delay(part.delay_ms)
                )
                parts.append(DeliveryPart(
                    part.text.strip(), delay
                ))
        if not parts:
            return DeliveryPlan("immediate", [])
        mode = "split" if len(parts) > 1 else ("delayed" if parts[0].delay_ms else "immediate")
        return DeliveryPlan(mode, parts)

    def _clamp_delay(self, value: int) -> int:
        return max(self.settings.minimum_delay_ms, min(self.settings.maximum_delay_ms, int(value)))
