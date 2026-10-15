from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence

from app.chat import ChatService
from app.config import Settings, get_settings
from app.core.llm import (
    LanguageModelConnectionError,
    LanguageModelRateLimitError,
    LanguageModelTimeoutError,
)
from app.schemas import ChatMessage, ChatRequest


EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit"}


class ConsoleSession:
    """Keep the conversation state and recent history for a console session."""

    def __init__(self, service: ChatService, settings: Settings) -> None:
        self.service = service
        self.history_limit = settings.chat_history_limit
        self.user_id = f"console-{uuid.uuid4().hex}"
        self.conversation_id = uuid.uuid4().hex
        self.history: list[ChatMessage] = []

    async def reply(self, message: str) -> str:
        response = await self.service.reply(
            ChatRequest(
                message=message,
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                history=self.history,
            )
        )
        self.history.extend(
            [
                ChatMessage(role="user", content=message),
                ChatMessage(role="assistant", content=response.reply),
            ]
        )
        self.history = self.history[-self.history_limit :]
        return response.reply

    def reset(self) -> None:
        self.service.reset_session(self.user_id, self.conversation_id)
        self.conversation_id = uuid.uuid4().hex
        self.history.clear()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="りりめろをUIなしでコンソールから試します。",
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="指定すると1回だけ応答し、省略すると対話モードで起動します。",
    )
    return parser


async def _interactive(session: ConsoleSession) -> None:
    print("りりめろ コンソール（終了: /exit、会話リセット: /reset）")
    while True:
        try:
            message = input("あなた > ").strip()
        except EOFError:
            print()
            return

        if not message:
            continue
        if message.lower() in EXIT_COMMANDS:
            return
        if message.lower() == "/reset":
            session.reset()
            print("会話をリセットしました。")
            continue

        reply = await session.reply(message)
        print(f"りりめろ > {reply}\n")


async def _run(args: argparse.Namespace, settings: Settings) -> None:
    service = ChatService(settings)
    session = ConsoleSession(service, settings)
    try:
        if args.message:
            print(await session.reply(" ".join(args.message)))
        else:
            await _interactive(session)
    finally:
        service.close()


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
        asyncio.run(_run(args, settings))
    except KeyboardInterrupt:
        print()
    except LanguageModelRateLimitError:
        print(
            "エラー: OpenAIが混み合っています。少し待って再試行してください。",
            file=sys.stderr,
        )
        return 1
    except LanguageModelTimeoutError:
        print("エラー: 応答がタイムアウトしました。再試行してください。", file=sys.stderr)
        return 1
    except LanguageModelConnectionError:
        print("エラー: OpenAIに接続できませんでした。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
