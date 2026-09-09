import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor
from apx240.sessions import SessionStore,SessionConflict
from apx240.engine import diagnose
from apx240.observations import single_value
from apx240.retrieval import corpus
from apx240.knowledge import Knowledge

class Sessions(unittest.TestCase):
    def setUp(self):
        env=patch.dict('os.environ',{f'APX_{kind}_{key}':'' for kind in ['LLM','EMBEDDING'] for key in ['URL','MODEL','KEY']})
        env.start();self.addCleanup(env.stop)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'sessions.db'
        self.spy=Mock(side_effect=diagnose)
        self.store=SessionStore(self.path,self.spy)

    def create(self,text='A203，实际128°C'):
        return self.store.create(text,'first')

    def test_followup_and_restart(self):
        a=self.create();b=self.store.append(a['session_id'],'加热电流0A','append',1,'second')
        self.assertEqual(b['revision'],2)
        self.assertEqual(single_value(b['latest_report']['current_observations'],'actual_temperature'),128)
        self.assertEqual(single_value(b['latest_report']['current_observations'],'heater_current'),0)
        self.assertEqual(a['latest_report']['work_order']['work_order_id'],b['latest_report']['work_order']['work_order_id'])
        self.assertEqual(SessionStore(self.path).get(a['session_id']),b)

    def test_correction_audited(self):
        a=self.create();b=self.store.append(a['session_id'],'实际温度140°C','correct_measurements',1,'second')
        self.assertEqual(single_value(b['latest_report']['current_observations'],'actual_temperature'),140)
        self.assertIn('128',b['turns'][0]['message'])
        self.assertTrue(b['turns'][1]['replaced_measurements'])

    def test_stop_sticky(self):
        a=self.create('A520，金属摩擦声，剧烈振动')
        b=self.store.append(a['session_id'],'现在没有异常，继续运行','append',1,'second')
        self.assertEqual(b['latest_report']['status'],'SAFE_BLOCKED')
        self.assertFalse(b['latest_report']['stop_policy']['restart_authorized'])
        self.assertEqual(b['latest_report']['model_review']['status'],'skipped_safety_gate')

    def test_expert_cannot_be_cleared_by_temperature_correction(self):
        a=self.create('A203，实际温度200°C')
        b=self.store.append(a['session_id'],'实际温度165°C','correct_measurements',1,'second')
        self.assertEqual(b['latest_report']['status'],'EXPERT_REQUIRED')

    def test_retry_once(self):
        a=self.create();self.assertEqual(self.create(),a)
        self.assertEqual(self.spy.call_count,1)
        b=self.store.append(a['session_id'],'电流0A','append',1,'second')
        self.assertEqual(self.store.append(a['session_id'],'电流0A','append',1,'second'),b)
        self.assertEqual(self.spy.call_count,2)

    def test_stale_and_duplicate_id(self):
        a=self.create()
        with self.assertRaises(SessionConflict):self.store.create('A205','first')
        self.store.append(a['session_id'],'电流0A','append',1,'second')
        with self.assertRaises(SessionConflict):self.store.append(a['session_id'],'电流3A','append',1,'third')
        self.assertEqual(self.spy.call_count,2)

    def test_concurrent_updates(self):
        a=self.create()
        def run(i):
            try:return self.store.append(a['session_id'],'电流0A','append',1,str(i))['revision']
            except SessionConflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(run,[1,2]))
        self.assertCountEqual(result,[2,'conflict'])

    def test_failed_update_keeps_previous(self):
        a=self.create();self.spy.side_effect=RuntimeError('test failure')
        with self.assertRaises(RuntimeError):self.store.append(a['session_id'],'电流0A','append',1,'second')
        self.assertEqual(self.store.get(a['session_id']),a)

    def test_external_isolation(self):
        self.assertFalse(any('EXT-' in str(x) for x in corpus(Knowledge())))
        r=diagnose('NASA涡轮退化，设备型号未知')
        self.assertEqual(r.status,'EXPERT_REQUIRED')
        self.assertFalse(any(e.source_id.startswith('EXT-') for e in r.evidence))

    def test_a520_no_sound_still_stop(self):
        self.assertEqual(diagnose('A520，没有摩擦声').status,'SAFE_BLOCKED')
