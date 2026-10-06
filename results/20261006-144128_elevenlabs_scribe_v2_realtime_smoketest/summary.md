# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-06T12:41:28+00:00, finished: 2026-10-06T12:45:08+00:00, rescored: 2026-10-06T13:54:31+00:00
- Runs per clip: 1, concurrency: 1, files: Ian.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2
- Values in brackets are the change vs clean.

## Accuracy (mean over streams)

| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |
|---|---|---|---|---|---|---|---|---|
| clean | 1/1 | 9.55 | 2.51 | 2.70 | 100.0 | 3.5 / 5.5 / 0.5 | 9.05 | 12.29 |
| cafeteria_snr5 | 1/1 | 11.06 (+1.51) | 4.52 (+2.01) | 3.78 (+1.08) | 94.1 (-5.9) | 4.5 / 6.0 / 0.5 | 10.43 | 14.52 |

## Latency (median over streams)

| Variant | TTFT s | TTFT range | TTFS s | TTFS range | Audio→final s | RTF | Connect s | Partial updates |
|---|---|---|---|---|---|---|---|---|
| clean | 2.21 | 2.21-2.21 | 0.19 | 0.19-0.19 | 94.17 | 1.002 | - | - |
| cafeteria_snr5 | 2.16 (-0.06) | 2.16-2.16 | 0.26 (+0.07) | 0.26-0.26 | 94.25 | 1.003 | - | - |

**Accuracy** (vs the reference transcript; lower is better except Numbers):
- **WER**: the benchmark's official word error rate.
- **Lenient WER**: WER that ignores number formatting (079-33-415-028 = "oh seven nine double three...") and spelling variants (all right = alright). Closer to real recognition mistakes.
- **CER**: character error rate; partly wrong words count partly.
- **Numbers correct**: share of the reference's numbers (phone, dates, times, prices) found exactly in the transcript.
- **MER / WIL**: match error rate and word information lost, alternative WER-style rates.

**Latency**:
- **TTFT**: first audio sent → first partial transcript.
- **TTFS**: end of speech (Silero VAD on the clean file) → final transcript. Audio after end of speech is trimmed before streaming, as in the benchmark.
- **Audio→final**: first audio sent → final transcript. **RTF**: audio→final / audio length.
- **Connect**: opening the connection (handshake, auth) until the first audio is sent.
- **Partial updates**: interim transcripts received per stream; more means the text updates more often.

Per-stream rows: `runs.csv`; word-level errors: `wer_errors.csv`; transcripts: `transcripts/`.
