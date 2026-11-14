"""Feature engineering shared by offline training and live serving."""
import numpy as np, pandas as pd
CAT=pd.read_parquet("data/catalog.parquet")
def build_tables(ui):
    """ui: user-item aggregates (u,i,v,a,p). Returns lookup tables."""
    ui=ui.merge(CAT[["product_id","category","sub"]],left_on="i",right_on="product_id")
    item=ui.groupby("i")[["v","a","p"]].sum().add_prefix("it_")
    usub=ui.groupby(["u","sub"])[["v","p"]].sum().add_prefix("us_")
    ucat=ui.groupby(["u","category"])[["v","p"]].sum().add_prefix("uc_")
    utot=ui.groupby("u")[["v","p"]].sum().add_prefix("ut_")
    uit=ui.set_index(["u","i"])[["v","a","p"]].add_prefix("ui_")
    return dict(item=item,usub=usub,ucat=ucat,utot=utot,uit=uit)
C=CAT.set_index("product_id")
def set_catalog(df):
    """Replace the global catalog (live: base catalog + catalog_updates)."""
    global C
    C=df
FEATS=["slot","in_rv","rv_cnt","is_last","rv_pos","same_sub","any_sub","same_brand","same_cat","n_rv",
 "lp_v","lp_a","lp_p","cr","cart","lprice","prel","age","page_home","page_cat",
 "ui_v","ui_a","ui_p","us_v","us_p","uc_v","uc_p","ut_v","ut_p","known","new_user"]
def featurize(pairs, T, now):
    """pairs: DataFrame with columns sid,u,i,slot,rv(list),page,new_user. Returns X with FEATS."""
    d=pairs.copy()
    d["sub"]=C["sub"].reindex(d.i).values; d["category"]=C.category.reindex(d.i).values
    d["brand"]=C.brand.reindex(d.i).values; d["price"]=C.price.reindex(d.i).values
    last=d.rv.map(lambda l:l[-1] if len(l) else None)
    ls=C["sub"].reindex(last).values; lc=C.category.reindex(last).values; lb=C.brand.reindex(last).values; lpz=C.price.reindex(last).values
    d["n_rv"]=d.rv.map(len)
    d["rv_cnt"]=[list(r).count(i) for r,i in zip(d.rv,d.i)]
    d["in_rv"]=(d.rv_cnt>0).astype(int)
    d["is_last"]=(d.i.values==last.values).astype(int)
    d["rv_pos"]=[ (len(r)-1-max(k for k,x in enumerate(r) if x==i)) if c else -1 for r,i,c in zip(d.rv,d.i,d.rv_cnt)]
    d["same_sub"]=(d["sub"].values==ls).astype(int); d["same_cat"]=(d.category.values==lc).astype(int); d["same_brand"]=(d.brand.values==lb).astype(int)
    d["any_sub"]=[int(s in set(C["sub"].reindex(list(r)).values)) if len(r) else 0 for s,r in zip(d["sub"],d.rv)]
    def look(name,idx):
        Ts=T if isinstance(T,list) else [T]
        out=None
        for t in Ts:
            v=t[name].reindex(idx).fillna(0)
            out=v if out is None else out+v.values
        return out
    it=look("item",d.i)
    d["lp_v"]=np.log1p(it.it_v.values); d["lp_a"]=np.log1p(it.it_a.values); d["lp_p"]=np.log1p(it.it_p.values)
    d["cr"]=(it.it_p.values+1)/(it.it_v.values+50); d["cart"]=(it.it_a.values+1)/(it.it_v.values+50)
    d["lprice"]=np.log(d.price); d["prel"]=np.where(pd.notna(lpz),np.log(d.price/np.where(pd.notna(lpz),lpz,1).astype(float)),0)
    d["age"]=(pd.Timestamp(now)-pd.to_datetime(C.created.reindex(d.i).values)).days
    d["page_home"]=(d.page=="home").astype(int); d["page_cat"]=(d.page=="category").astype(int)
    ui=look("uit",pd.MultiIndex.from_arrays([d.u,d.i]))
    d["ui_v"]=ui.ui_v.values; d["ui_a"]=ui.ui_a.values; d["ui_p"]=ui.ui_p.values
    us=look("usub",pd.MultiIndex.from_arrays([d.u,d["sub"]])); d["us_v"]=us.us_v.values; d["us_p"]=us.us_p.values
    uc=look("ucat",pd.MultiIndex.from_arrays([d.u,d.category])); d["uc_v"]=uc.uc_v.values; d["uc_p"]=uc.uc_p.values
    ut=look("utot",d.u); d["ut_v"]=ut.ut_v.values; d["ut_p"]=ut.ut_p.values; d["known"]=(d.ut_v>0).astype(int)
    d["new_user"]=d.new_user.astype(int)
    return d
