"""K30 policy-arm isolation and failure cases. No network or serving processes."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
from recsys import k30,lfm,live
from tools.k30_compare import summarize
from tools.k30_plan import plan
from tools.k30_replay import events_before,stamp
from test_lfm import build,catalog

ARMS=json.loads((Path(lfm.__file__).parent/'arms_k30.json').read_text())['lfm_arms']


def request(new=False,page='product',rv=('A30',)):
    return dict(user_id='u1',is_new_user=new,page=page,rv=list(rv))


class PatchTests(unittest.TestCase):
    def test_bonus_requires_both_cart_and_taste_and_is_bounded(self):
        X=np.zeros((5,len(lfm.FEATS))); X[:,0]=[-1.,0.,1.25,2.5,100.]
        X[:4,1]=np.log(2)
        before=np.zeros(5); after=k30.adjust(request(),X,before,lfm.FEATS,2.5)
        np.testing.assert_array_equal(after,[0.,0.,.5,1.,0.])
        np.testing.assert_array_equal(before,np.zeros(5))
        X[4,2]=1.
        self.assertEqual(k30.adjust(request(),X,before,lfm.FEATS,2.5)[4],1.)

    def test_unknown_or_nonfinite_affinity_is_neutral(self):
        X=np.zeros((2,len(lfm.FEATS))); X[:,0]=[np.nan,np.inf]; X[:,1]=1
        np.testing.assert_array_equal(k30.adjust(request(),X,np.zeros(2),lfm.FEATS,2.5),[0.,0.])

    def test_new_home_other_pages_and_empty_views_are_exactly_unchanged(self):
        X=np.ones((2,len(lfm.FEATS))); s=np.array([1.,2.])
        for r in (request(new=True),request(page='home'),request(page='search'),request(rv=())):
            self.assertIs(k30.adjust(r,X,s,lfm.FEATS,2.5),s)


class ArmTests(unittest.TestCase):
    def setUp(self):
        self.lf,self.aff=build(taste={'u1':5},unavail={'B25'})
        # Force varied taste independent of category and nonzero quality; pending
        # carts include one stale-history item plus purchased/inactive items.
        self.lf.add('u1','B25',a=1); self.lf.add('u1','A07',a=1)
        self.lf.set_arms(ARMS)

    def test_artifact_is_exact_frozen_r2_with_explicit_patch(self):
        root=Path(lfm.__file__).parent
        a=json.loads((root/'lfm_coef_r2.json').read_text()); b=json.loads((root/'lfm_coef_k30.json').read_text())
        self.assertEqual(b['score_patch'],'k30')
        for key in ('known','new','lq0'):self.assertEqual(a[key],b[key])
        self.assertEqual(len(live.clean_lfm_arms(ARMS)),2)
        for seg in ('known','new'):
            np.testing.assert_array_equal(self.lf.alt['q7a'][0][seg],self.lf.alt['q7b'][0][seg])

    def test_only_pending_cart_scores_can_change(self):
        r=request(); st=self.lf.user_state('u1')
        S,a=self.lf.scores(r,st,self.aff,model='q7a'); _,b=self.lf.scores(r,st,self.aff,model='q7b')
        pending=set(st[1])|set(st[2])
        unchanged=[k for p,k in S.row.items() if p not in pending]
        np.testing.assert_array_equal(a[unchanged],b[unchanged])
        m=np.isfinite(a)&np.isfinite(b)
        self.assertTrue(np.all(b[m]>=a[m])); self.assertLessEqual(float((b[m]-a[m]).max()),1.+1e-12)
        self.assertTrue(np.any(b[m]>a[m]))

    def test_new_and_home_exact_parity_with_same_weights(self):
        for r in (request(new=True),request(new=True,page='category'),request(page='home',rv=()),request(rv=())):
            st=self.lf.user_state('u1')
            np.testing.assert_array_equal(self.lf.scores(r,st,self.aff,model='q7a')[1],self.lf.scores(r,st,self.aff,model='q7b')[1])
            self.assertEqual(self.lf.slate(r,st,self.aff,model='q7a'),self.lf.slate(r,st,self.aff,model='q7b'))

    def test_stock_purchase_exclusions_and_ten_unique_are_preserved(self):
        for page in ('product','category'):
            r=request(page=page); st=self.lf.user_state('u1')
            for arm in ('q7a','q7b'):
                out=self.lf.slate(r,st,self.aff,model=arm,exclude={'B05'})
                self.assertEqual(len(out),10); self.assertEqual(len(set(out)),10)
                self.assertTrue(set(out)<=set(catalog().index))
                self.assertFalse(set(out)&{'B05','B06','B25'})
        self.lf.add('u1','A07',p=1)
        self.assertNotIn('A07',self.lf.slate(request(),self.lf.user_state('u1'),self.aff,model='q7b'))

    def test_repeatability_and_legacy_control_math(self):
        r=request(); st=self.lf.user_state('u1')
        a=self.lf.slate(r,st,self.aff,model='q7b')
        for _ in range(3):self.assertEqual(self.lf.slate(r,st,self.aff,model='q7b'),a)
        S,s=self.lf.scores(r,st,self.aff,model='q7a')
        w,b=self.lf.alt['q7a']; X=lfm.features(S,self.aff.affinity_all('u1',r['rv']),r['rv'],r['page'],st[2],st[1],bought_today=st[3])
        expected=X@w['known']+b['known']; expected[~np.isfinite(s)]=-np.inf
        np.testing.assert_array_equal(s,expected)

    def test_bad_patch_rejected_without_replacing_existing_arms(self):
        old=self.lf.alt
        with patch.object(lfm.json,'loads',return_value={'score_patch':'unknown'}):
            with self.assertRaises(ValueError):self.lf.set_arms(ARMS)
        self.assertIs(self.lf.alt,old)

    def test_writer_routes_existing_arms_and_public_labels_are_opaque_with_private_mask(self):
        with patch.object(live,'LF',self.lf),patch.object(live,'AP',type('AP',(),{'aff':self.aff})()),\
             patch.dict(live.POLICY,variant='lfm',lfm_arms=ARMS),patch.dict(live.LABELS,salt='test-only',map={},seen={}):
            versions={}
            reqs=[{**request(),'user_id':f'u{k}','request_id':f'r{k}'} for k in range(30)]
            out=live.lfm_slates(reqs,set(),versions)
            self.assertEqual(len(out),30)
            self.assertEqual(set(versions.values()),{'v3-lfm-q7a-k','v3-lfm-q7b-k'})
            for name in versions.values():self.assertRegex(live.public_label(name),r'^m[0-9a-f]{5}$')


class ReportingTests(unittest.TestCase):
    def fixture(self):
        labels={'salt':'test','map':{'v3-lfm-q7a-k':'m11111','v3-lfm-q7b-k':'m22222'}}
        state=dict(mode='practice',window=[0,1800],reference={'conversion':2.4},teams=[dict(team_id='team_26',on_time=99.9,versions=[
            dict(model_version='m11111',requests=600,conversion=2.),dict(model_version='m22222',requests=700,conversion=2.2),
            dict(model_version='v3-lfm-q7b-n',requests=10000,conversion=50.)])])
        return state,labels

    def test_only_target_cohort_and_same_window_reference(self):
        state,labels=self.fixture(); result=summarize(state,labels)
        self.assertEqual(result['arms']['candidate']['requests'],700)
        self.assertAlmostEqual(result['candidate_minus_control_pp'],.2)
        self.assertAlmostEqual(result['arms']['candidate']['delta_vs_reference_pp'],-.2)
        self.assertNotIn('salt',json.dumps(result))

    def test_suppressed_rows_unknown_not_zero(self):
        state,labels=self.fixture(); state['teams'][0]['versions'].pop(1)
        result=summarize(state,labels)
        self.assertIsNone(result['arms']['candidate']['conversion'])
        self.assertIsNone(result['candidate_minus_control_pp'])

    def test_missing_private_mask_or_ambiguous_rows_rejected(self):
        state,labels=self.fixture()
        with self.assertRaises(ValueError):summarize(state,None)
        state['teams'][0]['versions'].append(state['teams'][0]['versions'][0])
        with self.assertRaises(ValueError):summarize(state,labels)


class PlanAndTimeTests(unittest.TestCase):
    def test_plan_clones_selected_overrides_and_preserves_unrelated_keys(self):
        source={'variant':'lfm','note':'keep','lfm_arms':[{'tag':'a','file':'lfm_coef_r2.json'},
                {'tag':'b','file':'lfm_coef_r2.json','w':{'known':{'chn':4.,'cl':3.2}}}]}
        result=plan(source,'b'); a,b=result['lfm_arms']
        self.assertEqual(a['w'],b['w']); self.assertEqual(b['file'],'lfm_coef_k30.json')
        self.assertEqual(result['note'],'keep'); self.assertEqual(source['lfm_arms'][1]['tag'],'b')
        with self.assertRaises(ValueError):plan(source)
        with self.assertRaises(ValueError):plan({'variant':'lfm','lfm_arms':[{'tag':'r1'}]})

    def test_future_and_equal_time_cart_purchase_and_view_do_not_leak(self):
        lf,aff=build()
        aff.add=Mock()
        events=[{'u':'u1','i':'B05','e':kind,'ts':ts} for kind,ts in [
            ('view','2026-11-14T15:59:59Z'),('add_to_cart','2026-11-14T16:00:00Z'),('purchase','2026-11-14T16:00:01Z')]]
        cursor=events_before(lf,aff,events,0,stamp('2026-11-14T16:00:00Z'))
        self.assertEqual(cursor,1); self.assertNotIn('B05',lf.user_state('u1')[1])
        aff.add.assert_called_once_with('u1','B05',1)
        cursor=events_before(lf,aff,events,cursor,stamp('2026-11-14T16:00:01Z'))
        self.assertEqual(cursor,2); self.assertIn('B05',lf.user_state('u1')[1])
        cursor=events_before(lf,aff,events,cursor,stamp('2026-11-14T16:00:02Z'))
        self.assertEqual(cursor,3); self.assertIn('B05',lf.user_state('u1')[0]); self.assertNotIn('B05',lf.user_state('u1')[1])


if __name__=='__main__':unittest.main()
