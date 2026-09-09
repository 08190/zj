import unittest

from apx240.engine import diagnose
from apx240.sessions import summarize_changes


SAFE='无烟雾、焦味、异常高温、剧烈振动、金属摩擦、部件松脱、火花或起火迹象'


class VisibleReasoning(unittest.TestCase):
    def test_causes_are_stratified_without_deletion_or_confirmation(self):
        r=diagnose('A203，设定165°C，实际128°C，加热电流0A，已完成预热，'+SAFE)
        by_id={c['cause_id']:c for c in r.possible_causes}
        self.assertEqual(len(by_id),5)
        self.assertEqual(by_id['A203-C1']['assessment'],'CURRENTLY_UNSUPPORTED')
        self.assertEqual(by_id['A203-C2']['assessment'],'CURRENTLY_UNSUPPORTED')
        self.assertEqual(by_id['A203-C3']['assessment'],'PRIORITY')
        self.assertTrue(all(not c['confirmed'] for c in by_id.values()))

    def test_next_question_uses_active_manual_path(self):
        r=diagnose('A203，实际128°C，加热电流0A，'+SAFE)
        self.assertEqual(r.next_best_question['question'],'是否完成预热')
        self.assertIn('区分',r.next_best_question['reason'])

    def test_safety_block_has_no_diagnostic_question(self):
        r=diagnose('A203，现场有烟雾')
        self.assertEqual(r.status,'SAFE_BLOCKED')
        self.assertEqual(r.next_best_question,{})

    def test_change_summary_names_causes_instead_of_internal_ids(self):
        before=diagnose('A203，实际128°C，'+SAFE).to_dict()
        after=diagnose('A203，实际128°C，加热电流0A，已完成预热，'+SAFE)
        changes=summarize_changes(before,after)
        text='；'.join(changes)
        self.assertIn('加热电流',text)
        self.assertIn('加热器开路',text)
        self.assertIn('未预热：保留候选 → 当前证据不支持',text)
        self.assertNotIn('A203-C3',text)


if __name__=='__main__':unittest.main()
