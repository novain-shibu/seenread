# SeenRead

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23471690.svg)](https://doi.org/10.5281/zenodo.23471690)

**Prove, word by word and without OCR, whether the text a machine extracts from a PDF is the text a human sees.**

PDFs can show people one text while giving machines another: a font whose character table says "9" where it draws "1",
an edited text table (ToUnicode), white or invisible text, text outside the page. Copy-paste, search engines, screen
readers and AI pipelines (RAG, CV screening, AI-assisted reviewing) all read the machine version. Many PDFs in Indian
scripts are split the same way by accident: the page is right, the extracted text is garbled.

SeenRead never trusts the PDF's own font tables. It identifies every drawn glyph by its exact outline and advance in a
**trusted font** you supply, then accepts a text for a word only if the shaping engine (HarfBuzz) lays that text out with
the trusted font into **the same glyphs, arranged identically inside each cluster, in the same order** - so the two render
identically by construction. For each word it reports:

- `SAME` - the extracted text is what is drawn (proven)
- `DIFFERENT` - the extracted text is not what is drawn; the text a human sees is given (proven the same way)
- `UNKNOWN` - nothing could be proven (a glyph matches no trusted font, or no candidate lays out identically)

and lists text that machines read but humans cannot see (invisible render mode, transparent, under 1 pt, white,
outside the page).

## Results (synthetic documents, fresh blind sets, pre-registered)
Each blind set: 120 newly generated one-page documents (30 each in English, Hindi, Bengali, Tamil; about 40% clean
controls, the rest with font-remap or ToUnicode lies and/or hidden text), generated with a new random seed after the code
was frozen. Score = share of words whose human-visible text SeenRead gives exactly (aligned with the true visible text).

| Blind set | English | Hindi | Bengali | Tamil | Harmful errors | UNKNOWN | Hidden text found | False hidden alarms |
|---|---|---|---|---|---|---|---|---|
| seed 5303 (v2.6) | 99.88% | 100% | 100% | 100% | 1 of 4,386 (a missed lie) | 0 | 35/35 | 0/48 controls |
| seed 5304 (v2.7, released) | 100% | 99.93% | 100% | 100% | 0 of 4,317 | 1 | 28/28 | 0/53 controls |

The one miss in seed 5303 (Arial's small-caps lookups joined "o" and "O") was fixed in v2.7 and re-tested on seed 5304.
Two earlier blind sets with older versions scored lower and led to the fixes; all runs are in `bench/results/`.

**Compared with OCR on the same files** (seed 5303; Tesseract 5, better of two page modes per script):

| | English | Hindi | Bengali | Tamil |
|---|---|---|---|---|
| SeenRead - visible words exact | 99.88% | 100% | 100% | 100% |
| Tesseract OCR - visible words exact | 98.24% | 96.15% | 94.03% | 91.84% |
| Plain text extraction (PyMuPDF) | 91.53% | 58.19% | 24.59% | 26.79% |
| OCR-vs-extraction detector: lied/garbled words caught | 79.2% | 94.9% | 93.5% | 89.3% |
| OCR-vs-extraction detector: false alarms on clean words | 0.00% | 2.91% | 4.23% | 1.23% |

These are clean computer-generated pages - the best case for OCR. SeenRead caught all but one split word with no false
alarms; an OCR comparison misses words where OCR "corrects" a swapped letter back to a dictionary word, and raises
false alarms where OCR misreads.

## Limits (read before relying on it)
- **Synthetic documents only so far** (made with PyMuPDF's writers). Real-world PDFs from other producers, mixed
  layouts and unknown fonts are not tested yet.
- **Needs the trusted font.** A glyph that matches no trusted font gives `UNKNOWN` (never a guess). An attacker who
  draws new glyph shapes gets `UNKNOWN`, not `SAME`.
- Not handled yet: coloured backgrounds (white text is assumed invisible on a white page), clipping, objects covering
  text, Type 1 / CFF fonts (e.g. many LaTeX PDFs).
- Speed: seconds per page; lookup tables are built once per font and script.
- Built on the [Unshape](https://github.com/novain-shibu/unshape) decoder (same author) for Indian scripts.

## Use
```
pip install git+https://github.com/novain-shibu/seenread
seenread file.pdf --trusted Arial.ttf Lohit-Devanagari.ttf          # human-readable report
seenread file.pdf --trusted ... --json                               # per-word verdicts, visible text, hidden text
```
Reproduce the benchmark: `bench/generator.py` (set `SR_SEED`, font paths via `SR_ARIAL`, `SR_LOHIT`, `SR_NIRMALA`),
`bench/fastrun.py seenread.core <folder>`, `bench/summarize53d.py <folder>/results.jsonl`. Fonts are not included.

## Related work
- Split-view PDFs in document-to-LLM pipelines: Liu & Ming, arXiv 2606.15020 (IEEE S&P 2027) - 25 render/extract gaps,
  static screening; proposes dual-view consistency as future work.
- Font remapping attacks on LLM document readers: arXiv 2505.16957; Luo et al., IACR ePrint 2026/278 (OCR-based
  pipelines robust; recommends rendering + computer vision).
- Detection: CrackedPDFs (arXiv 2607.19396, learned hybrid detector); rule-based scanners (hidden-text-detector,
  PDF-Prompt-Injection-Toolkit); commercial scanners with ToUnicode heuristics and OCR comparison.
- We found no tool that proves the human-visible text from glyph identities and shaping layout without OCR; pointers to
  earlier work are welcome.

## Licence and commercial use
**AGPL-3.0-or-later**, or a **commercial licence** for closed-source products, internal pipelines and hosted services -
see [COMMERCIAL.md](COMMERCIAL.md). **Open for talks** about commercial licences, integration into document-AI, RAG and
LLM-ingestion pipelines, security reviews and partnerships: **Novain Shibu** · georgeshibu380@gmail.com ·
[github.com/novain-shibu](https://github.com/novain-shibu) · [linkedin.com/in/novain-shibu](https://www.linkedin.com/in/novain-shibu).
`bench/text/` and `bench/results/` contain Wikipedia text (CC BY-SA 4.0). Parts of this work were produced with AI
assistance (Claude, Anthropic), directed and reviewed by the author. Cite via [CITATION.cff](CITATION.cff).
