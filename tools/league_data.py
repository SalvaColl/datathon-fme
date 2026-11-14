from __future__ import annotations

import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com").rstrip("/")
KEY = os.environ.get("RAWTREE_API_KEY", "")


def sql(query: str):
    resp = requests.post(
        f"{API}/v1/query",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"sql": query}, timeout=600,
    )
    if not resp.ok:
        raise RuntimeError(f'RawTree query failed ({resp.status_code}): {resp.text[:2000]}')
    return resp.json()["data"]
