import copy
import json
import unittest
from unittest.mock import patch
from apx240.engine import diagnose
from apx240.knowledge import Knowledge
from apx240.observations import parse_observations,single_value
from apx240.providers import ProviderError,post_json,model_json
from apx240.retrieval import vectors,corpus,document_vectors
from apx240.model_review import SCHEMA
from apx240.validation import validate_report

LLM={'APX_LLM_URL':'https://example.invalid/v1/chat/completions','APX_LLM_MODEL':'test-model','APX_LLM_KEY':'test-key'}
EMBED={'APX_EMBEDDING_URL':'https://example.invalid/v1/embeddings','APX_EMBEDDING_MODEL':'test-embedding','APX_EMBEDDING_KEY':'test-key'}
LOW='A203，设定165°C，实际128°C，加热电流0A，没有烟雾和焦味。'

def model_output(report,**overrides):
    return {'risk':'no_additional_risk','risk_quote':'','observations':[],
            'ranking':[{'cause_id':c['cause_id'],'evidence_ids':c['evidence_ids']} for c in reversed(report.possible_causes)],**overrides}

class Stage2(unittest.TestCase):
    def setUp(self):
        p=patch.dict('os.environ',{f'APX_{kind}_{key}':'' for kind in ['LLM','EMBEDDING'] for key in ['URL','MODEL','KEY']})
        p.start();self.addCleanup(p.stop);document_vectors.cache_clear()

    def test_unit_conversion(self):
        o=parse_observations('上游640kPa，设备端4.1bar')
        self.assertEqual(single_value(o,'upstream_pressure'),.64)
        self.assertEqual(single_value(o,'device_pressure'),.41)

    def test_conflict(self):
        r=diagnose('A203，实际128°C，实际200°C')
        self.assertEqual(r.status,'EXPERT_REQUIRED')
        self.assertIn('SAFE-05',r.troubleshooting_order[0]['evidence_ids'])

    def test_risk_numeric(self):
        r=diagnose('A203，实际温度200°C')
        self.assertEqual(r.status,'EXPERT_REQUIRED')
        self.assertIn('PARAMETERS',[e.source_id for e in r.evidence])

    def test_wrong_equipment(self):
        self.assertEqual(diagnose('APX-999 A203').status,'EXPERT_REQUIRED')

    def test_history_same(self):
        r=diagnose(LOW)
        h=next(h for h in r.historical_comparison if h['source_id']=='H02')
        self.assertEqual(len(h['same']),4)
        self.assertEqual(h['differences'],[])
        self.assertEqual(r.possible_causes[0]['cause_id'],'A203-C3')

    def test_history_different(self):
        r=diagnose('A203，设定165°C，实际140°C，加热电流3A')
        h=next(h for h in r.historical_comparison if h['source_id']=='H02')
        self.assertEqual(len(h['differences']),2)
        self.assertEqual(r.possible_causes[0]['cause_id'],'A203-C1')

    def test_pressure_history(self):
        r=diagnose('A310，上游640kPa，设备端4.1bar，有持续漏气声')
        self.assertEqual(r.possible_causes[0]['cause_id'],'A310-C4')

    def test_negative_leak_difference(self):
        r=diagnose('A310，上游0.64MPa，设备端0.41MPa，没有漏气声')
        h=next(h for h in r.historical_comparison if h['source_id']=='H03')
        self.assertTrue(any('漏气' in x for x in h['differences']))

    def test_missing_units_not_invented(self):
        o=parse_observations('实际128，上游64')
        self.assertEqual(o['measurements'],{})

    def test_past_reading_never_current(self):
        r=diagnose('A203，上次实际128°C，加热电流0A，现在实际140°C')
        self.assertEqual(single_value(r.current_observations,'actual_temperature'),140)
        self.assertIsNone(single_value(r.current_observations,'heater_current'))
        self.assertEqual(r.status,'EXPERT_REQUIRED')

    def test_all_safety_denied(self):
        r=diagnose('A203，设定165°C，实际128°C，电流0A，已完成预热，无烟雾和焦味，无异常高温，无剧烈振动，无金属摩擦，无部件松脱，无火花')
        self.assertEqual(r.status,'REPORT_READY')

    def test_double_negation(self):
        self.assertEqual(diagnose('A203，不是没有烟雾').status,'EXPERT_REQUIRED')

    def test_uncertain_risk(self):
        self.assertEqual(diagnose('A310，不确定是否有焦味').status,'EXPERT_REQUIRED')

    def test_model_valid_reorders_only(self):
        baseline=diagnose(LOW)
        data=model_output(baseline,observations=[{'field':'heater_current','quote':'加热电流0A'}])
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',return_value=(data,{'model':'test-model'})):
            r=diagnose(LOW)
        self.assertEqual(r.model_review['status'],'applied')
        # The model may reorder within a deterministic evidence tier, but it
        # cannot promote a currently unsupported cause above priority causes.
        self.assertEqual(r.possible_causes[0]['assessment'],'PRIORITY')
        self.assertEqual(r.possible_causes[0]['cause_id'],'A203-C4')
        self.assertEqual(r.troubleshooting_order,baseline.troubleshooting_order)
        r.to_dict()

    def test_model_hallucination_fallback(self):
        data=model_output(diagnose(LOW),observations=[{'field':'heater_current','quote':'加热电流10A'}])
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',return_value=(data,{})):
            r=diagnose(LOW)
        self.assertEqual(r.model_review['status'],'fallback')

    def test_model_injected_steps_fallback(self):
        data=model_output(diagnose(LOW));data['steps']=['带电拆线']
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',return_value=(data,{})):
            self.assertEqual(diagnose(LOW).model_review['status'],'fallback')

    def test_model_citation_fallback(self):
        data=model_output(diagnose(LOW));data['ranking'][0]['evidence_ids']=['H99']
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',return_value=(data,{})):
            self.assertEqual(diagnose(LOW).model_review['status'],'fallback')

    def test_model_timeout_fallback(self):
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',side_effect=ProviderError('timeout')):
            self.assertEqual(diagnose(LOW).model_review['status'],'fallback')

    def test_model_escalation_updates_work_order(self):
        text='A203，设备附近有奇怪的声音'
        data=model_output(diagnose(text),risk='uncertain',risk_quote='奇怪的声音')
        with patch.dict('os.environ',LLM),patch('apx240.model_review.model_json',return_value=(data,{})):
            r=diagnose(text)
        self.assertEqual(r.status,'EXPERT_REQUIRED')
        self.assertEqual(r.work_order['risk_status'],r.status)
        self.assertEqual(r.troubleshooting_order[0]['evidence_ids'],['SAFE-05'])
        r.to_dict()

    def test_safety_gate_never_calls_remote(self):
        with patch.dict('os.environ',{**LLM,**EMBED}),patch('apx240.model_review.model_json') as model,patch('apx240.retrieval.vectors') as emb:
            for text in ['A205','A520','A203 有烟雾','A999','A203 实际200°C']:
                diagnose(text)
            model.assert_not_called();emb.assert_not_called()

    def test_rag_metadata_filter(self):
        calls=[]
        def fake(texts): calls.append(texts);return [[1.,0.] for t in texts]
        with patch.dict('os.environ',EMBED),patch('apx240.retrieval.vectors',side_effect=fake):
            r=diagnose(LOW)
        self.assertEqual(r.retrieval['semantic_channel'],'embedding')
        self.assertEqual({d['source_id'] for d in r.retrieval['documents']},{'A203','H02','WO-240-042'})
        self.assertEqual(len(calls),2)

    def test_rag_empty_threshold_does_not_assert_alarm(self):
        def fake(texts): return [[1.,0.] for t in texts] if len(texts)>1 else [[0.,1.]]
        with patch.dict('os.environ',EMBED),patch('apx240.retrieval.vectors',side_effect=fake):
            r=diagnose('无明确报警，动作不顺')
        self.assertEqual(r.retrieval['candidates'],[])
        self.assertEqual(r.possible_causes,[])
        self.assertTrue(r.expert_required)

    def test_embedding_malformed_responses(self):
        bad=[{'data':[{'index':0,'embedding':[0,0]}]}, {'data':[{'index':1,'embedding':[1,0]}]},
             {'data':[{'index':0,'embedding':[float('nan'),0]}]}, {'data':[]}]
        with patch.dict('os.environ',EMBED):
            for response in bad:
                with self.subTest(response=response),patch('apx240.retrieval.post_json',return_value=response):
                    with self.assertRaises(ProviderError): vectors(['q'])

    def test_provider_payload(self):
        result={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with patch.dict('os.environ',LLM),patch('apx240.providers.post_json',return_value=result) as post:
            model_json('system','user',SCHEMA)
            sent=post.call_args.args[1]
        self.assertEqual(sent['response_format']['json_schema']['strict'],True)

    def test_refusal(self):
        with patch.dict('os.environ',LLM),patch('apx240.providers.post_json',return_value={'choices':[{'finish_reason':'length','message':{}}]}):
            with self.assertRaises(ProviderError): model_json('system','user',SCHEMA)

    def test_endpoint_security(self):
        for url in ['http://example.com','https://user:secret@example.com/path','https://example.com/?key=secret']:
            with self.assertRaises(ProviderError): post_json({'url':url,'key':'test'}, {})

    def test_runtime_report_guard(self):
        data=diagnose(LOW).to_dict();data['work_order']['restart_approved']=True
        with self.assertRaises(ValueError): validate_report(data)

    def test_corpus_provenance(self):
        docs=corpus(Knowledge())
        self.assertEqual(len(docs),17)
        self.assertTrue(all(d['historical_only'] for d in docs if d['source_type']=='maintenance_record'))
        external=[d for d in docs if d['source_type']=='external_reference_case']
        self.assertEqual(external,[])

if __name__=='__main__': unittest.main()
