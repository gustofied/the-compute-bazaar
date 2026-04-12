"""
Contour plot of compute/electricity density across Ireland.
MW-weighted KDE from known data centre locations.
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.path import Path
from scipy.stats import gaussian_kde


# Ireland coastline (lon, lat) clockwise
IRELAND = np.array([
    (-7.37, 55.37),
    (-7.87, 55.20),
    (-8.28, 55.16),
    (-8.62, 54.97),
    (-8.77, 54.67),
    (-9.14, 54.30),
    (-9.60, 54.27),
    (-9.99, 54.30),
    (-10.11, 53.93),
    (-9.95, 53.75),
    (-9.65, 53.65),
    (-9.90, 53.47),
    (-9.74, 53.22),
    (-9.07, 53.12),
    (-8.88, 52.89),
    (-9.93, 52.57),
    (-10.18, 52.10),
    (-10.43, 51.80),
    (-9.81, 51.45),
    (-8.99, 51.58),
    (-8.25, 51.71),
    (-7.83, 51.82),
    (-6.93, 52.11),
    (-6.41, 52.19),
    (-6.07, 52.41),
    (-6.03, 53.10),
    (-6.08, 53.38),
    (-6.15, 53.60),
    (-6.23, 54.00),
    (-5.99, 54.25),
    (-5.58, 54.42),
    (-5.41, 54.65),
    (-5.67, 55.20),
    (-6.20, 55.35),
    (-7.37, 55.37),
])

# (lon, lat, MW capacity)
DATA_CENTRES = [
    (-6.17, 53.39, 500),   # Dublin East (Clonshaugh/Profile Park)
    (-6.42, 53.32, 700),   # Dublin West (Grange Castle)
    (-6.38, 53.28, 300),   # Dublin South (Tallaght/Citywest)
    (-6.23, 53.34, 150),   # Dublin Docklands
    (-6.30, 53.36,  90),   # Dublin mid
    (-6.25, 53.42,  70),   # Dublin North
    (-6.35, 53.44,  50),   # Dublin NW (Blanchardstown)
    (-6.10, 53.33,  40),   # Dublin Sandyford
    (-7.94, 53.42,  80),   # Athlone
    (-8.47, 51.90,  60),   # Cork
    (-8.63, 52.66,  40),   # Limerick
    (-9.05, 53.27,  30),   # Galway
    (-7.09, 52.66,  20),   # Portlaoise / Midlands
    (-6.46, 52.34,  15),   # Wicklow / Bray
    (-8.12, 53.32,  12),   # Tullamore
    (-6.77, 54.00,  10),   # Drogheda / Dundalk area
]

lons       = np.array([d[0] for d in DATA_CENTRES])
lats       = np.array([d[1] for d in DATA_CENTRES])
capacities = np.array([d[2] for d in DATA_CENTRES])


def make_grid(n=80):
    lg = np.linspace(-10.8, -5.2, n)
    ag = np.linspace(51.3, 55.7, n)
    return np.meshgrid(lg, ag)


def ireland_mask(LON, LAT):
    path = Path(IRELAND)
    pts  = np.column_stack([LON.ravel(), LAT.ravel()])
    return path.contains_points(pts).reshape(LON.shape)


def compute_kde(LON, LAT, bw=0.6):
    reps = np.round(capacities / capacities.min()).astype(int)
    pts  = np.repeat(np.column_stack([lons, lats]), reps, axis=0).T
    kde  = gaussian_kde(pts, bw_method=bw)
    return kde(np.vstack([LON.ravel(), LAT.ravel()])).reshape(LON.shape)


def main():
    LON, LAT = make_grid()
    mask = ireland_mask(LON, LAT)
    Z = compute_kde(LON, LAT)
    Z[~mask] = np.nan

    # Log-transform so the full island shows variation, not just Dublin
    Z = np.log10(Z)

    # ~12 discrete levels for the chunky geometric look
    vmin, vmax = np.nanmin(Z), np.nanmax(Z)
    levels = np.linspace(vmin, vmax, 13)

    fig, ax = plt.subplots(figsize=(7, 9))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    cf = ax.contourf(
        LON, LAT, Z,
        levels=levels,
        cmap="viridis_r",
        extend="neither",
    )

    # Ireland border
    ax.plot(IRELAND[:, 0], IRELAND[:, 1], color="white", lw=1.2, alpha=0.7)

    # Data centre scatter — blue dots like the reference
    rng = np.random.default_rng(42)
    path = Path(IRELAND)

    # Main facility dots sized by capacity
    ax.scatter(lons, lats,
               s=capacities * 0.25,
               color="#5b9bd5", edgecolors="white",
               linewidths=0.5, zorder=5, alpha=0.9)

    # Jitter dots around each facility (sub-campuses, feeders)
    for lon, lat, cap in DATA_CENTRES:
        n_sub = max(1, cap // 60)
        jlon = lon + rng.normal(0, 0.08, n_sub)
        jlat = lat + rng.normal(0, 0.06, n_sub)
        ax.scatter(jlon, jlat, s=14,
                   color="#5b9bd5", edgecolors="white",
                   linewidths=0.35, zorder=4, alpha=0.75)

    # Background scatter — minor/unknown sites across Ireland
    n_bg = 60
    bg_pts = []
    while len(bg_pts) < n_bg:
        candidate_lons = rng.uniform(-10.5, -5.5, n_bg * 3)
        candidate_lats = rng.uniform(51.5, 55.4, n_bg * 3)
        inside = path.contains_points(np.column_stack([candidate_lons, candidate_lats]))
        for lo, la, ins in zip(candidate_lons, candidate_lats, inside):
            if ins:
                bg_pts.append((lo, la))
    bg_pts = np.array(bg_pts[:n_bg])
    ax.scatter(bg_pts[:, 0], bg_pts[:, 1], s=10,
               color="#5b9bd5", edgecolors="white",
               linewidths=0.3, zorder=3, alpha=0.5)

    # Colorbar — discrete ticks at level boundaries, formatted cleanly
    cbar = fig.colorbar(cf, ax=ax, fraction=0.035, pad=0.03, ticks=levels)
    cbar.ax.set_yticklabels([f"{v:.2f}" for v in levels], fontsize=7)
    cbar.set_label("log₁₀ density (MW-weighted KDE)", fontsize=9)

    ax.set_title("Irish data centre compute density", fontsize=13, pad=12)
    ax.set_xlabel("Longitude", fontsize=9)
    ax.set_ylabel("Latitude", fontsize=9)
    ax.set_xlim(-10.8, -5.2)
    ax.set_ylim(51.3, 55.7)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8)

    plt.tight_layout()
    plt.savefig("ireland_compute_map.png", dpi=180, bbox_inches="tight")
    print("Saved ireland_compute_map.png")


if __name__ == "__main__":
    main()
