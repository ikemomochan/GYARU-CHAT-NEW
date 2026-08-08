const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messagesElement = document.querySelector("#messages");
const notice = document.querySelector("#notice");
const modelLabel = document.querySelector("#model-label");
const clearButton = document.querySelector("#clear-button");

const USER_KEY = "mem0-chat-user-id";
const CONVERSATION_KEY = "mem0-chat-conversation-id";
const HISTORY_KEY = "mem0-chat-history";
const RUNTIME_KEY = "mem0-chat-runtime-id";

const getOrCreateId = (key) => {
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID();
    localStorage.setItem(key, value);
  }
  return value;
};

const userId = getOrCreateId(USER_KEY);
let conversationId = getOrCreateId(CONVERSATION_KEY);
let history = loadHistory();
let waiting = false;

function loadHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(value) ? value.slice(-50) : [];
  } catch {
    return [];
  }
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-50)));
}

function addMessage(role, content, meta = "") {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  const body = document.createElement("div");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  body.appendChild(bubble);
  if (meta) {
    const metaElement = document.createElement("div");
    metaElement.className = "message-meta";
    metaElement.textContent = meta;
    body.appendChild(metaElement);
  }
  row.appendChild(body);
  messagesElement.appendChild(row);
  messagesElement.scrollTop = messagesElement.scrollHeight;
  return row;
}

function addTyping() {
  const row = document.createElement("div");
  row.className = "message-row assistant typing";
  row.innerHTML = '<div class="bubble"><span></span><span></span><span></span></div>';
  messagesElement.appendChild(row);
  messagesElement.scrollTop = messagesElement.scrollHeight;
  return row;
}

function showNotice(message) {
  notice.textContent = message;
  notice.classList.toggle("hidden", !message);
}

function setWaiting(value) {
  waiting = value;
  input.disabled = value;
  sendButton.disabled = value;
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("config request failed");
    const config = await response.json();
    syncRuntime(config);
    modelLabel.textContent = `${config.chat_model} · Mem0 + RAG`;
    if (!config.api_key_configured) {
      showNotice(".env の OPENAI_API_KEY を設定してからメッセージを送ってください。 ");
    }
  } catch {
    modelLabel.textContent = "サーバーに接続できません";
    showNotice("バックエンドとの接続を確認してください。");
  }
}

function syncRuntime(config) {
  const previousRuntime = localStorage.getItem(RUNTIME_KEY);
  if (
    config.reset_state_on_start &&
    previousRuntime !== config.runtime_id
  ) {
    history = [];
    saveHistory();
    conversationId = crypto.randomUUID();
    localStorage.setItem(CONVERSATION_KEY, conversationId);
    messagesElement.innerHTML = "";
    addMessage(
      "assistant",
      "サーバーを再起動したので、前回の会話と長期記憶をリセットしたよ。今日はどうした？",
    );
  }
  localStorage.setItem(RUNTIME_KEY, config.runtime_id);
}

for (const message of history) addMessage(message.role, message.content);
loadConfig();

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener("click", () => {
  history = [];
  saveHistory();
  conversationId = crypto.randomUUID();
  localStorage.setItem(CONVERSATION_KEY, conversationId);
  messagesElement.innerHTML = "";
  addMessage("assistant", "表示履歴をクリアしたよ。長期記憶はそのまま残ってるよ。");
  showNotice("");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || waiting) return;

  showNotice("");
  const requestHistory = history.slice(-12);
  addMessage("user", message);
  history.push({ role: "user", content: message });
  saveHistory();
  input.value = "";
  resizeInput();
  setWaiting(true);
  const typing = addTyping();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        user_id: userId,
        conversation_id: conversationId,
        history: requestHistory,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "応答に失敗しました。");
    }
    const meta = `記憶 ${data.recalled_memories}件 · 例 ${data.retrieved_examples}件`;
    addMessage("assistant", data.reply, meta);
    history.push({ role: "assistant", content: data.reply });
    saveHistory();
    if (data.warnings?.length) showNotice(data.warnings.join(" "));
  } catch (error) {
    showNotice(error.message || "通信エラーが発生しました。");
    addMessage("assistant", "ごめん、今うまく応答できなかった。設定かサーバーログを確認してみて。 ");
  } finally {
    typing.remove();
    setWaiting(false);
    input.focus();
  }
});
