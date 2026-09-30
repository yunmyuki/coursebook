"""Transactional single-page repair using the current pipeline and existing user settings."""
import copy
import json
import shutil
from datetime import datetime,timezone
from pathlib import Path
from .storage import atomic_json
from .parsers import DocumentParser,commit_layout,make_model
from .requests_control import RequestBudget
from .pipeline import request_units,apply_translations,quality
from .translation_context import translation_metadata
from .review import apply_overrides
from .export import export_site
from . import prompts


def refresh_evidence(page,site):
    from .extract import extract_pdf
    source=Path(site)/'sources'/(page['source']['fileId']+'.pdf')
    if source.is_file() and source.resolve().is_relative_to(Path(site).resolve()):
        fresh=extract_pdf(source,Path(site),page['source']['fileId'],page_numbers={page['number']})[0]
        for key in ('textLines','layoutAnalysis','width','height','needsOCR','imageRegions','vectorCount'):
            page[key]=fresh[key]
    return page


def reparse_page(store,cid,page_id,progress=lambda *a:None,cancel=None):
    site=store.course_path(cid);path=site/'course.json';before=path.read_bytes();course=json.loads(before)
    page=next((p for f in course['files'] for p in f['pages'] if p['id']==page_id),None)
    if page is None:raise ValueError('页面不存在。')
    profiles=store.profiles();hybrid=profiles['parse'].get('engine')=='local-layout-ocr'
    budget=RequestBudget(min(store.settings().get('requestLimit',1000),profiles['parse'].get('maxOcrRegions',32)*2+6) if hybrid else 6,cancel)
    progress('document-parsing',0,1,'按新版流程重新识别本页')
    refresh_evidence(page,site)
    parser=DocumentParser(profiles['parse'],store.root/'cache/model');parser.model.budget=budget
    parser.layout_root=store.root
    candidate=copy.deepcopy(page)
    for key in ('reviewRequired','reviewReasons','reviewedAt','reviewedBy'):candidate.pop(key,None)
    result=parser.parse(candidate,site);commit_layout(candidate,result,site)
    translator=make_model(profiles['translation'],store.root/'cache/model');translator.budget=budget
    active=[u for u in candidate['units'] if not u.get('reviewOnly')]
    for u in active:
        if not u['sourceText'].strip() or u['type'] in ('formula','code'):
            u.update(translatedText=u['sourceText'],translationStatus='complete',translationMethod='notation-preserved')
    pending=[u for u in active if u['translationStatus']!='complete']
    for start in range(0,len(pending),24):
        progress('translation',0,1,'为新分块生成完整译文')
        batch=pending[start:start+24];apply_translations(batch,request_units(translator,prompts.TRANSLATE,batch,translation_metadata(course)))
        for u in batch:u['translationMethod']=translator.model
    if cancel and cancel.is_set():raise ValueError('已取消，原页保持不变。')
    candidate['warnings']=[w for w in candidate['warnings'] if not w.startswith('处理未完成：')]
    candidate['parseRoute']={'route':'local-layout-ocr' if hybrid else 'vision','reason':'用户选择按新版流程重新识别本页'}
    candidate['reparsedAt']=datetime.now(timezone.utc).isoformat()
    page.clear();page.update(candidate);apply_overrides(course,store.root)
    course['quality']=quality(course)
    if course['quality']['errors']:raise ValueError('关联校验未通过，原页保持不变。')
    if path.read_bytes()!=before:raise ValueError('课程已在其他窗口更新，未覆盖，请重试。')
    backup=store.root/'backups'/cid/('reparse-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
    for name in ('course.json','quality-report.json','course-data.js'):
        if (site/name).exists():shutil.copy2(site/name,backup/name)
    from .pipeline_v2 import fingerprint
    saved=store.root/'cache'/cid/(page_id+'.json')
    if saved.exists():
        shutil.copy2(saved,backup/saved.name);checkpoint=json.loads(saved.read_text('utf-8'))
        checkpoint['page']=page;checkpoint.setdefault('stages',{})['parse']='v5-'+store.settings().get('parseMode','adaptive')+'-'+fingerprint(profiles['parse'])
        atomic_json(saved,checkpoint)
    atomic_json(path,course);atomic_json(site/'quality-report.json',course['quality']);export_site(course,site)
    item=next((c for c in store.courses() if c['id']==cid),None)
    if item:item['quality']=course['quality'];store.save_course(item)
    progress('page-complete',1,1,'本页已更新，原文和旧锚点已保留')
    return {'pageId':page_id,'quality':course['quality'],'metrics':budget.snapshot(),'backup':str(backup),
            'reviewRequired':bool(page.get('reviewRequired') or any(u.get('uncertain') for u in active))}
