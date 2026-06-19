(async function bootComputeBazaarStory() {
  const params = new URLSearchParams(window.location.search);
  const dataBase = (params.get("data") || defaultDataBase()).replace(/\/$/, "");
  const refreshMs = parseRefreshMs(params);

  const sourceNote = document.getElementById("source-note");
  setSourceNote(sourceNote, `Reading <code>${escapeHtml(dataBase)}</code>.`, "loading");

  if (!window.d3) {
    setSourceNote(sourceNote, "D3 did not load, so the market snapshot cannot render.", "error");
    return;
  }

  await loadAndRenderDashboard(dataBase, sourceNote);
  if (refreshMs > 0) {
    window.setInterval(() => {
      loadAndRenderDashboard(dataBase, sourceNote);
    }, refreshMs);
  }
})();

async function loadAndRenderDashboard(dataBase, sourceNote) {
  try {
    const [
      manifest,
      marketRun,
      marketHistory,
      indexPayload,
      indexHistoryPayload,
      indexQualityPayload,
      constituentPayload,
      comparisonPayload,
      listingsPayload,
    ] = await Promise.all([
      loadJson(`${dataBase}/manifest.json`),
      loadOptionalJson(`${dataBase}/market-run.json`),
      loadOptionalJson(`${dataBase}/market-history.json`),
      loadJson(`${dataBase}/latest-index.json`),
      loadOptionalJson(`${dataBase}/index-history.json`),
      loadOptionalJson(`${dataBase}/index-quality.json`),
      loadOptionalJson(`${dataBase}/index-constituents.json`),
      loadJson(`${dataBase}/provider-comparison.json`),
      loadJson(`${dataBase}/listings-sample.json`),
    ]);

    renderStats(manifest);
    renderHeartbeat(marketRun, manifest);
    renderOps(marketRun, manifest);
    renderQuality(marketRun, indexQualityPayload?.rows || []);
    renderFloorChart(indexPayload.rows || []);
    renderIndexHistoryChart(indexHistoryPayload?.rows || []);
    renderConstituentTable(constituentPayload?.rows || []);
    renderProviderTable(comparisonPayload.rows || []);
    renderHistoryTable(marketHistory?.rows || []);
    renderOfferTable(listingsPayload.rows || []);
    renderSourceState(sourceNote, manifest, marketRun, dataBase);
  } catch (error) {
    setSourceNote(
      sourceNote,
      `Could not load market snapshots from ${escapeHtml(dataBase)}: ${escapeHtml(error.message)}`,
      "error",
    );
  }
}

function defaultDataBase() {
  if (window.location.protocol === "file:") return "../../data/dashboard/compute-bazaar";
  return "/api/dashboard-snapshots";
}

function parseRefreshMs(params) {
  const raw = params.get("refreshMs") || params.get("refresh") || "300000";
  const numeric = Number(raw);
  if (!Number.isFinite(numeric) || numeric < 0) return 300000;
  return numeric;
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadOptionalJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function renderSourceState(node, manifest, marketRun, dataBase) {
  const observedAt = marketRun?.observed_at || manifest.observed_at;
  const exportedAt = manifest.dashboard_exported_at;
  const observedAge = minutesSince(observedAt);
  const exportedAge = minutesSince(exportedAt);
  const stale = Number.isFinite(observedAge) && observedAge > 90;
  const sourceKind = inferSourceKind(dataBase);
  const runId = marketRun?.market_run_id || manifest.run_id || "unknown";
  const ageText = Number.isFinite(observedAge)
    ? `observed ${formatAgePhrase(observedAge)}`
    : `observed ${formatDate(observedAt)}`;
  const syncText = exportedAt
    ? `exported ${formatAgePhrase(exportedAge)}`
    : "export timestamp unavailable";
  const caution = stale
    ? "This view may be behind the live Windmill/S3 feed; sync or export snapshots to redraw it."
    : "This view is fresh enough for local inspection.";

  setSourceNote(
    node,
    `${escapeHtml(sourceKind)} · <code>${escapeHtml(runId)}</code> · ${escapeHtml(ageText)} · ${escapeHtml(syncText)} · source <code>${escapeHtml(dataBase)}</code><br>${escapeHtml(caution)}`,
    stale ? "stale" : "ok",
  );
}

function inferSourceKind(dataBase) {
  if (/^https?:\/\//i.test(dataBase)) return "Remote/public JSON feed";
  if (dataBase === "/api/dashboard-snapshots") return "FastAPI S3/local snapshot proxy";
  if (/^s3:\/\//i.test(dataBase)) return "S3 JSON feed";
  return "Local cached JSON snapshot";
}

function minutesSince(value) {
  if (!value) return NaN;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return NaN;
  return Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
}

function formatAge(minutes) {
  if (!Number.isFinite(minutes)) return "unknown";
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 48) return rest ? `${hours}h ${rest}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function formatAgePhrase(minutes) {
  const age = formatAge(minutes);
  return age === "just now" || age === "unknown" ? age : `${age} ago`;
}

function renderStats(manifest) {
  const providers = manifest.provider_scope || [];
  const rows = manifest.row_counts || {};
  const stats = [
    [providers.length || 0, "providers"],
    [rows.fact_gpu_listings || 0, "market listings"],
    [rows.fact_price_index_values || 0, "index products"],
  ];

  d3.select("#market-stats")
    .selectAll("div")
    .data(stats)
    .join("div")
    .html(([value, label]) => `<span class="stat-value">${value}</span><span class="stat-label">${label}</span>`);
}

function renderHeartbeat(marketRun, manifest) {
  const node = d3.select("#market-heartbeat");
  if (!node.node()) return;

  const checks = marketRun?.checks || {};
  const checksText = Object.entries(checks)
    .map(([name, status]) => `${formatProvider(name)} ${status}`)
    .join(" · ");
  const rows = [
    ["Market run", marketRun?.market_run_id || manifest.run_id || "snapshot only"],
    ["Status", marketRun?.status || "gold snapshot"],
    ["Checks", checksText || "market heartbeat pending"],
  ];

  node
    .selectAll("div")
    .data(rows)
    .join("div")
    .html(([label, value]) => `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`);
}

function renderOps(marketRun, manifest) {
  const node = d3.select("#ops-strip");
  if (!node.node()) return;

  const providers = marketRun?.providers || manifest.provider_scope || [];
  const rowCounts = marketRun?.row_counts || {};
  const providerQuality = marketRun?.data_quality?.providers || {};
  const observedAt = marketRun?.observed_at || manifest.observed_at;
  const providerSummary =
    Object.entries(providerQuality)
      .map(([name, quality]) => {
        const raw = quality?.raw_offer_count ?? "?";
        const normalized = quality?.normalized_offer_count ?? "?";
        return `${formatProvider(name)} ${raw}/${normalized}`;
      })
      .join(" · ") || "raw/normalized counts pending";

  const rows = [
    ["Orchestrator", "Windmill market_hourly", marketRun ? `last run ${formatDate(observedAt)}` : "awaiting market run"],
    ["Providers", providers.map(formatProvider).join(" · ") || "pending", providerSummary],
    [
      "Lake Product",
      `${rowCounts.listings ?? manifest.row_counts?.fact_gpu_listings ?? 0} listings`,
      `${rowCounts.index_values ?? manifest.row_counts?.fact_price_index_values ?? 0} index values`,
    ],
    ["Surface", "DataFusion gold -> JSON -> D3", "browser reads public-safe snapshots only"],
  ];

  node
    .selectAll("div")
    .data(rows)
    .join("div")
    .html(
      ([label, value, detail]) => `
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        <em>${escapeHtml(detail)}</em>
      `,
    );
}

function renderQuality(marketRun, indexQualityRows) {
  const node = d3.select("#quality-strip");
  if (!node.node()) return;

  const checks = marketRun?.checks || {};
  const badChecks = Object.entries(checks).filter(([, status]) => !["ok", "skipped"].includes(String(status)));
  const providers = marketRun?.data_quality?.providers || {};
  const providerWarnings = Object.entries(providers).flatMap(([name, quality]) => {
    const warnings = [];
    if ((quality?.unknown_gpu_names || []).length) {
      warnings.push(`${formatProvider(name)} unknown GPUs ${quality.unknown_gpu_names.length}`);
    }
    if (Number(quality?.published_events || 0) <= 0) {
      warnings.push(`${formatProvider(name)} no Kafka events`);
    }
    return warnings;
  });
  const excluded = d3.sum(indexQualityRows, (row) => Number(row.excluded_count || 0));
  const included = d3.sum(indexQualityRows, (row) => Number(row.included_count || 0));
  const status = badChecks.length || providerWarnings.length ? "watch" : "ok";
  const details = [
    ...badChecks.map(([name, check]) => `${formatProvider(name)} ${check}`),
    ...providerWarnings,
    `${included} included index candidates`,
    `${excluded} excluded candidates`,
  ];
  const rows = [
    [
      "Quality",
      status === "ok" ? "clean heartbeat" : "needs attention",
      details.join(" · ") || "waiting for quality snapshot",
    ],
  ];

  node
    .classed("has-warning", status !== "ok")
    .selectAll("div")
    .data(rows)
    .join("div")
    .html(
      ([label, value, detail]) => `
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        <em>${escapeHtml(detail)}</em>
      `,
    );
}

function renderFloorChart(rows) {
  const data = rows
    .filter((row) => Number.isFinite(Number(row.floor_usd_gpu_hr)))
    .slice(0, 12);

  const container = d3.select("#floor-chart");
  container.selectAll("*").remove();

  if (!data.length) {
    container.append("p").text("No index data available yet.");
    return;
  }

  const width = Math.max(640, container.node().clientWidth || 640);
  const rowHeight = 28;
  const margin = { top: 8, right: 96, bottom: 28, left: 148 };
  const height = margin.top + margin.bottom + data.length * rowHeight;

  const svg = container
    .append("svg")
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("width", "100%")
    .attr("height", height);

  const x = d3
    .scaleLinear()
    .domain([0, d3.max(data, (row) => Number(row.floor_usd_gpu_hr)) || 1])
    .nice()
    .range([margin.left, width - margin.right]);

  const y = d3
    .scaleBand()
    .domain(data.map((row) => row.gpu_model))
    .range([margin.top, height - margin.bottom])
    .padding(0.28);

  svg
    .append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).ticks(4).tickFormat((value) => `$${formatPrice(value)}`))
    .call((g) => g.select(".domain").attr("stroke", "#ddd"))
    .call((g) => g.selectAll(".tick line").attr("stroke", "#eee"))
    .call((g) => g.selectAll("text").attr("class", "axis-label"));

  svg
    .append("g")
    .selectAll("text")
    .data(data)
    .join("text")
    .attr("class", "bar-label")
    .attr("x", margin.left - 10)
    .attr("y", (row) => y(row.gpu_model) + y.bandwidth() / 2)
    .attr("dy", "0.32em")
    .attr("text-anchor", "end")
    .text((row) => row.gpu_model);

  svg
    .append("g")
    .selectAll("rect")
    .data(data)
    .join("rect")
    .attr("x", margin.left)
    .attr("y", (row) => y(row.gpu_model))
    .attr("width", (row) => Math.max(1, x(Number(row.floor_usd_gpu_hr)) - margin.left))
    .attr("height", y.bandwidth())
    .attr("fill", "#2c5f2d")
    .attr("fill-opacity", 0.72);

  svg
    .append("g")
    .selectAll("text")
    .data(data)
    .join("text")
    .attr("class", "bar-label")
    .attr("x", (row) => x(Number(row.floor_usd_gpu_hr)) + 7)
    .attr("y", (row) => y(row.gpu_model) + y.bandwidth() / 2)
    .attr("dy", "0.32em")
    .text((row) => `$${formatPrice(row.floor_usd_gpu_hr)}`);
}

function renderIndexHistoryChart(rows) {
  const container = d3.select("#index-history-chart");
  container.selectAll("*").remove();

  const points = rows
    .map((row) => {
      const observedAt = row.gold_observed_at || row.latest_observed_at || row.calculated_at;
      const observed = new Date(observedAt);
      const price = Number(row.floor_usd_gpu_hr);
      return {
        gpu_model: String(row.gpu_model || "unknown"),
        observed,
        price,
        offer_count: Number(row.offer_count || 0),
      };
    })
    .filter((row) => row.gpu_model && Number.isFinite(row.price) && row.price > 0)
    .filter((row) => !Number.isNaN(row.observed.getTime()));

  const series = selectHistorySeries(points);
  if (!series.length) {
    container
      .append("p")
      .text("Waiting for at least two market runs before drawing an index history line.");
    return;
  }

  const plottedPoints = series.flatMap((entry) => entry.values);
  const width = Math.max(680, container.node().clientWidth || 680);
  const height = 330;
  const margin = { top: 16, right: 148, bottom: 38, left: 66 };

  let [minDate, maxDate] = d3.extent(plottedPoints, (row) => row.observed);
  if (!minDate || !maxDate) return;
  if (minDate.getTime() === maxDate.getTime()) {
    minDate = new Date(minDate.getTime() - 60 * 60 * 1000);
    maxDate = new Date(maxDate.getTime() + 60 * 60 * 1000);
  }

  const x = d3.scaleTime().domain([minDate, maxDate]).range([margin.left, width - margin.right]);
  const y = d3
    .scaleLinear()
    .domain([0, d3.max(plottedPoints, (row) => row.price) || 1])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const color = d3.scaleOrdinal(series.map((entry) => entry.gpu_model), d3.schemeTableau10);

  const svg = container
    .append("svg")
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("width", "100%")
    .attr("height", height);

  svg
    .append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x).ticks(4).tickSizeOuter(0))
    .call((g) => g.select(".domain").attr("stroke", "#ddd"))
    .call((g) => g.selectAll(".tick line").attr("stroke", "#eee"))
    .call((g) => g.selectAll("text").attr("class", "axis-label"));

  svg
    .append("g")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y).ticks(5).tickFormat((value) => `$${formatPrice(value)}`))
    .call((g) => g.select(".domain").attr("stroke", "#ddd"))
    .call((g) => g.selectAll(".tick line").attr("stroke", "#eee"))
    .call((g) => g.selectAll("text").attr("class", "axis-label"));

  const line = d3
    .line()
    .x((row) => x(row.observed))
    .y((row) => y(row.price));

  const group = svg
    .append("g")
    .selectAll("g")
    .data(series)
    .join("g");

  group
    .append("path")
    .attr("class", "history-line")
    .attr("d", (entry) => line(entry.values))
    .attr("stroke", (entry) => color(entry.gpu_model));

  group
    .selectAll("circle")
    .data((entry) => entry.values.map((value) => ({ ...value, gpu_model: entry.gpu_model })))
    .join("circle")
    .attr("class", "history-dot")
    .attr("cx", (row) => x(row.observed))
    .attr("cy", (row) => y(row.price))
    .attr("r", 3)
    .attr("fill", (row) => color(row.gpu_model));

  group
    .append("text")
    .attr("class", "line-label")
    .attr("x", width - margin.right + 12)
    .attr("y", (entry) => y(entry.values.at(-1).price))
    .attr("dy", "0.32em")
    .attr("fill", (entry) => color(entry.gpu_model))
    .text((entry) => entry.gpu_model);
}

function selectHistorySeries(points) {
  const priority = ["H100_80GB", "H200_141GB", "B200_180GB", "B300_288GB", "RTX4090_24GB", "RTX5090_32GB"];
  const priorityRank = new Map(priority.map((name, index) => [name, index]));
  const grouped = Array.from(d3.group(points, (row) => row.gpu_model), ([gpu_model, values]) => ({
    gpu_model,
    values: values.sort((a, b) => d3.ascending(a.observed, b.observed)),
  }))
    .filter((entry) => entry.values.length >= 2)
    .sort((a, b) => {
      const aRank = priorityRank.has(a.gpu_model) ? priorityRank.get(a.gpu_model) : Number.POSITIVE_INFINITY;
      const bRank = priorityRank.has(b.gpu_model) ? priorityRank.get(b.gpu_model) : Number.POSITIVE_INFINITY;
      return (
        d3.ascending(aRank, bRank) ||
        d3.descending(a.values.length, b.values.length) ||
        d3.ascending(a.gpu_model, b.gpu_model)
      );
    });

  return grouped.slice(0, 5);
}

function renderConstituentTable(rows) {
  const tbody = d3.select("#constituent-table tbody");
  const data = rows.slice(0, 18);

  if (!data.length) {
    tbody.html('<tr><td colspan="5" class="empty-cell">No index constituent rows exported yet.</td></tr>');
    return;
  }

  tbody
    .selectAll("tr")
    .data(data)
    .join("tr")
    .html(
      (row) => `
        <td>${escapeHtml(row.gpu_model)}</td>
        <td>${escapeHtml(formatProvider(row.provider))}</td>
        <td>$${formatPrice(row.price_usd_gpu_hr)}</td>
        <td>${row.included ? "yes" : "no"}</td>
        <td>${escapeHtml(row.exclusion_reason || (row.is_floor_constituent ? "floor" : "candidate"))}</td>
      `,
    );
}

function renderProviderTable(rows) {
  const tbody = d3.select("#provider-table tbody");
  const data = rows.slice(0, 24);

  if (!data.length) {
    tbody.html('<tr><td colspan="5" class="empty-cell">No available provider comparison rows yet.</td></tr>');
    return;
  }

  tbody
    .selectAll("tr")
    .data(data)
    .join("tr")
    .html(
      (row) => `
        <td>${escapeHtml(row.gpu_model)}</td>
        <td>${escapeHtml(formatProvider(row.provider))}</td>
        <td>$${formatPrice(row.floor_usd_gpu_hr)}</td>
        <td>${row.listing_count ?? ""}</td>
        <td>${row.country_count ?? ""}</td>
      `,
    );
}

function renderHistoryTable(rows) {
  const tbody = d3.select("#history-table tbody");
  const data = rows.slice(0, 12);

  if (!data.length) {
    tbody.html('<tr><td colspan="5" class="empty-cell">No market-run history exported yet.</td></tr>');
    return;
  }

  tbody
    .selectAll("tr")
    .data(data)
    .join("tr")
    .html(
      (row) => `
        <td>${escapeHtml(shortRun(row.market_run_id))}</td>
        <td>${escapeHtml(row.status || "unknown")}</td>
        <td>${escapeHtml(formatDate(row.observed_at))}</td>
        <td>${row.row_counts?.listings ?? ""}</td>
        <td>${row.row_counts?.index_values ?? ""}</td>
      `,
    );
}

function renderOfferTable(rows) {
  const data = rows.slice(0, 24);
  const tbody = d3.select("#offer-table tbody");

  if (!data.length) {
    tbody.html('<tr><td colspan="8" class="empty-cell">No normalized offer rows exported yet.</td></tr>');
    return;
  }

  tbody
    .selectAll("tr")
    .data(data)
    .join("tr")
    .html(
      (row) => `
        <td>${escapeHtml(row.gpu_model)}</td>
        <td>${escapeHtml(formatProvider(row.provider))}</td>
        <td>$${formatPrice(row.price_usd_gpu_hr)}</td>
        <td>$${formatPrice(row.price_usd_instance_hr ?? row.price_usd_hr)}</td>
        <td>${escapeHtml(row.gpu_count ?? "")}</td>
        <td>${escapeHtml(formatLocation(row.country, row.region))}</td>
        <td>${escapeHtml(row.availability_status || "unknown")}</td>
        <td>${row.has_raw_evidence ? "bronze" : "missing"}</td>
      `,
    );
}

function formatPrice(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "n/a";
  if (numeric < 1) return numeric.toFixed(3);
  if (numeric < 10) return numeric.toFixed(2);
  return numeric.toFixed(1);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatProvider(value) {
  const text = String(value || "");
  if (text.toLowerCase() === "lium") return "Lium";
  if (text.toLowerCase() === "vast") return "Vast";
  return text;
}

function formatLocation(country, region) {
  const parts = [country, region].filter((part) => part != null && String(part).trim());
  return parts.length ? parts.join(" · ") : "unknown";
}

function formatDate(value) {
  if (!value) return "unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function shortRun(value) {
  const text = String(value || "");
  if (text.length <= 34) return text;
  return `${text.slice(0, 18)}...${text.slice(-10)}`;
}

function setSourceNote(node, html, status) {
  if (!node) return;
  node.classList.remove("is-loading", "is-ok", "is-error", "is-stale");
  node.classList.add(`is-${status}`);
  node.innerHTML = html;
}
