import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

const $ = (selector) => document.querySelector(selector);

const elements = {
  hostList: $("#host-list"),
  hostCount: $("#host-count"),
  refreshState: $("#refresh-state"),
  overviewToggle: $("#overview-toggle"),
  overview: $("#overview-view"),
  overviewRows: $("#overview-rows"),
  overviewState: $("#overview-state"),
  empty: $("#fleet-empty"),
  view: $("#machine-view"),
  provider: $("#machine-provider"),
  name: $("#machine-name"),
  subtitle: $("#machine-subtitle"),
  readiness: $("#readiness"),
  termination: $("#termination"),
  systemMeta: $("#system-meta"),
  cpuValue: $("#cpu-value"),
  memoryValue: $("#memory-value"),
  diskValue: $("#disk-value"),
  cpuMeter: $("#cpu-meter"),
  memoryMeter: $("#memory-meter"),
  diskMeter: $("#disk-meter"),
  gpuMeta: $("#gpu-meta"),
  gpuList: $("#gpu-list"),
  chart: $("#telemetry-chart"),
  historyTime: $("#history-time"),
  historyGpu: $("#history-gpu"),
  historyVram: $("#history-vram"),
  historyCpu: $("#history-cpu"),
  checks: $("#check-list"),
  checkSummary: $("#check-summary"),
  workloadCount: $("#workload-count"),
  workloadList: $("#workload-list"),
  processCount: $("#process-count"),
  processList: $("#process-list"),
};

const state = {
  session: null,
  hostId: null,
  view: "detail",
  timer: null,
  refreshing: false,
  snapshots: new Map(),
  errors: new Map(),
  samples: new Map(),
  plot: null,
};

const checkLabels = {
  ssh: "SSH",
  gpu_count: "GPU",
  gpu_model: "Model",
  driver: "Driver",
  disk: "Disk",
  gpu_memory: "VRAM",
  temperature: "Temp",
  pcie_link: "PCIe",
  gpu_execution: "CUDA",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value, digits = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function percent(used, total) {
  return Number(total) > 0 ? clampPercent((Number(used) / Number(total)) * 100) : 0;
}

function formatMemory(mb) {
  return Number.isFinite(Number(mb)) ? `${(Number(mb) / 1024).toFixed(1)} GB` : "—";
}

function validNumbers(values) {
  return values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map(Number)
    .filter(Number.isFinite);
}

function average(values) {
  const valid = validNumbers(values);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

function sum(values) {
  const valid = validNumbers(values);
  return valid.length ? valid.reduce((total, value) => total + value, 0) : null;
}

function maximum(values) {
  const valid = validNumbers(values);
  return valid.length ? Math.max(...valid) : null;
}

function gpuSummary(payload) {
  const devices = payload.gpus ?? [];
  return {
    utilization: average(devices.map((gpu) => gpu.utilization_pct)),
    memoryUsed: sum(devices.map((gpu) => gpu.memory_used_mb)),
    memoryTotal: sum(devices.map((gpu) => gpu.memory_total_mb)),
    temperature: maximum(devices.map((gpu) => gpu.temperature_c)),
    power: sum(devices.map((gpu) => gpu.power_draw_w)),
  };
}

function machineGpuLabel(machine, payload = null) {
  const devices = payload?.gpus ?? [];
  const names = [...new Set(devices.map((gpu) => gpu.name).filter(Boolean))];
  return `${devices.length || machine.expected_gpu_count || "—"} × ${names.join(", ") || machine.expected_gpu_model || "NVIDIA GPU"}`;
}

function machineSubtitle(machine, payload = null) {
  const parts = [machineGpuLabel(machine, payload)];
  const gpuPrice = optionalNumber(machine.price_usd_gpu_hr);
  const instancePrice = optionalNumber(machine.price_usd_instance_hr);
  if (Number.isFinite(gpuPrice)) parts.push(`$${number(gpuPrice, 2)}/GPU-h`);
  if (Number.isFinite(instancePrice) && (!Number.isFinite(gpuPrice) || Math.abs(instancePrice - gpuPrice) > 0.0001)) {
    parts.push(`$${number(instancePrice, 2)}/h`);
  }
  return parts.join("  |  ");
}

function optionalNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function lineageLabel(machine) {
  const parts = [];
  if (machine.operator) {
    parts.push(machine.operator);
  } else if (machine.intermediary || machine.source) {
    parts.push(machine.intermediary || machine.source, "OPERATOR —");
  } else {
    return "ATTACHED";
  }
  if (machine.intermediary && machine.intermediary !== machine.operator) {
    parts.push(`VIA ${machine.intermediary}`);
  }
  if (machine.source && machine.source !== machine.intermediary && machine.source !== machine.operator) {
    parts.push(`SOURCE ${machine.source}`);
  }
  return parts.join("  |  ");
}

function stateLabel(value) {
  return {
    running: "UP",
    ready: "READY",
    healthy: "READY",
    terminated: "OFF",
    stopped: "OFF",
    degraded: "WARN",
    stale: "STALE",
    fault: "ERR",
    not_ready: "FAIL",
    not_verified: "UNCHECKED",
  }[value] ?? String(value ?? "—").replaceAll("_", " ").toUpperCase();
}

function activeHosts() {
  return (state.session?.hosts ?? []).filter((host) => host.ssh_ready && host.state === "running");
}

function orderedHosts() {
  return [...(state.session?.hosts ?? [])].sort((left, right) => {
    const leftActive = left.ssh_ready && left.state === "running";
    const rightActive = right.ssh_ready && right.state === "running";
    return Number(rightActive) - Number(leftActive);
  });
}

async function loadSession() {
  const response = await fetch("/api/fleet/session", { cache: "no-store" });
  if (!response.ok) throw new Error("Fleet unavailable");
  state.session = await response.json();
  const active = activeHosts();
  if (!active.some((host) => host.host_id === state.hostId)) state.hostId = active[0]?.host_id ?? null;
}

function hostReading(host) {
  if (host.state !== "running") return '<span class="host-reading"><span>OFF</span><span>—</span></span>';
  if (!host.ssh_ready) return '<span class="host-reading"><span>NO SSH</span><span>—</span></span>';
  const payload = state.snapshots.get(host.host_id);
  if (state.errors.has(host.host_id)) return '<span class="host-reading"><span>ERR</span><span>—</span></span>';
  if (!payload) return '<span class="host-reading"><span>WAIT</span><span>—</span></span>';
  const gpu = gpuSummary(payload);
  return `<span class="host-reading"><span>${payload.monitor?.status === "stale" ? "STALE" : `GPU ${number(gpu.utilization)}%`}</span><span>${number(gpu.temperature)}°C</span></span>`;
}

function renderHosts() {
  const hosts = activeHosts();
  const total = state.session?.hosts?.length ?? 0;
  elements.hostCount.textContent = `${hosts.length} UP / ${total}`;
  elements.hostList.innerHTML = hosts.map((host) => {
    const payload = state.snapshots.get(host.host_id);
    const failed = state.errors.has(host.host_id);
    const status = failed ? "fault" : payload?.monitor?.status === "stale" ? "stale" : host.state;
    return `
      <button class="host-button ${host.host_id === state.hostId ? "active" : ""} ${failed ? "fault" : ""}" type="button" data-host-id="${escapeHtml(host.host_id)}">
        <span class="host-name">${escapeHtml(host.name)}</span>
        <span class="host-meta"><span>${escapeHtml(machineGpuLabel(host, payload))}</span><span class="host-status">${escapeHtml(stateLabel(status))}</span></span>
        ${hostReading(host)}
      </button>`;
  }).join("");
  renderOverview();
}

function countdown(machine) {
  if (!machine.terminate_at) return "TTL —";
  const remaining = new Date(machine.terminate_at).getTime() - Date.now();
  return remaining <= 0 ? "TTL 0m" : `TTL ${Math.max(1, Math.ceil(remaining / 60000))}m`;
}

function captureSample(payload) {
  const gpu = gpuSummary(payload);
  const samples = state.samples.get(payload.machine.host_id) ?? (payload.telemetry ?? []).map((sample) => ({
    observedAt: sample.observed_at,
    gpu: Number(sample.gpu_utilization_pct) || 0,
    vram: percent(sample.gpu_memory_used_mb, sample.gpu_memory_total_mb),
    cpu: Number(sample.cpu_utilization_pct) || 0,
  }));
  if (samples.at(-1)?.observedAt === payload.observed_at) {
    state.samples.set(payload.machine.host_id, samples.slice(-180));
    return;
  }
  samples.push({
    observedAt: payload.observed_at,
    gpu: Number(gpu.utilization) || 0,
    vram: percent(gpu.memoryUsed, gpu.memoryTotal),
    cpu: Number(payload.system.cpu_utilization_pct) || 0,
  });
  state.samples.set(payload.machine.host_id, samples.slice(-180));
}

function checkValue(check) {
  const detail = String(check.detail ?? "—");
  if (check.check === "ssh") return check.status === "pass" ? "OK" : "ERR";
  if (check.check === "gpu_execution") return check.status === "pass" ? "OK" : check.status === "fail" ? "ERR" : "—";
  if (check.check === "gpu_count") {
    const detected = detail.match(/detected\s+(\d+)/i)?.[1];
    const expected = detail.match(/expected\s+(\d+)/i)?.[1];
    return detected ? `${detected}${expected ? ` / ${expected}` : ""}` : detail;
  }
  if (check.check === "gpu_model") return detail.replace(/^detected\s+/i, "").replace(/;\s*expected.*$/i, "");
  if (check.check === "disk") return detail.replace(/\s+free$/i, "");
  if (check.check === "gpu_memory") {
    const values = [...detail.matchAll(/:\s*(\d+)\s*MB/gi)].map((match) => Number(match[1]));
    if (values.length) return `${values.length > 1 ? `${values.length} × ` : ""}${[...new Set(values.map((value) => (value / 1024).toFixed(0)))].join("/")} GB`;
  }
  if (check.check === "temperature") {
    const values = [...detail.matchAll(/:\s*(\d+)\s*C/gi)].map((match) => Number(match[1]));
    if (values.length) return `${Math.max(...values)} C`;
  }
  if (check.check === "pcie_link") {
    const link = detail.match(/Gen\s+(\d+).*?x(\d+)/i);
    if (link) return `G${link[1]} ×${link[2]}`;
  }
  return detail;
}

function gpuCard(gpu, index) {
  const vram = percent(gpu.memory_used_mb, gpu.memory_total_mb);
  const utilization = clampPercent(gpu.utilization_pct);
  const power = percent(gpu.power_draw_w, gpu.power_limit_w);
  const temperature = percent(gpu.temperature_c, gpu.temperature_limit_c || 83);
  const pcie = gpu.pcie_generation_current
    ? `PCIe G${gpu.pcie_generation_current}/${gpu.pcie_generation_max ?? "—"} ×${gpu.pcie_width_current ?? "—"}/${gpu.pcie_width_max ?? "—"}`
    : "PCIe —";
  const stat = (label, className, value, text) => `
    <div class="gpu-stat ${className}">
      <span>${label}</span><div class="gpu-meter"><i style="width:${clampPercent(value)}%"></i></div><output>${escapeHtml(text)}</output>
    </div>`;
  return `
    <article class="gpu-card">
      <div class="gpu-card-title"><strong><b>${index}</b>${escapeHtml(gpu.name || "NVIDIA GPU")}</strong><span>${escapeHtml(pcie)}</span></div>
      ${stat("VRAM", "vram", vram, `${formatMemory(gpu.memory_used_mb)} / ${formatMemory(gpu.memory_total_mb)}`)}
      ${stat("UTIL", "util", utilization, `${number(gpu.utilization_pct)}%`)}
      ${stat("PWR", "power", power, `${number(gpu.power_draw_w)} / ${number(gpu.power_limit_w)} W`)}
      ${stat("TEMP", "temp", temperature, `${number(gpu.temperature_c)} / ${number(gpu.temperature_limit_c || 83)} C`)}
    </article>`;
}

function renderActivity(payload) {
  const workloads = payload.workloads ?? [];
  const processes = payload.gpu_processes ?? [];
  elements.workloadCount.textContent = String(workloads.length);
  elements.processCount.textContent = String(processes.length);
  elements.workloadList.innerHTML = workloads.map((workload) => `
    <div class="activity-row">
      <strong>${escapeHtml(workload.name)}</strong><span class="activity-state ${escapeHtml(workload.state)}">${escapeHtml(workload.state)}</span>
      <span class="activity-detail">${escapeHtml((workload.command ?? []).join(" "))}</span>
    </div>`).join("");
  elements.processList.innerHTML = processes.map((process) => `
    <div class="activity-row">
      <strong>${escapeHtml(process.process_name)}</strong><span>${escapeHtml(process.memory_used_mb ?? "—")} MB</span>
      <span class="activity-detail">PID ${escapeHtml(process.pid)}  GPU ${escapeHtml(process.gpu_index ?? "—")}</span>
    </div>`).join("");
}

function renderSnapshot(payload) {
  const { machine, system, gpus, readiness, checks } = payload;
  elements.empty.hidden = true;
  elements.overview.hidden = true;
  elements.view.hidden = false;
  elements.name.textContent = machine.name;
  elements.subtitle.textContent = machineSubtitle(machine, payload);
  elements.provider.textContent = [lineageLabel(machine), payload.monitor?.status === "stale" ? "STALE" : stateLabel(machine.state)].filter(Boolean).join("  |  ");
  elements.readiness.textContent = `VERIFY ${stateLabel(readiness)}`;
  elements.readiness.className = `readiness ${readiness}`;
  elements.termination.textContent = countdown(machine);

  const cpu = Number(system.cpu_utilization_pct) || 0;
  const memory = percent(system.memory_used_mb, system.memory_mb);
  const disk = percent(system.disk_used_gb, system.disk_total_gb);
  elements.systemMeta.textContent = [system.os_name, system.kernel].filter(Boolean).join("  |  ");
  elements.cpuValue.textContent = `${number(system.cpu_count, 1)} CPU  ${number(cpu, 1)}%`;
  elements.memoryValue.textContent = `${formatMemory(system.memory_used_mb)} / ${formatMemory(system.memory_mb)}`;
  elements.diskValue.textContent = `${number(system.disk_used_gb)} / ${number(system.disk_total_gb)} GB`;
  elements.cpuMeter.style.width = `${clampPercent(cpu)}%`;
  elements.memoryMeter.style.width = `${memory}%`;
  elements.diskMeter.style.width = `${disk}%`;

  const drivers = [...new Set(gpus.map((gpu) => gpu.driver_version).filter(Boolean))];
  elements.gpuMeta.textContent = [`${gpus.length} GPU`, drivers.length ? `driver ${drivers.join(", ")}` : null, system.driver_cuda_version ? `CUDA ${system.driver_cuda_version}` : null].filter(Boolean).join("  |  ");
  elements.gpuList.innerHTML = gpus.map(gpuCard).join("");

  const checkRank = { fail: 0, warn: 1, pass: 2 };
  const visibleChecks = [...(checks.length ? checks : (payload.health_checks ?? []))]
    .sort((left, right) => (checkRank[left.status] ?? 3) - (checkRank[right.status] ?? 3));
  elements.checkSummary.textContent = `${visibleChecks.filter((check) => check.status === "pass").length} / ${visibleChecks.length}`;
  elements.checks.innerHTML = visibleChecks.map((check) => `
    <div class="check-row ${escapeHtml(check.status)}">
      <span class="check-signal" aria-hidden="true"></span><strong>${escapeHtml(checkLabels[check.check] ?? check.check)}</strong><small title="${escapeHtml(check.detail)}">${escapeHtml(checkValue(check))}</small>
    </div>`).join("");
  renderActivity(payload);
  renderChart(machine.host_id);
}

function renderFailure(host, message) {
  elements.empty.hidden = true;
  elements.overview.hidden = true;
  elements.view.hidden = false;
  elements.name.textContent = host.name;
  elements.subtitle.textContent = machineGpuLabel(host);
  elements.provider.textContent = lineageLabel(host);
  elements.readiness.textContent = "SSH ERR";
  elements.readiness.className = "readiness not_ready";
  elements.termination.textContent = countdown(host);
  elements.systemMeta.textContent = message;
  elements.gpuMeta.textContent = "—";
  elements.gpuList.innerHTML = "";
  elements.checkSummary.textContent = "0 / 1";
  elements.checks.innerHTML = '<div class="check-row fail"><span class="check-signal"></span><strong>SSH</strong><small>ERR</small></div>';
  elements.workloadCount.textContent = "0";
  elements.processCount.textContent = "0";
  elements.workloadList.innerHTML = "";
  elements.processList.innerHTML = "";
}

function observedTime(payload) {
  return payload?.observed_at ? new Date(payload.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

function overviewRow(host) {
  const payload = state.snapshots.get(host.host_id);
  const gpu = payload ? gpuSummary(payload) : null;
  const status = state.errors.has(host.host_id) ? "fault" : payload?.monitor?.status === "stale" ? "stale" : payload?.health ?? host.state;
  return `
    <button class="overview-row ${escapeHtml(status)}" type="button" role="row" data-overview-host="${escapeHtml(host.host_id)}" ${host.ssh_ready && host.state === "running" ? "" : "disabled"}>
      <span class="col-host" role="cell"><strong>${escapeHtml(host.name)}</strong><small>${escapeHtml(lineageLabel(host))}</small></span>
      <span class="col-state overview-status" role="cell">${escapeHtml(stateLabel(status))}</span>
      <span class="col-gpu" role="cell">${escapeHtml(machineGpuLabel(host, payload))}</span>
      <span class="col-load" role="cell">${gpu ? `${number(gpu.utilization)}%` : "—"}</span>
      <span class="col-vram" role="cell">${gpu ? `${formatMemory(gpu.memoryUsed)} / ${formatMemory(gpu.memoryTotal)}` : "—"}</span>
      <span class="col-temp" role="cell">${gpu ? `${number(gpu.temperature)}°C` : "—"}</span>
      <span class="col-power" role="cell">${gpu ? `${number(gpu.power)} W` : "—"}</span>
      <span class="col-cpu" role="cell">${payload ? `${number(payload.system.cpu_utilization_pct, 1)}%` : "—"}</span>
      <span class="col-observed" role="cell">${observedTime(payload)}</span>
    </button>`;
}

function renderOverview() {
  const hosts = orderedHosts();
  elements.overviewState.textContent = `${activeHosts().length} UP / ${hosts.length}`;
  elements.overviewRows.innerHTML = hosts.map(overviewRow).join("");
}

function chartData(hostId) {
  const samples = state.samples.get(hostId) ?? [];
  if (samples.length === 1) {
    const sample = samples[0];
    const observedAt = Date.parse(sample.observedAt) / 1000;
    return [
      [observedAt - 5, observedAt],
      [sample.gpu, sample.gpu],
      [sample.vram, sample.vram],
      [sample.cpu, sample.cpu],
    ];
  }
  return [
    samples.map((sample) => Date.parse(sample.observedAt) / 1000),
    samples.map((sample) => sample.gpu),
    samples.map((sample) => sample.vram),
    samples.map((sample) => sample.cpu),
  ];
}

function renderHistoryReadout(hostId, index = null) {
  const samples = state.samples.get(hostId) ?? [];
  const sample = index === null ? samples.at(-1) : samples[Math.min(index, samples.length - 1)];
  elements.historyTime.textContent = sample ? new Date(sample.observedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
  elements.historyGpu.textContent = sample ? `${number(sample.gpu, 1)}%` : "—";
  elements.historyVram.textContent = sample ? `${number(sample.vram, 1)}%` : "—";
  elements.historyCpu.textContent = sample ? `${number(sample.cpu, 1)}%` : "—";
}

function plotTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function chartSize() {
  return {
    width: Math.max(320, elements.chart.clientWidth - 24),
    height: Math.max(120, elements.chart.clientHeight - 4),
  };
}

function chartOptions() {
  const { width, height } = chartSize();
  return {
    width,
    height,
    padding: [8, 6, 0, 0],
    legend: { show: false },
    cursor: { x: true, y: false, drag: { x: false, y: false, setScale: false }, points: { show: true, size: 4 } },
    scales: { x: { time: true }, pct: { range: [0, 100] } },
    axes: [
      {
        stroke: "#666666",
        grid: { stroke: "#181818", width: 1 },
        ticks: { show: false },
        size: 24,
        incrs: [5, 10, 15, 30, 60, 120, 300],
        values: (_, splits) => splits.map(plotTime),
        font: "12px SFMono-Regular",
      },
      { scale: "pct", stroke: "#666666", grid: { stroke: "#272727", width: 1 }, ticks: { show: false }, size: 32, splits: () => [0, 25, 50, 75, 100], font: "12px SFMono-Regular" },
    ],
    series: [
      {},
      { label: "GPU", scale: "pct", stroke: "#ff8700", width: 2, paths: uPlot.paths.stepped({ align: 1 }), points: { show: false } },
      { label: "VRAM", scale: "pct", stroke: "#00afff", width: 1.5, paths: uPlot.paths.stepped({ align: 1 }), points: { show: false } },
      { label: "CPU", scale: "pct", stroke: "#00ff00", width: 1.5, paths: uPlot.paths.stepped({ align: 1 }), points: { show: false } },
    ],
    hooks: {
      setCursor: [(plot) => renderHistoryReadout(state.hostId, plot.cursor.idx)],
    },
  };
}

function renderChart(hostId) {
  requestAnimationFrame(() => {
    if (state.view !== "detail" || elements.view.hidden || elements.chart.clientWidth < 1) return;
    const data = chartData(hostId);
    if (!state.plot) state.plot = new uPlot(chartOptions(), data, elements.chart);
    else {
      state.plot.setSize(chartSize());
      state.plot.setData(data);
    }
    renderHistoryReadout(hostId);
  });
}

function setView(view) {
  state.view = view;
  const overview = view === "overview";
  elements.overviewToggle.setAttribute("aria-pressed", String(overview));
  elements.overviewToggle.classList.toggle("active", overview);
  elements.overview.hidden = !overview;
  if (overview) {
    elements.empty.hidden = true;
    elements.view.hidden = true;
    renderOverview();
    return;
  }
  const host = activeHosts().find((candidate) => candidate.host_id === state.hostId);
  if (!host) {
    elements.empty.hidden = false;
    elements.view.hidden = true;
  } else if (state.errors.has(host.host_id)) renderFailure(host, state.errors.get(host.host_id));
  else if (state.snapshots.has(host.host_id)) renderSnapshot(state.snapshots.get(host.host_id));
}

async function fetchHost(host) {
  const response = await fetch(`/api/fleet/hosts/${encodeURIComponent(host.host_id)}`, { cache: "no-store" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Probe failed (${response.status})`);
  }
  return response.json();
}

async function refreshFleet() {
  if (state.refreshing) return;
  state.refreshing = true;
  elements.refreshState.textContent = "Polling";
  try {
    await loadSession();
    const hosts = activeHosts();
    const results = await Promise.allSettled(hosts.map(fetchHost));
    results.forEach((result, index) => {
      const host = hosts[index];
      if (result.status === "fulfilled") {
        state.snapshots.set(host.host_id, result.value);
        state.errors.delete(host.host_id);
        captureSample(result.value);
      } else state.errors.set(host.host_id, result.reason instanceof Error ? result.reason.message : "Probe failed");
    });
    renderHosts();
    setView(state.view);
    elements.refreshState.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } finally {
    state.refreshing = false;
  }
}

function selectHost(hostId) {
  state.hostId = hostId;
  state.view = "detail";
  renderHosts();
  setView("detail");
}

function cycleHost(offset) {
  const hosts = activeHosts();
  if (hosts.length < 2) return;
  const current = Math.max(0, hosts.findIndex((host) => host.host_id === state.hostId));
  selectHost(hosts[(current + offset + hosts.length) % hosts.length].host_id);
}

elements.hostList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-host-id]");
  if (button) selectHost(button.dataset.hostId);
});

elements.overviewRows.addEventListener("click", (event) => {
  const row = event.target.closest("[data-overview-host]");
  if (row && !row.disabled) selectHost(row.dataset.overviewHost);
});

elements.overviewToggle.addEventListener("click", () => setView(state.view === "overview" ? "detail" : "overview"));
elements.chart.addEventListener("mouseleave", () => renderHistoryReadout(state.hostId));

window.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
  if (event.key === "n" || event.key === "ArrowRight") cycleHost(1);
  if (event.key === "ArrowLeft") cycleHost(-1);
  if (event.key.toLowerCase() === "t") setView(state.view === "overview" ? "detail" : "overview");
});

new ResizeObserver(() => {
  if (state.plot && state.view === "detail") {
    state.plot.setSize(chartSize());
  }
}).observe(elements.chart);

window.addEventListener("pagehide", () => {
  if (state.timer) window.clearInterval(state.timer);
  state.plot?.destroy();
});

refreshFleet()
  .then(() => { state.timer = window.setInterval(refreshFleet, (state.session?.refresh_seconds || 5) * 1000); })
  .catch((error) => {
    elements.empty.hidden = false;
    elements.view.hidden = true;
    elements.empty.textContent = error instanceof Error ? error.message : String(error);
  });
