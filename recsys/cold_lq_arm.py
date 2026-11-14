"""cold_lq_arm — bounded, fail-closed quality corrections for products launched today, served as ONE lfm arm (T-028).

Reuses, without changing them: d4xn's `cold_lq.ColdLQ` (T-CS01, PR #17), Javi's `live_quality.LiveQuality` (K = 100,
log q = a_sub + 2 log rate) and the `cold_items` attribute prior. Nothing is re-estimated or tuned here.

    COR = cold_lq_arm.Corrector()                       # initialize(); .ready is False without the attribute prior
    c = COR.corrections(QR.q, QR.lq, cat, BASE["item"], T.item_frame(), AP.cold.desc, lq0=LF.lq0)   # refresher()
    LF.set_catalog(cat, unavail, AP.aff, QR.lq, d130.HC, lq_cold=c)                                 # c: {product: lq}

`c` only holds products that (1) arrived through a `new_product` update (they have a description in `desc`),
(2) have no historical quality in qrank, (3) have complete metadata and (4) got a finite prior prediction. For those:

    corrected lq = clip(cold_lq estimate, incumbent lq - log 20, incumbent lq + log 20)

where the incumbent is what lfm uses today (qrank's subcategory median). The bound is a predeclared risk limit for the
first trial (D-281), not a tuned parameter. Everything else keeps the incumbent quality: established products are never
in `c`, and on any failure (no prior, prior error, wrong length, bad metadata, non-finite numbers, any exception) the
affected products, or all of them, are left out. LiveQuality's own no-prior fallback (subcategory rate) is never used:
E-CS01c found it worse than the median (I-CS02).

No RawTree call, no fitting: one vectorised pass over the catalogue per refresh, in the refresher thread.
`QR.q` / `QR.lq` are only read. The arm applies the corrections on product/category requests with recent views only
(lfm.LiveFit.scores); home is untouched.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

if __package__:
    from . import cold_items, cold_lq, live_quality
else:
    import cold_items, cold_lq, live_quality

BOUND = math.log(20.0)          # max |corrected lq - incumbent lq| in the first trial
REQUIRED = ("category", "sub", "brand", "price")


class _GuardedPrior:
    """Wraps the attribute prior so LiveQuality can never fall back silently: a failure is recorded (and re-raised, the
    whole refresh is then discarded); non-finite or non-positive predictions are recorded per product and replaced by
    the median prediction only so the pass can finish (those products never get a correction)."""

    def __init__(self, prior):
        self.prior, self.failed, self.bad = prior, False, set()

    def reset(self): self.failed, self.bad = False, set()

    def __call__(self, cat):
        try:
            pr = np.asarray(self.prior(cat), float)
            if pr.shape != (len(cat),): raise ValueError("prior length")
        except Exception:
            self.failed = True
            raise
        ok = np.isfinite(pr) & (pr > 0)
        if not ok.any():
            self.failed = True
            raise ValueError("no finite prior prediction")
        self.bad = set(cat.index[~ok])
        return np.where(ok, pr, np.median(pr[ok]))


class Corrector:
    def __init__(self, prior="default", bound=BOUND):
        p = live_quality.default_prior() if prior == "default" else prior
        self.guard = _GuardedPrior(p) if p is not None else None
        self.clq = cold_lq.ColdLQ(live_quality.LiveQuality(prior=self.guard)) if self.guard is not None else None
        self.bound = float(bound)
        self.last = {}            # diagnostics of the last call (counts by reason), for logs and tests

    @property
    def ready(self): return self.clq is not None

    def eligible(self, q, cat, desc) -> list:
        """Products launched through a new_product update, without history quality, with complete metadata."""
        out = []
        have = set(cat.index)
        for p in sorted(desc):                                  # only products that arrived through a new_product update
            if p not in have or (q.get(p) or 0) > 0: continue
            r = cat.loc[p]
            try: price = float(r["price"])
            except Exception: continue
            if any(c not in cat.columns or pd.isna(r[c]) or r[c] == "" for c in REQUIRED): continue
            if not (math.isfinite(price) and price > 0) or not cold_items.attrs(desc.get(p) or ""): continue
            out.append(p)
        return out

    def corrections(self, q: dict, lq: dict, cat: pd.DataFrame, hist_item, live_item, desc: dict, lq0: float = 0.0) -> dict:
        """{product: corrected lq}; {} when nothing can be corrected safely. Never raises, never mutates its inputs."""
        self.last = {"eligible": 0, "corrected": 0, "clipped": 0, "rejected": 0, "reason": None}
        try:
            if not self.ready: self.last["reason"] = "no_prior"; return {}
            if cat.index.has_duplicates: self.last["reason"] = "duplicate_ids"; return {}
            desc = desc or {}
            elig = self.eligible(q, cat, desc)
            self.last["eligible"] = len(elig)
            if not elig: self.last["reason"] = "no_new_products"; return {}
            self.guard.reset()
            est = self.clq.estimate(q, cat, hist_item, live_item, desc)
            if self.guard.failed: self.last["reason"] = "prior_failed"; return {}
            out = {}
            for p in elig:
                v, inc = est.get(p), float(lq.get(p, lq0))
                if p in self.guard.bad or v is None or not math.isfinite(v) or not math.isfinite(inc):
                    self.last["rejected"] += 1; continue
                c = min(max(float(v), inc - self.bound), inc + self.bound)
                self.last["clipped"] += c != v
                out[p] = c
            self.last["corrected"] = len(out)
            return out
        except Exception as e:
            print("cold_lq_arm failed, every product keeps the incumbent quality:", type(e).__name__, e, flush=True)
            self.last["reason"] = "error"
            return {}
