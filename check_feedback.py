from starter.recommender import query, TEAM

rows = query(f"""
SELECT
    served_by::String AS served_by,
    count() AS requests,
    countIf(purchased != '') AS purchases,
    round(100 * countIf(purchased != '') / count(), 2)
        AS conversion_pct,
    round(sum(revenue_eur::Float64), 2) AS revenue_eur,
    round(quantile(0.95)(latency_ms::Float64), 0)
        AS p95_latency_ms
FROM {TEAM}.feedback
WHERE request_id != '__init__'
GROUP BY served_by
""")

for row in rows:
    print(row)