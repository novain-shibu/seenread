"""Bag-of-words exact-word recall; same words() as unshape_multi4.words (PREREG_51 scorer), ZWJ/ZWNJ stripped."""
import collections, re, sys, unicodedata
def words(t):
    t = unicodedata.normalize("NFC", t.replace("\u200d", "").replace("\u200c", ""))
    return [w for w in re.split(r"[\s\u0964\u0965.,;:!?()\[\]\"'“”‘’\-–—/]+", t) if w]
def score(truth, dec):
    g = collections.Counter(words(truth)); c = collections.Counter(words(dec))
    return sum(min(n, c[w]) for w, n in g.items()), sum(g.values()), [w for w in g if c[w] < g[w]]
