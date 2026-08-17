const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messagesElement = document.querySelector("#messages");
const statusLabel = document.querySelector("#status-label");
const phaseLabel = document.querySelector("#phase-label");
const timerLabel = document.querySelector("#timer-label");
const phaseTitle = document.querySelector("#phase-title");
const phaseHelp = document.querySelector("#phase-help");
const experimentGate = document.querySelector("#experiment-gate");
const experimentGateTitle = document.querySelector("#experiment-gate-title");
const experimentGateMessage = document.querySelector("#experiment-gate-message");
const advanceButton = document.querySelector("#advance-button");

const USER_KEY = "experiment-chat-user-id";
const CONVERSATION_KEY = "experiment-chat-conversation-id";
const HISTORY_KEY = "experiment-chat-history";
const PHASE_KEY = "experiment-chat-phase";
const REQUEST_TIMEOUT_MS = 90_000;
const SIMPLE_GREETING = "まずはこのAIと話してみてね。最初の送信でスタートするよ。";
const FULL_GREETING = "後半のAIに切り替わったよ。ここから新しく話してね。";

let viewportUpdateFrame = 0;
let waiting = false;
let experimentReady = false;
let statusRefreshInFlight = false;
let currentStatus = null;
let pendingStatus = null;
let renderedPhase = null;
let history = loadHistory();

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
  if (typeof webCrypto?.randomUUID === "function") return webCrypto.randomUUID();
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

function getOrCreateId(key) {
  let value = localStorage.getItem(key);
  if (!value) {
    value = createClientId();
    localStorage.setItem(key, value);
  }
  return value;
}

const userId = getOrCreateId(USER_KEY);
let conversationId = getOrCreateId(CONVERSATION_KEY);

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

function addMessage(role, content) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;
  const body = document.createElement("div");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  body.appendChild(bubble);
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

function renderHistory(greeting) {
  messagesElement.innerHTML = "";
  if (!history.length) addMessage("assistant", greeting);
  for (const message of history) addMessage(message.role, message.content);
  window.requestAnimationFrame(scrollMessagesToBottom);
}

function resetPhaseHistory(phase) {
  history = [];
  saveHistory();
  renderedPhase = phase;
  localStorage.setItem(PHASE_KEY, phase);
  conversationId = createClientId();
  localStorage.setItem(CONVERSATION_KEY, conversationId);
  renderHistory(phase === "FULL" ? FULL_GREETING : SIMPLE_GREETING);
}

function formatTime(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  if (seconds > 0 && seconds % 60 === 0) return `${seconds / 60}分`;
  return formatTime(seconds);
}

function activeConversationPhase(phase) {
  if (phase === "FULL" || phase === "COMPLETE") return "FULL";
  return "SIMPLE";
}

function showOperationalMessage(message) {
  phaseHelp.textContent = message;
}

function updateComposerAvailability() {
  const phase = currentStatus?.phase;
  const active = phase === "WAITING" || phase === "SIMPLE" || phase === "FULL";
  const unavailable = !experimentReady || !active;
  input.disabled = unavailable;
  sendButton.disabled = waiting || unavailable;
  form.classList.toggle("hidden", !active && experimentReady);
}

function applyExperimentStatus(status) {
  if (
    waiting &&
    currentStatus &&
    status.phase !== currentStatus.phase
  ) {
    pendingStatus = status;
    timerLabel.textContent = formatTime(status.remaining_seconds);
    return;
  }

  experimentReady = true;
  currentStatus = status;
  const conversationPhase = activeConversationPhase(status.phase);
  const savedPhase = localStorage.getItem(PHASE_KEY);
  if (renderedPhase === null) {
    if (savedPhase === conversationPhase) {
      renderedPhase = conversationPhase;
      renderHistory(conversationPhase === "FULL" ? FULL_GREETING : SIMPLE_GREETING);
    } else {
      resetPhaseHistory(conversationPhase);
    }
  } else if (renderedPhase !== conversationPhase) {
    resetPhaseHistory(conversationPhase);
  }

  timerLabel.textContent = formatTime(status.remaining_seconds);
  const phaseDuration = formatDuration(status.phase_seconds);
  const totalDuration = formatDuration(status.phase_seconds * 2);
  experimentGate.classList.add("hidden");
  advanceButton.classList.remove("hidden");

  if (status.phase === "WAITING") {
    phaseLabel.textContent = "前半";
    phaseTitle.textContent = "前半：シンプルなギャルAI";
    phaseHelp.textContent = `最初のメッセージ送信で${phaseDuration}タイマーが始まります`;
    statusLabel.textContent = "開始待ち";
  } else if (status.phase === "SIMPLE") {
    phaseLabel.textContent = "前半";
    phaseTitle.textContent = "前半：シンプルなギャルAI";
    phaseHelp.textContent = "「あなたはギャルです」だけを指示したAIです";
    statusLabel.textContent = "実験中";
  } else if (status.phase === "TRANSITION") {
    phaseLabel.textContent = "切替";
    phaseTitle.textContent = "前半終了";
    phaseHelp.textContent = "最後の返答を確認してから後半へ進んでください";
    statusLabel.textContent = "切替待ち";
    experimentGateTitle.textContent = `前半の${phaseDuration}が終わりました`;
    experimentGateMessage.textContent = "後半を始めると画面の会話履歴が消え、別のAIに切り替わります。";
    advanceButton.textContent = "後半を始める";
    experimentGate.classList.remove("hidden");
  } else if (status.phase === "FULL") {
    phaseLabel.textContent = "後半";
    phaseTitle.textContent = "後半：りりめろAI";
    phaseHelp.textContent = "現在の対話設計を使ったAIです";
    statusLabel.textContent = "実験中";
  } else {
    phaseLabel.textContent = "終了";
    phaseTitle.textContent = "実験終了";
    phaseHelp.textContent = `${totalDuration}の対話が完了しました`;
    statusLabel.textContent = "終了";
    experimentGateTitle.textContent = "実験は終了です";
    experimentGateMessage.textContent = "最後まで話してくれてありがとうございました。";
    advanceButton.classList.add("hidden");
    experimentGate.classList.remove("hidden");
  }
  updateComposerAvailability();
  window.requestAnimationFrame(scrollMessagesToBottom);
}

async function fetchExperimentStatus() {
  const response = await fetch("/api/experiment/status", { cache: "no-store" });
  if (!response.ok) throw new Error("experiment status request failed");
  return response.json();
}

async function refreshExperimentStatus() {
  if (statusRefreshInFlight) return;
  statusRefreshInFlight = true;
  try {
    applyExperimentStatus(await fetchExperimentStatus());
  } catch {
    experimentReady = false;
    updateComposerAvailability();
    statusLabel.textContent = "接続できません";
    showOperationalMessage("実験状態を確認できません。再読み込みしてみてください。 ");
  } finally {
    statusRefreshInFlight = false;
  }
}

async function initialize() {
  updateComposerAvailability();
  try {
    const configResponse = await fetch("/api/config");
    if (!configResponse.ok) throw new Error("config request failed");
    const config = await configResponse.json();
    if (!config.api_key_configured) {
      showOperationalMessage("OPENAI_API_KEY が設定されていません。 ");
    }
    await refreshExperimentStatus();
  } catch {
    statusLabel.textContent = "サーバーに接続できません";
    showOperationalMessage("バックエンドとの接続を確認してください。 ");
  }
}

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

advanceButton.addEventListener("click", async () => {
  advanceButton.disabled = true;
  try {
    const response = await fetch("/api/experiment/advance", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "後半へ進めませんでした。");
    applyExperimentStatus(data);
    input.focus();
  } catch (error) {
    showOperationalMessage(error.message || "後半へ進めませんでした。 ");
  } finally {
    advanceButton.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || waiting || input.disabled) return;

  const requestHistory = history.slice(-12);
  addMessage("user", message);
  history.push({ role: "user", content: message });
  saveHistory();
  input.value = "";
  input.style.height = "auto";
  waiting = true;
  updateComposerAvailability();
  statusLabel.textContent = "返信を考え中…";
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
      // Proxy-generated non-JSON errors are handled below.
    }
    if (!response.ok) {
      const detail = typeof data.detail === "object"
        ? data.detail
        : { message: data.detail };
      if (["experiment_transition", "experiment_complete"].includes(detail.code)) {
        await refreshExperimentStatus();
        const boundaryError = new Error(detail.message || "フェーズが終了しました。");
        boundaryError.isPhaseBoundary = true;
        throw boundaryError;
      }
      const retryAfter = response.headers.get("Retry-After");
      const retryHint = retryAfter ? ` ${retryAfter}秒ほど待ってください。` : "";
      throw new Error(`${detail.message || "応答に失敗しました。"}${retryHint}`);
    }
    if (!data.reply) throw new Error("空の応答が返ってきました。");
    addMessage("assistant", data.reply);
    history.push({ role: "assistant", content: data.reply });
    saveHistory();
    if (data.warnings?.length) showOperationalMessage(data.warnings.join(" "));
    await refreshExperimentStatus();
  } catch (error) {
    const messageText = error.name === "AbortError"
      ? "90秒待っても返事がなかったため送信を止めました。"
      : (error.message || "通信エラーが発生しました。");
    showOperationalMessage(messageText);
    if (!error.isPhaseBoundary) {
      addMessage("assistant", "ごめん、今うまく返せなかった。少し待ってもう一度送ってみて。 ");
    }
  } finally {
    window.clearTimeout(timeoutId);
    typing.remove();
    waiting = false;
    if (pendingStatus) {
      const status = pendingStatus;
      pendingStatus = null;
      applyExperimentStatus(status);
    } else {
      updateComposerAvailability();
      if (currentStatus) applyExperimentStatus(currentStatus);
    }
  }
});

initialize();
window.setInterval(refreshExperimentStatus, 1000);
