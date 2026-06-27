const state = {
  queries: [],
  selectedQueryKey: null,
  scratch: null,
  currentMode: "catalog",
  currentScratchQuery: null,
  currentRows: [],
};

const nodes = {
  summary: document.getElementById("summary"),
  queryList: document.getElementById("query-list"),
  refreshButton: document.getElementById("refresh-button"),
  scratchSql: document.getElementById("scratch-sql"),
  scratchRunButton: document.getElementById("scratch-run-button"),
  scratchTables: document.getElementById("scratch-tables"),
  resultKicker: document.getElementById("result-kicker"),
  resultTitle: document.getElementById("result-title"),
  resultDescription: document.getElementById("result-description"),
  limitInput: document.getElementById("limit-input"),
  status: document.getElementById("status"),
  table: document.getElementById("result-table"),
  lineagePanel: document.getElementById("lineage-panel"),
  lineageContent: document.getElementById("lineage-content"),
  lineageClose: document.getElementById("lineage-close"),
  refPreview: document.getElementById("ref-preview"),
};

nodes.refreshButton.addEventListener("click", () => loadCatalog({ keepSelection: true }));
nodes.scratchRunButton.addEventListener("click", runScratchSql);
nodes.limitInput.addEventListener("change", () => {
  if (state.currentMode === "scratch") {
    runScratchSql();
  } else if (state.selectedQueryKey) {
    runQuery(state.selectedQueryKey);
  }
});
nodes.lineageClose.addEventListener("click", clearLineage);

loadCatalog();

async function loadCatalog({ keepSelection = false } = {}) {
  setStatus("Loading operator query catalog...");
  try {
    const payload = await loadJson("/api/operator/queries");
    state.queries = payload.queries || [];
    state.scratch = payload.scratch || null;
    renderSummary(payload.manifest);
    renderQueryList();
    renderScratchTables();
    const nextQueryKey =
      keepSelection && state.queries.some((query) => queryKey(query) === state.selectedQueryKey)
        ? state.selectedQueryKey
        : queryKey(state.queries.find((query) => query.available));
    if (nextQueryKey) {
      await runQuery(nextQueryKey);
    } else {
      setStatus("No cataloged SQL queries are available for the latest gold manifest.");
    }
  } catch (error) {
    setStatus(`Could not load operator catalog: ${error.message}`, true);
  }
}

async function runQuery(selectedQueryKey) {
  const query = state.queries.find((candidate) => queryKey(candidate) === selectedQueryKey);
  if (!query || !query.available) return;

  state.selectedQueryKey = selectedQueryKey;
  state.currentMode = "catalog";
  state.currentScratchQuery = null;
  renderQueryList();
  nodes.resultKicker.textContent = "Cataloged DataFusion SQL";
  nodes.resultTitle.textContent = query.title;
  nodes.resultDescription.textContent = query.description;
  setStatus(`Running ${query.title}...`);

  try {
    const limit = Number(nodes.limitInput.value || query.default_limit || 100);
    const versionParam = query.version ? `&version=${encodeURIComponent(query.version)}` : "";
    const payload = await loadJson(`/api/operator/queries/${encodeURIComponent(query.query_id)}?limit=${encodeURIComponent(limit)}${versionParam}`);
    renderSummary(payload.manifest);
    renderTable(payload.rows || []);
    clearLineage();
    setStatus(`${payload.row_count || 0} rows from ${query.tables.join(", ")} · limit ${payload.limit}`);
  } catch (error) {
    setStatus(`Query failed: ${error.message}`, true);
  }
}

async function runScratchSql() {
  const sql = nodes.scratchSql.value || "";
  state.selectedQueryKey = null;
  state.currentMode = "scratch";
  renderQueryList();
  nodes.resultKicker.textContent = "Scratch DataFusion SQL";
  nodes.resultTitle.textContent = "Scratch SQL";
  nodes.resultDescription.textContent = "Read-only SQL over the latest gold tables. Promote useful queries into the Curia catalog.";
  setStatus("Running scratch SQL...");

  try {
    const limit = Number(nodes.limitInput.value || state.scratch?.default_limit || 100);
    const payload = await postJson("/api/operator/sql", { sql, limit });
    state.currentScratchQuery = payload.query || null;
    renderSummary(payload.manifest);
    renderTable(payload.rows || []);
    clearLineage();
    setStatus(`${payload.row_count || 0} scratch rows · ${payload.query?.engine || "datafusion"} · limit ${payload.limit}`);
  } catch (error) {
    setStatus(`Scratch SQL failed: ${error.message}`, true);
  }
}

function renderSummary(manifest) {
  const values = [
    ["Gold run", manifest?.run_id || "unknown"],
    ["Observed", formatDate(manifest?.observed_at)],
    ["Providers", (manifest?.provider_scope || []).join(" · ") || "unknown"],
  ];

  nodes.summary.innerHTML = values
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

function renderScratchTables() {
  if (!state.scratch || !state.scratch.tables?.length) {
    nodes.scratchTables.textContent = "No gold tables are available for scratch SQL yet.";
    return;
  }
  nodes.scratchTables.textContent = `Allowed tables: ${state.scratch.tables.join(", ")}`;
}

function renderQueryList() {
  nodes.queryList.innerHTML = state.queries
    .map((query) => {
      const active = queryKey(query) === state.selectedQueryKey ? " active" : "";
      const disabled = query.available ? "" : " disabled";
      const detail = query.available
        ? `${query.version || "v?"} · ${query.tables.join(", ")}`
        : `missing ${query.missing_tables.join(", ")}`;
      return `
        <button class="query-card${active}" type="button" data-query-key="${escapeHtml(queryKey(query))}"${disabled}>
          <strong>${escapeHtml(query.title)}</strong>
          <span>${escapeHtml(query.description)}</span>
          <em>${escapeHtml(detail)}</em>
        </button>
      `;
    })
    .join("");

  nodes.queryList.querySelectorAll("button[data-query-key]").forEach((button) => {
    button.addEventListener("click", () => runQuery(button.dataset.queryKey));
  });
}

function renderTable(rows) {
  state.currentRows = rows;
  const thead = nodes.table.querySelector("thead");
  const tbody = nodes.table.querySelector("tbody");
  if (!rows.length) {
    thead.innerHTML = "";
    tbody.innerHTML = `<tr><td>No rows returned.</td></tr>`;
    return;
  }

  const columns = Array.from(
    rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set()),
  );

  thead.innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>`;
  tbody.innerHTML = rows
    .map(
      (row, index) => `
        <tr data-row-index="${index}">
          ${columns.map((column) => `<td title="${escapeHtml(formatCell(row[column]))}">${escapeHtml(formatCell(row[column]))}</td>`).join("")}
        </tr>
      `,
    )
    .join("");

  tbody.querySelectorAll("tr[data-row-index]").forEach((rowNode) => {
    rowNode.addEventListener("click", () => inspectRow(Number(rowNode.dataset.rowIndex)));
  });
}

async function inspectRow(index) {
  const row = state.currentRows[index];
  if (state.currentMode === "scratch") {
    inspectScratchRow(index, row);
    return;
  }
  const query = state.queries.find((candidate) => queryKey(candidate) === state.selectedQueryKey);
  if (!row || !query) return;
  nodes.table.querySelectorAll("tbody tr").forEach((node) => node.classList.remove("selected"));
  const selected = nodes.table.querySelector(`tbody tr[data-row-index="${index}"]`);
  if (selected) selected.classList.add("selected");
  nodes.lineagePanel.classList.add("active");
  nodes.lineageContent.innerHTML = `<p class="lineage-empty">Tracing selected row...</p>`;

  try {
    const payload = await postJson("/api/operator/lineage", {
      query_id: query.query_id,
      version: query.version,
      row,
    });
    renderLineage(payload);
  } catch (error) {
    nodes.lineageContent.innerHTML = `<p class="lineage-error">Could not trace row: ${escapeHtml(error.message)}</p>`;
  }
}

function inspectScratchRow(index, row) {
  if (!row) return;
  nodes.table.querySelectorAll("tbody tr").forEach((node) => node.classList.remove("selected"));
  const selected = nodes.table.querySelector(`tbody tr[data-row-index="${index}"]`);
  if (selected) selected.classList.add("selected");
  nodes.lineagePanel.classList.add("active");
  nodes.lineageContent.innerHTML = `
    <div class="lineage-grid">
      <div>
        <h3>Selected scratch row</h3>
        ${renderKeyValues(row)}
      </div>
      <div>
        <h3>Scratch context</h3>
        ${renderKeyValues({
          engine: state.currentScratchQuery?.engine,
          query_hash: state.currentScratchQuery?.query_hash,
          read_only: state.currentScratchQuery?.read_only,
          tables: state.currentScratchQuery?.tables?.join(", "),
        })}
      </div>
    </div>
    <p class="lineage-empty">Scratch SQL is exploratory. Promote useful SQL into <code>queries/curia/</code> to make it versioned, named, and lineage-aware.</p>
  `;
  nodes.refPreview.innerHTML = "";
}

function queryKey(query) {
  if (!query) return null;
  return query.query_key || `${query.query_id}:${query.version || ""}`;
}

function renderLineage(payload) {
  const rowRefs = payload.row_refs || {};
  const trajectory = payload.trajectory || [];
  const providerRuns = payload.provider_runs || [];
  const gold = payload.gold || {};

  nodes.lineageContent.innerHTML = `
    <div class="lineage-grid">
      <div>
        <h3>Selected row</h3>
        ${renderKeyValues(rowRefs)}
      </div>
      <div>
        <h3>Gold context</h3>
        ${renderKeyValues({
          gold_run: gold.manifest?.run_id,
          observed_at: gold.manifest?.observed_at,
          manifest_ref: gold.manifest_ref,
        })}
      </div>
    </div>

    <ol class="trajectory">
      ${trajectory
        .map(
          (step) => `
            <li>
              <span>${escapeHtml(step.layer || "")}</span>
              <strong>${escapeHtml(step.title || "")}</strong>
              <em>${escapeHtml(step.note || "")}</em>
              ${renderRefs(step.refs || [])}
            </li>
          `,
        )
        .join("")}
    </ol>

    <div class="lineage-section">
      <h3>Provider runs</h3>
      ${providerRuns.length ? providerRuns.map(renderProviderRun).join("") : `<p class="lineage-empty">No provider run refs available.</p>`}
    </div>
  `;
  nodes.refPreview.innerHTML = "";
  nodes.lineageContent.querySelectorAll("button[data-ref]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      previewRef(button.dataset.ref);
    });
  });
}

function renderKeyValues(values) {
  return `
    <dl class="kv">
      ${Object.entries(values)
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatCell(value))}</dd>`)
        .join("") || "<dd>No row refs available.</dd>"}
    </dl>
  `;
}

function renderRefs(refs) {
  if (!refs.length) return `<p class="lineage-empty">No refs available for this layer.</p>`;
  return `
    <ul class="refs">
      ${refs
        .map(
          (ref) => `
            <li title="${escapeHtml(ref)}">
              <code>${escapeHtml(ref)}</code>
              <button type="button" data-ref="${escapeHtml(ref)}">Preview</button>
            </li>
          `,
        )
        .join("")}
    </ul>
  `;
}

function renderProviderRun(run) {
  return `
    <details class="provider-run">
      <summary>${escapeHtml(run.provider || "provider")} · ${escapeHtml(run.run_id || "unknown run")}</summary>
      ${renderKeyValues({
        observed_at: run.observed_at,
        raw_ref: run.raw_ref,
        normalized_ref: run.normalized_ref,
        manifest_ref: run.manifest_ref,
        raw_offer_count: run.raw_offer_count,
        normalized_offer_count: run.normalized_offer_count,
        published_events: run.published_events,
      })}
    </details>
  `;
}

function clearLineage() {
  nodes.table.querySelectorAll("tbody tr").forEach((node) => node.classList.remove("selected"));
  nodes.lineagePanel.classList.remove("active");
  nodes.lineageContent.innerHTML = "";
  nodes.refPreview.innerHTML = "";
}

async function previewRef(ref) {
  if (!ref) return;
  nodes.refPreview.innerHTML = `<p class="lineage-empty">Loading ref preview...</p>`;
  try {
    const payload = await postJson("/api/operator/ref-preview", {
      ref,
      max_bytes: 65536,
    });
    renderRefPreview(payload);
  } catch (error) {
    nodes.refPreview.innerHTML = `<p class="lineage-error">Could not preview ref: ${escapeHtml(error.message)}</p>`;
  }
}

function renderRefPreview(payload) {
  const content = payload.previewable
    ? renderPreviewPayload(payload)
    : `<p class="lineage-empty">${escapeHtml(payload.message || "Preview unavailable.")}</p>`;
  nodes.refPreview.innerHTML = `
    <div class="panel-head">
      <span>Ref preview</span>
      <button type="button" id="ref-preview-clear">Close</button>
    </div>
    <div class="ref-meta">
      <code title="${escapeHtml(payload.ref || "")}">${escapeHtml(payload.ref || "")}</code>
      <span>${escapeHtml(payload.kind || "ref")}${payload.byte_count ? ` · ${escapeHtml(formatCell(payload.byte_count))} bytes` : ""}${payload.truncated ? " · truncated" : ""}</span>
    </div>
    ${content}
  `;
  document.getElementById("ref-preview-clear")?.addEventListener("click", () => {
    nodes.refPreview.innerHTML = "";
  });
}

function renderPreviewPayload(payload) {
  if (payload.json_summary || payload.json_preview) {
    return `
      ${payload.json_summary ? `<pre>${escapeHtml(JSON.stringify(payload.json_summary, null, 2))}</pre>` : ""}
      ${payload.json_preview ? `<pre>${escapeHtml(JSON.stringify(payload.json_preview, null, 2))}</pre>` : ""}
    `;
  }
  return `<pre>${escapeHtml(payload.text || "")}</pre>`;
}

function setStatus(message, isError = false) {
  nodes.status.textContent = message;
  nodes.status.style.borderColor = isError ? "#9f3a2f" : "";
  nodes.status.style.color = isError ? "#9f3a2f" : "";
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // Keep the HTTP status text when no JSON body is available.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // Keep the HTTP status text when no JSON body is available.
    }
    throw new Error(detail);
  }
  return response.json();
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDate(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
