"""
Static site builder for wordsound.online.

Run: python scripts/build.py
Reads:  data/cmudict.dict, data/wordlist.txt
Writes: output/  (list pages, word pages, sitemap.xml, robots.txt, data/words.json,
        and a copy of assets/ so output/ is a fully self-contained deployable folder)

To add words to the per-word-page set: add one word per line to data/wordlist.txt
and re-run this script. No code changes needed.
"""

import json
import re
import shutil
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from parse_cmudict import load_cmudict, load_freq_counts, load_vocab, core_analyze, analyze, CURATED_SPLITS, ensure_data_files

MIN_FREQ_COUNT = 10_000  # ranking-only threshold now; load_vocab() is the real quality filter
WORDS_PER_PAGE = 300
SECTION_PREVIEW = 10  # letter sections longer than this show N, then a "view all" toggle

# Flip to False when the site is ready for search engines. True keeps every
# generated page out of the index while the design/content is still moving.
NOINDEX = False

ICONS = {
    "search": '<svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "heart": '<svg class="icon" viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.2C.5 8.2 2.6 5 6 5c2 0 3.5 1.1 6 3.4C14.5 6.1 16 5 18 5c3.4 0 5.5 3.2 4 6.8-2.5 4.6-10 9.2-10 9.2z"/></svg>',
    "copy": '<svg class="icon" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="1.5"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
    "download": '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3v12m0 0-4-4m4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>',
    "print": '<svg class="icon" viewBox="0 0 24 24"><path d="M6 9V3h12v6"/><rect x="4" y="9" width="16" height="8" rx="1"/><path d="M6 17v4h12v-4"/></svg>',
    "moon": '<svg class="icon" viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg>',
    "teacher": '<svg class="icon" viewBox="0 0 24 24"><path d="M2 9l10-5 10 5-10 5L2 9z"/><path d="M6 11.5V17c0 1.5 2.5 3 6 3s6-1.5 6-3v-5.5"/></svg>',
    "parent": '<svg class="icon" viewBox="0 0 24 24"><circle cx="8" cy="7" r="3"/><circle cx="17" cy="8" r="2.3"/><path d="M2 21v-2a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v2"/><path d="M15 13a4 4 0 0 1 4 4v1"/></svg>',
    "poet": '<svg class="icon" viewBox="0 0 24 24"><path d="M20 4c-5 0-11 4-13 12l-2 4 4-2C17 16 20 10 20 4z"/><path d="M9 15 4 20"/></svg>',
    "gift": '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="9" width="18" height="12" rx="1"/><path d="M3 13h18"/><path d="M12 9v12"/><path d="M12 9C9 9 7 7.5 7 5.5A2.5 2.5 0 0 1 12 5a2.5 2.5 0 0 1 5 .5C17 7.5 15 9 12 9z"/></svg>',
    "book": '<svg class="icon" viewBox="0 0 24 24"><path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H12v18H5.5A1.5 1.5 0 0 1 4 19.5v-15z"/><path d="M20 4.5A1.5 1.5 0 0 0 18.5 3H12v18h6.5a1.5 1.5 0 0 0 1.5-1.5v-15z"/></svg>',
    "bolt": '<svg class="icon" viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/></svg>',
}

# Two earlier approaches to word-list quality didn't hold up, in order:
#  1. Heuristics on cmudict's raw ~126k entries (length, apostrophes, an
#     acronym-pronunciation detector) caught a lot of junk but not proper
#     nouns -- cmudict ships fully lowercased, so "ohio"/"iago" are
#     indistinguishable from real words by spelling alone.
#  2. A web-frequency corpus (count_1w.txt) as the INCLUSION filter: at
#     high occurrence counts it surfaced e-commerce/directory-site text
#     ("ebay", "isbn", "wikipedia") that a curated stoplist could patch,
#     but scanning the full alphabetical lists (not just the frequency
#     top-40) showed the deeper problem -- personal and place names
#     (aaron, abbott, aachen...) are an unbounded category. Any string
#     that crosses an occurrence threshold gets in; a frequency corpus has
#     no concept of "proper noun" to exclude by.
# The fix: load_vocab() (SCOWL/ESDB, which preserves case -- "Aaron" only
# ever appears capitalized, never "aaron") is the inclusion filter now.
# count_1w.txt (MIN_FREQ_COUNT above) is ranking-only, to power the "most
# common" strip and pick which WORDS_PER_PAGE words to show.

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ASSETS_SRC = ROOT / "assets"
SITE_URL = "https://wordsound.online"
ORDINALS = ["zeroth", "first", "second", "third", "fourth", "fifth", "sixth",
            "seventh", "eighth", "ninth", "tenth"]

FAVICON_SRC = ASSETS_SRC / "images" / "favicon.png"

# Bundled, not loaded from the OS: og-image text has to render identically
# on this machine and on GitHub Actions' Ubuntu runner, which has no
# Georgia and no C:\Windows\Fonts at all. See assets/fonts -- README.md
# has the license (DejaVu, Bitstream Vera + public domain, permissive).
FONT_SERIF = ASSETS_SRC / "fonts" / "DejaVuSerif.ttf"
FONT_SERIF_BOLD = ASSETS_SRC / "fonts" / "DejaVuSerif-Bold.ttf"

# Every page's <head> gets these five lines verbatim -- one shared constant
# so the icon set can't drift out of sync between list pages, word pages,
# the counter, and About, each of which builds its own <head> separately.
FAVICON_HEAD = """<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#14110E">"""

# Same og:image/twitter:image pair on every page -- one shared social-preview
# image site-wide rather than a per-page render.
OG_IMAGE_TAGS = (f'<meta property="og:image" content="{SITE_URL}/og-image.png">\n'
                  f'<meta name="twitter:image" content="{SITE_URL}/og-image.png">')

# CANONICAL STRATEGY: "/2-syllable-words/" and "/two-syllable-words/" (and the
# 3-syllable equivalent) target different keyword variants with the same
# underlying word list. Rather than pick one URL and lose the other keyword,
# both get their own page (unique title + intro copy), but the non-numeral
# variant carries <link rel="canonical"> pointing at the numeral version.
# That captures both search queries while telling Google there's one
# authoritative URL, so link equity consolidates there instead of splitting.
# Per the same logic, the sitemap below lists ONLY canonical URLs -- a
# sitemap entry is effectively "please index this," which contradicts a
# canonical tag pointing elsewhere, so the alias pages are deliberately
# left out of it even though they're real, crawlable, linked pages.
CATEGORIES = [
    {
        "slug": "2-syllable-words", "canonical": "2-syllable-words",
        "title": "2 Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 2,
        "intro": "A filterable list of common two-syllable English words, each shown with "
                 "its syllable split. Built for teachers, parents, and speech-language "
                 "pathologists who need a quick, printable reference.",
        "faq_q": "How many two-syllable words are there?",
        "pull_quote": "Two beats. That's all it takes to build a rhythm.",
    },
    {
        "slug": "two-syllable-words", "canonical": "2-syllable-words",
        "title": "Two Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 2,
        "intro": "Looking for two-syllable words? This list covers common examples with "
                 "their syllable breakdowns, filterable and ready to print or copy.",
        "faq_q": "How many two-syllable words are there?",
        "pull_quote": "Two beats. That's all it takes to build a rhythm.",
    },
    {
        "slug": "3-syllable-words", "canonical": "3-syllable-words",
        "title": "3 Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 3,
        "intro": "A filterable list of common three-syllable English words, each shown "
                 "with its syllable split. Built for teachers, parents, and "
                 "speech-language pathologists who need a quick, printable reference.",
        "faq_q": "How many three-syllable words are there?",
        "pull_quote": "A good word is an exact match for the right rhythm.",
    },
    {
        "slug": "three-syllable-words", "canonical": "3-syllable-words",
        "title": "Three Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 3,
        "intro": "Looking for three-syllable words? This list covers common examples "
                 "with their syllable breakdowns, filterable and ready to print or copy.",
        "faq_q": "How many three-syllable words are there?",
        "pull_quote": "A good word is an exact match for the right rhythm.",
    },
    {
        "slug": "4-syllable-words", "canonical": "4-syllable-words",
        "title": "4 Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 4,
        "intro": "A filterable list of common four-syllable English words, each shown "
                 "with its syllable split.",
        "faq_q": "How many four-syllable words are there?",
        "pull_quote": "Four syllables in, and a word starts to feel like a sentence.",
    },
    {
        "slug": "5-syllable-words", "canonical": "5-syllable-words",
        "title": "5 Syllable Words",
        "predicate": lambda r: r["syllable_count"] == 5,
        "intro": "A filterable list of common five-syllable English words, each shown "
                 "with its syllable split.",
        "faq_q": "How many five-syllable words are there?",
        "pull_quote": "Five syllables is where words start to sound like music.",
    },
    {
        "slug": "multisyllabic-words", "canonical": "multisyllabic-words",
        "title": "Multisyllabic Words",
        "predicate": lambda r: r["syllable_count"] >= 3,
        "intro": "Multisyllabic words are words with three or more syllables. Browse "
                 "common examples with syllable splits, filterable and printable for "
                 "classroom or clinical use.",
        "faq_q": "What is a multisyllabic word?",
        "pull_quote": "Words have rhythm. Break them down and you can hear it.",
    },
    {
        "slug": "open-syllable-words", "canonical": "open-syllable-words",
        "title": "Open Syllable Words",
        "predicate": lambda r: (r["primary_stress_syllable_index"] is not None
                                 and r["open_closed_pattern"][r["primary_stress_syllable_index"]] == "open"),
        "intro": "An open syllable ends in a vowel sound with no consonant after it, "
                 "usually making that vowel long (as in “ba-by”). This list shows "
                 "common words whose stressed syllable is open, for phonics instruction "
                 "and reading practice.",
        "faq_q": "What is an open syllable word?",
        "pull_quote": "An open syllable lets the vowel ring all the way through.",
    },
    {
        "slug": "closed-syllable-words", "canonical": "closed-syllable-words",
        "title": "Closed Syllable Words",
        "predicate": lambda r: (r["primary_stress_syllable_index"] is not None
                                 and r["open_closed_pattern"][r["primary_stress_syllable_index"]] == "closed"),
        "intro": "A closed syllable ends in a consonant sound, which usually makes the "
                 "vowel short (as in “cat” or “nap-kin”). This list shows common words "
                 "whose stressed syllable is closed, for phonics instruction and reading "
                 "practice.",
        "faq_q": "What is a closed syllable word?",
        "pull_quote": "A closed syllable stops short — the consonant shuts the door.",
    },
]

CATEGORY_BY_SLUG = {cat["slug"]: cat for cat in CATEGORIES}

# "MORE WORD LISTS" (sidebar, real cross-page links) and the "Popular Words"
# panel both link out rather than filter in-page. The mockup drew these as
# syllable-count filter buttons on the SAME page, but that would cannibalize
# the dedicated landing pages for those exact keywords (3-syllable-words,
# open-syllable-words, ...) -- two pages competing for the same search
# query instead of one page with real crosslink equity pointing at the other.
MORE_LISTS_SLUGS = ["3-syllable-words", "4-syllable-words", "5-syllable-words",
                     "open-syllable-words", "closed-syllable-words"]
POPULAR_WORDS_SLUGS = ["3-syllable-words", "4-syllable-words", "5-syllable-words", "multisyllabic-words"]

LIST_COPY_PATH = DATA_DIR / "list_copy.json"

# Second h2's wording varies per category ("What makes a word 2-syllable"
# vs "...multisyllabic" vs "...open-syllable") -- not derivable cleanly
# from cat["title"] (which is capitalized for display, e.g. "2 Syllable
# Words"), so spelled out explicitly per slug instead of string-mangled.
WHAT_MAKES_LABEL = {
    "2-syllable-words": "2-syllable", "two-syllable-words": "two-syllable",
    "3-syllable-words": "3-syllable", "three-syllable-words": "three-syllable",
    "4-syllable-words": "4-syllable", "5-syllable-words": "5-syllable",
    "multisyllabic-words": "multisyllabic",
    "open-syllable-words": "open-syllable", "closed-syllable-words": "closed-syllable",
}


def load_list_copy():
    """data/list_copy.json holds the three-subsection prose block (how to
    use / what makes a word this category / commonly-miscounted words) for
    each list page. Fails loudly on a missing slug rather than silently
    rendering that page without its section -- an empty STRING is a valid,
    intentional "nothing to show yet" (see render_list_page's per-
    subsection skip), but a missing KEY means the file itself is out of
    sync with CATEGORIES and that's a build error, not a content choice."""
    data = json.loads(LIST_COPY_PATH.read_text(encoding="utf-8"))
    missing = [cat["slug"] for cat in CATEGORIES if cat["slug"] not in data]
    if missing:
        raise RuntimeError(
            f"data/list_copy.json is missing {len(missing)} categor{'y' if len(missing) == 1 else 'ies'}: "
            f"{', '.join(missing)}. Every slug in CATEGORIES needs an entry (even if its three "
            f"strings are empty) -- add it rather than letting the page render without this section."
        )
    return data


# Words that keep their own /syllables/ page (still real, still in
# wordlist.txt, still linked FROM other pages' sibling rows) but are never
# auto-linked out of list-copy prose. All ten of these are common enough
# as ordinary grammar ("...spoken as three while the dictionary keeps
# four...") that they show up in the copy far more often as connective
# tissue than as a cited example -- a plain conjunction turning into a
# blue link reads as a bug to a reader, not a feature. Excluding them here
# doesn't touch autolink_prose's general logic (still first-mention-only,
# still capped at 4) -- it just shrinks the candidate pool it draws from.
AUTOLINK_STOPLIST = {"while", "about", "our", "every", "very", "many", "different", "time", "love"}


def autolink_prose(texts, linkable_words, max_links=4):
    """texts: ordered list of raw (unescaped) prose strings, in the order
    they'll appear on the page. Returns the same-length list, HTML-escaped,
    with each linkable word's FIRST mention across the WHOLE list (not per
    string) turned into a link to its /syllables/[word]/ page -- capped at
    max_links total. No hand-written anchors in the source JSON; this is
    the only place word pages get linked from prose. AUTOLINK_STOPLIST is
    applied here, not upstream, so it only ever affects prose auto-linking
    -- word pages themselves and their sibling cross-links are untouched."""
    linkable_words = [w for w in linkable_words if w not in AUTOLINK_STOPLIST]
    if not linkable_words:
        return [escape(t) for t in texts]

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in sorted(linkable_words, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    linked_words = set()
    link_count = 0

    def linkify(escaped_text):
        nonlocal link_count

        def repl(m):
            nonlocal link_count
            matched = m.group(0)
            key = matched.lower()
            if key in linked_words or link_count >= max_links:
                return matched
            linked_words.add(key)
            link_count += 1
            return f'<a href="/syllables/{key}/">{matched}</a>'

        return pattern.sub(repl, escaped_text)

    return [linkify(escape(t)) for t in texts]


def list_page_js(slug):
    # Inline (not an external file) per spec, so every page is self-contained
    # with no extra request. Handles search/filter, letter-jump smooth scroll
    # w/ sticky-bar offset, section expand, favorites (localStorage), copy
    # (list + single word), download, and the dark-mode toggle.
    return f"""
(function () {{
  "use strict";
  var THEME_KEY = "wordsound_theme";
  var FAV_KEY = "wordsound_favorites";

  function getFavorites() {{
    try {{ return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); }} catch (e) {{ return []; }}
  }}
  function setFavorites(list) {{
    try {{ localStorage.setItem(FAV_KEY, JSON.stringify(list)); }} catch (e) {{}}
  }}
  function updateFavPill() {{
    var el = document.getElementById("fav-count");
    if (el) el.textContent = getFavorites().length;
  }}
  function toggleFavorite(word, btn) {{
    var favs = getFavorites();
    var i = favs.indexOf(word);
    if (i === -1) {{ favs.push(word); btn.classList.add("fav-active"); }}
    else {{ favs.splice(i, 1); btn.classList.remove("fav-active"); }}
    setFavorites(favs);
    updateFavPill();
  }}
  (function initFavs() {{
    var favs = getFavorites();
    document.querySelectorAll(".wr .f").forEach(function (btn) {{
      var word = btn.closest(".wr").querySelector(".w").textContent;
      if (favs.indexOf(word) !== -1) btn.classList.add("fav-active");
    }});
    updateFavPill();
  }})();

  // No form on the page -- set once here instead of type="button" on
  // every row's two buttons (repeated 1,000x/page otherwise).
  document.querySelectorAll(".wr button").forEach(function (b) {{ b.type = "button"; }});

  function copyText(text) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(text);
    }} else {{
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try {{ document.execCommand("copy"); }} catch (e) {{}}
      document.body.removeChild(ta);
    }}
  }}

  // Word/split/count aren't stored in data-* attributes -- they're just the
  // row's own visible text, read at event time via .w/.s/.c.
  document.addEventListener("click", function (e) {{
    var favBtn = e.target.closest(".wr .f");
    if (favBtn) {{
      var word = favBtn.closest(".wr").querySelector(".w").textContent;
      toggleFavorite(word, favBtn);
      return;
    }}

    var copyBtn = e.target.closest(".wr .cp");
    if (copyBtn) {{
      var row = copyBtn.closest(".wr");
      copyText(row.querySelector(".w").textContent + " \\u2014 " + row.querySelector(".s").textContent +
                " (" + row.querySelector(".c").textContent + " syllables)");
      return;
    }}

    var viewAll = e.target.closest(".view-all-btn");
    if (viewAll) {{
      var section = viewAll.closest(".letter-section");
      // Removing "extra" (not just unhiding) is what makes this permanent:
      // applySearch()'s empty-query branch below treats "still carries
      // .extra" as "still collapsed," so a row that keeps the class would
      // silently re-collapse the next time the search box is cleared.
      section.querySelectorAll(".wr.extra").forEach(function (r) {{ r.classList.remove("extra"); r.hidden = false; }});
      viewAll.remove();
      return;
    }}
  }});

  var searchInput = document.getElementById("search-input");
  var sections = Array.prototype.slice.call(document.querySelectorAll(".letter-section"));
  var noResults = document.getElementById("no-results");

  function applySearch() {{
    // "extra" already marks exactly the rows collapsed by the
    // section-preview limit (unrelated to search) -- reusing it here
    // instead of a second class keeps one source of truth for "is this
    // row supposed to be collapsed right now."
    var q = (searchInput.value || "").trim().toLowerCase();
    var anyVisible = false;
    sections.forEach(function (section) {{
      var rows = section.querySelectorAll(".wr");
      var visible = 0;
      rows.forEach(function (row) {{
        var hide;
        if (q) {{
          // A non-empty query reaches into collapsed rows too -- a match
          // should surface even if its row started out behind "View all."
          hide = row.querySelector(".w").textContent.toLowerCase().indexOf(q) === -1;
        }} else {{
          // Clearing the box restores each row to its PRE-search state
          // instead of unconditionally revealing it. Previously this branch
          // set hidden=false for every row unconditionally, which silently
          // and permanently un-collapsed every "View all" section on the
          // page the first time anyone cleared the search box.
          hide = row.classList.contains("extra");
        }}
        row.hidden = hide;
        if (!hide) visible++;
      }});
      // The section's word-count label reflects its TRUE total once the
      // query is cleared (matching the page's initial server-rendered
      // text), not just the currently-un-collapsed count -- "visible"
      // alone would undercount by however many rows are still behind
      // "View all."
      var shown = q ? visible : rows.length;
      if (shown > 0) anyVisible = true;
      section.hidden = q ? visible === 0 : false;
      var countEl = section.querySelector(".letter-count");
      var rangeEl = section.querySelector(".letter-range");
      if (countEl) countEl.textContent = "\\u2014 " + shown + (shown === 1 ? " word \\u2014" : " words \\u2014");
      if (rangeEl) rangeEl.textContent = q ? (visible + " match" + (visible === 1 ? "" : "es"))
                                           : rangeEl.getAttribute("data-original");
    }});
    if (noResults) noResults.classList.toggle("show", !anyVisible);
  }}
  if (searchInput) searchInput.addEventListener("input", applySearch);

  function visibleWords() {{
    return Array.prototype.slice.call(document.querySelectorAll(".wr"))
      .filter(function (r) {{ return !r.hidden && !r.closest(".letter-section").hidden; }})
      .map(function (r) {{ return r.querySelector(".w").textContent; }});
  }}

  var copyListBtn = document.getElementById("copy-list-btn");
  if (copyListBtn) copyListBtn.addEventListener("click", function () {{ copyText(visibleWords().join("\\n")); }});

  var downloadBtn = document.getElementById("download-btn");
  if (downloadBtn) downloadBtn.addEventListener("click", function () {{
    var blob = new Blob([visibleWords().join("\\n") + "\\n"], {{ type: "text/plain" }});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = "{slug}-wordsound.txt";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }});

  var printBtn = document.getElementById("print-btn");
  if (printBtn) printBtn.addEventListener("click", function () {{
    // Same class removal as "View all" above, for the same reason: leaving
    // "extra" in place would let a later search-clear silently re-collapse
    // rows this button just permanently revealed for print.
    document.querySelectorAll(".wr.extra").forEach(function (r) {{ r.classList.remove("extra"); r.hidden = false; }});
    document.querySelectorAll(".view-all-btn").forEach(function (b) {{ b.remove(); }});
    window.print();
  }});

  document.querySelectorAll(".letter-btn[href^='#']").forEach(function (btn) {{
    btn.addEventListener("click", function (e) {{
      var target = document.querySelector(btn.getAttribute("href"));
      if (!target) return;
      e.preventDefault();
      var bar = document.querySelector(".action-bar");
      var offset = (bar ? bar.offsetHeight : 0) + 12;
      var top = target.getBoundingClientRect().top + window.pageYOffset - offset;
      window.scrollTo({{ top: top, behavior: "smooth" }});
    }});
  }});

  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {{
    var current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {{ localStorage.setItem(THEME_KEY, next); }} catch (e) {{}}
  }});
}})();
"""


def write_page(slug, html):
    out_dir = OUTPUT_DIR if slug == "" else OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def count_label(n):
    return f"{n:,}"


def build_word_pool(cmu_words, vocab, freq_counts):
    """cmudict words that are (a) real dictionary vocabulary per SCOWL, and
    (b) at or above MIN_FREQ_COUNT in Google Books usage -- core-analyzed
    once, sorted most-frequent-first. See the module-level comment above
    for why vocab membership (not frequency) is the inclusion filter."""
    pool = []
    for word in vocab:
        if len(word) < 3 or not word.isalpha() or word not in cmu_words:
            continue
        count = freq_counts.get(word, 0)
        if count < MIN_FREQ_COUNT:
            continue
        result = core_analyze(word, cmu_words)
        if result["found"]:
            pool.append((word, result, count))
    pool.sort(key=lambda t: -t[2])
    print(f"  {len(pool):,} words: in dictionary vocab AND freq_count >= {MIN_FREQ_COUNT:,}")
    return [(w, r) for w, r, _count in pool]


def compute_category_data(cmu_words, pool, word_page_set):
    """One pass over every category, up front, so cross-linking widgets
    (MORE WORD LISTS, POPULAR WORDS) can quote other pages' real shown
    counts while rendering the current one. `pool` is already sorted
    most-frequent-first."""
    data = {}
    for cat in CATEGORIES:
        matches_all = [(w, r) for w, r in pool if cat["predicate"](r)]
        total_qualifying = len(matches_all)
        capped = matches_all[:WORDS_PER_PAGE]  # still freq-desc here

        top_common = []
        for word, r in capped[:30]:
            full = analyze(word, cmu_words)
            top_common.append({"word": word, "split": full["display_split"], "has_page": word in word_page_set})

        shown = []
        for word, r in sorted(capped, key=lambda pair: pair[0]):
            full = analyze(word, cmu_words)
            shown.append({
                "word": word, "split": full["display_split"],
                "count": r["syllable_count"], "has_page": word in word_page_set,
            })

        data[cat["slug"]] = {
            "shown": shown, "shown_n": len(capped),
            "total_qualifying": total_qualifying, "top_common": top_common,
        }
    return data


def word_row_inner(word, split, count, has_page):
    """The guts of one .wr row -- word/split/count/favorite/copy -- shared
    verbatim by list pages and the word-page sibling cross-links so both
    surfaces render byte-identical markup off one definition instead of
    two copies drifting apart."""
    split_dot = " &middot; ".join(escape(p) for p in split)
    word_el = (f'<a class=w href="/syllables/{word}/">{word}</a>'
               if has_page else f'<span class=w>{word}</span>')
    return (f'{word_el}<span class=s>{split_dot}</span><span class=c>{count}</span>'
            f'<button class=f aria-label="Favorite"><svg class=i aria-hidden="true"><use href="#i-heart"/></svg></button>'
            f'<button class=cp aria-label="Copy"><svg class=i aria-hidden="true"><use href="#i-copy"/></svg></button>')


def render_list_copy_block(cat, list_copy, linkable_words):
    """The three-subsection prose block (how to use / what makes a word
    this category / commonly-miscounted words), auto-linked against word
    pages. Returns "" (no wrapping container at all) when every subsection
    is empty -- an empty .list-copy shell would be exactly the kind of
    empty-container problem already ruled out elsewhere on these pages.

    A blank line (\\n\\n) inside one subsection's string is a paragraph
    break -- e.g. open/closed-syllable-words' "what_makes" holds two
    distinct paragraphs. Splitting on it before wrapping each piece in its
    own <p> matters: a literal "\\n\\n" left inside one <p> just collapses
    to whitespace in HTML, silently merging two paragraphs into one
    run-on block instead of rendering the break the source data intends."""
    entry = list_copy[cat["slug"]]
    raw = [entry["how_to_use"], entry["what_makes"], entry["tricky_cases"]]
    if not any(t.strip() for t in raw):
        return ""

    # Flatten to one paragraph per list entry for autolink_prose (so "first
    # mention" and the 4-link cap still apply across the WHOLE page, not
    # per paragraph), then regroup back under each subsection's heading.
    para_groups = [[p for p in t.split("\n\n") if p.strip()] for t in raw]
    flat_paras = [p for group in para_groups for p in group]
    linked_flat = autolink_prose(flat_paras, linkable_words)
    linked_groups = []
    i = 0
    for group in para_groups:
        linked_groups.append(linked_flat[i:i + len(group)])
        i += len(group)

    headings = [
        "How to use this list",
        f"What makes a word {WHAT_MAKES_LABEL[cat['slug']]}",
        "Words people commonly miscount",
    ]
    sections = "".join(
        f"<h2>{h}</h2>\n" + "".join(f"<p>{p}</p>\n" for p in paras)
        for h, paras in zip(headings, linked_groups)
        if paras
    )
    return f'<div class="list-copy">{sections}</div>'


def render_list_page(cat, cat_data, all_data, build_year, list_copy, linkable_words):
    shown = cat_data["shown"]
    shown_n = cat_data["shown_n"]
    total_qualifying = cat_data["total_qualifying"]
    h1_main, h1_accent = cat["title"].rsplit(" ", 1)
    # Instructed wording was "use search to find any word in this category" --
    # not accurate: search only filters the shown_n rows actually in the DOM,
    # it can't reach words outside that set. Using an honest claim instead.
    truncation_note = (
        f'<p class="muted-note">Showing the {shown_n:,} most common of {total_qualifying:,} '
        f'words in this category.</p>'
        if shown_n < total_qualifying else ""
    )

    # ---- letter sections (alphabetical; `shown` is already sorted) ----
    letters_present = []
    for item in shown:
        L = item["word"][0].upper()
        if not letters_present or letters_present[-1][0] != L:
            letters_present.append((L, []))
        letters_present[-1][1].append(item)

    sections_html = []
    for idx, (letter, items) in enumerate(letters_present):
        rows_html = []
        for i, item in enumerate(items):
            is_extra = i >= SECTION_PREVIEW
            div_open = '<div class="wr extra" hidden>' if is_extra else "<div class=wr>"
            # No data-word/data-split/data-count: those values are just the
            # row's own text content, recovered by JS at event time instead
            # of stored a second (and third) time -- that, not class-name
            # length, was the real per-row weight at 500x multiplication.
            # Buttons keep a short generic aria-label ("Favorite"/"Copy") and
            # the decorative svg gets aria-hidden, rather than aria-hidden on
            # the button itself (a real WCAG/axe violation: a keyboard stop
            # with no accessible name, not just "unlabeled") -- unchanged
            # per instruction to keep all accessibility attributes.
            # Single line, no indentation, unquoted single-token class
            # values ("wr extra" stays quoted -- it's two tokens): this is
            # the one place in the page deliberately minified, since it's
            # the one markup repeated hundreds of times per page.
            rows_html.append(
                f'{div_open}{word_row_inner(item["word"], item["split"], item["count"], item["has_page"])}</div>'
            )

        view_all = (f'<button class="view-all-btn" type="button">View all words starting with {letter} &#8964;</button>'
                    if len(items) > SECTION_PREVIEW else "")
        pull_quote_html = (f'<p class="pull-quote">&ldquo;{escape(cat["pull_quote"])}&rdquo;</p>' if idx == 0 else "")
        n = len(items)
        sections_html.append(f"""<section class="letter-section" id="letter-{letter}">
  <div class="letter-head">
    <span class="letter">{letter}</span>
    <span class="letter-count">&mdash; {n} word{"s" if n != 1 else ""} &mdash;</span>
    <span class="letter-range" data-original="1 &ndash; {n} of {n}">1 &ndash; {n} of {n}</span>
  </div>
  {pull_quote_html}
  {"".join(rows_html)}
  {view_all}
</section>""")

    # ---- sidebar: letter grid ----
    present_letters = {L for L, _ in letters_present}
    letter_btns = ['<span class="letter-btn disabled">#</span>']
    for L in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if L in present_letters:
            letter_btns.append(f'<a class="letter-btn" href="#letter-{L}">{L}</a>')
        else:
            letter_btns.append(f'<span class="letter-btn disabled">{L}</span>')

    more_lists_html = "".join(
        f'<li><a href="/{slug}/">{CATEGORY_BY_SLUG[slug]["title"]}</a></li>'
        for slug in MORE_LISTS_SLUGS if slug != cat["canonical"]
    )
    popular_html = "".join(
        f'<a class="popular-row" href="/{slug}/"><span class="lbl">{CATEGORY_BY_SLUG[slug]["title"]}</span>'
        f'<span class="n num">{all_data[slug]["shown_n"]:,}</span></a>'
        for slug in POPULAR_WORDS_SLUGS if slug != cat["canonical"]
    )

    # ---- head / meta ----
    title = f"{cat['title']} | WordSound"
    # Kept under 155 chars (measured on the unescaped string -- an HTML
    # entity like &#x27; would otherwise inflate a raw-source char count
    # without inflating what's actually displayed) with the keyword in the
    # first 60 chars. The original wording ran 173-178 chars across these
    # 9 pages; trimmed from the end rather than the front, which is where
    # the keyword and word count live.
    meta_desc = (f"Browse {count_label(shown_n)} common {cat['title'].lower()}, ranked by "
                 f"frequency. Filterable, printable list with syllable splits and stress patterns.")
    canonical_path = f"/{cat['canonical']}/"
    canonical_url = SITE_URL + canonical_path

    faq_ld = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question", "name": cat["faq_q"],
            "acceptedAnswer": {"@type": "Answer", "text":
                f"There are {total_qualifying:,} common words matching this category in our "
                f"dictionary; this page shows the {shown_n:,} most frequent, listed alphabetically "
                f"with the very top ones highlighted separately."},
        }],
    }
    # No ItemList JSON-LD here: 500 ListItem entries cost ~29KB and Google
    # doesn't generate rich results from an ItemList of plain words. FAQPage
    # (below) is the schema that actually earns something.
    robots_meta = '<meta name="robots" content="noindex, nofollow">\n' if NOINDEX else ""

    badges = [
        ("teacher", "Teacher Friendly", "Perfect for lesson plans &amp; worksheets"),
        ("parent", "Parent Approved", "Ideal for homework &amp; spelling practice"),
        ("poet", "Poet Loved", "Find the perfect words for your rhythm"),
    ]
    badges_html = "".join(
        f'<div class="badge">{ICONS[icon]}<span><strong>{label}</strong><span>{desc}</span></span></div>'
        for icon, label, desc in badges
    )

    trust_items = [
        ("gift", "100% Free", "No sign up required. Always will be."),
        ("print", "Print Ready", "Clean layout built for worksheets."),
        ("book", "Built on CMUdict", "Carnegie Mellon's 134,000-word dictionary."),
        ("bolt", "Fast &amp; Lightweight", "No trackers, no bloat."),
    ]
    trust_html = "".join(
        f'<div class="trust-item">{ICONS[icon]}<span><strong>{label}</strong><span>{desc}</span></span></div>'
        for icon, label, desc in trust_items
    )

    html = f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{FAVICON_HEAD}
<title>{escape(title)}</title>
<meta name="description" content="{escape(meta_desc)}">
{robots_meta}<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{escape(cat['title'])}">
<meta property="og:description" content="{escape(meta_desc)}">
<meta property="og:url" content="{canonical_url}">
{OG_IMAGE_TAGS}
<meta property="og:type" content="website">
<link rel="stylesheet" href="/assets/css/list.css">
<script>try{{var t=localStorage.getItem("wordsound_theme");if(t)document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}</script>
<script type="application/ld+json">{json.dumps(faq_ld)}</script>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.2C.5 8.2 2.6 5 6 5c2 0 3.5 1.1 6 3.4C14.5 6.1 16 5 18 5c3.4 0 5.5 3.2 4 6.8-2.5 4.6-10 9.2-10 9.2z"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="1.5"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></symbol>
</svg>
<header class="ws-header"><div class="wrap">
  <a class="wordmark" href="/"><span class="line1">WORD SOUND</span><span class="line2">&middot; Online &middot;</span></a>
  <nav class="ws-nav">
    <a href="/">Syllable Counter</a>
    <a href="/2-syllable-words/" class="active">Word Lists</a>
    <a href="/about/">About</a>
  </nav>
  <div class="header-actions">
    <span class="fav-pill"><svg class="ico"><use href="#i-heart"/></svg> <span id="fav-count">0</span><span class="fav-label"> Favorites</span></span>
    <button class="theme-toggle" id="theme-toggle" type="button" aria-label="Toggle dark mode">{ICONS['moon']}</button>
  </div>
</div></header>

<section class="hero"><div class="wrap">
  <div class="hero-copy">
    <p class="eyebrow">Words have rhythm.</p>
    <h1 class="page-title">{h1_main}<span class="accent">{h1_accent}</span></h1>
    <p class="hero-intro">{cat['intro']}</p>
    <div class="badges">{badges_html}</div>
  </div>
  <div class="hero-art">
    <img src="/assets/images/01_hero_A_feather_ink.png" width="355" height="385" loading="eager" alt="">
  </div>
  <div class="stats-rail">
    <div class="big num">{count_label(shown_n)}+</div><div class="lbl">WORDS SHOWN</div>
    <div class="big num">{total_qualifying:,}</div><div class="lbl">IN OUR DICTIONARY</div>
    <p class="tagline">Sound it. Break it. Use it.</p>
  </div>
</div></section>

<div class="action-bar"><div class="wrap">
  <div class="search-wrap">{ICONS['search']}<input id="search-input" type="text" placeholder="Search for a word..."></div>
  <button class="ab-btn" id="copy-list-btn" type="button"><svg class="ico"><use href="#i-copy"/></svg><span class="label">Copy List</span></button>
  <button class="ab-btn" id="download-btn" type="button">{ICONS['download']}<span class="label">Download</span></button>
  <button class="ab-btn filled" id="print-btn" type="button">{ICONS['print']}<span class="label">Print List</span></button>
</div></div>

<div class="wrap">
<div class="print-header">
  <h1>{cat['title']}</h1>
  <p>{shown_n:,} words &middot; syllable splits included</p>
</div>
<div class="body-grid">
  <aside class="sidebar">
    <p class="sb-label">Browse Words</p>
    <p class="sb-sub">Jump to a letter</p>
    <div class="letter-grid">{"".join(letter_btns)}</div>
    <div class="sb-block more-lists">
      <p class="sb-label">More Word Lists</p>
      <ul class="sb-links">{more_lists_html}</ul>
    </div>
    <div class="sb-block">
      <p class="sb-label">Popular Words</p>
      <p class="sb-sub">Most common by category</p>
      {popular_html}
      <a class="explore-link" href="/{POPULAR_WORDS_SLUGS[0]}/">Explore Now &rarr;</a>
    </div>
  </aside>
  <div class="main-col">
    <div class="word-list-cols">{"".join(sections_html)}</div>
    <p class="no-results" id="no-results">No words match your search.</p>
    {truncation_note}
    {render_list_copy_block(cat, list_copy, linkable_words)}
  </div>
</div>
</div>

<section class="cross-promo"><div class="wrap">
  <div>
    <h2>Find the perfect rhythm for your next line.</h2>
    <p>Use our Syllable Counter to check any word or phrase and build beautiful lines.</p>
    <a class="ab-btn filled" href="/">Try Syllable Counter &rarr;</a>
  </div>
  <div class="promo-art">
    <img src="/assets/images/05_cta_pen_paint_abstract.png" width="230" height="125" loading="lazy" alt="">
    <p class="promo-example">cre &middot; a &middot; tiv &middot; i &middot; ty &mdash; <span class="n">5 syllables</span></p>
  </div>
</div></section>

<section class="trust-bar"><div class="wrap">{trust_html}</div></section>

<footer class="ws-footer"><div class="wrap">
  <div class="footer-grid">
    <div>
      <a class="wordmark" href="/" style="color:var(--ink)"><span class="line1">WORD SOUND</span><span class="line2">&middot; Online &middot;</span></a>
      <p class="footer-tagline">Tools for writers, teachers, parents, and word lovers.</p>
    </div>
    <div><h3>Tools</h3><ul><li><a href="/">Syllable Counter</a></li><li><a href="/2-syllable-words/">Word Lists</a></li></ul></div>
    <div><h3>Help</h3><ul><li><a href="/about/">How It Works</a></li><li><a href="/about/">About</a></li></ul></div>
    <div><h3>Data</h3><p class="footer-tagline">Built on CMUdict, Carnegie Mellon's pronunciation dictionary.</p></div>
  </div>
  <div class="footer-bottom">&copy; {build_year} wordsound.online</div>
</div></footer>

<script>{list_page_js(cat['slug'])}</script>
</body>
</html>"""
    return html


def build_list_pages(cmu_words, all_data, build_year, list_copy, wordlist):
    # WORDS_PER_PAGE: with the 10k-word frequency list this was expected to be a
    # no-op (each category landing well under 1,000 words anyway), but
    # count_1w.txt's much larger pool (57k qualifying words total, 25k for
    # 2-syllable alone) broke that assumption -- uncapped, /2-syllable-words/
    # rendered a 2.8MB page. Capping at the top 500 by frequency keeps page
    # weight sane while still always showing the most useful words first.
    for cat in CATEGORIES:
        cat_data = all_data[cat["slug"]]
        html = render_list_page(cat, cat_data, all_data, build_year, list_copy, wordlist)
        write_page(cat["slug"], html)
        weight_kb = len(html.encode("utf-8")) / 1024
        flag = "  [!] over 150KB budget" if weight_kb > 150 else ""
        print(f"  /{cat['slug']}/  -> {cat_data['shown_n']:,} shown of {cat_data['total_qualifying']:,} qualifying, "
              f"{weight_kb:.1f} KB{flag}"
              + (f"  [canonical: /{cat['canonical']}/]" if cat["slug"] != cat["canonical"] else ""))


def list_link_for_count(count):
    if count in (2, 3, 4, 5):
        return f'<a href="/{count}-syllable-words/">See all {count}-syllable words &rarr;</a>'
    if count >= 6:
        return '<a href="/multisyllabic-words/">See all multisyllabic words &rarr;</a>'
    return ""  # no 1-syllable-words list page exists


# One or two sentences on why a word is commonly miscounted. Written ONLY for
# these 11 -- everything else omits the section entirely rather than
# stretching for content that isn't genuinely tricky. Each note is checked
# against this build's actual output (syllable count, split, ambiguous flag)
# rather than folk etymology, so it never contradicts the answer card above
# it -- e.g. "chocolate" and "squirrel" render 2 syllables here (one cmudict
# pronunciation each), so their notes explain the 2-vs-what-people-expect
# gap, not a fictitious 3-syllable "full form" this site doesn't use.
TRICKY_NOTES = {
    "fire": "Fire is often said as a single syllable in casual speech, but its "
            "full two-syllable pronunciation is the one most dictionaries -- and this site -- count.",
    "hour": "The silent h hides two real vowel sounds. That's why ‘hour’ "
            "is commonly miscounted as one syllable instead of two.",
    "every": "Casual speech often compresses ‘every’ to two syllables "
             "(‘ev-ry’). This site counts its full three-syllable form instead.",
    "poem": "Poem looks like it should rhyme with ‘foam’ as one syllable, but "
            "the two vowel sounds stay separate — it's two syllables, not one.",
    "our": "Like ‘hour’, ‘our’ is frequently reduced to one syllable in "
           "fast speech, but its full pronunciation carries two vowel sounds.",
    "science": "The ‘ie’ in ‘science’ looks like a single vowel sound, "
               "but it spans two syllables, not one.",
    "quiet": "The ‘ie’ in ‘quiet’ splits into two separate vowel sounds, "
             "unlike in a word like ‘pie’ where it's one — easy to undercount.",
    "everything": "It's tempting to spell out four syllables by ear (‘ev-er-y-thing’), "
                  "but the standard pronunciation compresses the middle, giving three.",
    "chocolate": "Chocolate looks like three syllables from its spelling "
                 "(‘choc-o-late’), but the standard pronunciation drops a vowel, giving two.",
    "family": "Family is often said with two syllables in casual speech "
              "(‘fam-ly’), but its full three-syllable pronunciation is the standard count.",
    "squirrel": "Squirrel is one of the most-argued syllable counts in English. "
                "Some speakers hear one beat; the standard pronunciation has two.",
}


def word_page_js():
    # Trimmed relative to list_page_js: word pages have no search bar, no
    # view-all toggle, no download/print buttons to wire up -- just the
    # favorites + copy behavior for the sibling .wr rows, and the same
    # dark-mode toggle every page carries.
    return """
(function () {
  "use strict";
  var THEME_KEY = "wordsound_theme";
  var FAV_KEY = "wordsound_favorites";

  function getFavorites() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); } catch (e) { return []; }
  }
  function setFavorites(list) {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(list)); } catch (e) {}
  }
  function updateFavPill() {
    var el = document.getElementById("fav-count");
    if (el) el.textContent = getFavorites().length;
  }
  function toggleFavorite(word, btn) {
    var favs = getFavorites();
    var i = favs.indexOf(word);
    if (i === -1) { favs.push(word); btn.classList.add("fav-active"); }
    else { favs.splice(i, 1); btn.classList.remove("fav-active"); }
    setFavorites(favs);
    updateFavPill();
  }
  (function initFavs() {
    var favs = getFavorites();
    document.querySelectorAll(".wr .f").forEach(function (btn) {
      var word = btn.closest(".wr").querySelector(".w").textContent;
      if (favs.indexOf(word) !== -1) btn.classList.add("fav-active");
    });
    updateFavPill();
  })();

  document.querySelectorAll(".wr button").forEach(function (b) { b.type = "button"; });

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text);
    } else {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  document.addEventListener("click", function (e) {
    var favBtn = e.target.closest(".wr .f");
    if (favBtn) {
      var word = favBtn.closest(".wr").querySelector(".w").textContent;
      toggleFavorite(word, favBtn);
      return;
    }
    var copyBtn = e.target.closest(".wr .cp");
    if (copyBtn) {
      var row = copyBtn.closest(".wr");
      copyText(row.querySelector(".w").textContent + " \\u2014 " + row.querySelector(".s").textContent +
                " (" + row.querySelector(".c").textContent + " syllables)");
      return;
    }
  });

  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  });
})();
"""


def render_word_page(word, r, siblings, build_year):
    count = r["syllable_count"]
    split = r["display_split"]
    plural = "s" if count != 1 else ""
    display_word = word.capitalize()
    stress_idx = r["primary_stress_syllable_index"]
    ordinal = ORDINALS[stress_idx + 1] if stress_idx is not None and stress_idx + 1 < len(ORDINALS) else None
    split_hyphen = "-".join(split)

    # ---- syllable columns: split text + scansion mark share one column
    # each, so the mark sits directly under ITS syllable regardless of how
    # wide neighboring syllables render -- a plain two-line block ("beau *
    # ti * ful" over "¯ ˘ ˘") only lines up by accident once
    # syllable widths differ. The interpunct dot gets its own column with a
    # blank (non-breaking-space) mark row so it doesn't inherit a stress
    # glyph that isn't real.
    cols = []
    for i, part in enumerate(split):
        stress_char = r["stress_pattern"][i] if i < len(r["stress_pattern"]) else "0"
        mark_cls, mark_glyph = ("u", "˘") if stress_char == "0" else ("s", "¯")
        cols.append(f'<div class="syl-col"><span class="syl-txt">{escape(part)}</span>'
                    f'<span class="syl-mark {mark_cls}">{mark_glyph}</span></div>')
        if i < len(split) - 1:
            cols.append('<div class="syl-col syl-dot"><span class="syl-txt">&middot;</span>'
                        '<span class="syl-mark">&nbsp;</span></div>')
    syllables_html = "".join(cols)

    tags_html = "".join(f'<span class="tag {oc}">[{oc}]</span>' for oc in r["open_closed_pattern"])
    stress_line = f"Primary stress on the {ordinal} syllable" if ordinal else ""

    # Ambiguity callout requires BOTH ambiguous=true and a stored note --
    # cmudict marks some words ambiguous (e.g. "family", 2 vs 3 syllables
    # across its two listed pronunciations) without this site having a
    # curated explanation for which form it picked (that only exists for
    # the PREFER_MORE_SYLLABLES set). Showing a headline-only callout with
    # no note text would be the empty-container problem the spec rules out,
    # just moved one level down -- so the callout only renders when there's
    # real content to put in it.
    ambiguous_block = ""
    if r["ambiguous"] and r["note"]:
        ambiguous_block = f'<div class="callout">{escape(r["note"])}</div>'

    approximate = not r["display_split_exact"]
    approx_block = ('<p class="muted-note">This syllable split is approximate.</p>'
                     if approximate else "")

    tricky_note = TRICKY_NOTES.get(word)
    tricky_block = f'<div class="tricky-note"><h2>Why this word trips people up</h2><p>{escape(tricky_note)}</p></div>' if tricky_note else ""

    list_link = list_link_for_count(count)
    list_link_block = f'<p class="see-all-link">{list_link}</p>' if list_link else ""
    # Each row shows the SIBLING's own count, not the current word's --
    # a fallback sibling (see build_word_pages) can have a different count,
    # and reusing `count` here would print a fabricated number for it.
    siblings_html = "".join(
        f'<div class=wr>{word_row_inner(w, sr["display_split"], sr["syllable_count"], True)}</div>'
        for w, sr in siblings
    )
    all_same_count = all(sr["syllable_count"] == count for _w, sr in siblings)
    siblings_heading = f"More {count}-syllable words" if all_same_count else "More words like this"

    crosslinks = f"""
<section class="crosslinks">
  {list_link_block}
  <h2>{siblings_heading}</h2>
  <div class="sibling-rows">{siblings_html}</div>
  <p class="cta-link"><a href="/syllable-counter/">Count syllables in your own text &rarr;</a></p>
</section>
"""

    title = f"How Many Syllables in {display_word}? | WordSound"
    stress_sentence = f" Primary stress on the {ordinal} syllable." if ordinal else ""
    answer_sentence = f"{display_word} has {count} syllable{plural}: {split_hyphen}.{stress_sentence}"
    meta_desc = answer_sentence[:159]
    canonical_path = f"/syllables/{word}/"
    canonical_url = SITE_URL + canonical_path
    robots_meta = '<meta name="robots" content="noindex, nofollow">\n' if NOINDEX else ""

    faq_ld = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question", "name": f"How many syllables does {word} have?",
            "acceptedAnswer": {"@type": "Answer", "text": answer_sentence},
        }],
    }

    body = f"""
<section class="answer-hero"><div class="wrap">
  <h1>How Many Syllables in {display_word}?</h1>
  <div class="answer-card">
    <p class="answer-number">{count}</p>
    <p class="answer-unit">syllable{plural}</p>
    <div class="answer-syllables">{syllables_html}</div>
  </div>
  <p class="answer-stress">{stress_line}</p>
  <div class="tag-row">{tags_html}</div>
</div></section>

<div class="wrap word-below">
{ambiguous_block}
{approx_block}
{tricky_block}
{crosslinks}
</div>
"""

    html = f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{FAVICON_HEAD}
<title>{escape(title)}</title>
<meta name="description" content="{escape(meta_desc)}">
{robots_meta}<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{escape(title.split(' | ')[0])}">
<meta property="og:description" content="{escape(meta_desc)}">
<meta property="og:url" content="{canonical_url}">
{OG_IMAGE_TAGS}
<meta property="og:type" content="website">
<link rel="stylesheet" href="/assets/css/list.css">
<link rel="stylesheet" href="/assets/css/word.css">
<script>try{{var t=localStorage.getItem("wordsound_theme");if(t)document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}</script>
<script type="application/ld+json">{json.dumps(faq_ld)}</script>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.2C.5 8.2 2.6 5 6 5c2 0 3.5 1.1 6 3.4C14.5 6.1 16 5 18 5c3.4 0 5.5 3.2 4 6.8-2.5 4.6-10 9.2-10 9.2z"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="1.5"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></symbol>
</svg>
{counter_header(None)}
{body}
{counter_footer(build_year)}
<script>{word_page_js()}</script>
</body>
</html>"""
    return html


def compute_sibling_map(wordlist, results, freq_counts):
    """Every word's cross-linked siblings for the word-page 'More N-syllable
    words' section, plus a coverage pass so no word ends up with zero
    inbound sibling links.

    First pass: each word's 5 nearest-by-frequency same-count words (widened
    to the whole wordlist if its own count-bucket has fewer than 5 others --
    a capacity fallback, kept for when the wordlist grows unevenly).

    That first pass is directional: word A picking word B as a near
    neighbor doesn't mean B's own independently-computed nearest-5 includes
    A back. At 45 words this left /syllables/heart/ with zero inbound
    links despite its own bucket (18 one-syllable words) never being thin
    -- nobody else's list happened to contain it. A capacity fallback can't
    fix that; it isn't a capacity problem. Hunting these by hand doesn't
    scale once the wordlist reaches ~400, so: a second, deterministic
    coverage pass finds every word with zero inbound links and appends it
    as a 6th entry to whichever OTHER word's list it's the closest
    frequency miss on (smallest freq_count gap, among words that don't
    already list it and whose list is still under the 6-entry cap -- never
    displacing an existing pick). Ties break alphabetically throughout, so
    the whole thing is stable across builds on the same input.
    """
    by_count = defaultdict(list)
    for w in wordlist:
        by_count[results[w]["syllable_count"]].append(w)

    sibling_map = {}
    for word in wordlist:
        count = results[word]["syllable_count"]
        candidates = [w for w in by_count[count] if w != word]
        if len(candidates) < 5:
            candidates = [w for w in wordlist if w != word]
        candidates.sort(key=lambda w: (abs(freq_counts.get(w, 0) - freq_counts.get(word, 0)), w))
        sibling_map[word] = candidates[:5]

    inbound = {w: set() for w in wordlist}
    for word, sibs in sibling_map.items():
        for s in sibs:
            inbound[s].add(word)

    orphans_before = [w for w in wordlist if not inbound[w]]
    for orphan in orphans_before:
        count = results[orphan]["syllable_count"]
        pool = [w for w in by_count[count] if w != orphan]
        eligible = [w for w in pool if orphan not in sibling_map[w] and len(sibling_map[w]) < 6]
        if not eligible:
            # Defensive only -- not expected to trigger on real data, but
            # widen past the same-count bucket rather than leave a word
            # unfixed if one is ever this constrained.
            eligible = [w for w in wordlist
                        if w != orphan and orphan not in sibling_map[w] and len(sibling_map[w]) < 6]
        if eligible:
            eligible.sort(key=lambda w: (abs(freq_counts.get(w, 0) - freq_counts.get(orphan, 0)), w))
            target = eligible[0]
            sibling_map[target].append(orphan)
            inbound[orphan].add(target)

    orphans_after = [w for w in wordlist if not inbound[w]]
    return sibling_map, orphans_before, orphans_after


def build_word_pages(cmu_words, wordlist, freq_counts):
    build_year = date.today().year
    results = {w: analyze(w, cmu_words) for w in wordlist}
    sibling_map, orphans_before, orphans_after = compute_sibling_map(wordlist, results, freq_counts)

    if orphans_after:
        print(f"  [!] {len(orphans_after)} word(s) still have zero inbound sibling "
              f"links after the coverage pass: {', '.join(orphans_after)}")
    print(f"  sibling coverage pass: {len(orphans_before)} of {len(wordlist)} words needed it "
          f"({', '.join(orphans_before) if orphans_before else 'none'}) -> "
          f"{'0 unintentional orphans remain' if not orphans_after else f'{len(orphans_after)} unresolved'}")

    total_kb = 0.0
    for word in wordlist:
        r = results[word]
        siblings = [(w, results[w]) for w in sibling_map[word]]

        html = render_word_page(word, r, siblings, build_year)
        write_page(f"syllables/{word}", html)
        total_kb += len(html.encode("utf-8")) / 1024

    avg_kb = total_kb / len(wordlist) if wordlist else 0
    print(f"  {len(wordlist)} word pages -> avg {avg_kb:.1f} KB, total {total_kb:.1f} KB")
    return results


def build_words_json(results, vocab, freq_counts):
    data = {}
    for word, r in results.items():
        data[word] = {
            "syllable_count": r["syllable_count"],
            "syllable_split": r["display_split"],
            "stress_pattern": r["stress_pattern"],
            "open_closed": r["open_closed_pattern"],
            "ambiguous": r["ambiguous"],
            "ambiguous_note": r["note"] or "",
            "approximate": not r["display_split_exact"],
            "in_vocab": word in vocab,
            "freq_count": freq_counts.get(word),  # null if absent from count_1w.txt
        }
    (DATA_DIR / "words.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  data/words.json  -> {len(data)} words")


def build_counter_dict(cmu_words, vocab, freq_counts):
    """Browser-side syllable-counter dictionary: every word that's real
    dictionary vocabulary (SCOWL) AND at or above MIN_FREQ_COUNT in Google
    Books usage, and that cmudict can pronounce. Common words only (so
    it's trustworthy and small), for Part 1's instant per-word lookup --
    words outside this set fall back to the counter's own algorithm
    client-side."""
    data = {}
    for word in vocab:
        count = freq_counts.get(word, 0)
        if count < MIN_FREQ_COUNT or word not in cmu_words:
            continue
        r = analyze(word, cmu_words)
        data[word] = {
            "syllable_count": r["syllable_count"],
            "syllable_split": r["display_split"],
            "stress_pattern": r["stress_pattern"],
        }
    path = DATA_DIR / "counter_dict.json"
    text = json.dumps(data, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    print(f"  data/counter_dict.json -> {len(data):,} words, {len(text) / 1024:.1f} KB")


COUNTER_DICT_N = 8000

# The signature "gutter" feature needs real per-syllable stress marks
# (spec: "˘ and ¯ marks from the stress data where known"). A bare
# word->count map (as originally specified: {able:2,...}) can't produce
# that -- there's no stress information in an integer. Storing the stress
# PATTERN STRING instead (e.g. "10") costs a little more per entry but
# gives scansion for free (syllable count is just pattern.length), and
# 8,000 entries this way is 116.2KB -- still under the 120KB ceiling, so
# no need to drop to 6,000 words either.
def build_counter_dict_js(cmu_words, freq_counts, n=COUNTER_DICT_N):
    """Top-n cmudict words by Google Books frequency -> stress pattern
    string, as a compact JS object literal. Deliberately NOT filtered
    through load_vocab() (the SCOWL common-word list used for the list
    pages): a syllable counter has to handle whatever a user actually
    types, and poems in particular are full of proper nouns (place names,
    people's names) that SCOWL's vocabulary-only filter would exclude."""
    candidates = [(w, c) for w, c in freq_counts.items() if w.isalpha() and w in cmu_words]
    candidates.sort(key=lambda t: -t[1])
    data = {}
    for word, _count in candidates[:n]:
        r = analyze(word, cmu_words)
        data[word] = r["stress_pattern"]
    js = "const D=" + json.dumps(data, separators=(",", ":")) + ";"
    return js, len(data)


COUNTER_JS = """
(function () {
  "use strict";
  var THEME_KEY = "wordsound_theme";

  var ta = document.getElementById("ta");
  var gutter = document.getElementById("gutter");
  var chipsEl = document.getElementById("chips");
  var emptyNote = document.getElementById("empty-note");
  var statSyl = document.getElementById("stat-syl");
  var statWords = document.getElementById("stat-words");
  var statLines = document.getElementById("stat-lines");
  var statChars = document.getElementById("stat-chars");
  var patternSelect = document.getElementById("pattern-select");
  var validatorList = document.getElementById("validator-list");
  var validatorBlock = document.getElementById("validator-block");

  var PATTERNS = {
    haiku: [5, 7, 5],
    tanka: [5, 7, 5, 7, 7],
    sonnet: [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10]
  };
  var AUTO_BY_LINES = { 3: "haiku", 5: "tanka", 14: "sonnet" };

  // Fallback estimator for words not in D (the inlined top-8000 dictionary).
  function estimateSyllables(word) {
    var groups = word.match(/[aeiouy]+/g) || [];
    var count = groups.length;
    if (word.length > 3 && /[^aeiouy]e$/.test(word)) count -= 1;
    if (/(es|ed)$/.test(word)) {
      var pre = word.charAt(word.length - 3);
      if (pre && !/[aeiouy]/.test(pre) && pre !== "t" && pre !== "d") count -= 1;
    }
    if (/[^aeiouy]le$/.test(word)) count += 1;
    if (/ism$/.test(word)) count += 1;
    if (/ia/.test(word)) count += 1;
    if (/io/.test(word)) count += 1;
    return Math.max(1, count);
  }

  // D stores stress patterns, not splits (that data isn't shipped either --
  // it's the same weight tradeoff as the counter itself). So every word's
  // visible split, dictionary or estimated, comes from this approximate
  // letter-level syllabifier, constrained to land on the known/estimated count.
  function splitWord(word, target) {
    if (!word) return [""];
    var groups = [];
    var re = /[aeiouy]+/g, m;
    while ((m = re.exec(word))) groups.push([m.index, m.index + m[0].length]);
    if (groups.length === 0) return [word];
    var bounds = [0];
    for (var i = 0; i < groups.length - 1; i++) {
      var cs = groups[i][1], ce = groups[i + 1][0], clen = ce - cs;
      bounds.push(clen <= 1 ? ce : cs + Math.ceil(clen / 2));
    }
    bounds.push(word.length);
    var parts = [];
    for (var i = 0; i < bounds.length - 1; i++) parts.push(word.slice(bounds[i], bounds[i + 1]));
    while (parts.length > target && parts.length > 1) parts[parts.length - 2] += parts.pop();
    while (parts.length < target) {
      var idx = 0;
      for (var i = 1; i < parts.length; i++) if (parts[i].length > parts[idx].length) idx = i;
      if (parts[idx].length < 2) break;
      var half = Math.ceil(parts[idx].length / 2);
      parts.splice(idx, 1, parts[idx].slice(0, half), parts[idx].slice(half));
    }
    return parts;
  }

  function analyzeWord(raw) {
    var clean = raw.toLowerCase().replace(/[^a-z]/g, "");
    if (!clean) return null;
    if (Object.prototype.hasOwnProperty.call(D, clean)) {
      var pattern = D[clean];
      return { raw: raw, clean: clean, count: pattern.length, pattern: pattern, estimated: false };
    }
    return { raw: raw, clean: clean, count: estimateSyllables(clean), pattern: null, estimated: true };
  }

  // Known syllable -> real stress mark. Estimated syllable -> a neutral dot,
  // not a guessed stress mark: we don't have stress data for these at all,
  // and fabricating it would be worse than the honest "unknown" signal.
  function marksFor(a) {
    if (a.pattern) {
      var s = "";
      for (var i = 0; i < a.pattern.length; i++) s += (a.pattern.charAt(i) === "0" ? "\\u02D8" : "\\u00AF");
      return s;
    }
    var s2 = "";
    for (var j = 0; j < a.count; j++) s2 += "\\u00B7";
    return s2;
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  var prevLineCounts = [];
  var lastLineResults = [];

  function render() {
    var text = ta.value;
    var lines = text.length ? text.split("\\n") : [];
    var totalSyl = 0, totalWords = 0;
    var lineResults = [];
    var chips = [];

    lines.forEach(function (line) {
      var tokens = line.match(/[A-Za-z']+/g) || [];
      var lineSyl = 0, marks = [];
      tokens.forEach(function (tok) {
        var a = analyzeWord(tok);
        if (!a) return;
        lineSyl += a.count;
        totalSyl += a.count;
        totalWords++;
        marks.push(marksFor(a));
        chips.push(a);
      });
      lineResults.push({ count: lineSyl, scan: marks.join(" ") });
    });

    var gHtml;
    if (!lineResults.length) {
      gHtml = '<div class="gline" style="opacity:.55"><span class="gcount">\\u2013</span></div>';
    } else {
      gHtml = "";
      lineResults.forEach(function (l, i) {
        var bump = prevLineCounts[i] !== undefined && prevLineCounts[i] !== l.count ? " bump" : "";
        gHtml += '<div class="gline' + bump + '"><span class="gcount">' + l.count +
                 '</span><span class="gscan">' + l.scan + "</span></div>";
      });
    }
    gutter.innerHTML = gHtml;
    prevLineCounts = lineResults.map(function (l) { return l.count; });
    gutter.style.height = ta.clientHeight + "px";
    gutter.scrollTop = ta.scrollTop;

    statSyl.textContent = totalSyl;
    statWords.textContent = totalWords;
    statLines.textContent = lines.length;
    statChars.textContent = text.length;

    if (!chips.length) {
      chipsEl.hidden = true;
      emptyNote.hidden = false;
    } else {
      chipsEl.hidden = false;
      emptyNote.hidden = true;
      var cHtml = "";
      chips.forEach(function (a) {
        var parts = splitWord(a.clean, a.count).join(" \\u00B7 ");
        cHtml += '<div class="chip"><span class="cw">' + escapeHtml(a.raw) +
                 (a.estimated ? '<span class="approx" title="Estimated \\u2014 this word isn\\'t in our dictionary." aria-label="Estimated">\\u2248</span>' : "") +
                 '</span><span class="cs">' + escapeHtml(parts) + "</span></div>";
      });
      chipsEl.innerHTML = cHtml;
    }

    lastLineResults = lineResults;
    renderValidator(lineResults);
  }

  function activePattern(lineCount) {
    var mode = patternSelect.value;
    if (mode === "none") return null;
    if (mode === "auto") {
      var key = AUTO_BY_LINES[lineCount];
      return key ? PATTERNS[key] : null;
    }
    return PATTERNS[mode] || null;
  }

  function renderValidator(lineResults) {
    var pattern = activePattern(lineResults.length);
    if (!pattern) { validatorBlock.hidden = true; return; }
    validatorBlock.hidden = false;
    var max = Math.max(pattern.length, lineResults.length);
    var html = "";
    for (var i = 0; i < max; i++) {
      var target = pattern[i];
      var row = lineResults[i];
      if (target === undefined) {
        html += "<li><span>Line " + (i + 1) + "</span><span class=\\"delta\\">extra line</span></li>";
      } else if (!row) {
        html += "<li><span>Line " + (i + 1) + "</span><span class=\\"delta\\">needs " + target + "</span></li>";
      } else if (row.count === target) {
        html += "<li><span>Line " + (i + 1) + "</span><span class=\\"ok\\">\\u2713 " + row.count + "</span></li>";
      } else {
        var diff = row.count - target;
        html += "<li><span>Line " + (i + 1) + "</span><span class=\\"delta\\">" + row.count + " \\u2014 needs " + target +
                 ", " + (diff > 0 ? "cut " + diff : "add " + (-diff)) + "</span></li>";
      }
    }
    validatorList.innerHTML = html;
  }

  var debounceTimer = null;
  ta.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(render, 80);
  });
  ta.addEventListener("scroll", function () { gutter.scrollTop = ta.scrollTop; });
  if (window.ResizeObserver) new ResizeObserver(function () { gutter.style.height = ta.clientHeight + "px"; }).observe(ta);
  patternSelect.addEventListener("change", function () { renderValidator(lastLineResults); });

  var copyBtn = document.getElementById("copy-results-btn");
  if (copyBtn) copyBtn.addEventListener("click", function () {
    var lines = ta.value.length ? ta.value.split("\\n") : [];
    var gcounts = gutter.querySelectorAll(".gcount");
    var out = lines.map(function (line, i) {
      var c = gcounts[i] ? gcounts[i].textContent : "0";
      return line + "  (" + c + ")";
    }).join("\\n");
    out += "\\n\\nTotal: " + statSyl.textContent + " syllables, " + statWords.textContent + " words, " +
           statLines.textContent + " lines.";
    copyText(out);
  });

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text); return; }
    var t = document.createElement("textarea");
    t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(t);
  }

  var clearBtn = document.getElementById("clear-btn");
  if (clearBtn) clearBtn.addEventListener("click", function () { ta.value = ""; render(); ta.focus(); });

  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  });

  render();
})();
"""


COUNTER_MODES = {
    # "home" and "tool" are both self-canonical (see render_counter_page),
    # so each needs its own H1 rather than competing for the same phrase.
    # "/syllable-counter/" keeps the exact-match head keyword as its H1;
    # "/" leads with the longer, more descriptive phrasing instead -- still
    # keyword-rich, but distinct enough that the two pages aren't sending
    # search engines identical top-of-page signals. The eyebrow stays
    # matched to each page's own framing (home: broad/poetic; tool: built-
    # for-poets), which was never the source of the collision.
    "home": {
        "slug": "",
        "title": "Syllable Counter — Count Syllables in Words, Sentences & Poems | WordSound",
        # Trimmed from 173 to under 155 chars, same audit fix as the list
        # pages -- see the meta_desc comment in render_list_page.
        "meta_desc": "Count syllables in any word, sentence, or poem, live as you type -- "
                     "with haiku, tanka, and sonnet checking. Plus 500+ word lists from CMUdict.",
        "eyebrow": "Words have rhythm.",
        "h1": "Count Syllables in Any Word, Sentence, or Poem",
        "intro": "Built on Carnegie Mellon's pronunciation dictionary. Free, no sign-up, works offline.",
    },
    "tool": {
        "slug": "syllable-counter",
        "title": "Syllable Counter | WordSound",
        "meta_desc": "A syllable counter built for poems: a per-line syllable gutter, live "
                     "scansion marks, and haiku/tanka/sonnet validation. Free, instant, works offline.",
        "eyebrow": "Built for poets first.",
        "h1": "Syllable Counter",
        "intro": "Count syllables in any word, sentence, or poem. The gutter on the left shows "
                 "a live syllable count and scansion for every line as you type.",
    },
}

# One line of real context per canonical list, for the homepage directory
# grid. Deliberately 7 entries, not 9: CATEGORIES has 9 total page entries,
# but 2 of those (two-syllable-words, three-syllable-words) are keyword-
# variant ALIASES of 2-/3-syllable-words -- same underlying list, different
# URL, canonical pointing back at the numeral version (see the CATEGORIES
# comment above). Listing all 9 here would put two links to the identical
# word list, under different URLs, side by side in the homepage's main
# internal-linking block -- exactly the signal-splitting the canonical
# strategy exists to avoid. The 7 canonical slugs are the real directory.
DIRECTORY_BLURBS = {
    "2-syllable-words": "Two-syllable words for early readers and spelling practice.",
    "3-syllable-words": "Three-syllable words for vocabulary building and phonics drills.",
    "4-syllable-words": "Four-syllable words for advanced spelling and speech therapy.",
    "5-syllable-words": "Five-syllable words for the trickiest vocabulary work.",
    "multisyllabic-words": "Every common word with three or more syllables, in one list.",
    "open-syllable-words": "Words whose stressed syllable ends in a long vowel sound.",
    "closed-syllable-words": "Words whose stressed syllable ends in a consonant, short vowel sound.",
}


def counter_header(active):
    return f"""<header class="ws-header"><div class="wrap">
  <a class="wordmark" href="/"><span class="line1">WORD SOUND</span><span class="line2">&middot; Online &middot;</span></a>
  <nav class="ws-nav">
    <a href="/"{' class="active"' if active == "counter" else ""}>Syllable Counter</a>
    <a href="/2-syllable-words/"{' class="active"' if active == "lists" else ""}>Word Lists</a>
    <a href="/about/">About</a>
  </nav>
  <div class="header-actions">
    <span class="fav-pill"><svg class="ico"><use href="#i-heart"/></svg> <span id="fav-count">0</span><span class="fav-label"> Favorites</span></span>
    <button class="theme-toggle" id="theme-toggle" type="button" aria-label="Toggle dark mode"><svg class="icon" viewBox="0 0 24 24"><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg></button>
  </div>
</div></header>"""


def fav_pill_init_js():
    # counter_header() puts a #fav-count pill on every page now (home, tool,
    # about, word pages), but only list.css pages and word pages have .wr
    # rows with their own favorite-toggle JS (list_page_js / word_page_js),
    # which already update the pill on load. Home/tool/about have no .wr
    # rows of their own, so they need this on-load read of the SAME
    # FAV_KEY to show an accurate count instead of a hardcoded 0.
    return """
(function () {
  "use strict";
  try {
    var favs = JSON.parse(localStorage.getItem("wordsound_favorites") || "[]");
    var el = document.getElementById("fav-count");
    if (el) el.textContent = favs.length;
  } catch (e) {}
})();
"""


def counter_footer(build_year):
    return f"""<footer class="ws-footer"><div class="wrap">
  <div class="footer-grid">
    <div>
      <a class="wordmark" href="/" style="color:var(--ink)"><span class="line1">WORD SOUND</span><span class="line2">&middot; Online &middot;</span></a>
      <p class="footer-tagline">Tools for writers, teachers, parents, and word lovers.</p>
    </div>
    <div><h3>Tools</h3><ul><li><a href="/syllable-counter/">Syllable Counter</a></li><li><a href="/2-syllable-words/">Word Lists</a></li></ul></div>
    <div><h3>Help</h3><ul><li><a href="/about/">How It Works</a></li><li><a href="/about/">About</a></li></ul></div>
    <div><h3>Data</h3><p class="footer-tagline">Built on CMUdict, Carnegie Mellon's pronunciation dictionary.</p></div>
  </div>
  <div class="footer-bottom">&copy; {build_year} wordsound.online</div>
</div></footer>"""


def render_counter_page(mode, dict_js, build_year, all_data):
    cfg = COUNTER_MODES[mode]
    # Both pages are now self-canonical -- "/" no longer aliases to
    # "/syllable-counter/". Earlier phases had "/" carry a canonical pointing
    # at the tool page (same consolidation pattern as the list-page aliases);
    # this task's instruction reverses that for the homepage specifically,
    # so both URLs are independently indexable now. See build_sitemap_and_robots
    # for the matching sitemap change (both URLs listed, not just one).
    canonical_path = "/" if mode == "home" else "/syllable-counter/"
    canonical_url = SITE_URL + canonical_path
    robots_meta = '<meta name="robots" content="noindex, nofollow">\n' if NOINDEX else ""

    software_ld = {
        "@context": "https://schema.org", "@type": "SoftwareApplication",
        "name": "WordSound Syllable Counter",
        "applicationCategory": "UtilitiesApplication",
        "operatingSystem": "Any (web-based)",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "url": canonical_url,
    }

    below_links = "".join(
        f'<li><a href="/{cat["slug"]}/">{cat["title"]}</a></li>'
        for cat in CATEGORIES if cat["slug"] == cat["canonical"]
    )

    # Homepage-only: the internal-linking block the spec asks for. Not on
    # /syllable-counter/ -- that page already links out via below_links, and
    # duplicating a second full directory there wouldn't add anything a
    # search engine or a reader needs that the shorter list doesn't already give.
    directory_html = ""
    if mode == "home":
        cards = "".join(
            f'<a class="dir-card" href="/{cat["slug"]}/">'
            f'<span class="dir-name">{cat["title"]}</span>'
            f'<span class="dir-count num">{all_data[cat["slug"]]["shown_n"]:,} words</span>'
            f'<span class="dir-blurb">{DIRECTORY_BLURBS[cat["slug"]]}</span></a>'
            for cat in CATEGORIES if cat["slug"] == cat["canonical"]
        )
        directory_html = f"""
<section class="list-directory"><div class="wrap">
  <h2>Browse the word lists</h2>
  <div class="dir-grid">{cards}</div>
</div></section>
"""

    body = f"""
<section class="tool-hero"><div class="wrap">
  <p class="eyebrow">{cfg['eyebrow']}</p>
  <h1>{cfg['h1']}</h1>
  <p class="hero-intro">{cfg['intro']}</p>
</div></section>

<div class="wrap">
<div class="tool-grid">
  <div class="panel">
    <div class="panel-head">Type or paste text</div>
    <div class="editor">
      <div class="gutter" id="gutter" aria-hidden="true"></div>
      <textarea id="ta" class="input-ta" wrap="off" spellcheck="false" autocapitalize="off"
        placeholder="Type or paste a word, a sentence, or a poem&hellip;"></textarea>
    </div>
  </div>

  <div class="panel">
    <div class="panel-head">Results</div>
    <div class="totals-bar" aria-live="polite">
      <div class="stat"><span class="n num" id="stat-syl">0</span><span class="lbl">Syllables</span></div>
      <div class="stat"><span class="n num" id="stat-words">0</span><span class="lbl">Words</span></div>
      <div class="stat"><span class="n num" id="stat-lines">0</span><span class="lbl">Lines</span></div>
      <div class="stat"><span class="n num" id="stat-chars">0</span><span class="lbl">Characters</span></div>
    </div>
    <div class="chips" id="chips" hidden></div>
    <p class="empty-note" id="empty-note">Results appear here as you type.</p>
    <div class="validator" id="validator-block" hidden>
      <div class="validator-row">
        <label for="pattern-select">Check against:</label>
        <select id="pattern-select">
          <option value="auto" selected>Auto-detect</option>
          <option value="haiku">Haiku (5-7-5)</option>
          <option value="tanka">Tanka (5-7-5-7-7)</option>
          <option value="sonnet">Sonnet (10 per line)</option>
          <option value="none">None</option>
        </select>
      </div>
      <ul class="vlines" id="validator-list"></ul>
    </div>
    <div class="tool-actions">
      <button class="ab-btn" id="copy-results-btn" type="button"><svg class="ico"><use href="#i-copy"/></svg><span class="label">Copy Results</span></button>
      <button class="ab-btn" id="clear-btn" type="button">Clear</button>
    </div>
  </div>
</div>

<div class="below-tool">
  <p>Syllable counts come from CMUdict, Carnegie Mellon's 134,000-word pronunciation
  dictionary -- the {COUNTER_DICT_N:,} most common words are built into this page for instant,
  offline lookup. Less common words are estimated from spelling and marked with &asymp;.</p>
  <ul class="below-links">{below_links}</ul>
</div>
</div>
{directory_html}
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="1.5"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></symbol>
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.2C.5 8.2 2.6 5 6 5c2 0 3.5 1.1 6 3.4C14.5 6.1 16 5 18 5c3.4 0 5.5 3.2 4 6.8-2.5 4.6-10 9.2-10 9.2z"/></symbol>
</svg>
"""

    html = f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{FAVICON_HEAD}
<title>{escape(cfg['title'])}</title>
<meta name="description" content="{escape(cfg['meta_desc'])}">
{robots_meta}<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{escape(cfg['h1'])}">
<meta property="og:description" content="{escape(cfg['meta_desc'])}">
<meta property="og:url" content="{canonical_url}">
{OG_IMAGE_TAGS}
<meta property="og:type" content="website">
<link rel="stylesheet" href="/assets/css/list.css">
<link rel="stylesheet" href="/assets/css/counter.css">
<script>try{{var t=localStorage.getItem("wordsound_theme");if(t)document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}</script>
<script type="application/ld+json">{json.dumps(software_ld)}</script>
</head>
<body>
{counter_header("counter")}
{body}
{counter_footer(build_year)}
<script>{dict_js}{COUNTER_JS}{fav_pill_init_js()}</script>
</body>
</html>"""
    return html


def build_counter_pages(cmu_words, freq_counts, all_data):
    dict_js, word_count = build_counter_dict_js(cmu_words, freq_counts)
    dict_kb = len(dict_js.encode()) / 1024
    build_year = date.today().year

    for mode, slug in (("home", ""), ("tool", "syllable-counter")):
        html = render_counter_page(mode, dict_js, build_year, all_data)
        write_page(slug, html)
        total_kb = len(html.encode()) / 1024
        page_only_kb = total_kb - dict_kb
        label = "/" if slug == "" else f"/{slug}/"
        flag = "  [!] over 150KB budget (excl. dictionary)" if page_only_kb > 150 else ""
        print(f"  {label}  -> {total_kb:.1f} KB total ({page_only_kb:.1f} KB excl. "
              f"{dict_kb:.1f} KB dictionary, {word_count:,} words){flag}")


def build_about_page():
    build_year = date.today().year
    title = "About | WordSound"
    meta_desc = "How WordSound counts syllables: built on CMUdict, Carnegie Mellon's " \
                "pronunciation dictionary, with honest notes on where the count is estimated or contested."
    canonical_path = "/about/"
    canonical_url = SITE_URL + canonical_path
    robots_meta = '<meta name="robots" content="noindex, nofollow">\n' if NOINDEX else ""

    # 250 words, plain voice, no marketing copy -- this page exists for
    # E-E-A-T, which means it has to read like a person actually explaining
    # the tool, limitations included, not like ad copy for it.
    body = f"""
<div class="wrap"><div class="about-body">
<h1>About WordSound</h1>
<p class="intro">WordSound counts syllables. Type a word, a sentence, or a whole poem, and
the counter shows a number for every line, plus a stress pattern where one is known. There
are also nine word lists &mdash; two-syllable words, closed-syllable words, and so on &mdash;
for anyone who wants to browse or search rather than type one word at a time.</p>

<h2>Where the data comes from</h2>
<p>Every syllable count here starts with <a href="https://github.com/cmusphinx/cmudict"
rel="noopener">CMUdict</a>, Carnegie Mellon University's pronunciation dictionary. It covers
roughly 134,000 English words, each transcribed as a sequence of phonemes with stress marked
on every vowel sound.</p>

<h2>How the count is derived</h2>
<p>A syllable count is just the number of stressed vowel phonemes in a word's transcription
&mdash; one per syllable, by definition. The syllable split you see (like &ldquo;beau &middot;
ti &middot; ful&rdquo;) is reconstructed by walking that phoneme sequence back onto the
original spelling, which is why it's usually exact but occasionally approximate.</p>

<h2>Where it can be wrong, on purpose</h2>
<p>Some words genuinely have more than one correct answer. &ldquo;Fire,&rdquo;
&ldquo;hour,&rdquo; and &ldquo;every&rdquo; can be said with fewer syllables in casual speech
than in their full, careful pronunciation. This site counts the fuller form &mdash; the one a
dictionary would cite &mdash; and says so on a word's own page when that choice is
contestable.</p>
<p>Words outside CMUdict are estimated from spelling rules instead of a real transcription,
and marked with &asymp; wherever they appear. A handful of syllable splits are also
hand-corrected, for words where the automatic phoneme-to-spelling mapping produces a wrong or
misleading-looking break.</p>

<h2>Who this is for</h2>
<p>Teachers building phonics lessons, speech-language pathologists who need a quick reference,
parents helping with homework, and poets counting beats &mdash; that's who this was built
for.</p>
</div></div>
"""

    html = f"""<!doctype html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{FAVICON_HEAD}
<title>{escape(title)}</title>
<meta name="description" content="{escape(meta_desc)}">
{robots_meta}<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="About | WordSound">
<meta property="og:description" content="{escape(meta_desc)}">
<meta property="og:url" content="{canonical_url}">
{OG_IMAGE_TAGS}
<meta property="og:type" content="website">
<link rel="stylesheet" href="/assets/css/list.css">
<link rel="stylesheet" href="/assets/css/about.css">
<script>try{{var t=localStorage.getItem("wordsound_theme");if(t)document.documentElement.setAttribute("data-theme",t);}}catch(e){{}}</script>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-10-9.2C.5 8.2 2.6 5 6 5c2 0 3.5 1.1 6 3.4C14.5 6.1 16 5 18 5c3.4 0 5.5 3.2 4 6.8-2.5 4.6-10 9.2-10 9.2z"/></symbol>
</svg>
{counter_header(None)}
{body}
{counter_footer(build_year)}
<script>
(function () {{
  "use strict";
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {{
    var current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    var next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {{ localStorage.setItem("wordsound_theme", next); }} catch (e) {{}}
  }});
}})();
</script>
<script>{fav_pill_init_js()}</script>
</body>
</html>"""
    write_page("about", html)
    weight_kb = len(html.encode("utf-8")) / 1024
    flag = "  [!] over 150KB budget" if weight_kb > 150 else ""
    print(f"  /about/  -> {weight_kb:.1f} KB{flag}")


def build_sitemap_and_robots(wordlist):
    today = date.today().isoformat()
    # "/" and "/syllable-counter/" are BOTH self-canonical now (see
    # render_counter_page) -- unlike the list-page numeral/word aliases,
    # neither one points its canonical at the other, so both belong in the
    # sitemap as real, independently indexable URLs. "/" gets the top
    # priority as the site root; the tool page is still the stronger
    # keyword-exact URL, so it sits just under it.
    urls = [("/", "1.0"), ("/syllable-counter/", "0.9"), ("/about/", "0.5")]
    for cat in CATEGORIES:
        if cat["slug"] == cat["canonical"]:
            urls.append((f"/{cat['slug']}/", "0.8"))
    for word in wordlist:
        urls.append((f"/syllables/{word}/", "0.6"))

    entries = "\n".join(
        f"  <url>\n    <loc>{SITE_URL}{path}</loc>\n    <lastmod>{today}</lastmod>\n"
        f"    <priority>{priority}</priority>\n  </url>"
        for path, priority in urls
    )
    sitemap = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
               f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entries}\n</urlset>\n')
    (OUTPUT_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n"
    (OUTPUT_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print(f"  sitemap.xml -> {len(urls)} canonical URLs, robots.txt")


def copy_assets():
    dest = OUTPUT_DIR / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ASSETS_SRC, dest)


FAVICON_SPECS = [
    ("favicon-16.png", 16),
    ("favicon-32.png", 32),
    ("favicon-48.png", 48),
    ("apple-touch-icon.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
]


def generate_favicons():
    """Resize the master square icon (assets/images/favicon.png -- 1254x1254
    on disk, not quite the 1024x1024 assumed when this was speced, but any
    square source works fine here) down to every size the site references,
    plus a combined multi-resolution .ico. Skipped entirely once every
    output is already newer than the source, so a no-op rebuild doesn't
    re-resize a ~1MB source image on every run for nothing."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ico_path = OUTPUT_DIR / "favicon.ico"
    outputs = [OUTPUT_DIR / name for name, _ in FAVICON_SPECS] + [ico_path]
    src_mtime = FAVICON_SRC.stat().st_mtime
    if all(p.exists() and p.stat().st_mtime >= src_mtime for p in outputs):
        print("  favicons up to date, skipping regeneration")
        return

    src = Image.open(FAVICON_SRC).convert("RGBA")
    resized = {}
    for name, size in FAVICON_SPECS:
        img = src.resize((size, size), Image.Resampling.LANCZOS)
        img.save(OUTPUT_DIR / name)
        resized[size] = img

    # Each ICO frame is one of the PNGs already LANCZOS-resized above,
    # passed in via append_images -- Pillow embeds a frame as-is when its
    # size already matches an entry in `sizes`, only falling back to its
    # own (also LANCZOS) internal resize for sizes with no match supplied.
    # The base image (the one .save() is called on) MUST be the largest
    # frame: Pillow's ICO writer filters `sizes` against the base image's
    # OWN dimensions before even looking at append_images, silently
    # dropping any requested size bigger than the base -- calling this on
    # resized[16] with 32/48 in append_images produced a .ico containing
    # only the 16x16 frame, with no error or warning. Confirmed by
    # inspecting the actual bytes written, not just trusting the call
    # succeeded.
    resized[48].save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                      append_images=[resized[16], resized[32]])
    print(f"  generated {len(outputs)} favicon files from {FAVICON_SRC.name}")


def generate_og_image():
    """1200x630 social-preview image, reused site-wide -- every page's
    og:image/twitter:image points at this one file, so it's generated once
    here rather than per-page. Same source-newer-than-output caching rule
    as generate_favicons()."""
    path = OUTPUT_DIR / "og-image.png"
    if path.exists() and path.stat().st_mtime >= FAVICON_SRC.stat().st_mtime:
        print("  og-image.png up to date, skipping regeneration")
        return

    W, H = 1200, 630
    canvas = Image.new("RGB", (W, H), (0x14, 0x11, 0x0E))

    # The icon's own square background is near-black (10,8,8) but not an
    # exact match for the canvas fill (20,17,14) -- keying it to
    # transparent by luminance and pasting WITH that alpha as the mask
    # avoids a faint seam around the icon where two slightly different
    # blacks would otherwise meet.
    icon = Image.open(FAVICON_SRC).convert("RGBA")
    icon = icon.resize((400, 400), Image.Resampling.LANCZOS)
    alpha = icon.convert("L").point(lambda p: 0 if p < 20 else 255)
    icon.putalpha(alpha)
    icon_x, icon_y = 80, (H - 400) // 2
    canvas.paste(icon, (icon_x, icon_y), icon)

    draw = ImageDraw.Draw(canvas)
    text_x = icon_x + 400 + 60
    # No fallback to a bitmap font on load failure: a degraded og-image
    # that silently ships is worse than a build that stops and says why.
    # This also means the image is byte-identical wherever it's built,
    # since it no longer depends on whatever serif happens to be
    # installed on the machine running this script.
    for font_path in (FONT_SERIF, FONT_SERIF_BOLD):
        if not font_path.exists():
            raise FileNotFoundError(
                f"og-image generation requires {font_path}, which is missing. "
                f"This font is bundled in the repo (assets/fonts/) specifically so "
                f"the build doesn't depend on fonts installed on the host machine -- "
                f"restore it from git rather than pointing this at a system font."
            )
    title_font = ImageFont.truetype(str(FONT_SERIF_BOLD), 78)
    sub_font = ImageFont.truetype(str(FONT_SERIF), 32)

    title_y = H // 2 - 58
    draw.text((text_x, title_y), "WordSound", font=title_font, fill=(0xFB, 0xFA, 0xF7))
    draw.text((text_x, title_y + 96), "Syllable counter and word lists", font=sub_font, fill=(0x8A, 0x85, 0x7D))

    canvas.save(path)
    print(f"  generated og-image.png ({path.stat().st_size / 1024:.1f} KB)")


def write_cname():
    """GitHub Pages drops the custom domain whenever the deploy artifact
    doesn't include a CNAME file, so this has to be written on every build
    rather than set once in the repo settings."""
    (OUTPUT_DIR / "CNAME").write_text("wordsound.online", encoding="utf-8")
    print("  CNAME written")


def write_webmanifest():
    manifest = {
        "name": "WordSound",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": "#14110E",
        "background_color": "#FBFAF7",
    }
    (OUTPUT_DIR / "site.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("  site.webmanifest written")


def main():
    print("Checking data files...")
    ensure_data_files()

    print("Loading cmudict + vocab + frequency counts...")
    cmu_words = load_cmudict()
    vocab = load_vocab()
    freq_counts = load_freq_counts()
    wordlist = [w.strip().lower() for w in (DATA_DIR / "wordlist.txt").read_text().splitlines() if w.strip()]
    print(f"  {sum(1 for w in cmu_words if w in vocab):,} cmudict words are in the SCOWL vocab")

    print("Building word pool (vocab filter, count_1w.txt ranking)...")
    pool = build_word_pool(cmu_words, vocab, freq_counts)

    word_page_set = set(wordlist)
    build_year = date.today().year

    # Computed once, shared by list pages (their own content) and the
    # homepage (its directory grid needs the same shown_n counts) so both
    # surfaces always agree on how many words a category shows.
    all_data = compute_category_data(cmu_words, pool, word_page_set)

    print("Loading data/list_copy.json...")
    list_copy = load_list_copy()

    print("Building list pages...")
    build_list_pages(cmu_words, all_data, build_year, list_copy, wordlist)

    print("Building word pages...")
    results = build_word_pages(cmu_words, wordlist, freq_counts)

    print("Writing data/words.json...")
    build_words_json(results, vocab, freq_counts)

    print("Writing data/counter_dict.json...")
    build_counter_dict(cmu_words, vocab, freq_counts)

    print("Building syllable counter (/ and /syllable-counter/)...")
    build_counter_pages(cmu_words, freq_counts, all_data)

    print("Building about page...")
    build_about_page()

    print("Writing sitemap.xml + robots.txt...")
    build_sitemap_and_robots(wordlist)

    print("Writing CNAME...")
    write_cname()

    print("Copying assets...")
    copy_assets()

    print("Generating favicons + og-image + manifest...")
    generate_favicons()
    generate_og_image()
    write_webmanifest()

    print("Done.")


if __name__ == "__main__":
    main()
