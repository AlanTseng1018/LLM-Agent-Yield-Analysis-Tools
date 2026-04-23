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
# path bootstrap so imports work regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import base64 as _base64
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent, ImageContent

from tools.information_read.read_wafer_info import read_wafer_info
from tools.wafer_map.wafer_bin_binary_plot import render_wafer_bin
from tools.wafer_map.wafer_item_property_plot import render_wafer_property
from tools.workflow.analyze_wafer import analyze_wafer
from tools.statistic_plot.pchart_plot import render_pchart

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


# workflow: full analysis
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


# tool 1: read basic wafer info
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


# tool 2: binary pass/fail
@mcp.tool()
def plot_wafer_bin(
    file_path: str,
    target_size: int = 300,
) -> Image:
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
    PNG image of the wafer map.
    """
    b64 = render_wafer_bin(file_path, target_size=target_size)
    return Image(data=_base64.b64decode(b64), format="png")


# tool 3: continuous PIN property map
@mcp.tool()
def plot_wafer_property(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 450,
    data_l: float | None = None,
    data_h: float | None = None,
) -> Image:
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
    PNG image with colour bar showing DataL, P50, and DataH tick marks.
    """
    b64 = render_wafer_property(
        file_path,
        pin_column=pin_column,
        target_size=target_size,
        data_l=data_l,
        data_h=data_h,
    )
    return Image(data=_base64.b64decode(b64), format="png")


# tool: P-chart (normal probability plot)
@mcp.tool()
def plot_pchart(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 300,
) -> Image:
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
    PNG image with per-wafer ECDF lines, IQR boundary lines, and a stats box.
    """
    b64 = render_pchart(file_path, pin_column=pin_column, target_size=target_size)
    return Image(data=_base64.b64decode(b64), format="png")


# entry point
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
