"""Per-segment league report on VALIDATION (T-CS01, E-CS01a). Reuses tools.league_metrics.evaluate unchanged.

    python -m tools.league_segments --policies baseline,mixed_category,same_subcategory [--plugin tools.my_policy]

Segments use only what a policy could know at request time: page, whether recent_views is empty, whether the user
has organic history BEFORE the training end (from the training snapshot's requests + a pinned profile file if given),
and whether any eligible product was created after the training end. Never opens the test period.
"""
from __future__ import annotations

import argparse
import importlib
import json
from collections import defaultdict
from pathlib import Path

from tools import league_metrics, league_policies
from tools.local_league import Catalog, load

ROOT = Path(__file__).resolve().parent.parent


def segment_rows(rows, train_users, train_end, created):
    seg = defaultdict(list)
    for r in rows:
        page = (r.get("context") or {}).get("page") or "?"
        rv = "rv" if r.get("recent_views") else "no_rv"
        user = "known" if r["user_id"] in train_users else "unseen"
        seg[f"page={page}"].append(r); seg[f"{user}/{rv}"].append(r); seg["all"].append(r)
        if any((created.get(p) or "") > train_end for p in (r.get("shown") or [])):
            seg["shown_new_product"].append(r)
    return seg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=ROOT / "data/local_eval/league_v2")
    ap.add_argument("--policies", default="baseline,mixed_category,same_subcategory")
    ap.add_argument("--plugin", action="append", default=[])
    ap.add_argument("--profiles", type=Path, help="optional training-window user profile JSON {'profiles': {user: ...}}")
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    for m in a.plugin:
        importlib.import_module(m)
    manifest = json.loads((a.cache / "manifest.json").read_text(encoding="utf-8"))
    train, val = load(a.cache, "train.json", manifest), load(a.cache, "validation.json", manifest)
    meta = load(a.cache, "catalog.json", manifest)
    users = {r["user_id"] for r in train["requests"]}
    if a.profiles:
        users |= set(json.loads(a.profiles.read_text())["profiles"])
    created = {r["product_id"]: str(r.get("created_at") or "") for r in meta["base"]}
    created.update({u["product_id"]: str(u["ts"]) for u in meta["updates"] if u.get("change") == "new_product"})
    names = a.policies.split(",")
    models = league_policies.train(names, train)
    out = {"period": [val["start"], val["end"]], "users_known_from": "train requests" + (" + profiles" if a.profiles else ""), "segments": {}}
    for name, rows in sorted(segment_rows(val["requests"], users, train["end"].replace("T", " ")[:23], created).items()):
        clicks = sum(r.get("clicked") not in (None, "") for r in rows); buys = sum(r.get("purchased") not in (None, "") for r in rows)
        res = {"impressions": len(rows), "logged_clicks": clicks, "logged_purchases": buys}
        if clicks >= 20:
            rep = league_metrics.evaluate(models, rows, Catalog(meta), a.bootstrap)
            for p in names:
                x = rep["results"][p]
                res[p] = {k: (round(x[k], 4) if isinstance(x.get(k), float) else x.get(k))
                          for k in ("hit@10", "SNIPS_slot1_buy", "SNIPS_slot1_click", "slot1_matches", "ESS", "valid_top10_rate")}
                res[p]["hit@10_CI95"] = [round(v, 3) if v is not None else None for v in x["CI95_hour_block_percentile"]["hit@10"]]
            res["paired_delta_CI95_hit@10"] = {k: [round(v, 3) if v is not None else None for v in d["hit@10"]] for k, d in rep["paired_delta_CI95"].items()}
        else:
            res["note"] = "fewer than 20 logged clicks: not evaluated (no statistical support)"
        out["segments"][name] = res
        print(name, json.dumps(res)[:600], flush=True)
    if a.out:
        a.out.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
