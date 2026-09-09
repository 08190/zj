"""Password-protected single-reviewer demo, exclusively behind an HTTPS proxy."""
import base64
import binascii
import hmac
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from urllib.parse import urlsplit
from .server import Handler,LocalServer
from .sessions import SessionStore
from .knowledge import ROOT,Knowledge
from .providers import configuration_status

class PublicConfig:
    def __init__(self):
        self.origin=os.getenv('APX_PUBLIC_ORIGIN') or os.getenv('RENDER_EXTERNAL_URL','')
        self.port=int(os.getenv('PORT','8765'))
        if not 1<=self.port<=65535:raise ValueError('PORT 必须为有效端口')
        parsed=urlsplit(self.origin)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('APX_PUBLIC_ORIGIN 必须为不带路径的 HTTPS 访问域名')
        self.host=parsed.netloc
        self.user=os.getenv('APX_ACCESS_USER','reviewer')
        self.password=os.getenv('APX_ACCESS_PASSWORD','')
        if not self.user or ':' in self.user or len(self.password)<20:
            raise ValueError('请配置独立访问账号和至少20字符的随机访问口令，不要使用API密钥')
        if self.password in [os.getenv('APX_LLM_KEY',''),os.getenv('APX_EMBEDDING_KEY','')]:
            raise ValueError('访问口令不能使用API密钥')
        self.hourly=int(os.getenv('APX_HOURLY_REQUESTS','30'))
        self.daily=int(os.getenv('APX_DAILY_REQUESTS','100'))
        if not 1<=self.hourly<=100 or not 1<=self.daily<=500:raise ValueError('请求上限超出允许范围')

class RequestBudget:
    def __init__(self,path,hourly,daily):
        self.path=path;self.hourly=hourly;self.daily=daily
        with closing(sqlite3.connect(path)) as db,db:db.execute('CREATE TABLE IF NOT EXISTS usage(window TEXT PRIMARY KEY,count INTEGER NOT NULL)')
    def consume(self,now=None):
        moment=int(time.time() if now is None else now)
        windows=[('h'+str(moment//3600),self.hourly),('d'+str(moment//86400),self.daily)]
        with closing(sqlite3.connect(self.path,timeout=5)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            for key,limit in windows:
                row=db.execute('SELECT count FROM usage WHERE window=?',(key,)).fetchone()
                if row and row[0]>=limit:return False
            for key,_ in windows:db.execute('INSERT INTO usage VALUES(?,1) ON CONFLICT(window) DO UPDATE SET count=count+1',(key,))
        return True

class PublicHandler(Handler):
    def authenticated(self):
        headers=self.headers.get_all('Authorization',[])
        if len(headers)!=1 or len(headers[0])>4096:return False
        scheme,_,value=headers[0].partition(' ')
        if scheme.lower()!='basic':return False
        try:decoded=base64.b64decode(value,validate=True)
        except (ValueError,binascii.Error):return False
        cfg=self.server.config
        return hmac.compare_digest(decoded,(cfg.user+':'+cfg.password).encode('utf-8'))
    def local_request(self):
        origins=self.headers.get_all('Origin',[])
        return (self.headers.get_all('Host',[])==[self.server.config.host] and len(origins)<=1
                and (not origins or origins[0]==self.server.config.origin)
                and self.headers.get('Sec-Fetch-Site')!='cross-site')
    def deny(self,status,message):
        # Consume only a well-sized body to return a readable Windows error.
        if self.command=='POST':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if 0<length<=40000 and not self.headers.get('Transfer-Encoding'):self.rfile.read(length)
            except (ValueError,OSError):pass
        body=json.dumps({'error':message},ensure_ascii=False).encode('utf-8');self.send_response(status)
        if status==401:self.send_header('WWW-Authenticate','Basic realm="APX-240 demo", charset="UTF-8"')
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/ready':
            try:
                Knowledge()
                ready=all(configuration_status(k)=='configured' for k in ['llm','embedding'])
                return self.send(200 if ready else 503,{'status':'ready' if ready else 'not_ready'})
            except Exception:return self.send(503,{'status':'not_ready'})
        if not self.authenticated():return self.deny(401,'请使用单独提供的演示访问账号和口令')
        # Authentication protects public read routes.  Do not reuse the local
        # server's loopback-only GET gate: reverse proxies can legitimately
        # rewrite Host details, which previously blocked remote browsers.
        return self.serve_GET()
    def do_POST(self):
        if not self.authenticated():return self.deny(401,'访问身份验证失败')
        if not self.local_request():return self.deny(403,'访问来源不允许')
        if self.path=='/api/diagnose' or self.path=='/api/sessions' or self.path.endswith('/turns'):
            if not self.server.budget.consume():return self.deny(429,'演示请求额度已用完，请联系提交人；不要据此继续设备操作')
        return super().do_POST()
    def log_message(self,format,*args):
        pass  # Avoid persisting session identifiers and access information.

class PublicServer(LocalServer):
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(8)
        super().__init__(*args,**kwargs)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

def main():
    config=PublicConfig();Knowledge()
    if any(configuration_status(k)!='configured' for k in ['llm','embedding']):
        raise ValueError('公网演示必须配置项目模型和向量接口；禁止以未配置状态启动')
    sessions=SessionStore()
    server=PublicServer(('0.0.0.0',config.port),PublicHandler)
    server.sessions=sessions;server.config=config
    server.storage_mode='ephemeral' if os.getenv('APX_EPHEMERAL_STORAGE')=='true' else 'local'
    server.budget=RequestBudget(str(ROOT/'runtime/request-budget.sqlite3'),config.hourly,config.daily)
    print('Protected demo backend ready; expose only through the configured HTTPS proxy.',flush=True)
    server.serve_forever()

if __name__=='__main__':main()
