#!/usr/bin/env python3
"""humanise.py — deterministic AI-tell detector (the diagnostic pass).

The mechanical half of the `humanise` skill. It does NOT rewrite — it measures.
The model reads this report, then does the judgment rewrite per SKILL.md.

Usage:
    python3 humanise.py <file>            # readable report
    python3 humanise.py --json <file>     # machine-readable
    cat draft.txt | python3 humanise.py   # stdin
    python3 humanise.py --text "some prose here"

No third-party deps. stdlib only.
"""
import sys
import re
import json
import statistics

# --- the corporate-safe word list (whole-word, case-insensitive) ---
CORPORATE = [
    "delve", "leverage", "tapestry", "navigate", "realm", "testament",
    "underscore", "robust", "seamless", "foster", "pivotal", "landscape",
    "holistic", "strategic", "transformative", "innovative", "ecosystem",
    "cutting-edge", "empower", "synergy", "unlock", "elevate", "streamline",
    "harness", "spearhead", "facilitate", "utilize", "myriad", "plethora",
    "intricate", "nuanced", "vibrant", "bustling", "showcase", "boasts",
    "moreover", "furthermore",
]
INTENSIFIERS = [
    "highly", "truly", "extremely", "incredibly", "remarkably", "vitally",
    "significantly", "substantially", "absolutely", "utterly",
]
HEDGES = [
    r"it'?s worth noting", r"it'?s important to", r"should be noted that",
    r"can help to", r"it'?s essential to", r"it is worth mentioning",
    r"keep in mind that", r"that being said", r"needless to say",
]
SIGNPOSTS = [
    r"\bmoreover\b", r"\bfurthermore\b", r"\badditionally\b",
    r"\bin addition\b", r"\bnotably\b",
]
CLOSERS = [
    r"\bin conclusion\b", r"\bultimately\b", r"\bin summary\b",
    r"\bat the end of the day\b", r"\bin essence\b", r"\boverall\b",
]
ANTITHESIS = [
    r"not (just|only|merely) [^.,;]{1,40}?[,;]?\s*(it'?s|but|they'?re|but rather)\b",
    r"isn'?t (just|only|merely) [^.,;]{1,40}?[,;]?\s*it'?s\b",
    r"doesn'?t just [^.,;]{1,40}?[,;:]\s*it\b",
]
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF⭐]"
)


def find_words(text, words):
    hits = {}
    low = text.lower()
    for w in words:
        # whole-word, allow hyphenated
        pat = r"(?<![\w-])" + re.escape(w.lower()) + r"(?![\w-])"
        n = len(re.findall(pat, low))
        if n:
            hits[w] = n
    return hits


def find_patterns(text, patterns):
    hits = []
    for p in patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            hits.append(m.group(0).strip())
    return hits


def sentences(text):
    # crude but adequate: split on sentence enders followed by space/eol
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in parts if s.strip()]


def analyse(text):
    words = re.findall(r"\S+", text)
    wc = len(words)
    sents = sentences(text)
    lens = [len(re.findall(r"\S+", s)) for s in sents] or [0]
    stdev = statistics.pstdev(lens) if len(lens) > 1 else 0.0
    in_band = sum(1 for L in lens if 15 <= L <= 25)
    band_pct = round(100 * in_band / len(lens)) if lens else 0

    em = text.count("—")        # —
    en = text.count("–")        # –
    spaced_hyphen = len(re.findall(r"\s-\s", text))
    dash_total = em + en + spaced_hyphen
    dash_per_100w = round(100 * dash_total / wc, 2) if wc else 0

    triads = len(re.findall(r"\w+,\s+\w+,\s+and\s+\w+", text))

    report = {
        "word_count": wc,
        "sentence_count": len(sents),
        "burstiness_stdev": round(stdev, 1),
        "sentence_len_min": min(lens),
        "sentence_len_max": max(lens),
        "sentence_len_mean": round(statistics.mean(lens), 1),
        "pct_in_15_25_band": band_pct,
        "em_dashes": em,
        "en_dashes": en,
        "spaced_hyphens": spaced_hyphen,
        "dashes_per_100w": dash_per_100w,
        "corporate_words": find_words(text, CORPORATE),
        "empty_intensifiers": find_words(text, INTENSIFIERS),
        "hedges": find_patterns(text, HEDGES),
        "signposts": find_patterns(text, SIGNPOSTS),
        "closers": find_patterns(text, CLOSERS),
        "antithesis": find_patterns(text, ANTITHESIS),
        "triadic_lists": triads,
        "emoji": len(EMOJI.findall(text)),
    }

    # crude tell score: each class contributes
    score = 0
    score += sum(report["corporate_words"].values())
    score += sum(report["empty_intensifiers"].values())
    score += 2 * len(report["hedges"])
    score += len(report["signposts"])
    score += 3 * len(report["closers"])
    score += 3 * len(report["antithesis"])
    score += triads
    score += report["emoji"]
    if report["dashes_per_100w"] > 1.0:
        score += int(report["dashes_per_100w"])
    if wc >= 40 and stdev < 6:          # low burstiness on enough text
        score += 5
    if wc >= 40 and band_pct > 70:
        score += 3
    report["tell_score"] = score
    report["verdict"] = (
        "reads human" if score <= 3 else
        "some tells" if score <= 10 else
        "strong AI fingerprint"
    )
    return report


def render(r):
    L = []
    L.append(f"AI-TELL REPORT  —  score {r['tell_score']}  ({r['verdict']})")
    L.append("-" * 52)
    L.append(f"words {r['word_count']} · sentences {r['sentence_count']}")
    L.append(
        f"sentence length: mean {r['sentence_len_mean']}, "
        f"min {r['sentence_len_min']}, max {r['sentence_len_max']}, "
        f"stdev {r['burstiness_stdev']} "
        f"({'LOW burstiness — too uniform' if r['burstiness_stdev'] < 6 and r['word_count'] >= 40 else 'ok'})"
    )
    L.append(f"  {r['pct_in_15_25_band']}% of sentences in the 15-25w AI band")
    L.append(
        f"dashes: {r['em_dashes']} em, {r['en_dashes']} en, "
        f"{r['spaced_hyphens']} spaced  → {r['dashes_per_100w']}/100w"
        f"{'  ⚑ overused' if r['dashes_per_100w'] > 1.0 else ''}"
    )

    def line(label, val):
        if val:
            if isinstance(val, dict):
                shown = ", ".join(f"{k}×{n}" for k, n in val.items())
            elif isinstance(val, list):
                shown = "; ".join(val[:8]) + (f"  (+{len(val)-8} more)" if len(val) > 8 else "")
            else:
                shown = str(val)
            L.append(f"⚑ {label}: {shown}")

    line("corporate words", r["corporate_words"])
    line("empty intensifiers", r["empty_intensifiers"])
    line("hedges", r["hedges"])
    line("signpost transitions", r["signposts"])
    line("summary closers", r["closers"])
    line("antithesis (not just X, it's Y)", r["antithesis"])
    if r["triadic_lists"]:
        L.append(f"⚑ triadic 'A, B, and C' lists: {r['triadic_lists']}")
    if r["emoji"]:
        L.append(f"⚑ emoji: {r['emoji']}")
    if r["tell_score"] <= 3:
        L.append("\nClean. No structural rewrite needed.")
    return "\n".join(L)


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args and args[0] == "--text":
        text = " ".join(args[1:])
    elif args:
        with open(args[0], encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    if not text.strip():
        print("humanise.py: no input text", file=sys.stderr)
        sys.exit(1)
    r = analyse(text)
    print(json.dumps(r, indent=2, ensure_ascii=False) if as_json else render(r))


if __name__ == "__main__":
    main()
