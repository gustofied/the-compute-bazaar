const elements = {
  hostList: document.querySelector("#host-list"),
  hostCount: document.querySelector("#host-count"),
  refreshState: document.querySelector("#refresh-state"),
  overviewToggle: document.querySelector("#overview-toggle"),
  overview: document.querySelector("#overview-view"),
  overviewRows: document.querySelector("#overview-rows"),
  overviewState: document.querySelector("#overview-state"),
  empty: document.querySelector("#fleet-empty"),
  view: document.querySelector("#machine-view"),
  provider: document.querySelector("#machine-provider"),
  name: document.querySelector("#machine-name"),
  subtitle: document.querySelector("#machine-subtitle"),
  readiness: document.querySelector("#readiness"),
  termination: document.querySelector("#termination"),
  gpuUtil: document.querySelector("#gpu-util"),
  gpuMemory: document.querySelector("#gpu-memory"),
  gpuMemoryTotal: document.querySelector("#gpu-memory-total"),
  gpuTemp: document.querySelector("#gpu-temp"),
  gpuTempLimit: document.querySelector("#gpu-temp-limit"),
  gpuPower: document.querySelector("#gpu-power"),
  gpuPowerLimit: document.querySelector("#gpu-power-limit"),
  cpuValue: document.querySelector("#cpu-value"),
  memoryValue: document.querySelector("#memory-value"),
  diskValue: document.querySelector("#disk-value"),
  cpuMeter: document.querySelector("#cpu-meter"),
  memoryMeter: document.querySelector("#memory-meter"),
  diskMeter: document.querySelector("#disk-meter"),
  gpuName: document.querySelector("#gpu-name"),
  driver: document.querySelector("#driver"),
  pcie: document.querySelector("#pcie"),
  osName: document.querySelector("#os-name"),
  kernel: document.querySelector("#kernel"),
  checks: document.querySelector("#check-list"),
  gpuLine: document.querySelector("#gpu-line"),
  vramLine: document.querySelector("#vram-line"),
  cpuLine: document.querySelector("#cpu-line"),
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
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

function percent(used, total) {
  const value = Number(total) > 0 ? (Number(used) / Number(total)) * 100 : 0;
  return Math.max(0, Math.min(100, value));
}

function formatMemory(mb) {
  return Number.isFinite(Number(mb)) ? `${(Number(mb) / 1024).toFixed(1)} GB` : "—";
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

function validNumbers(values) {
  return values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map(Number)
    .filter(Number.isFinite);
}

function gpuSummary(payload) {
  const devices = payload.gpus ?? [];
  return {
    utilization: average(devices.map((gpu) => gpu.utilization_pct)),
    memoryUsed: sum(devices.map((gpu) => gpu.memory_used_mb)),
    memoryTotal: sum(devices.map((gpu) => gpu.memory_total_mb)),
    temperature: maximum(devices.map((gpu) => gpu.temperature_c)),
    temperatureLimit: maximum(devices.map((gpu) => gpu.temperature_limit_c)),
    power: sum(devices.map((gpu) => gpu.power_draw_w)),
    powerLimit: sum(devices.map((gpu) => gpu.power_limit_w)),
    names: [...new Set(devices.map((gpu) => gpu.name).filter(Boolean))].join(", "),
    drivers: [...new Set(devices.map((gpu) => gpu.driver_version).filter(Boolean))].join(", "),
  };
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
  if (!response.ok) throw new Error("Fleet inventory unavailable");
  state.session = await response.json();
  const active = activeHosts();
  if (!active.some((host) => host.host_id === state.hostId)) {
    state.hostId = active[0]?.host_id ?? null;
  }
}

function hostReading(host) {
  if (host.state !== "running") {
    return `<span class="host-reading"><span>Stopped</span><span>—</span></span>`;
  }
  if (!host.ssh_ready) {
    return `<span class="host-reading"><span>No SSH</span><span>—</span></span>`;
  }
  const snapshot = state.snapshots.get(host.host_id);
  const error = state.errors.get(host.host_id);
  if (error) return `<span class="host-reading"><span>SSH fault</span><span>—</span></span>`;
  if (!snapshot) return `<span class="host-reading"><span>Waiting</span><span>—</span></span>`;
  const gpu = gpuSummary(snapshot);
  const label = snapshot.monitor?.status === "stale" ? "Stale" : `GPU ${number(gpu.utilization)}%`;
  return `<span class="host-reading"><span>${label}</span><span>${number(gpu.temperature)}°C</span></span>`;
}

function renderHosts() {
  const hosts = orderedHosts();
  const running = activeHosts().length;
  elements.hostCount.textContent = `${running}/${hosts.length} running`;
  elements.hostList.innerHTML = hosts.map((host) => {
    const snapshot = state.snapshots.get(host.host_id);
    const failed = state.errors.has(host.host_id);
    const status = failed ? "fault" : snapshot?.monitor?.status === "stale" ? "stale" : host.state;
    return `
      <button class="host-button ${host.host_id === state.hostId ? "active" : ""} ${failed ? "fault" : ""}" type="button" data-host-id="${escapeHtml(host.host_id)}" ${host.ssh_ready && host.state === "running" ? "" : "disabled"}>
        <span class="host-name">${escapeHtml(host.name)}</span>
        <span class="host-meta"><span>${escapeHtml(host.gpu_count)} × ${escapeHtml(host.gpu_model)}</span><span class="host-status">${escapeHtml(status)}</span></span>
        ${hostReading(host)}
      </button>
    `;
  }).join("");
  renderOverview();
}

function countdown(machine) {
  if (!machine.terminate_at) return "No deadline";
  const remaining = new Date(machine.terminate_at).getTime() - Date.now();
  if (remaining <= 0) return "Delete due";
  return `Deletes in ${Math.max(1, Math.ceil(remaining / 60000))}m`;
}

function captureSample(payload) {
  const gpu = gpuSummary(payload);
  const samples = state.samples.get(payload.machine.host_id) ?? [];
  if (samples.at(-1)?.observedAt === payload.observed_at) return;
  samples.push({
    observedAt: payload.observed_at,
    gpu: Number(gpu.utilization) || 0,
    vram: percent(gpu.memoryUsed, gpu.memoryTotal),
    cpu: Number(payload.system.cpu_utilization_pct) || 0,
  });
  state.samples.set(payload.machine.host_id, samples.slice(-120));
}

function renderSnapshot(payload) {
  const { machine, system, gpus, readiness, checks } = payload;
  const gpu = gpuSummary(payload);
  elements.empty.hidden = true;
  elements.overview.hidden = true;
  elements.view.hidden = false;
  elements.provider.textContent = [machine.provider || "imported", machine.state, payload.monitor?.status === "stale" ? "stale" : null].filter(Boolean).join(" / ");
  elements.name.textContent = machine.name;
  elements.subtitle.textContent = `${machine.gpu_count} × ${machine.gpu_model} · $${number(machine.price_usd_instance_hr, 2)} / hr`;
  elements.readiness.textContent = readiness.replace("_", " ");
  elements.readiness.className = `readiness ${readiness}`;
  elements.termination.textContent = countdown(machine);

  elements.gpuUtil.textContent = `${number(gpu.utilization)}%`;
  elements.gpuMemory.textContent = formatMemory(gpu.memoryUsed);
  elements.gpuMemoryTotal.textContent = `${formatMemory(gpu.memoryTotal)} total`;
  elements.gpuTemp.textContent = `${number(gpu.temperature)}°C`;
  elements.gpuTempLimit.textContent = `${number(gpu.temperatureLimit)}°C limit`;
  elements.gpuPower.textContent = `${number(gpu.power)} W`;
  elements.gpuPowerLimit.textContent = `${number(gpu.powerLimit)} W limit`;

  const cpuPct = Number(system.cpu_utilization_pct) || 0;
  const memoryPct = percent(system.memory_used_mb, system.memory_mb);
  const diskPct = percent(system.disk_used_gb, system.disk_total_gb);
  elements.cpuValue.textContent = `${number(system.cpu_count, 1)} CPU · ${number(cpuPct, 1)}%`;
  elements.memoryValue.textContent = `${formatMemory(system.memory_used_mb)} / ${formatMemory(system.memory_mb)}`;
  elements.diskValue.textContent = `${number(system.disk_used_gb)} / ${number(system.disk_total_gb)} GB`;
  elements.cpuMeter.style.width = `${cpuPct}%`;
  elements.memoryMeter.style.width = `${memoryPct}%`;
  elements.diskMeter.style.width = `${diskPct}%`;
  elements.gpuName.textContent = gpu.names || "—";
  elements.driver.textContent = gpu.drivers || "—";
  const firstGpu = gpus[0] ?? {};
  elements.pcie.textContent = firstGpu.pcie_generation_current
    ? `Gen ${firstGpu.pcie_generation_current}/${firstGpu.pcie_generation_max ?? "—"} ×${firstGpu.pcie_width_current ?? "—"}/${firstGpu.pcie_width_max ?? "—"}`
    : "—";
  elements.osName.textContent = system.os_name || "—";
  elements.kernel.textContent = system.kernel || "—";
  elements.checks.innerHTML = checks.map((check) => `
    <div class="check-row ${escapeHtml(check.status)}">
      <span class="check-signal" aria-hidden="true"></span>
      <div><strong>${escapeHtml(check.check.replaceAll("_", " "))}</strong><small>${escapeHtml(check.detail)}</small></div>
    </div>
  `).join("");
  renderChart(machine.host_id);
}

function renderFailure(host, message) {
  elements.empty.hidden = true;
  elements.overview.hidden = true;
  elements.view.hidden = false;
  elements.provider.textContent = `${host.provider} / ${host.state}`;
  elements.name.textContent = host.name;
  elements.subtitle.textContent = `${host.gpu_count} × ${host.gpu_model}`;
  elements.readiness.textContent = "SSH fault";
  elements.readiness.className = "readiness not_ready";
  elements.termination.textContent = countdown(host);
  elements.checks.innerHTML = `<div class="check-row fail"><span class="check-signal"></span><div><strong>SSH</strong><small>${escapeHtml(message)}</small></div></div>`;
}

function observedTime(payload) {
  if (!payload?.observed_at) return "—";
  return new Date(payload.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function overviewRow(host) {
  const payload = state.snapshots.get(host.host_id);
  const error = state.errors.get(host.host_id);
  const gpu = payload ? gpuSummary(payload) : null;
  const status = error
    ? "fault"
    : payload?.monitor?.status === "stale"
      ? "stale"
      : payload?.health ?? host.state;
  const memory = gpu ? `${formatMemory(gpu.memoryUsed)} / ${formatMemory(gpu.memoryTotal)}` : "—";
  return `
    <button class="overview-row ${escapeHtml(status)}" type="button" role="row" data-overview-host="${escapeHtml(host.host_id)}" ${host.ssh_ready && host.state === "running" ? "" : "disabled"}>
      <span role="cell"><strong>${escapeHtml(host.name)}</strong><small>${escapeHtml(host.provider)}</small></span>
      <span role="cell" class="overview-status">${escapeHtml(status)}</span>
      <span role="cell">${escapeHtml(host.gpu_count)} × ${escapeHtml(host.gpu_model)}</span>
      <span role="cell">${gpu ? `${number(gpu.utilization)}%` : "—"}</span>
      <span role="cell">${memory}</span>
      <span role="cell">${gpu ? `${number(gpu.temperature)}°C` : "—"}</span>
      <span role="cell">${gpu ? `${number(gpu.power)} W` : "—"}</span>
      <span role="cell">${payload ? `${number(payload.system.cpu_utilization_pct, 1)}%` : "—"}</span>
      <span role="cell">${observedTime(payload)}</span>
    </button>
  `;
}

function renderOverview() {
  const hosts = orderedHosts();
  elements.overviewState.textContent = `${activeHosts().length}/${hosts.length} running`;
  elements.overviewRows.innerHTML = hosts.map(overviewRow).join("");
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
  } else if (state.errors.has(host.host_id)) {
    renderFailure(host, state.errors.get(host.host_id));
  } else if (state.snapshots.has(host.host_id)) {
    renderSnapshot(state.snapshots.get(host.host_id));
  }
}

function linePath(samples, key) {
  if (!samples.length) return "";
  return samples.map((sample, index) => {
    const x = samples.length === 1 ? 1000 : (index / (samples.length - 1)) * 1000;
    const y = 220 - (Math.max(0, Math.min(100, sample[key])) / 100) * 200;
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function renderChart(hostId) {
  const samples = state.samples.get(hostId) ?? [];
  elements.gpuLine.setAttribute("d", linePath(samples, "gpu"));
  elements.vramLine.setAttribute("d", linePath(samples, "vram"));
  elements.cpuLine.setAttribute("d", linePath(samples, "cpu"));
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
    const results = await Promise.allSettled(hosts.map((host) => fetchHost(host)));
    results.forEach((result, index) => {
      const host = hosts[index];
      if (result.status === "fulfilled") {
        state.snapshots.set(host.host_id, result.value);
        state.errors.delete(host.host_id);
        captureSample(result.value);
      } else {
        state.errors.set(host.host_id, result.reason instanceof Error ? result.reason.message : "Probe failed");
      }
    });
    renderHosts();
    if (state.view === "overview") {
      setView("overview");
      elements.refreshState.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      return;
    }
    const selected = hosts.find((host) => host.host_id === state.hostId);
    if (!selected) {
      elements.empty.hidden = false;
      elements.view.hidden = true;
    } else if (state.errors.has(selected.host_id)) {
      renderFailure(selected, state.errors.get(selected.host_id));
    } else if (state.snapshots.has(selected.host_id)) {
      renderSnapshot(state.snapshots.get(selected.host_id));
    }
    elements.refreshState.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } finally {
    state.refreshing = false;
  }
}

function selectHost(hostId) {
  if (state.hostId === hostId) return;
  state.hostId = hostId;
  state.view = "detail";
  elements.overviewToggle.setAttribute("aria-pressed", "false");
  elements.overviewToggle.classList.remove("active");
  renderHosts();
  const host = activeHosts().find((candidate) => candidate.host_id === hostId);
  if (state.errors.has(hostId)) renderFailure(host, state.errors.get(hostId));
  else if (state.snapshots.has(hostId)) renderSnapshot(state.snapshots.get(hostId));
}

function cycleHost(offset) {
  const hosts = activeHosts();
  if (hosts.length < 2) return;
  const current = Math.max(0, hosts.findIndex((host) => host.host_id === state.hostId));
  selectHost(hosts[(current + offset + hosts.length) % hosts.length].host_id);
}

elements.hostList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-host-id]");
  if (button && !button.disabled) selectHost(button.dataset.hostId);
});

elements.overviewRows.addEventListener("click", (event) => {
  const row = event.target.closest("[data-overview-host]");
  if (row && !row.disabled) selectHost(row.dataset.overviewHost);
});

elements.overviewToggle.addEventListener("click", () => {
  setView(state.view === "overview" ? "detail" : "overview");
});

window.addEventListener("keydown", (event) => {
  if (["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
  if (event.key === "n" || event.key === "ArrowRight") cycleHost(1);
  if (event.key === "ArrowLeft") cycleHost(-1);
  if (event.key.toLowerCase() === "t") setView(state.view === "overview" ? "detail" : "overview");
});

window.addEventListener("pagehide", () => {
  if (state.timer) window.clearInterval(state.timer);
});

refreshFleet()
  .then(() => {
    state.timer = window.setInterval(refreshFleet, (state.session?.refresh_seconds || 5) * 1000);
  })
  .catch((error) => {
    elements.empty.hidden = false;
    elements.view.hidden = true;
    elements.empty.textContent = error instanceof Error ? error.message : String(error);
  });
