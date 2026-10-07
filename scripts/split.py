# /// script
# requires-python = ">=3.12"
# dependencies = ["imageio-ffmpeg>=0.5", "numpy>=1.26", "soundfile>=0.12"]
# ///
"""Split one recording into separately benchmarked parts.

Usage:
    uv run scripts/split.py data/Richard.m4a script=0-2:17 scenarios=2:21-end

Each NAME=START-END becomes data/<recording>_<NAME>.wav at the original quality.
Audio between parts (e.g. a spoken heading like "Scenarios") is dropped. Times
are seconds or m:ss; each cut moves to the quietest point within --snap seconds
so no word is cut in half.

A part is scored against transcripts/<recording>_<NAME>.txt if it exists, else
the shared transcripts/<NAME>.txt (so a part named "script" uses script.txt).

The original moves to data/unsplit/ and its generated audio (data/wav,
data/noisy) is removed, so it isn't benchmarked as a whole any more. Then rerun
convert.py and add_noise.py.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def parse_time(text: str) -> float:
    m = re.fullmatch(r"(?:(\d+):)?(\d+(?:\.\d+)?)", text.strip())
    if not m:
        sys.exit(f"bad time {text!r}: use seconds (135) or m:ss (2:15)")
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:05.2f}"


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode(path: Path) -> tuple[np.ndarray, int]:
    """Decode any format losslessly to 16-bit PCM, keeping sample rate and channels."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "full.wav"
        cmd = [ffmpeg_exe(), "-nostdin", "-v", "error", "-y", "-i", str(path),
               "-map", "0:a:0", "-map_metadata", "-1", "-c:a", "pcm_s16le", str(wav)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"ffmpeg failed on {path}:\n{proc.stderr.strip()}")
        audio, sr = sf.read(str(wav), dtype="int16", always_2d=True)
    return audio, sr


def snap(t: float, energy: np.ndarray, hop_s: float, window_s: float) -> float:
    """Move a cut to the quietest 100 ms stretch within +-window_s."""
    if window_s <= 0:
        return t
    smooth = np.convolve(energy, np.ones(5) / 5, mode="same")
    lo = max(0, int((t - window_s) / hop_s))
    hi = min(len(smooth), int((t + window_s) / hop_s) + 1)
    if hi <= lo:
        return t
    return (lo + int(np.argmin(smooth[lo:hi]))) * hop_s + hop_s / 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", type=Path)
    parser.add_argument("parts", nargs="+", metavar="NAME=START-END")
    parser.add_argument("--snap", type=float, default=0.5, metavar="SECONDS",
                        help="move each cut to the quietest point within this many seconds (0 = exact)")
    args = parser.parse_args()

    src: Path = args.recording
    if not src.is_file():
        sys.exit(f"not found: {src}")
    stem = src.stem

    parts: list[tuple[str, float, float | None]] = []
    for spec in args.parts:
        m = re.fullmatch(r"([A-Za-z0-9-]+)=([^-]+)-(.+)", spec)
        if not m:
            sys.exit(f"bad part {spec!r}: use NAME=START-END, e.g. script=0-2:17 or scenarios=2:21-end")
        end = None if m.group(3) == "end" else parse_time(m.group(3))
        parts.append((m.group(1), parse_time(m.group(2)), end))

    audio, sr = decode(src)
    duration = len(audio) / sr
    hop = 0.02
    mono = audio.astype(np.float64).mean(axis=1)
    n = len(mono) // int(hop * sr)
    energy = (mono[: n * int(hop * sr)].reshape(n, -1) ** 2).mean(axis=1)

    out_paths = []
    for name, start, end in parts:
        a = 0.0 if start == 0 else snap(start, energy, hop, args.snap)
        b = duration if end is None else snap(min(end, duration), energy, hop, args.snap)
        if not 0 <= a < b <= duration:
            sys.exit(f"{name}: empty or out-of-range part ({fmt(a)}-{fmt(b)} of {fmt(duration)})")
        dst = DATA / f"{stem}_{name}.wav"
        sf.write(str(dst), audio[int(a * sr) : int(b * sr)], sr, subtype="PCM_16")
        out_paths.append(dst)
        print(f"wrote    {dst.relative_to(ROOT)}  {fmt(a)}-{fmt(b)} ({b - a:.1f}s)")

    # Take the whole recording out of the pipeline: originals live in data/ (non-recursive),
    # generated copies in data/wav and data/noisy/<variant>.
    unsplit = DATA / "unsplit"
    if src.resolve().parent == DATA.resolve():
        unsplit.mkdir(exist_ok=True)
        shutil.move(str(src), unsplit / src.name)
        print(f"moved    {src.name} -> data/unsplit/")
    for generated in [DATA / "wav" / f"{stem}.wav", *DATA.glob(f"noisy/*/{stem}.wav")]:
        generated.unlink()
        print(f"removed  {generated.relative_to(ROOT)}")
    print("next: uv run scripts/convert.py && uv run scripts/add_noise.py")


if __name__ == "__main__":
    main()
