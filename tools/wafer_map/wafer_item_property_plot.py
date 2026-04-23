"""
Wafer property map renderer using PySide6 offscreen QPainter.
Each die is coloured by a continuous PIN value using HSV scale:
  high value -> red     (hue 0°)
  low  value -> blue    (hue 240°)

Colour scale bounds are auto-calculated from data:
  IQR robust sigma:
  sigma = (P75 - P25) / 1.35
  DataL = P50 - 6 * sigma
  DataH = P50 + 6 * sigma
so that subtle variation becomes visible.
"""

import base64
import csv
import math
import os
import statistics
import sys
import zipfile
from io import StringIO

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

# font bootstrap
_FONT_FAMILY = "Arial"
_FONT_LOADED  = False

def _ensure_font(app: QApplication) -> None:
    """Load a system TTF in offscreen mode (which has no font discovery)."""
    global _FONT_LOADED
    if _FONT_LOADED:
        return
    for path in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(path):
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    global _FONT_FAMILY
                    _FONT_FAMILY = families[0]
            break
    _FONT_LOADED = True


# fixed colours
_C_NAN  = QColor(130, 130, 130)   # outside wafer boundary
_C_GRID = QColor(0,   0,   0)     # grid lines


def _die_color(value: float, data_l: float, data_h: float) -> QColor:
    """Map a scalar value to a blue-to-red HSV colour."""
    span = data_h - data_l
    if span <= 0:
        t = 0.5
    else:
        t = (value - data_l) / span
    t = max(0.0, min(1.0, t)) # clamp to [0, 1]
    hue_f = 0.667 * (1.0 - t) # 0.667=blue (low) … 0.0=red (high)
    return QColor.fromHsvF(hue_f, 0.95, 0.92)


def _compute_scale(values: list[float]) -> tuple[float, float, float, float]:
    """
    Return (data_l, data_h, value_p50, x_sigma).

    data_l = round(P50 - 6*sigma, q2_decimal_count)
    data_h = round(P50 + 6*sigma, q2_decimal_count)

    q2_decimal_count is derived from the magnitude of sigma so that
    the rounded values preserve meaningful precision.
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    value_p50 = statistics.median(sorted_vals)
    value_p25 = sorted_vals[round(n * 0.25)]
    value_p75 = sorted_vals[round(n * 0.75)]
    x_sigma   = (value_p75 - value_p25) / 1.35 if n > 1 else 0.0

    if x_sigma > 0:
        magnitude = math.floor(math.log10(x_sigma))
        q2_decimal_count = max(0, -magnitude + 2)
    else:
        q2_decimal_count = 4

    data_l = round(value_p50 - 6 * x_sigma, q2_decimal_count)
    data_h = round(value_p50 + 6 * x_sigma, q2_decimal_count)
    return data_l, data_h, value_p50, x_sigma


def _read_rows(file_path: str) -> list[dict]:
    if file_path.lower().endswith(".zip"):
        with zipfile.ZipFile(file_path) as z:
            csv_name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            content = z.open(csv_name).read().decode("utf-8")
    else:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    return list(csv.DictReader(StringIO(content)))


def render_wafer_property(
    file_path: str,
    pin_column: str = "PIN_1",
    target_size: int = 250,
    output_path: str | None = None,
    data_l: float | None = None,
    data_h: float | None = None,
) -> str:
    """
    Render a continuous-value wafer map for *pin_column*.

    Parameters
    ----------
    file_path   : .csv or .zip path
    pin_column  : column name to visualise (default "PIN_1")
    target_size : image pixel size
    output_path : save PNG here; if None return base64 string
    data_l / data_h : override auto-calculated colour scale bounds

    Returns
    -------
    output_path (str) or base64 PNG string
    """
    _app = QApplication.instance() or QApplication(sys.argv)
    _ensure_font(_app)

    rows = _read_rows(file_path)

    xs = [int(r["X"]) for r in rows]
    ys = [int(r["Y"]) for r in rows]
    max_x, max_y = max(xs), max(ys)

    cols  = max_x + 1
    nrows = max_y + 1

    # Build lookup: (x, y) -> pin value
    die_map: dict[tuple[int, int], float] = {
        (int(r["X"]), int(r["Y"])): float(r[pin_column])
        for r in rows
        if r.get(pin_column, "").strip() not in ("", "nan", "NaN")
    }

    # scale
    all_vals = list(die_map.values())
    auto_l, auto_h, p50, sigma = _compute_scale(all_vals)
    if data_l is None:
        data_l = auto_l
    if data_h is None:
        data_h = auto_h

    # decimal places for labels (same logic as _compute_scale)
    if sigma > 0:
        mag = math.floor(math.log10(sigma))
        dec = max(0, -mag + 2)
    else:
        dec = 4

    # wafer grid setup
    cell_w = target_size / cols
    cell_h = target_size / nrows
    img_w  = round(cell_w * cols)
    img_h  = round(cell_h * nrows)

    wafer_img = QImage(img_w, img_h, QImage.Format.Format_RGB32)
    p = QPainter(wafer_img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(QPen(_C_GRID, 1))

    for row_i in range(nrows):
        for col_i in range(cols):
            x = round(col_i * cell_w)
            y = round(row_i * cell_h)
            w = round((col_i + 1) * cell_w) - x
            h = round((row_i + 1) * cell_h) - y
            key = (col_i, row_i)
            fill = _die_color(die_map[key], data_l, data_h) if key in die_map else _C_NAN
            p.fillRect(x, y, w, h, fill)
            p.drawRect(x, y, w - 1, h - 1)

    p.end()

    # color bar layout
    CBAR_LEFT   = 18   # gap between wafer and bar
    CBAR_W      = 20   # bar width
    TICK_LEN    = 5    # tick mark length
    TICK_PAD    = 4    # gap between tick and text
    FONT_SIZE   = 11
    TEXT_W      = 72   # reserved for label text
    V_PAD       = 20   # vertical padding inside color bar

    extra_w = CBAR_LEFT + CBAR_W + TICK_LEN + TICK_PAD + TEXT_W
    full_w  = img_w + extra_w
    full_h  = img_h

    full_img = QImage(full_w, full_h, QImage.Format.Format_RGB32)
    full_img.fill(QColor(245, 245, 245))

    p = QPainter(full_img)
    p.drawImage(0, 0, wafer_img)

    # ── gradient bar ───────────────────────────────────────────────────────
    cbar_x   = img_w + CBAR_LEFT
    cbar_top = V_PAD
    cbar_bot = full_h - V_PAD
    cbar_h   = cbar_bot - cbar_top

    N = 200
    for i in range(N):
        t = i / (N - 1)   # 0 = top = high = red
        hue_f = 0.667 * t # 0.0=red … 0.667=blue
        c = QColor.fromHsvF(hue_f, 0.95, 0.92)
        seg_y = cbar_top + round(i * cbar_h / N)
        seg_h = max(1, round((i + 1) * cbar_h / N) - round(i * cbar_h / N))
        p.fillRect(cbar_x, seg_y, CBAR_W, seg_h, c)

    # bar border
    p.setPen(QPen(QColor(80, 80, 80), 1))
    p.drawRect(cbar_x, cbar_top, CBAR_W - 1, cbar_h - 1)

    # ── tick marks & labels ────────────────────────────────────────────────
    span  = data_h - data_l if data_h != data_l else 1.0
    ticks = [
        (data_h, "IQR_H"),
        (p50,    "P50"),
        (data_l, "IQR_L"),
    ]

    font = QFont(_FONT_FAMILY)
    font.setPixelSize(FONT_SIZE + 1)
    p.setFont(font)
    p.setPen(QPen(QColor(30, 30, 30), 1))

    tick_x0 = cbar_x + CBAR_W # right edge of bar
    tick_x1 = tick_x0 + TICK_LEN
    label_x = tick_x1 + TICK_PAD

    for val, label in ticks:
        # y position: top = DataH, bottom = DataL (linear mapping)
        frac  = (data_h - val) / span   # 0=top, 1=bottom
        tick_y = cbar_top + round(frac * cbar_h)

        # tick line
        p.drawLine(tick_x0, tick_y, tick_x1, tick_y)

        # value text (small, above) + label text (below)
        val_str   = f"{val:.{dec}f}"
        label_str = f"({label})"

        # value on one line, label on next, centred on tick_y
        LINE_H = FONT_SIZE + 3
        p.drawText(label_x, tick_y - 1,         val_str)
        p.drawText(label_x, tick_y + LINE_H - 1, label_str)

    p.end()

    if output_path:
        full_img.save(output_path)
        return output_path

    buf_data = QByteArray()
    buf = QBuffer(buf_data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    full_img.save(buf, "PNG")
    return base64.b64encode(bytes(buf_data)).decode()


# standalone preview
if __name__ == "__main__":
    here   = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.normpath(
        os.path.join(here, "..", "..", "..", "raw_data_example", "wafer_data", "sample_1.zip")
    )

    out = os.path.join(here, "wafer_property_preview.png")
    render_wafer_property(sample, pin_column="PIN_1", target_size=500, output_path=out)
    print(f"Saved -> {out}")
