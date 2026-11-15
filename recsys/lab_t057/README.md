# T-057 lab: refit of lfm page weights on our own carousel purchases

Read-only on RawTree. Scripts as run in the cloud on 15 Nov (paths assume `/home/user/lab` as the working directory and the repo at `/home/user/datathon-fme`).

    cd recsys && python download_user_items.py && python cold_lq_replay.py --pull     # data
    cd /home/user/lab
    python build.py        # 4 min, 4 processes: shown impressions with features as of the request, full catalogue for requests with a purchase
    python addfeat.py      # prv / hcb / hcc columns (needs data/prev_views.parquet, data/hist_carousel.parquet, allreq.parquet)
    python clfit.py        # conditional logit by segment, temporal hold-outs
    python cmp2.py         # against the rotation policies, with the new signals
    python full.py         # rank of held-out carousel purchases over the full catalogue
    python inter.py; python newp.py; python listfx.py   # interactions, launched products, list variety
    python mk.py; python mk2.py  # write the policies

Method and results: E-570 in `experiments.md`.
