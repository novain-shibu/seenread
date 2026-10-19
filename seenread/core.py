# Copyright (c) 2026 Novain Shibu. AGPL-3.0-or-later, or a commercial licence (see COMMERCIAL.md).
"""SeenRead v2: render-equivalence proof of the text a human sees, word by word, without OCR or rasterising.

A claimed text is ACCEPTED for a word only if the shaping engine, laying it out with the TRUSTED font, puts the same glyphs
at the same positions (relative, in em units) as the PDF draws them. Glyph identities come from exact outline+advance
matches against trusted fonts (the PDF's own font tables are never trusted). Candidates per word: the text a machine
extracts, and the decoder's reconstructions from the glyphs in file order and in left-to-right order.
  SAME      - the machine's text is render-equivalent to the drawing
  DIFFERENT - the machine's text is not; another text is render-equivalent (given as human_sees)
  UNKNOWN   - nothing proven (unmatched glyphs, or no candidate lays out identically)
usage: seenread2.py file.pdf --trusted font1 [font2 ...] [--json]
"""
import collections, io, json, sys, unicodedata
_a = sys.argv[1:]
sys.argv = sys.argv[:1]
import pymupdf
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from unshape import decode as D
E = D.E
TOL = 0.06  # em: position tolerance (different shapers round mark offsets differently)


def trusted_index(paths):
    out = []
    for label, data, tt in D._ref_fonts(paths):
        rs = collections.defaultdict(list)
        for g in tt.getGlyphOrder():
            try:
                rs[D._sig(tt, g)].append(g)
            except Exception:
                pass
        out.append((label, data, tt, dict(rs)))
    return out


def _layout(fc, text):
    """[(gid, x_em, cluster)] of the text laid out by HarfBuzz with the trusted face."""
    b = hb.Buffer(); b.add_str(text); b.guess_segment_properties(); hb.shape(fc.hbf, b, {})
    upm = fc._upm; pen = 0; out = []
    for gi, gp in zip(b.glyph_infos, b.glyph_positions):
        out.append((gi.codepoint, (pen + gp.x_offset) / upm, gi.cluster)); pen += gp.x_advance
    return out


def _equiv(fc, text, drawn, lang, file_order=None):
    """drawn = [(gid, x_em)]. True if the text lays out to the same glyphs, same arrangement inside each cluster and the
    same cluster order (any producer). If the face carries a learned producer delta (Word + Nirmala), that variant is
    accepted only if the rewritten glyph sequence equals the drawn glyphs exactly in left-to-right order."""
    if not text:
        return False
    lay = _layout(fc, text)
    if _pos_equiv(fc, lay, drawn):
        return True
    rules = getattr(fc, "rules", {}).get(lang)
    if rules and file_order is not None:
        g = E.U.rewrite(tuple(x[0] for x in lay), rules)
        return len(g) == len(file_order) and [_vclass(fc, x) for x in g] == [_vclass(fc, x) for x in file_order]
    return False


def _vclass(fc, g):
    """Variant class of a glyph: contextual forms of ONE character share a class; glyphs that the trusted cmap maps to
    different characters (e.g. 'O' and 'o', joined by small-caps lookups) never do."""
    vc = fc.__dict__.get("_sr_vc")
    if vc is None:
        direct = {}
        for cp, gid in fc.cmap.items():
            direct.setdefault(gid, set()).add(cp)
        vc = fc._sr_vc = {}
        for gid, rep in fc.norm.items():
            if gid in direct and rep in direct and not (direct[gid] & direct[rep]):
                continue  # both are characters in their own right: not variants of each other
            vc[gid] = rep
    return vc.get(g, g)


def _pos_equiv(fc, lay, drawn):
    if len(lay) != len(drawn):
        return False
    # match laid-out glyphs to drawn glyphs: same glyph (variant class), in left-to-right order within each glyph
    by_g = collections.defaultdict(list)
    for gid, x in drawn:
        by_g[_vclass(fc, gid)].append(x)
    for v in by_g.values():
        v.sort()
    lay_g = collections.defaultdict(list)
    for gid, x, cl in lay:
        lay_g[_vclass(fc, gid)].append((x, cl))
    if by_g.keys() != lay_g.keys() or any(len(by_g[k]) != len(lay_g[k]) for k in by_g):
        return False
    delta = collections.defaultdict(list); cx_lay = collections.defaultdict(list); cx_drw = collections.defaultdict(list)
    for k, items in lay_g.items():
        for (x, cl), xd in zip(sorted(items), by_g[k]):
            delta[cl].append(xd - x); cx_lay[cl].append(x); cx_drw[cl].append(xd)
    # inside a cluster the arrangement must be identical; between clusters only the order may not change
    if any(max(d) - min(d) > TOL for d in delta.values()):
        return False
    order_lay = [cl for cl in sorted(cx_lay, key=lambda c: (min(cx_lay[c]), c))]
    order_drw = [cl for cl in sorted(cx_drw, key=lambda c: (min(cx_drw[c]), c))]
    return order_lay == order_drw


FACE_BY_LABEL = {}
_SP = {}


def spaces_of(tt):
    k = id(tt)
    if k not in _SP:
        _SP[k] = {tt.getGlyphID(n) for cp, n in (tt.getBestCmap() or {}).items() if chr(cp).isspace() and cp not in (0x200B, 0xFEFF)}
    return _SP[k]
CONFLICTS = []  # same span font name, same glyph number, different glyph in two subset copies (cannot tell apart)


def _swap_orders(seq, near=0.25, cap=16):
    """Orders of a word's glyphs with overlapping neighbours (marks within `near` em) swapped, up to `cap` orders:
    producers write stacked marks in different orders, the decoder's tables use the shaping engine's order."""
    pairs = [i for i in range(len(seq) - 1) if abs(seq[i][2] - seq[i + 1][2]) < near]
    out = []
    for mask in range(1, min(1 << len(pairs), cap + 1)):
        s2 = list(seq); used = set()
        for b, i in enumerate(pairs):
            if mask >> b & 1 and i not in used and i + 1 not in used:
                s2[i], s2[i + 1] = s2[i + 1], s2[i]; used |= {i, i + 1}
        if s2 != list(seq) and s2 not in out:
            out.append(s2)
    return out


def _mark_moves(fc, seq, cap=32):
    """Orders with each zero-width glyph (reph, vowel sign, nasal mark: advance < 0.15 em in the trusted font) moved
    one or two places: the only glyphs whose order in the file differs between producers."""
    tt = fc._tt; upm = fc._upm; order = tt.getGlyphOrder(); hm = tt["hmtx"].metrics
    adv = lambda g: hm[order[g]][0] / upm if 0 <= g < len(order) else 1.0
    marks = [i for i, t in enumerate(seq) if adv(t[0]) < 0.15]
    out = []
    for i in marks:
        for d in (-2, -1, 1, 2):
            j = i + d
            if 0 <= j < len(seq):
                s2 = list(seq); t = s2.pop(i); s2.insert(j, t)
                if s2 not in out:
                    out.append(s2)
    base = list(out)
    for a in base:  # two moves (e.g. a reph and a pre-base vowel sign in the same word)
        for i in [k for k, t in enumerate(a) if adv(t[0]) < 0.15]:
            for d in (-2, -1, 1, 2):
                j = i + d
                if 0 <= j < len(a) and len(out) < cap:
                    s2 = list(a); t = s2.pop(i); s2.insert(j, t)
                    if s2 not in out:
                        out.append(s2)
    return out[:cap]


def _word_block(fc, w):
    """Majority Indic block (0x0900..0x0D80) of the characters the word's trusted glyphs show; None if none."""
    gl = fc.__dict__.get("_sr_gl")
    if gl is None:
        gl = fc._sr_gl = D._glyph_letters(fc)
    cnt = collections.Counter()
    for g, _, _, _ in w:
        for chs in gl.get(g, ()):
            for ch in chs:
                cp = ord(ch)
                if 0x0900 <= cp < 0x0E00 and unicodedata.category(ch)[0] in "LM":
                    cnt[cp & ~0x7F] += 1
    return cnt.most_common(1)[0][0] if cnt else None


def _reorder_variants(c, lang):
    """The same letters with the reph (RA+virama) or a pre-base vowel sign moved to every other position."""
    L, M, V = E.U.classes(lang)
    virama = V[0] if V else ""
    ra = {"hi": "र", "bn": "র", "gu": "ર", "pa": "ਰ", "or": "ର", "ta": "ர", "te": "ర",
          "kn": "ರ", "ml": "ര", "si": "ර"}.get(lang, "")
    pre = {"ि", "ি", "ে", "ৈ", "િ", "ਿ", "େ", "ெ", "ே", "ை", "െ",
           "േ", "ൈ", "ෙ"}
    out = []
    units = [ra + virama] if ra and virama else []
    for u in units + sorted(pre):
        k = c.find(u)
        while k >= 0:
            rest = c[:k] + c[k + len(u):]
            for j in range(len(rest) + 1):
                v = rest[:j] + u + rest[j:]
                if v != c and v not in out:
                    out.append(v)
            k = c.find(u, k + 1)
    return out[:200]


def _fonts(doc, trusted):
    """span font name -> (face, remap gid->trusted gid, block) for every embedded font matched to a trusted font."""
    res, seen = {}, set()
    for pno in range(len(doc)):
        for xref, ext, typ, base, *_ in doc.get_page_fonts(pno, full=True):
            if xref in seen or ext not in ("ttf", "otf"):
                continue
            seen.add(xref)
            try:
                sub = TTFont(io.BytesIO(doc.extract_font(xref)[3]))
            except Exception:
                continue
            best = None
            for label, data, tt, rs in trusted:
                remap, m, tot = {}, 0, 0
                for i, g in enumerate(sub.getGlyphOrder()):
                    try:
                        s = D._sig(sub, g)
                    except Exception:
                        continue
                    c = rs.get(s, [])
                    if not s[0]:  # empty outline: identical-looking blanks (space, no-break space, CR...) -> prefer space
                        if c:
                            sp = [x for x in c if tt.getGlyphID(x) in spaces_of(tt)]
                            remap[i] = tt.getGlyphID(sp[0] if sp else c[0])
                        continue
                    tot += 1
                    if c:
                        m += 1; remap[i] = tt.getGlyphID(c[0])
                if tot and (best is None or m / tot > best[2]):
                    best = (label, data, m / tot, remap, tt)
            if not best or best[2] < 0.5:
                continue
            label, data, rate, remap, tt = best
            fc = FACE_BY_LABEL.get(label)
            if fc is None:
                fc = E.EmbFace(data); fc._upm = tt["head"].unitsPerEm; fc._tt = tt; fc._buf = data
                FACE_BY_LABEL[label] = fc
            else:  # another subset copy of the same font (Word writes several): same face, glyph maps merged below
                names = {base.split("+")[-1]}
                try:
                    names |= {str(sub["name"].getDebugName(i)) for i in (4, 6) if sub["name"].getDebugName(i)}
                except Exception:
                    pass
                for nm in names:
                    k = E.norm_name(nm)
                    if k in res and res[k][0] is fc:
                        merged = res[k][1]
                        for gi, rg in remap.items():
                            if merged.setdefault(gi, rg) != rg:
                                CONFLICTS.append((nm, gi))
                    else:
                        res[k] = (fc, dict(remap), label, rate)
                continue
            cps = [cp for cp in (sub.getBestCmap() or {}) if 0x0900 <= cp < 0x0E00]
            own = collections.Counter(cp & ~0x7F for cp in cps)
            if own:
                fc.block = own.most_common(1)[0][0]
            else:
                rc = {g: cp for cp, g in fc.cmap.items() if 0x0900 <= cp < 0x0E00}
                blk = collections.Counter(rc[g] & ~0x7F for g in remap.values() if g in rc)
                fc.block = blk.most_common(1)[0][0] if blk and sum(blk.values()) >= 5 else None
            if "Nirmala" in label:
                style = "Bold" if "Bold" in label else "Regular"
                fc.rules = dict(E.U.RULESETS.get(style, {}))
                fc.wshape = (lambda f: (lambda t, lang: E.U.rewrite(f.shape(t), f.rules.get(lang, ()))))(fc)
            names = {base.split("+")[-1]}
            try:
                names |= {str(sub["name"].getDebugName(i)) for i in (4, 6) if sub["name"].getDebugName(i)}
            except Exception:
                pass
            for nm in names:
                res[E.norm_name(nm)] = (fc, remap, label, rate)
    return res


def _invisible(span, bbox, page):
    """True if a human cannot see this glyph: invisible render mode, transparent, tiny, white, or off the page."""
    if span.get("type") == 3 or span.get("opacity", 1) == 0 or span["size"] < 1.0:
        return True
    c = span.get("color") or ()
    if c and min(c) > 0.97 and len(c) in (1, 3):  # white text (pages are assumed white; colour backgrounds: TODO)
        return True
    r = page.rect
    x0, y0, x1, y1 = bbox
    return x1 < r.x0 or x0 > r.x1 or y1 < r.y0 or y0 > r.y1


def _words(doc, fonts):
    """Words of decodable glyphs: [(fc, [(trusted_gid, unicode_str, x_em_abs, stream_index)])], split at spaces/gaps."""
    words, cur, curf, k = [], [], None, 0
    for page in doc:
        for span in page.get_texttrace():
            hit = fonts.get(E.norm_name(span["font"]))
            for u, gid, origin, bbox in span["chars"]:
                k += 1
                ch = chr(u) if u > 0 else ""
                if gid < 0:  # extra character of a multi-character glyph
                    if cur and ch:
                        g0, u0, x0, i0 = cur[-1]; cur[-1] = (g0, u0 + ch, x0, i0)
                    continue
                if hit is None:
                    if _invisible(span, bbox, page):
                        HIDDEN.append(ch)
                    if cur: words.append((curf, cur)); cur = []
                    continue
                fc, remap, label, rate = hit
                rg = remap.get(gid, -1)
                newline = cur and abs(origin[1] - cur_y) > 0.6 * span["size"]
                if (curf is not None and fc is not curf) or newline:
                    words.append((curf, cur)); cur = []
                is_space = rg in D._spaces(fc) or rg == fc.space  # trusted glyph identity only, never the PDF label
                if is_space:
                    if cur: words.append((fc, cur)); cur = []
                    continue
                if _invisible(span, bbox, page):
                    HIDDEN.append(ch); continue
                cur.append((rg, ch, origin[0] / span["size"], k)); curf = fc; cur_y = origin[1]
    if cur:
        words.append((curf, cur))
    return words


HIDDEN = []


def verify(pdf, trusted, keep=200):
    doc = pymupdf.open(pdf); HIDDEN.clear()
    FACE_BY_LABEL.clear(); CONFLICTS.clear(); fonts = _fonts(doc, trusted)
    rep = {"detail": [], "pdf": pdf, "fonts": sorted({(v[2], round(v[3], 4)) for v in fonts.values()}), "words": collections.Counter(),
           "different": [], "unknown": [], "human_text": []}
    for fc, w in _words(doc, fonts):
        machine = unicodedata.normalize("NFC", "".join(u for _, u, _, _ in w))
        blk = _word_block(fc, w)  # script from the trusted identities of this word's glyphs (multi-script fonts)
        if blk is not None:
            fc.block = blk
        lang = E.SCRIPT[fc.block][0] if (blk is not None and fc.block in E.SCRIPT) else None
        if lang is None:  # non-Indic: candidate = the characters of the trusted glyphs, left to right
            if any(g < 0 for g, _, _, _ in w):
                rep["words"]["UNKNOWN"] += 1; rep["unknown"].append(machine); rep["human_text"].append("?"); rep["detail"].append(("UNKNOWN", machine, "?")); continue
            drawn = [(g, x) for g, _, x, _ in w]
            if _equiv(fc, machine, drawn, None):
                rep["words"]["SAME"] += 1; rep["human_text"].append(machine); rep["detail"].append(("SAME", machine, machine)); continue
            gl = D._glyph_letters(fc)
            cand = ""
            for g, u, x, k in sorted(w, key=lambda t: (t[2], t[3])):
                opts = sorted(gl.get(g, ()), key=lambda c: (unicodedata.category(c[0]) == "Cf", len(c), (ord(c[0]) >> 7) != (ord(u[0]) >> 7 if u else 0), c))
                cand += opts[0] if opts else "?"
            if "?" not in cand and _equiv(fc, cand, drawn, None):
                rep["words"]["DIFFERENT"] += 1; rep["human_text"].append(cand); rep["detail"].append(("DIFFERENT", machine, cand))
                if len(rep["different"]) < keep:
                    rep["different"].append({"machine_reads": machine, "human_sees": cand})
            else:
                rep["words"]["UNKNOWN"] += 1; rep["human_text"].append("?"); rep["detail"].append(("UNKNOWN", machine, "?"))
                if len(rep["unknown"]) < keep:
                    rep["unknown"].append({"machine_reads": machine, "candidates": [cand]})
            continue
        if any(g < 0 for g, _, _, _ in w):
            rep["words"]["UNKNOWN"] += 1; rep["unknown"].append(machine); rep["human_text"].append("?"); rep["detail"].append(("UNKNOWN", machine, "?")); continue
        drawn = []  # a glyph drawn again at the same place (simulated bold) is seen once
        for g, _, x, _ in w:
            if not any(g == g2 and abs(x - x2) < 0.01 for g2, x2 in drawn):
                drawn.append((g, x))
        if _equiv(fc, machine, drawn, lang, [g for g, _ in sorted(drawn, key=lambda t: t[1])]):
            rep["words"]["SAME"] += 1; rep["human_text"].append(machine); rep["detail"].append(("SAME", machine, machine)); continue
        cands = []
        dd = [t for t in w if any(t[0] == g and abs(t[2] - x) < 1e-9 for g, x in drawn)]
        dd = [t for i, t in enumerate(dd) if not any(t[0] == q[0] and abs(t[2] - q[2]) < 0.01 for q in dd[:i])]
        faces_to_try = [fc]
        if getattr(fc, "rules", None):  # producer quirks known (Word): also decode as plain HarfBuzz would shape it
            tw = fc.__dict__.get("_sr_plain")
            if tw is None:
                tw = fc._sr_plain = E.EmbFace(fc._buf)
            tw.block = fc.block
            faces_to_try.append(tw)
        orders = [w, sorted(w, key=lambda t: (t[2], t[3])), dd, sorted(dd, key=lambda t: (t[2], t[3]))]
        orders += _swap_orders(dd) + _swap_orders(sorted(dd, key=lambda t: (t[2], t[3])))
        orders += _mark_moves(fc, sorted(dd, key=lambda t: (t[2], t[3]))) + _mark_moves(fc, dd)
        for face in faces_to_try:
            for order in orders:
                st = collections.Counter()
                c = D._decode([(g, u if len(u) != 1 else ord(u)) for g, u, _, _ in order], face, st)
                if c not in cands:
                    cands.append(c)
        inv = fc.__dict__.get("_sr_inv")
        if inv is None:  # trusted glyph -> the single character the font maps to it (digits, standalone signs)
            inv = collections.defaultdict(set)
            for cp, g in fc.cmap.items():
                inv[g].add(chr(cp))
            inv = fc._sr_inv = {g: next(iter(v)) for g, v in inv.items() if len(v) == 1}
        for order in (dd, sorted(dd, key=lambda t: (t[2], t[3]))):
            direct = unicodedata.normalize("NFC", "".join(inv.get(g, u) for g, u, _, _ in order))
            if direct not in cands:
                cands.append(direct)
        vo = [g for g, _ in sorted(drawn, key=lambda t: t[1])]
        ok = [c for c in cands if _equiv(fc, c, drawn, lang, vo)]
        if not ok:  # placements of the reph and of the pre-base vowel sign are where visual and logical order differ
            for c in list(cands):
                for v in _reorder_variants(c, lang):
                    if v not in cands and _equiv(fc, v, drawn, lang, vo):
                        ok.append(v); break
                if ok:
                    break
        if ok:
            rep["words"]["DIFFERENT"] += 1; rep["human_text"].append(ok[0]); rep["detail"].append(("DIFFERENT", machine, ok[0]))
            if len(rep["different"]) < keep:
                rep["different"].append({"machine_reads": machine, "human_sees": ok[0]})
        else:
            rep["words"]["UNKNOWN"] += 1; rep["human_text"].append("?"); rep["detail"].append(("UNKNOWN", machine, "?"))
            if len(rep["unknown"]) < keep:
                rep["unknown"].append({"machine_reads": machine, "candidates": cands})
    rep["words"] = dict(rep["words"])
    rep["hidden_text_machines_read"] = "".join(HIDDEN)
    rep["glyph_map_conflicts"] = len(CONFLICTS)
    return rep


if __name__ == "__main__":
    i = _a.index("--trusted"); pdf = _a[0]; as_json = "--json" in _a
    r = verify(pdf, trusted_index([x for x in _a[i + 1:] if x != "--json"]))
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"== {pdf}\n fonts: {r['fonts']}\n words: {r['words']}\n hidden (machines read, humans cannot see): {r['hidden_text_machines_read'][:200]!r}")
        for d in r["different"][:15]:
            print(f"   machine reads: {d['machine_reads']!r:28}  human sees: {d['human_sees']!r}")
        for d in r["unknown"][:8]:
            print(f"   UNKNOWN: {d}")
