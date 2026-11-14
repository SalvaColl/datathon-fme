"""Public model_version labels (labels.json): opaque codes on the wire, internal names inside the process."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recsys'))
import live


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.data, self.saved = live.DATA, dict(live.LABELS)
        self.tmp = tempfile.TemporaryDirectory(); live.DATA = Path(self.tmp.name)
        live.LABELS.update(salt=None, map={}, seen={})

    def tearDown(self):
        live.DATA = self.data; live.LABELS.clear(); live.LABELS.update(self.saved); self.tmp.cleanup()

    def test_no_file_keeps_labels(self):
        live.read_labels()
        self.assertEqual(live.public_label('v2-qrank-r1'), 'v2-qrank-r1')

    def test_mapped_and_derived_codes_are_opaque_and_stable(self):
        (live.DATA / 'labels.json').write_text(json.dumps({'salt': 's1', 'map': {'v3-lfm-r1-k': 'a1'}}))
        live.read_labels()
        self.assertEqual(live.public_label('v3-lfm-r1-k'), 'a1')
        code = live.public_label('v3-lfm-r1-n')
        self.assertRegex(code, r'^m[0-9a-f]{5}$')
        self.assertEqual(code, live.public_label('v3-lfm-r1-n'))
        self.assertNotEqual(code, live.public_label('v3-lfm-r1-nh'))
        for word in ('lfm', 'qrank', 'gbm', 'guard'): self.assertNotIn(word, code)
        (live.DATA / 'labels.json').write_text(json.dumps({'salt': 's2', 'map': {}}))
        live.read_labels()
        self.assertNotEqual(code, live.public_label('v3-lfm-r1-n'))       # a new salt rotates every derived code

    def test_broken_file_is_ignored(self):
        (live.DATA / 'labels.json').write_text('{not json')
        live.read_labels()
        self.assertEqual(live.public_label('v1-gbm-cand-r1'), 'v1-gbm-cand-r1')


if __name__ == '__main__':
    unittest.main()
