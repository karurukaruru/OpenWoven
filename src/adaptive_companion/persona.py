"""User-selected companion identity, separate from beliefs about the user.

These are editable conversation preferences, not psychological test scores.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import DEFAULT_INTERACTION, DEFAULT_PERSONA

PRESETS = {
    "companion": ("an equal, steady everyday companion", {"warmth": .65, "question_frequency": .30, "advice_frequency": .35}),
    "listener": ("a gentle listener who understands before offering solutions", {"warmth": .80, "empathy": .85, "question_frequency": .25, "advice_frequency": .20, "teasing": .10}),
    "playful": ("a lighthearted friend with kind humor, never ridicule", {"warmth": .65, "humor": .75, "teasing": .45, "question_frequency": .30}),
    "coach": ("a collaborative growth partner, not a boss or lecturer", {"directness": .75, "initiative": .65, "advice_frequency": .65, "humor": .30}),
    "custom": ("a companion with the user's explicitly chosen characterization", {}),
}
CHOICES = {
    "support": {"listen": {"empathy": .85, "advice_frequency": .20}, "solutions": {"advice_frequency": .70}},
    "disagreement": {"gentle": {"directness": .40, "warmth": .75}, "direct": {"directness": .80}},
    "playfulness": {"quiet": {"humor": .20, "teasing": .05}, "playful": {"humor": .75, "teasing": .45}},
    "detail": {"short": {"reply_length": .25}, "detailed": {"reply_length": .75}},
    "initiative": {"wait": {"initiative": .25, "question_frequency": .20}, "topics": {"initiative": .70, "question_frequency": .40}},
    "closeness": {"reserved": {"warmth": .40, "teasing": .10}, "warm": {"warmth": .80}},
}
LANGUAGES = {"zh-CN": "Simplified Chinese", "zh-TW": "Traditional Chinese", "ja": "Japanese", "en-US": "American English"}

# These exact built-in rules are already enforced by the shared runtime role
# contract. Keep them in saved/older persona data, not repeated in every prompt.
RUNTIME_REDUNDANT_PRINCIPLES = frozenset({
    'speak naturally', 'avoid customer-service style', 'preserve continuity across conversations',
    'Character backstory is fictional, not real offline activity. Portray it naturally without routine identity disclaimers; answer direct reality questions truthfully. Never demand exclusive attachment.',
    'Respect autonomy; never guilt or pressure the user into chatting. Explicit wishes and safety override style.',
    'Character details describe YOU, not user facts.',
})


def build_persona(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    preset = config.get("preset")
    preset = preset if isinstance(preset, str) and preset in PRESETS else "companion"
    frame, initial = PRESETS[preset]
    persona = deepcopy(DEFAULT_PERSONA)
    persona['traits']['playful'] = preset == 'playful'
    style = {**DEFAULT_INTERACTION, 'reply_length': .30, **initial}
    selected: dict[str, str] = {}
    choices = config.get("choices", {})
    if isinstance(choices, dict):
        for key, options in CHOICES.items():
            value = choices.get(key)
            if isinstance(value, str) and value in options:
                style.update(options[value])
                selected[key] = value
    persona.update({
        "preset": preset,
        "name": str(config.get("name") or "Companion").strip()[:40] or "Companion",
        "relationship": frame,
        "description": str(config.get("description") or "").strip()[:600],
        "boundaries": str(config.get("boundaries") or "").strip()[:300],
        "language": LANGUAGES.get(config.get("language") if isinstance(config.get("language"), str) else "zh-CN", "Simplified Chinese"),
        "initial_style": style,
        "scenario_choices": selected,
    })
    if isinstance(config.get('character_id'), str) and config['character_id'].strip():
        persona['character_id'] = config['character_id'].strip()[:80]
    interview = config.get('interview')
    if isinstance(interview, dict) and (interview or config.get('blueprint_version') == 2):
        from .character_interview import BASE_CHARACTER_INSTRUCTIONS, STYLE_IDS, clean_answers
        answers = {key: value for key, value in clean_answers(interview).items() if value != '__unsure__'}
        if answers.get('q39') == 'mixed':
            persona['initial_style'].update(empathy=.8, advice_frequency=.5)
        for key, dimension in STYLE_IDS.items():
            value = answers.get(key)
            if isinstance(value, (int, float)):
                persona['initial_style'][dimension] = value
        if answers.get('q38'):
            persona['relationship'] = str(answers['q38'])[:300]
        persona['principles'].append(BASE_CHARACTER_INSTRUCTIONS)
    persona['principles'].extend([
        "Character backstory is fictional, not real offline activity. Portray it naturally without routine identity disclaimers; answer direct reality questions truthfully. Never demand exclusive attachment.",
        "Respect autonomy; never guilt or pressure the user into chatting. Explicit wishes and safety override style.",
        "Character details describe YOU, not user facts.",
    ])
    return persona
