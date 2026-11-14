"""Optional taste-conditioned cart boost for returning product/category users.

Consumes the existing feature matrix. No new data, training, network or writes.
The fixed maximum bonus is one logit unit; carts at neutral affinity get zero.
This is an online-test hypothesis, not a fitted purchase-probability estimate.
"""
import numpy as np


def adjust(request, features, scores, names, affinity_scale):
    if request.get('is_new_user') or request.get('page') not in ('product','category') or not request.get('rv'):
        return scores
    cart=(features[:,names.index('chn')]>0) | (features[:,names.index('cl')]>0)
    affinity=features[:,names.index('aff10')]
    strength=np.clip(np.where(np.isfinite(affinity),affinity,0.)/affinity_scale,0.,1.)
    return scores + cart*strength
