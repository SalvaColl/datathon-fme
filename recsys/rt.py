import os, sys, json
from pathlib import Path
import requests, pandas as pd
ENV=next((p for p in (Path(".env"),Path("../.env")) if p.exists()),None)
for l in (ENV.read_text().splitlines() if ENV else []):
    k,_,v=l.partition("="); os.environ.setdefault(k.strip(),v.strip())
H={"Authorization":f"Bearer {os.environ['RAWTREE_API_KEY']}"}
def q(sql):
    r=requests.post("https://api.rawtree.com/v1/query",json={"sql":sql},headers=H,timeout=120)
    if r.status_code!=200: raise RuntimeError(r.text[:500])
    return pd.DataFrame(r.json()["data"])
if __name__=="__main__":
    pd.set_option("display.width",250); pd.set_option("display.max_columns",30); pd.set_option("display.max_colwidth",80)
    for s in sys.argv[1:]:
        print(q(s).to_string()); print()
