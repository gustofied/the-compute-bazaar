import perspective from "@perspective-dev/client";
import SERVER_WASM from "@perspective-dev/server/dist/wasm/perspective-server.wasm?url";
import perspectiveViewer from "@perspective-dev/viewer";
import CLIENT_WASM from "@perspective-dev/viewer/dist/wasm/perspective-viewer.wasm?url";
import "@perspective-dev/viewer/dist/css/themes.css";
import "@perspective-dev/viewer-charts";
import "@perspective-dev/viewer-datagrid";

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
  modelList: document.querySelector("#model-list"),
  modelCount: document.querySelector("#model-count"),
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
  saveable: true,
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
  elements.save.disabled = running || !state.hasResult || !state.saveable;
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
  await Promise.all([
    perspective.init_server(fetch(SERVER_WASM)),
    perspectiveViewer.init_client(fetch(CLIENT_WASM)),
  ]);
  await customElements.whenDefined("perspective-viewer");
  await waitForPerspectivePlugins(REQUIRED_PERSPECTIVE_PLUGINS);
  elements.viewer = document.createElement("perspective-viewer");
  elements.viewer.id = "viewer";
  elements.viewer.setAttribute("theme", "Pro Dark");
  elements.viewerHost.append(elements.viewer);
  elements.viewerConfig.disabled = false;
  state.perspective = perspective;
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
  const arrays = ["tables", "queries", "views", "models", "blueprints"];
  const valid = payload?.contract === "compute-bazaar.data.session"
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

function renderAnalyses(blueprints) {
  elements.viewCount.textContent = String(blueprints.length);
  elements.viewEmpty.hidden = blueprints.length > 0;
  elements.viewList.innerHTML = blueprints.map((blueprint) => `
    <div class="catalog-item" data-source-key="blueprint:${escapeHtml(blueprint.blueprint_id)}">
      <button class="catalog-item-copy saved-view-load" type="button" data-blueprint-id="${escapeHtml(blueprint.blueprint_id)}" ${blueprint.available ? "" : "disabled"}>
        <strong>${escapeHtml(blueprint.title)}</strong>
        <small>${escapeHtml(blueprint.model_id)}</small>
      </button>
      <button class="delete-view" type="button" data-delete-analysis="${escapeHtml(blueprint.blueprint_id)}" aria-label="Delete ${escapeHtml(blueprint.title)}">Delete</button>
    </div>
  `).join("");
}

function renderModels(models) {
  elements.modelCount.textContent = String(models.length);
  elements.modelList.innerHTML = models.map((model) => `
    <button
      class="catalog-item"
      type="button"
      data-model-id="${escapeHtml(model.model_id)}"
      data-source-key="model:${escapeHtml(model.model_id)}"
      ${model.available ? "" : "disabled"}
    >
      <span class="catalog-item-copy">
        <strong>${escapeHtml(model.title)}</strong>
        <small>${escapeHtml(model.description || model.model_id)}</small>
      </span>
      <span class="item-count">SQL</span>
    </button>
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

async function selectOffers(action) {
  if (state.running) return;
  const params = new URLSearchParams({ limit: String(action.limit || 100) });
  if (action.provider) params.set("provider", action.provider);
  if (action.gpu_model) params.set("gpu_model", action.gpu_model);
  if (action.offer_id) params.set("offer_id", action.offer_id);
  if (action.include_unavailable) params.set("include_unavailable", "true");
  setViewCopy(
    "Provider data",
    action.offer_id ? "Offer" : "Current offers",
    "Fetched directly from RunPod and Verda.",
  );
  setActiveSource(null);
  setSqlOpen(false);
  elements.sqlToggle.disabled = true;
  state.saveable = false;
  setRunning(true);
  setViewerState("Fetching offers", "Reading the provider APIs now.");
  try {
    const response = await fetch(`/api/data/offers?${params}`, { cache: "no-store" });
    if (!response.ok) throw new Error(await responseError(response));
    const arrow = await response.arrayBuffer();
    const nextTable = await state.worker.table(arrow);
    const previousTable = state.table;
    await elements.viewer.load(nextTable);
    await elements.viewer.restore({ plugin: "Datagrid", settings: false });
    await elements.viewer.flush();
    await elements.viewer.resize();
    state.table = nextTable;
    if (previousTable) await previousTable.delete();
    const rowCount = response.headers.get("X-Compute-Bazaar-Row-Count") || "0";
    elements.resultRows.textContent = formatCount(rowCount);
    elements.resultTime.textContent = `${response.headers.get("X-Compute-Bazaar-Elapsed-Ms") || "-"} ms`;
    elements.resultRun.textContent = "provider read";
    elements.resultRun.title = response.headers.get("X-Compute-Bazaar-Observed-At") || "";
    state.hasResult = true;
    setViewerState("Ready", `${formatCount(rowCount)} offers loaded.`, { hidden: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setViewerState("Offers unavailable", message, { error: true });
    state.hasResult = false;
  } finally {
    setRunning(false);
  }
}

async function selectLaunchPlan(action) {
  if (state.running) return;
  const params = new URLSearchParams({
    offer_id: action.offer_id,
    disk_gb: String(action.disk_gb || 50),
    volume_gb: String(action.volume_gb || 0),
  });
  if (action.name) params.set("name", action.name);
  if (action.image) params.set("image", action.image);
  if (action.ssh_key_id) params.set("ssh_key_id", action.ssh_key_id);
  setViewCopy(
    "Provider request",
    "Launch plan",
    "Revalidated against the provider. Nothing has been created.",
  );
  setActiveSource(null);
  setSqlOpen(false);
  elements.sqlToggle.disabled = true;
  state.saveable = false;
  setRunning(true);
  setViewerState("Revalidating offer", "Preparing the provider request now.");
  try {
    const response = await fetch(`/api/data/launch-plan?${params}`, { cache: "no-store" });
    if (!response.ok) throw new Error(await responseError(response));
    const arrow = await response.arrayBuffer();
    const nextTable = await state.worker.table(arrow);
    const previousTable = state.table;
    await elements.viewer.load(nextTable);
    await elements.viewer.restore({ plugin: "Datagrid", settings: false });
    await elements.viewer.flush();
    await elements.viewer.resize();
    state.table = nextTable;
    if (previousTable) await previousTable.delete();
    elements.resultRows.textContent = "1";
    elements.resultTime.textContent = `${response.headers.get("X-Compute-Bazaar-Elapsed-Ms") || "-"} ms`;
    elements.resultRun.textContent = response.headers.get("X-Compute-Bazaar-Run-Id") || "draft";
    elements.resultRun.title = response.headers.get("X-Compute-Bazaar-Observed-At") || "";
    state.hasResult = true;
    setViewerState("Ready", "Launch plan loaded. No request was submitted.", { hidden: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setViewerState("Launch plan unavailable", message, { error: true });
    state.hasResult = false;
  } finally {
    setRunning(false);
  }
}

async function saveCurrentAnalysis(name) {
  const config = stripTransientConfig(await elements.viewer.save());
  const activeBlueprintId = state.activeSource?.startsWith("blueprint:")
    ? state.activeSource.slice("blueprint:".length)
    : null;
  const activeBlueprint = state.session.blueprints.find(
    (candidate) => candidate.blueprint_id === activeBlueprintId,
  );
  const activeModelId = activeBlueprint?.model_id
    || (state.activeSource?.startsWith("model:")
      ? state.activeSource.slice("model:".length)
      : null);
  const response = await fetch("/api/data/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: name,
      model_id: activeModelId,
      blueprint_id: activeBlueprintId,
      description: elements.viewDescription.textContent,
      sql: elements.editor.value.trim(),
      limit: Number(elements.limit.value),
      perspective: config,
    }),
  });
  if (!response.ok) throw new Error(await responseError(response));
  const saved = await response.json();
  await refreshSessionArtifacts();
  setActiveSource(`blueprint:${saved.blueprint.blueprint_id}`);
  showToast(`Saved ${name}`);
}

async function selectBlueprint(blueprint) {
  setViewCopy("Analysis", blueprint.title, blueprint.description || blueprint.model_id);
  elements.editor.value = blueprint.sql;
  state.sourceSql = blueprint.sql.trim();
  elements.limit.value = blueprint.default_limit;
  setActiveSource(`blueprint:${blueprint.blueprint_id}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: blueprint.perspective, preserveView: false });
}

async function selectModel(model) {
  setViewCopy("SQL model", model.title, model.description || model.model_id);
  elements.editor.value = model.sql;
  state.sourceSql = model.sql.trim();
  elements.limit.value = model.default_limit;
  setActiveSource(`model:${model.model_id}`);
  setSqlOpen(false);
  closeCatalogOnMobile();
  await runCurrentQuery({ restoreConfig: { plugin: "Datagrid", settings: false }, preserveView: false });
}

async function deleteAnalysis(id) {
  const blueprint = state.session.blueprints.find((candidate) => candidate.blueprint_id === id);
  const response = await fetch(`/api/data/blueprints/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await responseError(response));
  await refreshSessionArtifacts();
  if (state.activeSource === `blueprint:${id}`) setActiveSource(null);
  showToast(blueprint ? `Deleted ${blueprint.title}` : "Deleted analysis");
}

async function refreshSessionArtifacts() {
  const response = await fetch("/api/data/session", { cache: "no-store" });
  if (!response.ok) throw new Error("Could not refresh analysis artifacts");
  const next = validateSession(await response.json());
  state.session.models = next.models;
  state.session.blueprints = next.blueprints;
  renderAnalyses(state.session.blueprints);
  renderModels(state.session.models);
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
  state.saveable = true;
  elements.sqlToggle.disabled = false;
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
  const sectionIds = {
    tables: ["gold-heading", "silver-heading"],
    queries: ["saved-query-heading"],
    views: ["terminal-view-heading"],
    models: ["model-heading"],
    blueprints: ["view-heading"],
  };
  const ids = sectionIds[name] || [];
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
      case "model": {
        const model = state.session.models.find(
          (candidate) => candidate.model_id.toLowerCase() === String(action.model_id).toLowerCase() && candidate.available,
        );
        if (!model) throw new Error(`Unknown model: ${action.model_id}`);
        await selectModel(model);
        return;
      }
      case "blueprint": {
        const blueprint = state.session.blueprints.find(
          (candidate) => candidate.blueprint_id.toLowerCase() === String(action.blueprint_id).toLowerCase() && candidate.available,
        );
        if (!blueprint) throw new Error(`Unknown blueprint: ${action.blueprint_id}`);
        await selectBlueprint(blueprint);
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
        await selectScratch(action.sql, action.limit || 500, action.perspective);
        return;
      case "offers":
        await selectOffers(action);
        return;
      case "launch-plan":
        await selectLaunchPlan(action);
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
    const deleteButton = event.target.closest("[data-delete-analysis]");
    if (deleteButton) {
      void deleteAnalysis(deleteButton.dataset.deleteAnalysis).catch((error) => {
        showToast(error instanceof Error ? error.message : String(error));
      });
      return;
    }
    const loadButton = event.target.closest("[data-blueprint-id]");
    if (!loadButton) return;
    const blueprint = state.session.blueprints.find(
      (candidate) => candidate.blueprint_id === loadButton.dataset.blueprintId,
    );
    if (blueprint) void selectBlueprint(blueprint);
  });

  elements.modelList.addEventListener("click", (event) => {
    const item = event.target.closest("[data-model-id]");
    if (!item) return;
    const model = state.session.models.find(
      (candidate) => candidate.model_id === item.dataset.modelId,
    );
    if (model) void selectModel(model);
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
    void saveCurrentAnalysis(name).catch((error) => {
      showToast(error instanceof Error ? error.message : String(error));
    });
  });
  elements.saveDialog.addEventListener("click", (event) => {
    if (event.target === elements.saveDialog) elements.saveDialog.close();
  });
}

async function initialize() {
  bindEvents();
  setSqlOpen(false);
  try {
    const sessionResponse = await fetch("/api/data/session", { cache: "no-store" });
    if (!sessionResponse.ok) throw new Error("Could not open the local data catalog");
    state.session = validateSession(await sessionResponse.json());
    renderViews(state.session.views);
    renderAnalyses(state.session.blueprints);
    renderModels(state.session.models);
    renderQueryList(state.session.queries, state.session.views);
    renderTableList(state.session.tables, "gold");
    renderTableList(state.session.tables, "silver");

    const run = state.session.run || {};
    elements.runId.textContent = run.run_id || "Unknown run";
    elements.runId.title = run.run_id || "";
    elements.observedAt.textContent = formatObservedAt(run.observed_at);
    await startPerspective();
    const pendingAction = window.ComputeBazaarTerminal?.takePendingAction();
    if (pendingAction) await handleTerminalAction(pendingAction);
    else await openInitialSource();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setViewerState("Terminal unavailable", message, { error: true });
  }
}

void initialize();
