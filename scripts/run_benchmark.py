"""Benchmark an STT provider on the clean and noisy recordings.

Usage (from ~/benchmarks):
    uv run --project benchmarks/runner scripts/run_benchmark.py
    uv run --project benchmarks/runner scripts/run_benchmark.py --concurrency 5
    uv run --project benchmarks/runner scripts/run_benchmark.py --runs 1 --only clean --only 'white_*'
    uv run --project benchmarks/runner scripts/run_benchmark.py --provider deepgram --model nova-3
    uv run --project benchmarks/runner scripts/run_benchmark.py --dry-run
    uv run --project benchmarks/runner scripts/run_benchmark.py --rescore results/<run folder>

Each stream goes through the benchmark's own per-clip code
(coval_bench.runner.orchestrator._run_stt_item, the same path `coval-bench probe`
uses), so trimming, retries, failure detection, and the TTFT / AudioToFinal /
TTFS / RTF metrics match the public benchmark. Text metrics (official WER plus
the extras in text_metrics.py) use the benchmark's compute_wer and normalization.
Nothing is written to the database.

Clips:     data/wav/*.wav (variant "clean") + every variant in data/noisy/manifest.json
Reference: transcripts/<name>.txt if it exists, else the shared transcripts/script.txt
           (WER is skipped when neither exists)
TTFS:      end-of-speech from data/wav/speech_end.json (scripts/vad.py; run automatically)
Output:    results/<timestamp>_<provider>_<model>/
--rescore: recompute text metrics and summaries of an existing results folder from its
           saved transcripts (e.g. after editing a reference), without calling the API
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import csv
import fnmatch
import hashlib
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
import time
import traceback
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
REPO = ROOT / "benchmarks"

try:
    from coval_bench.config import Settings
    from coval_bench.datasets.loader import DatasetItem
    from coval_bench.db.models import ResultStatus
    from coval_bench.logging import configure_logging
    from coval_bench.metrics.wer import NORM_VERSION
    from coval_bench.providers.stt import STT_PROVIDERS
    from coval_bench.registries import MODEL_REGISTRY, Benchmark, Metric
    from coval_bench.runner import orchestrator
except ImportError:
    sys.exit(
        "coval_bench is not importable. Run this inside the benchmark's environment:\n"
        "  uv run --project benchmarks/runner scripts/run_benchmark.py"
    )

from text_metrics import first_partial_plausible, text_metrics

TEXT_COLUMNS = [
    "wer_pct", "wer_lenient_pct", "cer_pct", "mer_pct", "wil_pct",
    "numbers_pct", "numbers_found", "numbers_total",
    "wer_sub_pct", "wer_ins_pct", "wer_del_pct",
]
RUN_COLUMNS = [
    "run", "variant", "file", "status", "error",
    "ttft_s", "ttfs_s", "audio_to_final_s", "rtf", "connect_s", "session_s", "partial_updates",
    "first_partial_ok", *TEXT_COLUMNS,
    "audio_sent_s", "speech_end_s", "duration_s", "started_at", "first_partial", "transcript",
]
INT_COLUMNS = {"run", "partial_updates", "first_partial_ok", "numbers_found", "numbers_total"}
TEXT_FIELDS = {"variant", "file", "status", "error", "started_at", "first_partial", "transcript"}
LATENCY_COLUMNS = {
    Metric.TTFT: "ttft_s",
    Metric.TTFS: "ttfs_s",
    Metric.AUDIO_TO_FINAL: "audio_to_final_s",
    Metric.RTF: "rtf",
}
SUMMARY_COLUMNS = [
    "wer_pct", "wer_lenient_pct", "cer_pct", "mer_pct", "wil_pct", "numbers_pct",
    "wer_sub_pct", "wer_ins_pct", "wer_del_pct",
    "ttft_s", "ttfs_s", "audio_to_final_s", "rtf", "connect_s", "session_s", "partial_updates",
    "first_partial_ok",
]
# Change vs clean: accuracy compares means, latency compares medians (robust to one slow stream).
DELTA_CENTER = {
    "wer_pct": "mean", "wer_lenient_pct": "mean", "cer_pct": "mean", "numbers_pct": "mean",
    "ttft_s": "median", "ttfs_s": "median",
}

# Raw STTResult of the stream running in the current task (see capture_provider_results).
_captured: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("captured", default=None)


@dataclass(frozen=True)
class Clip:
    variant: str
    path: Path
    source: str  # clean file name the variant was made from, e.g. Ian.wav
    duration_s: float


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        fmt = (w.getframerate(), w.getnchannels(), w.getsampwidth())
        if fmt != (16000, 1, 2):
            sys.exit(f"{rel(path)}: expected 16 kHz mono PCM16, got {fmt}; run scripts/convert.py")
        return w.getnframes() / w.getframerate()


def discover(data_dir: Path) -> list[Clip]:
    clips = [Clip("clean", p, p.name, wav_duration(p)) for p in sorted((data_dir / "wav").glob("*.wav"))]
    manifest_path = data_dir / "noisy" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for variant, spec in manifest["variants"].items():
            for fname in spec["files"]:
                path = data_dir / "noisy" / variant / fname
                if path.exists():
                    clips.append(Clip(variant, path, fname, wav_duration(path)))
    return clips


def resolve_references(
    sources: set[str], transcripts_dir: Path, default_reference: str
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Reference text per recording: transcripts/<name>.txt, else the shared default."""
    references: dict[str, str] = {}
    reference_files: dict[str, str | None] = {}
    shared = transcripts_dir / default_reference
    for s in sorted(sources):
        own = transcripts_dir / f"{Path(s).stem}.txt"
        ref_path = own if own.exists() else shared if shared.exists() else None
        reference_files[s] = rel(ref_path) if ref_path else None
        if ref_path:
            references[s] = ref_path.read_text().strip()
        else:
            print(f"warning: neither {rel(own)} nor {rel(shared)} exists; WER skipped for {s}")
    return references, reference_files


def load_speech_ends(wav_dir: Path, sources: set[str]) -> dict[str, float | None]:
    """End-of-speech offsets (ms) for the clean files, computing any that are missing."""
    out_path = wav_dir / "speech_end.json"

    def stale() -> list[str]:
        files = json.loads(out_path.read_text())["files"] if out_path.exists() else {}
        return [
            s for s in sorted(sources)
            if files.get(s, {}).get("sha256") != hashlib.sha256((wav_dir / s).read_bytes()).hexdigest()
        ]

    if missing := stale():
        print(f"computing end of speech (Silero VAD) for: {', '.join(missing)}", flush=True)
        cmd = ["uv", "run", "--quiet", str(SCRIPTS / "vad.py"), "--audio-dir", str(wav_dir)]
        if subprocess.run(cmd, check=False).returncode != 0 or stale():
            sys.exit("scripts/vad.py failed; fix it or pass --no-ttfs")
    files = json.loads(out_path.read_text())["files"]
    return {s: files[s]["speech_end_offset_ms"] for s in sources}


def find_entry(provider: str, model: str) -> Any:
    for entry in MODEL_REGISTRY:
        if entry.benchmark is Benchmark.STT and entry.provider == provider and entry.model == model:
            return entry
    known = sorted(f"{e.provider}/{e.model}" for e in MODEL_REGISTRY if e.benchmark is Benchmark.STT)
    sys.exit(f"{provider}/{model} is not a registered STT model. Known:\n  " + "\n  ".join(known))


def capture_provider_results(provider_cls: type) -> None:
    """Keep each stream's raw STTResult. _run_stt_item only returns metric rows, but the
    provider also records partial updates and session timing. Patched in this process only;
    retries run in the same task, so the holder ends up with the attempt that produced
    the metrics."""
    original = provider_cls.measure_ttft  # type: ignore[attr-defined]

    async def measure_ttft(self: Any, *args: Any, **kwargs: Any) -> Any:
        called = time.monotonic()
        result = await original(self, *args, **kwargs)
        holder = _captured.get()
        if holder is not None:
            holder.update(result=result, called=called)
        return result

    provider_cls.measure_ttft = measure_ttft  # type: ignore[attr-defined]


def git_commit() -> str | None:
    proc = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() or None


def fmt_num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def fmt_range(s: dict[str, Any], col: str, center: str) -> str:
    if s[f"{col}_{center}"] is None:
        return "-"
    return f"{fmt_num(s[f'{col}_{center}'])} ({fmt_num(s[f'{col}_min'])}-{fmt_num(s[f'{col}_max'])})"


def fmt_delta(s: dict[str, Any], col: str, digits: int = 2) -> str:
    """'value (+change vs clean)'; the clean row shows its value only."""
    value = fmt_num(s[f"{col}_{DELTA_CENTER[col]}"], digits)
    delta = s.get(f"{col}_delta")
    return value if delta is None else f"{value} ({delta:+.{digits}f})"


def score_row(row: dict[str, Any], reference: str) -> list[list[Any]]:
    """Fill the text-metric columns of a finished stream; return its word-error rows."""
    for col in TEXT_COLUMNS:
        row[col] = None
    row["first_partial_ok"] = None
    if not (reference and row["transcript"] and row["status"] == "ok"):
        return []
    plausible = first_partial_plausible(reference, row["first_partial"])
    row["first_partial_ok"] = None if plausible is None else int(plausible)
    metrics, errors = text_metrics(reference, row["transcript"])
    row.update(metrics)
    return [[row["run"], row["variant"], row["file"], e.type, e.reference or "", e.hypothesis or ""] for e in errors]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return dict.fromkeys(("mean", "median", "stdev", "min", "max"))
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else None,
        "min": min(values),
        "max": max(values),
    }


def summarize(rows: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    ok_rows = [r for r in rows if r["status"] == "ok"]

    def per_file(variant: str, col: str, center: str) -> dict[str, float]:
        out = {}
        for f in {r["file"] for r in ok_rows}:
            vals = [r[col] for r in ok_rows if r["variant"] == variant and r["file"] == f and r[col] is not None]
            if vals:
                out[f] = statistics.mean(vals) if center == "mean" else statistics.median(vals)
        return out

    summary = []
    for variant in order:
        sel = [r for r in rows if r["variant"] == variant]
        if not sel:
            continue
        ok = [r for r in sel if r["status"] == "ok"]
        entry: dict[str, Any] = {"variant": variant, "streams": len(sel), "ok": len(ok)}
        for col in SUMMARY_COLUMNS:
            for k, v in stats([r[col] for r in ok if r[col] is not None]).items():
                entry[f"{col}_{k}"] = v
        for col, center in DELTA_CENTER.items():
            # Paired by recording, then averaged, so a hard recording missing from one
            # variant doesn't shift that variant's change.
            if variant == "clean":
                entry[f"{col}_delta"] = None
                continue
            base, here = per_file("clean", col, center), per_file(variant, col, center)
            diffs = [here[f] - base[f] for f in here if f in base]
            entry[f"{col}_delta"] = statistics.mean(diffs) if diffs else None
        summary.append(entry)
    return summary


def write_summary(out_dir: Path, meta: dict[str, Any], summary: list[dict[str, Any]]) -> str:
    if summary:
        with (out_dir / "summary.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)

    lines = [
        f"# {meta['provider']}/{meta['model']}: clean vs noisy",
        "",
        f"- Started: {meta['started_at']}, finished: {meta.get('finished_at', 'interrupted')}"
        + (f", rescored: {meta['rescored_at']}" if meta.get("rescored_at") else ""),
        f"- Runs per clip: {meta['runs']}, concurrency: {meta['concurrency']}, files: {', '.join(meta['files'])}",
        f"- Benchmark repo commit: {meta['repo_commit']}, WER normalization v{meta['wer_norm_version']}",
        "- Values in brackets are the change vs clean.",
        "",
        "## Accuracy (mean over streams)",
        "",
        "| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['variant']} | {s['ok']}/{s['streams']} "
            f"| {fmt_delta(s, 'wer_pct')} | {fmt_delta(s, 'wer_lenient_pct')} | {fmt_delta(s, 'cer_pct')} "
            f"| {fmt_delta(s, 'numbers_pct', 1)} "
            f"| {fmt_num(s['wer_sub_pct_mean'], 1)} / {fmt_num(s['wer_ins_pct_mean'], 1)} / {fmt_num(s['wer_del_pct_mean'], 1)} "
            f"| {fmt_num(s['mer_pct_mean'])} | {fmt_num(s['wil_pct_mean'])} |"
        )
    lines += [
        "",
        "## Latency (median over streams)",
        "",
        "| Variant | TTFT s | TTFT range | First partial plausible % | TTFS s | TTFS range | Audio→final s | RTF "
        "| Connect s | Partial updates |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['variant']} | {fmt_delta(s, 'ttft_s')} "
            f"| {fmt_num(s['ttft_s_min'])}-{fmt_num(s['ttft_s_max'])} "
            f"| {fmt_num(None if s['first_partial_ok_mean'] is None else s['first_partial_ok_mean'] * 100, 0)} "
            f"| {fmt_delta(s, 'ttfs_s')} | {fmt_num(s['ttfs_s_min'])}-{fmt_num(s['ttfs_s_max'])} "
            f"| {fmt_num(s['audio_to_final_s_median'])} | {fmt_num(s['rtf_median'], 3)} "
            f"| {fmt_num(s['connect_s_median'])} | {fmt_num(s['partial_updates_median'], 0)} |"
        )
    lines += [
        "",
        "**Accuracy** (vs the reference transcript; lower is better except Numbers):",
        "- **WER**: the benchmark's official word error rate.",
        "- **Lenient WER**: WER that ignores number formatting (079-33-415-028 = \"oh seven nine double "
        "three...\") and spelling variants (all right = alright). Closer to real recognition mistakes.",
        "- **CER**: character error rate; partly wrong words count partly.",
        "- **Numbers correct**: share of the reference's numbers (phone, dates, times, prices) found exactly "
        "in the transcript.",
        "- **MER / WIL**: match error rate and word information lost, alternative WER-style rates.",
        "",
        "**Latency**:",
        "- **TTFT**: first audio sent → first partial transcript.",
        "- **First partial plausible**: share of streams whose first partial shares a word with the reference. "
        "Below 100% means TTFT sometimes timed a wrong-language guess (e.g. \"Алло!\"), not real text.",
        "- **TTFS**: end of speech (Silero VAD on the clean file) → final transcript. Audio after end of "
        "speech is trimmed before streaming, as in the benchmark.",
        "- **Audio→final**: first audio sent → final transcript. **RTF**: audio→final / audio length.",
        "- **Connect**: opening the connection (handshake, auth) until the first audio is sent.",
        "- **Partial updates**: interim transcripts received per stream; more means the text updates more often.",
        "",
        "Per-stream rows: `runs.csv`; word-level errors: `wer_errors.csv`; transcripts: `transcripts/`.",
    ]
    text = "\n".join(lines) + "\n"
    (out_dir / "summary.md").write_text(text)
    return text


# ---------------------------------------------------------------------------
# Rescore
# ---------------------------------------------------------------------------


def parse_value(col: str, raw: str) -> Any:
    if col in TEXT_FIELDS:
        return raw or None
    if raw == "":
        return None
    return int(float(raw)) if col in INT_COLUMNS else float(raw)


def rescore(out_dir: Path, transcripts_dir: Path, default_reference: str) -> None:
    meta_path = out_dir / "meta.json"
    if not (meta_path.exists() and (out_dir / "runs.csv").exists()):
        sys.exit(f"{rel(out_dir)} is not a results folder (needs meta.json and runs.csv)")
    meta = json.loads(meta_path.read_text())
    with (out_dir / "runs.csv").open(newline="") as f:
        rows = [{col: parse_value(col, r.get(col) or "") for col in RUN_COLUMNS} for r in csv.DictReader(f)]

    references, meta["reference_files"] = resolve_references(
        {r["file"] for r in rows}, transcripts_dir, default_reference
    )
    errors = [e for r in rows for e in score_row(r, references.get(r["file"], ""))]
    with (out_dir / "runs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with (out_dir / "wer_errors.csv").open("w", newline="") as f:
        writer2 = csv.writer(f)
        writer2.writerow(["run", "variant", "file", "type", "reference", "hypothesis"])
        writer2.writerows(errors)

    meta["rescored_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(write_summary(out_dir, meta, summarize(rows, meta["variants"])))
    print(f"rescored {len(rows)} stream(s) in {rel(out_dir)}/")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def run_all(
    *,
    jobs: list[tuple[int, Clip]],
    entry: Any,
    settings: Settings,
    references: dict[str, str],
    speech_ends: dict[str, float | None],
    concurrency: int,
    out_dir: Path,
    rows: list[dict[str, Any]],
) -> None:
    sem = asyncio.Semaphore(concurrency)
    unlimited = asyncio.Semaphore(len(jobs))
    runs_file = (out_dir / "runs.csv").open("w", newline="")
    errors_file = (out_dir / "wer_errors.csv").open("w", newline="")
    runs_csv = csv.DictWriter(runs_file, fieldnames=RUN_COLUMNS)
    errors_csv = csv.writer(errors_file)
    runs_csv.writeheader()
    errors_csv.writerow(["run", "variant", "file", "type", "reference", "hypothesis"])
    done = 0

    async def one(run: int, clip: Clip) -> None:
        nonlocal done
        reference = references.get(clip.source, "")
        speech_end_ms = speech_ends.get(clip.source)
        row: dict[str, Any] = dict.fromkeys(RUN_COLUMNS)
        row.update(
            run=run, variant=clip.variant, file=clip.source,
            duration_s=round(clip.duration_s, 3),
            speech_end_s=None if speech_end_ms is None else speech_end_ms / 1000,
            audio_sent_s=round(min(clip.duration_s, (speech_end_ms or math.inf) / 1000), 3),
        )
        holder: dict[str, Any] = {}
        _captured.set(holder)  # each gathered coroutine is its own task, so this is per stream
        # Limit concurrency here rather than via _run_stt_item's own semaphore, so
        # started_at is when the stream actually began, not when it was queued.
        async with sem:
            row["started_at"] = datetime.now(UTC).isoformat(timespec="milliseconds")
            try:
                item = DatasetItem(
                    path=clip.path,
                    transcript=reference,
                    duration_sec=clip.duration_s,
                    sha256=hashlib.sha256(clip.path.read_bytes()).hexdigest(),
                    speech_end_offset_ms=speech_end_ms,
                )
                results = await orchestrator._run_stt_item(
                    entry=entry, item=item, run_id=0, sem=unlimited, settings=settings, writer=None
                )
            except Exception as exc:  # noqa: BLE001 - record and keep going
                results = []
                row["error"] = f"{type(exc).__name__}: {exc}"

        for r in results:
            col = LATENCY_COLUMNS.get(Metric(r.metric_type))
            if col and r.status == ResultStatus.SUCCESS:
                row[col] = r.metric_value
            if r.status != ResultStatus.SUCCESS and not row["error"]:
                row["error"] = r.error or f"{r.metric_type} failed"
            row["transcript"] = row["transcript"] or r.transcript
        row["status"] = "ok" if results and not row["error"] else "failed"

        raw = holder.get("result")
        if raw is not None:
            row["partial_updates"] = len(raw.partial_transcripts)
            row["first_partial"] = raw.first_token_content
            row["session_s"] = raw.total_time
            if raw.audio_start_time is not None:
                row["connect_s"] = raw.audio_start_time - holder["called"]

        errors_csv.writerows(score_row(row, reference))
        if row["transcript"]:
            tdir = out_dir / "transcripts" / clip.variant
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / f"{Path(clip.source).stem}.run{run}.txt").write_text(row["transcript"] + "\n")

        rows.append(row)
        runs_csv.writerow(row)
        runs_file.flush()
        errors_file.flush()
        done += 1
        if row["status"] == "ok" and row["wer_pct"] is None:
            detail = f"no reference  TTFT {fmt_num(row['ttft_s'])}s  TTFS {fmt_num(row['ttfs_s'])}s"
        elif row["status"] == "ok":
            detail = (
                f"WER {fmt_num(row['wer_pct'], 1)}% (lenient {fmt_num(row['wer_lenient_pct'], 1)}%)  "
                f"numbers {row['numbers_found']}/{row['numbers_total']}  "
                f"TTFT {fmt_num(row['ttft_s'])}s  TTFS {fmt_num(row['ttfs_s'])}s"
            )
        else:
            detail = f"FAILED: {row['error']}"
        print(f"[{done}/{len(jobs)}] run {run}  {clip.variant:<20} {clip.source}  {detail}", flush=True)

    try:
        # Created in order and the semaphore is FIFO, so streams start in job order.
        await asyncio.gather(*(one(run, clip) for run, clip in jobs))
    finally:
        runs_file.close()
        errors_file.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="elevenlabs")
    parser.add_argument("--model", default="scribe_v2_realtime")
    parser.add_argument("--runs", type=int, default=3, help="streams per clip (default 3)")
    parser.add_argument("--only", action="append", default=[], metavar="PATTERN",
                        help="variant name or glob, repeatable: --only clean --only 'white_*'")
    parser.add_argument("--files", action="append", default=[], metavar="PATTERN",
                        help="recording name or glob, repeatable (default: all)")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="parallel streams (default 1); keep below the provider's realtime limit")
    parser.add_argument("--no-ttfs", action="store_true",
                        help="skip VAD: no TTFS, and stream the whole file without trimming")
    parser.add_argument("--label", default="", help="suffix for the results folder name")
    parser.add_argument("--dry-run", action="store_true", help="show what would run, then exit")
    parser.add_argument("--rescore", type=Path, metavar="RESULTS_DIR",
                        help="recompute text metrics + summary for an existing results folder; no API calls")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--transcripts-dir", type=Path, default=ROOT / "transcripts")
    parser.add_argument("--default-reference", default="script.txt",
                        help="transcript used by recordings without their own <name>.txt (default script.txt)")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    if args.rescore:
        rescore(args.rescore, args.transcripts_dir, args.default_reference)
        return

    configure_logging(args.log_level)
    entry = find_entry(args.provider, args.model)
    settings = Settings(_env_file=str(args.env_file))  # type: ignore[call-arg]
    key_attr = f"{args.provider}_api_key"
    if hasattr(settings, key_attr) and not getattr(settings, key_attr):
        sys.exit(f"{key_attr.upper()} is not set in {rel(args.env_file)}")

    clips = discover(args.data_dir)
    if not clips:
        sys.exit(f"no clips in {rel(args.data_dir / 'wav')}; run scripts/convert.py first")
    if args.only:
        clips = [c for c in clips if any(fnmatch.fnmatch(c.variant, p) for p in args.only)]
    if args.files:
        clips = [c for c in clips if any(fnmatch.fnmatch(c.source, p) or fnmatch.fnmatch(Path(c.source).stem, p)
                                         for p in args.files)]
    if not clips:
        sys.exit("no clips match --only / --files")

    sources = {c.source for c in clips}
    references, reference_files = resolve_references(sources, args.transcripts_dir, args.default_reference)

    variant_order = list(dict.fromkeys(c.variant for c in clips))
    # Round-robin: every variant is streamed once per run before the next run starts, so
    # network drift over a long session spreads evenly instead of biasing one variant.
    jobs = [(run, clip) for run in range(1, args.runs + 1) for clip in clips]

    if args.dry_run:
        for v in variant_order:
            files = [c.source for c in clips if c.variant == v]
            print(f"{v:<24} {', '.join(files)}")
        print()
        for src, ref in reference_files.items():
            print(f"{src:<24} reference: {ref or 'none (WER skipped)'}")
        audio = sum(c.duration_s for c in clips) * args.runs
        print(f"\n{len(variant_order)} variant(s) x {len(sources)} file(s) x {args.runs} run(s) "
              f"= {len(jobs)} streams, about {audio / 60 / args.concurrency:.0f} min of real-time streaming "
              f"plus per-stream connect/close time (~16 s each for ElevenLabs)")
        return

    speech_ends: dict[str, float | None] = {}
    if not args.no_ttfs:
        speech_ends = load_speech_ends(args.data_dir / "wav", sources)
    # The benchmark caps a stream at 45 s (its clips are 2-15 s). Allow for long recordings.
    longest = max(c.duration_s for c in clips)
    orchestrator._STT_TIMEOUT_S = max(orchestrator._STT_TIMEOUT_S, math.ceil(longest) + 60)
    capture_provider_results(STT_PROVIDERS[args.provider])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{args.provider}_{args.model}" + (f"_{args.label}" if args.label else "")
    out_dir = args.results_dir / name
    out_dir.mkdir(parents=True)
    noise_manifest = args.data_dir / "noisy" / "manifest.json"
    if noise_manifest.exists() and any(c.variant != "clean" for c in clips):
        shutil.copy(noise_manifest, out_dir / "noise_manifest.json")

    meta: dict[str, Any] = {
        "provider": args.provider,
        "model": args.model,
        "runs": args.runs,
        "concurrency": args.concurrency,
        "variants": variant_order,
        "files": sorted(sources),
        "reference_files": reference_files,
        "speech_end_offset_ms": speech_ends or None,
        "trimmed_after_speech_end": not args.no_ttfs,
        "stt_timeout_s": orchestrator._STT_TIMEOUT_S,
        "wer_norm_version": NORM_VERSION,
        "repo_commit": git_commit(),
        "command": " ".join(sys.argv),
        "python": platform.python_version(),
        "host": platform.node(),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    total_audio = sum(min(c.duration_s, (speech_ends.get(c.source) or math.inf) / 1000) for c in clips)
    print(f"{args.provider}/{args.model}: {len(jobs)} streams "
          f"({len(variant_order)} variant(s) x {len(sources)} file(s) x {args.runs} run(s)), "
          f"~{total_audio * args.runs / 60 / args.concurrency:.1f} min of audio plus per-stream connect/close "
          f"time (~16 s for ElevenLabs). Results: {rel(out_dir)}/", flush=True)

    async def go(rows: list[dict[str, Any]]) -> None:
        try:
            await STT_PROVIDERS[args.provider].warmup(settings=settings)
        except Exception as exc:  # noqa: BLE001 - the benchmark also ignores warmup failures
            print(f"warning: provider warmup failed: {exc}")
        await run_all(
            jobs=jobs, entry=entry, settings=settings, references=references,
            speech_ends=speech_ends, concurrency=args.concurrency, out_dir=out_dir, rows=rows,
        )

    rows: list[dict[str, Any]] = []
    t0 = time.monotonic()
    interrupted = False
    try:
        asyncio.run(go(rows))
        meta["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    except KeyboardInterrupt:
        interrupted = True
    except Exception:  # noqa: BLE001 - still write a summary of the streams that finished
        traceback.print_exc()
        interrupted = True
    meta["wall_clock_s"] = round(time.monotonic() - t0, 1)
    meta["streams_completed"] = len(rows)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    text = write_summary(out_dir, meta, summarize(rows, variant_order))
    print("\n" + text)
    print(f"{'interrupted; partial ' if interrupted else ''}results saved to {rel(out_dir)}/")
    failed = sum(r["status"] != "ok" for r in rows)
    sys.exit(1 if interrupted or failed else 0)


if __name__ == "__main__":
    main()
