"""T-054: recent views of the requests of the last 30 days of shop.history_sessions, per shopper and product.
Writes data/prev_views.parquet (u, i, n = requests that had the product in view). Read-only on RawTree, ~2 minutes.
The live writer loads the file at start if it exists; the requests of the event itself come from shop.requests."""
import json, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from rt import q

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
END = "2026-11-14"          # last day with history_sessions rows (the event's requests start that morning)


def day(d):
    f = q(f"""SELECT user_id::String u, toJSONString(recent_views) rv FROM shop.history_sessions
              WHERE ts::DateTime64(3) >= '{d} 00:00:00' AND ts::DateTime64(3) < toDateTime('{d} 00:00:00') + INTERVAL 1 DAY""")
    c = Counter()
    for u, rv in zip(f.u.values, f.rv.values) if len(f) else ():
        try: items = {x["product_id"] for x in json.loads(rv) if isinstance(x, dict) and x.get("product_id")}
        except (ValueError, TypeError): continue
        for i in items: c[(u, i)] += 1
    return c


def main():
    days = pd.date_range(end=END, periods=DAYS).strftime("%Y-%m-%d")
    tot = Counter()
    with ThreadPoolExecutor(4) as ex:
        for c in ex.map(day, days): tot.update(c)
    out = pd.DataFrame([(u, i, n) for (u, i), n in tot.items()], columns=["u", "i", "n"])
    out.to_parquet("data/prev_views.parquet")
    print(len(out), "pairs", out.u.nunique(), "users", int(out.n.sum()), "views")


if __name__ == "__main__":
    main()
