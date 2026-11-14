"""Collaborative-filtering factors for lfm's `mf` feature (T-035). Read-only on RawTree; writes lfm_mf.npz.

    python download_user_items.py      # data/user_item_all.parquet: one row per (user, product) of the 60-day organic history
    python lfm_mf_build.py             # -> lfm_mf.npz (users, items, P, Q)

Plain version. Every lfm feature so far describes the shopper through attributes (category, subcategory, description
phrases). This one uses the other shoppers: a matrix shoppers x products with log(1 + views + 3 carts + 6 purchases)
is compressed to 16 numbers per shopper (P) and per product (Q) with a truncated SVD. P[u] . Q[i] is high when
shoppers with a history like u's interacted with i, even if u never saw it. lfm standardises that score across the
catalogue for each shopper (lfm.features) and gives it one weight, fitted on the live feedback like the others.

Only the history is used (nothing from today), so the file is built once. Shoppers without history and products
launched after it get 0, which is "no opinion".
"""
from pathlib import Path
import numpy as np, pandas as pd, scipy.sparse as sp
from scipy.sparse.linalg import svds

HERE = Path(__file__).resolve().parent
K = 16


def build(h: pd.DataFrame, k=K):
    uc, users = pd.factorize(h.u); ic, items = pd.factorize(h.i)
    val = np.log1p(h.v.values + 3.0 * h.a.values + 6.0 * h.p.values).astype(np.float32)
    M = sp.csr_matrix((val, (uc, ic)), shape=(len(users), len(items)))
    U, s, Vt = svds(M, k=k, v0=np.ones(min(M.shape), dtype=np.float32))        # fixed start: same file on every run
    return np.array(users, dtype=str), np.array(items, dtype=str), (U * s).astype(np.float32), Vt.T.astype(np.float32)


if __name__ == "__main__":
    h = pd.read_parquet(HERE / "data" / "user_item_all.parquet", columns=["u", "i", "v", "a", "p"])
    users, items, P, Q = build(h)
    np.savez_compressed(HERE / "lfm_mf.npz", users=users, items=items, P=P, Q=Q)
    print("users", len(users), "items", len(items), "rank", P.shape[1], "->", (HERE / "lfm_mf.npz").stat().st_size // 1024, "KiB")
