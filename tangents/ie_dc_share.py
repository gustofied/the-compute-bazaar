"""
Ireland data centre electricity share — trend + country comparison.
Sources: EirGrid annual reports, IEA, Eurostat.
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches


# --- Ireland historical DC share (% of metered electricity) ---
# Source: EirGrid annual sustainability/system reports
IE_YEARS  = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]
IE_SHARE  = [  5.1,  6.4,  7.5,  9.2, 11.0, 12.8, 14.2, 18.0, 21.0]

# Projection to 2030 (EirGrid Tomorrow's Energy Scenarios)
PROJ_YEARS = [2023, 2025, 2027, 2030]
PROJ_LOW   = [21.0, 23.0, 25.0, 27.0]
PROJ_HIGH  = [21.0, 26.0, 30.0, 34.0]

# --- Country comparison (2023, % of national electricity) ---
# Sources: IEA, national grid reports, EuropeActive Datacentres
COUNTRIES = [
    ("Ireland",       21.0),
    ("Singapore",      8.0),
    ("Denmark",        4.8),
    ("Netherlands",    3.5),
    ("Sweden",         3.2),
    ("Finland",        2.9),
    ("Germany",        1.8),
    ("UK",             1.5),
    ("USA",            2.5),
    ("EU avg",         1.2),
]
COUNTRIES = sorted(COUNTRIES, key=lambda x: x[1], reverse=True)
c_names  = [c[0] for c in COUNTRIES]
c_shares = [c[1] for c in COUNTRIES]


# --- Key events ---
EVENTS = [
    (2021, "Dublin grid\nmoratorium"),
    (2022, "EirGrid\ncapacity warning"),
]


def main():
    fig = plt.figure(figsize=(13, 6))
    gs  = gridspec.GridSpec(1, 2, width_ratios=[1.6, 1], wspace=0.38)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    # ── Left: Ireland trend ──────────────────────────────────────────
    ax1.fill_between(PROJ_YEARS, PROJ_LOW, PROJ_HIGH,
                     alpha=0.15, color="#e05c2a", label="EirGrid projection range")
    ax1.plot(PROJ_YEARS, PROJ_LOW,  "--", color="#e05c2a", lw=1.2, alpha=0.7)
    ax1.plot(PROJ_YEARS, PROJ_HIGH, "--", color="#e05c2a", lw=1.2, alpha=0.7)

    ax1.plot(IE_YEARS, IE_SHARE, color="#2e6fba", lw=2.2, zorder=3)
    ax1.scatter(IE_YEARS, IE_SHARE, color="#2e6fba", s=45, zorder=4)

    # Annotate last known point
    ax1.annotate("21% (2023)", xy=(2023, 21.0),
                 xytext=(2020.5, 22.5),
                 fontsize=8.5, color="#2e6fba",
                 arrowprops=dict(arrowstyle="->", color="#2e6fba", lw=1))

    # Event markers
    for yr, label in EVENTS:
        ax1.axvline(yr, color="gray", lw=0.9, linestyle=":", alpha=0.7)
        ax1.text(yr + 0.1, 2.5, label, fontsize=7, color="gray",
                 va="bottom", ha="left")

    # EU average reference line
    ax1.axhline(1.2, color="green", lw=1, linestyle="--", alpha=0.5)
    ax1.text(2015.1, 1.6, "EU avg ~1.2%", fontsize=7, color="green", alpha=0.8)

    ax1.set_xlim(2014.5, 2030.5)
    ax1.set_ylim(0, 38)
    ax1.set_xlabel("Year", fontsize=10)
    ax1.set_ylabel("Data centre share of national electricity (%)", fontsize=10)
    ax1.set_title("Ireland: data centre electricity share", fontsize=11, fontweight="bold")

    hist_patch = mpatches.Patch(color="#2e6fba", label="Historical (EirGrid)")
    proj_patch = mpatches.Patch(color="#e05c2a", alpha=0.5, label="Projected range")
    ax1.legend(handles=[hist_patch, proj_patch], fontsize=8, loc="upper left")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax1.grid(axis="y", alpha=0.3)

    # ── Right: country comparison ────────────────────────────────────
    colors = ["#e05c2a" if c == "Ireland" else "#2e6fba" for c in c_names]
    bars = ax2.barh(c_names, c_shares, color=colors, height=0.6)

    for bar, val in zip(bars, c_shares):
        ax2.text(val + 0.3, bar.get_y() + bar.get_height() / 2,
                 f"{val:.1f}%", va="center", fontsize=8.5)

    ax2.set_xlim(0, 26)
    ax2.set_xlabel("Data centre share of national electricity (%)", fontsize=10)
    ax2.set_title("Country comparison (2023)", fontsize=11, fontweight="bold")
    ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax2.invert_yaxis()
    ax2.grid(axis="x", alpha=0.3)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    for ax in [ax1, ax2]:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.suptitle(
        "Ireland is the most compute-intensive grid in the EU",
        fontsize=13, fontweight="bold", y=1.01
    )

    plt.tight_layout()
    plt.savefig("ie_dc_share.png", dpi=180, bbox_inches="tight")
    print("Saved ie_dc_share.png")


if __name__ == "__main__":
    main()
