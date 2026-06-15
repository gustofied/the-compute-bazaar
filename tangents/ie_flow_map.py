"""
Ireland electricity flow map — real asset locations, price trend, and
the relationship between wind shortfall, DC load, and price spikes.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.path import Path
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde


# ── Ireland coastline ───────────────────────────────────────────────
IRELAND = np.array([
    (-7.37, 55.37), (-7.87, 55.20), (-8.28, 55.16), (-8.62, 54.97),
    (-8.77, 54.67), (-9.14, 54.30), (-9.60, 54.27), (-9.99, 54.30),
    (-10.11, 53.93), (-9.95, 53.75), (-9.65, 53.65), (-9.90, 53.47),
    (-9.74, 53.22), (-9.07, 53.12), (-8.88, 52.89), (-9.93, 52.57),
    (-10.18, 52.10), (-10.43, 51.80), (-9.81, 51.45), (-8.99, 51.58),
    (-8.25, 51.71), (-7.83, 51.82), (-6.93, 52.11), (-6.41, 52.19),
    (-6.07, 52.41), (-6.03, 53.10), (-6.08, 53.38), (-6.15, 53.60),
    (-6.23, 54.00), (-5.99, 54.25), (-5.58, 54.42), (-5.41, 54.65),
    (-5.67, 55.20), (-6.20, 55.35), (-7.37, 55.37),
])

# ── Assets (lon, lat, MW) ───────────────────────────────────────────
WIND_FARMS = [
    ("Oweninny",      -9.550, 54.151, 192),
    ("Galway WP",     -9.370, 53.355, 174),
    ("Grousemount",   -9.331, 51.877, 114),
    ("Gusta Gaoithe", -9.314, 53.348, 101),
    ("Meenadreen",    -8.100, 54.750,  95),  # Donegal approx
    ("Knockacummer",  -9.111, 52.259, 100),
    ("Knockduff",     -8.830, 52.032,  65),
    ("Derrybrien",    -8.606, 53.093,  60),
    ("Boggeragh",     -8.898, 52.051,  57),
    ("Carrigdangan",  -9.139, 51.803,  54),
    ("Bindoo",        -7.107, 54.012,  48),
    ("Cloghboola",    -9.438, 52.336,  48),
    ("Cloncreen",     -7.400, 53.350,  75),  # Offaly approx
    ("Mountlucas",    -7.236, 53.271,  84),
    ("Bruckana",      -7.669, 52.782,  42),
    ("Ballywater",    -6.240, 52.535,  42),
]

GAS_PLANTS = [
    ("Huntstown",  -6.310, 53.393, 744),
    ("Poolbeg",    -6.213, 53.332, 450),
    ("Aghada",     -8.150, 51.880, 900),
    ("Whitegate",  -8.260, 51.850, 445),
    ("Great Island",-6.890, 52.310, 108),
    ("Edenderry",  -7.050, 53.340, 120),
    ("Tarbert",    -9.378, 52.575, 600),
]

DATA_CENTRES = [
    ("AWS (Clonshaugh)", -6.172, 53.391, 500),
    ("AWS (Tallaght)",   -6.380, 53.290, 300),
    ("Google (Grange C)",-6.417, 53.323, 700),
    ("Google (Portarl)", -7.189, 53.154,  80),
    ("Meta (Clonee)",    -6.452, 53.432, 400),
    ("Microsoft",        -6.330, 53.360, 250),
    ("Equinix DUB",      -6.261, 53.340, 120),
    ("Athlone DCs",      -7.940, 53.420,  80),
    ("Cork DCs",         -8.470, 51.900,  60),
]

INTERCONNECTORS = [
    ("EWIC\n(to Wales)",    -6.730, 53.540, "+"),  # Woodland substation
    ("Greenlink\n(to Wales)",-7.090, 52.200, "+"), # Kilmurrin substation
]

# ── Price data (EUR/MWh) ────────────────────────────────────────────
PRICES = {
    "2023-07": 96.26,  "2023-08": 106.42, "2023-09": 111.64,
    "2023-10": 125.52, "2023-11": 122.90, "2023-12": 89.07,
    "2024-01": 99.85,  "2024-02": 84.62,  "2024-03": 86.63,
    "2024-04": 88.57,  "2024-05": 107.70, "2024-06": 107.72,
    "2024-07": 110.94, "2024-08": 100.41, "2024-09": 112.75,
    "2024-10": 123.55, "2024-11": 146.16, "2024-12": 137.10,
    "2025-01": 167.33, "2025-02": 140.90, "2025-03": 131.80,
    "2025-04": 111.01, "2025-05": 108.82, "2025-06": 95.19,
    "2025-07": 99.62,  "2025-08": 96.44,  "2025-09": 94.44,
    "2025-10": 100.63, "2025-11": 122.90, "2025-12": 107.66,
    "2026-01": 126.96, "2026-02": 107.98, "2026-03": 128.70,
    "2026-04": 112.83,
}


def draw_arrow(ax, x0, y0, x1, y1, color, lw=1.2, alpha=0.6, style="->"):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, alpha=alpha,
                                connectionstyle="arc3,rad=0.15"))


def load_eirgrid(path):
    df = pd.read_excel(path, engine="openpyxl")
    df["ts"] = pd.to_datetime(df["DateTime"])
    df = df.set_index("ts").sort_index()
    df["net_ic"]     = df["EWIC I/C"] + df["Greenlink I/C"]
    df["wind_cover"] = df["IE Wind Generation"] / df["IE Demand"]
    df["gas_proxy"]  = (df["IE Demand"] - df["IE Wind Generation"]
                        - df["IE Solar Generation"] - df["IE Hydro"]
                        - df["net_ic"]).clip(lower=0)
    return df


def map_panel(ax, df):
    ax.set_facecolor("#e8f4f8")
    poly = plt.Polygon(IRELAND, closed=True, facecolor="#f5f0e8",
                       edgecolor="#888", lw=1.0, zorder=1)
    ax.add_patch(poly)

    # Wind farms
    for name, lon, lat, mw in WIND_FARMS:
        ax.scatter(lon, lat, s=mw * 0.35, color="#3ab87a",
                   alpha=0.75, zorder=3, edgecolors="white", lw=0.4)

    # Gas plants
    for name, lon, lat, mw in GAS_PLANTS:
        ax.scatter(lon, lat, s=mw * 0.2, color="#e05c2a",
                   marker="s", alpha=0.8, zorder=4, edgecolors="white", lw=0.4)

    # Data centres
    for name, lon, lat, mw in DATA_CENTRES:
        ax.scatter(lon, lat, s=mw * 0.3, color="#7b4fa6",
                   marker="D", alpha=0.9, zorder=5, edgecolors="white", lw=0.5)

    # Interconnectors
    for name, lon, lat, sym in INTERCONNECTORS:
        ax.scatter(lon, lat, s=120, color="#2e6fba", marker="*",
                   zorder=6, edgecolors="white", lw=0.5)
        ax.text(lon + 0.08, lat - 0.12, name, fontsize=5.5,
                color="#2e6fba", ha="left", va="top")

    # Flow arrows: wind (west) → demand centre (Dublin)
    dublin_lon, dublin_lat = -6.30, 53.36
    for _, lon, lat, mw in WIND_FARMS:
        if mw >= 84 and lon < -8.0:  # big western farms only
            draw_arrow(ax, lon, lat, dublin_lon, dublin_lat,
                       color="#3ab87a", lw=0.7, alpha=0.3)

    # Interconnector import arrows → Dublin
    for _, lon, lat, _ in INTERCONNECTORS:
        draw_arrow(ax, lon, lat, dublin_lon, dublin_lat,
                   color="#2e6fba", lw=1.0, alpha=0.5)

    # Labels for big DCs
    for name, lon, lat, mw in DATA_CENTRES:
        if mw >= 300:
            short = name.split("(")[0].strip()
            ax.text(lon + 0.08, lat + 0.04, short, fontsize=5.5,
                    color="#7b4fa6", fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=1.5, foreground="white")])

    ax.set_xlim(-10.8, -5.1)
    ax.set_ylim(51.2, 55.8)
    ax.set_aspect("equal")
    ax.set_title("Electricity assets & flow — Ireland", fontsize=10, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=8)
    ax.set_ylabel("Latitude", fontsize=8)
    ax.tick_params(labelsize=7)

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#3ab87a",
               markersize=8, label="Wind farm"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#e05c2a",
               markersize=7, label="Gas plant"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#7b4fa6",
               markersize=7, label="Data centre"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#2e6fba",
               markersize=9, label="Interconnector"),
    ]
    ax.legend(handles=legend_elements, fontsize=7, loc="lower left",
              framealpha=0.9)


def price_panel(ax):
    dates  = pd.to_datetime([k + "-01" for k in PRICES])
    prices = list(PRICES.values())

    colors = ["#e05c2a" if p > 130 else "#2e6fba" for p in prices]
    ax.bar(dates, prices, color=colors, width=25, alpha=0.8)
    ax.axhline(np.mean(prices), color="gray", lw=1, linestyle="--", alpha=0.7)
    ax.text(dates[-1], np.mean(prices) + 3, f"avg €{np.mean(prices):.0f}",
            fontsize=7, color="gray")

    # Annotate peaks
    for d, p in zip(dates, prices):
        if p >= 160 or p <= 85:
            ax.annotate(f"€{p:.0f}", xy=(d, p),
                        xytext=(0, 6 if p >= 160 else -14),
                        textcoords="offset points",
                        fontsize=6.5, ha="center",
                        color="#e05c2a" if p >= 160 else "#2e6fba")

    ax.set_ylabel("€/MWh", fontsize=8)
    ax.set_title("Ireland wholesale electricity price", fontsize=10, fontweight="bold")
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    spike_patch = mpatches.Patch(color="#e05c2a", alpha=0.8, label=">€130 spike")
    norm_patch  = mpatches.Patch(color="#2e6fba", alpha=0.8, label="≤€130 normal")
    ax.legend(handles=[spike_patch, norm_patch], fontsize=7)


def wind_price_panel(ax, df):
    # Daily avg wind cover and gas proxy — shows when gas sets price
    daily_wind = df["wind_cover"].resample("D").mean() * 100
    daily_gas  = df["gas_proxy"].resample("D").mean()

    ax2 = ax.twinx()
    ax.fill_between(daily_wind.index, daily_wind,
                    alpha=0.4, color="#3ab87a", label="Wind cover %")
    ax.plot(daily_wind.index, daily_wind, color="#3ab87a", lw=1.2)

    ax2.plot(daily_gas.index, daily_gas, color="#e05c2a",
             lw=1.5, label="Gas/import proxy (MW)")
    ax2.set_ylabel("Gas + import residual (MW)", fontsize=8, color="#e05c2a")
    ax2.tick_params(axis="y", colors="#e05c2a", labelsize=7)

    # Shade low-wind days (high price risk)
    low_wind = daily_wind[daily_wind < 25]
    for d in low_wind.index:
        ax.axvspan(d, d + pd.Timedelta("1D"), alpha=0.12, color="red")

    ax.set_ylabel("Wind as % of demand", fontsize=8, color="#3ab87a")
    ax.tick_params(axis="y", colors="#3ab87a", labelsize=7)
    ax.tick_params(axis="x", labelsize=7)
    ax.set_title("Low wind = gas sets price — Jan/Feb 2026 (red = wind <25% of demand)",
                 fontsize=9, fontweight="bold")
    ax.grid(axis="x", alpha=0.2)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=7)
    for spine in ["top"]:
        ax.spines[spine].set_visible(False)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="/Users/adams/Downloads/System-Data-Qtr-Hourly-2026-v2.xlsx")
    args = parser.parse_args()

    df = load_eirgrid(args.file)

    fig = plt.figure(figsize=(16, 14))
    gs  = gridspec.GridSpec(2, 2, hspace=0.38, wspace=0.32,
                            height_ratios=[1.6, 1])

    map_panel(        fig.add_subplot(gs[0, 0]), df)
    price_panel(      fig.add_subplot(gs[0, 1]))
    wind_price_panel( fig.add_subplot(gs[1, :]), df)

    fig.suptitle(
        "Ireland compute grid — asset flows, price spikes, and the wind–gas–price mechanism",
        fontsize=13, fontweight="bold", y=1.005
    )
    plt.savefig("ie_flow_map.png", dpi=160, bbox_inches="tight")
    print("Saved ie_flow_map.png")


if __name__ == "__main__":
    main()
