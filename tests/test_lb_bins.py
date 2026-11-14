import unittest

from recsys import lb_bins


def windows(truth, starts, n_bins):
    """Build the API rows a perfect server would return for per-block truth {mv: [(n, expected buys), ...]}."""
    rows = []
    for mv, blocks in truth.items():
        for a in starts:
            for L in (3, 4):
                if a + L > n_bins: continue
                seg = blocks[a:a + L]; n = sum(x[0] for x in seg); s = sum(x[1] for x in seg)
                if n < 100: continue                       # the API hides versions under 100 requests
                rows.append(dict(a=a * 300, b=(a + L) * 300, mv=mv, n=n, conv=100.0 * s / n))
    return rows


class LbBins(unittest.TestCase):
    def test_recovers_every_block(self):
        truth = {"x": [(100, 2.0), (120, 1.0), (90, 3.5), (110, 0.5), (130, 4.0), (100, 1.5)],
                 "y": [(50, 0.2), (60, 0.9), (70, 0.1), (40, 0.0), (55, 1.1), (65, 0.3)]}
        B = lb_bins.bins_from_windows(windows(truth, range(6), 6)).set_index(["bin", "mv"])
        for mv, blocks in truth.items():
            for k, (n, s) in enumerate(blocks):
                self.assertAlmostEqual(B.loc[(k * 300, mv), "n"], n)
                self.assertAlmostEqual(B.loc[(k * 300, mv), "hs"], s, places=9)

    def test_version_listed_in_a_single_window_is_not_reported(self):
        rows = [dict(a=0, b=1200, mv="small", n=120, conv=0.5)]                       # under 100 requests in every 15-minute window
        self.assertTrue(lb_bins.bins_from_windows(rows).empty)

    def test_empty_input(self):
        self.assertTrue(lb_bins.bins_from_windows([]).empty)


if __name__ == "__main__":
    unittest.main()
