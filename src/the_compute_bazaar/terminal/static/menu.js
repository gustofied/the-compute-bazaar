const runLight = document.querySelector("#run-light");
const runLabel = document.querySelector("#run-label");
const menuDetail = document.querySelector("#menu-detail");
const evalDestination = document.querySelector("#eval-destination");
const evalState = document.querySelector("#eval-state");

function shortRunId(value) {
  const id = String(value || "unknown run");
  return id.length > 28 ? `${id.slice(0, 24)}...` : id;
}

async function initializeMenu() {
  try {
    const response = await fetch("/api/terminal", { cache: "no-store" });
    if (!response.ok) throw new Error("Terminal state unavailable");
    const payload = await response.json();
    if (payload.contract !== "compute-bazaar.terminal.v1") {
      throw new Error("Terminal contract mismatch");
    }

    runLight.classList.add("ready");
    runLabel.textContent = shortRunId(payload.run?.run_id);
    menuDetail.textContent = `${payload.table_count} data tables / DataFusion / Perspective`;

    if (!payload.destinations?.eval?.available) {
      evalDestination.removeAttribute("href");
      evalDestination.classList.add("is-unavailable");
      evalDestination.setAttribute("aria-disabled", "true");
      evalState.textContent = "No reports";
    }
  } catch (error) {
    runLight.classList.add("error");
    runLabel.textContent = error instanceof Error ? error.message : "Terminal unavailable";
  }
}

void initializeMenu();
