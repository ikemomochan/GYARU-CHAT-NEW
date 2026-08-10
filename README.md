# Mem0 + RAG Chat

Mem0による長期記憶と、ローカルfew-shot例のRAG検索を組み合わせた、最小構成のDM風チャットです。内容重視の下書き生成は `gpt-5.6-sol` と `claude-sonnet-5` を `.env` で切り替えられます。口調チェック、記憶、要約、EmbeddingはOpenAI APIを使います。

`MODE` で会話方式を切り替えられます。`simple` は `SIMPLE_CHAT_SYSTEM_PROMPT`、`prompt` は既存の `CHAT_SYSTEM_PROMPT` だけで会話し、どちらもRAG・Mem0・会話要約・口調補正を使いません。`Mem0` は以下のフル構成で動作します。

## 処理フロー

1. ユーザーの発言でMem0の長期記憶を検索
2. 同じ発言でギャル口調の言い換え一覧をEmbedding検索し、類似度上位5件を取得
3. `CHAT_SYSTEM_PROMPT` に記憶・会話要約・直近履歴を渡し、内容重視の下書きを生成
4. 出力チェック用プロンプトに下書きとfew-shot上位5件を渡し、意味を変えずギャル口調へ整形
5. 整形後の回答をユーザーへ返す
6. 会話から長期記憶候補をStructured Outputsで抽出
7. 既存記憶と照合し、ADD / UPDATE / DELETE / NONEを判定してMem0へ反映
8. 会話をSQLiteへ保存し、一定件数ごとにローリング要約を更新

Mem0検索とfew-shot検索は並列実行します。few-shot例のEmbeddingは `.data/few_shot_embeddings.json` にキャッシュされ、例またはEmbeddingモデルが変わった場合だけ再作成されます。

各回答の下にある「参照した口調例を見る」を開くと、口調整形に渡した5件について、例ID・標準表現・ギャル表現・コサイン類似度を確認できます。この参照情報はブラウザの会話履歴にも保存されます。

## セットアップ

Python 3.11以降を推奨します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`MODE=Mem0` を使う場合は `.env` の `OPENAI_API_KEY` を設定します。OpenAIを下書き生成にも使う場合は次の設定です。

```dotenv
OPENAI_API_KEY=sk-...
BASE_MODEL_PROVIDER=openai
BASE_MODEL=gpt-5.6-sol
OPENAI_MEMORY_MODEL=gpt-5.6-luna
```

下書き生成をClaude Sonnet 5へ切り替える場合は、次の3行を設定してサーバーを再起動します。

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
BASE_MODEL_PROVIDER=anthropic
BASE_MODEL=claude-sonnet-5
```

`MODE=Mem0` でClaudeを選択した場合も、後段の口調チェック、Mem0、会話要約、RAG Embeddingに使うため `OPENAI_API_KEY` は必要です。`simple` / `prompt` でClaudeを使う場合は `ANTHROPIC_API_KEY` だけで動作します。

起動:

```powershell
uvicorn app.main:app --reload
```

ブラウザで <http://127.0.0.1:8000> を開きます。

## 再起動時のリセット

`RESET_STATE_ON_START=true` により、サーバープロセスを起動するたびに以下を削除します。

- Mem0の長期記憶と変更履歴
- SQLiteに保存した会話メッセージとローリング要約
- ブラウザに残っている前回プロセスの表示履歴

ギャル口調のJSONL原本とfew-shot Embeddingキャッシュは削除しません。`uvicorn --reload` はソース変更のたびにプロセスを再起動するため、そのたびに会話状態もリセットされます。

## 主なファイル

- `app/prompts.py`: 下書き生成、口調チェック、記憶抽出、記憶照合、会話要約の全プロンプト
- `app/memory.py`: Mem0 OSS + ローカルQdrantとADD / UPDATE / DELETE処理
- `app/conversation.py`: 会話履歴とローリング要約のSQLite永続化
- `app/rag.py`: few-shot例のEmbedding、キャッシュ、コサイン類似度検索
- `app/base_model.py`: OpenAI / Anthropicの下書き生成API切替
- `app/chat.py`: 検索と最終応答のオーケストレーション
- `data/gyaru_rag_documents.jsonl`: 標準表現からギャル口調への言い換え一覧
- `app/static/`: DM風UI

Mem0 V3の標準抽出はADD-onlyですが、このアプリでは旧方式に近い整合性管理をアプリ側で実装しています。抽出・照合はOpenAI Responses APIで行い、確定した操作だけをMem0の `add(infer=False)` / `update()` / `delete()` へ渡します。これにより、アプリが使うプロンプトはすべて `app/prompts.py` で管理できます。

## 設定

すべて `.env` で変更できます。

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `MODE` | `Mem0` | 会話方式（`simple` / `prompt` / `Mem0`） |
| `BASE_MODEL_PROVIDER` | `openai` | 下書き生成プロバイダー（`openai` / `anthropic`） |
| `BASE_MODEL` | `gpt-5.6-sol` | 内容重視の下書き生成モデル |
| `OPENAI_API_KEY` | なし | OpenAI使用時に必要。`Mem0` では生成プロバイダーにかかわらず必須 |
| `ANTHROPIC_API_KEY` | なし | Claudeを選ぶ場合のAnthropic APIキー |
| `OPENAI_STYLE_MODEL` | `gpt-5.6-luna` | few-shot照合・口調整形モデル |
| `OPENAI_MEMORY_MODEL` | `gpt-5.6-luna` | Mem0の記憶抽出モデル |
| `OPENAI_SUMMARY_MODEL` | `gpt-5.6-luna` | ローリング会話要約モデル |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Mem0とRAGのEmbedding |
| `OPENAI_REASONING_EFFORT` | `low` | 最終応答のreasoning effort |
| `RAG_TOP_K` | `5` | 毎回取得するギャル口調の言い換え例数 |
| `MEMORY_TOP_K` | `5` | 取得する長期記憶件数 |
| `CHAT_HISTORY_LIMIT` | `12` | 最終応答へ渡す直近メッセージ数 |
| `SUMMARY_TRIGGER_MESSAGES` | `12` | 会話要約を更新する未要約メッセージ数 |
| `MAX_OUTPUT_TOKENS` | `1000` | 応答の最大出力トークン |
| `RESET_STATE_ON_START` | `true` | 起動時に長期記憶・会話履歴・要約を削除 |

## テスト

```powershell
pytest
```

テストではOpenAI APIを呼びません。実APIを使った確認はキー設定後、ブラウザから行ってください。
