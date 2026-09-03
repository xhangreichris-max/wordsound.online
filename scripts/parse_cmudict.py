"""
CMUdict parser for wordsound.online.

Derives, per word:
  - syllable count       (from stressed ARPAbet vowel phonemes)
  - syllable split        (pure phoneme-driven: maximal-onset syllabification,
                            then mapped back onto the spelling via a
                            phoneme -> grapheme character-consumption walk)
  - stress pattern         (1 = primary, 2 = secondary, 0 = unstressed, per syllable)
  - open/closed per syllable (from the same phoneme syllabification)

Multiple pronunciations (cmudict marks alternates as "word(2)", "word(3)", ...)
are resolved as follows:
  - For words in PREFER_MORE_SYLLABLES, pick the pronunciation with the
    HIGHEST syllable count (the "full" citation form searchers expect,
    even where casual speech compresses it: fire, hour, our, every, ...).
  - For everything else, use cmudict's first-listed pronunciation.
"""

import re
import sys
from pathlib import Path

DICT_PATH = Path(__file__).parent.parent / "data" / "cmudict.dict"
FREQ_PATH = Path(__file__).parent.parent / "data" / "count_1w.txt"
VOCAB_PATH = Path(__file__).parent.parent / "data" / "scowl_70.txt"

# cmudict.dict and count_1w.txt are large (24MB combined) and permissively
# licensed, so rather than commit them, this fetches and caches them
# locally on first run -- both a local dev checkout and CI start with an
# empty data/ dir. Pinned to a specific commit/URL (not a moving "latest")
# so a build today and a build next year read the identical bytes.
#
# scowl_70.txt has NO download step and IS committed to the repo instead:
# it's not a static file, it's dynamically generated per-request by
# app.aspell.net/create from the ESDB database, which is revised over
# time -- re-fetching it later could silently return a different word
# list than the one the site was built and reviewed against.
CMUDICT_URL = (
    "https://raw.githubusercontent.com/cmusphinx/cmudict/"
    "0f8072f814306c5ee4fbf992ed853601b12c01f9/cmudict.dict"
)
COUNT_1W_URL = "https://norvig.com/ngrams/count_1w.txt"


def _fetch(url, dest):
    import requests
    print(f"  downloading {dest.name} from {url} ...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"  saved {dest} ({dest.stat().st_size / 1024:.0f} KB)")


def ensure_data_files():
    """Downloads cmudict.dict / count_1w.txt if missing. No-ops (and makes
    no network call) once both are present, so a cached data/ dir in CI --
    or an already-populated one in local dev -- costs nothing on rebuild.
    Does NOT fetch scowl_70.txt; that one must exist as a committed file,
    and a missing one is a repo problem, not something to paper over by
    silently regenerating a possibly-different list."""
    if not DICT_PATH.exists():
        _fetch(CMUDICT_URL, DICT_PATH)
    if not FREQ_PATH.exists():
        _fetch(COUNT_1W_URL, FREQ_PATH)
    if not VOCAB_PATH.exists():
        raise FileNotFoundError(
            f"{VOCAB_PATH} is missing. Unlike cmudict.dict/count_1w.txt, this "
            f"file is committed to the repo (not fetched) because it's "
            f"dynamically generated and not reproducible from a static URL -- "
            f"restore it from git rather than trying to regenerate it."
        )

VOWEL_BASES = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
    "IH", "IY", "OW", "OY", "UH", "UW",
}

# Words where we deliberately prefer the pronunciation with MORE syllables,
# even if casual speech usually compresses it. Per product decision: these
# are the "citation form" searchers expect to see, not the reduced form.
PREFER_MORE_SYLLABLES = {
    "every", "fire", "hour", "our", "poem", "science",
    "quiet", "prayer", "caramel", "evening",
}

# ARPAbet consonant clusters that form legal English syllable onsets.
# Used when two vowels are separated by a consonant cluster: this decides
# how much of the cluster moves to the following syllable's onset (the
# rest stays behind as the coda of the previous syllable) -- i.e. the
# maximal onset principle, bounded by what English actually allows as a
# syllable-initial cluster. ("umbrella" -> um-brel-la, not u-mbrel-la,
# because "mbr" isn't a legal onset but "br" is.)
LEGAL_ONSETS_2 = {
    ("B", "L"), ("B", "R"), ("D", "R"), ("D", "W"), ("F", "L"), ("F", "R"),
    ("G", "L"), ("G", "R"), ("K", "L"), ("K", "R"), ("K", "W"), ("P", "L"),
    ("P", "R"), ("S", "K"), ("S", "L"), ("S", "M"), ("S", "N"), ("S", "P"),
    ("S", "T"), ("S", "W"), ("T", "R"), ("T", "W"), ("TH", "R"), ("SH", "R"),
    ("V", "L"), ("V", "R"), ("HH", "Y"),
}
LEGAL_ONSETS_3 = {
    ("S", "K", "R"), ("S", "K", "W"), ("S", "K", "L"), ("S", "P", "L"),
    ("S", "P", "R"), ("S", "T", "R"),
}

# Phoneme (base, no stress digit) -> candidate spellings, longest first.
# Used only to re-derive syllable boundaries in the ORIGINAL spelling from
# an already-known phoneme sequence -- not a general text-to-speech table.
GRAPHEMES = {
    # consonants
    "P": ["pp", "p"], "B": ["bb", "b"],
    "T": ["tt", "t"], "D": ["dd", "d"],
    "K": ["ck", "ch", "qu", "k", "c"], "G": ["gg", "gh", "g"],
    "CH": ["tch", "ch"], "JH": ["dge", "dg", "j", "g"],
    "F": ["ph", "ff", "gh", "f"], "V": ["ve", "v"],
    "TH": ["th"], "DH": ["th"],
    "S": ["ss", "sc", "c", "s"], "Z": ["zz", "se", "ze", "z", "s"],
    "SH": ["ssi", "ti", "ci", "sh", "ch"], "ZH": ["si", "zh", "ge"],
    "HH": ["wh", "h"],
    "M": ["mm", "mb", "m"], "N": ["nn", "kn", "gn", "n"],
    "NG": ["ng", "n"], "L": ["ll", "l"], "R": ["rr", "wr", "re", "r"],
    # Y/W glides are frequently absorbed into a neighboring vowel digraph
    # with no letter of their own (e.g. the Y in "beautiful" -> "eau", the
    # W in "quiet" -> "qu"). "" as a last-resort candidate lets the walker
    # skip them silently instead of wrongly eating an unrelated letter.
    "Y": ["y", "i", ""], "W": ["wh", "w", "u", ""],
    # vowels (longer/less-common digraphs first, plain letters last)
    "AA": ["au", "a", "o"],
    "AE": ["a"],
    "AH": ["a", "e", "i", "o", "u"],
    "AO": ["augh", "ough", "aw", "au", "al", "o", "a"],
    "AW": ["ou", "ow", "au"],
    # "ie" deliberately excluded here: it's a legitimate AY1 spelling in
    # monosyllables ("pie") but greedily eats into the next syllable's
    # vowel in hiatus words ("sci-ence", "qui-et") where i+e are two
    # separate nuclei, not one. Single-syllable words don't need a split
    # anyway, so dropping it only costs us the rarer case.
    "AY": ["igh", "eye", "y", "i"],
    "EH": ["ea", "e"],
    "ER": ["er", "ir", "ur", "or", "ar", "re", "r"],
    "EY": ["eigh", "ai", "ay", "ey", "ea", "a"],
    "IH": ["y", "i", "e"],
    "IY": ["ee", "ea", "ey", "ie", "y", "i", "e"],
    "OW": ["ow", "oa", "oe", "o"],
    "OY": ["oy", "oi"],
    "UH": ["oo", "u", "o"],
    "UW": ["eau", "oo", "ou", "ew", "ue", "u", "o"],
}

# Hand-verified overrides for words where the general algorithm's output
# doesn't match the split we want to publish (irregular spelling, or a
# pedagogical convention the general onset rule doesn't capture). Checked
# first, before the algorithm runs. Expand this as spot-checks surface
# new mismatches -- cheap and 100% accurate for the handful of words that
# actually need it, versus over-fitting the general algorithm to them.
CURATED_SPLITS = {
    "every": ["ev", "er", "y"],
    # Silent leading "h": no HH phoneme exists to anchor it, so the walker
    # strands it as its own 1-letter syllable ("h-our"). Curated instead.
    "hour": ["hou", "r"],
}


def strip_stress(phoneme):
    return re.sub(r"\d", "", phoneme)


def stress_digit(phoneme):
    m = re.search(r"\d", phoneme)
    return m.group(0) if m else None


def load_cmudict(path=DICT_PATH):
    """Returns dict: base_word -> list of pronunciations (each a list of phonemes)."""
    words = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";;;"):
                continue
            parts = line.split()
            raw_word, phonemes = parts[0], parts[1:]
            m = re.match(r"^(.*)\(\d+\)$", raw_word)
            base = m.group(1) if m else raw_word
            words.setdefault(base, []).append(phonemes)
    return words


def load_freq_counts(path=FREQ_PATH):
    """word -> raw occurrence count, from Norvig's count_1w.txt (Google
    Books unigram counts, ~333k words, tab-separated "word\\tcount").
    Higher count = more common. Words not in the list are simply absent --
    callers should treat a missing key as freq_count=None, not zero."""
    counts = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        word, _, count = line.partition("\t")
        word = word.strip().lower()
        if word and count:
            counts[word] = int(count)
    return counts


def load_vocab(path=VOCAB_PATH):
    """Set of real English dictionary words, from a SCOWL/ESDB size-70
    wordlist (app.aspell.net/create) -- excludes proper nouns and
    abbreviations by construction, unlike a web-frequency corpus, which
    can't distinguish "aaron" from "apple" since both just cross an
    occurrence threshold. This is the inclusion filter for list pages;
    count_1w.txt is ranking-only from here on.

    An earlier attempt (dwyl/english-words' words_alpha.txt) turned out to
    include plenty of personal names too (aaron, abbott, abby...) with no
    way to tell them apart from real words. SCOWL's raw file solves this
    because it preserves case: proper nouns appear ONLY capitalized
    ("Aaron", never "aaron"), so keeping just the fully-lowercase alphabetic
    lines both drops the license header (plain-English sentences aren't
    alphabetic-only) and drops every proper-noun/abbreviation entry, in one
    filter."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {w for w in (line.strip() for line in lines) if w.isalpha() and w.islower()}


def syllable_count(phonemes):
    return sum(1 for p in phonemes if stress_digit(p) is not None)


def pick_pronunciation(word, pronunciations):
    """Returns (phonemes, ambiguous: bool, counts_seen: set[int])."""
    counts = {syllable_count(p) for p in pronunciations}
    ambiguous = len(counts) > 1
    if word in PREFER_MORE_SYLLABLES and ambiguous:
        best = max(pronunciations, key=syllable_count)
        return best, ambiguous, counts
    return pronunciations[0], ambiguous, counts


def syllabify_phonemes(phonemes):
    """Split a phoneme list into syllables via vowel nuclei + maximal onset
    (bounded by phonotactic legality). Returns list of dicts:
        {"phonemes": [...], "vowel": "AH1", "stress": "1", "open": True/False}
    """
    vowel_idxs = [i for i, p in enumerate(phonemes) if stress_digit(p) is not None]
    if not vowel_idxs:
        return [{"phonemes": phonemes, "vowel": None, "stress": None, "open": False}]

    n = len(vowel_idxs)
    onsets = [[] for _ in range(n)]
    codas = [[] for _ in range(n)]

    onsets[0] = [strip_stress(p) for p in phonemes[:vowel_idxs[0]]]
    codas[-1] = [strip_stress(p) for p in phonemes[vowel_idxs[-1] + 1:]]

    for i in range(n - 1):
        start, end = vowel_idxs[i] + 1, vowel_idxs[i + 1]
        cluster = [strip_stress(p) for p in phonemes[start:end]]
        if not cluster:
            continue
        onset_len = 0
        if len(cluster) >= 3 and tuple(cluster[-3:]) in LEGAL_ONSETS_3:
            onset_len = 3
        elif len(cluster) >= 2 and tuple(cluster[-2:]) in LEGAL_ONSETS_2:
            onset_len = 2
        elif len(cluster) >= 1:
            onset_len = 1
        codas[i] = cluster[: len(cluster) - onset_len]
        onsets[i + 1] = cluster[len(cluster) - onset_len:]

    syllables = []
    for i, vi in enumerate(vowel_idxs):
        vowel_phoneme = phonemes[vi]
        syl_phonemes = onsets[i] + [vowel_phoneme] + codas[i]
        syllables.append({
            "phonemes": syl_phonemes,
            "vowel": vowel_phoneme,
            "stress": stress_digit(vowel_phoneme),
            "open": len(codas[i]) == 0,
        })
    return syllables


def map_to_spelling(word, syllables):
    """Walk the spelling left-to-right, consuming characters that correspond
    to each phoneme in order, to recover syllable boundaries in the ORIGINAL
    spelling. Returns (parts: list[str], exact_match: bool)."""
    pos = 0
    spans = []
    for syl in syllables:
        start = pos
        for ph in syl["phonemes"]:
            base = strip_stress(ph)
            candidates = GRAPHEMES.get(base, [base.lower()])
            matched_len, found = 0, False
            for cand in candidates:
                L = len(cand)
                if word[pos:pos + L].lower() == cand:
                    matched_len, found = L, True
                    break
            if not found and pos < len(word):
                matched_len = 1  # unmapped phoneme: consume one char, keep going
            pos += matched_len
        spans.append([start, pos])

    exact_match = pos == len(word)
    if pos < len(word):
        spans[-1][1] = len(word)  # trailing silent letters (e.g. magic e) -> last syllable
        pos = len(word)

    # Repair any empty syllables (grapheme lookup failure) by borrowing a
    # character from a neighboring syllable -- never by merging/dropping one.
    # The displayed split must always have exactly len(syllables) parts: a
    # part count that silently disagrees with the stated syllable count
    # (e.g. a 3-syllable word showing only 2 hyphenated parts) is worse
    # than an imperfect boundary.
    changed, guard = True, 0
    while changed and guard < len(spans) * 2:
        changed = False
        guard += 1
        for i, (s, e) in enumerate(spans):
            if e > s:
                continue
            if i + 1 < len(spans) and spans[i + 1][1] - spans[i + 1][0] > 1:
                spans[i][1] = spans[i][0] + 1
                spans[i + 1][0] += 1
                changed = True
            elif i > 0 and spans[i - 1][1] - spans[i - 1][0] > 1:
                spans[i][0] = spans[i][1] - 1
                spans[i - 1][1] -= 1
                changed = True

    parts = [word[s:e] for s, e in spans]
    exact_match = exact_match and all(e > s for s, e in spans)
    return parts, exact_match


def core_analyze(word, cmu_words):
    """Everything derivable straight from phonemes: count, stress, open/closed,
    ambiguity. Skips the (pricier) phoneme->spelling display-split walk, so
    this is the cheap path for bulk-classifying the full cmudict set (~117k
    words after filtering) when all that's needed is which bucket a word
    falls into. Call analyze() instead when you also need display_split."""
    word = word.lower()
    pronunciations = cmu_words.get(word)
    if not pronunciations:
        return {"word": word, "found": False}

    phonemes, ambiguous, counts_seen = pick_pronunciation(word, pronunciations)
    syllables = syllabify_phonemes(phonemes)
    count = len(syllables)

    stress_pattern = "".join(s["stress"] or "0" for s in syllables)
    primary_idx = next((i for i, s in enumerate(syllables) if s["stress"] == "1"), None)

    note = None
    if ambiguous and word in PREFER_MORE_SYLLABLES:
        other = min(counts_seen)
        note = f"Some speakers say {other} syllable{'s' if other != 1 else ''}, others say {count}."

    return {
        "word": word,
        "found": True,
        "all_pronunciations": pronunciations,
        "chosen_pronunciation": phonemes,
        "ambiguous": ambiguous,
        "note": note,
        "syllable_count": count,
        "syllables_phonemic": [
            {"phonemes": s["phonemes"], "open": s["open"], "stress": s["stress"]}
            for s in syllables
        ],
        "stress_pattern": stress_pattern,
        "primary_stress_syllable_index": primary_idx,
        "open_closed_pattern": ["open" if s["open"] else "closed" for s in syllables],
    }


def analyze(word, cmu_words):
    """core_analyze() plus the display split (word -> spelling walk)."""
    result = core_analyze(word, cmu_words)
    if not result["found"]:
        return result

    word = result["word"]
    if word in CURATED_SPLITS:
        parts, exact_match = CURATED_SPLITS[word], True
    else:
        phonemes = result["chosen_pronunciation"]
        syllables = syllabify_phonemes(phonemes)
        parts, exact_match = map_to_spelling(word, syllables)

    result["display_split"] = parts
    result["display_split_exact"] = exact_match
    return result


def format_report(result):
    if not result["found"]:
        return f"'{result['word']}' -- NOT FOUND in cmudict"

    w = result["word"]
    lines = [f"=== {w} ==="]
    if len(result["all_pronunciations"]) > 1:
        lines.append(f"  cmudict has {len(result['all_pronunciations'])} pronunciations:")
        for p in result["all_pronunciations"]:
            marker = " <- chosen" if p == result["chosen_pronunciation"] else ""
            lines.append(f"    {' '.join(p)}{marker}")
    lines.append(f"  syllable count: {result['syllable_count']}")
    if result["note"]:
        lines.append(f"  note: {result['note']}")
    split_flag = "" if result["display_split_exact"] else "  [~ approximate, unmapped letters folded into a syllable]"
    lines.append(f"  display split: {'-'.join(result['display_split'])}{split_flag}")
    lines.append(f"  stress pattern: {result['stress_pattern']} (1=primary, 2=secondary, 0=unstressed)")
    for i, s in enumerate(result["syllables_phonemic"]):
        marker = "  <- primary stress" if result["primary_stress_syllable_index"] == i else ""
        lines.append(f"    syllable {i+1}: {' '.join(s['phonemes'])}  [{'open' if s['open'] else 'closed'}]{marker}")
    return "\n".join(lines)


if __name__ == "__main__":
    words = sys.argv[1:] or [
        "beautiful", "fire", "every", "poem", "hour",
        "squirrel", "chocolate", "umbrella", "elephant", "family",
        "science", "quiet", "prayer", "caramel", "evening", "our",
    ]
    ensure_data_files()
    cmu_words = load_cmudict()
    print(f"Loaded {len(cmu_words)} distinct words from cmudict.\n")
    for w in words:
        result = analyze(w, cmu_words)
        print(format_report(result))
        print()
