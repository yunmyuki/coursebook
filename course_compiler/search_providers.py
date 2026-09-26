"""Fixed-endpoint search adapters. One request, no retries or implicit provider fallback."""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS={'bocha':'博查','baidu':'百度 · 千帆','tavily':'Tavily','exa':'Exa','brave':'Brave','serpapi':'SerpApi'}
ENGINES={'google':'Google','bing':'Bing','baidu':'百度'}

def validate_provider(provider):
    if not isinstance(provider,str) or provider not in PROVIDERS:raise ValueError('请选择有效的搜索服务。')
    return provider

def validate_key(key):
    if not isinstance(key,str) or len(key)>4096 or any(c in key for c in '\r\n\0'):raise ValueError('搜索密钥格式无效。')
    return key.strip()

def validate_engine(engine):
    if not isinstance(engine,str) or engine not in ENGINES:raise ValueError('SerpApi 支持 Google、Bing 或百度。')
    return engine

def label(profile):
    provider=validate_provider(profile.get('provider','bocha'))
    return ENGINES[validate_engine(profile.get('engine','google'))]+' · SerpApi' if provider=='serpapi' else PROVIDERS[provider]

def build_request(query,profile):
    provider=validate_provider(profile.get('provider','bocha'));key=validate_key(profile.get('apiKey',''))
    if not key:raise ValueError('请为 '+label(profile)+' 填写搜索密钥。')
    if not isinstance(query,str) or not 0<len(query.strip())<=500:raise ValueError('搜索词须为 1–500 字。')
    query=query.strip();headers={'Accept':'application/json'};body=None
    if provider=='bocha':
        url='https://api.bochaai.com/v1/web-search';headers['Authorization']='Bearer '+key
        body={'query':query,'summary':True,'count':5}
    elif provider=='baidu':
        url='https://qianfan.baidubce.com/v2/ai_search/web_search';headers['Authorization']='Bearer '+key
        body={'messages':[{'role':'user','content':query}],'search_source':'baidu_search_v2','resource_type_filter':[{'type':'web','top_k':5}]}
    elif provider=='tavily':
        url='https://api.tavily.com/search';headers['Authorization']='Bearer '+key
        body={'query':query,'search_depth':'basic','auto_parameters':False,'max_results':5,'include_answer':False,'include_raw_content':False}
    elif provider=='exa':
        url='https://api.exa.ai/search';headers['x-api-key']=key
        body={'query':query,'type':'fast','numResults':5,'contents':{'highlights':True,'text':False}}
    elif provider=='brave':
        if len(query)>400 or len(query.split())>50:raise ValueError('Brave 检索词请缩短至 400 字、50 词以内。')
        url='https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':query,'count':5,'extra_snippets':'true'})
        headers['X-Subscription-Token']=key
    else:
        engine=validate_engine(profile.get('engine','google'))
        params={'engine':engine,'q':query,'api_key':key,'output':'json'}
        if engine=='baidu':params['rn']=5
        # SerpApi specifies query-string authentication. Never log this request URL.
        url='https://serpapi.com/search?'+urllib.parse.urlencode(params)
    if body is not None:headers['Content-Type']='application/json'
    return urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=headers)

def plain(value):
    return html.unescape(re.sub(r'<[^>]*>','',value)) if isinstance(value,str) else ''

def safe_result_url(value):
    if not isinstance(value,str) or len(value)>6000 or re.search(r'[\s\x00-\x1f\x7f]',value):return False
    try:
        u=urllib.parse.urlsplit(value)
        return u.scheme in ('http','https') and bool(u.hostname) and not(u.username or u.password)
    except ValueError:return False

def normalize(provider,body):
    validate_provider(provider)
    if not isinstance(body,dict):raise ValueError('搜索响应格式无效。')
    if body.get('error') or body.get('error_code'):raise ValueError('搜索服务返回错误，请检查密钥、权限和额度。')
    code=body.get('code')
    if code not in (None,0,'0',200,'200'):raise ValueError('搜索服务返回错误，请检查权限和额度。')
    if provider=='bocha':
        data=body.get('data',body)
        rows=data.get('webPages',{}).get('value') if isinstance(data,dict) else None
    elif provider=='baidu':rows=body.get('references')
    elif provider=='brave':
        if 'web' not in body and 'query' not in body:raise ValueError('搜索响应格式无效。')
        rows=body.get('web',{}).get('results',[])
    elif provider=='serpapi':
        if 'organic_results' not in body and body.get('search_metadata',{}).get('status')!='Success':raise ValueError('搜索响应格式无效。')
        if body.get('search_metadata',{}).get('status') in ('Error','Processing'):raise ValueError('搜索尚未成功返回，请稍后重试。')
        rows=body.get('organic_results',[])
    else:rows=body.get('results')
    if not isinstance(rows,list):raise ValueError('搜索服务未返回有效的结果列表。')
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):continue
        url=row.get('url',row.get('link',''))
        if not safe_result_url(url) or url in seen:continue
        if provider=='bocha':text=row.get('summary') or row.get('snippet','')
        elif provider=='brave':text='\n'.join([s for s in [row.get('description',''),*(row.get('extra_snippets',[]) if isinstance(row.get('extra_snippets',[]),list) else [])] if isinstance(s,str)])
        elif provider=='exa':text='\n'.join(x for x in row.get('highlights',[]) if isinstance(x,str)) if isinstance(row.get('highlights'),list) else row.get('text','')
        elif provider=='serpapi':
            text=row.get('snippet','')
            if not text:
                rich=row.get('rich_snippet',[]);rich=rich if isinstance(rich,list) else [rich]
                text='\n'.join(s for r in rich if isinstance(r,dict) for s in r.get('extensions',[]) if isinstance(s,str))
        else:text=row.get('content','')
        seen.add(url);result.append({'title':plain(row.get('title',row.get('name','')))[:200] or url,'url':url,'text':plain(text)[:2000]})
        if len(result)==5:break
    return result

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def search(query,profile,budget):
    request=build_request(query,profile);name=label(profile)
    budget.before_request()
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('搜索响应过大。')
        return normalize(profile.get('provider','bocha'),json.loads(raw))
    except urllib.error.HTTPError as e:
        reason='密钥或访问权限无效' if e.code in (401,403) else '额度不足或请求过于频繁' if e.code in (402,429,432,433) else '服务请求未成功'
        raise ValueError(f'{name}：{reason}（HTTP {e.code}）。') from None
    except (TimeoutError,urllib.error.URLError,ConnectionError):raise ValueError(f'{name}：连接失败或超时，请检查网络后重试。') from None
    except (ValueError,TypeError,AttributeError,KeyError):raise ValueError(f'{name}：搜索响应无效，请检查服务权限或额度。') from None

def probe(store,incoming):
    from .requests_control import RequestBudget
    profile=store.search_profile(incoming);rows=search('effective study methods',profile,RequestBudget(1))
    return {'ok':True,'provider':profile['provider'],'message':f'{label(profile)} 已连接，返回 {len(rows)} 条网页结果。'+('当前测试无匹配结果。' if not rows else ''),'count':len(rows)}
