# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Download real background-noise recordings into noise/ for add_noise.py.

Source: DEMAND (Diverse Environments Multichannel Acoustic Noise Database),
Thiemann, Ito & Vincent, 2013 - https://zenodo.org/records/1227121
License: CC BY-SA 3.0. Each environment is a 5-minute 16 kHz recording; only
channel 1 is kept (~10 MB per environment; each download is ~100 MB).

Usage:
    uv run scripts/fetch_noise.py                    # cafeteria + street
    uv run scripts/fetch_noise.py office station bus
    uv run scripts/fetch_noise.py --list

You can also drop your own clips (wav/flac, any rate) into noise/ and refer to
them by file name in noise.yaml.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://zenodo.org/records/1227121/files/{code}_16k.zip?download=1"

ENVIRONMENTS = {
    "kitchen": "DKITCHEN",
    "living": "DLIVING",
    "washing": "DWASHING",
    "field": "NFIELD",
    "park": "NPARK",
    "river": "NRIVER",
    "hallway": "OHALLWAY",
    "meeting": "OMEETING",
    "office": "OOFFICE",
    "cafeteria": "PCAFETER",
    "restaurant": "PRESTO",
    "station": "PSTATION",
    "cafe": "SCAFE",
    "square": "SPSQUARE",
    "street": "STRAFFIC",
    "bus": "TBUS",
    "car": "TCAR",
    "metro": "TMETRO",
}
DEFAULT = ["cafeteria", "street"]

ATTRIBUTION = """\
Files named after DEMAND environments in this folder come from:
  DEMAND: Diverse Environments Multichannel Acoustic Noise Database
  J. Thiemann, N. Ito, E. Vincent (2013). https://zenodo.org/records/1227121
  License: CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/)
  Only channel 1 (ch01.wav) of each 16 kHz environment is kept.
"""


def fetch(name: str, out_dir: Path) -> None:
    dst = out_dir / f"{name}.wav"
    if dst.exists():
        print(f"skip     {name} (noise/{dst.name} exists)")
        return
    code = ENVIRONMENTS[name]
    url = URL.format(code=code)
    print(f"download {name} ({code}) ...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{code}.zip"
        with urllib.request.urlopen(url, timeout=60) as resp, zip_path.open("wb") as f:  # noqa: S310
            shutil.copyfileobj(resp, f, length=1 << 20)
        with zipfile.ZipFile(zip_path) as zf:
            member = next((n for n in zf.namelist() if n.endswith("ch01.wav")), None)
            if member is None:
                sys.exit(f"{code}: ch01.wav not found in archive")
            with zf.open(member) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
    print(f"saved    noise/{dst.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", default=DEFAULT, help="environment names (see --list)")
    parser.add_argument("-o", "--out-dir", type=Path, default=ROOT / "noise")
    parser.add_argument("--list", action="store_true", help="list available environments")
    args = parser.parse_args()

    if args.list:
        for name, code in ENVIRONMENTS.items():
            print(f"{name:<11} {code}")
        return
    unknown = [n for n in args.names if n not in ENVIRONMENTS]
    if unknown:
        sys.exit(f"unknown environment(s): {', '.join(unknown)}. Use --list.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ATTRIBUTION.txt").write_text(ATTRIBUTION)
    for name in args.names:
        fetch(name, args.out_dir)


if __name__ == "__main__":
    main()
