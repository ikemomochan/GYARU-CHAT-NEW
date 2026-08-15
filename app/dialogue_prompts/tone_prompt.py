from __future__ import annotations

import json
from typing import Any, Sequence

from app.core.llm import ModelMessage
from app.core.session_state import DialogueStrategy, SafetyLevel


TONE_SYSTEM_PROMPT = """\
あなたは「りりめろ」の口調編集者。下書きの意味を変えず、Few-shot例から話し方だけを参考にして、自然なギャル口調へ整える。

- 新しい事実、解釈、感情、経験、助言、質問を足さない。内容を削らない。
- 下書きの肯定・否定、提案内容、質問の対象と抽象度を変えない。LISTENの質問を具体化しない。
- 戦略を変更しない。下書きが質問していなければ質問を作らず、質問が一つなら増やさない。
- Few-shot例の人物・出来事・意見はコピーしない。口調、語尾、テンポだけを参考にする。
- AIが人間と同じ経験をしたような「分かる」「あるある」「あーしも」「うちも」は追加しない。
- 明確な倫理上の境界や緊急時の安全案内は、軽くしたり削ったりしない。
- 原則45文字以内。緊急時など、意味の保持に必要なら超えてよい。返答本文だけを出力する。
- 内容を保ったまま口調だけを直せない場合は、下書きをそのまま返す。
"""


def build_tone_input(
    *,
    history: Sequence[ModelMessage],
    latest_message: str,
    draft: str,
    strategy: DialogueStrategy,
    safety_level: SafetyLevel,
    examples: Sequence[dict[str, Any]],
) -> str:
    compact_examples = [
        {
            "standard": str(example["input"]),
            "gyaru": str(example["output"]),
        }
        for example in examples
        if "input" in example and "output" in example
    ]
    return json.dumps(
        {
            "recent_conversation": list(history[-4:]),
            "latest_user_message": latest_message,
            "strategy": strategy.value,
            "safety_level": safety_level.value,
            "draft": draft,
            "few_shot_examples": compact_examples,
        },
        ensure_ascii=False,
    )
