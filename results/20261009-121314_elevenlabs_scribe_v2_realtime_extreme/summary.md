# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-09T10:13:14+00:00, finished: 2026-10-09T10:29:27+00:00, rescored: 2026-10-09T10:34:29+00:00
- Runs per clip: 1, concurrency: 5, files: Ian.wav, Richard_scenarios.wav, Richard_script.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2
- Values in brackets are the change vs clean.

## Accuracy (mean over streams)

| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |
|---|---|---|---|---|---|---|---|---|
| white_snr0 | 3/3 | 11.29 | 8.84 | 5.98 | 92.2 | 5.2 / 4.3 / 1.8 | 10.82 | 15.60 |
| white_snr-5 | 3/3 | 36.14 | 35.24 | 26.28 | 63.9 | 27.3 / 5.7 / 3.2 | 34.03 | 51.31 |
| cafeteria_snr0 | 3/3 | 13.08 | 9.89 | 7.31 | 85.8 | 6.3 / 4.3 / 2.6 | 12.50 | 17.87 |
| cafeteria_snr-5 | 3/3 | 33.07 | 30.36 | 22.86 | 74.0 | 19.2 / 6.9 / 7.0 | 30.74 | 43.99 |
| street_snr0 | 3/3 | 7.58 | 5.40 | 3.65 | 100.0 | 3.9 / 3.0 / 0.7 | 7.34 | 10.98 |
| street_snr-5 | 3/3 | 11.65 | 7.16 | 6.04 | 96.1 | 4.1 / 5.6 / 1.9 | 10.84 | 14.67 |
| reverb_rt1.2 | 3/3 | 8.68 | 4.63 | 3.62 | 100.0 | 3.3 / 4.8 / 0.6 | 8.24 | 11.30 |
| phone_cafeteria_snr5 | 3/3 | 11.22 | 6.93 | 5.73 | 92.2 | 5.7 / 4.0 / 1.5 | 10.75 | 15.93 |
| phone_street_snr5 | 3/3 | 6.88 | 5.10 | 3.39 | 98.0 | 3.3 / 2.7 / 0.9 | 6.66 | 9.77 |
| mobile_loss5 | 3/3 | 8.22 | 4.41 | 3.72 | 100.0 | 3.3 / 3.9 / 1.0 | 7.88 | 10.97 |
| mobile_loss15 | 3/3 | 9.18 | 6.43 | 4.49 | 100.0 | 4.2 / 3.6 / 1.5 | 8.81 | 12.39 |

## Latency (median over streams)

| Variant | TTFT s | TTFT range | First partial plausible % | TTFS s | TTFS range | Audio→final s | RTF | Connect s | Partial updates |
|---|---|---|---|---|---|---|---|---|---|
| white_snr0 | 2.21 | 2.21-3.10 | 33 | 0.22 | 0.21-0.24 | 135.10 | 1.002 | 0.34 | 133 |
| white_snr-5 | 2.49 | 2.47-3.12 | 33 | 0.28 | 0.26-0.29 | 135.17 | 1.002 | 0.35 | 130 |
| cafeteria_snr0 | 2.22 | 2.12-4.03 | 33 | 0.26 | 0.25-0.34 | 135.14 | 1.003 | 0.33 | 112 |
| cafeteria_snr-5 | 2.26 | 2.22-5.05 | 67 | 0.21 | 0.18-0.27 | 135.07 | 1.002 | 0.28 | 124 |
| street_snr0 | 2.22 | 2.22-3.05 | 33 | 0.24 | 0.23-0.28 | 135.16 | 1.002 | 0.28 | 133 |
| street_snr-5 | 2.37 | 2.21-3.09 | 67 | 0.23 | 0.20-0.24 | 135.12 | 1.002 | 0.26 | 133 |
| reverb_rt1.2 | 2.22 | 2.21-3.05 | 67 | 0.22 | 0.19-0.25 | 135.11 | 1.002 | 0.29 | 133 |
| phone_cafeteria_snr5 | 2.13 | 2.12-5.03 | 67 | 0.24 | 0.17-0.25 | 135.13 | 1.002 | 0.27 | 130 |
| phone_street_snr5 | 2.22 | 2.21-3.17 | 67 | 0.22 | 0.18-0.22 | 135.06 | 1.002 | 0.27 | 133 |
| mobile_loss5 | 2.22 | 2.22-3.11 | 0 | 0.24 | 0.21-0.24 | 135.12 | 1.002 | 0.29 | 133 |
| mobile_loss15 | 3.09 | 2.23-3.16 | 33 | 0.24 | 0.23-0.28 | 135.16 | 1.002 | 0.27 | 133 |

**Accuracy** (vs the reference transcript; lower is better except Numbers):
- **WER**: the benchmark's official word error rate.
- **Lenient WER**: WER that ignores number formatting (079-33-415-028 = "oh seven nine double three...") and spelling variants (all right = alright). Closer to real recognition mistakes.
- **CER**: character error rate; partly wrong words count partly.
- **Numbers correct**: share of the reference's numbers (phone, dates, times, prices) found exactly in the transcript.
- **MER / WIL**: match error rate and word information lost, alternative WER-style rates.

**Latency**:
- **TTFT**: first audio sent → first partial transcript.
- **First partial plausible**: share of streams whose first partial shares a word with the reference. Below 100% means TTFT sometimes timed a wrong-language guess (e.g. "Алло!"), not real text.
- **TTFS**: end of speech (Silero VAD on the clean file) → final transcript. Audio after end of speech is trimmed before streaming, as in the benchmark.
- **Audio→final**: first audio sent → final transcript. **RTF**: audio→final / audio length.
- **Connect**: opening the connection (handshake, auth) until the first audio is sent.
- **Partial updates**: interim transcripts received per stream; more means the text updates more often.

Per-stream rows: `runs.csv`; word-level errors: `wer_errors.csv`; transcripts: `transcripts/`.
