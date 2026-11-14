import pandas as pd
from rt import q
pop=q("SELECT product_id::String product_id, countIf(event_type='view') v, countIf(event_type='add_to_cart') a, countIf(event_type='purchase') p, countIf(event_type='purchase' AND ts::DateTime64(3) > toDateTime64('2026-11-07',3)) p7, countIf(event_type='view' AND ts::DateTime64(3) > toDateTime64('2026-11-07',3)) v7 FROM shop.history_events GROUP BY product_id")
pop.to_parquet("data/pop.parquet"); print(pop.describe())
print(q("SELECT countDistinct(user_id::String) u FROM shop.history_events"))
print(q("""SELECT count() n, countIf(user_id::String IN (SELECT DISTINCT user_id::String FROM shop.history_events)) in_ev,
 countIf(user_id::String IN (SELECT DISTINCT user_id::String FROM shop.history_sessions)) in_hs, countIf(is_new_user::Bool) new FROM (SELECT user_id, is_new_user FROM shop.requests ORDER BY ts DESC LIMIT 5000)"""))
print(q("SELECT context.page::String p, count() n, countIf(length(recent_views)=0) nov FROM (SELECT * FROM shop.requests ORDER BY ts DESC LIMIT 5000) GROUP BY p"))
print(q("SELECT change::String c, count() FROM shop.catalog_updates GROUP BY c"))
