import unittest
from unittest.mock import patch

from apx240.engine import diagnose


class ProductRound(unittest.TestCase):
    def offline(self, text):
        with patch.dict('os.environ', {'APX_LLM_MODE':'off','APX_EMBEDDING_MODE':'off'}, clear=False):
            return diagnose(text)

    def test_enumerated_denial_does_not_invent_final_fire_signal(self):
        report=self.offline('A900，无烟雾、焦味、异常高温、剧烈振动、摩擦声、松脱或火花。')
        self.assertNotEqual(report.status,'SAFE_BLOCKED')
        self.assertEqual(report.current_observations['conditions']['起火迹象']['state'],'negative')

    def test_ambiguous_alarm_never_creates_causes(self):
        report=self.offline('代码可能是A205，也可能是A203，最后一位看不清。')
        self.assertEqual(report.status,'EXPERT_REQUIRED')
        self.assertFalse(report.possible_causes)
        self.assertIn('SAFE-05',{e.source_id for e in report.evidence})

    def test_a401_reclose_synonym_triggers_local_stop(self):
        with patch('apx240.retrieval.vectors',side_effect=AssertionError('remote retrieval called')):
            report=self.offline('A401，门框没有夹料，安全门先打开又重新合上，面板报警依旧没有消失。')
        self.assertEqual(report.status,'SAFE_BLOCKED')

    def test_report_exposes_evidence_class_and_trace(self):
        report=self.offline('A203，实际温度128°C，加热电流0A。').to_dict()
        self.assertTrue(all(e['authority'] and e['usage'] for e in report['evidence']))
        self.assertEqual(report['execution_metadata']['trace_id'],report['report_id'])
        self.assertTrue(all(c['verification_status']=='待现场验证' for c in report['possible_causes']))

    def test_structured_context_enters_work_order(self):
        report=self.offline('设备编号：APX240-01\n产线/工位：包装一线\n故障时间：14:20\n报告人：张工\n发生阶段：预热\n报警码：A203').to_dict()
        order=report['work_order']
        self.assertEqual((order['equipment_id'],order['production_line'],order['reporter']),('APX240-01','包装一线','张工'))
        self.assertEqual(order['status'],'DRAFT')
        self.assertFalse(order['restart_approved'])


if __name__=='__main__': unittest.main()
