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

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fikemomochan%2FGYARU-CHAT-NEW%2Ftree%2Fsystem_YANS)

1. 上のボタンからRenderへサインインします。
2. Blueprint作成画面で `OPENAI_API_KEY` を入力します。キーはGitHubへコミットしません。
3. Blueprintを適用し、デプロイ完了後に表示される `onrender.com` URLを共有します。

`render.yaml` はSingaporeリージョンのFree Web Service、`system_YANS`ブランチの自動デプロイ、`/api/health`のヘルスチェックを設定します。本番ビルドでは `requirements-render.txt` を使い、現在の実行経路で不要なMem0依存をインストールしません。

公開URLではIPとブラウザ内IDの組み合わせごとに、60秒間に12メッセージまでに制限しています。値はRenderの `CHAT_RATE_LIMIT` と `CHAT_RATE_WINDOW_SECONDS` で変更できます。公開専用のOpenAI Project API keyを作り、Project Limitsで利用額とモデル別レート制限も設定してください。

Free Web Serviceは無通信時にスリープするため、最初のアクセスに時間がかかる場合があります。またSession Stateはプロセス内だけにあるため、スリープ、再起動、再デプロイで消えます。

### 体験版の回数制限

- 通常利用は同じブラウザ端末につき10回です。`TRIAL_MESSAGE_LIMIT` で変更できます。
- 回数はHttpOnly Cookie、サーバー側SQLite、ブラウザ側の使用済み回数で管理するため、履歴を消したりサーバーを再起動したりしても、同じブラウザでは復活しません。
- 実装者はロック画面の「実装者はこちら」から `DEBUG_ACCESS_CODE` を入力すると、30日間の無制限モードになります。解除コードはフロントエンドへ配信しません。
- RenderのEnvironment画面で `DEBUG_ACCESS_CODE` をSecretとして設定してください。`TRIAL_SIGNING_SECRET` と `DEBUG_TOKEN_SECRET` はBlueprintが自動生成します。

名前は本人確認にならず、別名で回数制限を避けられるため、ロック判定には使用していません。Cookieやブラウザのサイトデータを完全に削除した場合、別ブラウザを使った場合まで同一端末と断定することはできません。そこまで厳密に制限する場合は、ログインと外部の永続データベースが必要です。RenderのローカルSQLiteは再デプロイなどで消える可能性があるため、長期運用時は外部DBへ移してください。

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
