# Noise-robustness benchmark scripts

Measure how an STT provider's accuracy and latency hold up as recordings get
noisier. These scripts use the benchmark repo's own provider and metric code,
so the numbers follow the public benchmark's method.

## Setup

Prerequisites: `git` and [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv fetches Python 3.12 and every dependency itself; no ffmpeg or system packages
are needed. Expect about 1.5 GB of downloads on first use (mostly CPU-only
PyTorch for the speech detector, plus ~200 MB of noise recordings), kept in uv's
cache and `noise/`. Tested on Linux; macOS should work but hasn't been tried.

```bash
git clone --recurse-submodules <this repo> && cd <repo>
cd benchmarks/runner && uv sync && cd ../..        # benchmark code (pinned submodule)
cp benchmarks/.env.example benchmarks/.env          # add provider API keys
```

Recordings, noise clips and generated audio aren't in git. Put recordings in
`data/` and run the workflow below. `results/` holds our committed runs; to
reproduce them exactly you need the original recordings, shared separately.
The noise and end-of-speech steps are deterministic, so the same recording
gives byte-identical noisy files on any machine.

## Folder layout

```
benchmarks/        coval benchmarks repo, as a git submodule (provides .env with API keys)
data/              your original recordings (any format: m4a, mp3, wav, ...)
  wav/             16 kHz mono WAVs                  <- convert.py
  wav/speech_end.json  end-of-speech per recording   <- vad.py
  noisy/<variant>/ degraded copies + manifest.json   <- add_noise.py
noise/             background-noise clips            <- fetch_noise.py (or your own)
transcripts/       reference text: script.txt (shared) or <recording>.txt
results/           one folder per benchmark run      <- run_benchmark.py
scripts/           these scripts + noise.yaml
```

## Workflow

Run everything from `~/benchmarks`:

```bash
# 1. Convert recordings in data/ to 16 kHz mono WAV (skips files already done)
uv run scripts/convert.py

# 2. Get real background noise (once). See `--list` for all 18 environments.
uv run scripts/fetch_noise.py                # cafeteria + street

# 3. Make the noisy variants defined in scripts/noise.yaml
uv run scripts/add_noise.py --list           # preview
uv run scripts/add_noise.py

# 4. Benchmark (end-of-speech detection runs automatically the first time)
uv run --project benchmarks/runner scripts/run_benchmark.py --dry-run
uv run --project benchmarks/runner scripts/run_benchmark.py
```

To add a recording, put it in `data/` and rerun steps 1, 3 and 4. Recordings of
the shared script are scored against `transcripts/script.txt`. A recording with
different text needs its own `transcripts/<same name>.txt`, which takes priority.

If one recording holds several texts (e.g. the script, then the scenarios), split
it first. Audio between parts, like a spoken heading, is dropped, and each cut
moves to the nearest pause:

```bash
uv run scripts/split.py data/Richard.m4a script=0-2:17 scenarios=2:21-end
```

This writes `data/Richard_script.wav` and `data/Richard_scenarios.wav` and moves
the original to `data/unsplit/`. A part `<recording>_<part>` is scored against
`transcripts/<recording>_<part>.txt` if it exists, else the shared
`transcripts/<part>.txt` (here `script.txt` and `scenarios.txt`).

## Benchmark options

| Option | Default | |
|---|---|---|
| `--provider`, `--model` | `elevenlabs`, `scribe_v2_realtime` | any registered STT model; its key must be in `benchmarks/.env` |
| `--runs N` | 3 | streams per clip, to get a latency spread |
| `--only PATTERN` | all | variants to run, repeatable: `--only clean --only 'cafeteria_*'` |
| `--files PATTERN` | all | recordings to run, e.g. `--files Ian` |
| `--default-reference` | `script.txt` | transcript for recordings without their own `<name>.txt` |
| `--concurrency N` | 1 | parallel streams. Stay at least 1 below the provider's realtime limit (ElevenLabs free: 6, so use 5); over the limit, streams are queued or rejected |
| `--no-ttfs` | off | skip VAD: no TTFS, and stream whole files untrimmed |
| `--label NAME` | | added to the results folder name |
| `--dry-run` | | list the streams and estimated time without calling the API |
| `--rescore DIR` | | recompute text metrics and summaries of an existing results folder from its saved transcripts (e.g. after fixing a reference). No API calls |

Streaming is real time: each stream takes as long as the recording, plus about
16 s while ElevenLabs closes the idle session after the final transcript. The
default config (clean + 16 variants, 3 runs, one 94 s recording) takes about
95 minutes, or about 20 minutes with `--concurrency 5`. Ctrl-C stops early and
still writes a summary of the finished streams. Parallelism doesn't change cost:
ElevenLabs bills per second of audio (about 1.3 credits/s on the free tier, so a
full default run costs about 6,200 credits).

## Noise configuration (`noise.yaml`)

Each condition is a list of steps applied in order. A list-valued parameter
expands into one variant per value: `snr_db: [20, 10, 5, 0]` gives
`white_snr20` ... `white_snr0`.

| Step | Parameters |
|---|---|
| `synthetic` | `color`: white / pink / brown; `snr_db` |
| `background` | `noise`: file name in `noise/` (or a glob); `snr_db` |
| `phone` | `codec`: mulaw / alaw / none (G.711, 8 kHz); `band_hz`: [300, 3400] |
| `reverb` | `rt60`: decay time in s (0.3 small room, 1.2 hall); `drr_db`: lower = farther (default 3) |
| `dropout` | `loss_pct`: share of audio lost in bursts, like a weak mobile signal (5 noticeable, 15 severe); `burst_ms`: average gap (default 60) |

Steps can be chained, e.g. cafeteria noise followed by a phone line. The
`seed` makes output reproducible: same config and input give byte-identical files.

## Results (`results/<timestamp>_<provider>_<model>/`)

| File | Contents |
|---|---|
| `summary.md` | per-variant accuracy and latency tables, with the change vs clean |
| `summary.csv` | mean/median/stdev/min/max of every metric, plus the change vs clean |
| `runs.csv` | one row per stream, written as each stream finishes |
| `wer_errors.csv` | every word error: type, reference word, recognized word |
| `transcripts/<variant>/` | what the provider returned, per run |
| `meta.json`, `noise_manifest.json` | settings, repo commit, VAD offsets, exact noise parameters |

## Metrics

All are free: they come from the stream itself or from the saved transcript.

| Metric | Column | Meaning |
|---|---|---|
| WER | `wer_pct` | the benchmark's official word error rate (+ `wer_sub/ins/del_pct` split) |
| Lenient WER | `wer_lenient_pct` | WER ignoring number formatting and spelling variants (see below) |
| CER | `cer_pct` | character error rate; partly wrong words count partly |
| Numbers correct | `numbers_pct` | share of the reference's numbers (phone, NHS, dates, times, prices) found exactly in the transcript |
| MER, WIL | `mer_pct`, `wil_pct` | alternative WER-style rates (jiwer definitions), for comparison with other tools |
| TTFT | `ttft_s` | first audio sent → first partial transcript |
| First partial plausible | `first_partial_ok` | first partial shares a word with the reference (1/0); see below |
| TTFS | `ttfs_s` | end of speech → final transcript (the benchmark's headline latency) |
| Audio→final, RTF | `audio_to_final_s`, `rtf` | first audio → final transcript; and that divided by audio length |
| Connect | `connect_s` | opening the connection (handshake, auth, session start) until the first audio is sent |
| Partial updates | `partial_updates` | interim transcripts received; more means the text updates more often |
| Session | `session_s` | whole session including close; mostly ElevenLabs' idle close (~16 s), not a latency |

The change vs clean compares each variant with the clean recording of the same
file: means for accuracy, medians for latency.

## Method notes

- **Metrics** come from the benchmark's `_run_stt_item` (the path `coval-bench probe`
  uses): same retries, failure detection, WER normalization, and trimming of audio
  after end of speech. Nothing is written to the database.
- **TTFS** = audio→final minus end of speech. End of speech comes from Silero VAD
  on the *clean* recording (same settings as the benchmark's
  `precompute_vad_offsets.py`), and that point is reused for every noisy variant.
  Noise doesn't change when the speaker stops, and VAD on noisy audio would move it.
- **Timeout**: the benchmark allows 45 s per stream because its clips are 2-15 s long.
  Here the limit is the longest recording plus 60 s.
- **SNR** is measured against active speech (pauses excluded), so 0 dB means
  noise as loud as the talking parts.
- **WER and numbers**: the normalizer turns spoken digits ("oh seven nine") into
  `079`, but drops leading zeros from written ones (`079` becomes `79`) and splits
  hyphenated numbers. A provider that writes phone numbers as digits is penalized
  even when every digit is right. **Lenient WER** fixes this: digits split by
  spaces or hyphens become one number, leading zeros drop, adjacent numbers in the
  same sentence join, "all right" = "alright", and an "oh" that isn't part of a
  number stays a word instead of becoming 0. Dates and times are matched by meaning:
  `02/02/1964` = "second of the second, 1964", `9th` = `9`, `3:00` = "three",
  `2:30` = "half two", `9:15` = "quarter past nine", `3:45` = "quarter to four". **Numbers correct** applies the same rules, so a single
  wrong digit in a phone number (which WER buries among formatting errors) shows up.
  Numbers spoken back to back in one sentence merge into one, as the benchmark's
  normalizer merges them in the reference; a slip in either then counts the whole
  group as missed. Check `wer_errors.csv` for what was actually heard.
- **First partial plausible**: ElevenLabs isn't told the language, so its first
  interim result is sometimes a guess in another language ("Алло!" for English
  speech). TTFT then times that guess, not real text. Read TTFT together with this.
- **Noise attribution**: DEMAND noise clips are CC BY-SA 3.0 (see `noise/ATTRIBUTION.txt`).
