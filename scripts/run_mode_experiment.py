from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.chat import ChatService  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.schemas import ChatMessage, ChatRequest  # noqa: E402


DEFAULT_MODES = ("simple", "prompt", "Mem0")
RESULT_FIELDS = (
    "mode",
    "round",
    "turn",
    "input",
    "output",
    "status",
    "error",
    "recalled_memories",
    "retrieved_examples",
    "referenced_examples",
    "warnings",
    "elapsed_seconds",
    "completed_at",
)


def load_inputs(path: Path) -> list[str]:
    messages: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            message = next((cell.strip() for cell in row if cell.strip()), "")
            if message:
                messages.append(message)
    if not messages:
        raise ValueError(f"入力文がありません: {path}")
    return messages


def build_experiment_settings(
    base_settings: Settings,
    mode: str,
    run_id: str,
) -> Settings:
    safe_run_id = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
    safe_mode = mode.lower()
    state_dir = PROJECT_ROOT / ".data" / "experiments" / safe_run_id / safe_mode
    return replace(
        base_settings,
        mode=mode,
        reset_state_on_start=False,
        mem0_vector_path=state_dir / "mem0_qdrant",
        mem0_history_db_path=state_dir / "mem0_history.db",
        mem0_collection_name=f"experiment_{safe_run_id}_{safe_mode}",
        conversation_db_path=state_dir / "conversations.db",
    )


async def run_mode(
    *,
    mode: str,
    service: ChatService,
    messages: Sequence[str],
    rounds: int,
    run_id: str,
    output_path: Path,
) -> int:
    errors = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=RESULT_FIELDS)
            writer.writeheader()

            for round_number in range(1, rounds + 1):
                # A round must never inherit Mem0 or summary state from the last one.
                service.reset_state()
                history: list[ChatMessage] = []
                user_id = f"experiment-{run_id}-{mode}-round-{round_number}"
                conversation_id = f"{user_id}-conversation"

                for turn_number, message in enumerate(messages, start=1):
                    print(
                        f"[{mode}] round {round_number}/{rounds} "
                        f"turn {turn_number}/{len(messages)}"
                    )
                    started_at = time.perf_counter()
                    row = {
                        "mode": mode,
                        "round": round_number,
                        "turn": turn_number,
                        "input": message,
                        "output": "",
                        "status": "ok",
                        "error": "",
                        "recalled_memories": 0,
                        "retrieved_examples": 0,
                        "referenced_examples": "[]",
                        "warnings": "[]",
                        "elapsed_seconds": "",
                        "completed_at": "",
                    }
                    try:
                        response = await service.reply(
                            ChatRequest(
                                message=message,
                                user_id=user_id,
                                conversation_id=conversation_id,
                                history=history,
                            )
                        )
                    except Exception as exc:
                        errors += 1
                        row["status"] = "error"
                        row["error"] = f"{type(exc).__name__}: {exc}"
                        print(f"  error: {row['error']}", file=sys.stderr)
                    else:
                        row["output"] = response.reply
                        row["recalled_memories"] = response.recalled_memories
                        row["retrieved_examples"] = response.retrieved_examples
                        row["referenced_examples"] = json.dumps(
                            [
                                example.model_dump()
                                for example in response.referenced_examples
                            ],
                            ensure_ascii=False,
                        )
                        row["warnings"] = json.dumps(
                            response.warnings,
                            ensure_ascii=False,
                        )
                        history.extend(
                            [
                                ChatMessage(role="user", content=message),
                                ChatMessage(
                                    role="assistant",
                                    content=response.reply,
                                ),
                            ]
                        )
                    finally:
                        row["elapsed_seconds"] = (
                            f"{time.perf_counter() - started_at:.3f}"
                        )
                        row["completed_at"] = datetime.now(timezone.utc).isoformat()
                        writer.writerow(row)
                        target.flush()
    finally:
        # Leave the isolated experiment store empty even after the final round.
        try:
            service.reset_state()
        finally:
            service.close()
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "CSVの各文をsimple/prompt/Mem0へ順番に入力し、モード別CSVへ保存します。"
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "test.csv",
        help="入力CSV（既定: data/test.csv）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "result",
        help="結果の保存先（既定: result）",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=25,
        help="各モードでCSV全体を繰り返す回数（既定: 25）",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=DEFAULT_MODES,
        default=list(DEFAULT_MODES),
        help="実行するモード（既定: simple prompt Mem0）",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    if args.rounds < 1:
        raise ValueError("--rounds は1以上にしてください")

    messages = load_inputs(args.input.resolve())
    run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    run_dir = args.output_dir.resolve() / run_id
    base_settings = get_settings()

    mode_settings = {
        mode: build_experiment_settings(base_settings, mode, run_id)
        for mode in args.modes
    }
    missing = {
        mode: settings.missing_api_keys
        for mode, settings in mode_settings.items()
        if settings.missing_api_keys
    }
    if missing:
        details = "; ".join(
            f"{mode}: {', '.join(keys)}" for mode, keys in missing.items()
        )
        raise RuntimeError(f"必要なAPIキーが設定されていません ({details})")

    run_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        "run_id": run_id,
        "input": str(args.input.resolve()),
        "messages_per_round": len(messages),
        "rounds": args.rounds,
        "calls_per_mode": len(messages) * args.rounds,
        "modes": list(args.modes),
        "base_model_provider": base_settings.base_model_provider,
        "base_model": base_settings.base_model,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_errors = 0
    print(
        f"{len(messages)}文 x {args.rounds}周 = "
        f"各モード{len(messages) * args.rounds}回を実行します。"
    )
    print(f"保存先: {run_dir}")
    for mode, settings in mode_settings.items():
        service = ChatService(settings)
        total_errors += await run_mode(
            mode=mode,
            service=service,
            messages=messages,
            rounds=args.rounds,
            run_id=run_id,
            output_path=run_dir / f"{mode}.csv",
        )

    print(f"完了: {run_dir}")
    if total_errors:
        print(f"APIエラー: {total_errors}件（各CSVに記録済み）", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main(parse_args()))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"実験を開始できません: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
