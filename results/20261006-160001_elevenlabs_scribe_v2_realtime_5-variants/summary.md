# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-06T14:00:01+00:00, finished: 2026-10-06T14:01:51+00:00
- Runs per clip: 1, concurrency: 5, files: Ian.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2
- Values in brackets are the change vs clean.

## Accuracy (mean over streams)

| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |
|---|---|---|---|---|---|---|---|---|
| clean | 1/1 | 9.55 | 2.51 | 2.70 | 100.0 | 3.5 / 5.5 / 0.5 | 9.05 | 12.29 |
| white_snr5 | 1/1 | 12.06 (+2.51) | 6.03 (+3.52) | 4.32 (+1.62) | 82.4 (-17.6) | 5.5 / 6.0 / 0.5 | 11.37 | 16.32 |
| cafeteria_snr5 | 1/1 | 11.06 (+1.51) | 4.52 (+2.01) | 3.78 (+1.08) | 94.1 (-5.9) | 4.5 / 6.0 / 0.5 | 10.43 | 14.52 |
| phone | 1/1 | 9.55 (+0.00) | 2.51 (+0.00) | 2.70 (+0.00) | 100.0 (+0.0) | 3.5 / 5.5 / 0.5 | 9.05 | 12.29 |
| reverb_rt0.6 | 1/1 | 11.56 (+2.01) | 5.03 (+2.51) | 3.89 (+1.19) | 82.4 (-17.6) | 4.5 / 5.5 / 1.5 | 10.95 | 15.11 |

## Latency (median over streams)

| Variant | TTFT s | TTFT range | First partial plausible % | TTFS s | TTFS range | Audio→final s | RTF | Connect s | Partial updates |
|---|---|---|---|---|---|---|---|---|---|
| clean | 2.11 | 2.11-2.11 | 0 | 0.29 | 0.29-0.29 | 94.28 | 1.003 | 0.41 | 94 |
| white_snr5 | 2.18 (+0.07) | 2.18-2.18 | 0 | 0.19 (-0.10) | 0.19-0.19 | 94.18 | 1.002 | 0.40 | 93 |
| cafeteria_snr5 | 2.11 (+0.00) | 2.11-2.11 | 0 | 0.23 (-0.06) | 0.23-0.23 | 94.22 | 1.002 | 0.33 | 93 |
| phone | 2.23 (+0.12) | 2.23-2.23 | 0 | 0.31 (+0.02) | 0.31-0.31 | 94.29 | 1.003 | 0.37 | 94 |
| reverb_rt0.6 | 2.12 (+0.01) | 2.12-2.12 | 0 | 0.22 (-0.06) | 0.22-0.22 | 94.21 | 1.002 | 0.36 | 93 |

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
