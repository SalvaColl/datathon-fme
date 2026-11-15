"""Commit and SHA-256 of the files that define the served policy: recsys/data/policy.json (if present), every
recsys/policy*.json, lfm_coef*.json and cold_prior.json. Prints only; reads no credentials.
    python tools/final_checksums.py [--active-only]"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent / "recsys"


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("commit", subprocess.run(["git", "rev-parse", "HEAD"], cwd=R, capture_output=True, text=True).stdout.strip())
    act = R / "data" / "policy.json"; files = sorted(R.glob("lfm_coef*.json")) + [R / "cold_prior.json"]
    if act.exists():
        print(sha(act), "data/policy.json")
        same = [p.name for p in sorted(R.glob("policy*.json")) if p.read_bytes() == act.read_bytes()]
        print("  identical to:", ", ".join(same) or "no committed policy file (hand-edited or newer)")
        try: print("  arms:", [a.get("tag") for a in json.loads(act.read_text()).get("lfm_arms", [])])
        except ValueError: print("  NOT VALID JSON")
    else: print("(no data/policy.json on this machine)")
    if "--active-only" not in sys.argv: files = sorted(R.glob("policy*.json")) + files
    for p in files:
        if p.exists(): print(sha(p), p.name)


if __name__ == "__main__":
    main()
