"""Loopback-only compiler UI. No credentials or backend are exported to the static site."""
import hashlib
import json
import mimetypes
import os
import re
import secrets
import threading
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .model import Model
from .pipeline import compile_course
from .export import export_site

ROOT=Path(__file__).resolve().parent.parent
TOKEN=secrets.token_urlsafe(32)
JOBS={}
FILES={}
LOCK=threading.Lock()
MAX_UPLOAD=250*1024*1024


def index_files():
    for p in list(ROOT.glob('*'))+list((ROOT/'input').rglob('*')):
        if p.is_file() and p.suffix.lower() in ('.pdf','.ppt','.pptx'):
            fid=hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:16]
            FILES[fid]=p


def file_items():
    return [{'id':fid,'name':p.name,'size':p.stat().st_size} for fid,p in FILES.items() if p.exists()]


def run_job(job,paths,settings):
    def progress(stage,current,total,message):
        event={'stage':stage,'current':current,'total':total,'message':message}
        with LOCK:
            job['progress']=event
            job['events']=(job['events']+[event])[-40:]
    try:
        model=Model(provider=settings.get('provider'),base_url=settings.get('baseUrl') or None,model=settings.get('model') or None,api_key=settings.get('apiKey') or None)
        ocr_name=settings.get('ocrModel','').strip()
        ocr_model=False if ocr_name.lower()=='none' else Model(provider=model.provider,base_url=model.base_url,api_key=model.api_key,model=ocr_name) if model.provider=='siliconflow' and ocr_name else None
        ai=not settings.get('extractOnly',False)
        if ai and not model.available:
            raise ValueError('请填写模型密钥或选择“仅提取原文”。密钥仅保留在本地进程内存中。')
        output=ROOT/'output'/job['id']
        course=compile_course(paths,output,model=model,workers=settings.get('workers',3),ai=ai,progress=progress,cancel=job['cancel'],ocr_model=ocr_model)
        bundle=ROOT/'output'/(job['id']+'.zip')
        export_site(course,output,bundle)
        job['quality']=course['quality']
        job['status']='blocked' if course.get('status')=='blocked' else 'cancelled' if job['cancel'].is_set() else 'complete' if course['quality']['complete'] else 'partial'
        job['readerUrl']='/courses/'+job['id']+'/index.html'
        job['downloadUrl']='/download/'+job['id']+'.zip'
        job['outputPath']=str(output)
    except Exception as e:
        job['status']='error'
        job['error']=str(e) if isinstance(e,(ValueError,RuntimeError)) else '编译失败：'+type(e).__name__


class Handler(BaseHTTPRequestHandler):
    server_version='CourseCompiler/1.0'

    def log_message(self,fmt,*args):
        # Do not log request bodies, configuration or authorization headers.
        pass

    def json_response(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)

    def safe_request(self,mutation=False):
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            self.json_response(403,{'error':'仅接受本机访问。'});return False
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in allowed}:
            self.json_response(403,{'error':'不允许跨站请求。'});return False
        if mutation and not secrets.compare_digest(self.headers.get('X-Course-Token',''),TOKEN):
            self.json_response(403,{'error':'页面会话已失效，请刷新。'});return False
        return True

    def serve_file(self,root,relative):
        root=root.resolve();p=(root/urllib.parse.unquote(relative)).resolve()
        if not p.is_relative_to(root) or not p.is_file() or any(part.startswith('.') for part in p.relative_to(root).parts):
            self.json_response(404,{'error':'未找到文件。'});return
        content_type=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        if p.suffix=='.js':content_type='text/javascript'
        self.send_response(200);self.send_header('Content-Type',content_type+('; charset=utf-8' if content_type.startswith('text/') else ''));self.send_header('Content-Length',str(p.stat().st_size));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-cache');self.send_header('Referrer-Policy','no-referrer');self.end_headers()
        with p.open('rb') as stream:
            while chunk:=stream.read(1024*1024):
                self.wfile.write(chunk)

    def do_GET(self):
        if not self.safe_request():return
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/status':
            model=Model()
            from .config import local_settings
            return self.json_response(200,{'token':TOKEN,'files':file_items(),'modelConfigured':model.available,'provider':model.provider,'model':model.model,'ocrModel':local_settings().get('COURSE_OCR_MODEL','PaddlePaddle/PaddleOCR-VL-1.5') if model.provider=='siliconflow' else '', 'hasReader':(ROOT/'dist'/'index.html').exists(),'converterAvailable':bool(__import__('course_compiler.extract',fromlist=['locate_converter']).locate_converter())})
        if path.startswith('/api/jobs/'):
            job=JOBS.get(path.rsplit('/',1)[-1])
            return self.json_response(200,{k:v for k,v in job.items() if k!='cancel'}) if job else self.json_response(404,{'error':'任务不存在。'})
        if path in ('/','/compiler'):
            return self.serve_file(ROOT/'web','compiler.html')
        if path.startswith('/web/'):
            return self.serve_file(ROOT/'web',path[5:])
        if path.startswith('/reader/'):
            return self.serve_file(ROOT/'dist',path[8:] or 'index.html')
        if path.startswith('/courses/'):
            return self.serve_file(ROOT/'output',path[9:])
        if path.startswith('/download/') and re.fullmatch(r'/download/job-[a-f0-9]{16}\.zip',path):
            return self.serve_file(ROOT/'output',path.rsplit('/',1)[-1])
        self.json_response(404,{'error':'页面不存在。'})

    def do_POST(self):
        if not self.safe_request(True):return
        try:
            length=int(self.headers.get('Content-Length','0'))
            path=urllib.parse.urlsplit(self.path).path
            if path=='/api/upload':
                if not 0<length<=MAX_UPLOAD:raise ValueError('单文件大小须在 0–250 MB 之间。')
                name=Path(urllib.parse.unquote(self.headers.get('X-Filename',''))).name
                if '\\' in name or '/' in name or name in ('.','..'):raise ValueError('文件名无效。')
                ext=Path(name).suffix.lower()
                if ext not in ('.pdf','.pptx','.ppt'):raise ValueError('只支持 PDF、PPTX、PPT。')
                payload=self.rfile.read(length)
                if len(payload)!=length:raise ValueError('上传中断，请重试。')
                if ext=='.pdf' and not payload.startswith(b'%PDF'):raise ValueError('不是有效 PDF。')
                if ext=='.ppt' and not payload.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):raise ValueError('不是有效 PPT。')
                if ext=='.pptx':
                    import io
                    try:
                        with zipfile.ZipFile(io.BytesIO(payload)) as z:
                            if 'ppt/presentation.xml' not in z.namelist():raise ValueError('不是有效 PPTX。')
                            if sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('PPTX 解压体积过大。')
                    except zipfile.BadZipFile:raise ValueError('PPTX 文件已损坏。')
                fid=hashlib.sha256(payload).hexdigest()[:16]
                dest=ROOT/'input'/fid/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload);FILES[fid]=dest
                return self.json_response(200,{'id':fid,'name':name,'size':length})
            if not 0<length<=100000:raise ValueError('请求大小无效。')
            settings=json.loads(self.rfile.read(length))
            if path=='/api/compile':
                if any(j['status']=='running' for j in JOBS.values()):
                    return self.json_response(409,{'error':'已有课程正在编译，请等待完成或停止。'})
                ids=settings.get('files',[])
                if not isinstance(ids,list) or not ids or any(i not in FILES for i in ids):raise ValueError('请选择有效讲义。')
                if len(ids)>100:raise ValueError('一次最多选择 100 份文件。')
                paths=[FILES[i] for i in dict.fromkeys(ids)]
                if settings.get('provider') not in (None,'openai','anthropic'):raise ValueError('不支持的模型服务格式。')
                url=settings.get('baseUrl') or ''
                if url:
                    parsed=urllib.parse.urlsplit(url)
                    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost')):raise ValueError('模型地址须使用 HTTPS；本机模型可用 HTTP。')
                    if parsed.username or parsed.password:raise ValueError('模型地址中不能包含密码。')
                if not isinstance(settings.get('workers',3),int) or not 1<=settings.get('workers',3)<=8:raise ValueError('并发数须为 1–8。')
                # Stable destination also makes checkpoint resume reusable and reviewable.
                from .extract import natural_key
                digest=hashlib.sha256(''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths,key=natural_key)).encode()).hexdigest()[:16]
                jid='job-'+digest
                job={'id':jid,'status':'running','progress':{'stage':'prepare','current':0,'total':0,'message':'正在准备讲义'},'events':[],'cancel':threading.Event()}
                with LOCK:
                    if any(j['status']=='running' for j in JOBS.values()):
                        return self.json_response(409,{'error':'已有课程正在编译，请等待完成或停止。'})
                    JOBS[jid]=job
                threading.Thread(target=run_job,args=(job,paths,settings),daemon=True).start()
                return self.json_response(202,{'id':jid})
            if path.startswith('/api/cancel/'):
                job=JOBS.get(path.rsplit('/',1)[-1])
                if not job:raise ValueError('任务不存在。')
                job['cancel'].set()
                return self.json_response(200,{'message':'当前模型请求结束后停止，已完成结果会保留。'})
            self.json_response(404,{'error':'未知操作。'})
        except (ValueError,TypeError,KeyError) as e:
            self.json_response(400,{'error':str(e)})
        except Exception:
            self.json_response(500,{'error':'本地处理失败，请查看文件格式并重试。'})


def serve_local(port=8765):
    index_files()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Course Compiler: http://127.0.0.1:{port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()
