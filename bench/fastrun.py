"""Parallel scoring: N persistent workers (font tables built once per worker), results written as they finish.
usage: fastrun.py <module> <folder> [workers]"""
import sys, json, time, concurrent.futures as cf
mod, folder = sys.argv[1], sys.argv[2]; nw = int(sys.argv[3]) if len(sys.argv) > 3 else 5
import scorelib
def _init(m, f):
    scorelib.init(m, f)
def _one(i):
    try:
        return scorelib.score(i)
    except Exception as e:
        return {"i": i, "timeout_or_error": True, "error": repr(e)[:300]}
if __name__ == "__main__":
    n = len(json.load(open(folder + "/answer_key.json", encoding="utf-8")))
    # interleave scripts so every worker builds each font's tables once and the load is even
    order = sorted(range(n), key=lambda i: (i % 30, i))
    import os
    done = set()
    if os.environ.get("RESUME") and os.path.exists(folder + "/results_part1.jsonl"):
        done = {json.loads(l)["i"] for l in open(folder + "/results_part1.jsonl", encoding="utf-8") if l.startswith("{")}
        order = [i for i in order if i not in done]
    t0 = time.time()
    with open(folder + "/results.jsonl", "a" if done else "w", encoding="utf-8") as out, cf.ProcessPoolExecutor(nw, initializer=_init, initargs=(mod, folder)) as ex:
        futs = {ex.submit(_one, i): i for i in order}
        for f in cf.as_completed(futs):
            try:
                row = f.result(timeout=600)
            except Exception as e:
                row = {"i": futs[f], "timeout_or_error": True, "error": repr(e)[:200]}
            out.write(json.dumps(row, ensure_ascii=False) + "\n"); out.flush()
        out.write("FINISHED %.0fs\n" % (time.time() - t0))
