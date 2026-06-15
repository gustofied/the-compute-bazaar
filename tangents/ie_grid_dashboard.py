"""
Ireland grid dashboard — load balancing patterns, spikes, and renewable dynamics.
Uses EirGrid quarter-hourly Excel data.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
from matplotlib.colors import TwoSlopeNorm


def load(filepath: str) -> pd.DataFrame:
    df = pd.read_excel(filepath, engine="openpyxl")
    df["ts"] = pd.to_datetime(df["DateTime"], utc=False)
    df = df.set_index("ts").sort_index()
    df["net_interconnect"] = df["EWIC I/C"] + df["Greenlink I/C"]  # + = importing
    df["wind_pct"] = df["IE Wind Generation"] / df["IE Demand"] * 100
    df["hour"] = df.index.hour + df.index.minute / 60
    df["date"] = df.index.date
    return df


def demand_heatmap(ax, df):
    pivot = df.pivot_table(index="date", columns=df.index.hour, values="IE Demand", aggfunc="mean")
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn_r",
                   vmin=3300, vmax=5900)
    ax.set_title("IE Demand heatmap — MW by hour of day", fontsize=10, fontweight="bold")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Date")
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 3)], fontsize=7)
    dates = list(pivot.index)
    tick_pos  = list(range(0, len(dates), max(1, len(dates)//8)))
    ax.set_yticks(tick_pos)
    ax.set_yticklabels([str(dates[i]) for i in tick_pos], fontsize=7)
    plt.colorbar(im, ax=ax, label="MW", fraction=0.03, pad=0.02)


def wind_vs_demand(ax, df):
    # Colour by time of day
    c = df.index.hour
    sc = ax.scatter(df["IE Wind Generation"], df["IE Demand"],
                    c=c, cmap="twilight", alpha=0.25, s=4, linewidths=0)
    # Mark extreme demand spikes
    threshold = df["IE Demand"].quantile(0.99)
    spikes = df[df["IE Demand"] >= threshold]
    ax.scatter(spikes["IE Wind Generation"], spikes["IE Demand"],
               color="red", s=18, zorder=5, label=f"Top 1% demand (>{threshold:.0f} MW)")
    ax.set_xlabel("Wind generation (MW)")
    ax.set_ylabel("IE Demand (MW)")
    ax.set_title("Wind generation vs demand", fontsize=10, fontweight="bold")
    cb = plt.colorbar(sc, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("Hour of day", fontsize=8)
    ax.legend(fontsize=7, markerscale=1.5)
    ax.grid(alpha=0.2)


def snsp_series(ax, df):
    daily_max  = df["SNSP"].resample("D").max()
    daily_mean = df["SNSP"].resample("D").mean()
    ax.fill_between(daily_max.index, daily_mean, daily_max,
                    alpha=0.3, color="#e05c2a", label="Daily max")
    ax.plot(daily_mean.index, daily_mean, color="#2e6fba", lw=1.5, label="Daily mean")
    ax.axhline(0.75, color="red", lw=1.2, linestyle="--", label="75% SNSP limit")
    # Mark days that hit the limit
    hits = daily_max[daily_max >= 0.74]
    ax.scatter(hits.index, hits, color="red", s=25, zorder=5)
    ax.set_ylabel("SNSP")
    ax.set_title("System Non-Synchronous Penetration — grid stability", fontsize=10, fontweight="bold")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(fontsize=7)
    ax.grid(alpha=0.2)
    ax.set_ylim(0, 0.9)


def interconnector_flow(ax, df):
    daily = df["net_interconnect"].resample("D").mean()
    colors = ["#2e6fba" if v >= 0 else "#e05c2a" for v in daily]
    ax.bar(daily.index, daily, color=colors, width=0.8, alpha=0.85)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Net flow MW (+ = importing)")
    ax.set_title("Interconnector net flow — EWIC + Greenlink", fontsize=10, fontweight="bold")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    # Annotation
    peak_import = daily.idxmax()
    peak_export = daily.idxmin()
    ax.annotate(f"Peak import\n{daily[peak_import]:.0f} MW",
                xy=(peak_import, daily[peak_import]),
                xytext=(10, 5), textcoords="offset points", fontsize=7, color="#2e6fba")
    ax.annotate(f"Peak export\n{daily[peak_export]:.0f} MW",
                xy=(peak_export, daily[peak_export]),
                xytext=(5, -30), textcoords="offset points", fontsize=7, color="#e05c2a")
    ax.grid(axis="y", alpha=0.2)


def demand_spike_zoom(ax, df):
    # Find the single biggest demand spike and zoom in 48h around it
    peak_ts = df["IE Demand"].idxmax()
    window = df.loc[peak_ts - pd.Timedelta("24h") : peak_ts + pd.Timedelta("24h")]
    ax.plot(window.index, window["IE Demand"], color="#2e6fba", lw=1.5, label="IE Demand")
    ax.plot(window.index, window["IE Wind Generation"], color="green", lw=1.2, alpha=0.8, label="Wind gen")
    ax.axvline(peak_ts, color="red", lw=1, linestyle="--")
    ax.text(peak_ts, window["IE Demand"].max(), f" Peak\n {df['IE Demand'].max():.0f} MW",
            color="red", fontsize=7, va="top")
    ax.set_title(f"Biggest demand spike — 48h window around {peak_ts.strftime('%d %b %H:%M')}",
                 fontsize=10, fontweight="bold")
    ax.set_ylabel("MW")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.legend(fontsize=7)
    ax.grid(alpha=0.2)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="/Users/adams/Downloads/System-Data-Qtr-Hourly-2026-v2.xlsx")
    args = parser.parse_args()

    df = load(args.file)
    print(f"Loaded {len(df)} rows: {df.index[0].date()} -> {df.index[-1].date()}")

    fig = plt.figure(figsize=(16, 12))
    gs  = gridspec.GridSpec(3, 2, hspace=0.45, wspace=0.32)

    demand_heatmap(   fig.add_subplot(gs[0, :]), df)
    wind_vs_demand(   fig.add_subplot(gs[1, 0]), df)
    snsp_series(      fig.add_subplot(gs[1, 1]), df)
    interconnector_flow(fig.add_subplot(gs[2, 0]), df)
    demand_spike_zoom(  fig.add_subplot(gs[2, 1]), df)

    fig.suptitle("Ireland grid — load balancing patterns Jan–Feb 2026", fontsize=14, fontweight="bold", y=1.01)
    plt.savefig("ie_grid_dashboard.png", dpi=160, bbox_inches="tight")
    print("Saved ie_grid_dashboard.png")


if __name__ == "__main__":
    main()
