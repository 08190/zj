import json
import unittest
from pathlib import Path
from unittest.mock import patch
from apx240.engine import diagnose

class Golden(unittest.TestCase):
    def test_36_labeled_scenarios(self):
        cases=json.loads(Path(__file__).with_name('golden_cases.json').read_text(encoding='utf-8'))
        with patch.dict('os.environ',{f'APX_{kind}_{key}':'' for kind in ['LLM','EMBEDDING'] for key in ['URL','MODEL','KEY']}):
            for case in cases:
                with self.subTest(case=case['id']):
                    r=diagnose(case['input'])
                    self.assertEqual(r.status,case['status'])
                    self.assertEqual(r.expert_required,case['expert'])
                    self.assertFalse(any(c['confirmed'] for c in r.possible_causes))
                    r.to_dict()
