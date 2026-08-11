const evalDestination = document.querySelector("#eval-destination");

async function initializeMenu() {
  try {
    const response = await fetch("/api/terminal", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.contract !== "compute-bazaar.terminal") return;

    if (!payload.destinations?.eval?.available) {
      evalDestination.removeAttribute("href");
      evalDestination.classList.add("is-unavailable");
      evalDestination.setAttribute("aria-disabled", "true");
    }
  } catch {}
}

void initializeMenu();
