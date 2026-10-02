from __future__ import annotations

import json


def run_demo(core, conversation_id: str = "demo") -> None:
    before = core.aul()["interaction"]
    print("Turn 1 / initial policy:")
    print(json.dumps(core.current_policy("随便聊聊"), ensure_ascii=False, indent=2))

    messages = [
        "我叫林舟，我现在是电子信息专业。",
        "回答短点。",
        "别扯这么多。",
        "别每句话都问我问题。",
        "我喜欢咖啡。",
        "我最近不想喝咖啡。",
        "我的目标是这周完成信号处理项目。",
        "今天项目终于完成了。",
    ]
    for message in messages:
        print(f"\nYou: {message}")
        print(f"Companion: {core.chat(message, conversation_id)}")
        core.wait_for_learning()

    core.memory.maybe_create_rolling_summary(conversation_id)
    daily = core.memory.consolidate_daily()
    weekly = core.memory.consolidate_weekly()
    after = core.aul()["interaction"]
    print("\nLearning result:")
    print(json.dumps({
        "reply_length": {"before": before["reply_length"], "after": after["reply_length"]},
        "question_frequency": {"before": before["question_frequency"], "after": after["question_frequency"]},
        "policy": core.current_policy("帮我看看代码 bug"),
        "daily": daily,
        "weekly": weekly,
        "audit_entries": len(core.store.list_audit()),
    }, ensure_ascii=False, indent=2))
