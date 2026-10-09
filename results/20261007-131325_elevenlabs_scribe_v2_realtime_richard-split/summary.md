# elevenlabs/scribe_v2_realtime: clean vs noisy

- Started: 2026-10-07T11:13:25+00:00, finished: 2026-10-07T11:18:27+00:00, rescored: 2026-10-09T10:34:25+00:00
- Runs per clip: 1, concurrency: 5, files: Richard_scenarios.wav, Richard_script.wav
- Benchmark repo commit: b497b821f4c2132ebf36eb4cea200dc605ad9596, WER normalization v2
- Values in brackets are the change vs clean.

## Accuracy (mean over streams)

| Variant | OK | WER % | Lenient WER % | CER % | Numbers correct % | Sub / Ins / Del % | MER % | WIL % |
|---|---|---|---|---|---|---|---|---|
| clean | 2/2 | 6.86 | 5.15 | 3.62 | 100.0 | 2.9 / 3.3 / 0.6 | 6.61 | 9.38 |
| white_snr5 | 2/2 | 9.10 (+2.24) | 7.41 (+2.27) | 5.09 (+1.47) | 100.0 (+0.0) | 4.3 / 3.6 / 1.2 | 8.77 | 12.77 |
| cafeteria_snr5 | 2/2 | 7.42 (+0.56) | 5.33 (+0.19) | 4.02 (+0.40) | 100.0 (+0.0) | 2.9 / 3.7 / 0.8 | 7.14 | 9.90 |
| reverb_rt0.6 | 2/2 | 7.23 (+0.37) | 5.15 (+0.00) | 3.70 (+0.08) | 100.0 (+0.0) | 2.9 / 3.7 / 0.6 | 6.96 | 9.72 |

## Latency (median over streams)

| Variant | TTFT s | TTFT range | First partial plausible % | TTFS s | TTFS range | Audio→final s | RTF | Connect s | Partial updates |
|---|---|---|---|---|---|---|---|---|---|
| clean | 2.68 | 2.22-3.15 | 100 | 0.26 | 0.24-0.28 | 135.19 | 1.002 | 0.41 | 134 |
| white_snr5 | 2.74 (+0.06) | 2.32-3.16 | 50 | 0.27 (+0.01) | 0.24-0.29 | 135.20 | 1.002 | 0.36 | 134 |
| cafeteria_snr5 | 2.21 (-0.47) | 2.21-2.22 | 0 | 0.25 (-0.00) | 0.23-0.28 | 135.19 | 1.002 | 0.41 | 136 |
| reverb_rt0.6 | 2.67 (-0.02) | 2.21-3.13 | 100 | 0.29 (+0.03) | 0.29-0.29 | 135.22 | 1.002 | 0.36 | 134 |

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
