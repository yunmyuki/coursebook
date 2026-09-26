"""Adaptive single-pass document parsing, local checks, and independent model stages."""
import copy
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from .extract import extract_files,course_order_key
from .figures import native_figures
from .model import ModelError,ModelAuthorizationError
from .parsers import DocumentParser,commit_layout,routing,make_model
from .pipeline import quality,build_sections,apply_translations,apply_terminology,request_units,DEFAULT_TERMS
from .storage import atomic_json
from . import prompts
from .export import export_site
from .structure import restore_heading_groups
from .translation_context import PROMPT as CONTEXT_PROMPT,validate_context,context_key,context_samples,translation_metadata

def course_id(paths):
    paths=sorted(map(Path,paths),key=course_order_key)
    return 'course-'+hashlib.sha256(('pipeline-v1'+''.join(hashlib.sha256(p.read_bytes()).hexdigest() for p in paths)).encode()).hexdigest()[:16]

def fingerprint(profile):
    return hashlib.sha256(json.dumps({k:v for k,v in profile.items() if k not in ('apiKey','hasApiKey','encryptedKey')},sort_keys=True).encode()).hexdigest()[:16]

def compile_course(paths,output,profiles,cache_root,workers=3,ai=True,explanations=False,parse_mode='adaptive',progress=lambda *a:None,cancel=None,title=None,request_limit=1000,translation_context=None,terminology=None,retained_course=None):
    started=time.monotonic();paths=sorted(map(Path,paths),key=course_order_key);cid=course_id(paths)
    output=Path(output);output.mkdir(parents=True,exist_ok=True);cache=Path(cache_root)/cid;cache.mkdir(parents=True,exist_ok=True)
    extraction=cache/'extraction-v3.json'
    if extraction.exists() and (output/'assets').exists() and (output/'sources').exists():files=json.loads(extraction.read_text('utf-8'))
    else:files=extract_files(paths,output,progress);atomic_json(extraction,files)
    all_pages=[p for f in files for p in f['pages']];total=len(all_pages)
    parse_key='v3-'+parse_mode+'-'+fingerprint(profiles['parse']);translation_key=fingerprint(profiles['translation'])
    parser=DocumentParser(profiles['parse'],Path(cache_root)/'model')
    translator=make_model(profiles['translation'],Path(cache_root)/'model')
    from .requests_control import RequestBudget
    budget=RequestBudget(request_limit,cancel)
    if hasattr(parser,'model'):parser.model.budget=budget
    translator.budget=budget
    course={'schemaVersion':2,'id':cid,'title':title or ('Behavioral Finance' if any('fudan' in p.name.lower() for p in paths) else paths[0].stem),'subtitle':'双语课程 · 本地学习空间','files':files,'explanations':[],'targetLanguage':'zh-CN','compiledAt':datetime.now(timezone.utc).isoformat(),'terminology':dict(DEFAULT_TERMS),'provenance':{'compiler':'coursebook 2.0','parsingStrategy':'adaptive-single-pass','profiles':{r:{k:v for k,v in p.items() if k in ('provider','model','engine')} for r,p in profiles.items()}}}
    if retained_course:
        translation_context=translation_context or retained_course.get('translationContext')
        terminology=terminology or retained_course.get('terminology')
    course['terminology']=dict(terminology or {})
    course['translationContext']=dict(translation_context or {'subject':'未确定','style':'准确、完整的学术翻译，保留原文语气与术语。','status':'pending'})
    contextfile=cache/('translation-context-'+translation_key+'.json');context_blocked=None
    if not translation_context and ai and translator.available and not (cancel and cancel.is_set()):
        try:
            if contextfile.exists():context_result=validate_context(json.loads(contextfile.read_text('utf-8')))
            else:
                progress('translation-context',0,total,'识别课程主题与翻译风格')
                context_result=translator.request(CONTEXT_PROMPT,{'courseTitle':course['title'],'samples':context_samples(files)},max_tokens=1600,validator=validate_context)
                validate_context(context_result);atomic_json(contextfile,context_result)
            course['translationContext']={k:context_result[k] for k in ('subject','style')};course['translationContext']['status']='generated'
            course['terminology']={**context_result.get('terminology',{}),**course['terminology']}
        except (ModelError,ValueError) as e:
            course['translationContext']['status']='fallback'
            course['translationContext']['warning']='主题识别未完成，使用忠实的通用学术翻译。'
            if isinstance(e,ModelAuthorizationError):context_blocked=str(e)
    termfile=cache/('terminology-'+translation_key+'.json')
    if termfile.exists():course['terminology']={**json.loads(termfile.read_text('utf-8')),**course['terminology']}
    lock=threading.Lock();halt=threading.Event();done=0;metrics={'nativePages':0,'visionPages':0,'resumedPages':0,'documentCalls':0,'secondPassCalls':0,'pageFailures':0}
    if context_blocked:halt.set();progress('blocked',0,total,context_blocked)
    legacy_translation_key=translation_key;translation_key+='-'+context_key(course['translationContext'])+'-'+hashlib.sha256(json.dumps(course['terminology'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
    def stopped():return halt.is_set() or bool(cancel and cancel.is_set())
    def process(page):
        nonlocal done
        saved=cache/(page['id']+'.json');exp=[];meta={}
        text_lines=page.get('textLines',[])
        if saved.exists():
            previous=json.loads(saved.read_text('utf-8'));page.clear();page.update(previous['page']);exp=previous.get('explanations',[]);meta=previous.get('stages',{})
        if text_lines:page['textLines']=text_lines
        restore_heading_groups(page)
        route,reason=routing(page,parse_mode)
        if stopped():
            # Retain cached explanations without counting an untouched page as processed.
            with lock:course['explanations'].extend(exp)
            return
        try:
            if stopped():return
            if ai:
                if meta.get('parse')!=parse_key or page.get('visualStatus')!='complete':
                    progress('document-parsing',page['number'],total,reason)
                    candidate=copy.deepcopy(page)
                    if route=='native':
                        native_figures(candidate,output);candidate.update(visualStatus='complete',transcriptionStatus='complete',validationMethod='native-text-plus-local-checks')
                        with lock:metrics['nativePages']+=1
                    else:
                        with lock:metrics['documentCalls']+=1
                        result=parser.parse(candidate,output);commit_layout(candidate,result,output)
                        with lock:metrics['visionPages']+=1
                    page.clear();page.update(candidate);page['parseRoute']={'route':route,'reason':reason};meta['parse']=parse_key
                    exp=[];meta.pop('explanation',None)
                    atomic_json(saved,{'page':page,'explanations':exp,'stages':meta})
                else:
                    with lock:metrics['resumedPages']+=1
                if stopped():return
                active=[u for u in page['units'] if not u.get('reviewOnly')]
                if meta.get('translation') not in (None,translation_key,legacy_translation_key):
                    for u in active:u.update(translatedText=None,translationStatus='pending')
                for u in active:
                    if u['translationStatus']=='complete':continue
                    if not u['sourceText'].strip() or u['type'] in ('formula','code') or re.fullmatch(r'[\d\s+−\-–.,()%*/=<>×:;\[\]{}±*]+',u['sourceText']):u.update(translatedText=u['sourceText'],translationStatus='complete',translationMethod='notation-preserved')
                pending=[u for u in active if u['translationStatus']!='complete']
                if pending and not translator.available:raise ModelAuthorizationError('请为翻译配置 API 密钥。')
                for i in range(0,len(pending),24):
                    if stopped():return
                    progress('translation',page['number'],total,'逐单元翻译')
                    batch=pending[i:i+24];apply_translations(batch,request_units(translator,prompts.TRANSLATE,batch,translation_metadata(course)))
                    for u in batch:u['translationMethod']=translator.model
                    meta['translation']=translation_key;atomic_json(saved,{'page':page,'explanations':exp,'stages':meta})
                apply_terminology(page,course['terminology']);meta['translation']=translation_key
                # Explanations are now requested by the reader's study agent, never precomputed.
                page['warnings']=[w for w in page['warnings'] if not w.startswith('处理未完成：')]
            else:native_figures(page,output)
        except ModelAuthorizationError as e:
            halt.set();page['warnings'].append('处理未完成：'+str(e));progress('blocked',page['number'],total,str(e))
        except Exception as e:
            message=str(e) if isinstance(e,(ModelError,ValueError)) else type(e).__name__
            page['warnings'].append('处理未完成：'+message)
            with lock:metrics['pageFailures']+=1
            progress('page-error',page['number'],total,message)
        finally:
            atomic_json(saved,{'page':page,'explanations':exp,'stages':meta})
            with lock:
                done+=1;course['explanations'].extend(exp);progress('page-complete',done,total,page['title'])
    with ThreadPoolExecutor(max_workers=max(1,min(workers,8))) as pool:
        for future in as_completed([pool.submit(process,p) for p in all_pages]):future.result()
    build_sections(files);course['explanations'].sort(key=lambda e:(e['source']['file'],e['source']['page'],e['id']))
    if retained_course and retained_course.get('materialHistory'):
        compiled_ids={f['id'] for f in files}
        untouched=copy.deepcopy([f for f in retained_course['files'] if f['id'] not in compiled_ids])
        retained_unit_ids={u['id'] for f in untouched for p in f['pages'] for u in p['units']}
        course['files'].extend(untouched)
        course['explanations'].extend(copy.deepcopy([e for e in retained_course['explanations'] if set(e['relatedContentIds'])<=retained_unit_ids]))
        valid_chapters=[ch['id'] for f in course['files'] for ch in f['chapters']]
        course['readingOrder']=[c for c in retained_course.get('readingOrder',[]) if c in valid_chapters]
        course['readingOrder'].extend(c for c in valid_chapters if c not in course['readingOrder'])
        course['materialHistory']=copy.deepcopy(retained_course['materialHistory'])
    from .review import apply_overrides
    apply_overrides(course,Path(cache_root).parent)
    for page in all_pages:restore_heading_groups(page)
    course['quality']=quality(course);course['quality']['figures']=sum(len(p.get('figures',[])) for p in all_pages)
    course['metrics']={**metrics,**budget.snapshot(),'elapsedSeconds':round(time.monotonic()-started,2)}
    course['status']='blocked' if halt.is_set() else 'cancelled' if stopped() else 'finished'
    for name,value in [('course.json',course),('quality-report.json',course['quality']),('terminology.json',course['terminology'])]:atomic_json(output/name,value)
    export_site(course,output);return course
