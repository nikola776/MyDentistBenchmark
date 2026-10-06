# Noise-robustness benchmark scripts

Measure how an STT provider's accuracy and latency hold up as recordings get
noisier. These scripts use the benchmark repo's own provider and metric code,
so the numbers follow the public benchmark's method.

## Setup

```bash
git clone --recurse-submodules <this repo> && cd <repo>
cd benchmarks/runner && uv sync && cd ../..        # benchmark code (pinned submodule)
cp benchmarks/.env.example benchmarks/.env          # add provider API keys
```

Recordings, noise clips and generated audio aren't in git. Put recordings in
`data/` and run the workflow below.

## Folder layout (`~/benchmarks`)

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

## Benchmark options

| Option | Default | |
|---|---|---|
| `--provider`, `--model` | `elevenlabs`, `scribe_v2_realtime` | any registered STT model; its key must be in `benchmarks/.env` |
| `--runs N` | 3 | streams per clip, to get a latency spread |
| `--only PATTERN` | all | variants to run, repeatable: `--only clean --only 'cafeteria_*'` |
| `--files PATTERN` | all | recordings to run, e.g. `--files Ian` |
| `--default-reference` | `script.txt` | transcript for recordings without their own `<name>.txt` |
| `--concurrency N` | 1 | parallel streams; above 1 is faster but can skew latency |
| `--no-ttfs` | off | skip VAD: no TTFS, and stream whole files untrimmed |
| `--label NAME` | | added to the results folder name |
| `--dry-run` | | list the streams and estimated time without calling the API |

Streaming is real time: each stream takes as long as the recording. The default
config (clean + 16 variants, 3 runs, one 94 s recording) takes about 80 minutes.
Ctrl-C stops early and still writes a summary of the finished streams.

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

Steps can be chained, e.g. cafeteria noise followed by a phone line. The
`seed` makes output reproducible: same config and input give byte-identical files.

## Results (`results/<timestamp>_<provider>_<model>/`)

| File | Contents |
|---|---|
| `summary.md` | per-variant table: WER, TTFT, TTFS, audio→final, RTF |
| `summary.csv` | the same with mean/median/min/max of every metric |
| `runs.csv` | one row per stream, written as each stream finishes |
| `wer_errors.csv` | every word error: type, reference word, recognized word |
| `transcripts/<variant>/` | what the provider returned, per run |
| `meta.json`, `noise_manifest.json` | settings, repo commit, VAD offsets, exact noise parameters |

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
  even when every digit is right. Check `wer_errors.csv` before reading too much
  into WER on number-heavy speech.
- **Noise attribution**: DEMAND noise clips are CC BY-SA 3.0 (see `noise/ATTRIBUTION.txt`).
