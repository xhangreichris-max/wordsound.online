# wordsound.online

A static syllable-counter and word-list site. `scripts/build.py` reads
`data/` and `assets/` and writes a fully static `output/` -- no server,
no build framework, no npm.

## Prerequisites

- Python 3.11+
- git

## First run

```
pip install requests pillow
python scripts/parse_cmudict.py
python scripts/build.py
cd output && python -m http.server 8000
```

Then open `http://localhost:8000`.

`parse_cmudict.py` downloads `data/cmudict.dict` and `data/count_1w.txt`
(~24MB combined) the first time it runs, and caches them locally --
later runs, and later `build.py` runs, don't re-download. `data/scowl_70.txt`
is committed to the repo, not downloaded (see **Data sources and licenses**
below for why).

The site must be served from `output/`, not the repo root -- the generated
HTML uses root-relative asset paths (`/assets/...`) that only resolve
correctly once `output/` itself is the server root.

## Adding words

Edit `wordlist.txt`, one word per line, and push. Each word gets its own
page at `/syllables/<word>/`. `build.py` re-derives everything else --
syllable count, split, sibling cross-links -- on the next build.

## Editing list-page copy

`data/list_copy.json`, keyed by category slug (`2-syllable-words`,
`open-syllable-words`, etc). Each entry has `how_to_use`, `what_makes`,
and `tricky_cases` string fields; use `\n\n` inside a string to start a
new paragraph. Text that names a word already in `wordlist.txt` is
auto-linked to that word's page at build time (see **Auto-link stoplist**
below for what's excluded from that).

## Curated syllable splits

`CURATED_SPLITS` in `scripts/parse_cmudict.py` (near the top). The
syllabification algorithm gets almost everything right from the phonemes
alone, but a handful of words -- irregular spelling, a silent letter with
no phoneme to anchor it -- need a hand-verified override instead of a
special case in the general algorithm. Add an entry there only after
spot-checking that the algorithm's own output is actually wrong for that
word, not just unexpected.

## Auto-link stoplist

`AUTOLINK_STOPLIST` in `scripts/build.py`. Ordinary grammar words
(`while`, `about`, `our`, ...) that have their own word pages but should
never be auto-linked out of list-page prose -- linking a conjunction or
preposition mid-sentence reads as a bug, not a feature. Add a word here
if it starts getting linked from a sentence where it's just being used
normally, not cited as an example.

## Replacing the favicon

Drop a new square PNG at `assets/images/favicon.png`. `build.py`
regenerates every derived size (`favicon-16/32/48.png`, `favicon.ico`,
`apple-touch-icon.png`, `icon-192/512.png`) and `output/og-image.png` on
the next build, but only if the source PNG is newer than what's already
in `output/` -- an unchanged favicon costs nothing on rebuild.

## Folder structure

```
scripts/
  parse_cmudict.py   cmudict parsing, syllabification, data-file fetching
  build.py            site generator -- reads data/+assets/, writes output/
data/
  wordlist.txt        one word per line -- the site's word pages
  list_copy.json       hand-written prose for the 9 list pages
  cmudict.dict         downloaded on demand (see First run)
  count_1w.txt         downloaded on demand (see First run)
  scowl_70.txt         committed -- dictionary-word filter, not re-downloadable
assets/
  css/ js/ images/ fonts/   copied into output/ as-is (fonts/ is also a
                             build-time input to og-image.png generation)
output/                 generated -- the whole deployed site
.github/workflows/      GitHub Actions deploy workflow
```

## Data sources and licenses

- **CMUdict** -- pronunciation dictionary, pinned to a specific commit of
  [cmusphinx/cmudict](https://github.com/cmusphinx/cmudict) for
  reproducibility. BSD-style, permissive.
- **Norvig `count_1w.txt`** -- word-frequency ranking, from
  [norvig.com/ngrams](https://norvig.com/ngrams/) (Google Books unigram
  counts). Public domain.
- **SCOWL / ESDB** (`data/scowl_70.txt`) -- dictionary-word inclusion
  filter, generated via [app.aspell.net/create](https://app.aspell.net/create).
  Permissive, requires the copyright notice to travel with the data --
  it's embedded in the file's own header, which is why this one file is
  committed rather than fetched: it's not a static download (the ESDB
  database it's generated from is revised over time), so re-generating it
  later could silently return a different word list than the one the
  site was built and reviewed against.
- **DejaVu Serif** (`assets/fonts/`) -- based on Bitstream Vera, DejaVu's
  changes released into the public domain. Bundled so `og-image.png`
  renders identically on any machine, without depending on fonts
  installed on the host. See `assets/fonts/LICENSE-DejaVu.txt` for the
  full text, or the project at
  [dejavu-fonts.github.io](https://dejavu-fonts.github.io).

None of these require attribution in the built site itself.

## Deploying

See [DEPLOY.md](DEPLOY.md) for the one-time GitHub Pages + DNS setup.
Every push to `main` rebuilds and redeploys automatically via
`.github/workflows/deploy.yml`.
