const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat-button");
const messagesElement = document.querySelector("#messages");
const statusLabel = document.querySelector("#status-label");

const USER_KEY = "ririmero-chat-user-id";
const CONVERSATION_KEY = "ririmero-chat-conversation-id";
const HISTORY_KEY = "ririmero-chat-history";
const REQUEST_TIMEOUT_MS = 90_000;
const GREETING = "やほ〜、今日はどしたん？ ゆっくり話してみてね。";

let viewportUpdateFrame = 0;
let waiting = false;
let ready = false;
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
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.lang = "ja";
  bubble.textContent = content;
  row.appendChild(bubble);
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

function renderHistory() {
  messagesElement.innerHTML = "";
  if (!history.length) addMessage("assistant", GREETING);
  for (const message of history) addMessage(message.role, message.content);
  window.requestAnimationFrame(scrollMessagesToBottom);
}

function updateAvailability() {
  input.disabled = waiting || !ready;
  sendButton.disabled = waiting || !ready;
  newChatButton.disabled = waiting;
}

function startNewConversation() {
  history = [];
  saveHistory();
  conversationId = createClientId();
  localStorage.setItem(CONVERSATION_KEY, conversationId);
  renderHistory();
  input.focus();
}

async function initialize() {
  renderHistory();
  updateAvailability();
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error("config request failed");
    const config = await response.json();
    ready = Boolean(config.api_key_configured);
    statusLabel.textContent = ready ? "Online" : "API key not configured";
  } catch {
    ready = false;
    statusLabel.textContent = "Unable to connect";
  } finally {
    updateAvailability();
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

newChatButton.addEventListener("click", () => {
  if (waiting) return;
  if (history.length && !window.confirm("Start a new chat? The current chat will remain saved on the server.")) {
    return;
  }
  startNewConversation();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || waiting || !ready) return;

  const requestHistory = history.slice(-12);
  addMessage("user", message);
  history.push({ role: "user", content: message });
  saveHistory();
  input.value = "";
  input.style.height = "auto";
  waiting = true;
  updateAvailability();
  statusLabel.textContent = "Thinking...";
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
      const retryAfter = response.headers.get("Retry-After");
      const retryHint = retryAfter ? ` Please wait about ${retryAfter} seconds.` : "";
      const errorMessages = {
        429: "Too many requests.",
        503: "The service is currently unavailable.",
        504: "The response timed out.",
      };
      throw new Error(`${errorMessages[response.status] || "Could not get a response."}${retryHint}`);
    }
    if (!data.reply) throw new Error("The server returned an empty response.");
    addMessage("assistant", data.reply);
    history.push({ role: "assistant", content: data.reply });
    saveHistory();
  } catch (error) {
    const messageText = error.name === "AbortError"
      ? "The request was stopped after 90 seconds without a response."
      : (error.message || "A connection error occurred.");
    const errorRow = addMessage("assistant", messageText);
    errorRow.querySelector(".bubble").lang = "en";
  } finally {
    window.clearTimeout(timeoutId);
    typing.remove();
    waiting = false;
    statusLabel.textContent = ready ? "Online" : "Unable to connect";
    updateAvailability();
  }
});

initialize();
