"""
Wafer binary bin map renderer using PySide6 offscreen QPainter.
BIN=0  → green  (pass)
BIN!=0 → black  (fail)
no die → light gray (outside wafer boundary)
"""

import base64
import csv
import os
import sys
import zipfile
from io import StringIO

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# ── colours ────────────────────────────────────────────────────────────────
_C_NAN   = QColor(130, 130, 130)   # gray  – no die
_C_PASS  = QColor(10, 186, 181)   # teal        – BIN = 0
_C_FAIL  = QColor(30,   30,  30)   # near-black  – BIN != 0
_C_GRID  = QColor(0,     0,   0)   # black grid lines


def _read_rows(file_path: str) -> list[dict]:
    """Load CSV rows from a plain .csv or a .zip containing one .csv."""
    if file_path.lower().endswith(".zip"):
        with zipfile.ZipFile(file_path) as z:
            csv_name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            content = z.open(csv_name).read().decode("utf-8")
    else:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    return list(csv.DictReader(StringIO(content)))


def render_wafer_bin(
    file_path: str,
    target_size: int = 250,
    output_path: str | None = None,
) -> str:
    """
    Render a binary wafer map from file_path.

    Parameters
    ----------
    file_path   : path to .csv or .zip containing a single .csv
    target_size : approximate pixel size of the output image (width & height)
    output_path : if given, save PNG to this path; otherwise return base64 PNG

    Returns
    -------
    If output_path is None  -> base64-encoded PNG string
    If output_path is given -> the output_path string
    """
    _app = QApplication.instance() or QApplication(sys.argv)

    rows = _read_rows(file_path)

    xs = [int(r["X"]) for r in rows]
    ys = [int(r["Y"]) for r in rows]
    max_x, max_y = max(xs), max(ys)

    cols = max_x + 1   # grid width  (e.g. 57 for X 0-56)
    nrows = max_y + 1  # grid height (e.g. 41 for Y 0-40)

    # Build lookup: (x, y) -> bin value
    die_map: dict[tuple[int, int], int] = {
        (int(r["X"]), int(r["Y"])): int(r["BIN"]) for r in rows
    }

    # Cell size scales with die count on each axis independently
    # so the image fills target_size × target_size as fully as possible
    cell_w = target_size / cols   # float – width  per die column
    cell_h = target_size / nrows  # float – height per die row

    img_w = round(cell_w * cols)
    img_h = round(cell_h * nrows)

    image = QImage(img_w, img_h, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # Grid pen (1 px, drawn inside fillRect so it doesn't overflow)
    grid_pen = QPen(_C_GRID)
    grid_pen.setWidth(1)
    painter.setPen(grid_pen)

    for row_i in range(nrows):
        for col_i in range(cols):
            # Pixel-snapped rect to avoid sub-pixel gaps between cells
            x = round(col_i * cell_w)
            y = round(row_i * cell_h)
            w = round((col_i + 1) * cell_w) - x
            h = round((row_i + 1) * cell_h) - y

            key = (col_i, row_i)
            if key not in die_map:
                fill = _C_NAN
            elif die_map[key] == 0:
                fill = _C_PASS
            else:
                fill = _C_FAIL

            # Fill body
            painter.fillRect(x, y, w, h, fill)
            # Grid border (drawn on top of fill, inside the cell)
            painter.drawRect(x, y, w - 1, h - 1)

    painter.end()

    if output_path:
        image.save(output_path)
        return output_path

    buf_data = QByteArray()
    buf = QBuffer(buf_data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return base64.b64encode(bytes(buf_data)).decode()


# ── standalone preview ──────────────────────────────────────────────────────
if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.normpath(
        os.path.join(here, "..", "..", "..", "raw_data_example", "wafer_data", "sample_1.zip")
    )

    out = os.path.join(here, "wafer_preview.png")
    render_wafer_bin(sample, target_size=500, output_path=out)
    print(f"Saved -> {out}")
