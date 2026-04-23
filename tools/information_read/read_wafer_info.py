"""
Read basic wafer information from a CSV or ZIP data file.

Returns a list of per-wafer summary dicts (one entry per WAFER_ID):
  wafer_id    : wafer identifier
  test_die    : total number of tested dies
  pass_count  : dies with BIN = 0
  fail_count  : dies with BIN != 0
  yield_pct   : pass_count / test_die × 100  (rounded to 2 dp)
  pin_columns : PIN columns present in the file
"""

import csv
import zipfile
from io import StringIO

from typing_extensions import TypedDict


class WaferInfo(TypedDict):
    wafer_id: str
    test_die: int
    pass_count: int
    fail_count: int
    yield_pct: float
    pin_columns: list[str]


def _read_rows(file_path: str) -> list[dict]:
    if file_path.lower().endswith(".zip"):
        with zipfile.ZipFile(file_path) as z:
            csv_name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            content = z.open(csv_name).read().decode("utf-8")
    else:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    return list(csv.DictReader(StringIO(content)))


def read_wafer_info(file_path: str) -> list[WaferInfo]:
    """
    Parse wafer data and return a summary for each WAFER_ID found.

    Parameters
    ----------
    file_path : path to .csv or .zip (ZIP must contain one .csv)

    Returns
    -------
    List of WaferInfo dicts, one per unique WAFER_ID, sorted by wafer_id.
    """
    rows = _read_rows(file_path)
    if not rows:
        return []

    # Identify PIN columns
    pin_cols = sorted(c for c in rows[0].keys() if c.upper().startswith("PIN"))

    # Group by WAFER_ID
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        wid = r.get("WAFER_ID", "unknown").strip()
        buckets.setdefault(wid, []).append(r)

    result: list[WaferInfo] = []
    for wid in sorted(buckets.keys()):
        dies = buckets[wid]
        test_die   = len(dies)
        pass_count = sum(1 for d in dies if d.get("BIN", "").strip() == "0")
        fail_count = test_die - pass_count
        yield_pct  = round(pass_count / test_die * 100, 2) if test_die else 0.0

        result.append(
            WaferInfo(
                wafer_id=wid,
                test_die=test_die,
                pass_count=pass_count,
                fail_count=fail_count,
                yield_pct=yield_pct,
                pin_columns=pin_cols,
            )
        )

    return result


# standalone test
if __name__ == "__main__":
    import os, pprint
    here   = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.normpath(
        os.path.join(here, "..", "..", "..", "raw_data_example", "wafer_data", "sample_1.zip")
    )
    for info in read_wafer_info(sample):
        pprint.pprint(info)
