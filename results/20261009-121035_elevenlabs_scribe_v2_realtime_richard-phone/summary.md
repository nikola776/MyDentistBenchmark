# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-09T10:10:35+00:00, finished: 2026-10-09T10:13:06+00:00, rescored: 2026-10-09T10:34:26+00:00
- Runs per clip: 1, concurrency: 5, files: Richard_scenarios.wav, Richard_script.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2
- Values in brackets are the change vs clean.

## Accuracy (mean over streams)

| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |
|---|---|---|---|---|---|---|---|---|
| phone | 2/2 | 7.37 | 5.66 | 3.73 | 100.0 | 3.4 / 3.3 / 0.6 | 7.09 | 10.30 |

## Latency (median over streams)

| Variant | TTFT s | TTFT range | First partial plausible % | TTFS s | TTFS range | Audio→final s | RTF | Connect s | Partial updates |
|---|---|---|---|---|---|---|---|---|---|
| phone | 2.66 | 2.21-3.11 | 100 | 0.24 | 0.22-0.26 | 135.17 | 1.002 | 0.35 | 134 |

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
