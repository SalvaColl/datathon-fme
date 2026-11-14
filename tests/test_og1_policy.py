"""T-041: the og1 weight file and the night policy that carries it are accepted whole and leave the champion its share."""
import json, pathlib, unittest

from recsys import lfm, live

HERE = pathlib.Path(lfm.HERE)


class Og1Tests(unittest.TestCase):
    def test_weight_file_has_the_format_of_the_others_and_new_shoppers_keep_r3(self):
        og, r3 = (json.loads((HERE / f).read_text()) for f in ("lfm_coef_og1.json", "lfm_coef_r3.json"))
        for seg in ("known", "new"):
            self.assertTrue(set(og[seg]["w"]) <= set(lfm.FEATS)); self.assertIn("b", og[seg])
            self.assertTrue(all(abs(v) <= 20 for v in og[seg]["w"].values()))
        self.assertEqual(og["new"]["w"], r3["new"]["w"])                       # hold-out did not improve for new shoppers
        self.assertNotEqual(og["known"]["w"], r3["known"]["w"])
        self.assertEqual(og["known"]["w"]["home"], r3["known"]["w"]["home"])

    def test_night_policy_is_accepted_and_champion_keeps_half_of_every_slice(self):
        raw = json.loads((HERE / "policy.night_1114_og1.json").read_text())["lfm_arms"]
        arms = live.clean_lfm_arms(raw)
        self.assertEqual(arms, raw); self.assertEqual([a["tag"] for a in arms], ["r3", "np1", "og1", "cn1"])
        saved = live.POLICY["lfm_arms"]
        try:
            live.POLICY["lfm_arms"] = arms
            routed = [live.lfm_route(a, False, "product", ["A01"]) for a in arms]
            self.assertEqual(routed.count("r3"), 2)                              # known pages: r3 50%, np1 25%, og1 25%
        finally: live.POLICY["lfm_arms"] = saved
        og = next(a for a in arms if a["tag"] == "og1")
        self.assertEqual(og["home"], {"file": "lfm_coef_r3.json"})              # home requests of the arm are served with r3


if __name__ == "__main__":
    unittest.main()
