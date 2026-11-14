"""cold_lq — give lfm (the live champion) a real quality for products launched today (T-CS01, I-CS01, E-CS01).

The gap: lfm reads product quality from `QR.lq` = log(q), q = qrank's history-only carousel quality. A product
launched today has no q, so qrank.set_catalog gives it the MEDIAN q of its subcategory, all day, whatever it does live.
Observed 14 Nov 14:35-15:40 UTC: new products got 2.4% of organic views but 0.15% of our impressions (E-CS01b).

Javi already built the estimator (T-018, live_quality.py, I-183): organic purchases/view = attribute prior
(cold_items GLM) shrunk with live views (K=100), turned into carousel quality with log q = a_sub + 2 log rate. It is
OFF in production and, when on, only feeds plain qrank slates (QR2), never lfm. This module only REUSES it:

    CLQ = cold_lq.ColdLQ()                                            # initialize(): one live_quality.LiveQuality
    lq_lfm = CLQ.lq_for_lfm(QR, cat, BASE["item"], LIVE.item_frame(), AP.cold.desc)   # refresher(), before LF.set_catalog
    LF.set_catalog(cat, unavail, AP.aff, lq_lfm, d130.HC)             # instead of QR.lq

lq_for_lfm returns QR.lq itself (same object, nothing changes) unless data/coldlq.json says {"mode": "on"}. When on:
a copy of QR.lq where ONLY products without a history q get live_quality's estimate; established products, qrank,
QR.lq and qrank's slates are untouched. No RawTree calls (the refresher already has catalogue, history and live
counts), no writes, ~0.1 s per refresh. Any error -> QR.lq unchanged.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

if __package__:
    from . import live_quality
else:
    import live_quality

HERE = Path(__file__).resolve().parent
CONF = HERE / "data" / "coldlq.json"


def mode(path=None):
    try:
        m = json.loads(Path(path or CONF).read_text()).get("mode", "off")
        return m if m in ("off", "on") else "off"
    except Exception:
        return "off"


class ColdLQ:
    def __init__(self, lq: live_quality.LiveQuality | None = None):
        self.lq = lq if lq is not None else live_quality.LiveQuality(prior=live_quality.default_prior())
        self.last = {}                       # product -> lq given to lfm on the last 'on' refresh (for logs/tests)

    def estimate(self, q: dict, cat, hist_item=None, live_item=None, desc=None) -> dict:
        """lq (= log of qrank-scale quality, clipped like qrank.set_catalog) for every catalogue product without a
        history q. Old products are not returned. cat: index product id; category, sub, brand, price."""
        desc = desc or {}
        c = cat.assign(description=[desc.get(i, "") for i in cat.index])
        known = {p for p, v in q.items() if v and v > 0}
        self.lq.update(c, hist_item, live_item, None, known=known)     # window=None: no hot-subcategory multipliers
        q2 = self.lq.adjust_q(q)
        return {p: math.log(max(float(q2[p]), 1e-6)) for p in cat.index if p not in known and p in q2}

    def lq_for_lfm(self, QR, cat, hist_item=None, live_item=None, desc=None, force=False):
        """QR.lq unchanged (same object) when off or on any error; else a new dict with the new products patched."""
        try:
            if not force and mode() != "on":
                return QR.lq
            upd = self.estimate(QR.q, cat, hist_item, live_item, desc)
            if not upd:
                return QR.lq
            out = dict(QR.lq); out.update(upd); self.last = upd
            return out
        except Exception as e:
            print("cold_lq failed, lfm keeps qrank's lq:", type(e).__name__, e, flush=True)
            return QR.lq
