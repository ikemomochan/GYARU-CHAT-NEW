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

状態はサーバープロセス内のメモリに、ユーザーIDと会話IDの組み合わせごとに保持されます。

```json
{
  "topic": "",
  "known_context": "",
  "user_need": "",
  "strategy_history": [],
  "perspective_ready": false
}
```

ブラウザが保持する会話履歴も毎ターンSelectorへ渡します。Session Stateは長期記憶ではなく、サーバー再起動またはUIの「履歴を消す」で破棄されます。

## Mem0とRAG

現在の返信経路ではMem0とSQLiteローリング要約を使用しません。旧実装と単体テストは、既存機能を不用意に削除しないためリポジトリ内に残しています。

RAGは用途別に分かれています。

- 口調補正: 全戦略で `data/gyaru_rag_documents.jsonl` のFew-shot例を検索し、内容ではなく話し方だけを参照
- ギャル原則: `ADVICE` と `SYMPATHY` のときだけ `data/gyaru_principles_rag.jsonl` を検索し、役立つ場合だけ任意参考としてGeneratorへ渡す

原則RAGファイルは空でも正常に動作します。追加時は1行1JSONで、`{"id":"...", "text":"..."}`、または `title`、`principle`、`caution`、`quotes` を持つ形式を使います。絶対に守る原則はRAGだけに置かず、Response System Promptと `GYARU_PRINCIPLES` に保持しています。

## LLMプロバイダー

SelectorとGeneratorは `LanguageModel` Protocolだけに依存します。現在はOpenAIアダプターを実装しています。将来Qwen、Gemma、Swallowなどを使う場合は、同じProtocolを実装するアダプターを `app/providers/` に追加します。fine-tuningは前提としていません。

## セットアップ

Python 3.11以降を推奨します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` を設定します。

```dotenv
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
STRATEGY_MODEL=gpt-5.6-luna
RESPONSE_MODEL=gpt-5.6-luna
TONE_MODEL=gpt-5.6-luna
```

起動:

```powershell
uvicorn app.main:app --reload
```

ブラウザで <http://127.0.0.1:8000> を開きます。

### スマートフォンから開く

PCとスマートフォンを同じWi-Fiへ接続し、PowerShellで次を実行します。

```powershell
.\scripts\setup_mobile_access.ps1
.\scripts\start_mobile.ps1
```

初回だけ `setup_mobile_access.ps1` を実行します。Windowsの管理者確認後、信頼できるWi-Fiであることを確認して`y`を入力すると、TCP 8000をプライベートネットワークのローカルサブネットだけに許可します。

続いて `start_mobile.ps1` を実行し、表示される `スマホ: http://192.168.x.x:8000` をスマートフォンのブラウザで開きます。IPアドレスはWi-Fiへ接続し直すと変わることがあります。

接続できない場合は、Windowsのネットワーク設定で信頼できる自宅Wi-Fiのプロファイルが「プライベート」になっているか確認し、Windows Defenderファイアウォールの確認画面ではプライベートネットワーク上のPythonを許可します。公共Wi-Fiでは公開しないでください。

## Renderへ公開する

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fikemomochan%2FGYARU-CHAT-NEW%2Ftree%2FEXP01-system)

1. 上のボタンからRenderへサインインします。
2. Blueprint作成画面で `OPENAI_API_KEY` を入力します。キーはGitHubへコミットしません。
3. Blueprintを適用し、デプロイ完了後に表示される `onrender.com` URLを共有します。

`render.yaml` はSingaporeリージョンのFree Web Service、`EXP01-system`ブランチの自動デプロイ、`/api/health`のヘルスチェックを設定します。本番ビルドでは `requirements-render.txt` を使い、現在の実行経路で不要なMem0依存をインストールしません。

公開URLではIPとブラウザ内IDの組み合わせごとに、60秒間に12メッセージまでに制限しています。値はRenderの `CHAT_RATE_LIMIT` と `CHAT_RATE_WINDOW_SECONDS` で変更できます。公開専用のOpenAI Project API keyを作り、Project Limitsで利用額とモデル別レート制限も設定してください。

Free Web Serviceは無通信時にスリープするため、最初のアクセスに時間がかかる場合があります。またSession Stateはプロセス内だけにあるため、スリープ、再起動、再デプロイで消えます。

### 2フェーズ対話実験

- 最初の送信から4分間は、System Promptが「あなたはギャルです」だけの単純条件です。
- 4分経過後は入力を停止し、参加者が「後半を始める」を押すまで待機します。
- 後半開始時に画面履歴とモデルへ渡す履歴を削除し、現在のStrategy / RAG / 口調補正を使う条件へ切り替えます。
- 後半も4分経過すると入力を停止し、実験を終了します。
- 各フェーズの時間は `EXPERIMENT_PHASE_SECONDS` で変更できます。既定値は240秒です。

現在は全参加者が単純条件→提案手法条件の固定順です。比較実験として使う場合は、順序効果を避けるため条件順を参加者ごとに入れ替える設計も検討してください。

モデルへ渡す会話履歴と研究ログは分離しています。切替時に会話履歴を削除しても、研究ログには `SIMPLE` / `FULL` の条件名、発話、Strategy、RAG件数などが残ります。IPアドレスや入力された名前は保存しません。

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
| `OPENAI_API_KEY` | なし | OpenAIアダプターのAPIキー |
| `OPENAI_REASONING_EFFORT` | `low` | OpenAIモデルのreasoning effort |
| `MAX_OUTPUT_TOKENS` | `1000` | 各モデル呼び出しの最大出力トークン |
| `RESET_STATE_ON_START` | `true` | 再起動時にブラウザ表示履歴を新セッションへ切り替える |

その他のMem0、要約、Embedding、旧RAG設定は互換性のため残っていますが、新しい返信経路では参照しません。

## テスト

```powershell
pytest
```

テストでは実際のLLM APIを呼びません。
