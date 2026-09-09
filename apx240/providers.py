"""APX-only configuration. No inherited tool credentials or automatic retries."""
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from .diagnostics import API_CODES

class ProviderError(Exception):
    def __init__(self, code, api_code=None):
        super().__init__(code)
        self.api_code=api_code if api_code in API_CODES else None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('redirect_rejected')

def configuration(kind):
    prefix='APX_'+kind.upper()+'_'
    names=['URL','MODEL','KEY']
    return {n.lower():os.getenv(prefix+n,'') for n in names}

def configuration_status(kind):
    c=configuration(kind)
    return 'configured' if all(c.values()) else 'partial' if any(c.values()) else 'disabled'

def post_json(config,payload):
    url=urllib.parse.urlsplit(config['url'])
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise ProviderError('invalid_endpoint')
    req=urllib.request.Request(config['url'],data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+config['key']},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response:
            data=response.read(2_000_001)
            if len(data)>2_000_000: raise ProviderError('response_too_large')
            return json.loads(data)
    except urllib.error.HTTPError as e:
        api_code=None
        try:
            body=json.loads(e.read(65536))
            error=body.get('error',{}) if isinstance(body,dict) else {}
            candidate=error.get('code') if isinstance(error,dict) else None
            if isinstance(candidate,str) and candidate in API_CODES: api_code=candidate
        except (OSError,ValueError): pass
        finally: e.close()
        raise ProviderError('http_'+str(e.code),api_code) from None
    except urllib.error.URLError as e:
        reason=e.reason
        code='timeout' if isinstance(reason,TimeoutError) else 'tls_error' if isinstance(reason,ssl.SSLError) else 'dns_error' if isinstance(reason,socket.gaierror) else 'connection_error'
        raise ProviderError(code) from None
    except TimeoutError:
        raise ProviderError('timeout') from None
    except ssl.SSLError:
        raise ProviderError('tls_error') from None
    except (OSError,ValueError) as e:
        # Do not expose vendor error bodies, URLs, keys or prompts.
        raise ProviderError('transport_or_json_error') from None

def model_json(system,user,schema):
    cfg=configuration('llm')
    if not all(cfg.values()): raise ProviderError('not_configured')
    mode=os.getenv('APX_LLM_FORMAT','json_schema')
    if mode not in ['json_schema','json_object']: raise ProviderError('invalid_format')
    response_format={'type':'json_schema','json_schema':{'name':'apx240_review','strict':True,'schema':schema}} if mode=='json_schema' else {'type':'json_object'}
    payload={'model':cfg['model'],'messages':[{'role':'system','content':system},
        {'role':'user','content':json.dumps(user,ensure_ascii=False)}],'response_format':response_format}
    result=post_json(cfg,payload)
    try:
        choice=result['choices'][0]
        if choice.get('finish_reason')!='stop' or choice['message'].get('refusal'):
            raise ProviderError('refused_or_incomplete')
        content=choice['message']['content']
        if not isinstance(content,str): raise ProviderError('invalid_content')
        raw_usage=result.get('usage',{})
        usage={k:v for k,v in raw_usage.items() if k in ['prompt_tokens','completion_tokens','total_tokens'] and type(v) is int and v>=0} if isinstance(raw_usage,dict) else {}
        return json.loads(content), {'model':cfg['model'],'usage':usage}
    except (KeyError,IndexError,TypeError,ValueError):
        raise ProviderError('invalid_response') from None
