import json, sys, unittest
from pathlib import Path
REC = Path(__file__).resolve().parents[1] / "recsys"
sys.path.insert(0, str(REC))
import live, lfm

NAMES = ["cs2r", "ogsr", "cs4r", "cx6l", "fsr", "cx3l"]          # T-043 screening variants (E-430)


class CartVariantPolicies(unittest.TestCase):
    def test_writer_accepts_each_policy_whole_and_only_known_pages_move(self):
        for n in NAMES:
            conf = json.loads((REC / f"policy.rot_{n}.json").read_text())
            self.assertEqual(conf["variant"], "lfm")
            arms = live.clean_lfm_arms(conf["lfm_arms"])
            self.assertEqual(arms, conf["lfm_arms"], n)                      # nothing dropped or rewritten
            self.assertEqual(len(arms), 1); a = arms[0]
            self.assertEqual(a["tag"], n)
            self.assertNotIn("lq", a); self.assertNotIn("explore", a)        # no price-bug trigger (T-042), no exploration slot
            self.assertEqual(set(a["w"]), {"known"})                         # new shoppers keep the file's weights
            self.assertEqual(a["home"], {"file": "lfm_coef_r3.json"})        # home requests stay on r3
            self.assertTrue((REC / a["file"]).exists())

    def test_new_shoppers_and_home_score_exactly_as_r3(self):
        r3 = json.loads((REC / "lfm_coef_r3.json").read_text())
        LF = lfm.LiveFit(r3)
        for n in NAMES:
            arm = json.loads((REC / f"policy.rot_{n}.json").read_text())["lfm_arms"][0]
            LF.set_arms([{"tag": "r3", "file": "lfm_coef_r3.json"}, arm])
            (w, b), (w0, b0), (wh, bh) = LF.alt[n], LF.alt["r3"], LF.alt[n + "@home"]
            self.assertTrue((w["new"] == w0["new"]).all() and b["new"] == b0["new"], n)
            self.assertTrue(all((wh[s] == w0[s]).all() and bh[s] == b0[s] for s in ("known", "new")), n)
            self.assertFalse((w["known"] == w0["known"]).all(), n)


if __name__ == "__main__":
    unittest.main()
