"""Explicit user corrections retain original text, content IDs and a local override log."""
import json
from datetime import datetime,timezone
from .pipeline import quality
from .storage import atomic_json
from .export import export_site

def apply_overrides(course,store_root):
    from .cleanup import apply_cleanup
    path=store_root/'reviews'/(course['id']+'.json')
    if not path.exists():
        apply_cleanup(course,store_root)
        return
    overrides=json.loads(path.read_text('utf-8'))
    for f in course['files']:
        for p in f['pages']:
            needs_relink=bool(p.get('layoutQuality',{}).get('issues'))
            for u in p['units']:
                if u['id'] in overrides.get('units',{}):u.update(overrides['units'][u['id']])
                if u.get('reviewOnly') and not u.get('cleanupHidden') and u['id'] in overrides.get('units',{}):
                    needs_relink=True;u['reviewOnly']=False;p.update(reviewRequired=True,reviewReasons=['解析分块已变化；已保留人工修正，请重新核对对应关系。'])
            if p['id'] in overrides.get('pages',{}) and not needs_relink:p.update(overrides['pages'][p['id']])
    for e in course['explanations']:
        if any(uid in overrides.get('units',{}) for uid in e['relatedContentIds']):e['needsReview']=True
    apply_cleanup(course,store_root)

def review_course(store,cid,data):
    site=store.course_path(cid);course=json.loads((site/'course.json').read_text('utf-8'));now=datetime.now(timezone.utc).isoformat()
    path=store.root/'reviews'/(cid+'.json');overrides=store.read('reviews/'+cid+'.json',{'units':{},'pages':{}})
    patch_result={}
    if data.get('contentId'):
        target=next((u for f in course['files'] for p in f['pages'] for u in p['units'] if u['id']==data['contentId']),None)
        if not target or target.get('reviewOnly'):raise ValueError('请修正正文中的有效内容单元。')
        if 'expectedSourceText' in data and (target['sourceText']!=data['expectedSourceText'] or target.get('translatedText')!=data.get('expectedTranslatedText')):raise ValueError('此内容已在其他窗口更新，请重新打开复核后再保存。')
        if 'expectedLatex' in data and target.get('latex')!=data['expectedLatex']:raise ValueError('此公式已在其他窗口更新，请重新打开复核后再保存。')
        source=data.get('sourceText');translated=data.get('translatedText')
        empty_cell=target['type']=='table-cell' and source=='' and translated==''
        if not isinstance(source,str) or (not source.strip() and not empty_cell) or len(source)>30000 or not isinstance(translated,str) or len(translated)>30000:raise ValueError('请填写原文；原文和译文各不超过 30000 字符。')
        source_changed=source!=target['sourceText'] or (target['type']=='formula' and data.get('latex','')!=(target.get('latex') or ''))
        stale=source_changed and translated==(target.get('translatedText') or '') and data.get('confirmTranslation') is not True
        complete=(bool(translated.strip()) or empty_cell) and not stale
        change={'sourceText':source,'translatedText':translated if complete else None,'translationStatus':'complete' if complete else 'pending','translationMethod':'user-reviewed' if complete else 'user-edit-pending','uncertain':False,'corrections':target.get('corrections',[])+[{'kind':'user-review','before':target['sourceText'],'after':source,'previousTranslation':target.get('translatedText'),'previousLatex':target.get('latex'),'reviewedAt':now}]}
        overrides['units'][target['id']]=change;target.update(change)
        if target['type']=='formula':
            latex=data.get('latex','')
            if not isinstance(latex,str) or len(latex)>30000:raise ValueError('公式格式无效。')
            change['latex']=latex or None;target['latex']=latex or None
        for e in course['explanations']:
            if target['id'] in e['relatedContentIds']:e['needsReview']=True
        patch_result={'unit':target}
    elif data.get('pageId'):
        page=next((p for f in course['files'] for p in f['pages'] if p['id']==data['pageId']),None)
        if not page:raise ValueError('页面不存在。')
        update={'reviewRequired':False,'reviewReasons':[],'reviewedAt':now,'reviewedBy':'user'};overrides['pages'][page['id']]=update;page.update(update)
        patch_result={'pageId':page['id'],'pageChanges':update}
    else:raise ValueError('请选择需要复核的内容。')
    from .structure import restore_heading_groups
    for file in course['files']:
        for page in file['pages']:
            if data.get('contentId') and any(u['id']==data['contentId'] for u in page['units']):
                restore_heading_groups(page)
                patch_result.update(pageId=page['id'],pageChanges={'title':page['title'],'headingGroups':page.get('headingGroups',[])})
    course['quality']=quality(course)
    if course['quality']['errors']:raise ValueError('修正后的关联检查失败。')
    atomic_json(path,overrides);persist_course(store,cid,course)
    return {'saved':True,**patch_result,'quality':course['quality'],'explanationReviewIds':[e['id'] for e in course['explanations'] if e.get('needsReview')]}

def persist_course(store,cid,course):
    site=store.course_path(cid)
    course['quality']=quality(course)
    if course['quality']['errors']:raise ValueError('关联检查失败，未写入正文。')
    atomic_json(site/'course.json',course);atomic_json(site/'quality-report.json',course['quality']);export_site(course,site)
    item=next((c for c in store.courses() if c['id']==cid),None)
    if item:
        q=course['quality'];ready=q['readingTranslated']==q['readingUnits'] and q['transcriptionValidated']==q['pages'] and q['visualValidated']==q['pages'];item.update(quality=q,status='review' if ready and q.get('reviewPages') else 'complete' if ready else 'partial');store.save_course(item)


def suggest_translation(store,cid,data):
    """Generate a draft only. The user must explicitly confirm the final revision."""
    from .parsers import make_model
    from .pipeline import request_units,apply_translations
    from .requests_control import RequestBudget
    from . import prompts
    import copy,re
    course=json.loads((store.course_path(cid)/'course.json').read_text('utf-8'))
    target=next((u for f in course['files'] for p in f['pages'] for u in p['units'] if u['id']==data.get('contentId') and not u.get('reviewOnly')),None)
    text=data.get('sourceText')
    if not target or not isinstance(text,str) or len(text)>30000:raise ValueError('请选择有效原文。')
    if target['type'] in ('formula','code') or not text.strip() or re.fullmatch(r'[\d\s+−\-–.,()%*/=<>×:;\[\]{}±*]+',text):return {'translatedText':text,'draft':True,'requests':0}
    unit=copy.deepcopy(target);unit.update(sourceText=text,translatedText=None,translationStatus='pending')
    model=make_model(store.profiles()['translation'],store.root/'cache/review');model.budget=RequestBudget(2)
    from .translation_context import translation_metadata
    apply_translations([unit],request_units(model,prompts.TRANSLATE,[unit],translation_metadata(course)))
    return {'translatedText':unit['translatedText'],'draft':True,'requests':model.budget.calls}
