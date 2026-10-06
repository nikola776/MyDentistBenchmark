# /// script
# requires-python = ">=3.12"
# dependencies = ["imageio-ffmpeg>=0.5"]
# ///
"""Convert recordings to the 16 kHz mono PCM16 WAV the benchmark streams.

Usage:
    uv run scripts/convert.py                      # data/*  -> data/wav/
    uv run scripts/convert.py path/to/a.m4a dir/   # specific files / folders
    uv run scripts/convert.py raw_noise/ -o noise  # e.g. your own noise clips

Uses ffmpeg from PATH if present, otherwise the static binary bundled with
imageio-ffmpeg (no system install needed). Outputs that are newer than their
source are skipped unless --force is given.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_EXTS = {
    ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aac",
    ".mp4", ".webm", ".wma", ".aif", ".aiff", ".amr", ".3gp",
}
TARGET = (16000, 1, 2)  # sample rate, channels, bytes per sample


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def collect(inputs: list[Path], out_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in inputs:
        if p.is_dir():
            # Non-recursive: data/ holds originals, its subfolders hold generated audio.
            files.extend(f for f in sorted(p.iterdir()) if f.suffix.lower() in AUDIO_EXTS)
        elif p.is_file():
            files.append(p)
        else:
            sys.exit(f"not found: {p}")
    return [f for f in files if f.resolve().parent != out_dir.resolve()]


def wav_format(path: Path) -> tuple[int, int, int] | None:
    try:
        with wave.open(str(path), "rb") as w:
            return (w.getframerate(), w.getnchannels(), w.getsampwidth())
    except (wave.Error, EOFError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", type=Path, default=[ROOT / "data"])
    parser.add_argument("-o", "--out-dir", type=Path, default=ROOT / "data" / "wav")
    parser.add_argument("--force", action="store_true", help="re-convert even if output is up to date")
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    files = collect(args.inputs, out_dir)
    if not files:
        sys.exit(f"no audio files found in: {', '.join(map(str, args.inputs))}")

    stems: dict[str, Path] = {}
    for f in files:
        if f.stem in stems:
            sys.exit(f"two inputs would both become {f.stem}.wav: {stems[f.stem]} and {f}")
        stems[f.stem] = f

    ffmpeg = ffmpeg_exe()
    for src in files:
        dst = out_dir / f"{src.stem}.wav"
        if (
            not args.force
            and dst.exists()
            and dst.stat().st_mtime >= src.stat().st_mtime
            and wav_format(dst) == TARGET
        ):
            print(f"skip     {dst.relative_to(ROOT) if dst.is_relative_to(ROOT) else dst} (up to date)")
            continue
        cmd = [
            ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(src),
            "-map", "0:a:0", "-map_metadata", "-1",
            "-ac", "1", "-ar", str(TARGET[0]), "-c:a", "pcm_s16le", str(dst),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"ffmpeg failed on {src}:\n{proc.stderr.strip()}")
        if wav_format(dst) != TARGET:
            sys.exit(f"unexpected output format for {dst}: {wav_format(dst)}")
        with wave.open(str(dst), "rb") as w:
            secs = w.getnframes() / w.getframerate()
        print(f"convert  {src.name} -> {dst.relative_to(ROOT) if dst.is_relative_to(ROOT) else dst} ({secs:.2f}s)")


if __name__ == "__main__":
    main()
