"""Realized conversion per model_version (joins our submissions with feedback). Usage: python compare_versions.py [minutes]"""
import sys
from rt import q, os
TEAM=os.environ["TEAM_ID"]; mins=int(sys.argv[1]) if len(sys.argv)>1 else 120
print(q(f"""SELECT s.model_version::String version, f.served_by::String served_by, count() n,
  round(100*countIf(f.purchased::String!='')/n,3) conv_pct, round(100*countIf(f.clicked::String!='')/n,2) ctr_pct,
  round(sum(f.revenue_eur::Float64)/n,3) eur_per_req, round(quantile(0.95)(f.latency_ms::Float64)) p95_ms
FROM {TEAM}.feedback f INNER JOIN {TEAM}.submissions s ON s.request_id::String=f.request_id::String
WHERE f.ts::DateTime64(3) > now() - INTERVAL {mins} MINUTE GROUP BY version, served_by ORDER BY n DESC""").to_string())
