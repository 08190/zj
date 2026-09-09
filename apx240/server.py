from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import re
from .sessions import SessionStore, SessionConflict, SessionNotFound
from .engine import diagnose
from .knowledge import ROOT, Knowledge
from .providers import configuration_status
from .reviews import ReviewStore

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def send(self,status,data,kind='application/json; charset=utf-8'):
        body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if not self.local_request(): return self.send(403,{'error':'Local requests only'})
        return self.serve_GET()

    def serve_GET(self):
        if self.path=='/': self.send(200,(ROOT/'web/index.html').read_bytes(),'text/html; charset=utf-8')
        elif self.path=='/manual.pdf':
            # Serve the immutable, hash-verified source bundled with this
            # knowledge snapshot.  The UI page fragment selects the cited page.
            kb=Knowledge()
            self.send(200,(kb.path/'manual.pdf').read_bytes(),'application/pdf')
        elif self.path=='/health':
            try:
                kb=Knowledge()
                self.send(200,{'status':'ok','app_version':'0.5','knowledge_version':kb.manifest['version_id'],
                    'storage_mode':getattr(self.server,'storage_mode','local'),
                    'llm':configuration_status('llm'),'embedding':configuration_status('embedding')})
            except Exception: self.send(503,{'status':'knowledge_unavailable'})
        elif re.fullmatch(r'/api/sessions/[a-f0-9-]{36}',self.path):
            try: self.send(200,self.server.sessions.get(self.path.split('/')[3]))
            except SessionNotFound as e: self.send(404,{'error':str(e)})
            except Exception: self.send(503,{'error':'无法读取本机会话；请检查本地服务'})
        elif re.fullmatch(r'/api/sessions/[a-f0-9-]{36}/review',self.path):
            try:self.send(200,ReviewStore(self.server.sessions).get(self.path.split('/')[3]))
            except SessionNotFound as e:self.send(404,{'error':str(e)})
            except Exception:self.send(503,{'error':'无法读取本地复核记录'})
        else: self.send(404,{'error':'Not found'})

    def local_request(self):
        hosts=[f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
        host_headers=self.headers.get_all('Host',[])
        origin_headers=self.headers.get_all('Origin',[])
        return (len(host_headers)==1 and host_headers[0] in hosts and len(origin_headers)<=1
                and (not origin_headers or origin_headers[0] in ['http://'+h for h in hosts])
                and self.headers.get('Sec-Fetch-Site')!='cross-site')

    def do_POST(self):
        try:
            if self.headers.get_all('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                raise ValueError('请求长度头不合法')
            length=int(self.headers['Content-Length'])
            if not 0<length<=40000: raise ValueError('请求体长度不合法')
            raw=self.rfile.read(length)
            if len(raw)!=length: raise ValueError('请求内容不完整')
            # Drain a bounded body before rejection so Windows does not reset
            # the connection with unread bytes and discard the error response.
            if not self.local_request():return self.send(403,{'error':'Origin rejected'})
            if self.headers.get_content_type()!='application/json':
                return self.send(415,{'error':'请使用 application/json 请求'})
            def unique_object(pairs):
                result={}
                for key,value in pairs:
                    if key in result: raise ValueError('请求包含重复字段')
                    result[key]=value
                return result
            payload=json.loads(raw,object_pairs_hook=unique_object)
            if not isinstance(payload,dict): raise ValueError('请求必须为 JSON 对象')
            if self.path=='/api/diagnose':
                if set(payload)!={'description'}: raise ValueError('请求字段不合法')
                result=diagnose(payload.get('description')).to_dict()
            elif self.path=='/api/sessions':
                if set(payload)!={'message','request_id'}: raise ValueError('请求字段不合法')
                result=self.server.sessions.create(**payload)
            elif re.fullmatch(r'/api/sessions/[a-f0-9-]{36}/turns',self.path):
                if set(payload)!={'message','mode','expected_revision','request_id'}: raise ValueError('请求字段不合法')
                result=self.server.sessions.append(self.path.split('/')[3],**payload)
            elif re.fullmatch(r'/api/sessions/[a-f0-9-]{36}/review',self.path):
                if set(payload)!={'action','actor','note','questions','expected_revision','expected_review_revision','request_id'}:raise ValueError('复核请求字段不合法')
                result=ReviewStore(self.server.sessions).apply(self.path.split('/')[3],**payload)
            else: return self.send(404,{'error':'Not found'})
            self.send(200,result)
        except (ValueError,TypeError) as e: self.send(400,{'error':str(e)})
        except SessionConflict as e: self.send(409,{'error':str(e)})
        except SessionNotFound as e: self.send(404,{'error':str(e)})
        except Exception: self.send(503,{'error':'知识库或服务不可用；停止诊断，请检查本地配置'})

class LocalServer(ThreadingHTTPServer):
    allow_reuse_address=False

    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

def main(port=8765):
    server=LocalServer(('127.0.0.1',port),Handler)
    server.sessions=SessionStore()
    print(f'APX-240 demo: http://127.0.0.1:{port}',flush=True)
    server.serve_forever()

if __name__=='__main__': main()
