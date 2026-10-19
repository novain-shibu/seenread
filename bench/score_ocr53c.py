import json, sys, collections, difflib
sys.path.insert(0, ".")
import pymupdf, scorelib as L
keys = json.load(open("blind53c/answer_key.json", encoding="utf-8"))
ocr = json.load(open("ocr53c/out/ocr53c.json", encoding="utf-8"))
def flags(seq, truth):
    ok = [False] * len(truth)
    for a, b, n in difflib.SequenceMatcher(None, seq, truth, autojunk=False).get_matching_blocks():
        for j in range(n): ok[b + j] = True
    return ok
agg = collections.defaultdict(collections.Counter)
for k in keys:
    png = k["file"].split("/")[-1][:-4] + ".png"; truth = L.toks(k["visible"])
    mach = L.toks(pymupdf.open(k["file"])[0].get_text()); mok = flags(mach, truth)
    for psm in ("3", "6"):
        ook = flags(L.toks(ocr[png][psm]), truth)
        c = agg[(k["script"], psm)]
        c["truth"] += len(truth); c["ocr_ok"] += sum(ook); c["mach_ok"] += sum(mok)
        c["lie_tokens"] += sum(1 for m in mok if not m)
        c["lie_caught"] += sum(1 for m, o in zip(mok, ook) if not m and o)       # OCR reads the visible word -> mismatch flagged correctly
        c["clean_tokens"] += sum(1 for m in mok if m)
        c["false_alarm"] += sum(1 for m, o in zip(mok, ook) if m and not o)     # OCR misreads a clean word -> false flag
for sc in ("latin", "hindi", "bengali", "tamil"):
    best = max(("3", "6"), key=lambda p: agg[(sc, p)]["ocr_ok"])
    c = agg[(sc, best)]
    print(f"{sc:8s} OCR(psm {best}) visible words matched {100*c['ocr_ok']/c['truth']:.2f}% | plain extraction {100*c['mach_ok']/c['truth']:.2f}% | "
          f"OCR-vs-extraction detector: catches {c['lie_caught']}/{c['lie_tokens']} split words ({100*c['lie_caught']/max(1,c['lie_tokens']):.1f}%), "
          f"false alarms {c['false_alarm']}/{c['clean_tokens']} clean words ({100*c['false_alarm']/max(1,c['clean_tokens']):.2f}%)")
