# りりめろ Dialogue Chat

「りりめろ」は、話を聞き、必要なことだけを尋ね、状況が十分に分かったときにギャルの価値観から率直な視点を返す対話AIです。

`prompt_ab-20261015` ではPromptアブレーションのため、RAGと口調補正を一時的に無効化しています。成功した会話はローカルSQLiteへ保存します。

## 対話フロー

```text
Conversation History
        ↓
Session State
        ↓
Strategy Selector
        ↓
LISTEN / ADVICE / SYMPATHY
        ↓
Gyaru Principles
        ↓
Response Generator
```

現在の実験経路では、Few-shot RAG、ADVICE／SYMPATHY用の原則RAG、Tone Correctorを呼びません。Response Generatorの出力をそのまま最終回答にし、Responses APIへ明示的な `max_output_tokens` も送りません。Strategy Selectorの構造化出力には内部処理用の上限があります。

- `LISTEN`: 軽く共感し、状況を理解するための質問を一つ行う
- `ADVICE`: 状況を十分理解したら、率直な助言や行動の提案を返す
- `SYMPATHY`: 状況を十分理解したら、共感しつつ前向きな別視点を返す

生命・身体の危険など緊急性が高い場合は、安全確保と警察・救急・医療機関等への相談を通常の会話より優先します。

## 通常モードと会話履歴

- 時間制限と総メッセージ回数制限はありません
- 公開時の過剰利用を防ぐ短時間のレート制限はあります（初期値は60秒に12件）
- ブラウザの「新しい会話」で別の会話IDを発行できます
- 画面を新しい会話に切り替えても、以前のサーバーログは削除されません
- モデルへ渡す履歴は、匿名端末IDと会話IDを使ってサーバー側DBから取得します

初回アクセス時にランダムな匿名端末IDを作り、署名付きHttpOnly Cookieへ保存します。通常会話ログにはIPアドレスを保存しません。

保存先は `.data/chat_logs.db` です。次の情報を保存します。

- 匿名端末ID、ブラウザ側ユーザーIDのハッシュ、会話ID
- ユーザー発言とAI応答
- 会話・発言時刻
- Strategy、内部の選択理由、Safety判定
- RAG取得件数（現在は常に0）、応答生成時の警告

会話を収集する場合は、利用者へ保存目的・保存期間・閲覧者・削除方法を事前に案内してください。

## API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 稼働確認 |
| `GET` | `/api/config` | 公開設定の取得 |
| `POST` | `/api/chat` | RAG・口調補正なしの実験経路で応答し、成功した対話を保存 |
| `GET` | `/api/admin/export` | 通常会話ログをCSVで取得。管理コード必須 |
| `GET` | `/api/experiment/admin/export` | 旧 `.data/experiment_logs.db` をCSVで取得する互換API |

管理APIは `X-Admin-Code` ヘッダーを使い、`.env` の `CHAT_ADMIN_CODE` と一致した場合だけ実行されます。移行のため、`CHAT_ADMIN_CODE` が空なら旧 `EXPERIMENT_ADMIN_CODE` を使用します。

## セットアップ

Python 3.11以降を推奨します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` に最低限APIキーを設定します。CSVを取得する場合は長い管理コードも設定します。

```dotenv
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
STRATEGY_MODEL=gpt-6-luna
RESPONSE_MODEL=gpt-6-luna
TONE_MODEL=gpt-6-luna
CHAT_ADMIN_CODE=ローカル用の長い管理コード
CHAT_DEVICE_SECRET=ランダムな長い固定文字列
CHAT_LOG_DB_PATH=.data/chat_logs.db
```

既存の `.env` に `EXPERIMENT_ADMIN_CODE` と `EXPERIMENT_DEVICE_SECRET` が設定されている場合は、その値を引き続き利用できます。

## ローカル起動

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

ブラウザで <http://127.0.0.1:8000> を開きます。

## コンソールで試す

Web UIやサーバーを起動せず、現在の実験用対話経路を直接試せます。

```powershell
.\.venv\Scripts\python.exe -m app.console
```

`あなた >` に続けてメッセージを入力します。終了は `/exit`、会話を最初からやり直す場合は `/reset` を入力してください。このモードの会話はSQLiteへ保存しません。

1回だけ応答を確認する場合は、メッセージを引数で渡します。この場合、標準出力には応答だけが表示されます。

```powershell
.\.venv\Scripts\python.exe -m app.console "今日はちょっと疲れた"
```

## プロンプト・アブレーション実験

`data/prompt_ablation/user_inputs.json` の `messages` に、1会話として順番に送る固定入力を10件設定します。空欄や10件以外の場合はAPIを呼ばずに終了します。

```powershell
.\.venv\Scripts\python.exe -m app.ablation
```

1回の実行で10ターンを10周し、各周の開始時に会話履歴とSession Stateをリセットします。結果は `.data/prompt_ablation_runs/YYYYMMDD-HHMMSS/` に保存されます。

1応答につきStrategy SelectorとResponse Generatorの2回GPTを呼ぶため、100応答では通常約200回のGPT呼び出しが発生します。RAG用Embeddingは呼びません。連続LISTENの補正時はStrategy Selectorが追加で呼ばれる場合があります。

- `conversations.jsonl`: 全100ターンの入力、応答、送信時の履歴、選択戦略、選択理由、安全判定
- `responses.jsonl`: Distinct-Nなどの集計に使いやすい応答と選択戦略
- `run_metadata.json`: 使用モデル、無効化した処理、周回数、完了件数、実行状態
- `user_inputs.json`: 実行時に使った固定入力のコピー
- `response_system_prompt.txt` / `common_response_prompt.txt`: Response Promptのスナップショット
- `strategy_response_prompts.json`: LISTEN / ADVICE / SYMPATHY別Prompt
- `strategy_selector_prompt.txt`: 戦略選択Prompt
- `safety_response_prompts.json`: Safety Level別の追加Prompt

動作確認などで周回数だけ変える場合は `--rounds` を指定できます。

```powershell
.\.venv\Scripts\python.exe -m app.ablation --rounds 1
```

### 通常会話ログのCSV出力

```powershell
$headers = @{ "X-Admin-Code" = "ローカル用の長い管理コード" }
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/admin/export" `
  -Headers $headers `
  -OutFile "ririmero-chat.csv"
```

Excelで開けるUTF-8 BOM付きCSVです。`conversation_id` ごとに会話をまとめ、`role` と `content` で発言者と内容を確認できます。

## ローカルPCから一時公開する

Cloudflare Quick Tunnelで、ローカルのFastAPIへ一時的なHTTPS URLをつなぎます。Cloudflareアカウントや独自ドメインは不要です。

初回だけ次を実行します。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_public_access.ps1
```

公開を開始します。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_public.ps1
```

ターミナルに表示される `https://...trycloudflare.com` を利用者へ共有します。会話ログは公開URL側ではなく、このPCの `.data/chat_logs.db` に保存されます。

- 公開中はPCとターミナルを起動したままにしてください
- `Ctrl+C` でトンネルと、このスクリプトが起動したローカルサーバーを終了します
- URLは起動ごとに変わります
- URLを知る人はアクセスできるため、管理コードは共有しないでください
- 公共Wi-Fiでは公開しないでください

## 旧実験ログの取得

以前の実験版で収集した `.data/experiment_logs.db` は削除しません。通常版の管理コードで引き続きCSVにできます。

```powershell
$headers = @{ "X-Admin-Code" = "ローカル用の長い管理コード" }
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/experiment/admin/export" `
  -Headers $headers `
  -OutFile "ririmero-experiment.csv"
```

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 主なファイル

- `app/main.py`: FastAPI、無制限チャット、管理者CSV API
- `app/chat.py`: Strategy SelectorとResponse Generatorをつなぐ実験用対話サービス
- `app/console.py`: UIなしで試す対話型・ワンショットCLI
- `app/ablation.py`: 固定10ターンを10周するPrompt実験ランナー
- `app/core/chat_log.py`: 通常会話ログ、会話履歴取得、CSV出力
- `app/core/experiment.py`: 旧実験ログの互換出力
- `app/static/`: モバイル向け通常チャットUI
- `scripts/start_public.ps1`: ローカルサーバーと一時公開URLの起動・終了

## 主な環境変数

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `OPENAI_API_KEY` | なし | OpenAI APIキー |
| `STRATEGY_MODEL` | `gpt-6-luna` | Strategy Selector |
| `RESPONSE_MODEL` | `gpt-6-luna` | Response Generator |
| `TONE_MODEL` | `gpt-6-luna` | 現在の実験経路では未使用 |
| `MAX_OUTPUT_TOKENS` | `1000` | Strategy Selector等の内部処理用。最終応答には未指定 |
| `CHAT_RATE_LIMIT` | `12` | レート窓内の最大メッセージ数 |
| `CHAT_RATE_WINDOW_SECONDS` | `60` | レート制限の時間窓 |
| `CHAT_HISTORY_LIMIT` | `12` | モデルへ渡す直近履歴数 |
| `CHAT_ADMIN_CODE` | 旧管理コードへフォールバック | CSV出力用管理コード |
| `CHAT_DEVICE_SECRET` | 旧SecretまたはAPIキー等から導出 | 匿名端末Cookieの署名 |
| `CHAT_LOG_DB_PATH` | `.data/chat_logs.db` | 通常会話ログのSQLiteファイル |
| `EXPERIMENT_DB_PATH` | `.data/experiment_logs.db` | 旧実験ログのSQLiteファイル |
