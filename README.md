# りりめろ Dialogue Chat

「りりめろ」は、ユーザーの代わりにタスクを完成させるのではなく、話を聞き、必要なことだけを尋ね、状況が十分に分かったときにギャルの価値観から率直な視点を返す対話AIです。

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
Principle RAG（ADVICE / SYMPATHYのみ、任意参考）
        ↓
Response Generator
        ↓
Few-shot Tone Corrector
```

Strategy Selectorは毎ターン構造化出力で戦略を一つ選びます。Response Generatorは選ばれた戦略に従って返答内容を生成し、最後にTone CorrectorがFew-shot例を参照して口調だけを整えます。Selectorの判断理由はSession Stateとサーバーログにだけ残り、ユーザーには表示されません。

### 戦略

- `LISTEN`: 軽く共感し、状況を理解するための広い質問を一つだけ行う。最大5回連続
- `ADVICE`: 状況を十分理解したら、率直な助言や行動の提案を一つ返す
- `SYMPATHY`: 状況を十分理解したら、共感しつつ前向きな別視点を一つ返す

明確な加害行為はどの戦略でも正当化しません。生命・身体の危険など緊急性が高い場合は、安全確保と警察・救急・医療機関等への相談を通常の会話より優先します。

`ANSWER` や `TASK` はありません。成果物の代行を標準動作にせず、Listen / Think with the user / Give a perspectiveに役割を限定しています。

## Session State

現行手法条件の状態は、サーバープロセス内のメモリにユーザーIDと会話IDの組み合わせごとに保持されます。

```json
{
  "topic": "",
  "known_context": "",
  "user_need": "",
  "strategy_history": [],
  "perspective_ready": false
}
```

実験中にモデルへ渡す履歴は、ブラウザから受け取った内容を信用せず、サーバーが現在の実験IDと条件から組み立てます。Session Stateは長期記憶ではなく、実験条件ごとに異なる会話IDを使います。

## Mem0とRAG

現在の返信経路ではMem0とSQLiteローリング要約を使用しません。旧実装と単体テストは、既存機能を不用意に削除しないためリポジトリ内に残しています。

RAGは用途別に分かれています。

- 口調補正: 全戦略で `data/gyaru_rag_documents.jsonl` のFew-shot例を検索し、内容ではなく話し方だけを参照
- ギャル原則: `ADVICE` と `SYMPATHY` のときだけ `data/gyaru_principles_rag.jsonl` を検索し、役立つ場合だけ任意参考としてGeneratorへ渡す

原則RAGファイルは空でも正常に動作します。追加時は1行1JSONで、`{"id":"...", "text":"..."}`、または `title`、`principle`、`caution`、`quotes` を持つ形式を使います。絶対に守る原則はRAGだけに置かず、Response System Promptと `GYARU_PRINCIPLES` に保持しています。

## LLMプロバイダー

SelectorとGeneratorは `LanguageModel` Protocolだけに依存します。現在はOpenAIアダプターを実装しています。将来Qwen、Gemma、Swallowなどを使う場合は、同じProtocolを実装するアダプターを `app/providers/` に追加します。fine-tuningは前提としていません。

## 実験システム設計

同じ参加者が、単純なプロンプトだけの条件と現行手法の条件を順番に体験する、2フェーズの比較実験です。注意書き画面と入力回数制限は使用しません。

```text
WAITING
  │ 最初のメッセージを送信
  ▼
SIMPLE（7分）
  │ 時間終了
  ▼
TRANSITION（入力停止）
  │ 「後半を始める」
  │ UI履歴・モデル履歴を初期化
  ▼
FULL（7分）
  │ 時間終了
  ▼
COMPLETE（入力停止）
```

タイマーはブラウザではなくサーバー時刻を正とします。画面は `/api/experiment/status` を定期的に取得して残り時間と状態を表示します。前半のタイマーは最初のメッセージをサーバーが受け付けた時点、後半は参加者が「後半を始める」を押した時点から開始します。前半終了後の遷移画面に時間制限はありません。

### 実験条件

| 条件 | System Prompt | 使用する処理 |
| --- | --- | --- |
| `SIMPLE` | `あなたはギャルです` の1文だけ | 通常の会話履歴と1回の応答生成のみ。Strategy Selector、原則RAG、口調補正は使わない |
| `FULL` | 現行のりりめろ用Prompt | Session State、Strategy Selector、Gyaru Principles、必要時の原則RAG、Response Generator、Few-shot Tone Correctorを使う |

現在は全参加者が `SIMPLE` → `FULL` の固定順です。比較実験として使う場合は、順序効果を避けるため条件順を参加者ごとに入れ替える設計も検討してください。

### 会話履歴と研究ログの分離

会話履歴には二つの用途があり、別々に扱います。

- モデル用履歴: 現在の条件の発話だけを取得する。`FULL` 開始時には空になり、`SIMPLE` の発話は一切渡さない
- 研究ログ: 条件を切り替えても削除せず、実装者が後からCSVで確認できるように保存する

ブラウザ側も条件切替時に表示履歴を消し、新しい会話IDを発行します。サーバー側では条件ごとに履歴を検索し、異なる会話IDでSession Stateを管理するため、ブラウザを改変して古い履歴を送っても後半条件には混ざりません。

### 識別・保存データ

初回アクセス時にランダムな匿名端末IDを作り、署名付きHttpOnly Cookieへ保存します。名前やIPアドレスは研究ログへ保存しません。

SQLiteの `experiments` テーブルには、実験ID、匿名端末ID、作成時刻、各条件の開始時刻を保存します。`experiment_messages` テーブルには、条件、話者、発話本文、記録時刻と次のメタデータを保存します。

- 実験条件名
- 選択Strategyと内部の選択理由
- Safety判定
- Few-shot例と原則RAGの取得件数
- 応答生成時の警告

初期保存先は `.data/experiment_logs.db` です。モデル用履歴を消しても、この研究ログは残ります。

### 実験API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/experiment/status` | 現在のフェーズと残り秒数を取得 |
| `POST` | `/api/chat` | 現在の条件で応答し、成功した対話を記録 |
| `POST` | `/api/experiment/advance` | `TRANSITION` から `FULL` へ進む |
| `GET` | `/api/experiment/admin/export` | 全実験ログをCSVで取得。管理コード必須 |
| `POST` | `/api/experiment/admin/reset-current` | 現在の端末の実験とログを削除してやり直す。管理コード必須 |

管理APIは `X-Admin-Code` ヘッダーを使い、`.env` の `EXPERIMENT_ADMIN_CODE` と一致した場合だけ実行されます。

## セットアップ

Python 3.11以降を推奨します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

作成した `.env` を開き、最低限 `OPENAI_API_KEY` を設定します。ローカルでCSV出力や実験リセットも試す場合は、任意の長い管理コードも設定します。

```dotenv
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
STRATEGY_MODEL=gpt-5.6-luna
RESPONSE_MODEL=gpt-5.6-luna
TONE_MODEL=gpt-5.6-luna
EXPERIMENT_PHASE_SECONDS=420
EXPERIMENT_ADMIN_CODE=ローカル用の管理コード
```

### ローカル起動

リポジトリのルートで次を実行します。

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

ブラウザで <http://127.0.0.1:8000> を開きます。

動作確認だけ短時間で行いたい場合は、`.env` の `EXPERIMENT_PHASE_SECONDS=30` などに変更してサーバーを再起動します。

ローカルの実験ログをCSVへ書き出すコマンド:

```powershell
$headers = @{ "X-Admin-Code" = "ローカル用の管理コード" }
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/experiment/admin/export" `
  -Headers $headers `
  -OutFile "ririmero-experiment.csv"
```

現在のブラウザで実験を最初からやり直すコマンド:

```powershell
$headers = @{ "X-Admin-Code" = "ローカル用の管理コード" }
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/experiment/admin/reset-current" `
  -Headers $headers
```

### スマートフォンから開く

PCとスマートフォンを同じWi-Fiへ接続し、PowerShellで次を実行します。

```powershell
.\scripts\setup_mobile_access.ps1
.\scripts\start_mobile.ps1
```

初回だけ `setup_mobile_access.ps1` を実行します。Windowsの管理者確認後、信頼できるWi-Fiであることを確認して`y`を入力すると、TCP 8000をプライベートネットワークのローカルサブネットだけに許可します。

続いて `start_mobile.ps1` を実行し、表示される `スマホ: http://192.168.x.x:8000` をスマートフォンのブラウザで開きます。IPアドレスはWi-Fiへ接続し直すと変わることがあります。

接続できない場合は、Windowsのネットワーク設定で信頼できる自宅Wi-Fiのプロファイルが「プライベート」になっているか確認し、Windows Defenderファイアウォールの確認画面ではプライベートネットワーク上のPythonを許可します。公共Wi-Fiでは公開しないでください。

### PCで起動している間だけインターネット公開する

現在のUI、Cookie、7分タイマー、実験APIをそのまま使うため、GradioへのUI移植ではなくCloudflare Quick Tunnelを使います。ローカルのFastAPIへ一時的なHTTPS URLをつなぐ方式で、Cloudflareアカウントや独自ドメインは不要です。

初回だけ、PowerShellでCloudflare公式配布の `cloudflared.exe` を `.tools/` へ取得します。システム全体へのインストールや管理者権限は不要です。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_public_access.ps1
```

次の1コマンドでローカルサーバーと公開トンネルを起動します。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_public.ps1
```

ターミナルに表示された `https://...trycloudflare.com` を参加者へ共有します。URL発行直後はDNS反映に少し時間がかかる場合があるため、開けないときは10〜30秒待ってから再読み込みしてください。`Ctrl+C` を押すかPCを停止すると公開も終了します。スクリプト実行前からローカルサーバーが動いていた場合、そのサーバーは終了しません。

Quick TunnelのURLは起動ごとに変わり、URLを知っている人はアクセスできます。管理コードは共有しないでください。この方式は短時間の実験・デモ向けで、安定運用や固定URLが必要な場合はRenderまたは認証付きのNamed Tunnelを使います。

## Renderへ公開する

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fikemomochan%2FGYARU-CHAT-NEW%2Ftree%2FEXP01-system)

1. 上のボタンからRenderへサインインします。
2. Blueprint作成画面で `OPENAI_API_KEY` を入力します。キーはGitHubへコミットしません。
3. Blueprintを適用し、デプロイ完了後に表示される `onrender.com` URLを共有します。

`render.yaml` はSingaporeリージョンのFree Web Service、`EXP01-system`ブランチの自動デプロイ、`/api/health`のヘルスチェックを設定します。本番ビルドでは `requirements-render.txt` を使い、現在の実行経路で不要なMem0依存をインストールしません。

公開URLではIPとブラウザ内IDの組み合わせごとに、60秒間に12メッセージまでに制限しています。値はRenderの `CHAT_RATE_LIMIT` と `CHAT_RATE_WINDOW_SECONDS` で変更できます。公開専用のOpenAI Project API keyを作り、Project Limitsで利用額とモデル別レート制限も設定してください。

Free Web Serviceは無通信時にスリープするため、最初のアクセスに時間がかかる場合があります。またSession Stateはプロセス内だけにあるため、スリープ、再起動、再デプロイで消えます。

### 実験ログの取得

RenderのEnvironment画面で `EXPERIMENT_ADMIN_CODE` をSecretとして設定してください。`EXPERIMENT_DEVICE_SECRET` はBlueprintが自動生成します。ログは次のようにCSVで取得できます。

```powershell
$headers = @{ "X-Admin-Code" = "設定した管理コード" }
Invoke-WebRequest `
  -Uri "https://あなたのサービス.onrender.com/api/experiment/admin/export" `
  -Headers $headers `
  -OutFile "ririmero-experiment.csv"
```

同じ端末で実装テストをやり直す場合は、管理コード付きで `/api/experiment/admin/reset-current` へPOSTします。SQLiteはRenderの再デプロイ等で消える可能性があるため、この構成はパイロット実験用です。本番の研究データ収集前に外部の永続データベースへ移し、参加者同意・保存期間・削除手順を別途定めてください。

```powershell
$headers = @{ "X-Admin-Code" = "設定した管理コード" }
Invoke-RestMethod `
  -Method Post `
  -Uri "https://あなたのサービス.onrender.com/api/experiment/admin/reset-current" `
  -Headers $headers
```

## 主なファイル

- `app/gyaru_principles.py`: SelectorとGeneratorが共有する差し替え可能な価値観
- `app/dialogue_prompts/strategy_prompt.py`: 戦略選択用プロンプトと入力構築
- `app/dialogue_prompts/response_prompt.py`: 短い応答System Promptと入力構築
- `app/core/session_state.py`: Session State、構造化戦略、プロセス内ストア
- `app/core/strategy_selector.py`: LISTEN / ADVICE / SYMPATHYの選択と連続LISTEN上限
- `app/core/response_generator.py`: 選択済み戦略に従う応答生成
- `app/core/tone_corrector.py`: Few-shot例を使い、内容を変えずに口調を補正
- `app/core/llm.py`: プロバイダー非依存のLLM Protocol
- `app/core/retrieval.py`: 原則RAGとFew-shot検索のプロバイダー非依存インターフェース
- `app/core/experiment.py`: 2フェーズのサーバー時間、条件別履歴、研究ログ、CSV出力
- `app/simple_chat.py`: 「あなたはギャルです」だけを使う前半条件
- `app/providers/openai_provider.py`: OpenAI Responses APIアダプター
- `app/providers/openai_retrieval.py`: OpenAI Embeddingsを使う2種類のRetriever
- `app/chat.py`: 新しい対話フローのオーケストレーション
- `app/rag.py`: 既存Few-shotの読み込み・Embedding検索（アダプター経由で口調補正に再利用）
- `app/memory.py`: 現在の返信経路では使わない旧Mem0実装
- `app/conversation.py`: 現在の返信経路では使わない旧要約実装
- `app/static/`: 既存DM風UI
- `scripts/setup_public_access.ps1`: 一時公開用Cloudflare Tunnelの初回セットアップ
- `scripts/start_public.ps1`: ローカルサーバーと一時公開URLの起動・終了

## 設定

| 変数 | 既定値 | 用途 |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | LLMアダプター名 |
| `STRATEGY_MODEL` | `OPENAI_CHAT_MODEL`の値 | Strategy Selectorのモデル |
| `RESPONSE_MODEL` | `OPENAI_CHAT_MODEL`の値 | Response Generatorのモデル |
| `TONE_MODEL` | `OPENAI_CHAT_MODEL`の値 | Tone Correctorのモデル |
| `STYLE_TOP_K` | `5` | 口調補正で参照するFew-shot例数 |
| `STYLE_EXAMPLES_PATH` | `data/gyaru_rag_documents.jsonl` | 口調Few-shotデータ |
| `PRINCIPLE_RAG_TOP_K` | `5` | ADVICE/SYMPATHYで参照する原則資料数 |
| `PRINCIPLE_RAG_PATH` | `data/gyaru_principles_rag.jsonl` | ギャル原則RAG資料 |
| `EXPERIMENT_PHASE_SECONDS` | `420` | SIMPLEとFULLそれぞれの制限時間（秒） |
| `EXPERIMENT_ADMIN_CODE` | なし | CSV出力と現在端末のリセットに使う管理コード |
| `EXPERIMENT_DEVICE_SECRET` | 未設定時はAPIキー等から導出 | 匿名端末Cookieの署名用Secret。本番では固定値を設定 |
| `EXPERIMENT_DB_PATH` | `.data/experiment_logs.db` | 実験状態と研究ログを保存するSQLiteファイル |
| `OPENAI_API_KEY` | なし | OpenAIアダプターのAPIキー |
| `OPENAI_REASONING_EFFORT` | `low` | OpenAIモデルのreasoning effort |
| `MAX_OUTPUT_TOKENS` | `1000` | 各モデル呼び出しの最大出力トークン |
| `RESET_STATE_ON_START` | `true` | 再起動時にブラウザ表示履歴を新セッションへ切り替える |

その他のMem0、要約、Embedding、旧RAG設定は互換性のため残っていますが、新しい返信経路では参照しません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest
```

テストでは実際のLLM APIを呼びません。
