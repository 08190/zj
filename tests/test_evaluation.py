import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from apx240.engine import diagnose
from apx240.knowledge import Knowledge,KB,ROOT
from apx240.evaluate import assess,offline_environment,run_suite
from apx240.validation import validate_report
from apx240.check_live import check_sessions

class Evaluation(unittest.TestCase):
    def setUp(self):
        ctx=offline_environment();ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)

    def test_manual_behavior_cases(self):
        cases=json.loads((ROOT/'tests/acceptance_cases_v3.json').read_text(encoding='utf-8'))
        result=run_suite(cases)
        for case in result['cases']:
            with self.subTest(case=case['id']):self.assertTrue(case['passed'],case['failures'])

    def test_evaluator_detects_bad_report(self):
        case=json.loads((ROOT/'tests/acceptance_cases_v3.json').read_text(encoding='utf-8'))[0]
        report=diagnose(case['description']).to_dict()
        report['possible_causes'][0]['confirmed']=True
        report['missing_information']=[]
        failures=assess(case,report,Knowledge())
        self.assertIn('历史候选被确认为根因',failures)
        self.assertTrue(any('追问缺失' in f for f in failures))

    def test_policy_mismatch_rejected(self):
        report=diagnose('A520').to_dict();report['stop_policy']['immediate_stop']=False
        with self.assertRaises(ValueError):validate_report(report)

    def test_explicit_current_alarm_does_not_import_past_alarm(self):
        report=diagnose('上次A205，实际200°C。本次A203，实际128°C')
        self.assertEqual(report.status,'INFO_REQUIRED')
        self.assertTrue(all(c['cause_id'].startswith('A203-') for c in report.possible_causes))

    def test_repair_association_independent_of_order(self):
        kb=Knowledge();kb.repairs.reverse()
        report=diagnose('A203，实际128°C',kb)
        self.assertIn('WO-240-042',[e.source_id for e in report.evidence])
        self.assertNotIn('WO-240-063',[e.source_id for e in report.evidence])

    def test_citation_id_cannot_borrow_other_row(self):
        kb=Knowledge()
        with self.assertRaises(ValueError):kb.evidence('SAFE-01','safety_rule',3,'安全规则',kb.rules['SAFE-04'])
        with self.assertRaises(ValueError):kb.evidence('H02','history_case',5,'历史',kb.history[0]['cause'],True)

    def test_manifest_omission_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'kb';shutil.copytree(KB,path)
            manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
            del manifest['files']['alarms.json']
            (path/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaises(ValueError):Knowledge(path)

    def test_snapshot_covers_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'kb';shutil.copytree(KB,path)
            before=Knowledge(path)
            index=path/'alarms.json';index.write_bytes(index.read_bytes()+b'\n')
            manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
            manifest['files']['alarms.json']=hashlib.sha256(index.read_bytes()).hexdigest()
            (path/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            after=Knowledge(path)
            self.assertEqual(before.manifest['version_id'],after.manifest['version_id'])
            self.assertNotEqual(before.snapshot_digest,after.snapshot_digest)

    def test_live_multiturn_contract_with_simulated_provider(self):
        env={f'APX_{kind}_{part}':value for kind in ['LLM','EMBEDDING'] for part,value in [('URL','https://example.invalid/v1/test'),('MODEL','simulated'),('KEY','test')]}
        def model(system,payload,schema):
            return {'risk':'no_additional_risk','risk_quote':'','observations':[],
                'ranking':[{'cause_id':c['cause_id'],'evidence_ids':c['evidence_ids']} for c in payload['possible_causes']]},{}
        with patch.dict('os.environ',env),patch('apx240.model_review.model_json',side_effect=model) as provider,patch('apx240.retrieval.vectors',side_effect=lambda texts:[[1.,0.] for t in texts]):
            result=check_sessions()
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(provider.call_count,2)
