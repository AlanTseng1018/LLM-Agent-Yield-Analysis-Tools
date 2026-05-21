"""
MCP server - Wafer tools
Transport: Streamable HTTP  →  http://0.0.0.0:8001/mcp
Run:  python server.py

Tools
-----
[workflow]
run_wafer_analysis      Full analysis in one call: info + binary map + PIN maps

[primitives]
get_wafer_info          Basic wafer summary  (yield, pass/fail, wafer_id …)
plot_wafer_bin          Binary pass/fail map  (BIN=0 → teal, else → black)
plot_wafer_property     Continuous-value map  (low(blue) → high(red), auto IQR scale)
note: IQR scale L_IQR = P50 - 6 x IQR_Sigma; H_IQR = P50 + 6 x IQR_Sigma
      Where IQR_sigma = (P75 - P25) / 1.35

[statistics]
plot_pchart             Normal probability (P-chart) for a PIN column, per wafer
"""

import os
import sys
# ── path bootstrap so imports work regardless of cwd ──
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from tools.information_read.read_wafer_info import read_wafer_info, _read_rows
from tools.wafer_map.wafer_bin_binary_plot import render_wafer_bin
from tools.wafer_map.wafer_item_property_plot import render_wafer_property, compute_property_stats
from tools.workflow.analyze_wafer import analyze_wafer
from tools.statistic_plot.pchart_plot import render_pchart, compute_pchart_stats


# ── fact-card helpers ──────────────────────────────────────────────────────
# Each plotting tool returns a short text "fact card" alongside its image.
# Numbers a vision model would otherwise have to read off tiny pixels (yield,
# IQR scale bounds, percentiles) are given as exact text, so the model can
# focus on the spatial pattern instead of OCR-ing labels.

def _lot_name(file_path: str) -> str:
    """Wafer lot name from the data's Wafer_lot_name column; file name as fallback."""
    try:
        rows = _read_rows(file_path)
        if rows:
            name = (rows[0].get("Wafer_lot_name") or "").strip()
            if name:
                return name
    except Exception:
        pass
    stem = os.path.basename(file_path)
    for ext in (".zip", ".csv"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
    return stem or "unknown"


def _binary_fact_card(file_path: str) -> str:
    lines = ["[Wafer Facts]", f"Product / Lot: {_lot_name(file_path)}"]
    for w in read_wafer_info(file_path):
        lines.append(
            f"Wafer {w['wafer_id']}: yield {w['yield_pct']}% "
            f"({w['pass_count']} pass / {w['fail_count']} fail / {w['test_die']} dies)"
        )
    return "\n".join(lines)


def _property_fact_card(file_path: str, pin_column: str) -> str:
    s = compute_property_stats(file_path, pin_column)
    head = f"[Wafer Facts]\nProduct / Lot: {_lot_name(file_path)}\nPIN: {pin_column}"
    if s.get("n", 0) == 0:
        return f"{head}\n(no numeric data)"
    return (
        f"{head}\n"
        f"Statistics: P50={s['p50']:.4g}, IQR sigma={s['sigma']:.4g}, N={s['n']} dies\n"
        f"Colour scale (auto IQR): low={s['iqr_l']:.4g} (blue) ... high={s['iqr_h']:.4g} (red)"
    )


def _pchart_fact_card(file_path: str, pin_column: str) -> str:
    s = compute_pchart_stats(file_path, pin_column)
    head = f"[Wafer Facts]\nProduct / Lot: {_lot_name(file_path)}\nPIN: {pin_column}"
    if s.get("n", 0) == 0:
        return f"{head}\n(no numeric data)"
    return (
        f"{head}\n"
        f"Statistics: P50={s['p50']:.4g}, IQR sigma={s['sigma']:.4g}\n"
        f"IQR boundaries: IQR_L={s['iqr_l']:.4g}, IQR_H={s['iqr_h']:.4g}\n"
        f"N={s['n']}, Fail={s['fail']}, Yield={s['yield']}"
    )

# ── server instance ──
mcp = FastMCP(
    name="wafer-map",
    host="0.0.0.0",
    port=8001,
    instructions=(
        "Wafer analysis tools. "
        "Data files are CSV or ZIP (containing one CSV) with columns: "
        "BIN, X, Y, WAFER_ID, PIN_1,....PIN_N. "
        "Use run_wafer_analysis for a full analysis in one call. "
        "Use individual tools (get_wafer_info, plot_wafer_bin, plot_wafer_property) "
        "for targeted requests."
    ),
)


# ── workflow: full analysis ──
@mcp.tool()
def run_wafer_analysis(
    file_path: str,
    pin_columns: list[str] | None = None,
    target_size: int = 300,
) -> list[TextContent | ImageContent]:
    """
    Full wafer analysis in one call.

    Runs in order:
      1. Wafer summary  (yield, pass/fail counts, available PIN columns)
      2. Binary pass/fail map image
      3. Per-PIN continuous property map image (for every PIN column, or the
         subset specified by pin_columns)

    Parameters
    ----------
    file_path   : Path to .csv or .zip wafer data file.
    pin_columns : PIN columns to visualise, e.g. ["PIN_1", "PIN_3"].
                  Omit to plot all available PIN columns.
    target_size : Output image pixel size.  Default 300.

    Returns
    -------
    List of mixed content: text summary, binary map, per-PIN property maps.
    """
    result = analyze_wafer(file_path, pin_columns=pin_columns, target_size=target_size)

    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=result["summary"]),
        TextContent(type="text", text="### Binary pass/fail map"),
        ImageContent(type="image", data=result["bin_map"], mimeType="image/png"),
    ]
    for pin in result["pin_maps"]:
        content.append(TextContent(type="text", text=f"### {pin} property map"))
        content.append(ImageContent(type="image", data=result["pin_maps"][pin], mimeType="image/png"))
        content.append(TextContent(type="text", text=f"### {pin} P-chart"))
        content.append(ImageContent(type="image", data=result["pin_charts"][pin], mimeType="image/png"))

    return content


# ── tool 1: read basic wafer info ─────────────────────────────────────────
@mcp.tool()
def get_wafer_info(file_path: str) -> list[dict]:
    """
    Read basic summary information from a wafer data file.

    Returns one record per WAFER_ID with:
      wafer_id    : wafer identifier
      test_die    : total dies tested
      pass_count  : dies with BIN = 0
      fail_count  : dies with BIN != 0
      yield_pct   : pass rate in % (2 decimal places)
      pin_columns : PIN measurement columns available in the file

    Parameters
    ----------
    file_path : Absolute or relative path to a .csv or .zip file.
                The ZIP must contain exactly one .csv.
    """
    return read_wafer_info(file_path)


# ── tool 2: binary pass/fail ───────────────────────────────────────────────
@mcp.tool()
def plot_wafer_bin(
    file_path: str,
    target_size: int = 300,
) -> list[TextContent | ImageContent]:
    """
    Render a binary pass/fail wafer map.

    Each die is coloured by its BIN value:
      - BIN = 0  → teal   (pass)
      - BIN ≠ 0  → black  (fail)
      - no die   → gray   (outside wafer boundary)

    Parameters
    ----------
    file_path   : Absolute or relative path to a .csv or .zip file.
                  The ZIP must contain exactly one .csv.
    target_size : Output image pixel size (width and height).  Default 300.

    Returns
    -------
    A text fact card (product/lot, yield) followed by the PNG wafer map.
    """
    b64 = render_wafer_bin(file_path, target_size=target_size)
    return [
        TextContent(type="text", text=_binary_fact_card(file_path)),
        ImageContent(type="image", data=b64, mimeType="image/png"),
    ]


# ── tool 3: continuous PIN property map ───────────────────────────────────
@mcp.tool()
def plot_wafer_property(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 450,
    data_l: float | None = None,
    data_h: float | None = None,
) -> list[TextContent | ImageContent]:
    """
    Render a continuous-value wafer map for a single PIN measurement.

    Colour scale (blue → green → red):
      - High value → red
      - Low  value → blue

    Scale bounds are auto-calculated when omitted:
      DataL = P50 - 6 * Sigma_IQR   (Sigma_IQR = (P75 - P25) / 1.35)
      DataH = P50 + 6 * Sigma_IQR

    Parameters
    ----------
    file_path   : Absolute or relative path to a .csv or .zip file.
    pin_column  : Column name to visualise (e.g. "PIN_1", "PIN_3").  Default "PIN_1".
    target_size : Output image pixel size.  Default 500.
    data_l      : Override lower bound of colour scale.
    data_h      : Override upper bound of colour scale.

    Returns
    -------
    A text fact card (product/lot, PIN statistics, IQR scale) followed by the
    PNG property map.
    """
    b64 = render_wafer_property(
        file_path,
        pin_column=pin_column,
        target_size=target_size,
        data_l=data_l,
        data_h=data_h,
    )
    return [
        TextContent(type="text", text=_property_fact_card(file_path, pin_column)),
        ImageContent(type="image", data=b64, mimeType="image/png"),
    ]


# ── tool: P-chart (normal probability plot) ───────────────────────────────
@mcp.tool()
def plot_pchart(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 300,
) -> list[TextContent | ImageContent]:
    """
    Render a P-chart (normal probability plot) for a single PIN column.

    Each WAFER_ID is plotted as a separate ECDF line on a normal-probability
    Y-axis.  A straight line on this chart means the data is normally distributed.

    Boundary lines are auto-computed using IQR robust sigma (same as property map):
        sigma = (P75 - P25) / 1.35
        IQR_L = P50 - 6 * sigma  (blue dashed)
        IQR_H = P50 + 6 * sigma  (red  dashed)

    Parameters
    ----------
    file_path   : Absolute or relative path to a .csv or .zip file.
    pin_column  : PIN measurement column to plot (e.g. "PIN_1").  Default "PIN_1".
    target_size : Output image pixel size.  Default 300.

    Returns
    -------
    A text fact card (product/lot, PIN statistics, IQR boundaries) followed by
    the PNG P-chart.
    """
    b64 = render_pchart(file_path, pin_column=pin_column, target_size=target_size)
    return [
        TextContent(type="text", text=_pchart_fact_card(file_path, pin_column)),
        ImageContent(type="image", data=b64, mimeType="image/png"),
    ]


# ── entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
