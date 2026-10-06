# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["silero-vad>=5.1", "soundfile>=0.12", "numpy>=1.26", "torch", "torchaudio"]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# torchaudio = { index = "pytorch-cpu" }
# ///
"""Find where speech ends in each clean recording (needed for TTFS).

Usage:
    uv run scripts/vad.py            # data/wav/*.wav -> data/wav/speech_end.json

Same method and defaults as the benchmark's runner/scripts/precompute_vad_offsets.py:
SileroVAD, min_silence 300 ms, speech_pad 100 ms, speech end = end of the last
speech segment, clamped to the clip length. run_benchmark.py calls this
automatically when an offset is missing or the audio changed.

Offsets are computed on the clean audio only. Noise doesn't move where the
speaker stops, and running VAD on noisy audio would shift the anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-dir", type=Path, default=ROOT / "data" / "wav")
    parser.add_argument("--min-silence-ms", type=int, default=300)
    parser.add_argument("--speech-pad-ms", type=int, default=100)
    parser.add_argument("--force", action="store_true", help="recompute every file")
    args = parser.parse_args()

    out_path = args.audio_dir / "speech_end.json"
    params = {"method": "silero-vad", "min_silence_ms": args.min_silence_ms, "speech_pad_ms": args.speech_pad_ms}
    cache = json.loads(out_path.read_text()) if out_path.exists() else {}
    files: dict[str, dict] = cache.get("files", {}) if cache.get("params") == params and not args.force else {}

    todo = [p for p in sorted(args.audio_dir.glob("*.wav")) if files.get(p.name, {}).get("sha256") != sha256(p)]
    if todo:
        import numpy as np
        import soundfile as sf
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        model = load_silero_vad()
        for path in todo:
            wav_np, sr = sf.read(str(path), dtype="float32")
            if wav_np.ndim > 1:
                wav_np = np.mean(wav_np, axis=1)
            wav = torch.from_numpy(np.ascontiguousarray(wav_np))
            ts = get_speech_timestamps(
                wav,
                model,
                sampling_rate=sr,
                min_silence_duration_ms=args.min_silence_ms,
                speech_pad_ms=args.speech_pad_ms,
            )
            duration_ms = len(wav) / sr * 1000.0
            end_ms = round(min(ts[-1]["end"] / sr * 1000.0, duration_ms), 1) if ts else None
            files[path.name] = {
                "speech_end_offset_ms": end_ms,
                "duration_ms": round(duration_ms, 1),
                "sha256": sha256(path),
            }

    present = {p.name for p in args.audio_dir.glob("*.wav")}
    files = {k: v for k, v in sorted(files.items()) if k in present}
    out_path.write_text(json.dumps({"params": params, "files": files}, indent=2) + "\n")

    for name, f in files.items():
        end = f["speech_end_offset_ms"]
        trailing = "n/a" if end is None else f"{(f['duration_ms'] - end) / 1000:.2f}s"
        end_s = "NO SPEECH" if end is None else f"{end / 1000:.2f}s"
        print(f"{name:<32} speech ends {end_s:>9} of {f['duration_ms'] / 1000:.2f}s (trailing {trailing})")
    print(f"{'computed' if todo else 'cached'}: {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}")


if __name__ == "__main__":
    main()
