"""
P-Chart (Normal Probability Plot) renderer
==========================================
Headless matplotlib implementation — no Qt window required.

For each WAFER_ID in the dataset, plots the ECDF of a chosen PIN column
on a normal-probability Y-axis so deviations from a straight line indicate
non-normality, and spec-limit lines show the pass/fail boundary.

Public API
----------
render_pchart(file_path, pin_column, spec_l, spec_h, target_size)
    Returns a base64-encoded PNG string.
"""
from __future__ import annotations

import base64
import csv
import math
import zipfile
from io import BytesIO, StringIO

import matplotlib
matplotlib.use("Agg")   # headless — must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.scale as mscale
import matplotlib.ticker as ticker
import matplotlib.transforms as mtransforms
import numpy as np
from scipy.stats import norm
from statsmodels.distributions.empirical_distribution import ECDF


# Probability scale (identical logic to original PchartReportWidget)

class _ProbabilityTransform(mtransforms.Transform):
    input_dims = output_dims = 1
    is_separable = True

    def transform_non_affine(self, a):
        return norm.ppf(np.clip(a, 1e-5, 1 - 1e-5))

    def inverted(self):
        return _InvertedProbabilityTransform()


class _InvertedProbabilityTransform(mtransforms.Transform):
    input_dims = output_dims = 1
    is_separable = True

    def transform_non_affine(self, a):
        return norm.cdf(a)

    def inverted(self):
        return _ProbabilityTransform()


class _ProbabilityScale(mscale.ScaleBase):
    name = "prob_scale_headless"

    def __init__(self, axis, **kwargs):
        super().__init__(axis)

    def get_transform(self):
        return _ProbabilityTransform()

    def set_default_locators_and_formatters(self, axis):
        pcts = np.array([0.01, 0.1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 99.99]) / 100
        axis.set_major_locator(ticker.FixedLocator(pcts))
        axis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x * 100:.2f}%")
        )


mscale.register_scale(_ProbabilityScale)


# Data helpers

def _read_rows(file_path: str) -> list[dict]:
    if file_path.lower().endswith(".zip"):
        with zipfile.ZipFile(file_path) as z:
            csv_name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            content = z.open(csv_name).read().decode("utf-8")
    else:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    return list(csv.DictReader(StringIO(content)))


def _to_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _iqr_bounds(data: list[float]) -> tuple[float, float, float]:
    """
    Compute IQR-based bounds (same formula as wafer_item_property_plot).

    Returns (iqr_l, p50, iqr_h) where:
        sigma = (P75 - P25) / 1.35
        IQR_L = P50 - 6 * sigma
        IQR_H = P50 + 6 * sigma
    """
    arr = np.array(data)
    p25, p50, p75 = float(np.percentile(arr, 25)), float(np.percentile(arr, 50)), float(np.percentile(arr, 75))
    sigma = (p75 - p25) / 1.35
    return p50 - 6 * sigma, p50, p50 + 6 * sigma


def _calculate_fail_count(
    data: list[float],
    iqr_l: float,
    iqr_h: float,
) -> tuple[int, int, str]:
    total = len(data)
    if total == 0:
        return 0, 0, "N/A"
    fail = sum(1 for v in data if v < iqr_l or v > iqr_h)
    yield_str = f"{round((total - fail) / total * 100, 2)}%"
    return total, fail, yield_str


# ── Main renderer ────────────────────────────────────────────────────────────

_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]
_MARKERS = ["o", "^", "s", "p", "*", "h", "D", "x", "P", "X"]


def render_pchart(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 300,
) -> str:
    """
    Render a P-chart (normal probability plot) for one PIN column.

    Boundary lines are auto-computed from the data using IQR robust sigma:
        sigma = (P75 - P25) / 1.35
        IQR_L = P50 - 6 * sigma   (blue dashed line)
        IQR_H = P50 + 6 * sigma   (red  dashed line)

    Parameters
    ----------
    file_path  : Path to .csv or .zip file.
    pin_column : Column name to plot (e.g. "PIN_1").
    target_size: Output image size in pixels (width & height).

    Returns
    -------
    Base64-encoded PNG string.
    """
    rows = _read_rows(file_path)

    # Group by WAFER_ID
    buckets: dict[str, list[float]] = {}
    for r in rows:
        v = _to_float(r.get(pin_column))
        if v is None:
            continue
        wid = r.get("WAFER_ID", "W?").strip()
        buckets.setdefault(wid, []).append(v)

    if not buckets:
        raise ValueError(f"No valid numeric data found in column '{pin_column}'.")

    dpi = 150
    fig_size = target_size / dpi
    fig, ax = plt.subplots(figsize=(fig_size * 1.4, fig_size), dpi=dpi)
    fig.patch.set_facecolor("#ffffff")

    all_values: list[float] = []

    for idx, (wid, values) in enumerate(sorted(buckets.items())):
        values.sort()
        all_values.extend(values)

        cumprob = ECDF(values)(values)
        color  = _COLORS[idx % len(_COLORS)]
        marker = _MARKERS[idx % len(_MARKERS)]

        ax.step(
            values, cumprob,
            where="post",
            color=color,
            marker=marker,
            markersize=2,
            alpha=0.8,
            linewidth=0.8,
            label=f"Wafer {wid}",
        )

    # ── Probability Y-axis ────────────────────────────────────────────────
    ax.set_yscale("prob_scale_headless")
    ax.set_ylim(0, 1)

    # ── IQR bounds ────────────────────────────────────────────────────────
    iqr_l, p50, iqr_h = _iqr_bounds(all_values)
    ax.axvline(iqr_h, color="red",   linestyle="--", linewidth=1.0,
               label=f"IQR_H = {iqr_h:.4g}")
    ax.axvline(iqr_l, color="blue",  linestyle="--", linewidth=1.0,
               label=f"IQR_L = {iqr_l:.4g}")
    ax.axvline(p50,   color="green", linestyle="--", linewidth=1.0,
               label=f"P50   = {p50:.4g}")

    # ── X-axis range: IQR_L/H with 20% padding ───────────────────────────
    span = (iqr_h - iqr_l) or abs(p50) * 0.2 or 1.0
    ax.set_xlim(iqr_l - span * 0.2, iqr_h + span * 0.2)

    # ── Stats box ─────────────────────────────────────────────────────────
    total, fail, yield_str = _calculate_fail_count(all_values, iqr_l, iqr_h)
    stats_lines = [
        f"N     : {total}",
        f"Fail  : {fail}",
        f"Yield : {yield_str}",
    ]

    ax.text(
        0.02, 0.02,
        "\n".join(stats_lines),
        transform=ax.transAxes,
        ha="left", va="bottom",
        fontsize=5.5,
        color="#1a1a1a",
        bbox=dict(facecolor="white", edgecolor="#cccccc",
                  alpha=0.85, boxstyle="round,pad=0.3"),
    )

    # Cosmetics
    ax.set_title(f"P-Chart  —  {pin_column}", fontsize=7, pad=4)
    ax.set_xlabel("Value", fontsize=6)
    ax.set_ylabel("Cumulative Probability", fontsize=6)
    ax.tick_params(axis="both", labelsize=5)
    ax.grid(True, linewidth=0.4, alpha=0.5)
    ax.legend(
        loc="upper left",
        prop={"size": 5},
        framealpha=0.7,
        borderaxespad=0.5,
    )

    fig.tight_layout(pad=0.8)

    # Encode to base64 PNG
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# Standalone test
if __name__ == "__main__":
    import os

    here   = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.normpath(
        os.path.join(here, "..", "..", "..", "raw_data_example", "wafer_data", "sample_1.zip")
    )
    out = os.path.join(here, "pchart_preview.png")

    b64 = render_pchart(sample, pin_column="PIN_1", target_size=400)
    with open(out, "wb") as f:
        f.write(base64.b64decode(b64))
    print(f"Saved → {out}")
