from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.chat import ChatService
from app.config import PROJECT_ROOT, Settings, get_settings
from app.core.llm import (
    LanguageModelConnectionError,
    LanguageModelRateLimitError,
    LanguageModelTimeoutError,
)
from app.core.session_state import DialogueStrategy, SafetyLevel
from app.dialogue_prompts.response_prompt import (
    COMMON_RESPONSE_PROMPT,
    RESPONSE_SYSTEM_PROMPT,
    SAFETY_RESPONSE_PROMPTS,
    STRATEGY_RESPONSE_PROMPTS,
)
from app.dialogue_prompts.strategy_prompt import STRATEGY_SYSTEM_PROMPT
from app.schemas import ChatMessage, ChatRequest, ChatResponse


EXPECTED_INPUT_COUNT = 10
DEFAULT_ROUNDS = 10
DEFAULT_INPUTS_PATH = (
    PROJECT_ROOT / "data" / "prompt_ablation" / "user_inputs.json"
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".data" / "prompt_ablation_runs"


class AblationService(Protocol):
    async def reply(self, request: ChatRequest) -> ChatResponse: ...

    def reset_session(self, user_id: str, conversation_id: str) -> None: ...


def load_user_inputs(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"入力ファイルが見つかりません: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"入力ファイルが正しいJSONではありません: {path}") from exc

    messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(messages, list):
        raise ValueError("入力JSONには messages 配列を指定してください。")
    if len(messages) != EXPECTED_INPUT_COUNT:
        raise ValueError(
            f"固定入力はちょうど{EXPECTED_INPUT_COUNT}件必要です。"
            f"現在は{len(messages)}件です。"
        )

    normalized: list[str] = []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"固定入力の{index}件目が空です。内容を設定してください。")
        normalized.append(message.strip())
    return normalized


def create_run_directory(
    output_root: Path,
    started_at: datetime,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    base_name = started_at.strftime("%Y%m%d-%H%M%S")
    candidate = output_root / base_name
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{base_name}-{suffix:02d}"
        suffix += 1
    candidate.mkdir()
    return candidate


def write_prompt_snapshots(run_directory: Path) -> None:
    text_snapshots = {
        "response_system_prompt.txt": RESPONSE_SYSTEM_PROMPT,
        "common_response_prompt.txt": COMMON_RESPONSE_PROMPT,
        "strategy_selector_prompt.txt": STRATEGY_SYSTEM_PROMPT,
    }
    for filename, prompt in text_snapshots.items():
        (run_directory / filename).write_text(prompt, encoding="utf-8")

    _write_json(
        run_directory / "strategy_response_prompts.json",
        {
            strategy.value: prompt
            for strategy, prompt in STRATEGY_RESPONSE_PROMPTS.items()
        },
    )
    _write_json(
        run_directory / "safety_response_prompts.json",
        {
            safety_level.value: prompt
            for safety_level, prompt in SAFETY_RESPONSE_PROMPTS.items()
        },
    )


async def run_ablation(
    service: AblationService,
    settings: Settings,
    messages: Sequence[str],
    run_directory: Path,
    *,
    rounds: int = DEFAULT_ROUNDS,
    input_source: Path | None = None,
    progress: Callable[[str], None] | None = print,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> int:
    if len(messages) != EXPECTED_INPUT_COUNT:
        raise ValueError(f"固定入力はちょうど{EXPECTED_INPUT_COUNT}件必要です。")
    if rounds < 1:
        raise ValueError("周回数は1以上にしてください。")

    run_id = run_directory.name
    user_id = f"ablation-{uuid.uuid4().hex}"
    started_at = clock()
    completed_responses = 0
    normalized_inputs = list(messages)
    input_json = json.dumps(
        normalized_inputs,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "rounds": rounds,
        "turns_per_round": len(normalized_inputs),
        "expected_responses": rounds * len(normalized_inputs),
        "completed_responses": 0,
        "history_limit": settings.chat_history_limit,
        "input_source": str(input_source) if input_source else None,
        "input_sha256": hashlib.sha256(input_json.encode("utf-8")).hexdigest(),
        "models": {
            "strategy": settings.strategy_model,
            "response": settings.response_model,
        },
        "pipeline": {
            "rag": False,
            "external_advice_context": False,
            "tone_correction": False,
            "response_max_output_tokens": None,
        },
        "reasoning_effort": settings.reasoning_effort,
        "strategy_max_output_tokens": min(settings.max_output_tokens, 800),
    }
    _write_json(run_directory / "run_metadata.json", metadata)
    _write_json(
        run_directory / "user_inputs.json",
        {"messages": normalized_inputs},
    )
    write_prompt_snapshots(run_directory)

    try:
        for round_number in range(1, rounds + 1):
            conversation_id = f"{run_id}-round-{round_number:02d}"
            history: list[ChatMessage] = []
            try:
                for turn_number, user_message in enumerate(
                    normalized_inputs,
                    start=1,
                ):
                    history_before = [message.model_dump() for message in history]
                    request_started_at = clock()
                    response = await service.reply(
                        ChatRequest(
                            message=user_message,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            history=history,
                        )
                    )
                    response_completed_at = clock()
                    completed_responses += 1

                    record = {
                        "run_id": run_id,
                        "round": round_number,
                        "turn": turn_number,
                        "conversation_id": conversation_id,
                        "request_started_at": request_started_at.isoformat(),
                        "response_completed_at": response_completed_at.isoformat(),
                        "history_before": history_before,
                        "user_message": user_message,
                        "assistant_response": response.reply,
                        "selected_strategy": response.strategy,
                        "strategy_reason": response.strategy_reason,
                        "safety_level": response.safety_level,
                        "retrieved_examples": response.retrieved_examples,
                        "retrieved_principles": response.retrieved_principles,
                        "warnings": response.warnings,
                    }
                    _append_jsonl(run_directory / "conversations.jsonl", record)
                    _append_jsonl(
                        run_directory / "responses.jsonl",
                        {
                            "round": round_number,
                            "turn": turn_number,
                            "response": response.reply,
                            "selected_strategy": response.strategy,
                        },
                    )

                    history.extend(
                        [
                            ChatMessage(role="user", content=user_message),
                            ChatMessage(role="assistant", content=response.reply),
                        ]
                    )
                    history = history[-settings.chat_history_limit :]

                    if progress:
                        progress(
                            f"[{round_number:02d}/{rounds:02d}]"
                            f"[{turn_number:02d}/{len(normalized_inputs):02d}] "
                            f"{response.strategy or 'UNKNOWN'}: {response.reply}"
                        )
            finally:
                service.reset_session(user_id, conversation_id)
    except BaseException as exc:
        failed_at = clock()
        metadata.update(
            {
                "status": "failed",
                "completed_at": failed_at.isoformat(),
                "completed_responses": completed_responses,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        )
        _write_json(run_directory / "run_metadata.json", metadata)
        _append_jsonl(
            run_directory / "errors.jsonl",
            {
                "occurred_at": failed_at.isoformat(),
                "completed_responses": completed_responses,
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise

    metadata.update(
        {
            "status": "completed",
            "completed_at": clock().isoformat(),
            "completed_responses": completed_responses,
        }
    )
    _write_json(run_directory / "run_metadata.json", metadata)
    return completed_responses


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        output.write("\n")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("1以上の整数を指定してください。")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="固定された10ターンを繰り返すプロンプト・アブレーション実験",
    )
    parser.add_argument(
        "--inputs",
        type=Path,
        default=DEFAULT_INPUTS_PATH,
        help=f"固定入力JSON（既定: {DEFAULT_INPUTS_PATH}）",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"実験結果の保存先（既定: {DEFAULT_OUTPUT_ROOT}）",
    )
    parser.add_argument(
        "--rounds",
        type=_positive_int,
        default=DEFAULT_ROUNDS,
        help=f"周回数（既定: {DEFAULT_ROUNDS}）",
    )
    return parser


async def _run_cli(args: argparse.Namespace, settings: Settings) -> Path:
    messages = load_user_inputs(args.inputs)
    started_at = datetime.now().astimezone()
    run_directory = create_run_directory(args.output_root, started_at)
    print(
        f"{len(messages)}ターン × {args.rounds}周 = "
        f"{len(messages) * args.rounds}応答を実行します。"
    )
    print(f"保存先: {run_directory}")

    service = ChatService(settings)
    try:
        count = await run_ablation(
            service,
            settings,
            messages,
            run_directory,
            rounds=args.rounds,
            input_source=args.inputs.resolve(),
        )
    finally:
        service.close()
    print(f"完了: {count}応答を保存しました。")
    return run_directory


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    if not settings.api_key_configured:
        print(
            "エラー: .env に OPENAI_API_KEY を設定してください。",
            file=sys.stderr,
        )
        return 1

    try:
        asyncio.run(_run_cli(args, settings))
    except ValueError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except LanguageModelRateLimitError:
        print(
            "エラー: OpenAIのレート制限に達しました。部分ログは保存済みです。",
            file=sys.stderr,
        )
        return 1
    except LanguageModelTimeoutError:
        print(
            "エラー: 応答がタイムアウトしました。部分ログは保存済みです。",
            file=sys.stderr,
        )
        return 1
    except LanguageModelConnectionError:
        print(
            "エラー: OpenAIに接続できませんでした。部分ログは保存済みです。",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\n中断しました。部分ログは保存済みです。", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
