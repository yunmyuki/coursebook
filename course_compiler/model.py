"""Small server-side model adapter. Credentials never enter exported assets or caches."""
import base64
import hashlib
import http.client
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from .config import local_settings


class ModelError(RuntimeError):
    pass


class ModelAuthorizationError(ModelError):
    """Non-retryable authorization/quota error: stop the course queue."""
    pass


class Model:
    def __init__(self, provider=None, base_url=None, model=None, api_key=None, cache=None):
        settings=local_settings()
        self.provider = provider or settings.get('COURSE_PROVIDER') or ('siliconflow' if settings.get('SILICONFLOW_API_KEY') else 'anthropic' if settings.get('ANTHROPIC_AUTH_TOKEN') else 'openai')
        sf=self.provider=='siliconflow'
        self.base_url = (base_url or settings.get('COURSE_BASE_URL') or settings.get('SILICONFLOW_BASE_URL' if sf else 'ANTHROPIC_BASE_URL' if self.provider=='anthropic' else 'OPENAI_BASE_URL') or ('https://api.siliconflow.cn/v1' if sf else 'https://api.anthropic.com' if self.provider=='anthropic' else 'https://api.openai.com/v1')).rstrip('/')
        self.model = model or settings.get('COURSE_MODEL') or ('Qwen/Qwen3.8-27B' if sf else 'claude-sonnet-4-6' if self.provider=='anthropic' else 'gpt-4.1')
        self.api_key = api_key or settings.get('COURSE_API_KEY') or (settings.get('SILICONFLOW_API_KEY','') if sf else settings.get('ANTHROPIC_AUTH_TOKEN') or settings.get('ANTHROPIC_API_KEY','') if self.provider=='anthropic' else settings.get('OPENAI_API_KEY',''))
        self.cache = Path(cache or '.course-cache/model')
        self.cache.mkdir(parents=True, exist_ok=True)

    @property
    def available(self):
        return bool(self.api_key)

    def request(self, system, data, image=None, max_tokens=12000, json_output=True, validator=None):
        from .cache_locks import request_lock
        text=data if isinstance(data,str) else json.dumps(data,ensure_ascii=False)
        signature=(str(self.cache.resolve()),self.base_url,self.model,system,text,hashlib.sha256(Path(image).read_bytes()).hexdigest() if image else '',json_output,json.dumps(getattr(self,'request_options',{}),sort_keys=True))
        with request_lock(hashlib.sha256(repr(signature).encode()).hexdigest()):
            return self._request(system,data,image,max_tokens,json_output,validator)

    def _request(self, system, data, image=None, max_tokens=12000, json_output=True, validator=None):
        if not self.available:
            raise ModelError('未配置模型密钥。可先提取原文，配置模型后继续。')
        text = data if isinstance(data,str) else json.dumps(data, ensure_ascii=False)
        b64 = base64.b64encode(Path(image).read_bytes()).decode() if image else None
        media_type=(mimetypes.guess_type(str(image))[0] or 'image/jpeg') if image else None
        key = hashlib.sha256((('raw:' if not json_output else '') + self.base_url + self.model + system + text + (b64 or '') + (getattr(self,'image_detail','') if image else '') + (json.dumps(self.request_options,sort_keys=True) if getattr(self,'request_options',None) else '')).encode()).hexdigest()
        target = self.cache / (key + '.json')
        if target.exists():
            try:
                cached=json.loads(target.read_text('utf-8'))
                if validator:validator(cached)
            except (ValueError,ModelError):target.replace(target.with_suffix('.invalid.json'))
            else:
                if getattr(self,'budget',None):self.budget.cache_hit()
                return cached
        if self.provider == 'anthropic':
            content = []
            if b64:
                content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': b64}})
            content.append({'type': 'text', 'text': text})
            body = {'model': self.model, 'max_tokens': max_tokens, 'system': system, 'messages': [{'role': 'user', 'content': content}]}
            url = self.base_url + ('/messages' if self.base_url.endswith('/v1') else '/v1/messages')
            headers = {'x-api-key': self.api_key, 'Authorization': 'Bearer ' + self.api_key, 'anthropic-version': '2023-06-01'}
        else:
            content = [{'type': 'text', 'text': text}]
            if b64:
                content.append({'type': 'image_url', 'image_url': {'url': 'data:'+media_type+';base64,' + b64}})
                if getattr(self,'image_detail',None):content[-1]['image_url']['detail']=self.image_detail
            if b64 and 'PaddleOCR' in self.model:content.reverse()
            body = {'model': self.model, 'max_tokens': max_tokens, 'messages': ([{'role':'system','content':system}] if system else [])+[{'role':'user','content':content}]}
            if json_output:body['response_format']={'type':'json_object'}
            if self.provider=='siliconflow' and 'Qwen/' in self.model:body.update(enable_thinking=False,temperature=0.1)
            if self.provider=='siliconflow':body['stream']=True
            url = self.base_url + '/chat/completions'
            headers = {'Authorization': 'Bearer ' + self.api_key}
        if getattr(self,'request_options',None):body.update(self.request_options)
        attempts=getattr(self,'max_attempts',4)
        for attempt in range(attempts):
            retry_wait=min(2 ** attempt * 2, 16)
            try:
                if getattr(self,'budget',None):self.budget.before_request()
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=getattr(self,'timeout',600 if body.get('stream') else 240)) as response:
                    if body.get('stream'):
                        parts=[];usage={};finish=None;last_save=0;started=time.time();stream_done=False
                        for line in response:
                            if getattr(self,'timeout',None) and time.time()-started>self.timeout*2:raise ModelError('模型输出超过本页时间限制；已保存记录，可重试。')
                            line=line.decode('utf-8').strip()
                            if not line.startswith('data:'):continue
                            payload=line[5:].strip()
                            if payload=='[DONE]':stream_done=True;break
                            event=json.loads(payload)
                            if event.get('error'):raise ModelError('模型流返回错误；中间识别记录已保留。')
                            if event.get('usage'):usage=event['usage']
                            for choice in event.get('choices',[]):
                                delta=choice.get('delta',{})
                                if isinstance(delta.get('content'),str):parts.append(delta['content'])
                                finish=choice.get('finish_reason') or finish
                            if time.time()-last_save>=5:
                                partial=''.join(parts)
                                (self.cache/(key+'.partial.txt')).write_text(partial,'utf-8')
                                (self.cache/(key+'.progress.json')).write_text(json.dumps({'model':self.model,'characters':sum(map(len,parts)),'started':started,'updated':time.time()}),'utf-8')
                                last_save=time.time()
                                # Only inspect correction reasons, never source passages or table values.
                                # A runaway justification must not spend the whole output budget or be committed.
                                if json_output and re.search(r'"reason"\s*:\s*"[^"\\]{3000}',partial):
                                    raise ModelError('模型校正说明异常冗长；中间结果已保留，本页可重试。')
                        if not stream_done and not finish:raise ValueError('Stream ended before completion')
                        result={'choices':[{'message':{'content':''.join(parts)},'finish_reason':finish}],'usage':usage}
                    else:result=json.load(response)
                (self.cache/(key+'.response.json')).write_text(json.dumps(result,ensure_ascii=False),'utf-8')
                if getattr(self,'budget',None):self.budget.record(result.get('usage',{}))
                (self.cache/(key+'.usage.json')).write_text(json.dumps({'model':self.model,'usage':result.get('usage',{}),'timestamp':time.time()}),'utf-8')
                if self.provider == 'anthropic':
                    raw = ''.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
                    if result.get('stop_reason') == 'max_tokens':
                        raise ModelError('模型输出被截断；本页未标记完成。')
                else:
                    choice = result['choices'][0]
                    raw = choice['message']['content']
                    if choice.get('finish_reason') == 'length':
                        raise ModelError('模型输出被截断；本页未标记完成。')
                raw = raw.strip()
                if json_output and raw.startswith('```'):
                    raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
                parsed = json.loads(raw) if json_output else raw
                if json_output and not isinstance(parsed, dict):
                    raise ValueError('Expected JSON object')
                if not raw:raise ValueError('Empty response')
                if validator:validator(parsed)
                temp = target.with_suffix('.tmp')
                temp.write_text(json.dumps(parsed, ensure_ascii=False), 'utf-8')
                temp.replace(target)
                if body.get('stream'):
                    (self.cache/(key+'.progress.json')).write_text(json.dumps({'model':self.model,'characters':len(raw),'status':'complete','updated':time.time()}),'utf-8')
                return parsed
            except urllib.error.HTTPError as exc:
                if exc.code==429:
                    try:retry_wait=max(15,min(60,float(exc.headers.get('Retry-After') or 20*(attempt+1))))
                    except (TypeError,ValueError):retry_wait=30
                    try:reason=json.loads(exc.read(100000)).get('error',{}).get('code')
                    except (ValueError,AttributeError):reason=None
                    if reason=='insufficient_quota':
                        raise ModelAuthorizationError('模型额度不足，已停止新的请求；完成的内容已保留。') from None
                if exc.code in (401,402,403):
                    raise ModelAuthorizationError(f'模型服务 HTTP {exc.code}：授权或额度不可用，已停止新的请求。请检查服务账户后恢复编译。') from None
                if exc.code not in (408, 429, 500, 502, 503, 504, 529) or attempt == attempts-1:
                    raise ModelError(f'模型服务 HTTP {exc.code}；请检查模型配置或稍后重试。') from None
            except (ValueError,KeyError) as exc:
                raise ModelError('模型输出格式无效，未自动重复生成；原文与响应已保留，可手动重试。') from None
            except (TimeoutError, urllib.error.URLError, http.client.HTTPException, ConnectionError) as exc:
                if attempt == attempts-1:
                    raise ModelError(f'模型请求失败：{type(exc).__name__}；可恢复重试。') from None
            if getattr(self,'budget',None):
                from .requests_control import pause
                pause(retry_wait,self.budget)
            else:time.sleep(retry_wait)
        raise ModelError('模型请求重试失败。')
