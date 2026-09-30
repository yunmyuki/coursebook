"""Desktop local workspace API: files, courses, settings and learning records on disk."""
import hashlib
import io
import json
import re
import shutil
import threading
import time
import urllib.parse
import zipfile
from datetime import datetime,timezone
from pathlib import Path
from .server import Handler,TOKEN,MAX_UPLOAD
from .storage import Store,atomic_json
from .paths import resource_root
from .pipeline_v2 import compile_course,course_id
from .export import export_site
from .extract import locate_converter
from . import __version__

class AppHandler(Handler):
    @property
    def store(self):return self.server.store
    def do_GET(self):
        if not self.safe_request():return
        path=urllib.parse.urlsplit(self.path).path
        try:
            if path in ('/','/app','/compiler'):return self.serve_file(resource_root()/'web','desktop.html')
            if path=='/api/status':return self.json_response(200,{'token':TOKEN,'version':__version__,'dataPath':str(self.store.root),'converterAvailable':bool(locate_converter()),'files':self.files(),'courses':self.store.courses(),'settings':self.store.settings(public=True)})
            if path=='/api/settings':return self.json_response(200,self.store.settings(public=True))
            if path=='/api/layout-component':
                from .local_layout import status
                return self.json_response(200,{**status(self.store.root),**getattr(self.server,'layout_install',{})})
            if path.startswith('/api/assistant/'):
                return self.json_response(200,self.server.assistant.snapshot(path.rsplit('/',1)[-1]))
            if path=='/api/library':return self.json_response(200,self.store.courses())
            if path=='/api/jobs':return self.json_response(200,[self.public_job(j) for j in self.server.jobs.values()])
            if path.startswith('/api/jobs/'):
                job=self.server.jobs.get(path.rsplit('/',1)[-1]);return self.json_response(200,self.public_job(job)) if job else self.json_response(404,{'error':'任务不存在。'})
            if path.startswith('/api/learning/'):
                return self.json_response(200,{'state':self.store.learning(path.rsplit('/',1)[-1])})
            if path.startswith('/web/'):return self.serve_file(resource_root()/'web',path[5:])
            if path.startswith('/courses/'):
                parts=path.split('/',3)
                if len(parts)==4:
                    site=self.store.course_path(parts[2]);asset=parts[3] or 'index.html'
                    if asset in ('index.html','styles.css','notion.css','app.js','assistant.js','review.js','favicon.svg') and (site/'course.json').is_file():return self.serve_file(resource_root()/'web',asset)
                    return self.serve_file(site,asset)
            if path.startswith('/download/'):
                cid=Path(path).stem;site=self.store.course_path(cid);bundle=self.store.root/'exports'/(cid+'.zip')
                if not(site/'course.json').exists():raise ValueError('课程不存在。')
                bundle.parent.mkdir(exist_ok=True)
                with self.server.job_lock:
                    if any(j['status']=='running' and j['id']==cid for j in self.server.jobs.values()):return self.json_response(409,{'error':'课程正在处理，请完成后导出。'})
                    export_site(json.loads((site/'course.json').read_text('utf-8')),site,bundle)
                return self.serve_file(bundle.parent,bundle.name)
            return self.json_response(404,{'error':'页面不存在。'})
        except ValueError as e:return self.json_response(400,{'error':str(e)})
    def files(self):
        return [{'id':p.parent.name,'name':p.name,'size':p.stat().st_size} for p in (self.store.root/'input').glob('*/*') if p.is_file() and p.suffix.lower() in ('.pdf','.pptx','.ppt')]
    def public_job(self,job):return {k:v for k,v in job.items() if k not in ('cancel','settings','profiles')}
    def do_POST(self):
        if not self.safe_request(True):return
        path=urllib.parse.urlsplit(self.path).path
        try:
            length=int(self.headers.get('Content-Length','0'))
            if path=='/api/layout-component/import':
                from .local_layout import SIZE,install
                if length!=SIZE:raise ValueError('请选择官方固定版本 inference.onnx（130502049 字节）。')
                with self.server.job_lock:
                    if getattr(self.server,'layout_install',{}).get('downloading') or any(j['status']=='running' for j in self.server.jobs.values()):raise ValueError('请等待当前任务结束后安装版面组件。')
                    import tempfile
                    with tempfile.TemporaryDirectory(dir=self.store.root) as directory:
                        source=Path(directory)/'model.onnx';remaining=length
                        with source.open('wb') as stream:
                            while remaining:
                                chunk=self.rfile.read(min(256*1024,remaining))
                                if not chunk:raise ValueError('模型上传中断。')
                                stream.write(chunk);remaining-=len(chunk)
                        return self.json_response(200,install(self.store.root,source=source))
            if path=='/api/import-course':
                if not 0<length<=250*1024**2:raise ValueError('课程 ZIP 上限 250 MB。')
                with self.server.job_lock:
                    if any(j['status']=='running' for j in self.server.jobs.values()):return self.json_response(409,{'error':'请等待当前编译结束后再导入课程。'})
                    from .import_course import import_course
                    return self.json_response(200,import_course(io.BytesIO(self.rfile.read(length)),self.store))
            if path=='/api/upload':
                if not 0<length<=MAX_UPLOAD:raise ValueError('单文件上限 250 MB。')
                name=urllib.parse.unquote(self.headers.get('X-Filename',''))
                if not name or len(name)>180 or any(x in name for x in '/\\:') or name.startswith('.'):raise ValueError('文件名无效。')
                ext=Path(name).suffix.lower();payload=self.rfile.read(length)
                if len(payload)!=length:raise ValueError('上传中断。')
                if ext=='.pdf':
                    if not payload.startswith(b'%PDF'):raise ValueError('不是有效 PDF。')
                elif ext=='.ppt':
                    if not payload.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):raise ValueError('不是有效 PPT。')
                elif ext=='.pptx':
                    try:
                        with zipfile.ZipFile(io.BytesIO(payload)) as z:
                            if 'ppt/presentation.xml' not in z.namelist() or sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('PPTX 无效或解压后体积过大。')
                    except zipfile.BadZipFile:raise ValueError('PPTX 已损坏。') from None
                else:raise ValueError('支持 PDF、PPTX、PPT。')
                fid=hashlib.sha256(payload).hexdigest()[:16];dest=self.store.root/'input'/fid/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
                return self.json_response(200,{'id':fid,'name':name,'size':length})
            if not 0<length<=8*1024*1024:raise ValueError('请求大小无效。')
            data=json.loads(self.rfile.read(length))
            if path=='/api/layout-component/install':
                from .local_layout import install
                with self.server.job_lock:
                    if getattr(self.server,'layout_install',{}).get('downloading'):return self.json_response(202,{'started':True})
                    if any(j['status']=='running' for j in self.server.jobs.values()):raise ValueError('请等待当前任务结束后安装版面组件。')
                    self.server.layout_install={'downloading':True,'downloadedBytes':0,'error':None}
                server=self.server;root=self.store.root
                def download_component():
                    try:
                        install(root,progress=lambda received,total:server.layout_install.update(downloadedBytes=received))
                        server.layout_install={'downloading':False,'error':None}
                    except Exception:
                        server.layout_install={'downloading':False,'error':'下载或校验失败。可重试，或导入官方 inference.onnx 文件。'}
                threading.Thread(target=download_component,daemon=True).start()
                return self.json_response(202,{'started':True})
            if path=='/api/search/probe':
                from .search_providers import probe
                return self.json_response(200,probe(self.store,data))
            if path.startswith('/api/assistant-cancel/'):
                return self.json_response(200,self.server.assistant.cancel(path.rsplit('/',1)[-1]))
            if path.startswith('/api/assistant/'):
                return self.json_response(202,self.server.assistant.start(path.rsplit('/',1)[-1],data))
            if path=='/api/probe':
                from .probe import probe
                return self.json_response(200,probe(self.store,data.get('role','parse'),data.get('profile',{})))
            if path.startswith('/api/review-translation/'):
                from .review import suggest_translation
                return self.json_response(200,suggest_translation(self.store,path.rsplit('/',1)[-1],data))
            if path.startswith('/api/reparse/'):
                from .reparse import reparse_page
                cid=path.rsplit('/',1)[-1];site=self.store.course_path(cid);page_id=data.get('pageId')
                course=json.loads((site/'course.json').read_text('utf-8'))
                if not any(p['id']==page_id for f in course['files'] for p in f['pages']):raise ValueError('页面不存在。')
                with self.server.job_lock:
                    if any(j['status']=='running' for j in self.server.jobs.values()):return self.json_response(409,{'error':'请等待当前编译结束后重识别。'})
                    job={'id':cid,'title':course.get('title','课程')+' · 单页重识别','kind':'page-reparse','pageId':page_id,'status':'running','cancel':threading.Event(),'events':[],'startedAt':datetime.now(timezone.utc).isoformat()};self.server.jobs[cid]=job
                    atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                def repair_run():
                    def progress(stage,current,total,message):
                        job['progress']={'stage':stage,'current':current,'total':total,'message':message}
                    try:
                        result=reparse_page(self.store,cid,page_id,progress,job['cancel']);job.update(result,status='review' if result['reviewRequired'] else 'complete')
                    except Exception as e:job.update(status='error',error=str(e) if isinstance(e,(ValueError,RuntimeError)) else type(e).__name__)
                    finally:atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                threading.Thread(target=repair_run,daemon=True).start();return self.json_response(202,{'id':cid})
            if path.startswith('/api/review/'):
                with self.server.job_lock:
                    if any(j['status']=='running' for j in self.server.jobs.values()):raise ValueError('请等待编译结束后修正。')
                    from .review import review_course
                    return self.json_response(200,review_course(self.store,path.rsplit('/',1)[-1],data))
            if path=='/api/settings':return self.json_response(200,self.store.save_settings(data))
            if path=='/api/materials/plan':
                from .materials import plan_addition
                return self.json_response(200,plan_addition(self.store,data.get('courseId'),data.get('files')))
            if path=='/api/materials/add':
                from .materials import validate_addition,add_materials
                with self.server.job_lock:
                    if any(j['status']=='running' for j in self.server.jobs.values()):return self.json_response(409,{'error':'已有课程正在处理，请先完成或停止。'})
                    original,_=validate_addition(self.store,data);cid=original['id'];settings=self.store.settings();profiles=self.store.profiles()
                    job={'id':cid,'kind':'addition','status':'running','title':original['title']+' · 添加材料','events':[],'cancel':threading.Event(),'startedAt':datetime.now(timezone.utc).isoformat(),'processedPages':0,'additionRequest':data}
                    self.server.jobs[cid]=job;atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                def add_run():
                    def progress(stage,current,total,message):
                        with self.server.job_lock:
                            event={'stage':stage,'current':current,'total':total,'message':message};job['progress']=event;job['events']=(job['events']+[event])[-80:]
                            if stage=='page-complete':job['processedPages']=max(job['processedPages'],current)
                    try:
                        result=add_materials(self.store,data,settings,profiles,progress,job['cancel']);c=result['course']
                        job.update(status='complete' if result['committed'] else 'cancelled' if job['cancel'].is_set() else 'blocked' if c['status']=='blocked' else 'partial',quality=c['quality'],metrics=result.get('metrics',c.get('metrics',{})),readerUrl=f'/courses/{cid}/index.html',downloadUrl=f'/download/{cid}.zip',committed=result['committed'])
                        if not result['committed']:job['error']='新材料尚未完成，原课程保持不变；可继续处理已保存的进度。'
                    except Exception as e:job.update(status='error',error=str(e) if isinstance(e,(ValueError,RuntimeError)) else type(e).__name__)
                    finally:atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                threading.Thread(target=add_run,daemon=True).start();return self.json_response(202,{'id':cid})
            if path.startswith('/api/learning/'):
                self.store.save_learning(path.rsplit('/',1)[-1],data);return self.json_response(200,{'saved':True})
            if path=='/api/compile':
                selected=data.get('files',[]);lookup={f['id']:f for f in self.files()}
                if not isinstance(selected,list) or not selected or len(selected)>100 or any(i not in lookup for i in selected):raise ValueError('请选择有效讲义。')
                paths=[self.store.root/'input'/i/lookup[i]['name'] for i in dict.fromkeys(selected)]
                cid=course_id(paths);settings=self.store.settings();profiles=self.store.profiles()
                title=str(data.get('title','')).strip()[:160] or paths[0].stem
                with self.server.job_lock:
                    if any(j['status']=='running' for j in self.server.jobs.values()):return self.json_response(409,{'error':'已有课程正在处理，请先完成或停止。'})
                    job={'id':cid,'status':'running','title':title,'events':[],'cancel':threading.Event(),'startedAt':datetime.now(timezone.utc).isoformat(),'processedPages':0};self.server.jobs[cid]=job
                    atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                def run():
                    def progress(stage,current,total,message):
                        with self.server.job_lock:
                            event={'stage':stage,'current':current,'total':total,'message':message};job['progress']=event;job['events']=(job['events']+[event])[-80:]
                            if stage=='page-complete':job['processedPages']=max(job['processedPages'],current)
                    site=self.store.course_path(cid)
                    try:
                        retained=json.loads((site/'course.json').read_text('utf-8')) if (site/'course.json').exists() else None
                        course=compile_course(paths,site,profiles,self.store.root/'cache',workers=settings['workers'],parse_mode=settings['parseMode'],ai=not data.get('extractOnly'),explanations=False,cancel=job['cancel'],progress=progress,title=title,request_limit=settings.get('requestLimit',1000),retained_course=retained)
                        q=course['quality'];ready=q['readingTranslated']==q['readingUnits'] and q['visualValidated']==q['pages'] and q['transcriptionValidated']==q['pages'] and not q['errors']
                        job.update(status='cancelled' if job['cancel'].is_set() else 'blocked' if course['status']=='blocked' else 'review' if ready and q.get('reviewPages') else 'complete' if ready else 'partial',quality=q,metrics=course['metrics'],readerUrl=f'/courses/{cid}/index.html',downloadUrl=f'/download/{cid}.zip')
                        self.store.save_course({'id':cid,'title':title,'pages':q['pages'],'figures':q.get('figures',0),'updatedAt':course['compiledAt'],'status':job['status'],'quality':q,'fileIds':list(dict.fromkeys(selected)),'readerUrl':job['readerUrl'],'downloadUrl':job['downloadUrl'],'hasAddedMaterials':bool(course.get('materialHistory'))})
                    except Exception as e:job.update(status='error',error=str(e) if isinstance(e,(ValueError,RuntimeError)) else type(e).__name__)
                    finally:atomic_json(self.store.root/'jobs'/(cid+'.json'),self.public_job(job))
                threading.Thread(target=run,daemon=True).start();return self.json_response(202,{'id':cid})
            if path.startswith('/api/cancel/'):
                job=self.server.jobs.get(path.rsplit('/',1)[-1])
                if not job:raise ValueError('任务不存在。')
                job['cancel'].set();return self.json_response(200,{'cancelled':True})
            return self.json_response(404,{'error':'未知操作。'})
        except zipfile.BadZipFile:return self.json_response(400,{'error':'ZIP 文件无效或已损坏。'})
        except (ValueError,TypeError,KeyError) as e:return self.json_response(400,{'error':str(e)})
        except Exception:return self.json_response(500,{'error':'本地处理失败，请检查文件后重试。'})

def make_server(port=8765,root=None):
    from http.server import ThreadingHTTPServer
    server=ThreadingHTTPServer(('127.0.0.1',port),AppHandler);server.store=Store(root);server.jobs={};server.job_lock=threading.RLock()
    from .study_agent import StudyService
    server.assistant=StudyService(server.store)
    for p in (server.store.root/'jobs').glob('*.json'):
        try:
            job=json.loads(p.read_text('utf-8'));job['cancel']=threading.Event()
            if job['status']=='running':job['status']='interrupted'
            server.jobs[job['id']]=job
        except (ValueError,KeyError):pass
    return server
