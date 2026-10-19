"""Scoring as a function (same logic as score53d_one.py) for persistent parallel workers."""
import sys, json, collections, time, pickle, os, hashlib, difflib, re, unicodedata
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import importlib, pymupdf, score52 as SC
S = None; FOLDER = None
HY = str.maketrans({"‐": "-", "‑": "-", "­": "-", "‒": "-", "–": "-", "−": "-"})
def norm(t):
    t = unicodedata.normalize("NFC", t.translate(HY).replace("‌", "").replace("‍", ""))
    out = []
    for ch in t:  # a mark drawn twice in the same place is seen once
        if out and ch == out[-1] and unicodedata.category(ch)[0] == 'M':
            continue
        out.append(ch)
    return ''.join(out)
def toks(t): return SC.words(norm(t))
_IDX = {}
def init(mod, folder):
    """Worker start: load SeenRead once; one face object per font program for the worker's lifetime (tables reused)."""
    global S, FOLDER
    S = importlib.import_module(mod); FOLDER = folder
    orig = S.E.EmbFace; memo = {}
    def face(buf):
        key = hashlib.sha1(buf).hexdigest()
        if key not in memo: memo[key] = orig(buf)
        return memo[key]
    S.E.EmbFace = face
def score(i):
    k = json.load(open(FOLDER + "/answer_key.json", encoding="utf-8"))[i]
    t0 = time.time()
    tkey = tuple(k["trusted"])
    if tkey in _IDX:
        idx = _IDX[tkey]
    else:
        cp = FOLDER + "/_trusted_" + hashlib.sha1("|".join(k["trusted"]).encode()).hexdigest()[:10] + ".pkl"
        if os.path.exists(cp):
            rs = pickle.load(open(cp, "rb")); idx = [(l, d, tt, r) for (l, d, tt), r in zip(S.D._ref_fonts(k["trusted"]), rs)]
        else:
            idx = S.trusted_index(k["trusted"]); pickle.dump([x[3] for x in idx], open(cp, "wb"))
        _IDX[tkey] = idx
    r = S.verify(k["file"], idx, keep=10**6)
    truth = toks(k["visible"])
    seq, owner = [], []  # SeenRead's human tokens, each tagged with its word index
    for wi, (verdict, mach, hum) in enumerate(r["detail"]):
        for t in toks(hum) if verdict != "UNKNOWN" else ["\u2047"]:
            seq.append(t); owner.append(wi)
    ok_tok = [False] * len(seq)
    sm = difflib.SequenceMatcher(None, seq, truth, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for j in range(n): ok_tok[a + j] = True
    word_ok = collections.defaultdict(lambda: True)
    for j, wi in enumerate(owner):
        word_ok[wi] &= ok_tok[j]
    cnt = collections.Counter(); errs = []
    for wi, (verdict, mach, hum) in enumerate(r["detail"]):
        if not toks(hum) and verdict != "UNKNOWN":
            continue
        if verdict == "UNKNOWN":
            cnt["unknown"] += 1; errs.append(("UNKNOWN", mach, hum))
        elif word_ok[wi]:
            cnt["correct"] += 1; cnt["correct_" + verdict] += 1
        else:
            cnt["harmful_" + verdict] += 1; errs.append((verdict, mach, hum))
    matched = sum(n for _, _, n in sm.get_matching_blocks())
    hid = k.get("hidden"); hs = "".join(r["hidden_text_machines_read"].split())
    row = {"i": i, "file": k["file"], "kind": k["kind"], "script": k["script"], "font": k.get("font"), "words": dict(cnt),
           "truth_tokens": len(truth), "truth_tokens_matched": matched,
           "hidden_ok": ("".join(hid[1].split()) in hs) if hid else None, "hidden_reported": bool(hs),
           "errors": errs[:30], "sec": round(time.time() - t0, 1)}
    return row
