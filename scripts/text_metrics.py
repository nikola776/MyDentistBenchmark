"""Accuracy metrics computed from a reference and a transcript, with no API calls.

Everything starts from the benchmark's own normalization
(coval_bench.metrics.wer), so the official WER here is identical to the
benchmark's and the extra metrics are comparable with it.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import jiwer
from coval_bench.metrics.wer import WordError, compute_wer, normalize_text

# Separators inside a written number: "079-33-415-028", "485 777 3912".
_DIGIT_SEPARATOR = re.compile(r"(?<=\d)[ \-‐-–]+(?=\d)")
# A date written as digits, day first (UK): "02/02/1964" -> "2nd of the 2nd, 1964", the
# spoken form's order ("second of the second, 1964").
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _spoken_date(m: re.Match[str]) -> str:
    return f"{_ordinal(int(m.group(1)))} of the {_ordinal(int(m.group(2)))}, {m.group(3)}"

# The leading 0 of a written phone-length number, which the normalizer drops ("07933..." -> "7933...")
# but keeps when spoken ("oh seven nine..."). Spelled out so both sides keep it.
_LEADING_ZERO = re.compile(r"\b0(?=\d{4,})")
_ORDINAL = re.compile(r"^(\d+)(?:st|nd|rd|th)$")
# A whole hour written as a clock time: "at 3:00" == "at three", "past 9:00" == "past nine".
_WHOLE_HOUR = re.compile(r"\b(\d{1,2}):00\b")
# British spoken times as clock times: "half two" == "2:30", "quarter past nine" == "9:15",
# "quarter to four" == "3:45". Applied to both sides, so a wrong time still counts as wrong.
_HOURS = {
    w: i
    for i, w in enumerate(
        ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"], start=1
    )
}
_SPOKEN_TIME = re.compile(
    r"\b(half past|half|quarter past|quarter to)\s+(" + "|".join(_HOURS) + r"|1[0-2]|[1-9])\b", re.I
)


def _clock(m: re.Match[str]) -> str:
    word = m.group(2).lower()
    hour = _HOURS.get(word) or int(word)
    minutes = {"half past": 30, "half": 30, "quarter past": 15}.get(m.group(1).lower())
    if minutes is None:  # quarter to
        return f"{(hour - 2) % 12 + 1}:45"
    return f"{hour}:{minutes}"
# Numbers never join across a sentence end (". ", "? ", "! ", a new line): "ninety. Oh seven
# nine..." is a year, then a phone number. Commas don't split, since phone numbers are spoken
# in comma-separated groups. The marker survives normalization and is dropped afterwards.
_SENTENCE_END = re.compile(r"[.?!]+(?=\s|$)|\n+")
_BREAK = "zzsentencebreakzz"
# Spelling variants that aren't recognition errors; applied after normalization.
_EQUIVALENT = [(re.compile(r"\ball right\b"), "alright"), (re.compile(r"\bokay\b"), "ok")]
_WORD = re.compile(r"[A-Za-z']+|\d+")
_DIGIT_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "double", "triple"}


def _protect_interjection_oh(text: str) -> str:
    """The normalizer reads every "oh" as the digit 0 ("Oh, hiya" -> "0 hiya"). Keep "oh" as
    a digit only next to other digits ("oh seven nine"); otherwise rewrite it as "ohh", the
    same way on both sides, so it isn't counted as a number."""
    words = list(_WORD.finditer(text))
    out, last = [], 0
    for i, m in enumerate(words):
        if m.group().lower() != "oh":
            continue
        near = [words[j].group().lower() for j in (i - 1, i + 1) if 0 <= j < len(words)]
        if not any(w in _DIGIT_WORDS or w.isdigit() for w in near):
            out += [text[last : m.start()], "ohh"]
            last = m.end()
    return "".join(out) + text[last:]


def lenient_tokens(text: str) -> list[str]:
    """Benchmark normalization, then forgive formatting that isn't a recognition error:

    - digits split by spaces or hyphens are one number, so "079-33-415-028" matches
      "oh seven nine double three four one five oh two eight"
    - adjacent number tokens join, and leading zeros drop (the normalizer keeps them for
      spoken digits but drops them for written ones); a phone number's leading 0 is kept on
      both sides so it still joins correctly with a number spoken just before it
    - "02/02/1964" == "second of the second, 1964", "9th" == "9", "3:00" == "three",
      "half two" == "2:30", "quarter past nine" == "9:15"
    - numbers from different sentences never join ("ninety. Oh seven nine..." = 90, then 079...)
    - "all right" == "alright", "okay" == "ok"
    - an "oh" that isn't part of a number stays a word instead of becoming 0
    """
    text = _NUMERIC_DATE.sub(_spoken_date, text)
    text = _SPOKEN_TIME.sub(_clock, _WHOLE_HOUR.sub(r"\1", text))
    text = _SENTENCE_END.sub(f" {_BREAK} ", text)
    text = _LEADING_ZERO.sub("oh ", _DIGIT_SEPARATOR.sub("", text))
    norm = normalize_text(_protect_interjection_oh(text))
    for pattern, repl in _EQUIVALENT:
        norm = pattern.sub(repl, norm)
    tokens: list[str] = []
    joinable = False
    for tok in norm.split():
        if tok == _BREAK:
            joinable = False
            continue
        # An ordinal ("9th", or a bare number after "the": "of the 9") is a complete number,
        # usually part of a date: nothing joins onto it or after it.
        ordinal = _ORDINAL.match(tok)
        if ordinal:
            tok = ordinal.group(1)
        complete = bool(ordinal) or (tok.isdigit() and bool(tokens) and tokens[-1] == "the")
        if tok.isdigit() and not complete and joinable and tokens[-1].isdigit():
            tokens[-1] += tok
        else:
            tokens.append(tok)
        joinable = not complete
    return [(t.lstrip("0") or "0") if t.isdigit() else t for t in tokens]


def _numbers(tokens: list[str]) -> Counter[str]:
    return Counter(t for t in tokens if any(c.isdigit() for c in t))


def text_metrics(reference: str, hypothesis: str) -> tuple[dict[str, Any], list[WordError]]:
    """Return (metrics, word errors). Percentages are 0-100; lower is better except numbers_pct.

    wer_pct            official benchmark WER (+ substitution/insertion/deletion split)
    wer_lenient_pct    WER after lenient_tokens(): number formatting and spelling variants forgiven
    cer_pct            character error rate on benchmark-normalized text
    mer_pct, wil_pct   match error rate and word information lost (jiwer definitions)
    numbers_pct        share of numbers in the reference (phone, dates, times, prices) that
                       appear in the transcript, order-insensitive, after lenient_tokens()
    """
    official = compute_wer(reference, hypothesis)
    split = official.error_percentages
    ref_norm, hyp_norm = official.normalized_reference, official.normalized_hypothesis
    words = jiwer.process_words(ref_norm, hyp_norm)

    ref_len, hyp_len = lenient_tokens(reference), lenient_tokens(hypothesis)
    ref_nums, hyp_nums = _numbers(ref_len), _numbers(hyp_len)
    found, total = sum((ref_nums & hyp_nums).values()), sum(ref_nums.values())

    metrics = {
        "wer_pct": official.wer_percentage,
        "wer_sub_pct": split["wer_substitutions_pct"],
        "wer_ins_pct": split["wer_insertions_pct"],
        "wer_del_pct": split["wer_deletions_pct"],
        "wer_lenient_pct": jiwer.wer(" ".join(ref_len), " ".join(hyp_len)) * 100,
        "cer_pct": jiwer.cer(ref_norm, hyp_norm) * 100,
        "mer_pct": words.mer * 100,
        "wil_pct": words.wil * 100,
        "numbers_pct": found / total * 100 if total else None,
        "numbers_found": found,
        "numbers_total": total,
    }
    return metrics, official.incorrect_words


def first_partial_plausible(reference: str, first_partial: str | None) -> bool | None:
    """Whether the first interim transcript shares at least one word with the reference.

    Providers that auto-detect language can open with text in the wrong language
    (e.g. "Алло!" for English speech). TTFT then times that guess, not real text.
    """
    if not (reference and first_partial):
        return None
    return bool(set(lenient_tokens(first_partial)) & set(lenient_tokens(reference)))
