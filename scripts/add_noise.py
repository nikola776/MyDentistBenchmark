# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=1.26", "scipy>=1.11", "soundfile>=0.12", "pyyaml>=6"]
# ///
"""Create degraded copies of the clean recordings, as configured in noise.yaml.

Usage:
    uv run scripts/add_noise.py                    # every condition in noise.yaml
    uv run scripts/add_noise.py --only 'white_*'   # just some variants
    uv run scripts/add_noise.py --list             # show variants, write nothing
    uv run scripts/add_noise.py --config my.yaml

Reads 16 kHz mono WAVs from input_dir (run convert.py first) and writes
<output_dir>/<variant>/<name>.wav plus <output_dir>/manifest.json, which
records every parameter, the noise file and offset used, and any gain applied.
Speech timing is never shifted, so the clean file's end-of-speech point holds
for every variant.
"""

from __future__ import annotations

import argparse
import fnmatch
import itertools
import json
import sys
import zlib
from datetime import UTC, datetime
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import yaml
from scipy.signal import butter, fftconvolve, resample_poly, sosfiltfilt

SR = 16000
SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
PEAK_LIMIT = 0.99
NOISE_EXTS = {".wav", ".flac", ".ogg"}

# Parameters that expand when given as a list, and their short name in variant names.
EXPANDABLE = {"snr_db": "snr", "rt60": "rt", "drr_db": "drr"}
STEP_KEYS = {
    "synthetic": {"color", "snr_db"},
    "background": {"noise", "snr_db"},
    "phone": {"codec", "band_hz"},
    "reverb": {"rt60", "drr_db"},
}
REQUIRED_KEYS = {
    "synthetic": {"color", "snr_db"},
    "background": {"noise", "snr_db"},
    "phone": set(),
    "reverb": {"rt60"},
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def fmt(value: Any) -> str:
    f = float(value)
    return str(int(f)) if f.is_integer() else str(f)


def validate_step(cond: str, step: Any) -> None:
    if not isinstance(step, dict) or "type" not in step:
        sys.exit(f"{cond}: each step needs a 'type' ({', '.join(STEP_KEYS)})")
    kind = step["type"]
    if kind not in STEP_KEYS:
        sys.exit(f"{cond}: unknown step type {kind!r} (expected one of {', '.join(STEP_KEYS)})")
    keys = set(step) - {"type"}
    if unknown := keys - STEP_KEYS[kind]:
        sys.exit(f"{cond}: unknown parameter(s) for {kind}: {', '.join(sorted(unknown))}")
    if missing := REQUIRED_KEYS[kind] - keys:
        sys.exit(f"{cond}: {kind} step is missing: {', '.join(sorted(missing))}")
    if kind == "synthetic" and step["color"] not in ("white", "pink", "brown"):
        sys.exit(f"{cond}: color must be white, pink or brown")
    if kind == "phone" and step.get("codec", "mulaw") not in ("mulaw", "alaw", "none"):
        sys.exit(f"{cond}: codec must be mulaw, alaw or none")


def expand(cond: str, steps: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Expand list-valued parameters into one (variant name, concrete steps) per combination."""
    slots = [
        (i, key)
        for i, step in enumerate(steps)
        for key in EXPANDABLE
        if isinstance(step.get(key), list)
    ]
    if not slots:
        return [(cond, steps)]
    variants = []
    for combo in itertools.product(*(steps[i][key] for i, key in slots)):
        concrete = [dict(s) for s in steps]
        suffix = []
        for (i, key), value in zip(slots, combo, strict=True):
            concrete[i][key] = value
            suffix.append(f"{EXPANDABLE[key]}{fmt(value)}")
        variants.append((f"{cond}_{'_'.join(suffix)}", concrete))
    return variants


def load_config(path: Path) -> tuple[dict[str, Any], list[tuple[str, list[dict[str, Any]]]]]:
    cfg = yaml.safe_load(path.read_text())
    base = path.resolve().parent
    for key in ("input_dir", "output_dir", "noise_dir"):
        cfg[key] = (base / cfg[key]).resolve()
    cfg.setdefault("seed", 0)
    conditions = cfg.get("conditions") or {}
    if not conditions:
        sys.exit(f"{path}: no conditions defined")

    variants: list[tuple[str, list[dict[str, Any]]]] = []
    for cond, steps in conditions.items():
        if cond == "clean":
            sys.exit("'clean' is reserved for the unmodified recordings")
        if not isinstance(steps, list) or not steps:
            sys.exit(f"{cond}: expected a list of steps")
        for step in steps:
            validate_step(cond, step)
        variants.extend(expand(cond, steps))

    names = [name for name, _ in variants]
    if dupes := {n for n in names if names.count(n) > 1}:
        sys.exit(f"duplicate variant names: {', '.join(sorted(dupes))}")
    return cfg, variants


# ---------------------------------------------------------------------------
# DSP
# ---------------------------------------------------------------------------


def active_power(x: np.ndarray) -> float:
    """Mean power over active-speech frames: 30 ms frames within 30 dB of the loud
    (95th-percentile) frames. Keeps pauses from making the SNR look better than it sounds."""
    frame = int(0.03 * SR)
    n = len(x) // frame
    if n == 0:
        return float(np.mean(x**2))
    energy = (x[: n * frame].reshape(n, frame) ** 2).mean(axis=1)
    loud = np.percentile(energy, 95)
    if loud <= 0:
        return 0.0
    return float(energy[energy >= loud * 10 ** (-30 / 10)].mean())


def mix_at_snr(x: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    ps, pn = active_power(x), float(np.mean(noise**2))
    if ps == 0 or pn == 0:
        return x
    return x + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))


def colored_noise(n: int, color: str, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(n)
    if color == "white":
        return white
    exponent = {"pink": 1.0, "brown": 2.0}[color]  # power spectrum ~ 1/f^exponent
    spec = np.fft.rfft(white)
    freqs = np.maximum(np.fft.rfftfreq(n, 1 / SR), 20.0)  # floor at 20 Hz: no DC drift
    shaped = np.fft.irfft(spec / freqs ** (exponent / 2), n)
    return shaped / shaped.std()


def read_mono(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    x = data.mean(axis=1)
    if sr != SR:
        g = gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g)
    return x


def loop_to_length(noise: np.ndarray, n: int) -> np.ndarray:
    """Repeat a short noise clip with 20 ms crossfades so the loop point doesn't click."""
    out = noise.copy()
    while len(out) < n:
        k = min(int(0.02 * SR), len(noise) // 2, len(out) // 2)
        ramp = np.linspace(0.0, 1.0, k)
        out = np.concatenate([out[:-k], out[-k:] * (1 - ramp) + noise[:k] * ramp, noise[k:]])
    return out[:n]


def background_segment(
    spec: str, noise_dir: Path, n: int, rng: np.random.Generator, cache: dict[Path, np.ndarray]
) -> tuple[np.ndarray, Path, float]:
    pattern = spec if any(c in spec for c in "*?[") or Path(spec).suffix else f"{spec}.*"
    matches = sorted(p for p in noise_dir.glob(pattern) if p.suffix.lower() in NOISE_EXTS)
    if not matches:
        sys.exit(
            f"no noise file matches {spec!r} in {noise_dir}. "
            "Run scripts/fetch_noise.py or add your own wav/flac clips there."
        )
    path = matches[int(rng.integers(len(matches)))]
    if path not in cache:
        cache[path] = read_mono(path)
    noise = cache[path]
    if len(noise) >= n:
        start = int(rng.integers(0, len(noise) - n + 1))
        return noise[start : start + n], path, start / SR
    return loop_to_length(noise, n), path, 0.0


def g711_roundtrip(x: np.ndarray, codec: str) -> np.ndarray:
    """Encode to 8-bit G.711 (mu-law or A-law) and decode back."""
    x = np.clip(x, -1.0, 1.0)
    sign, mag = np.sign(x), np.abs(x)
    if codec == "mulaw":
        mu = 255.0
        y = np.log1p(mu * mag) / np.log1p(mu)
    else:  # alaw
        a = 87.6
        y = np.where(mag < 1 / a, a * mag / (1 + np.log(a)), (1 + np.log(np.maximum(a * mag, 1e-12))) / (1 + np.log(a)))
    y = np.round(y * 127) / 127  # 7 magnitude bits + sign = 8 bits per sample
    if codec == "mulaw":
        mag = ((1 + mu) ** y - 1) / mu
    else:
        cut = 1 / (1 + np.log(a))
        mag = np.where(y < cut, y * (1 + np.log(a)) / a, np.exp(y * (1 + np.log(a)) - 1) / a)
    return sign * mag


def phone(x: np.ndarray, codec: str, band_hz: list[float]) -> np.ndarray:
    sos = butter(4, band_hz, btype="bandpass", fs=SR, output="sos")
    narrow = resample_poly(sosfiltfilt(sos, x), 1, 2)  # zero-phase filter: no time shift
    if codec != "none":
        narrow = g711_roundtrip(narrow, codec)
    out = resample_poly(narrow, 2, 1)
    return np.pad(out, (0, max(0, len(x) - len(out))))[: len(x)]


def reverb(x: np.ndarray, rt60: float, drr_db: float, rng: np.random.Generator) -> np.ndarray:
    """Convolve with a synthetic room response: direct path at t=0 (so speech timing is
    unchanged) plus an exponentially decaying diffuse tail."""
    n = int(SR * max(1.5 * rt60, 0.05))
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * np.exp(-np.log(1000) * t / rt60)  # -60 dB at t = rt60
    tail[: int(0.0025 * SR)] = 0.0  # first reflections arrive ~2.5 ms after the direct sound
    tail *= np.sqrt(10 ** (-drr_db / 10) / np.sum(tail**2))
    tail[0] = 1.0
    y = fftconvolve(x, tail)[: len(x)]
    # Keep speech loudness unchanged so only the room character differs.
    return y * np.sqrt(active_power(x) / max(active_power(y), 1e-20))


def apply_steps(
    x: np.ndarray,
    steps: list[dict[str, Any]],
    rng: np.random.Generator,
    noise_dir: Path,
    cache: dict[Path, np.ndarray],
) -> tuple[np.ndarray, dict[str, Any]]:
    info: dict[str, Any] = {}
    y = x
    for step in steps:
        kind = step["type"]
        if kind == "synthetic":
            y = mix_at_snr(y, colored_noise(len(y), step["color"], rng), float(step["snr_db"]))
        elif kind == "background":
            seg, path, offset = background_segment(step["noise"], noise_dir, len(y), rng, cache)
            y = mix_at_snr(y, seg, float(step["snr_db"]))
            info["noise_file"] = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
            info["noise_offset_s"] = round(offset, 3)
        elif kind == "phone":
            y = phone(y, step.get("codec", "mulaw"), list(step.get("band_hz", [300, 3400])))
        elif kind == "reverb":
            y = reverb(y, float(step["rt60"]), float(step.get("drr_db", 3.0)), rng)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > PEAK_LIMIT:
        y = y * (PEAK_LIMIT / peak)
        info["gain_db"] = round(20 * np.log10(PEAK_LIMIT / peak), 2)  # scaled down to avoid clipping
    return y, info


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=SCRIPTS / "noise.yaml")
    parser.add_argument("--only", action="append", default=[], metavar="PATTERN",
                        help="variant name or glob, repeatable (e.g. 'white_*')")
    parser.add_argument("--list", action="store_true", help="print the variants and exit")
    args = parser.parse_args()

    cfg, variants = load_config(args.config)
    if args.only:
        variants = [v for v in variants if any(fnmatch.fnmatch(v[0], p) for p in args.only)]
        if not variants:
            sys.exit(f"no variant matches {args.only}")
    if args.list:
        for name, steps in variants:
            print(f"{name:<24} {json.dumps(steps)}")
        print(f"\n{len(variants)} variant(s)")
        return

    inputs = sorted(cfg["input_dir"].glob("*.wav"))
    if not inputs:
        sys.exit(f"no WAVs in {cfg['input_dir']}; run scripts/convert.py first")
    clean: dict[str, np.ndarray] = {}
    for path in inputs:
        info = sf.info(str(path))
        if (info.samplerate, info.channels) != (SR, 1):
            sys.exit(f"{path.name}: expected 16 kHz mono, got {info.samplerate} Hz x{info.channels}; run convert.py")
        clean[path.name] = sf.read(str(path), dtype="float64")[0]

    out_dir: Path = cfg["output_dir"]
    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, Any] = {"variants": {}}
    if args.only and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())  # partial run: keep the other variants
    manifest.update(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        config=rel(args.config.resolve()),
        seed=cfg["seed"],
        sample_rate=SR,
        input_dir=rel(cfg["input_dir"]),
    )

    cache: dict[Path, np.ndarray] = {}
    for name, steps in variants:
        vdir = out_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        files: dict[str, Any] = {}
        for fname, x in clean.items():
            # Seeded per (variant, file): reproducible and independent of processing order.
            rng = np.random.default_rng([int(cfg["seed"]), zlib.crc32(name.encode()), zlib.crc32(fname.encode())])
            y, info = apply_steps(x, steps, rng, cfg["noise_dir"], cache)
            sf.write(str(vdir / fname), y, SR, subtype="PCM_16")
            files[fname] = {"source": rel(cfg["input_dir"] / fname), **info}
        manifest["variants"][name] = {"steps": steps, "files": files}
        print(f"wrote    {rel(vdir)}/ ({len(files)} file(s))")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest {rel(manifest_path)} ({len(manifest['variants'])} variant(s))")

    stale = sorted(
        d.name for d in out_dir.iterdir() if d.is_dir() and d.name not in manifest["variants"]
    )
    if stale:
        print(f"note: folders not in the manifest (not benchmarked, safe to delete): {', '.join(stale)}")


if __name__ == "__main__":
    main()
