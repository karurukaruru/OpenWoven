from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .core import CompanionCore
from .llm import LocalCompanionProvider, OpenAICompatibleProvider
from .semantic_observer import HybridObserver, OpenAICompatibleEvidenceObserver


def _dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _provider(name: str):
    if name == "openai":
        return OpenAICompatibleProvider.from_env()
    return LocalCompanionProvider()


def _observer(name: str):
    if name == "hybrid":
        return HybridObserver(OpenAICompatibleEvidenceObserver.from_env())
    return None


def _show(core: CompanionCore, subject: str, key: str | None = None) -> None:
    core.wait_for_learning()
    if subject == "aul":
        _dump(core.aul())
    elif subject == "state":
        _dump(core.aul()["current"])
    elif subject == "policy":
        _dump(core.current_policy())
    elif subject == "evidence":
        _dump([asdict(e) for e in core.store.list_evidence(key=key)])
    elif subject == "memories":
        _dump(core.store.list_memories())
    elif subject == "daily":
        _dump(core.store.list_memories("daily"))
    elif subject in {"weekly", "monthly"}:
        _dump(core.store.list_memories(subject))
    elif subject == "audit":
        _dump(core.store.list_audit(field=key))
    elif subject == "metrics":
        observer = core.learning.observer
        semantic = getattr(observer, "semantic", None)
        semantic_calls = int(getattr(observer, "semantic_calls", 0))
        user_messages = core.store.count_messages(role="user")
        generations = core.store.list_generation_metrics(limit=1000)
        successful = [item for item in generations if item["status"] == "success"]
        _dump({
            "messages": user_messages,
            "aul_version": core.aul()["version"],
            "dialogue_provider": type(core.provider).__name__,
            "dialogue_token_usage": getattr(core.provider, "total_usage", {}),
            "persisted_generation_count": len(generations),
            "persisted_total_tokens": sum(item["total_tokens"] for item in successful),
            "average_success_latency_ms": round(
                sum(item["latency_ms"] for item in successful) / max(1, len(successful)), 1
            ),
            "observer": type(observer).__name__,
            "semantic_calls": semantic_calls,
            "semantic_failures": int(getattr(observer, "semantic_failures", 0)),
            "semantic_call_rate": round(semantic_calls / max(1, user_messages), 4),
            "observer_token_usage": getattr(semantic, "total_usage", {}),
        })
    elif subject == "preference":
        if not key or key not in core.aul()["interaction"]:
            raise SystemExit("show preference requires a valid key")
        preference = core.aul()["interaction"][key]
        full_key = f"interaction.{key}"
        _dump({
            **preference,
            "evidence": [asdict(e) for e in core.store.list_evidence(full_key)],
            "audit": core.store.list_audit(full_key),
        })


def interactive(core: CompanionCore, conversation_id: str) -> None:
    print("OpenWoven — 输入 /help 查看命令，/quit 退出")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            break
        if line == "/help":
            print("/show aul|state|policy|evidence|memories|daily|weekly|audit|metrics")
            print("/show preference <key> | /daily | /weekly | /archive | /search <query> | /quit")
            continue
        if line == "/daily":
            core.wait_for_learning()
            _dump(core.memory.consolidate_daily())
            continue
        if line == "/weekly":
            core.wait_for_learning()
            _dump(core.memory.consolidate_weekly())
            continue
        if line.startswith("/show "):
            parts = line.split(maxsplit=2)
            _show(core, parts[1], parts[2] if len(parts) > 2 else None)
            continue
        if line == "/archive":
            core.wait_for_learning()
            _dump(core.memory.maintain())
            continue
        if line.startswith("/search "):
            _dump(core.retriever.retrieve(line[8:]))
            continue
        print(core.chat(line, conversation_id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openwoven", description="OpenWoven CLI")
    parser.add_argument("--db", default=os.environ.get("COMPANION_DB", "companion.db"))
    parser.add_argument("--provider", choices=("local", "openai"), default="local")
    parser.add_argument("--observer", choices=("rule", "hybrid"), default="rule")
    sub = parser.add_subparsers(dest="command")
    chat = sub.add_parser("chat")
    chat.add_argument("--conversation", default="default")
    show = sub.add_parser("show")
    show.add_argument("subject", choices=(
        "aul", "state", "policy", "evidence", "memories", "daily", "weekly", "monthly", "audit", "preference", "metrics"
    ))
    show.add_argument("key", nargs="?")
    sub.add_parser("daily")
    sub.add_parser("weekly")
    sub.add_parser("archive")
    search = sub.add_parser("search")
    search.add_argument("query")
    detail = sub.add_parser("archive-detail")
    detail.add_argument("memory_id")
    detail.add_argument("--offset", type=int, default=0)
    demo = sub.add_parser("demo")
    demo.add_argument("--conversation", default="demo")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with CompanionCore(
        args.db, provider=_provider(args.provider), observer=_observer(args.observer)
    ) as core:
        if args.command in {None, "chat"}:
            interactive(core, getattr(args, "conversation", "default"))
        elif args.command == "show":
            _show(core, args.subject, args.key)
        elif args.command == "daily":
            core.wait_for_learning()
            _dump(core.memory.consolidate_daily())
        elif args.command == "weekly":
            core.wait_for_learning()
            _dump(core.memory.consolidate_weekly())
        elif args.command == "demo":
            from .demo import run_demo
            run_demo(core, args.conversation)
        elif args.command == "archive":
            core.wait_for_learning()
            _dump(core.memory.maintain())
        elif args.command == "search":
            _dump(core.retriever.retrieve(args.query))
        elif args.command == "archive-detail":
            _dump(core.memory.archives.detail(args.memory_id, args.offset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
