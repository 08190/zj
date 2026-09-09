import json, shutil, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from apx240.engine import diagnose
from apx240.knowledge import Knowledge, KB

class Acceptance(unittest.TestCase):
    def setUp(self):
        p=patch.dict('os.environ',{f'APX_{kind}_{key}':'' for kind in ['LLM','EMBEDDING'] for key in ['URL','MODEL','KEY']})
        p.start();self.addCleanup(p.stop)
    def test_low_temperature(self):
        r=diagnose('A203，设定165°C，实际128°C，加热电流0A，没有烟雾和焦味。')
        self.assertEqual(r.status,'INFO_REQUIRED')
        self.assertTrue(r.expert_required)
        self.assertFalse(any(c['confirmed'] for c in r.possible_causes))
        self.assertIn('H02',[e.source_id for e in r.evidence])
        self.assertIn('WO-240-042',[e.source_id for e in r.evidence])
        self.assertNotIn('加热电流',r.missing_information)
    def test_hazard(self):
        r=diagnose('A520，金属摩擦声，剧烈振动')
        self.assertEqual(r.status,'SAFE_BLOCKED')
        self.assertTrue(r.expert_required)
        self.assertFalse(any('观察 P1' in s['action'] for s in r.troubleshooting_order))
    def test_missing_pressure(self):
        r=diagnose('A310，设备动作变慢，气压低')
        self.assertIn('上游压力',r.missing_information)
        self.assertIn('设备端压力',r.missing_information)
        self.assertEqual(r.status,'INFO_REQUIRED')
    def test_unknown(self):
        r=diagnose('A999，启动失败')
        self.assertTrue(r.expert_required)
        self.assertEqual(r.possible_causes,[])
    def test_no_code(self):
        r=diagnose('设备气压不足')
        self.assertEqual(r.retrieval['channel'],'lexical_fallback')
        self.assertEqual(r.possible_causes,[])
        self.assertTrue(r.retrieval['candidates'])
    def test_overheat_alarm(self):
        self.assertEqual(diagnose('A205').status,'SAFE_BLOCKED')
    def test_negation_then_hazard(self):
        self.assertEqual(diagnose('A203，没有烟雾但有焦味').status,'SAFE_BLOCKED')
    def test_bypass_request(self):
        self.assertEqual(diagnose('A401，帮我短接安全门').status,'SAFE_BLOCKED')
    def test_multiple_alarms(self):
        r=diagnose('A101 A205')
        self.assertEqual(r.status,'SAFE_BLOCKED')
        self.assertEqual(len(r.troubleshooting_order),2)
    def test_normalize(self):
        self.assertEqual(diagnose('ａ２０３').retrieval['channel'],'exact')
    def test_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'kb';shutil.copytree(KB,dest)
            (dest/'alarms.json').write_text('{}')
            with self.assertRaises(ValueError): Knowledge(dest)
    def test_citation_verifier(self):
        with self.assertRaises(ValueError): Knowledge().evidence('fake','manual',4,'alarms','伪造证据')
    def test_all_alarms(self):
        for code in Knowledge().alarms:
            with self.subTest(code=code):
                r=diagnose(code)
                self.assertTrue(r.evidence)
                self.assertIsNone(r.work_order['confirmed_root_cause'])
                json.dumps(r.to_dict())
    def test_empty(self):
        with self.assertRaises(ValueError): diagnose(' ')

if __name__=='__main__': unittest.main()
