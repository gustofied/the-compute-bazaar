const HISTORY_KEY = "compute-bazaar.terminal.command-history.v1";
const PENDING_KEY = "compute-bazaar.terminal.pending-command.v1";
const MAX_HISTORY = 50;

const workspace = document.body.dataset.terminalWorkspace || inferWorkspace();
const state = {
  commands: [],
  history: loadHistory(),
  historyIndex: -1,
  draft: "",
  status: null,
};

const root = document.createElement("section");
root.className = "terminal-command";
root.setAttribute("aria-label", "Terminal command");
root.innerHTML = `
  <div class="terminal-command-panel" hidden>
    <div class="terminal-command-panel-head">
      <p class="terminal-command-panel-title">Terminal</p>
      <button class="terminal-command-close" type="button" aria-label="Close command help">×</button>
    </div>
    <div class="terminal-command-panel-body"></div>
  </div>
  <form class="terminal-command-inner" autocomplete="off">
    <span class="terminal-command-workspace">${escapeHtml(workspace)}</span>
    <span class="terminal-command-prompt" aria-hidden="true">›</span>
    <textarea
      class="terminal-command-input"
      rows="1"
      spellcheck="false"
      autocomplete="off"
      autocapitalize="off"
      aria-label="Terminal command or read-only SQL"
      placeholder="SQL or command · try help"
    ></textarea>
    <span class="terminal-command-shortcut">⌘K</span>
    <button class="terminal-command-run" type="submit">Run</button>
  </form>
`;

document.body.classList.add("terminal-command-enabled");
document.body.append(root);

const elements = {
  form: root.querySelector("form"),
  input: root.querySelector("textarea"),
  panel: root.querySelector(".terminal-command-panel"),
  panelTitle: root.querySelector(".terminal-command-panel-title"),
  panelBody: root.querySelector(".terminal-command-panel-body"),
  close: root.querySelector(".terminal-command-close"),
};

function inferWorkspace() {
  if (window.location.pathname.startsWith("/data")) return "data";
  if (window.location.pathname.startsWith("/eval")) return "eval";
  return "terminal";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function loadHistory() {
  try {
    const values = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(values) ? values.filter((value) => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function saveHistory(command) {
  const next = [command, ...state.history.filter((value) => value !== command)].slice(0, MAX_HISTORY);
  state.history = next;
  state.historyIndex = -1;
  state.draft = "";
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 96)}px`;
}

function setInput(value, { focus = true } = {}) {
  elements.input.value = value;
  resizeInput();
  if (focus) {
    elements.input.focus();
    elements.input.setSelectionRange(value.length, value.length);
  }
}

function closePanel() {
  elements.panel.hidden = true;
  elements.panel.classList.remove("error");
}

function showMessage(title, message, { error = false } = {}) {
  elements.panelTitle.textContent = title;
  elements.panelBody.replaceChildren();
  const paragraph = document.createElement("p");
  paragraph.className = "terminal-command-message";
  paragraph.textContent = message;
  elements.panelBody.append(paragraph);
  elements.panel.classList.toggle("error", error);
  elements.panel.hidden = false;
}

function showOptions(title, options) {
  elements.panelTitle.textContent = title;
  elements.panel.classList.remove("error");
  elements.panelBody.replaceChildren();
  const list = document.createElement("div");
  list.className = "terminal-command-options";
  options.forEach((option) => {
    const button = document.createElement("button");
    button.className = "terminal-command-option";
    button.type = "button";
    button.innerHTML = `<code>${escapeHtml(option.command)}</code><span>${escapeHtml(option.description)}</span>`;
    button.addEventListener("click", () => {
      setInput(option.command);
      closePanel();
    });
    list.append(button);
  });
  elements.panelBody.append(list);
  elements.panel.hidden = false;
}

function normalizedInput(value) {
  return value
    .trim()
    .replace(/^compute-bazaar(?:\s+terminal)?(?:\s+|$)/i, "")
    .replace(/^\//, "")
    .trim()
    .toLowerCase();
}

function commandSuggestions(value) {
  const normalized = normalizedInput(value);
  if (!normalized || /^(select|with)\b/.test(normalized)) return [];
  return state.commands
    .filter((entry) => entry.command.toLowerCase().startsWith(normalized))
    .slice(0, 6);
}

async function loadTerminal({ refresh = false } = {}) {
  if (state.status && !refresh) return state.status;
  const response = await fetch("/api/terminal", { cache: "no-store" });
  if (!response.ok) throw new Error("Terminal status is unavailable");
  state.status = await response.json();
  state.commands = Array.isArray(state.status.commands) ? state.status.commands : [];
  return state.status;
}

async function resolveCommand(command) {
  const response = await fetch("/api/terminal/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Command service is unavailable");
  }
  return response.json();
}

function savePendingAction(action) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(action));
}

function takePendingAction() {
  try {
    const value = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
    return value ? JSON.parse(value) : null;
  } catch {
    sessionStorage.removeItem(PENDING_KEY);
    return null;
  }
}

function sendToData(action) {
  const detail = { action, handled: false };
  window.dispatchEvent(new CustomEvent("compute-bazaar:command", { detail }));
  if (detail.handled) return;
  savePendingAction(action);
  window.location.assign("/data");
}

async function showStatus() {
  try {
    const status = await loadTerminal({ refresh: true });
    const runId = status.run?.run_id || "unknown run";
    const destinations = Object.entries(status.destinations || {})
      .filter(([, destination]) => destination.available)
      .map(([name]) => name)
      .join(", ");
    showMessage(
      "Terminal status",
      `${status.table_count || 0} tables · ${runId} · ${destinations || "no workspaces available"}`,
    );
  } catch (error) {
    showMessage("Status unavailable", error instanceof Error ? error.message : String(error), { error: true });
  }
}

async function execute(action) {
  if (!action) return;
  switch (action.kind) {
    case "help":
      await loadTerminal();
      showOptions("Terminal commands", state.commands);
      return;
    case "clear":
      setInput("");
      closePanel();
      return;
    case "navigate":
      window.location.assign(action.href);
      return;
    case "locked":
      showMessage("Trade is locked", "Execution will live here later. Data and Eval are available now.");
      return;
    case "status":
      await showStatus();
      return;
    case "error":
      showMessage("Command not understood", action.message, { error: true });
      return;
    default:
      closePanel();
      sendToData(action);
  }
}

async function submit() {
  const raw = elements.input.value.trim();
  if (!raw) {
    await loadTerminal();
    showOptions("Terminal commands", state.commands);
    return;
  }
  saveHistory(raw);
  try {
    const action = await resolveCommand(raw);
    await execute(action);
    if (action.kind !== "error") setInput("");
  } catch (error) {
    showMessage("Command unavailable", error instanceof Error ? error.message : String(error), { error: true });
  }
}

function browseHistory(direction) {
  if (!state.history.length) return;
  if (state.historyIndex === -1) state.draft = elements.input.value;
  state.historyIndex = Math.max(-1, Math.min(state.history.length - 1, state.historyIndex + direction));
  setInput(state.historyIndex === -1 ? state.draft : state.history[state.historyIndex]);
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void submit();
});

elements.close.addEventListener("click", closePanel);

elements.input.addEventListener("input", () => {
  resizeInput();
  state.historyIndex = -1;
  const suggestions = commandSuggestions(elements.input.value);
  if (suggestions.length) showOptions("Commands", suggestions);
  else if (!elements.input.value.trim()) closePanel();
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submit();
    return;
  }
  if (event.key === "Escape") {
    closePanel();
    elements.input.blur();
    return;
  }
  if (event.key === "ArrowUp" && !elements.input.value.includes("\n")) {
    event.preventDefault();
    browseHistory(1);
  }
  if (event.key === "ArrowDown" && !elements.input.value.includes("\n")) {
    event.preventDefault();
    browseHistory(-1);
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.input.focus();
    elements.input.select();
  }
});

void loadTerminal().catch(() => {});

window.ComputeBazaarTerminal = {
  takePendingAction,
  showMessage,
  closePanel,
};
