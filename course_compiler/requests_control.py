"""Bound actual outbound attempts, including retries; cached results are free locally."""
import json
import threading
import time
import urllib.error
import urllib.request
from .model import ModelError, ModelAuthorizationError


class RequestBudget:
    def __init__(self, limit=1000, cancel=None):
        self.limit=limit; self.cancel=cancel; self.lock=threading.Lock()
        self.calls=0; self.cache_hits=0; self.input_tokens=0; self.output_tokens=0; self.usage_reports=0

    def before_request(self):
        with self.lock:
            if self.cancel and self.cancel.is_set():raise ModelAuthorizationError('已停止新请求，已完成内容保留。')
            if self.calls>=self.limit:raise ModelAuthorizationError(f'已达到本次 {self.limit} 次请求上限，已保留进度；可调整上限后继续。')
            self.calls+=1

    def cache_hit(self):
        with self.lock:self.cache_hits+=1

    def record(self, usage):
        if not isinstance(usage,dict) or not usage:return
        with self.lock:
            self.input_tokens+=int(usage.get('prompt_tokens',usage.get('input_tokens',0)) or 0)
            self.output_tokens+=int(usage.get('completion_tokens',usage.get('output_tokens',0)) or 0)
            self.usage_reports+=1

    def snapshot(self):
        with self.lock:return {'requests':self.calls,'requestLimit':self.limit,'cacheHits':self.cache_hits,
            'reportedInputTokens':self.input_tokens,'reportedOutputTokens':self.output_tokens,
            'usageReports':self.usage_reports,'usageIncomplete':self.usage_reports<self.calls}


def pause(seconds,budget=None):
    if budget and budget.cancel:
        if budget.cancel.wait(seconds):raise ModelAuthorizationError('已停止新请求，已完成内容保留。')
    else:time.sleep(seconds)


def post_document(url,body,key,budget=None,auth='Bearer'):
    for attempt in range(2):
        if budget:budget.before_request()
        headers={'Content-Type':'application/json'}
        if key:headers['Authorization']=auth+' '+key
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=150) as response:raw=json.load(response)
            if budget:budget.record(raw.get('usage',{}))
            return raw
        except urllib.error.HTTPError as e:
            if e.code in (401,402,403):raise ModelAuthorizationError(f'文档服务授权或额度不可用（HTTP {e.code}）。') from None
            if attempt or e.code not in (408,429,500,502,503,504):raise ModelError(f'文档服务 HTTP {e.code}；已保留原页，可重试。') from None
            try:delay=min(30,max(2,float(e.headers.get('Retry-After',2))))
            except (ValueError,TypeError):delay=2
        except (TimeoutError,urllib.error.URLError,ConnectionError) as e:
            if attempt:raise ModelError('文档请求超时或连接失败；已保留原页。') from None
            delay=2
        except (ValueError,AttributeError):raise ModelError('文档服务未返回有效 JSON，未自动重复付费请求。') from None
        pause(delay,budget)
