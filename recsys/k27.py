"""T-K27: isolated optional challenger. No network, fitting, or data access.

Public versions are opaque. Private mapping: a/b are target control/treatment,
 c/d their guarded/failed paths, z unchanged traffic, u guarded unchanged traffic.
Only returning home requests without recent views are randomized. In treatment,
eligible historical carts precede the current ranker's other choices.
"""
from __future__ import annotations
import zlib
import numpy as np

VARIANTS = ('k27', 'k27a', 'k27b')
PUBLIC = frozenset(('k27a', 'k27b', 'k27c', 'k27d', 'k27z', 'k27u'))


def is_new(value):
    return value in (True, 1, 'true', 'True', '1')


def target(req):
    return (req.get('page') == 'home' and not req.get('rv')
            and not is_new(req.get('is_new_user')))


def version(req, variant):
    if not target(req):
        return 'k27z'
    if variant == 'k27a':
        return 'k27a'
    if variant == 'k27b':
        return 'k27b'
    # Separate salt from existing experiments. Assignment never depends on outcomes.
    return 'k27b' if zlib.crc32(('k27:' + str(req['user_id'])).encode()) % 2 else 'k27a'


def guard_version(req, variant):
    return {'k27a': 'k27c', 'k27b': 'k27d', 'k27z': 'k27u'}[version(req, variant)]


def public_version(req, variant, original, repaired=False):
    expected = version(req, variant)
    return expected if not repaired and original == expected else guard_version(req, variant)


def control_slate(S, scores, exclude, n=10):
    """Exactly the incumbent LiveFit.slate selector, operating on one score snapshot."""
    top = np.argpartition(-scores, min(n + 20, S.n - 1))[:n + 20]
    top = top[np.argsort(-scores[top])]
    out = [S.ids[k] for k in top if np.isfinite(scores[k]) and S.ids[k] not in exclude][:n]
    return out if len(out) == n and len(set(out)) == n else None


def slate(lf, req, state, affinity, exclude=(), variant='k27', n=10):
    if variant not in VARIANTS:
        raise ValueError('Unknown experiment variant')
    # Both arms share the same model, feature computation, snapshots and selector.
    S, scores = lf.scores(req, state, affinity)
    control = control_slate(S, scores, exclude, n)
    label = version(req, variant)
    if control is None or label != 'k27b':
        return control, label
    bought, _, hist_cart = state
    blocked = set(exclude) | set(bought)
    rows = [S.row[p] for p in hist_cart if p in S.row and p not in blocked
            and np.isfinite(scores[S.row[p]])]
    rows.sort(key=lambda k: (-float(scores[k]), S.ids[k]))
    priority = [S.ids[k] for k in rows[:n]]
    if not priority:
        return control, label
    seen = set(priority)
    result = (priority + [p for p in control if p not in seen])[:n]
    if len(result) != n or len(set(result)) != n:
        return control, label
    return result, label
