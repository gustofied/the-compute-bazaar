import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";

const HISTORY_KEY = "compute-bazaar.terminal.command-history";
const PENDING_KEY = "compute-bazaar.terminal.pending-command";
const OPEN_KEY = "compute-bazaar.terminal.last-open";
const MAX_HISTORY = 50;

const workspace = document.body.dataset.terminalWorkspace || inferWorkspace();
const nativeLaunchToken = takeNativeLaunchToken();
const nativeBootstrap = establishNativeSession(nativeLaunchToken);
const state = {
  commands: [],
  history: loadHistory(),
  historyIndex: -1,
  draft: "",
  status: null,
  openTimer: null,
  opening: false,
  shell: {
    socket: null,
    terminal: null,
    fit: null,
    resizeObserver: null,
    connectPromise: null,
  },
};

const root = document.createElement("section");
root.className = "terminal-command";
root.setAttribute("aria-label", "Terminal command");
root.innerHTML = `
  <section class="terminal-shell" id="terminal-shell-drawer" hidden aria-label="Local shell">
    <header class="terminal-shell-head">
      <div class="terminal-shell-identity">
        <span class="terminal-shell-status">Shell</span>
        <code class="terminal-shell-cwd">repository root</code>
      </div>
      <div class="terminal-shell-actions">
        <button type="button" data-shell-action="interrupt">Interrupt</button>
        <button type="button" data-shell-action="clear">Clear</button>
        <button type="button" data-shell-action="close">Close</button>
      </div>
    </header>
    <div class="terminal-shell-stage"></div>
  </section>
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
    <button
      class="terminal-command-shell-toggle"
      type="button"
      aria-controls="terminal-shell-drawer"
      aria-expanded="false"
      aria-label="Toggle shell"
      hidden
    >Shell</button>
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
  shell: root.querySelector(".terminal-shell"),
  shellStage: root.querySelector(".terminal-shell-stage"),
  shellStatus: root.querySelector(".terminal-shell-status"),
  shellCwd: root.querySelector(".terminal-shell-cwd"),
  shellToggle: root.querySelector(".terminal-command-shell-toggle"),
};

function takeNativeLaunchToken() {
  const url = new URL(window.location.href);
  const fragment = new URLSearchParams(url.hash.replace(/^#/, ""));
  const supplied = fragment.get("session") || url.searchParams.get("session");
  if (supplied) {
    url.searchParams.delete("session");
    fragment.delete("session");
    const hash = fragment.size ? `#${fragment}` : "";
    window.history.replaceState(null, "", `${url.pathname}${url.search}${hash}`);
  }
  return supplied;
}

async function establishNativeSession(token) {
  if (!token) return;
  const response = await fetch("/api/terminal/session", {
    method: "POST",
    headers: { "X-Compute-Bazaar-Session": token },
  });
  if (!response.ok) throw new Error("Native Terminal session was rejected");
}

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
  await nativeBootstrap.catch(() => {});
  if (state.status && !refresh) return state.status;
  const response = await fetch("/api/terminal", { cache: "no-store" });
  if (!response.ok) throw new Error("Terminal status is unavailable");
  state.status = await response.json();
  state.commands = Array.isArray(state.status.commands) ? state.status.commands : [];
  if (state.status.shell?.authorized) {
    elements.input.placeholder = "SQL, command, or shell · try help";
    elements.shellToggle.hidden = false;
  }
  return state.status;
}

async function resolveCommand(command) {
  await nativeBootstrap.catch(() => {});
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

function ensureShellTerminal() {
  if (state.shell.terminal) return state.shell.terminal;
  const terminal = new Terminal({
    allowProposedApi: false,
    convertEol: true,
    cursorBlink: true,
    cursorStyle: "bar",
    fontFamily: '"SFMono-Regular", "Cascadia Code", "Roboto Mono", Consolas, monospace',
    fontSize: 12,
    lineHeight: 1.35,
    scrollback: 10_000,
    theme: {
      background: "#0d1110",
      foreground: "#efede4",
      cursor: "#a8c96b",
      cursorAccent: "#0d1110",
      selectionBackground: "#a8c96b55",
      black: "#0d1110",
      red: "#d98770",
      green: "#b7d07b",
      yellow: "#f3c888",
      blue: "#91aecb",
      magenta: "#bd7bd0",
      cyan: "#73bfc1",
      white: "#efede4",
      brightBlack: "#737c76",
      brightRed: "#e59a85",
      brightGreen: "#c8df93",
      brightYellow: "#f6d6a2",
      brightBlue: "#abc3da",
      brightMagenta: "#cf96dd",
      brightCyan: "#91d2d4",
      brightWhite: "#ffffff",
    },
  });
  const fit = new FitAddon();
  terminal.loadAddon(fit);
  terminal.open(elements.shellStage);
  terminal.onData((data) => sendShell({ type: "input", data }));
  terminal.onResize(({ cols, rows }) => {
    sendShell({ type: "resize", columns: cols, rows });
  });
  const resizeObserver = new ResizeObserver(() => fitShell());
  resizeObserver.observe(elements.shellStage);
  state.shell.terminal = terminal;
  state.shell.fit = fit;
  state.shell.resizeObserver = resizeObserver;
  return terminal;
}

function fitShell() {
  if (!state.shell.fit || elements.shell.hidden) return;
  requestAnimationFrame(() => {
    try {
      state.shell.fit.fit();
    } catch {
      // The drawer may have closed between measurement and animation frame.
    }
  });
}

function shellSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/terminal/shell`;
}

async function connectShell() {
  const status = await loadTerminal({ refresh: true });
  if (!status.shell?.authorized) {
    throw new Error("Shell requires the native Terminal");
  }
  if (state.shell.socket?.readyState === WebSocket.OPEN) {
    return state.shell.socket;
  }
  if (state.shell.connectPromise) return state.shell.connectPromise;
  state.shell.connectPromise = new Promise((resolve, reject) => {
    const socket = new WebSocket(shellSocketUrl());
    state.shell.socket = socket;
    socket.addEventListener("open", () => {
      state.shell.connectPromise = null;
      resolve(socket);
    }, { once: true });
    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "snapshot") renderShellSnapshot(message);
      if (message.type === "error") showMessage("Shell", message.message, { error: true });
    });
    socket.addEventListener("close", () => {
      state.shell.socket = null;
      state.shell.connectPromise = null;
      elements.shellStatus.textContent = "Shell disconnected";
    });
    socket.addEventListener("error", () => {
      reject(new Error("Shell connection failed"));
    }, { once: true });
  });
  return state.shell.connectPromise;
}

function sendShell(message) {
  const socket = state.shell.socket;
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function renderShellSnapshot(snapshot) {
  const terminal = ensureShellTerminal();
  if (snapshot.reset) terminal.reset();
  if (snapshot.output) terminal.write(snapshot.output);
  elements.shellStatus.textContent = snapshot.active ? "Shell" : "Shell exited";
  elements.shellCwd.textContent = snapshot.cwd || "repository root";
}

async function openShell(command = null) {
  ensureShellTerminal();
  elements.shell.hidden = false;
  root.classList.add("shell-open");
  document.body.classList.add("terminal-shell-open");
  elements.shellToggle.setAttribute("aria-expanded", "true");
  window.dispatchEvent(new CustomEvent("compute-bazaar:shell", { detail: { open: true } }));
  closePanel();
  fitShell();
  const socket = await connectShell();
  state.shell.fit?.fit();
  socket.send(JSON.stringify({
    type: command ? "run" : "open",
    ...(command ? { command } : {}),
    columns: state.shell.terminal?.cols || 120,
    rows: state.shell.terminal?.rows || 32,
  }));
  state.shell.terminal?.focus();
}

function closeShell() {
  elements.shell.hidden = true;
  root.classList.remove("shell-open");
  document.body.classList.remove("terminal-shell-open");
  elements.shellToggle.setAttribute("aria-expanded", "false");
  window.dispatchEvent(new CustomEvent("compute-bazaar:shell", { detail: { open: false } }));
  elements.input.focus();
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
    case "shell":
      await openShell(action.command);
      return;
    case "error":
      showMessage("Command not understood", action.message, { error: true });
      return;
    default:
      closePanel();
      sendToData(action);
  }
}

async function pollTerminalOpen() {
  if (state.opening || document.visibilityState === "hidden") return;
  state.opening = true;
  try {
    const response = await fetch("/api/terminal/open", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    const launch = payload.contract === "compute-bazaar.terminal.open" ? payload.launch : null;
    if (!launch?.launch_id || !launch.action) return;
    if (localStorage.getItem(OPEN_KEY) === launch.launch_id) return;
    localStorage.setItem(OPEN_KEY, launch.launch_id);
    window.focus();
    await execute(launch.action);
  } catch {
    // The local process may be stopping or reloading.
  } finally {
    state.opening = false;
  }
}

function watchTerminalOpen() {
  void pollTerminalOpen();
  state.openTimer = window.setInterval(pollTerminalOpen, 500);
}

async function submit() {
  const raw = elements.input.value.trim();
  if (!raw) {
    await loadTerminal();
    showOptions("Terminal commands", state.commands);
    return;
  }
  if (["reload", "refresh"].includes(normalizedInput(raw))) {
    window.location.reload();
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

elements.shellToggle.addEventListener("click", () => {
  if (elements.shell.hidden) {
    void openShell().catch((error) => {
      showMessage("Shell unavailable", error instanceof Error ? error.message : String(error), { error: true });
    });
  }
  else closeShell();
});

elements.shell.addEventListener("click", (event) => {
  const button = event.target.closest("[data-shell-action]");
  if (!button) return;
  const action = button.dataset.shellAction;
  if (action === "close") {
    closeShell();
    return;
  }
  if (action === "interrupt") sendShell({ type: "interrupt" });
  if (action === "clear") {
    state.shell.terminal?.reset();
    sendShell({ type: "clear" });
  }
});

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
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "r") {
    event.preventDefault();
    window.location.reload();
    return;
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.input.focus();
    elements.input.select();
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "j" && !elements.shellToggle.hidden) {
    event.preventDefault();
    elements.shellToggle.click();
  }
  if (event.key === "Escape" && !elements.shell.hidden) closeShell();
});

void loadTerminal().then(watchTerminalOpen).catch(() => {});

window.addEventListener("pagehide", () => {
  if (state.openTimer) window.clearInterval(state.openTimer);
});

window.ComputeBazaarTerminal = {
  takePendingAction,
  showMessage,
  closePanel,
  closeShell,
};
