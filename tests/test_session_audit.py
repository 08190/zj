"""Regression checks for session integrity and the localhost HTTP boundary."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from apx240.engine import diagnose
from apx240.knowledge import Knowledge
from apx240.server import Handler, LocalServer
from apx240.sessions import SessionConflict, SessionStore


class SessionAudit(unittest.TestCase):
    def setUp(self):
        env=patch.dict('os.environ',{f'APX_{kind}_{key}':'' for kind in ['LLM','EMBEDDING'] for key in ['URL','MODEL','KEY']})
        env.start();self.addCleanup(env.stop)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'sessions.db'
        self.spy=Mock(side_effect=diagnose)
        self.store=SessionStore(self.path,self.spy)

    def test_two_stores_deduplicate_before_diagnosis(self):
        def slow(*args,**kwargs):
            time.sleep(.04)
            return diagnose(*args,**kwargs)
        self.spy.side_effect=slow
        other=SessionStore(self.path,self.spy)
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda s:s.create('A203，实际128°C','shared-request'),[self.store,other]))
        self.assertEqual(results[0],results[1])
        self.assertEqual(self.spy.call_count,1)

    def test_two_stores_reject_stale_revision_before_diagnosis(self):
        state=self.store.create('A203，实际128°C','first')
        other=SessionStore(self.path,self.spy)
        def update(args):
            store,request_id=args
            try:return store.append(state['session_id'],'加热电流0A','append',1,request_id)['revision']
            except SessionConflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(update,[(self.store,'second'),(other,'third')]))
        self.assertCountEqual(results,[2,'conflict'])
        self.assertEqual(self.spy.call_count,2)

    def test_same_manual_with_different_knowledge_digest_is_rejected(self):
        state=self.store.create('A203','first')
        kb=Knowledge();kb.snapshot_digest='changed-index-digest'
        with patch('apx240.sessions.Knowledge',return_value=kb):
            with self.assertRaisesRegex(SessionConflict,'知识快照已变化'):
                self.store.append(state['session_id'],'加热电流0A','append',1,'second')
        self.assertEqual(self.spy.call_count,1)
        self.assertEqual(self.store.get(state['session_id']),state)

    def test_legacy_session_is_preserved_but_cannot_silently_continue(self):
        state=self.store.create('A520','first')
        del state['knowledge_snapshot_digest']
        with self.store.connect(write=True) as db:
            db.execute('UPDATE sessions SET state=? WHERE id=?',(json.dumps(state),state['session_id']))
        with self.assertRaisesRegex(SessionConflict,'旧会话'):
            self.store.append(state['session_id'],'现在正常','append',1,'second')
        self.assertEqual(self.store.get(state['session_id'])['safety_latch'],'SAFE_BLOCKED')

    def test_boolean_conflict_across_turns_retains_stop(self):
        state=self.store.create('A203，有烟雾','first')
        state=self.store.append(state['session_id'],'没有烟雾','append',1,'second')
        self.assertEqual(state['latest_report']['status'],'SAFE_BLOCKED')
        self.assertFalse(state['latest_report']['stop_policy']['restart_authorized'])
        self.assertEqual(len(state['turns']),2)


class QuietHandler(Handler):
    def log_message(self,*args):
        pass


class HttpBoundary(unittest.TestCase):
    def setUp(self):
        self.store=Mock()
        self.server=LocalServer(('127.0.0.1',0),QuietHandler)
        self.server.sessions=self.store
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,body,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('POST','/api/sessions',body,headers or {'Content-Type':'application/json'})
            response=conn.getresponse()
            return response.status,json.loads(response.read())
        finally:conn.close()

    def test_cross_site_request_never_reaches_session_store(self):
        status,_=self.request('{}',{'Content-Type':'application/json','Sec-Fetch-Site':'cross-site'})
        self.assertEqual(status,403);self.store.create.assert_not_called()

    def test_cross_origin_request_never_reaches_session_store(self):
        status,_=self.request('{}',{'Content-Type':'application/json','Origin':'https://example.invalid'})
        self.assertEqual(status,403);self.store.create.assert_not_called()

    def test_form_content_cannot_call_json_api(self):
        status,_=self.request('{"message":"A520","request_id":"r1"}',{'Content-Type':'text/plain'})
        self.assertEqual(status,415);self.store.create.assert_not_called()

    def test_duplicate_json_fields_are_rejected(self):
        status,_=self.request('{"message":"A520","message":"A101","request_id":"r1"}')
        self.assertEqual(status,400);self.store.create.assert_not_called()

    def test_client_cannot_override_safety_latch(self):
        status,_=self.request('{"message":"A520","request_id":"r1","safety_latch":null}')
        self.assertEqual(status,400);self.store.create.assert_not_called()

    def test_read_failure_returns_structured_response(self):
        self.store.get.side_effect=RuntimeError('private implementation detail')
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            conn.request('GET','/api/sessions/00000000-0000-0000-0000-000000000000')
            response=conn.getresponse();body=json.loads(response.read())
            self.assertEqual(response.status,503)
            self.assertNotIn('private',body['error'])
        finally:conn.close()
