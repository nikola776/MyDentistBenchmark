# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-06T12:41:28+00:00, finished: 2026-10-06T12:45:08+00:00
- Runs per clip: 1, concurrency: 1, files: Ian.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2

| Variant | OK | WER % mean (min-max) | Sub / Ins / Del % | TTFT s median (min-max) | TTFS s median (min-max) | Audio→final s median | RTF median |
|---|---|---|---|---|---|---|---|
| clean | 1/1 | 9.55 (9.55-9.55) | 3.5 / 5.5 / 0.5 | 2.21 (2.21-2.21) | 0.19 (0.19-0.19) | 94.17 | 1.002 |
| cafeteria_snr5 | 1/1 | 11.06 (11.06-11.06) | 4.5 / 6.0 / 0.5 | 2.16 (2.16-2.16) | 0.26 (0.26-0.26) | 94.25 | 1.003 |

- **WER**: word error rate vs `transcripts/<name>.txt`, benchmark normalization (lower is better).
- **TTFT**: time from first audio sent to first partial transcript.
- **TTFS**: time from end of speech (Silero VAD on the clean file) to the final transcript.
  Audio after end of speech is trimmed before streaming, as in the benchmark.
- **Audio→final**: time from first audio sent to the final transcript. **RTF**: audio→final / audio length.
- Per-stream rows: `runs.csv`; word-level errors: `wer_errors.csv`; transcripts: `transcripts/`.
