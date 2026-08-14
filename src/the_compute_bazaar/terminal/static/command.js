import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";

const HISTORY_KEY = "compute-bazaar.terminal.command-history";
const PENDING_KEY = "compute-bazaar.terminal.pending-command";
const OPEN_KEY = "compute-bazaar.terminal.last-open";
const SHELL_LAYOUT_KEY = "compute-bazaar.terminal.shell-layout";
const MAX_HISTORY = 50;
const SHELL_MIN_WIDTH = 320;
const SHELL_MIN_WORKSPACE_WIDTH = 420;
const MAX_AGENT_EVENTS = 400;
const AGENT_BUSY_STATES = new Set(["starting", "working", "stopping"]);
const BAZAAR_GLOBALS = new Set(["/home", "/data", "/fleet", "/eval", "/trade"]);

const workspace = document.body.dataset.terminalWorkspace || inferWorkspace();
const nativeLaunchToken = takeNativeLaunchToken();
const nativeBootstrap = establishNativeSession(nativeLaunchToken);
const shellLayout = loadShellLayout();
if (shellLayout.width) {
  document.documentElement.style.setProperty("--terminal-shell-width", `${shellLayout.width}px`);
}
const state = {
  commands: [],
  history: loadHistory(),
  historyIndex: -1,
  draft: "",
  status: null,
  openTimer: null,
  opening: false,
  activeSession: shellLayout.tab,
  agent: {
    access: "read",
    state: "idle",
    submitting: false,
    events: [],
    socket: null,
    connectPromise: null,
  },
  shell: {
    socket: null,
    terminal: null,
    fit: null,
    resizeObserver: null,
    connectPromise: null,
    open: shellLayout.open,
    width: shellLayout.width,
  },
};

const root = document.createElement("section");
root.className = "terminal-command";
root.setAttribute("aria-label", "Terminal command");
root.innerHTML = `
  <section class="terminal-shell" id="terminal-shell-drawer" hidden aria-label="Terminal sessions">
    <header class="terminal-shell-head">
      <nav class="terminal-session-tabs" role="tablist" aria-label="Sessions">
        <button id="terminal-session-tab-shell" type="button" role="tab" data-session-tab="shell" aria-controls="terminal-session-panel-shell" aria-selected="true">
          <span>Shell</span><i data-session-state="idle" aria-hidden="true"></i>
        </button>
        <button id="terminal-session-tab-agent" type="button" role="tab" data-session-tab="agent" aria-controls="terminal-session-panel-agent" aria-selected="false" tabindex="-1">
          <span>Agent</span><i data-session-state="idle" aria-hidden="true"></i>
        </button>
      </nav>
      <div class="terminal-shell-actions">
        <button type="button" data-session-action="access" title="Agent access" hidden>Read</button>
        <button type="button" data-session-action="interrupt" aria-label="Interrupt session" title="Interrupt session">^C</button>
        <button type="button" data-session-action="clear" title="Clear shell">Clear</button>
        <button type="button" data-session-action="close" aria-label="Close sessions" title="Close sessions">×</button>
      </div>
    </header>
    <div class="terminal-session-stack">
      <div id="terminal-session-panel-shell" class="terminal-shell-stage" data-session-panel="shell" role="tabpanel" aria-labelledby="terminal-session-tab-shell"></div>
      <section id="terminal-session-panel-agent" class="terminal-agent-stage" data-session-panel="agent" role="tabpanel" aria-labelledby="terminal-session-tab-agent" hidden>
        <div class="terminal-agent-transcript" role="log" aria-live="polite"></div>
      </section>
    </div>
    <div
      class="terminal-shell-resizer"
      role="separator"
      aria-label="Resize shell"
      aria-orientation="vertical"
      tabindex="0"
    ></div>
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
      aria-label="Toggle sessions"
      hidden
    >Sessions</button>
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
  workspace: root.querySelector(".terminal-command-workspace"),
  run: root.querySelector(".terminal-command-run"),
  shellToggle: root.querySelector(".terminal-command-shell-toggle"),
  shellResizer: root.querySelector(".terminal-shell-resizer"),
  tabs: [...root.querySelectorAll("[data-session-tab]")],
  panels: [...root.querySelectorAll("[data-session-panel]")],
  access: root.querySelector('[data-session-action="access"]'),
  interrupt: root.querySelector('[data-session-action="interrupt"]'),
  clear: root.querySelector('[data-session-action="clear"]'),
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
  if (window.location.pathname.startsWith("/fleet")) return "fleet";
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

function loadShellLayout() {
  try {
    const value = JSON.parse(localStorage.getItem(SHELL_LAYOUT_KEY) || "{}");
    return {
      open: value.open === true,
      width: Number.isFinite(value.width) && value.width > 0 ? value.width : null,
      tab: ["shell", "agent"].includes(value.tab) ? value.tab : "shell",
    };
  } catch {
    return { open: false, width: null, tab: "shell" };
  }
}

function shellWidthBounds() {
  return {
    min: SHELL_MIN_WIDTH,
    max: Math.max(
      SHELL_MIN_WIDTH,
      Math.min(900, window.innerWidth - SHELL_MIN_WORKSPACE_WIDTH),
    ),
  };
}

function persistShellLayout() {
  try {
    localStorage.setItem(SHELL_LAYOUT_KEY, JSON.stringify({
      open: state.shell.open,
      width: state.shell.width,
      tab: state.activeSession,
    }));
  } catch {
    // The layout still works when local storage is unavailable.
  }
}

function setShellWidth(width, { persist = false } = {}) {
  const bounds = shellWidthBounds();
  const next = Math.round(Math.max(bounds.min, Math.min(bounds.max, width)));
  state.shell.width = next;
  document.documentElement.style.setProperty("--terminal-shell-width", `${next}px`);
  elements.shellResizer.setAttribute("aria-valuemin", String(bounds.min));
  elements.shellResizer.setAttribute("aria-valuemax", String(bounds.max));
  elements.shellResizer.setAttribute("aria-valuenow", String(next));
  elements.shellResizer.setAttribute("aria-valuetext", `${next} pixels`);
  if (persist) persistShellLayout();
  fitShell();
}

if (state.shell.width) setShellWidth(state.shell.width);

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
    elements.shellToggle.hidden = false;
  }
  if (!state.agent.socket && !agentIsBusy()) {
    state.agent.state = state.status.agent?.state || "idle";
  }
  elements.tabs.forEach((tab) => {
    const sessionId = tab.dataset.sessionTab;
    const available = sessionId === "shell"
      ? state.status.shell?.authorized
      : state.status.agent?.available;
    tab.disabled = !available;
  });
  updateSessionControls();
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
    cursorBlink: false,
    cursorStyle: "bar",
    disableStdin: false,
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
  if (!state.shell.fit || elements.shell.hidden || state.activeSession !== "shell") return;
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
      setSessionState("shell", "error");
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
  setSessionState("shell", snapshot.active ? "working" : "idle");
}

async function openShell(command = null, { persist = true, focus = true } = {}) {
  root.classList.add("shell-open");
  document.body.classList.add("terminal-shell-open");
  elements.shell.hidden = false;
  state.shell.open = true;
  if (!state.shell.width && window.innerWidth > 760) {
    setShellWidth(elements.shell.getBoundingClientRect().width);
  }
  if (persist) persistShellLayout();
  elements.shellToggle.setAttribute("aria-expanded", "true");
  window.dispatchEvent(new CustomEvent("compute-bazaar:shell", { detail: { open: true } }));
  closePanel();
  await activateSession(command ? "shell" : state.activeSession, { focus });
  if (command) {
    sendShell({
      type: "run",
      command,
      columns: state.shell.terminal?.cols || 120,
      rows: state.shell.terminal?.rows || 32,
    });
  }
}

function closeShell({ persist = true } = {}) {
  elements.shell.hidden = true;
  root.classList.remove("shell-open");
  document.body.classList.remove("terminal-shell-open");
  state.shell.open = false;
  if (persist) persistShellLayout();
  elements.shellToggle.setAttribute("aria-expanded", "false");
  window.dispatchEvent(new CustomEvent("compute-bazaar:shell", { detail: { open: false } }));
  elements.workspace.textContent = workspace;
  elements.run.textContent = "Run";
  elements.input.placeholder = "SQL or command · try help";
  elements.input.focus();
}

function sessionTab(sessionId) {
  return elements.tabs.find((tab) => tab.dataset.sessionTab === sessionId);
}

function setSessionState(sessionId, value) {
  const tab = sessionTab(sessionId);
  const indicator = tab?.querySelector("[data-session-state]");
  if (indicator) indicator.dataset.sessionState = value;
  if (sessionId === "agent") {
    state.agent.state = value;
    updateSessionControls();
  }
}

function agentIsBusy() {
  return state.agent.submitting || AGENT_BUSY_STATES.has(state.agent.state);
}

function updateSessionControls() {
  const agent = state.shell.open && state.activeSession === "agent"
    ? state.agent
    : null;
  elements.access.hidden = !agent;
  elements.access.textContent = agent?.access === "full" ? "Full access" : "Read";
  elements.access.dataset.access = agent?.access || "read";
  elements.access.disabled = Boolean(agent && agentIsBusy());
  elements.interrupt.textContent = agent ? "Stop" : "^C";
  elements.clear.textContent = agent ? "New session" : "Clear";
  elements.clear.title = agent ? "Start a new agent session" : "Clear shell";
  elements.clear.disabled = Boolean(agent && agentIsBusy());
  elements.workspace.textContent = state.shell.open ? state.activeSession : workspace;
  elements.input.placeholder = agent
    ? "Agent prompt"
    : "SQL, command, or shell · try help";
  elements.input.setAttribute(
    "aria-label",
    agent ? "Agent prompt" : "Terminal command or read-only SQL",
  );
  elements.run.textContent = agent ? "Send" : "Run";
  elements.run.disabled = Boolean(agent && agentIsBusy());
}

async function activateSession(sessionId, { focus = true } = {}) {
  const tab = sessionTab(sessionId);
  if (!tab || tab.disabled) return;
  state.activeSession = sessionId;
  elements.tabs.forEach((item) => {
    item.setAttribute("aria-selected", String(item === tab));
    item.tabIndex = item === tab ? 0 : -1;
  });
  elements.panels.forEach((panel) => {
    panel.hidden = panel.dataset.sessionPanel !== sessionId;
  });
  updateSessionControls();
  persistShellLayout();
  if (sessionId === "shell") {
    ensureShellTerminal();
    const socket = await connectShell();
    fitShell();
    socket.send(JSON.stringify({
      type: "open",
      columns: state.shell.terminal?.cols || 120,
      rows: state.shell.terminal?.rows || 32,
    }));
    if (focus) state.shell.terminal?.focus();
    return;
  }
  await connectAgent();
  if (focus) elements.input.focus();
}

function agentSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/terminal/agent`;
}

async function connectAgent() {
  await loadTerminal();
  const agent = state.agent;
  if (agent.socket?.readyState === WebSocket.OPEN) return agent.socket;
  if (agent.connectPromise) return agent.connectPromise;
  agent.connectPromise = new Promise((resolve, reject) => {
    const socket = new WebSocket(agentSocketUrl());
    agent.socket = socket;
    socket.addEventListener("open", () => {
      agent.connectPromise = null;
      resolve(socket);
    }, { once: true });
    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      applyAgentMessage(message);
    });
    socket.addEventListener("close", () => {
      const wasBusy = agentIsBusy();
      agent.socket = null;
      agent.connectPromise = null;
      agent.submitting = false;
      if (wasBusy) setSessionState("agent", "error");
      else updateSessionControls();
    });
    socket.addEventListener("error", () => {
      agent.connectPromise = null;
      reject(new Error("Agent connection failed"));
    }, { once: true });
  });
  return agent.connectPromise;
}

function applyAgentMessage(message) {
  const agent = state.agent;
  if (message.type === "snapshot") {
    agent.events = Array.isArray(message.events) ? message.events.slice(-MAX_AGENT_EVENTS) : [];
    setSessionState("agent", message.state || "idle");
    renderAgent();
    return;
  }
  if (message.type === "reset") {
    agent.events = [];
    renderAgent();
    return;
  }
  if (message.type === "state") {
    agent.submitting = false;
    setSessionState("agent", message.state || "idle");
    return;
  }
  if (message.type === "event" && message.event) {
    agent.events.push(message.event);
    if (trimAgentEvents()) renderAgent();
    else renderAgentEvent(message.event);
    return;
  }
  if (message.type === "replace" && message.event) {
    const index = agent.events.findIndex((item) => item.id === message.event.id);
    if (index === -1) agent.events.push(message.event);
    else agent.events[index] = message.event;
    trimAgentEvents();
    renderAgent();
    return;
  }
  if (message.type === "append") {
    const event = agent.events.find((item) => item.id === message.event_id);
    if (event) event.text = `${event.text || ""}${message.text || ""}`;
    const node = agentPanel()?.querySelector(`[data-agent-event="${message.event_id}"] pre`);
    if (node) node.textContent = event?.text || "";
    scrollAgent();
    return;
  }
  if (message.type === "error") {
    agent.submitting = false;
    const event = { kind: "error", text: message.message || "Agent request failed" };
    agent.events.push(event);
    if (trimAgentEvents()) renderAgent();
    else renderAgentEvent(event);
    updateSessionControls();
  }
}

function trimAgentEvents() {
  const overflow = state.agent.events.length - MAX_AGENT_EVENTS;
  if (overflow <= 0) return false;
  state.agent.events.splice(0, overflow);
  return true;
}

function agentPanel() {
  return elements.panels.find((panel) => panel.dataset.sessionPanel === "agent");
}

function renderAgent() {
  const transcript = agentPanel()?.querySelector(".terminal-agent-transcript");
  if (!transcript) return;
  transcript.replaceChildren();
  state.agent.events.forEach((event) => appendAgentEvent(transcript, event));
  scrollAgent({ force: true });
}

function renderAgentEvent(event) {
  const transcript = agentPanel()?.querySelector(".terminal-agent-transcript");
  if (!transcript) return;
  appendAgentEvent(transcript, event);
  scrollAgent();
}

function appendAgentEvent(transcript, event) {
  const row = document.createElement("div");
  row.className = `terminal-agent-event ${event.kind || "notice"}`;
  if (event.id !== undefined) row.dataset.agentEvent = String(event.id);
  if (event.kind === "message") {
    row.classList.add(event.role === "user" ? "user" : "assistant");
    const content = document.createElement("pre");
    content.textContent = event.text || "";
    if (event.role === "user") {
      const label = document.createElement("span");
      label.textContent = ">";
      row.append(label);
    }
    row.append(content);
  } else if (event.kind === "tool") {
    const status = document.createElement("span");
    status.textContent = event.status || "running";
    const title = document.createElement("code");
    title.textContent = event.title || "Tool";
    row.append(status, title);
  } else {
    row.textContent = event.text || "";
  }
  transcript.append(row);
}

function scrollAgent({ force = false } = {}) {
  const transcript = agentPanel()?.querySelector(".terminal-agent-transcript");
  if (!transcript) return;
  const pinned = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
  if (force || pinned) transcript.scrollTop = transcript.scrollHeight;
}

async function sendAgentPrompt(prompt) {
  const agent = state.agent;
  if (agentIsBusy()) {
    throw new Error("Agent is already working");
  }
  agent.submitting = true;
  updateSessionControls();
  try {
    const socket = await connectAgent();
    socket.send(JSON.stringify({
      type: "prompt",
      prompt,
      access: agent.access,
    }));
  } catch (error) {
    agent.submitting = false;
    setSessionState("agent", "error");
    throw error;
  }
}

function isBazaarGlobal(raw) {
  return BAZAAR_GLOBALS.has(raw.trim().toLowerCase());
}

function savePendingAction(action, launchId = null) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ action, launchId }));
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

async function sendToData(action, launchId = null) {
  const detail = { action, handled: false, completion: null };
  window.dispatchEvent(new CustomEvent("compute-bazaar:command", { detail }));
  if (detail.handled) {
    await detail.completion;
    return { deferred: false };
  }
  savePendingAction(action, launchId);
  window.location.assign("/data");
  return { deferred: true };
}

async function completeTerminalOpen(launchId, { message = null, error = null } = {}) {
  if (!launchId) return;
  const response = await fetch(`/api/terminal/open/${encodeURIComponent(launchId)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, error }),
  });
  if (!response.ok) throw new Error("Could not report the Terminal result");
}

function actionSuccessMessage(action) {
  switch (action?.kind) {
    case "navigate": {
      const destination = action.href === "/" ? "Terminal" : action.href.split("/").filter(Boolean)[0];
      return `Opened ${destination.charAt(0).toUpperCase()}${destination.slice(1)}.`;
    }
    case "query": return `Opened ${action.query_id} in Data.`;
    case "view": return `Opened ${action.view_id} in Data.`;
    case "model": return `Opened ${action.model_id} in Data.`;
    case "blueprint": return `Opened ${action.blueprint_id} in Data.`;
    case "table": return `Opened ${action.table_ref} in Data.`;
    case "describe": return `Opened ${action.table_ref} schema in Data.`;
    case "offers": return "Opened current offers in Data.";
    case "launch-plan": return "Opened the launch plan in Data.";
    case "catalog": return "Opened Browse in Data.";
    case "sql": return "Opened query in Data.";
    default: return "Opened in the Compute Bazaar Terminal.";
  }
}

async function showStatus() {
  try {
    const status = await loadTerminal({ refresh: true });
    const runId = status.run?.source_run_id || status.run?.run_id || "unknown run";
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

async function execute(action, { launchId = null } = {}) {
  if (!action) return { deferred: false };
  switch (action.kind) {
    case "help":
      await loadTerminal();
      showOptions("Terminal commands", state.commands);
      return { deferred: false };
    case "clear":
      setInput("");
      closePanel();
      return { deferred: false };
    case "navigate":
      if (launchId) {
        await completeTerminalOpen(launchId, {
          message: actionSuccessMessage(action),
        });
      }
      window.location.assign(action.href);
      return { deferred: Boolean(launchId) };
    case "locked":
      showMessage("Trade is locked", "Execution will live here later. Data and Eval are available now.");
      return { deferred: false };
    case "status":
      await showStatus();
      return { deferred: false };
    case "shell":
      await openShell(action.command);
      return { deferred: false };
    case "error":
      showMessage("Command not understood", action.message, { error: true });
      return { deferred: false };
    default:
      closePanel();
      return sendToData(action, launchId);
  }
}

async function pollTerminalOpen() {
  if (state.opening) return;
  state.opening = true;
  let launchId = null;
  try {
    const response = await fetch("/api/terminal/open", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    const launch = payload.contract === "compute-bazaar.terminal.open" ? payload.launch : null;
    if (!launch?.launch_id || !launch.action || launch.state !== "pending") return;
    launchId = launch.launch_id;
    if (localStorage.getItem(OPEN_KEY) === launch.launch_id) return;
    localStorage.setItem(OPEN_KEY, launch.launch_id);
    window.focus();
    const result = await execute(launch.action, { launchId: launch.launch_id });
    if (!result?.deferred) {
      await completeTerminalOpen(launch.launch_id, {
        message: actionSuccessMessage(launch.action),
      });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await completeTerminalOpen(launchId, { error: message }).catch(() => {});
    showMessage("Could not open", message, { error: true });
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
    if (state.shell.open && state.activeSession !== "shell") return;
    await loadTerminal();
    showOptions("Terminal commands", state.commands);
    return;
  }
  if (state.shell.open && state.activeSession !== "shell" && !isBazaarGlobal(raw)) {
    if (agentIsBusy()) return;
    saveHistory(raw);
    try {
      await sendAgentPrompt(raw);
      setInput("");
    } catch (error) {
      showMessage(
        "Agent unavailable",
        error instanceof Error ? error.message : String(error),
        { error: true },
      );
    }
    return;
  }
  if (state.shell.open && state.activeSession === "shell" && !isBazaarGlobal(raw)) {
    saveHistory(raw);
    try {
      const socket = await connectShell();
      socket.send(JSON.stringify({
        type: "run",
        command: raw,
        columns: state.shell.terminal?.cols || 120,
        rows: state.shell.terminal?.rows || 32,
      }));
      setInput("");
      state.shell.terminal?.focus();
    } catch (error) {
      showMessage(
        "Shell unavailable",
        error instanceof Error ? error.message : String(error),
        { error: true },
      );
    }
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

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    void activateSession(tab.dataset.sessionTab).catch((error) => {
      showMessage(
        "Session unavailable",
        error instanceof Error ? error.message : String(error),
        { error: true },
      );
    });
  });
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const available = elements.tabs.filter((item) => !item.disabled);
    const index = available.indexOf(tab);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = available[(index + step + available.length) % available.length];
    next?.focus();
    if (next) void activateSession(next.dataset.sessionTab, { focus: false });
  });
});

elements.shell.addEventListener("click", (event) => {
  const button = event.target.closest("[data-session-action]");
  if (!button) return;
  const action = button.dataset.sessionAction;
  if (action === "close") {
    closeShell();
    return;
  }
  if (action === "access" && state.activeSession !== "shell") {
    const agent = state.agent;
    agent.access = agent.access === "read" ? "full" : "read";
    updateSessionControls();
    return;
  }
  if (action === "interrupt") {
    if (state.activeSession === "shell") sendShell({ type: "interrupt" });
    else {
      const socket = state.agent.socket;
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "cancel" }));
      }
    }
  }
  if (action === "clear") {
    if (state.activeSession === "shell") {
      state.shell.terminal?.reset();
      sendShell({ type: "clear" });
    } else {
      void connectAgent().then((socket) => {
        socket.send(JSON.stringify({ type: "new" }));
      }).catch((error) => {
        showMessage("Agent unavailable", error instanceof Error ? error.message : String(error), { error: true });
      });
    }
  }
});

let resizePointer = null;

elements.shellResizer.addEventListener("pointerdown", (event) => {
  if (window.innerWidth <= 760) return;
  event.preventDefault();
  resizePointer = event.pointerId;
  elements.shellResizer.setPointerCapture(event.pointerId);
  document.body.classList.add("terminal-shell-resizing");
});

elements.shellResizer.addEventListener("pointermove", (event) => {
  if (event.pointerId !== resizePointer) return;
  setShellWidth(event.clientX);
});

function finishShellResize(event) {
  if (event.pointerId !== resizePointer) return;
  resizePointer = null;
  document.body.classList.remove("terminal-shell-resizing");
  persistShellLayout();
}

elements.shellResizer.addEventListener("pointerup", finishShellResize);
elements.shellResizer.addEventListener("pointercancel", finishShellResize);
elements.shellResizer.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const bounds = shellWidthBounds();
  const current = elements.shell.getBoundingClientRect().width;
  const width = event.key === "Home"
    ? bounds.min
    : event.key === "End"
      ? bounds.max
      : current + (event.key === "ArrowLeft" ? -24 : 24);
  setShellWidth(width, { persist: true });
});

window.addEventListener("resize", () => {
  if (!state.shell.width || window.innerWidth <= 760) return;
  setShellWidth(state.shell.width);
});

elements.input.addEventListener("input", () => {
  resizeInput();
  state.historyIndex = -1;
  if (state.shell.open && state.activeSession !== "shell") {
    closePanel();
    return;
  }
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
  const shellHasFocus = state.shell.open
    && state.activeSession === "shell"
    && elements.shellStage.contains(document.activeElement);
  if (shellHasFocus && event.ctrlKey && !event.metaKey) return;
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
  if (
    event.key === "Escape"
    && !elements.shell.hidden
    && !elements.shell.contains(document.activeElement)
  ) closeShell();
});

void loadTerminal().then((status) => {
  if (sessionTab(state.activeSession)?.disabled) state.activeSession = "shell";
  if (status.shell?.authorized && state.shell.open) {
    void openShell(null, { persist: false, focus: false }).catch(() => {
      closeShell({ persist: false });
    });
  }
  watchTerminalOpen();
}).catch(() => {});

window.addEventListener("pagehide", () => {
  if (state.openTimer) window.clearInterval(state.openTimer);
});

window.ComputeBazaarTerminal = {
  takePendingAction,
  completeTerminalOpen,
  actionSuccessMessage,
  showMessage,
  closePanel,
  closeShell,
};
