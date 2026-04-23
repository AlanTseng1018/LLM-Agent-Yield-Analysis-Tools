"""
Workflow: full wafer analysis in one call.

Steps
-----
1. read_wafer_info          → text summary (yield, pass/fail, available PINs)
2. render_wafer_bin         → binary pass/fail map image
3. render_wafer_property    (× each PIN) → property heatmap images
4. render_pchart            (× each PIN) → P-chart (normal probability plot) images
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))

from tools.information_read.read_wafer_info import read_wafer_info
from tools.wafer_map.wafer_bin_binary_plot import render_wafer_bin
from tools.wafer_map.wafer_item_property_plot import render_wafer_property
from tools.statistic_plot.pchart_plot import render_pchart


def _format_summary(infos: list[dict]) -> str:
    lines = ["## Wafer Analysis Summary", ""]
    for w in infos:
        lines += [
            f"**Wafer ID : {w['wafer_id']}**",
            f"  Test Die  : {w['test_die']}",
            f"  Pass      : {w['pass_count']}",
            f"  Fail      : {w['fail_count']}",
            f"  Yield     : {w['yield_pct']} %",
            f"  PIN cols  : {', '.join(w['pin_columns'])}",
            "",
        ]
    return "\n".join(lines)


def analyze_wafer(
    file_path: str,
    pin_columns: list[str] | None = None,
    target_size: int = 300,
) -> dict:
    """
    Run full wafer analysis and return a structured result.

    Parameters
    ----------
    file_path   : Path to .csv or .zip wafer data file.
    pin_columns : Which PIN columns to plot.  None = all available PINs.
    target_size : Image size in pixels.

    Returns
    -------
    {
      "summary"   : str           – formatted text summary
      "bin_map"   : str           – base64 PNG, binary pass/fail map
      "pin_maps"  : {str: str}    – base64 PNG property heatmap per PIN
      "pin_charts": {str: str}    – base64 PNG P-chart per PIN
    }
    """
    # ── 1. read info ───────────────────────────────────────────────────────
    infos = read_wafer_info(file_path)
    summary = _format_summary(infos)

    all_pins = infos[0]["pin_columns"] if infos else []
    pins_to_plot = pin_columns if pin_columns else all_pins

    # ── 2. binary map ──────────────────────────────────────────────────────
    bin_b64 = render_wafer_bin(file_path, target_size=target_size)

    # ── 3. per-PIN property maps ───────────────────────────────────────────
    pin_maps: dict[str, str] = {}
    for pin in pins_to_plot:
        pin_maps[pin] = render_wafer_property(
            file_path, pin_column=pin, target_size=target_size
        )

    # ── 4. per-PIN P-charts ────────────────────────────────────────────────
    pin_charts: dict[str, str] = {}
    for pin in pins_to_plot:
        pin_charts[pin] = render_pchart(
            file_path, pin_column=pin, target_size=target_size
        )

    return {
        "summary":    summary,
        "bin_map":    bin_b64,
        "pin_maps":   pin_maps,
        "pin_charts": pin_charts,
    }
