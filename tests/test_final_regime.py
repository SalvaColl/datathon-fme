"""T-064: invariants of the writer under a regime change (new catalogue, almost no catalogue, no state).
Some tests CHARACTERISE behaviour that is not ideal (marked "characterisation"): they document what the writer of the
final does, so nobody assumes otherwise; if the serving code is improved they must be updated, not deleted."""
import contextlib, datetime, io, json, unittest
import numpy as np

from recsys import lfm, live, serving
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NOW = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
UF1 = json.loads((lfm.HERE / "policy.rot_uf1.json").read_text())["lfm_arms"]


def fit(unavail=(), newp=None, history=HIST, arms=UF1):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, history); lf.set_arms(live.clean_lfm_arms(arms))
    oq = {p: (400.0, 20.0 + int(p[1:])) for p in cat.index}
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, newp=newp, oq=oq, oq_hist=set(cat.index) - set(newp or ()))
    return lf, aff, cat


class NeverInvalidProductsTests(unittest.TestCase):
    """Whatever the ranking returns, what leaves through repair / repair_for is active, unique and ten long, or nothing."""

    def setUp(self):
        self.saved = (live.LF, dict(live.BOUGHT)); live.LF = None; live.BOUGHT.clear()

    def tearDown(self):
        live.LF = self.saved[0]; live.BOUGHT.clear(); live.BOUGHT.update(self.saved[1])

    def test_repair_never_fills_with_inactive_or_unknown_products(self):
        best = ["p%02d" % k for k in range(40)]; active = set(best[20:]) | {"x1"}
        for items in (None, [], ["gone"] * 10, best[:10], ["x1", "x1", None, 7, "p00", "p25"], best[15:25]):
            for fn in (lambda i: serving.repair(i, best, active), lambda i: live.repair_for("u", i, best, active)):
                out = fn(items)
                self.assertEqual(len(out), 10); self.assertEqual(len(set(out)), 10); self.assertTrue(set(out) <= active, (items, out))

    def test_fewer_than_ten_active_products_raises_instead_of_sending(self):
        best = ["p%02d" % k for k in range(40)]; active = set(best[:9])
        for items in (None, best[:9], best[:10], best[:9] + ["gone"]):
            with self.assertRaises(ValueError): serving.repair(items, best, active)
            with self.assertRaises(ValueError): live.repair_for("u", items, best, active)
        live.BOUGHT["u"].update(best[:3])                                   # ...also on the already-bought path
        with self.assertRaises(ValueError): live.repair_for("u", best[:9], best, active)

    def test_ten_active_but_some_bought_sends_bought_rather_than_nothing(self):
        """Ten valid products come first: with exactly ten active and three of them bought, the list carries the three."""
        best = ["p%02d" % k for k in range(40)]; active = set(best[:10]); live.BOUGHT["u"].update(best[:3])
        with contextlib.redirect_stdout(io.StringIO()): out = live.repair_for("u", best[:10], best, active)
        self.assertEqual(set(out), active); self.assertEqual(out[:7], best[3:10])       # the unbought ones first

    def test_fallback_answers_skip_inactive_and_bought(self):
        best = ["p%02d" % k for k in range(40)]
        saved = dict(live.state); self.addCleanup(lambda: live.state.update(saved))
        live.state.update(best=best, unavail=set(best[:5]), stock_out={"p07"}); live.BOUGHT["u"].add("p08")
        a, b = live.fallback_answers([dict(request_id="r1", user_id="u"), dict(request_id="r2", user_id="other")])
        self.assertEqual(a["items"], ["p05", "p06"] + best[9:17]); self.assertEqual(b["items"], ["p05", "p06"] + best[8:16])
        self.assertEqual(a["model_version"], "v1-gbm-cand-r1-guard")


class TinyCatalogueSendPathTests(unittest.TestCase):
    """Characterisation: with fewer than ten active products nothing is sent, and the exception leaves the serving loop's
    iteration (main() logs 'loop error' and pulls again), so every request of that pull is left to the platform fallback."""

    def setUp(self):
        self.saved = (live.LF, dict(live.BOUGHT), dict(live.state)); live.LF = None; live.BOUGHT.clear()
        self.best = ["p%02d" % k for k in range(40)]

    def tearDown(self):
        live.LF = self.saved[0]; live.BOUGHT.clear(); live.BOUGHT.update(self.saved[1]); live.state.update(self.saved[2])

    def world(self, n_active):
        cat = type("Cat", (), {"index": list(self.best)})()
        live.state.update(cat=cat, best=self.best, unavail=set(self.best[n_active:]), stock_out=set(), pools={}, live=None)

    def reqs(self, n): return [dict(request_id=f"r{k}", user_id=f"u{k}", ts=NOW(), rv=[]) for k in range(n)]

    def test_fallback_answers_are_short_and_send_answers_refuses_them(self):
        self.world(9); rq = self.reqs(4); ans = live.fallback_answers(rq)
        self.assertEqual([len(a["items"]) for a in ans], [9] * 4)                      # not padded with inactive products
        seen = set()
        with self.assertRaises(ValueError): live.send_answers(rq, ans, None, seen, dry=True)
        self.assertEqual(seen, set())                                                  # nothing marked as answered

    def test_one_unrepairable_request_drops_its_whole_group_and_the_rest_of_the_pull(self):
        """12 requests = 3 groups of 4. The request that cannot be repaired is in the first group: no group is sent."""
        self.world(30); rq = self.reqs(12); sent = []
        real = live.repair_for; self.addCleanup(setattr, live, "repair_for", real)
        def poisoned(u, items, best, active):
            if u == "u1": raise ValueError("Fewer than ten eligible products; refusing invalid submission")
            return real(u, items, best, active)
        live.repair_for = poisoned
        def deliver(group, answers):
            seen = set(); live.send_answers(group, answers, None, seen, dry=True); sent.extend(seen)
        with self.assertRaises(ValueError):
            serving.serve(rq, live.fallback_answers, live.fallback_answers, deliver)
        self.assertEqual(sent, [])                                                     # r0 (valid, same group) and r4..r11 got nothing either
        live.repair_for = real; sent.clear()
        self.assertEqual(serving.serve(rq, live.fallback_answers, live.fallback_answers, deliver), 0); self.assertEqual(len(sent), 12)

    def test_with_ten_or_more_active_everything_is_sent(self):
        for n in (10, 12):
            self.world(n); rq = self.reqs(8); seen = set()
            live.send_answers(rq, live.fallback_answers(rq), None, seen, dry=True)
            self.assertEqual(len(seen), 8)


class LfmRegimeTests(unittest.TestCase):
    def slate(self, lf, aff, user="u9", rv=("A30",), new=False, page="product", exclude=()):
        return lf.slate(dict(user_id=user, rv=list(rv), page=page, is_new_user=new), lf.user_state(user), aff, exclude=exclude, model="uf1")

    def test_old_catalogue_dead_serves_only_launched_products_despite_the_cap(self):
        """Only 12 launched products are active and the arm caps launched products at 2 per list (new shoppers, home):
        the cap cannot be honoured, so the uncapped list is served: ten active products, never an inactive one."""
        ids = list(catalog().index); launched = set(ids[:6] + ids[40:46])
        lf, aff, cat = fit(unavail=set(ids) - launched, newp=launched)
        for new in (False, True):
            for rv, page in ((["A30"], "product"), (["A01", "B03"], "category"), ([], "home")):
                s = self.slate(lf, aff, rv=rv, new=new, page=page)
                self.assertIsNotNone(s); self.assertEqual(len(set(s)), 10); self.assertTrue(set(s) <= launched)

    def test_fewer_than_ten_active_gives_none_never_a_padded_list(self):
        ids = list(catalog().index)
        lf, aff, cat = fit(unavail=set(ids[9:]))
        for new in (False, True): self.assertIsNone(self.slate(lf, aff, new=new)); self.assertIsNone(self.slate(lf, aff, rv=(), new=new, page="home"))
        lf, aff, cat = fit(unavail=set(ids[12:]))
        self.assertIsNone(self.slate(lf, aff, exclude=set(ids[:3])))                    # stock moved after the snapshot
        self.assertEqual(set(self.slate(lf, aff, exclude=set(ids[:2]))), set(ids[2:12]))

    def test_restart_with_empty_state_and_unknown_everything(self):
        """A writer that has just started: no history frame, no live state; shopper, page, device and views unknown."""
        lf, aff, cat = fit(history=None, newp={"A38", "A39"})
        self.assertEqual(lf.user_state("nobody")[:4], (set(), set(), {}, set()))
        for new in (True, False, None):
            for rv in ([], ["p_does_not_exist"], ["p_does_not_exist", "A30"]):
                req = dict(user_id="nobody", rv=rv, page="unknown-page", is_new_user=new, device=None, region="ZZ", request_id=None)
                s = lf.slate(req, lf.user_state("nobody"), aff, exclude={"A31"}, model="uf1")
                self.assertIsNotNone(s); self.assertEqual(len(set(s)), 10); self.assertTrue(set(s) <= set(cat.index) - {"A31"})

    def test_views_of_a_category_no_table_has_seen(self):
        lf, aff, cat = fit()
        cat2 = cat.copy(); moved = ["A30", "A31", "A32", "B10"]
        for k in range(20): cat2.loc[moved[k % 4] if k < 4 else f"A{k:02d}", ["category", "sub"]] = [f"New {k}", f"New sub {k}"]   # more than lf.NC categories in all
        lf.set_catalog(cat2, set(), aff, None, None)
        s = self.slate(lf, aff, rv=moved[:3], page="category")
        self.assertIsNotNone(s); self.assertEqual(len(set(s)), 10)

    def test_launched_share_cliff_turns_newp_and_the_cap_off_together(self):
        """live.new_products: up to 25% of the catalogue the set is used; above it None, and then newp / newph are 0 for
        every product and the cap has nothing to cap (cap_launched returns the scores untouched)."""
        cat = catalog(); ids = list(cat.index)                                         # 80 products
        saved = live.QR; self.addCleanup(setattr, live, "QR", saved)
        live.QR = type("QR", (), {"q": {p: 0.1 for p in ids[20:]}})()
        self.assertEqual(live.new_products(cat), set(ids[:20]))                         # exactly 25%: still on
        live.QR = type("QR", (), {"q": {p: 0.1 for p in ids[21:]}})()
        self.assertIsNone(live.new_products(cat))                                      # 26%: off
        on, aff, _ = fit(newp=set(ids[:20])); off, _, _ = fit(newp=None)
        self.assertIsNone(off.snap.newp)
        req = dict(user_id="nobody", rv=[], page="home", is_new_user=True)
        S, s = off.scores(req, off.user_state("nobody"), aff, "uf1")
        self.assertIs(lfm.cap_launched(S, s, 2), s)
        a = on.slate(req, on.user_state("nobody"), aff, model="uf1"); b = off.slate(req, off.user_state("nobody"), aff, model="uf1")
        self.assertLessEqual(len(set(a) & set(ids[:20])), 2)                            # cap honoured while the set is known
        self.assertEqual(len(set(a)), 10); self.assertEqual(len(set(b)), 10)


if __name__ == "__main__":
    unittest.main()
