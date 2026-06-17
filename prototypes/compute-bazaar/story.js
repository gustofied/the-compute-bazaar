(async function bootComputeBazaarStory() {
  const params = new URLSearchParams(window.location.search);
  const dataBase = (params.get("data") || "../../data/dashboard/compute-bazaar").replace(/\/$/, "");

  const sourceNote = document.getElementById("source-note");
  setSourceNote(sourceNote, `Reading <code>${escapeHtml(dataBase)}</code>.`, "loading");

  if (!window.d3) {
    setSourceNote(sourceNote, "D3 did not load, so the market snapshot cannot render.", "error");
    return;
  }

  try {
    const [manifest, indexPayload, comparisonPayload, listingsPayload] = await Promise.all([
      loadJson(`${dataBase}/manifest.json`),
      loadJson(`${dataBase}/latest-index.json`),
      loadJson(`${dataBase}/provider-comparison.json`),
      loadJson(`${dataBase}/listings-sample.json`),
    ]);

    renderStats(manifest);
    renderFloorChart(indexPayload.rows || []);
    renderProviderTable(comparisonPayload.rows || []);
    renderListingStrip(listingsPayload.rows || []);
    setSourceNote(
      sourceNote,
      `Snapshot <code>${escapeHtml(manifest.run_id || "unknown")}</code> · ${formatDate(manifest.observed_at)} · source <code>${escapeHtml(dataBase)}</code>`,
      "ok",
    );
  } catch (error) {
    setSourceNote(
      sourceNote,
      `Could not load market snapshots from ${escapeHtml(dataBase)}: ${escapeHtml(error.message)}`,
      "error",
    );
  }
})();

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
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

function renderListingStrip(rows) {
  const data = rows.slice(0, 12);
  const strip = d3.select("#listing-strip");

  if (!data.length) {
    strip.html('<p class="empty-cell">No fresh listing sample available yet.</p>');
    return;
  }

  strip
    .selectAll(".listing-card")
    .data(data)
    .join("div")
    .attr("class", "listing-card")
    .html(
      (row) => `
        <strong>${escapeHtml(row.gpu_model)} · $${formatPrice(row.price_usd_gpu_hr)}/GPU hr</strong>
        <span>${escapeHtml(formatProvider(row.provider))} · ${escapeHtml(row.country || "unknown")} · ${escapeHtml(row.region || "unknown")}</span>
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

function setSourceNote(node, html, status) {
  if (!node) return;
  node.classList.remove("is-loading", "is-ok", "is-error");
  node.classList.add(`is-${status}`);
  node.innerHTML = html;
}
