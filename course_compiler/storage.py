"""Local JSON library and Windows account-bound encrypted API profiles. No database."""
import base64
import copy
import ctypes
import json
import os
import sys
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit
from .paths import data_root
from .config import local_settings
from .search_providers import PROVIDERS,validate_provider,validate_key,validate_engine

ROLES=('parse','translation','explanation')
def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8');temp.replace(path)

def protect(text,decode=False):
    if sys.platform=='darwin':
        from .mac_security import protect_key
        return protect_key(text,decode)
    if os.name!='nt':raise ValueError('当前系统尚未提供安全密钥存储。此桌面发行版面向 Windows。')
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_char))]
    raw=base64.b64decode(text) if decode else text.encode();buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_char)));dest=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decode else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest)):raise ValueError('Windows 无法读取本账户的 API 密钥，请重新填写。')
    try:
        value=ctypes.string_at(dest.data,dest.size)
        return value.decode() if decode else base64.b64encode(value).decode()
    finally:ctypes.windll.kernel32.LocalFree(dest.data)

def validate_profile(p):
    from .parsers import validate_parser_connection
    validate_parser_connection(p)
    if p.get('provider','openai') not in ('openai','siliconflow','anthropic'):raise ValueError('接口格式无效。')
    if p.get('engine','vision') not in ('vision','glm-ocr','unlimited-ocr','paddle-layout','local-layout-ocr'):raise ValueError('文档解析引擎无效。')
    if p.get('ocrFlavor','auto') not in ('auto','paddle','glm','deepseek','vision'):raise ValueError('区域 OCR 协议无效。')
    if not isinstance(p.get('maxOcrRegions',32),int) or not 1<=p.get('maxOcrRegions',32)<=100:raise ValueError('单页 OCR 区域上限应为 1–100。')
    if p.get('authScheme','Bearer') not in ('Bearer','token'):raise ValueError('认证方式无效。')
    url=urlsplit(p.get('baseUrl',''))
    if url.scheme!='https' and not(url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('API 地址须使用 HTTPS，本地模型可使用 HTTP。')
    if url.username or url.password or url.query or url.fragment:raise ValueError('API 地址不能包含密码、查询参数或片段。')
    if not isinstance(p.get('model'),str) or not 0<len(p['model'])<=150:raise ValueError('请填写模型名称。')

class Store:
    def __init__(self,root=None):
        self.root=Path(root or data_root());self.root.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock()
    def read(self,name,default):
        p=self.root/name
        if not p.exists():return copy.deepcopy(default)
        try:return json.loads(p.read_text('utf-8'))
        except (ValueError,OSError):raise ValueError(f'本地文件 {name} 无法读取，请恢复备份。') from None
    def defaults(self):
        cfg=local_settings();key=cfg.get('SILICONFLOW_API_KEY','')
        common={'provider':'siliconflow','baseUrl':cfg.get('SILICONFLOW_BASE_URL','https://api.siliconflow.cn/v1'),'model':cfg.get('COURSE_MODEL','Qwen/Qwen3.8-27B'),'engine':'vision','apiKey':key}
        parser={**common,'model':'PaddlePaddle/PaddleOCR-VL-1.5','engine':'local-layout-ocr','ocrFlavor':'paddle','maxOcrRegions':32}
        return {'version':2,'settingsMode':'advanced','profiles':{'parse':parser,'translation':{**common,'inherit':False},'explanation':{**common,'inherit':False}},'workers':3,'parseMode':'adaptive','requestLimit':1000}
    def settings(self,public=False):
        with self.lock:
            value=self.read('settings.json',None)
            if value is None:value=self.defaults()
            else:
                for p in value['profiles'].values():
                    try:p['apiKey']=protect(p.pop('encryptedKey'),True) if p.get('encryptedKey') else ''
                    except ValueError:p['apiKey']='';p['keyUnavailable']=True
            value.setdefault('settingsMode','simple' if all(value['profiles'].get(r,{}).get('inherit') for r in ('translation','explanation')) else 'advanced')
            value.setdefault('requestLimit',1000)
            raw=value.get('webSearch',{});provider=validate_provider(raw.get('provider','bocha'))
            saved=raw.get('profiles',{provider:raw});search={'provider':provider,'profiles':{}}
            for name in PROVIDERS:
                p=saved.get(name,{});profile={}
                if name=='serpapi':profile['engine']=validate_engine(p.get('engine','google'))
                try:profile['apiKey']=protect(p['encryptedKey'],True) if p.get('encryptedKey') else p.get('apiKey','')
                except ValueError:profile['apiKey']='';profile['keyUnavailable']=True
                search['profiles'][name]=profile
            search['apiKey']=search['profiles'][provider]['apiKey'];value['webSearch']=search
            if public:
                for p in value['profiles'].values():p['hasApiKey']=bool(p.pop('apiKey',''))
                for p in search['profiles'].values():p['hasApiKey']=bool(p.pop('apiKey',''))
                search['hasApiKey']=bool(search.pop('apiKey',''))
                value['secureStorage']='Windows DPAPI' if os.name=='nt' else 'macOS Keychain' if sys.platform=='darwin' else 'unavailable'
            return value
    def save_settings(self,incoming):
        with self.lock:
            old=self.settings();result={'version':2,'settingsMode':incoming.get('settingsMode','advanced'),'profiles':{},'workers':incoming.get('workers',3),'parseMode':incoming.get('parseMode','adaptive'),'requestLimit':incoming.get('requestLimit',1000)}
            if result['settingsMode'] not in ('simple','advanced'):raise ValueError('设置模式无效。')
            if type(result['requestLimit']) is not int or not 1<=result['requestLimit']<=10000:raise ValueError('请求上限须为 1–10000。')
            if type(result['workers']) is not int or not 1<=result['workers']<=8:raise ValueError('并发数须为 1–8。')
            if result['parseMode'] not in ('adaptive','vision'):raise ValueError('解析策略无效。')
            for role in ROLES:
                p=incoming.get('profiles',{}).get(role,{})
                if not isinstance(p,dict):raise ValueError('模型配置格式无效。')
                p={k:p[k] for k in ('provider','baseUrl','model','engine','authScheme','ocrFlavor','maxOcrRegions','inherit','apiKey','clearKey') if k in p}
                if role=='parse':p['inherit']=False
                if not p.get('inherit'):validate_profile(p)
                prior=old['profiles'].get(role,{})
                key=p.pop('apiKey','')
                if not isinstance(key,str) or len(key)>4096:raise ValueError('API 密钥格式无效。')
                if not key and not p.pop('clearKey',False) and p.get('baseUrl')==prior.get('baseUrl'):key=prior.get('apiKey','')
                if key:p['encryptedKey']=protect(key)
                result['profiles'][role]=p
            search=incoming.get('webSearch',{})
            if not isinstance(search,dict):raise ValueError('搜索配置格式无效。')
            provider=validate_provider(search.get('provider',old['webSearch']['provider']))
            incoming_profiles=search.get('profiles',{})
            if not isinstance(incoming_profiles,dict) or any(name not in PROVIDERS for name in incoming_profiles):raise ValueError('搜索配置包含未知服务。')
            result['webSearch']={'provider':provider,'profiles':{}}
            for name in PROVIDERS:
                prior=old['webSearch']['profiles'][name]
                # Older clients edit only the active service. Keys never cross service boundaries.
                p=incoming_profiles.get(name,search if name==provider and 'profiles' not in search else {})
                if not isinstance(p,dict):raise ValueError('搜索配置格式无效。')
                key=validate_key(p.get('apiKey',''))
                if not key and not p.get('clearKey'):key=prior.get('apiKey','')
                saved={}
                if name=='serpapi':saved['engine']=validate_engine(p.get('engine',prior.get('engine','google')))
                if key:saved['encryptedKey']=protect(key)
                result['webSearch']['profiles'][name]=saved
            atomic_json(self.root/'settings.json',result)
            return self.settings(public=True)
    def search_profile(self,incoming=None):
        saved=self.settings()['webSearch'];incoming={} if incoming is None else incoming
        if not isinstance(incoming,dict):raise ValueError('搜索配置格式无效。')
        provider=validate_provider(incoming.get('provider',saved['provider']))
        prior=saved['profiles'][provider];key=validate_key(incoming.get('apiKey',''))
        if not key and not incoming.get('clearKey'):key=prior.get('apiKey','')
        result={'provider':provider,'apiKey':key}
        if provider=='serpapi':result['engine']=validate_engine(incoming.get('engine',prior.get('engine','google')))
        return result
    def profiles(self):
        value=self.settings();ps=value['profiles'];result={r:copy.deepcopy(ps['parse'] if ps[r].get('inherit') else ps[r]) for r in ROLES}
        if any(result[r].get('engine') in ('glm-ocr','unlimited-ocr','paddle-layout','local-layout-ocr') for r in ('translation','explanation')):raise ValueError('专用 OCR 模型不能翻译或作为 AI 助手，请为这两个阶段选择文本模型。')
        return result

    def probe_profile(self,role,incoming):
        if role not in ROLES:raise ValueError('请选择有效阶段。')
        p=copy.deepcopy(incoming)
        prior=self.settings()['profiles'].get(role,{})
        if p.get('inherit'):p=copy.deepcopy(self.settings()['profiles']['parse'])
        elif not p.get('apiKey') and p.get('baseUrl')==prior.get('baseUrl'):p['apiKey']=prior.get('apiKey','')
        validate_profile(p)
        if role!='parse' and p.get('engine')!='vision':raise ValueError('翻译和 AI 助手请选择文本模型。')
        return p
    def courses(self):return self.read('library.json',[])
    def save_course(self,item):
        with self.lock:
            rows=[c for c in self.courses() if c['id']!=item['id']];rows.insert(0,item);atomic_json(self.root/'library.json',rows)
    def course_path(self,cid):
        if not re.fullmatch(r'course-[a-f0-9]{16}',cid):raise ValueError('课程编号无效。')
        return self.root/'courses'/cid
    def save_learning(self,cid,state):
        self.course_path(cid)
        if not isinstance(state,dict) or state.get('courseId')!=cid:raise ValueError('学习记录不属于此课程。')
        with self.lock:
            previous=self.learning(cid)
            if previous and previous.get('savedAt',0)>state.get('savedAt',0):return
            atomic_json(self.root/'notes'/(cid+'.json'),state)
    def learning(self,cid):
        self.course_path(cid);return self.read('notes/'+cid+'.json',None)
