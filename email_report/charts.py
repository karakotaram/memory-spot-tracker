"""Render YTD indexed price charts (PNG bytes) for embedding in the daily email.

Emails can't run JavaScript, so the interactive Chart.js views on the website are
reproduced here as static images. They mirror the site's look: the same
colorblind-safe palette, a base=100 index, and de-collided end-of-line labels.
"""

import csv
import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend for CI
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

# Colorblind-safe categorical palette (validated: adjacent CVD deltaE >= 8) — matches the site.
COLORS = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
]

# A few source rows carry a typo'd product name on a single date — merge them (matches the site).
PRODUCT_ALIASES = {
    "DDR4 16Gb (2Gx8)3200": "DDR4 16Gb (2Gx8) 3200",
    "DDR5 16G (2Gx8) 4800/5600": "DDR5 16Gb (2Gx8) 4800/5600",
}

INK = "#1a1a2e"
MUTED = "#6c757d"
GRID = "#e6e5de"
AXIS = "#c3c2b7"


def _short_label(product: str) -> str:
    """Compact label drawn at the end of each line (matches the site's shortLabel)."""
    s = re.sub(r"\(.*?\)", " ", product)
    s = re.sub(r"\d+GBx8|\d+MBx8|\d+Mx8", "", s)
    s = re.sub(r"1600/1866|4800/5600|3200|1866|1600", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _read_series(csv_path: Path, cutoff: str):
    """Return [(product, [(date, avg), ...]), ...] for rows on/after `cutoff`, in first-seen order."""
    order, by_product = [], {}
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            if not r.get("date") or r["date"] < cutoff:
                continue
            product = PRODUCT_ALIASES.get(r["product"], r["product"])
            try:
                avg = float(r["session_avg"])
            except (TypeError, ValueError):
                continue
            if product not in by_product:
                by_product[product] = []
                order.append(product)
            by_product[product].append((r["date"], avg))
    return [(p, sorted(by_product[p], key=lambda x: x[0])) for p in order]


def _render(series, title: str):
    """Render one category's YTD indexed chart to PNG bytes (or None if no data)."""
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=200)
    fig.subplots_adjust(left=0.09, right=0.79, top=0.87, bottom=0.13)

    end_points, y_all = [], []
    for i, (product, pts) in enumerate(series):
        base = pts[0][1] if pts else 0
        if not base:
            continue
        xs = [datetime.strptime(d, "%Y-%m-%d") for d, _ in pts]
        ys = [v / base * 100 for _, v in pts]
        y_all.extend(ys)
        color = COLORS[i % len(COLORS)]
        ax.plot(xs, ys, color=color, linewidth=1.8, solid_capstyle="round", solid_joinstyle="round")
        ax.plot(xs[-1], ys[-1], "o", color=color, markersize=3.6,
                markeredgecolor="white", markeredgewidth=0.8, zorder=5)
        end_points.append([ys[-1], color, _short_label(product)])

    if not y_all:
        plt.close(fig)
        return None

    ymin, ymax = min(y_all), max(y_all)
    span = (ymax - ymin) or 1
    pad = span * 0.08
    top = ymax + pad
    ax.set_ylim(ymin - pad, top)

    # base = 100 reference line
    ax.axhline(100, color=AXIS, linewidth=1, linestyle=(0, (2, 3)), zorder=1)

    # de-collide end labels in data space, then shift down if they overflow the top
    end_points.sort(key=lambda e: e[0])
    gap = span * 0.062
    for j in range(1, len(end_points)):
        if end_points[j][0] - end_points[j - 1][0] < gap:
            end_points[j][0] = end_points[j - 1][0] + gap
    overflow = end_points[-1][0] - top
    if overflow > 0:
        for e in end_points:
            e[0] -= overflow
    ytrans = ax.get_yaxis_transform()  # x in axes fraction, y in data coords
    for y, color, label in end_points:
        ax.text(1.02, y, label, transform=ytrans, color=color, fontsize=7.5,
                fontweight="bold", va="center", ha="left", clip_on=False)

    # chrome
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=7.5, length=0)
    ax.set_ylabel("Indexed (base = 100)", color=MUTED, fontsize=7.5)
    ax.set_title(title, color=INK, fontsize=10.5, fontweight="bold", loc="left", pad=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def generate_ytd_charts():
    """Return {cid: png_bytes} for the DRAM and NAND YTD indexed charts.

    Never raises — on any failure the offending chart is skipped so the email
    still sends with its tables intact.
    """
    year = datetime.now(timezone.utc).year
    cutoff = f"{year}-01-01"
    specs = [
        ("dram_chart", DATA_DIR / "dram_spot.csv", f"DRAM — {year} YTD relative performance"),
        ("nand_chart", DATA_DIR / "nand_spot.csv", f"NAND flash — {year} YTD relative performance"),
    ]
    out = {}
    for cid, path, title in specs:
        try:
            if not path.exists():
                logger.warning("Chart source missing: %s", path)
                continue
            png = _render(_read_series(path, cutoff), title)
            if png:
                out[cid] = png
        except Exception as e:  # noqa: BLE001 — email must survive a chart failure
            logger.warning("Failed to render %s chart: %s", cid, e)
    return out
