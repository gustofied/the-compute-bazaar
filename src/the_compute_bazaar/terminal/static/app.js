const VIEW_STORAGE_KEY = "compute-bazaar.terminal.views.v1";
const PERSPECTIVE_VERSION = "4.5.2";
const PERSPECTIVE_ASSETS = {
  viewer: `https://cdn.jsdelivr.net/npm/@perspective-dev/viewer@${PERSPECTIVE_VERSION}/dist/cdn/perspective-viewer.js`,
  datagrid: `https://cdn.jsdelivr.net/npm/@perspective-dev/viewer-datagrid@${PERSPECTIVE_VERSION}/dist/cdn/perspective-viewer-datagrid.js`,
  charts: `https://cdn.jsdelivr.net/npm/@perspective-dev/viewer-charts@${PERSPECTIVE_VERSION}/dist/cdn/perspective-viewer-charts.js`,
  client: `https://cdn.jsdelivr.net/npm/@perspective-dev/client@${PERSPECTIVE_VERSION}/dist/cdn/perspective.js`,
};
const REQUIRED_PERSPECTIVE_PLUGINS = [
  { name: "Datagrid", tag: "perspective-viewer-datagrid" },
  { name: "Y Bar", tag: "perspective-viewer-charts-y-bar" },
  { name: "Y Line", tag: "perspective-viewer-charts-y-line" },
];

const elements = {
  body: document.body,
  catalogPanel: document.querySelector("#catalog-panel"),
  catalogToggle: document.querySelector("#catalog-toggle"),
  catalogClose: document.querySelector("#catalog-close"),
  catalogScrim: document.querySelector("#catalog-scrim"),
  terminalViewList: document.querySelector("#terminal-view-list"),
  terminalViewCount: document.querySelector("#terminal-view-count"),
  queryList: document.querySelector("#query-list"),
  queryCount: document.querySelector("#query-count"),
  goldList: document.querySelector("#gold-list"),
  goldCount: document.querySelector("#gold-count"),
  silverList: document.querySelector("#silver-list"),
  silverCount: document.querySelector("#silver-count"),
  viewList: document.querySelector("#view-list"),
  viewEmpty: document.querySelector("#view-empty"),
  viewCount: document.querySelector("#view-count"),
  runLabel: document.querySelector("#run-label"),
  runLight: document.querySelector("#run-light"),
  runId: document.querySelector("#run-id"),
  observedAt: document.querySelector("#observed-at"),
  viewKind: document.querySelector("#view-kind"),
  viewTitle: document.querySelector("#view-title"),
  viewDescription: document.querySelector("#view-description"),
  sqlToggle: document.querySelector("#sql-toggle"),
  queryDrawer: document.querySelector("#query-drawer"),
  editor: document.querySelector("#sql-editor"),
  limit: document.querySelector("#query-limit"),
  run: document.querySelector("#run-query"),
  save: document.querySelector("#save-view"),
  resultRows: document.querySelector("#result-rows"),
  resultTime: document.querySelector("#result-time"),
  resultRun: document.querySelector("#result-run"),
  viewerConfig: document.querySelector("#viewer-config"),
  viewerStage: document.querySelector("#viewer-stage"),
  viewerHost: document.querySelector("#viewer-host"),
  viewer: null,
  viewerState: document.querySelector("#viewer-state"),
  viewerStateTitle: document.querySelector("#viewer-state-title"),
  viewerStateDetail: document.querySelector("#viewer-state-detail"),
  saveDialog: document.querySelector("#save-dialog"),
  saveForm: document.querySelector("#save-form"),
  viewName: document.querySelector("#view-name"),
  cancelSave: document.querySelector("#cancel-save"),
  toast: document.querySelector("#toast"),
};

const state = {
  session: null,
  perspective: null,
  worker: null,
  table: null,
  activeSource: null,
  sourceSql: null,
  hasResult: false,
  running: false,
  sqlOpen: false,
  toastTimer: null,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortRunId(value) {
  const id = String(value || "unknown run");
  return id.length > 24 ? `${id.slice(0, 20)}...` : id;
}

function formatObservedAt(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function formatCount(value) {
  if (value === null || value === undefined) return "";
  return new Intl.NumberFormat().format(Number(value));
}

function setCatalogOpen(open) {
  elements.body.classList.toggle("catalog-open", open);
  elements.catalogToggle.setAttribute("aria-expanded", String(open));
}

function setSqlOpen(open) {
  state.sqlOpen = open;
  elements.queryDrawer.classList.toggle("open", open);
  elements.queryDrawer.setAttribute("aria-hidden", String(!open));
  elements.queryDrawer.inert = !open;
  elements.sqlToggle.setAttribute("aria-expanded", String(open));
  elements.sqlToggle.classList.toggle("active", open);
}

function setViewerState(title, detail, { error = false, hidden = false } = {}) {
  elements.viewerStateTitle.textContent = title;
  elements.viewerStateDetail.textContent = detail;
  elements.viewerState.classList.toggle("error", error);
  elements.viewerState.classList.toggle("hidden", hidden);
  elements.viewerStage.setAttribute("aria-busy", String(!hidden && !error));
}

function setRunning(running) {
  state.running = running;
  elements.run.disabled = running;
  elements.save.disabled = running || !state.hasResult;
  elements.run.querySelector("span").textContent = running ? "Running" : "Run query";
}

function showToast(message) {
  window.clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  state.toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 2200);
}

function setActiveSource(key) {
  state.activeSource = key;
  document.querySelectorAll("[data-source-key]").forEach((element) => {
    element.classList.toggle("active", element.dataset.sourceKey === key);
  });
}

function setViewCopy(kind, title, description) {
  elements.viewKind.textContent = kind;
  elements.viewTitle.textContent = title;
  elements.viewDescription.textContent = description;
}

async function startPerspective() {
  const stages = [
    ["Loading Perspective", PERSPECTIVE_ASSETS.viewer],
    ["Loading table viewer", PERSPECTIVE_ASSETS.datagrid],
    ["Loading chart viewer", PERSPECTIVE_ASSETS.charts],
  ];
  for (const [label, url] of stages) {
    elements.runLabel.textContent = label;
    await import(url);
  }
  await customElements.whenDefined("perspective-viewer");
  await waitForPerspectivePlugins(REQUIRED_PERSPECTIVE_PLUGINS);
  elements.viewer = document.createElement("perspective-viewer");
  elements.viewer.id = "viewer";
  elements.viewer.setAttribute("theme", "Pro Dark");
  elements.viewerHost.append(elements.viewer);
  elements.viewerConfig.disabled = false;
  elements.runLabel.textContent = "Starting Arrow engine";
  const module = await import(PERSPECTIVE_ASSETS.client);
  state.perspective = module.default;
  state.worker = await state.perspective.worker();
}

async function waitForPerspectivePlugins(required, timeoutMs = 5000) {
  for (const plugin of required) {
    await customElements.whenDefined(plugin.tag);
  }

  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    const probe = document.createElement("perspective-viewer");
    const registered = new Set(probe.getAllPlugins().map(perspectivePluginName));
    if (required.every((plugin) => registered.has(plugin.name))) return;
    await new Promise((resolve) => window.setTimeout(resolve, 16));
  }
  throw new Error(`Perspective plugins did not register: ${required.map((plugin) => plugin.name).join(", ")}`);
}

function perspectivePluginName(plugin) {
  if (typeof plugin === "string") return plugin;
  if (typeof plugin?.name === "string") return plugin.name;
  if (typeof plugin?.get_static_config === "function") {
    return plugin.get_static_config().name;
  }
  return "";
}

function validateSession(payload) {
  const arrays = ["tables", "queries", "views"];
  const valid = payload?.contract === "compute-bazaar.data.session.v1"
    && arrays.every((key) => Array.isArray(payload[key]));
  if (!valid) {
    throw new Error("This port is serving an older Compute Bazaar process. Stop it or run Data on another port.");
  }
  return payload;
}

function renderViews(views) {
  const available = views.filter((view) => view.available);
  elements.terminalViewCount.textContent = String(available.length);
  elements.terminalViewList.innerHTML = available.map((view, index) => `
    <button
      class="catalog-item terminal-view-item"
      type="button"
      data-terminal-view-id="${escapeHtml(view.view_id)}"
      data-source-key="view:${escapeHtml(view.view_id)}"
    >
      <span class="view-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="catalog-item-copy">
        <span class="view-kind-label">${escapeHtml(view.kind || "Market")}</span>
        <strong>${escapeHtml(view.title)}</strong>
        <small>${escapeHtml(view.description)}</small>
      </span>
    </button>
  `).join("");
}

function renderQueryList(queries, views) {
  const viewQueries = new Set(views.map((view) => view.query_id));
  const remaining = queries.filter((query) => !viewQueries.has(query.query_id));
  elements.queryCount.textContent = String(remaining.length);
  elements.queryList.innerHTML = remaining.map((query) => `
    <button
      class="catalog-item"
      type="button"
      data-query-id="${escapeHtml(query.query_id)}"
      data-source-key="query:${escapeHtml(query.query_id)}"
      ${query.available ? "" : "disabled"}
    >
      <span class="catalog-item-copy">
        <strong>${escapeHtml(query.title)}</strong>
        <small>${escapeHtml(query.description)}</small>
      </span>
      <span class="item-count">SQL</span>
    </button>
  `).join("");
}

function renderTableList(tables, layer) {
  const matching = tables.filter((table) => table.layer === layer);
  elements[`${layer}Count`].textContent = String(matching.length);
  elements[`${layer}List`].innerHTML = matching.map((table) => {
    const ref = `${table.layer}.${table.table_name}`;
    const count = table.row_count === null || table.row_count === undefined
      ? table.table_type.toLowerCase()
      : formatCount(table.row_count);
    return `
      <button
        class="catalog-item"
        type="button"
        data-table-ref="${escapeHtml(ref)}"
        data-source-key="table:${escapeHtml(ref)}"
      >
        <span class="catalog-item-copy">
          <strong>${escapeHtml(table.table_name)}</strong>
          <small>${escapeHtml(ref)}</small>
        </span>
        <span class="item-count">${escapeHtml(count)}</span>
      </button>
    `;
  }).join("");
}

function loadSavedViews() {
  try {
    const payload = JSON.parse(localStorage.getItem(VIEW_STORAGE_KEY) || "[]");
    return Array.isArray(payload) ? payload : [];
  } catch {
    return [];
  }
}

function persistSavedViews(views) {
  localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(views));
}

function renderSavedViews() {
  const views = loadSavedViews();
  elements.viewCount.textContent = String(views.length);
  elements.viewEmpty.hidden = views.length > 0;
  elements.viewList.innerHTML = views.map((view) => `
    <div class="catalog-item" data-source-key="saved:${escapeHtml(view.id)}">
      <button class="catalog-item-copy saved-view-load" type="button" data-saved-view-id="${escapeHtml(view.id)}">
        <strong>${escapeHtml(view.name)}</strong>
        <small>${escapeHtml(shortRunId(view.runId))}</small>
      </button>
      <button class="delete-view" type="button" data-delete-view="${escapeHtml(view.id)}" aria-label="Delete ${escapeHtml(view.name)}">Delete</button>
    </div>
  `).join("");
}

function stripTransientConfig(config) {
  if (!config || typeof config !== "object") return config;
  const cleaned = structuredClone(config);
  delete cleaned.table;
  delete cleaned.name;
  return cleaned;
}

async function selectView(view, limit = view.default_limit) {
  setViewCopy(`${view.kind || "Market"} view`, view.title, view.description);
  elements.editor.value = view.sql;
  state.sourceSql = view.sql.trim();
  elements.limit.value = limit;
  setActiveSource(`view:${view.view_id}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: view.perspective, preserveView: false });
}

async function selectQuery(query, limit = query.default_limit) {
  setViewCopy("Saved SQL", query.title, query.description || "Saved DataFusion query.");
  elements.editor.value = query.sql;
  state.sourceSql = query.sql.trim();
  elements.limit.value = limit;
  setActiveSource(`query:${query.query_id}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: { plugin: "Datagrid", settings: false }, preserveView: false });
}

async function selectTable(table) {
  const tableRef = `${table.layer}.${table.table_name}`;
  setViewCopy(`${table.layer} table`, table.table_name, `Direct inspection of ${tableRef}.`);
  elements.editor.value = `select *\nfrom ${tableRef}`;
  state.sourceSql = elements.editor.value.trim();
  elements.limit.value = Math.min(Number(elements.limit.value) || 100, 500);
  setActiveSource(`table:${tableRef}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: { plugin: "Datagrid", settings: false }, preserveView: false });
}

async function selectScratch(sql, limit, perspective = null) {
  setViewCopy("Scratch SQL", "Query result", "A bounded read-only DataFusion result.");
  elements.editor.value = sql;
  state.sourceSql = sql.trim();
  elements.limit.value = limit;
  setActiveSource(null);
  setSqlOpen(false);
  await runCurrentQuery({
    restoreConfig: perspective || { plugin: "Datagrid", settings: false },
    preserveView: false,
  });
}

async function saveCurrentView(name) {
  const config = stripTransientConfig(await elements.viewer.save());
  const views = loadSavedViews();
  const view = {
    id: crypto.randomUUID(),
    name,
    description: elements.viewDescription.textContent,
    sql: elements.editor.value.trim(),
    limit: Number(elements.limit.value),
    config,
    createdAt: new Date().toISOString(),
    runId: state.session?.run?.run_id || null,
  };
  views.unshift(view);
  persistSavedViews(views.slice(0, 30));
  renderSavedViews();
  setActiveSource(`saved:${view.id}`);
  showToast(`Saved ${name}`);
}

async function loadSavedView(id) {
  const view = loadSavedViews().find((candidate) => candidate.id === id);
  if (!view) return;
  setViewCopy("My view", view.name, view.description || `Saved ${formatObservedAt(view.createdAt)}.`);
  elements.editor.value = view.sql;
  state.sourceSql = view.sql.trim();
  elements.limit.value = view.limit;
  setActiveSource(`saved:${view.id}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: view.config, preserveView: false });
}

function deleteSavedView(id) {
  const views = loadSavedViews();
  const view = views.find((candidate) => candidate.id === id);
  persistSavedViews(views.filter((candidate) => candidate.id !== id));
  renderSavedViews();
  if (state.activeSource === `saved:${id}`) setActiveSource(null);
  showToast(view ? `Deleted ${view.name}` : "Deleted view");
}

async function responseError(response) {
  try {
    const payload = await response.json();
    return payload.detail || `Query failed (${response.status})`;
  } catch {
    return `Query failed (${response.status})`;
  }
}

async function runCurrentQuery({ restoreConfig = null, preserveView = true } = {}) {
  if (state.running) return;
  const sql = elements.editor.value.trim();
  const limit = Math.max(1, Math.min(1000, Number(elements.limit.value) || 500));
  elements.limit.value = String(limit);
  if (!sql) {
    setViewerState("SQL is empty", "Write a SELECT or WITH statement before running it.", { error: true });
    return;
  }

  const sourceChanged = Boolean(state.activeSource && state.sourceSql !== sql);
  if (sourceChanged) {
    setViewCopy("Scratch SQL", "Query result", "A bounded read-only DataFusion result.");
    setActiveSource(null);
  }

  let currentConfig = restoreConfig;
  if (!currentConfig && preserveView && state.hasResult && !sourceChanged) {
    try {
      currentConfig = stripTransientConfig(await elements.viewer.save());
    } catch {
      currentConfig = null;
    }
  }

  setRunning(true);
  setViewerState("Running DataFusion", "Streaming the bounded result as Arrow.");
  try {
    const response = await fetch("/api/data/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql, limit }),
    });
    if (!response.ok) throw new Error(await responseError(response));

    const arrow = await response.arrayBuffer();
    const nextTable = await state.worker.table(arrow);
    const previousTable = state.table;
    await elements.viewer.load(nextTable);
    const restored = await restoreViewerLayout(currentConfig);
    if (!restored && restoreConfig) {
      showToast("This layout does not match the current result");
    }
    await elements.viewer.flush();
    await elements.viewer.resize();
    state.table = nextTable;
    state.sourceSql = sql;
    if (previousTable) await previousTable.delete();

    const rowCount = response.headers.get("X-Compute-Bazaar-Row-Count") || "0";
    const elapsed = response.headers.get("X-Compute-Bazaar-Elapsed-Ms") || "-";
    const runId = response.headers.get("X-Compute-Bazaar-Run-Id") || "unknown";
    elements.resultRows.textContent = formatCount(rowCount);
    elements.resultTime.textContent = `${elapsed} ms`;
    elements.resultRun.textContent = shortRunId(runId);
    elements.resultRun.title = runId;
    state.hasResult = true;
    setViewerState("Ready", `${formatCount(rowCount)} rows loaded.`, { hidden: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setViewerState("Query failed", message, { error: true });
    state.hasResult = false;
  } finally {
    setRunning(false);
  }
}

async function restoreViewerLayout(config) {
  const fallback = { plugin: "Datagrid", settings: false };
  try {
    await elements.viewer.restore(config || fallback);
    return true;
  } catch {
    await elements.viewer.reset();
    await elements.viewer.restore(fallback);
    return false;
  }
}

function closeCatalogOnMobile() {
  if (window.matchMedia("(max-width: 820px)").matches) setCatalogOpen(false);
}

async function openInitialSource() {
  const requestedView = new URLSearchParams(window.location.search).get("view");
  const launch = requestedView
    ? { kind: "view", view_id: requestedView }
    : state.session.launch;
  if (launch?.kind === "sql") {
    await selectScratch(launch.sql, launch.limit, launch.perspective);
    return;
  }
  if (launch?.kind === "view") {
    const view = state.session.views.find((candidate) => candidate.view_id === launch.view_id && candidate.available);
    if (view) {
      await selectView(view);
      return;
    }
  }
  if (launch?.kind === "query") {
    const view = state.session.views.find((candidate) => candidate.query_id === launch.query_id && candidate.available);
    if (view) {
      await selectView(view, launch.limit || view.default_limit);
      return;
    }
    const query = state.session.queries.find((candidate) => candidate.query_id === launch.query_id && candidate.available);
    if (query) {
      await selectQuery(query, launch.limit || query.default_limit);
      return;
    }
  }
  const defaultView = state.session.views.find((view) => view.available);
  if (!defaultView) throw new Error("No terminal view is available in this catalog");
  await selectView(defaultView);
}

function catalogSection(name) {
  const ids = name === "tables"
    ? ["gold-heading", "silver-heading"]
    : [name === "queries" ? "saved-query-heading" : "terminal-view-heading"];
  ids.forEach((id) => {
    const heading = document.querySelector(`#${id}`)?.closest(".section-heading");
    if (heading) heading.setAttribute("aria-expanded", "true");
  });
  setCatalogOpen(true);
}

function findTable(tableRef) {
  const normalized = String(tableRef || "").trim().toLowerCase();
  return state.session.tables.find(
    (candidate) => `${candidate.layer}.${candidate.table_name}`.toLowerCase() === normalized,
  );
}

async function handleTerminalAction(action) {
  try {
    switch (action.kind) {
      case "catalog":
        catalogSection(action.section);
        return;
      case "view": {
        const view = state.session.views.find(
          (candidate) => candidate.view_id.toLowerCase() === String(action.view_id).toLowerCase() && candidate.available,
        );
        if (!view) throw new Error(`Unknown view: ${action.view_id}`);
        await selectView(view);
        return;
      }
      case "query": {
        const queryId = String(action.query_id).toLowerCase();
        const view = state.session.views.find(
          (candidate) => candidate.query_id?.toLowerCase() === queryId && candidate.available,
        );
        if (view) {
          await selectView(view, action.limit || view.default_limit);
          return;
        }
        const query = state.session.queries.find(
          (candidate) => candidate.query_id.toLowerCase() === queryId && candidate.available,
        );
        if (!query) throw new Error(`Unknown query: ${action.query_id}`);
        await selectQuery(query, action.limit || query.default_limit);
        return;
      }
      case "table": {
        const table = findTable(action.table_ref);
        if (!table) throw new Error(`Unknown table: ${action.table_ref}`);
        await selectTable(table);
        return;
      }
      case "describe": {
        const table = findTable(action.table_ref);
        if (!table) throw new Error(`Unknown table: ${action.table_ref}`);
        const layer = table.layer.replaceAll("'", "''");
        const tableName = table.table_name.replaceAll("'", "''");
        await selectScratch(`select column_name, data_type, is_nullable\nfrom information_schema.columns\nwhere table_schema = '${layer}' and table_name = '${tableName}'\norder by ordinal_position`, 500);
        setViewCopy("Table schema", `${table.layer}.${table.table_name}`, "Columns registered in the current DataFusion catalog.");
        return;
      }
      case "sql":
        await selectScratch(action.sql, action.limit || 500);
        return;
      default:
        throw new Error("This command is not available in Data.");
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    window.ComputeBazaarTerminal?.showMessage("Command failed", message, { error: true });
  }
}

window.addEventListener("compute-bazaar:command", (event) => {
  if (!event.detail?.action || !state.session) return;
  event.detail.handled = true;
  void handleTerminalAction(event.detail.action);
});

function bindEvents() {
  elements.catalogToggle.addEventListener("click", () => setCatalogOpen(true));
  elements.catalogClose.addEventListener("click", () => setCatalogOpen(false));
  elements.catalogScrim.addEventListener("click", () => setCatalogOpen(false));
  elements.sqlToggle.addEventListener("click", () => setSqlOpen(!state.sqlOpen));

  document.querySelectorAll(".section-heading").forEach((heading) => {
    heading.addEventListener("click", () => {
      const expanded = heading.getAttribute("aria-expanded") === "true";
      heading.setAttribute("aria-expanded", String(!expanded));
    });
  });

  elements.terminalViewList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-terminal-view-id]");
    if (!item) return;
    const view = state.session.views.find((candidate) => candidate.view_id === item.dataset.terminalViewId);
    if (view) void selectView(view);
  });

  elements.queryList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-query-id]");
    if (!item) return;
    const query = state.session.queries.find((candidate) => candidate.query_id === item.dataset.queryId);
    if (query) void selectQuery(query);
  });

  const tableHandler = (event) => {
    const item = event.target.closest("[data-table-ref]");
    if (!item) return;
    const table = state.session.tables.find(
      (candidate) => `${candidate.layer}.${candidate.table_name}` === item.dataset.tableRef,
    );
    if (table) void selectTable(table);
  };
  elements.goldList.addEventListener("click", tableHandler);
  elements.silverList.addEventListener("click", tableHandler);

  elements.viewList.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("[data-delete-view]");
    if (deleteButton) {
      deleteSavedView(deleteButton.dataset.deleteView);
      return;
    }
    const loadButton = event.target.closest("[data-saved-view-id]");
    if (loadButton) void loadSavedView(loadButton.dataset.savedViewId);
  });

  elements.run.addEventListener("click", () => void runCurrentQuery());
  elements.viewerConfig.addEventListener("click", () => void elements.viewer.toggleConfig());
  elements.editor.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void runCurrentQuery();
    }
  });

  elements.save.addEventListener("click", () => {
    elements.viewName.value = elements.viewTitle.textContent || "Terminal view";
    elements.saveDialog.showModal();
    elements.viewName.select();
  });
  elements.cancelSave.addEventListener("click", () => elements.saveDialog.close());
  elements.saveForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = elements.viewName.value.trim();
    if (!name) return;
    elements.saveDialog.close();
    void saveCurrentView(name);
  });
  elements.saveDialog.addEventListener("click", (event) => {
    if (event.target === elements.saveDialog) elements.saveDialog.close();
  });
}

async function initialize() {
  bindEvents();
  setSqlOpen(false);
  renderSavedViews();
  try {
    const sessionResponse = await fetch("/api/data/session", { cache: "no-store" });
    if (!sessionResponse.ok) throw new Error("Could not open the local data catalog");
    state.session = validateSession(await sessionResponse.json());
    renderViews(state.session.views);
    renderQueryList(state.session.queries, state.session.views);
    renderTableList(state.session.tables, "gold");
    renderTableList(state.session.tables, "silver");

    const run = state.session.run || {};
    elements.runLight.classList.add("ready");
    elements.runLabel.textContent = `${state.session.tables.length} tables / ${shortRunId(run.run_id)}`;
    elements.runId.textContent = run.run_id || "Unknown run";
    elements.runId.title = run.run_id || "";
    elements.observedAt.textContent = formatObservedAt(run.observed_at);
    await startPerspective();
    elements.runLabel.textContent = `${state.session.tables.length} tables / ${shortRunId(run.run_id)}`;
    const pendingAction = window.ComputeBazaarTerminal?.takePendingAction();
    if (pendingAction) await handleTerminalAction(pendingAction);
    else await openInitialSource();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    elements.runLight.classList.add("error");
    elements.runLabel.textContent = "Lake unavailable";
    setViewerState("Terminal unavailable", message, { error: true });
  }
}

void initialize();
