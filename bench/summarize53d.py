import json, sys, collections
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.startswith("{")]
by = collections.defaultdict(collections.Counter)
for r in rows:
    keys = ["ALL"] if r.get("timeout_or_error") else [r["script"], "ALL"]
    for k in keys:
        c = by[k]
        if r.get("timeout_or_error"): c["timeouts"] += 1; continue
        c["docs"] += 1
        for a, b in r["words"].items(): c[a] += b
        c["tt"] += r["truth_tokens"]; c["tm"] += r["truth_tokens_matched"]
        if r["hidden_ok"] is not None: c["hd"] += 1; c["hok"] += r["hidden_ok"]
        if r["kind"] == "control": c["ctl"] += 1; c["ctl_fh"] += r["hidden_reported"]
for k, c in sorted(by.items()):
    w = c["correct"] + c["unknown"] + c["harmful_SAME"] + c["harmful_DIFFERENT"]
    p = lambda a: f"{100*a/w:.2f}%" if w else "-"
    print(f"{k:8s} docs {c['docs']:3d} words {w:5d} | correct {p(c['correct'])} | harmful: missed(SAME-wrong) {c['harmful_SAME']} wrong-DIFFERENT {c['harmful_DIFFERENT']} | UNKNOWN {c['unknown']} | "
          f"truth tokens matched {100*c['tm']/max(1,c['tt']):.2f}% | hidden {c['hok']}/{c['hd']} | controls false-hidden {c['ctl_fh']}/{c['ctl']} | timeouts {c['timeouts']}")
