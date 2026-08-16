const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messagesElement = document.querySelector("#messages");
const notice = document.querySelector("#notice");
const statusLabel = document.querySelector("#status-label");
const trialLabel = document.querySelector("#trial-label");
const clearButton = document.querySelector("#clear-button");
const trialLock = document.querySelector("#trial-lock");
const trialLockMessage = document.querySelector("#trial-lock-message");
const debugUnlockForm = document.querySelector("#debug-unlock-form");
const debugAccessCode = document.querySelector("#debug-access-code");
const debugUnlockMessage = document.querySelector("#debug-unlock-message");

const USER_KEY = "mem0-chat-user-id";
const CONVERSATION_KEY = "mem0-chat-conversation-id";
const HISTORY_KEY = "mem0-chat-history";
const RUNTIME_KEY = "mem0-chat-runtime-id";
const TRIAL_USED_KEY = "ririmero-trial-used";
const INITIAL_GREETING = "あーし、おしゃべり系ギャルのりりめろ💖いっぱい話そー";
const REQUEST_TIMEOUT_MS = 90_000;
let viewportUpdateFrame = 0;

function syncVisualViewport() {
  const viewport = window.visualViewport;
  const height = viewport?.height || window.innerHeight;
  const offsetTop = viewport?.offsetTop || 0;
  document.documentElement.style.setProperty("--app-height", `${height}px`);
  document.documentElement.style.setProperty("--app-offset-top", `${offsetTop}px`);
}

function scheduleViewportSync() {
  window.cancelAnimationFrame(viewportUpdateFrame);
  viewportUpdateFrame = window.requestAnimationFrame(syncVisualViewport);
}

window.visualViewport?.addEventListener("resize", scheduleViewportSync);
window.visualViewport?.addEventListener("scroll", scheduleViewportSync);
window.addEventListener("resize", scheduleViewportSync);
window.addEventListener("orientationchange", scheduleViewportSync);
syncVisualViewport();

function createClientId() {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === "function") {
    return webCrypto.randomUUID();
  }
  if (typeof webCrypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    webCrypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const getOrCreateId = (key) => {
  let value = localStorage.getItem(key);
  if (!value) {
    value = createClientId();
    localStorage.setItem(key, value);
  }
  return value;
};

const userId = getOrCreateId(USER_KEY);
let conversationId = getOrCreateId(CONVERSATION_KEY);
let history = loadHistory();
let waiting = false;
let trialReady = false;
let trialLimit = 10;
let trialRemaining = 0;
let localTrialUsed = loadLocalTrialUsed();
let trialLocked = false;
let debugUnlimited = false;

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

function scrollMessagesToBottom() {
  messagesElement.scrollTop = messagesElement.scrollHeight;
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
  scrollMessagesToBottom();
  return row;
}

function addTyping() {
  const row = document.createElement("div");
  row.className = "message-row assistant typing";
  row.innerHTML = '<div class="bubble"><span></span><span></span><span></span></div>';
  messagesElement.appendChild(row);
  scrollMessagesToBottom();
  return row;
}

function showNotice(message) {
  notice.textContent = message;
  notice.classList.toggle("hidden", !message);
}

function setWaiting(value) {
  waiting = value;
  updateComposerAvailability();
  input.setAttribute("aria-busy", String(value));
  updateStatusLabel();
}

function loadLocalTrialUsed() {
  const value = Number.parseInt(localStorage.getItem(TRIAL_USED_KEY) || "0", 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function saveLocalTrialUsed(value) {
  localTrialUsed = Math.max(localTrialUsed, value);
  localStorage.setItem(TRIAL_USED_KEY, String(localTrialUsed));
}

function updateComposerAvailability() {
  const unavailable = !trialReady || trialLocked;
  input.disabled = unavailable;
  sendButton.disabled = waiting || unavailable;
}

function updateStatusLabel() {
  if (waiting) {
    statusLabel.textContent = "返信を考え中…";
  } else if (debugUnlimited) {
    statusLabel.textContent = "実装者モード";
  } else if (trialLocked) {
    statusLabel.textContent = "体験終了";
  } else {
    statusLabel.textContent = "オンライン";
  }
}

function applyTrialStatus(status) {
  trialReady = true;
  trialLimit = status.limit ?? trialLimit;
  debugUnlimited = Boolean(status.debug_unlimited);
  const serverRemaining = status.remaining ?? 0;
  const serverUsed = status.used ?? Math.max(0, trialLimit - serverRemaining);
  if (!debugUnlimited) saveLocalTrialUsed(serverUsed);
  const effectiveUsed = Math.max(serverUsed, localTrialUsed);
  trialRemaining = Math.max(0, trialLimit - effectiveUsed);
  trialLocked = !debugUnlimited && (
    Boolean(status.locked) || effectiveUsed >= trialLimit
  );
  trialLabel.textContent = debugUnlimited
    ? "無制限 ∞"
    : `残り ${trialRemaining} 回`;
  trialLockMessage.textContent = `りりめろと話してくれてありがとー！この端末での${trialLimit}回分を使い切ったよ。`;
  trialLock.classList.toggle("hidden", !trialLocked);
  form.classList.toggle("hidden", trialLocked);
  updateComposerAvailability();
  updateStatusLabel();
  if (trialLocked) window.requestAnimationFrame(scrollMessagesToBottom);
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
    if (!config.api_key_configured) {
      showNotice(".env の OPENAI_API_KEY を設定してからメッセージを送ってください。 ");
    }
    return true;
  } catch {
    statusLabel.textContent = "サーバーに接続できません";
    showNotice("バックエンドとの接続を確認してください。");
    return false;
  }
}

async function loadTrialStatus() {
  try {
    const response = await fetch("/api/trial/status");
    if (!response.ok) throw new Error("trial status request failed");
    applyTrialStatus(await response.json());
  } catch {
    trialReady = false;
    updateComposerAvailability();
    statusLabel.textContent = "利用状態を確認できません";
    showNotice("体験版の利用状態を確認できませんでした。再読み込みしてみてね。");
  }
}

async function initialize() {
  updateComposerAvailability();
  if (await loadConfig()) await loadTrialStatus();
}

function syncRuntime(config) {
  const previousRuntime = localStorage.getItem(RUNTIME_KEY);
  if (
    config.reset_state_on_start &&
    previousRuntime !== config.runtime_id
  ) {
    history = [];
    saveHistory();
    conversationId = createClientId();
    localStorage.setItem(CONVERSATION_KEY, conversationId);
    messagesElement.innerHTML = "";
    addMessage("assistant", INITIAL_GREETING);
  }
  localStorage.setItem(RUNTIME_KEY, config.runtime_id);
}

for (const message of history) addMessage(message.role, message.content);
initialize();

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener("click", async () => {
  const previousConversationId = conversationId;
  try {
    await fetch("/api/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        conversation_id: previousConversationId,
      }),
    });
  } catch {
    // A new conversation ID still isolates the next session locally.
  }
  history = [];
  saveHistory();
  conversationId = createClientId();
  localStorage.setItem(CONVERSATION_KEY, conversationId);
  messagesElement.innerHTML = "";
  addMessage("assistant", INITIAL_GREETING);
  showNotice("");
});

debugUnlockForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  debugUnlockMessage.textContent = "確認中…";
  try {
    const response = await fetch("/api/debug/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_code: debugAccessCode.value }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "解除できませんでした。");
    }
    debugAccessCode.value = "";
    debugUnlockMessage.textContent = "";
    applyTrialStatus(data);
    showNotice("実装者モードに切り替えました。この端末では回数無制限です。");
    input.focus();
  } catch (error) {
    debugUnlockMessage.textContent = error.message || "解除できませんでした。";
  }
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
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        message,
        user_id: userId,
        conversation_id: conversationId,
        history: requestHistory,
      }),
    });
    const responseText = await response.text();
    let data = {};
    try {
      data = responseText ? JSON.parse(responseText) : {};
    } catch {
      // RenderなどのプロキシがHTMLエラーを返した場合も送信欄を復帰させる。
    }
    if (!response.ok) {
      const apiDetail = typeof data.detail === "object"
        ? data.detail
        : { message: data.detail };
      if (response.status === 403 && apiDetail.code === "trial_limit_reached") {
        await loadTrialStatus();
        const trialError = new Error(apiDetail.message || "体験版は終了しました。");
        trialError.isTrialLimit = true;
        throw trialError;
      }
      const retryAfter = response.headers.get("Retry-After");
      const retryHint = retryAfter ? ` ${retryAfter}秒ほど待ってね。` : "";
      throw new Error(`${apiDetail.message || "応答に失敗しました。"}${retryHint}`);
    }
    if (!data.reply) throw new Error("空の応答が返ってきました。");
    addMessage("assistant", data.reply);
    history.push({ role: "assistant", content: data.reply });
    saveHistory();
    if (data.debug_unlimited) {
      applyTrialStatus({
        limit: trialLimit,
        used: localTrialUsed,
        remaining: trialRemaining,
        locked: false,
        debug_unlimited: true,
      });
    } else if (data.trial_remaining !== null) {
      applyTrialStatus({
        limit: trialLimit,
        used: Math.max(0, trialLimit - data.trial_remaining),
        remaining: data.trial_remaining,
        locked: data.trial_locked,
        debug_unlimited: false,
      });
    }
    if (data.warnings?.length) showNotice(data.warnings.join(" "));
  } catch (error) {
    const message = error.name === "AbortError"
      ? "90秒待っても返事がなかったから送信を止めたよ。もう一度試してみて。"
      : (error.message || "通信エラーが発生しました。");
    showNotice(message);
    if (!error.isTrialLimit) {
      addMessage("assistant", "ごめん、今うまく返せなかった。ちょい待ってもう一回送ってみて。 ");
    }
  } finally {
    window.clearTimeout(timeoutId);
    typing.remove();
    setWaiting(false);
  }
});
