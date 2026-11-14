import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import pandas as pd
from recsys import k27, lfm, live, d130
from tools.k27_report import summarize
from test_lfm import build, slate as incumbent, COEF


def request(user='u1', **kwargs):
    return dict(user_id=user, request_id='r', rv=[], page='home', is_new_user=False) | kwargs


class K27Tests(unittest.TestCase):
    def test_control_exactly_matches_incumbent_on_every_segment(self):
        lf, aff = build(taste={'u1': 7})
        for new in (False, True):
            for page, rv in [('home', []), ('product', ['A30']), ('category', ['B05']), ('home', ['unknown'])]:
                r = request(is_new_user=new, page=page, rv=rv)
                st = lf.user_state('u1')
                expected = lf.slate(r, st, aff, exclude={'A00'})
                actual, _ = k27.slate(lf, r, st, aff, exclude={'A00'}, variant='k27a')
                self.assertEqual(actual, expected)

    def test_treatment_promotes_all_eligible_carts_even_outside_original_top10(self):
        ids = [f'p{i:02}' for i in range(50)]
        S = SimpleNamespace(ids=ids, n=len(ids), row={p:i for i,p in enumerate(ids)})
        scores = np.arange(50, 0, -1, dtype=float)
        lf = SimpleNamespace(scores=lambda *args: (S, scores))
        state = ({'p40'}, set(), {'p35':1, 'p36':2, 'p40':1, 'p42':1, 'unknown':1})
        scores[42] = -np.inf
        out, label = k27.slate(lf, request(), state, None, exclude={'p36'}, variant='k27b')
        self.assertEqual(label, 'k27b')
        self.assertEqual(out, ['p35'] + ids[:9])
        self.assertFalse({'p36','p40','p42','unknown'} & set(out))

    def test_no_change_outside_target_and_without_carts(self):
        lf, aff = build()
        for r in (request('u9'), request(is_new_user=True), request(page='product', rv=['A30']), request(rv=['A30'])):
            st = lf.user_state(r['user_id'])
            out, label = k27.slate(lf, r, st, aff, variant='k27b')
            self.assertEqual(out, lf.slate(r, st, aff))
            if not k27.target(r): self.assertEqual(label, 'k27z')

    def test_more_than_ten_carts_and_late_stock_exclusion(self):
        lf, aff = build()
        for p in list(lf.snap.row)[10:30]: lf.hcart.setdefault('u1', {})[p] = 1
        r = request(); st = lf.user_state('u1')
        out, _ = k27.slate(lf, r, st, aff, exclude={'A10','A11'}, variant='k27b')
        self.assertEqual(len(set(out)), 10)
        self.assertTrue(set(out) <= set(st[2]))
        self.assertFalse({'A10','A11'} & set(out))
        self.assertEqual(k27.slate(lf, r, st, aff, variant='k27b')[0],
                         k27.slate(lf, r, st, aff, variant='k27b')[0])

    def test_no_valid_control_returns_none_for_existing_fallback(self):
        lf, aff = build(); r = request()
        out, _ = k27.slate(lf, r, lf.user_state('u1'), aff, exclude=set(lf.snap.ids), variant='k27b')
        self.assertIsNone(out)

    def test_assignment_stable_independent_of_request_and_balanced(self):
        labels = [k27.version(request(f'u{i}'), 'k27') for i in range(10000)]
        self.assertTrue(4800 < labels.count('k27a') < 5200)
        self.assertEqual(k27.version(request('u1'), 'k27'), k27.version(request('u1', request_id='different'), 'k27'))
        self.assertEqual(k27.version(request('u1', is_new_user='true'), 'k27'), 'k27z')
        self.assertIn(k27.version(request('u1', is_new_user='false'), 'k27'), ('k27a','k27b'))

    def test_public_labels_never_include_algorithm_segment_or_wrapper(self):
        for variant in k27.VARIANTS:
            for r in (request(), request(is_new_user=True), request(page='product', rv=['A30'])):
                label = k27.version(r, variant)
                self.assertEqual(k27.public_version(r, variant, label), label)
                for original in ('v3-lfm-r1-kh', 'v1-gbm-cand-r1-guard', label+'+home', 'baseline-ctrl'):
                    public = k27.public_version(r, variant, original)
                    self.assertIn(public, k27.PUBLIC)
                    self.assertNotIn(public, ('k27a','k27b','k27z'))
                self.assertEqual(k27.public_version(r, variant, label, repaired=True), k27.guard_version(r, variant))


class K27RoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = live.POLICY['variant'], live.LF, live.AP
        lf, aff = build()
        live.LF = lf; live.AP = SimpleNamespace(aff=aff)
    def tearDown(self):
        live.POLICY['variant'], live.LF, live.AP = self.saved

    def test_single_writer_routing_controls_and_tags_both_arms(self):
        live.POLICY['variant'] = 'k27'
        rs = [request(f'u{i}', request_id=f'r{i}') for i in range(40)]
        versions = {}; out = live.lfm_slates(rs, {'A00'}, versions)
        self.assertEqual(len(out), len(rs))
        self.assertEqual(set(versions.values()), {'k27a','k27b'})
        self.assertTrue(all(len(set(s)) == 10 and 'A00' not in s for s in out.values()))
        self.assertTrue(all(live.use_lfm(r) and not live.use_qrank(r) and not live.use_aff(r) for r in rs))

    def test_existing_variants_do_not_call_challenger(self):
        with patch.object(k27, 'slate', side_effect=AssertionError('unexpected challenger call')):
            for v in ('v1','qrank','lfm','ab_lfm'):
                live.POLICY['variant'] = v
                live.lfm_slates([request()], set(), {})

    def test_failed_model_uses_existing_fallback(self):
        live.POLICY['variant'] = 'k27'; live.LF = None
        self.assertEqual(live.lfm_slates([request()], set(), {}), {})
        self.assertEqual(k27.public_version(request(), 'k27', 'v1-gbm-cand-r1'), k27.guard_version(request(), 'k27'))

    def test_final_journal_payload_is_opaque_even_on_repair(self):
        r = request(); items = list(live.LF.snap.ids)[:10]
        cat = pd.DataFrame(index=live.LF.snap.ids)
        journal = SimpleNamespace(claim=lambda a: True, finish=lambda *args: None)
        for variant in k27.VARIANTS:
            live.POLICY['variant'] = variant
            with patch.object(live, 'snapshot', return_value=({}, {items[0]}, cat, None, list(cat.index))), \
                 patch.object(live, 'age', return_value=.1), patch.object(live, 'session') as http:
                live.send_answers([r], [dict(request_id='r', items=items, model_version='v3-lfm-r1-kh+home')], journal, set())
                a = http.return_value.post.call_args.kwargs['json'][0]
                self.assertEqual(a['model_version'], k27.guard_version(r, variant))
                self.assertNotIn(items[0], a['items'])

    def test_d130_cannot_override_experiment_or_rename_labels(self):
        from test_d130 import fake_writer, history, catalog
        saved = d130.HC
        try:
            g = fake_writer(); g['POLICY'] = {'variant':'k27'}
            d130.install(g, history()); g['make_pools'](catalog(), set())
            rs = [request()]
            with patch.object(d130, 'mode', return_value='home'):
                self.assertEqual(g['predict'](rs), fake_writer()['predict'](rs))
        finally:
            d130.HC = saved


class K27ReportTests(unittest.TestCase):
    def test_guards_are_combined_and_cold_uses_its_own_denominator(self):
        rows = [dict(model_version='k27a', requests=100, conversion=2., cold_requests=10, cold_conversion=3., revenue_per_request=1., first=0,last=10),
                dict(model_version='k27c', requests=20, conversion=0., cold_requests=2, cold_conversion=0., revenue_per_request=0., first=1,last=11),
                dict(model_version='k27b', requests=120, conversion=2.5, cold_requests=0, cold_conversion=0., revenue_per_request=1.5, first=0,last=11)]
        result = summarize({'teams':[dict(team_id='team_26',versions=rows)]})
        self.assertEqual(result['arms']['A']['requests'], 120)
        self.assertAlmostEqual(result['arms']['A']['conversion_pct'], 200/120)
        self.assertAlmostEqual(result['arms']['A']['cold_conversion_pct'], 2.5)
        self.assertIsNone(result['arms']['B']['cold_conversion_pct'])
        self.assertEqual(result['status'], 'collect_more_data')

    def test_no_versions_is_no_evidence_not_a_win(self):
        result = summarize({'teams':[]})
        self.assertIsNone(result['conversion_delta_pp_B_minus_A'])
        self.assertEqual(result['status'],'collect_more_data')


if __name__ == '__main__': unittest.main()
