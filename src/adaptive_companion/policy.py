from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


CONTEXT_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "casual_chat": {"warmth": 0.08, "humor": 0.08},
    "technical": {"directness": 0.30, "humor": -0.30, "teasing": -0.30,
                  "empathy": -0.15, "question_frequency": -0.18},
    "venting": {"empathy": 0.35, "warmth": 0.20, "advice_frequency": -0.40,
                "question_frequency": -0.20, "humor": -0.25},
    "emotional": {"empathy": 0.30, "warmth": 0.25, "humor": -0.25,
                  "teasing": -0.25},
    "sharing_good_news": {"warmth": 0.25, "humor": 0.10, "initiative": 0.10},
    "asking_for_advice": {"advice_frequency": 0.35, "directness": 0.20,
                          "initiative": 0.15},
    "serious_discussion": {"directness": 0.18, "humor": -0.30, "teasing": -0.30},
    "bored": {"humor": 0.25, "initiative": 0.30, "teasing": 0.10},
}


class InteractionPolicyBuilder:
    def __init__(self, initial_style: dict[str, float] | None = None):
        self.initial_style = initial_style or {}

    def classify(self, text: str, aul: dict[str, Any]) -> str:
        lower = text.lower()
        rules = [
            ("venting", r"烦|煩|受不了|吐槽|气死|氣死|崩溃|崩潰|annoyed|vent|腹が立つ|むかつく|愚痴"),
            ("emotional", r"难过|難過|伤心|傷心|焦虑|焦慮|害怕|孤独|孤獨|sad|anxious|lonely|悲しい|不安|寂しい"),
            ("sharing_good_news", r"好消息|成功了|通过了|通過了|拿到了|太好了|good news|i did it|合格した|うまくいった"),
            ("asking_for_advice", r"怎么办|怎麼辦|建议|建議|该不该|該不該|帮我选|幫我選|what should|advice|どうすれば|アドバイス"),
            ("bored", r"无聊|無聊|没事干|沒事幹|bored|退屈|暇だ"),
            ("technical", r"代码|代碼|bug|报错|報錯|算法|接口|数据库|資料庫|python|java|api|sql|error|コード|エラー|アルゴリズム"),
            ("serious_discussion", r"认真聊|認真聊|严肃|嚴肅|重要决定|重要決定|serious|真剣な話|大事な決断"),
        ]
        for context, pattern in rules:
            if re.search(pattern, lower):
                return context
        mood = aul.get("current", {}).get("mood")
        mood_value = mood.get("value") if isinstance(mood, dict) else mood
        if mood_value in {"stressed", "sad", "tired"} and len(text) <= 40:
            return "emotional"
        return "casual_chat"

    def build(self, text: str, aul: dict[str, Any]) -> dict[str, Any]:
        context = self.classify(text, aul)
        result: dict[str, Any] = {"context": context}
        adjustments = CONTEXT_ADJUSTMENTS[context]
        familiarity = float(aul.get("relationship", {}).get("familiarity", 0.0))
        for key, data in aul["interaction"].items():
            baseline = float(data['value'])
            # Persona style is a fallback, not an override of learned user wishes.
            if not data.get('evidence_count') and key in self.initial_style:
                baseline = self.initial_style[key]
            value = baseline + adjustments.get(key, 0.0)
            if context in {"casual_chat", "sharing_good_news"}:
                if key == "warmth":
                    value += 0.08 * familiarity
                elif key == "teasing":
                    value += 0.10 * familiarity
                elif key == "initiative":
                    value += 0.06 * familiarity
            result[key] = round(max(0.0, min(1.0, value)), 3)
        result["aul_version"] = aul["version"]
        document = r'(?:写|寫).{0,12}(?:通知|小作文|作文|文章|邮件|郵件|信|报告|報告|声明|聲明|故事)|(?:write|draft).{0,30}(?:essay|email|letter|notice|report|story)|(?:手紙|作文|文章|メール).{0,8}書'
        declined = r'(?:不要|别|別|不用|不必).{0,3}(?:写|寫)|(?:don.t|do not).{0,12}(?:write|draft)'
        if re.search(document, text, re.I) and not re.search(declined, text, re.I):
            result['message_format'] = 'document'
        return result
