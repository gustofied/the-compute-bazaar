const elements = {
  hostList: document.querySelector("#host-list"),
  hostCount: document.querySelector("#host-count"),
  refreshState: document.querySelector("#refresh-state"),
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

const state = { session: null, hostId: null, timer: null, samples: [] };

async function loadSession() {
  const response = await fetch("/api/fleet/session", { cache: "no-store" });
  if (!response.ok) throw new Error("Fleet inventory is unavailable");
  state.session = await response.json();
  const current = state.session.hosts.find(
    (host) => host.host_id === state.hostId && host.ssh_ready && host.state === "running",
  );
  const first = state.session.hosts.find((host) => host.ssh_ready && host.state === "running");
  state.hostId = current?.host_id ?? first?.host_id ?? null;
  renderHosts();
}

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

function percent(used, total) {
  const value = Number(total) > 0 ? (Number(used) / Number(total)) * 100 : 0;
  return Math.max(0, Math.min(100, value));
}

function formatMemory(mb) {
  return Number.isFinite(Number(mb)) ? `${(Number(mb) / 1024).toFixed(1)} GB` : "—";
}

function renderHosts() {
  const hosts = state.session?.hosts ?? [];
  elements.hostCount.textContent = `${hosts.length} ${hosts.length === 1 ? "host" : "hosts"}`;
  elements.hostList.innerHTML = hosts.map((host) => `
    <button class="host-button ${host.host_id === state.hostId ? "active" : ""}" type="button" data-host-id="${escapeHtml(host.host_id)}" ${host.ssh_ready ? "" : "disabled"}>
      <span class="host-name">${escapeHtml(host.name)}</span>
      <span class="host-meta"><span>${escapeHtml(host.gpu_count)} × ${escapeHtml(host.gpu_model)}</span><span class="host-status">${escapeHtml(host.state)}</span></span>
    </button>
  `).join("");
}

function countdown(machine) {
  const remaining = new Date(machine.terminate_at).getTime() - Date.now();
  if (remaining <= 0) return "Termination due";
  const minutes = Math.max(1, Math.ceil(remaining / 60000));
  return `Auto deletes in ${minutes}m`;
}

function renderSnapshot(payload) {
  const { machine, system, gpus, readiness, checks } = payload;
  const gpu = gpus[0] ?? {};
  elements.empty.hidden = true;
  elements.view.hidden = false;
  elements.provider.textContent = `${machine.provider} / ${machine.state}`;
  elements.name.textContent = machine.name;
  elements.subtitle.textContent = `${machine.gpu_count} × ${machine.gpu_model} · $${number(machine.price_usd_instance_hr, 2)} / hr`;
  elements.readiness.textContent = readiness.replace("_", " ");
  elements.readiness.className = `readiness ${readiness}`;
  elements.termination.textContent = countdown(machine);

  elements.gpuUtil.textContent = `${number(gpu.utilization_pct, 0)}%`;
  elements.gpuMemory.textContent = formatMemory(gpu.memory_used_mb);
  elements.gpuMemoryTotal.textContent = `${formatMemory(gpu.memory_total_mb)} total`;
  elements.gpuTemp.textContent = `${number(gpu.temperature_c, 0)}°C`;
  elements.gpuTempLimit.textContent = `${number(gpu.temperature_limit_c, 0)}°C limit`;
  elements.gpuPower.textContent = `${number(gpu.power_draw_w, 0)} W`;
  elements.gpuPowerLimit.textContent = `${number(gpu.power_limit_w, 0)} W limit`;

  const cpuPct = Number(system.cpu_utilization_pct) || 0;
  const memoryPct = percent(system.memory_used_mb, system.memory_mb);
  const diskPct = percent(system.disk_used_gb, system.disk_total_gb);
  elements.cpuValue.textContent = `${number(system.cpu_count, 1)} CPU · ${number(cpuPct, 1)}%`;
  elements.memoryValue.textContent = `${formatMemory(system.memory_used_mb)} / ${formatMemory(system.memory_mb)}`;
  elements.diskValue.textContent = `${number(system.disk_used_gb)} / ${number(system.disk_total_gb)} GB`;
  elements.cpuMeter.style.width = `${cpuPct}%`;
  elements.memoryMeter.style.width = `${memoryPct}%`;
  elements.diskMeter.style.width = `${diskPct}%`;
  elements.gpuName.textContent = gpu.name || "—";
  elements.driver.textContent = gpu.driver_version || "—";
  elements.pcie.textContent = gpu.pcie_generation ? `Gen ${gpu.pcie_generation} ×${gpu.pcie_width ?? "—"}` : "—";
  elements.osName.textContent = system.os_name || "—";
  elements.kernel.textContent = system.kernel || "—";
  elements.checks.innerHTML = checks.map((check) => `
    <div class="check-row ${escapeHtml(check.status)}">
      <span class="check-signal" aria-hidden="true"></span>
      <div><strong>${escapeHtml(check.check.replaceAll("_", " "))}</strong><small>${escapeHtml(check.detail)}</small></div>
    </div>
  `).join("");

  state.samples.push({
    gpu: Number(gpu.utilization_pct) || 0,
    vram: percent(gpu.memory_used_mb, gpu.memory_total_mb),
    cpu: cpuPct,
  });
  state.samples = state.samples.slice(-120);
  renderChart();
}

function linePath(key) {
  const samples = state.samples;
  if (!samples.length) return "";
  return samples.map((sample, index) => {
    const x = samples.length === 1 ? 1000 : (index / (samples.length - 1)) * 1000;
    const y = 220 - (Math.max(0, Math.min(100, sample[key])) / 100) * 200;
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function renderChart() {
  elements.gpuLine.setAttribute("d", linePath("gpu"));
  elements.vramLine.setAttribute("d", linePath("vram"));
  elements.cpuLine.setAttribute("d", linePath("cpu"));
}

async function refreshHost() {
  if (!state.hostId) return;
  elements.refreshState.textContent = "Reading SSH";
  try {
    const response = await fetch(`/api/fleet/hosts/${encodeURIComponent(state.hostId)}`, { cache: "no-store" });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Fleet probe failed (${response.status})`);
    }
    const payload = await response.json();
    renderSnapshot(payload);
    elements.refreshState.textContent = `Updated ${new Date(payload.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  } catch (error) {
    elements.refreshState.textContent = error instanceof Error ? error.message : "Probe failed";
    const failedHostId = state.hostId;
    await loadSession().catch(() => {});
    if (state.hostId && state.hostId !== failedHostId) {
      state.samples = [];
      await refreshHost();
    } else if (!state.hostId) {
      elements.empty.hidden = false;
      elements.view.hidden = true;
    }
  }
}

function selectHost(hostId) {
  if (state.hostId === hostId) return;
  state.hostId = hostId;
  state.samples = [];
  renderHosts();
  void refreshHost();
}

async function initialize() {
  await loadSession();
  if (state.hostId) await refreshHost();
  else {
    elements.empty.hidden = false;
    elements.view.hidden = true;
  }
  state.timer = window.setInterval(refreshHost, (state.session.refresh_seconds || 5) * 1000);
}

elements.hostList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-host-id]");
  if (button && !button.disabled) selectHost(button.dataset.hostId);
});

window.addEventListener("pagehide", () => {
  if (state.timer) window.clearInterval(state.timer);
});

initialize().catch((error) => {
  elements.empty.hidden = false;
  elements.empty.querySelector("h2").textContent = "Fleet unavailable";
  elements.empty.querySelector("p:last-child").textContent = error instanceof Error ? error.message : String(error);
});
