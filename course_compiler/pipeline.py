import copy
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from .extract import extract_files, normalize, unit
from .model import Model, ModelError, ModelAuthorizationError
from . import prompts


def write_json(path,data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def compact(units):
    return [{k:u.get(k) for k in ('id','type','sourceText','position','level','tableId','row','col','latex')} for u in units]


def request_units(model,prompt,units,metadata=None,**kwargs):
    """Use request-local short IDs on the wire; persisted content anchors never change."""
    aliases={u['id']:'u'+str(i+1) for i,u in enumerate(units)}
    originals={v:k for k,v in aliases.items()}
    wire=compact(units)
    for u in wire:u['id']=aliases[u['id']]
    payload={**(metadata or {}),'units':wire}
    for key in ('protectedContentIds','modelGeneratedContentIds'):
        if key in payload:payload[key]=[aliases[uid] for uid in payload[key]]
    from . import prompts
    if prompt==prompts.TRANSLATE and 'validator' not in kwargs:
        def validate_translation(result):apply_translations(copy.deepcopy(wire),result)
        kwargs['validator']=validate_translation
    result=copy.deepcopy(model.request(prompt,payload,**kwargs))
    if result.pop('verifiedAll',False) is True:
        result['verifiedContentIds']=list(originals)
    for key in ('corrections','translations'):
        for item in result.get(key,[]) or []:
            if isinstance(item,dict) and 'id' in item:item['id']=originals.get(item['id'],item['id'])
    for key in ('verifiedContentIds','uncertainContentIds','rejectedContentIds'):
        if isinstance(result.get(key),list):result[key]=[originals.get(uid,uid) for uid in result[key]]
    for e in result.get('explanations',[]) or []:
        if isinstance(e.get('relatedContentIds'),list):e['relatedContentIds']=[originals.get(uid,uid) for uid in e['relatedContentIds']]
    return result


def merge_visual(page,result,stage):
    corrections=result.get('corrections',[]);raw_additions=result.get('additions',[])
    if not any(k in result for k in ('corrections','additions','tables','verifiedAll','verifiedContentIds')) or not isinstance(corrections,list) or not isinstance(raw_additions,list):
        raise ModelError('视觉结果不符合 schema，未修改原文。')
    additions=list(raw_additions)
    for table in result.get('tables',[]) or []:
        rows=table.get('rows');box=table.get('position')
        if not isinstance(rows,list) or not rows or not all(isinstance(row,list) for row in rows):raise ModelError('视觉表格行结构无效。')
        if not (isinstance(box,list) and len(box)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in box)):raise ModelError('视觉表格位置无效。')
        width=max(map(len,rows))
        if not width or len(rows)*width>5000:raise ModelError('视觉表格大小无效。')
        for ri,row in enumerate(rows):
            for ci,cell in enumerate(row):
                value=cell.get('text','') if isinstance(cell,dict) else cell
                if not isinstance(value,str):value=str(value) if isinstance(value,(float,int)) else ''
                if not value.strip():continue
                pos=[box[0]+(box[2]-box[0])*ci/width,box[1]+(box[3]-box[1])*ri/len(rows),box[0]+(box[2]-box[0])*(ci+1)/width,box[1]+(box[3]-box[1])*(ri+1)/len(rows)]
                additions.append({'type':'table-cell','sourceText':value,'tableId':table.get('tableId'),'row':ri,'col':ci,'position':pos,'positionEstimated':True,**({k:cell[k] for k in ('rowSpan','colSpan','uncertain') if k in cell} if isinstance(cell,dict) else {})})
    by_id={u['id']:u for u in page['units']}
    rejected=set()
    for correction in corrections:
        if correction.get('id') not in by_id:
            raise ModelError('视觉校验返回了未知 contentId。')
        u=by_id[correction['id']]
        text=correction.get('sourceText',u['sourceText'])
        if not isinstance(text,str) or not text.strip():
            continue
        before=u['sourceText']
        structure={k:correction[k] for k in ('type','level','position','row','col','rowSpan','colSpan') if k in correction and correction[k]!=u.get(k)}
        if u.get('origin')=='conversation-visual-review' and (text!=before or structure):
            u.setdefault('suggestedCorrections',[]).append(correction)
            rejected.add(u['id'])
            continue
        ratio=SequenceMatcher(None,re.sub(r'\W','',before.lower()),re.sub(r'\W','',text.lower())).ratio()
        if ratio < .58 and len(before)>30:
            u['uncertain']=True
            u.setdefault('suggestedCorrections',[]).append(correction)
            rejected.add(u['id'])
            page['warnings'].append(f"{u['id']}: 校正差异过大，保留提取原文供复核。")
            continue
        if text != before:
            u['corrections'].append({'kind':stage,'before':before,'after':text,'reason':correction.get('reason','')})
            u['sourceText']=text
            # A corrected source must never retain a stale translation.
            u['translatedText']=None
            u['translationStatus']='pending'
        if correction.get('latex'):
            u['latex']=correction['latex']
            if u['type']!='table-cell':u['type']='formula'
        validated={}
        for key,value in structure.items():
            if key=='type' and value in ('title','paragraph','bullet','caption','footnote','speaker-note','code','formula'):validated[key]=value
            elif key in ('level','row','col','rowSpan','colSpan') and isinstance(value,int) and 0<=value<5000:validated[key]=value
            elif key=='position' and isinstance(value,list) and len(value)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in value):validated[key]=value
        if validated:
            u['corrections'].append({'kind':stage+'-structure','before':{k:u.get(k) for k in validated},'after':validated,'reason':correction.get('reason','')})
            u.update(validated)
    active=[u for u in page['units'] if not u.get('reviewOnly') and u.get('origin')!='local-ocr']
    seen={normalize(u['sourceText']) for u in active}
    allowed={'title','paragraph','bullet','formula','caption','footnote','code','table-cell','speaker-note'}
    for i,a in enumerate(additions):
        text=a.get('sourceText')
        if not isinstance(text,str) or not text.strip():
            continue
        # Skip duplicate non-cell additions only at overlapping positions. Repeated table values are meaningful.
        box=a.get('position')
        if not (isinstance(box,list) and len(box)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in box)):
            box=None
        if a.get('type')!='table-cell' and normalize(text) in seen and any(normalize(u['sourceText'])==normalize(text) and u.get('position') and box and abs(u['position'][1]-box[1])<.035 for u in active):
            continue
        tid=str(a.get('tableId') or '')
        if tid and not tid.startswith(page['id']+'-'):tid=page['id']+'-'+tid
        if a.get('type')=='table-cell' and any(u.get('tableId')==tid and u.get('row')==a.get('row') and u.get('col')==a.get('col') and normalize(u['sourceText'])==normalize(text) for u in active):continue
        uid=hashlib.sha256((stage+str(i)+text+str(box)).encode()).hexdigest()[:10]
        u=unit(page['id'],len(page['units'])+1,text,a.get('type') if a.get('type') in allowed else 'paragraph',page['source'],box,
               origin='visual-transcription',uncertain=bool(a.get('uncertain',False)),level=max(0,min(6,int(a.get('level') or 0))))
        u['id']=f"content-{page['id']}-v{uid}"
        for key in ('latex','tableId','row','col','rowSpan','colSpan','positionEstimated'):
            if a.get(key) is not None:
                u[key]=a[key]
        if u['type']=='table-cell' and not (isinstance(u.get('row'),int) and isinstance(u.get('col'),int) and u.get('tableId')):
            u['type']='paragraph';u['uncertain']=True
        if u.get('tableId'):
            u['tableId']=tid
        page['units'].append(u)
        active.append(u)
        seen.add(normalize(text))
    verified=by_id.keys() if result.get('verifiedAll') is True else result.get('verifiedContentIds',[]) or []
    for uid in verified:
        if uid in by_id and uid not in rejected and by_id[uid].get('origin')!='conversation-visual-review':
            by_id[uid]['uncertain']=False
    for uid in result.get('uncertainContentIds',[]) or []:
        if uid in by_id:by_id[uid]['uncertain']=True
    for uid in result.get('rejectedContentIds',[]) or []:
        if uid in by_id and by_id[uid].get('origin')=='visual-transcription':
            by_id[uid].update(reviewOnly=True,rejectedArtifact=True,uncertain=True,artifactReason='独立视觉核对认为该自动识别项未出现在原页；原始结果保留供复查。')
    page['units'].sort(key=lambda u: ((u.get('position') or [0,2,0,2])[1],(u.get('position') or [0,2,0,2])[0]))
    page['warnings'].extend(str(w) for w in result.get('warnings',[]) if isinstance(w,str))
    if result.get('title'):
        page['title']=str(result['title'])


def apply_translations(units,result):
    values=result.get('translations')
    if not isinstance(values,list):
        raise ModelError('翻译结果缺少 translations。')
    expected={u['id'] for u in units}
    received=[v.get('id') for v in values]
    if len(received)!=len(set(received)) or set(received)!=expected:
        raise ModelError('译文与原文 ID 不一一对应，整批未提交。')
    by_id={v['id']:v.get('translatedText') for v in values}
    for u in units:
        if not isinstance(by_id[u['id']],str) or not by_id[u['id']].strip():
            raise ModelError('译文为空，整批未提交。')
    for u in units:
        u['translatedText']=u['sourceText'] if u['type'] in ('formula','code') else by_id[u['id']]
        u['translationStatus']='complete'
        if u['type'] not in ('formula','code') and len(u['sourceText'])>160 and len(u['translatedText'])<len(u['sourceText'])*.12:
            u['translationStatus']='review'
            u['uncertain']=True


def apply_terminology(page,terms):
    """Normalize exact terminology labels without rewriting paragraphs or source text."""
    glossary={normalize(k).casefold():v for k,v in terms.items() if isinstance(k,str) and isinstance(v,str)}
    changed=0
    for u in page['units']:
        if u.get('reviewOnly') or u['type'] in ('formula','code') or u.get('translationStatus')!='complete':continue
        source=re.sub(r'^[•●▪◦]\s*','',u['sourceText']).strip()
        term=source.rstrip(':：').casefold();expected=glossary.get(term)
        translated=u.get('translatedText') or ''
        # Preserve bilingual proper-name forms if the canonical Chinese term is already present.
        if not expected or expected in translated:continue
        after=expected+('：' if source.endswith((':','：')) else '')
        if translated.startswith('•'):after='• '+after
        u.setdefault('translationCorrections',[]).append({'kind':'terminology-consistency','term':source,'before':translated,'after':after})
        u['translatedText']=after;changed+=1
    return changed


DEFAULT_TERMS={'Behavioral finance':'行为金融学','CAPM':'资本资产定价模型（CAPM）','beta':'贝塔系数',
'risk premium':'风险溢价','book-to-market':'账面市值比','momentum':'动量','overconfidence':'过度自信',
'disposition effect':'处置效应','loss aversion':'损失厌恶','confirmation bias':'确认偏误','self-attribution bias':'自我归因偏误',
'accruals':'应计项目','idiosyncratic volatility':'特质波动率','abnormal return':'异常收益','value stocks':'价值股',
'glamour stocks':'魅力股','post-earnings-announcement drift':'盈余公告后漂移','risk-free rate':'无风险利率'}


def build_sections(files):
    for f in files:
        chapters=[]
        current=None
        for page in f['pages']:
            reading=[u for u in page['units'] if not u.get('reviewOnly')]
            candidates=[page['title']]+[u['sourceText'] for u in reading[:3]]
            heading=next((s for s in candidates if re.match(r'^(Part|Chapter|Lecture|Week)\s*\d+\s*[:.：-]',s,re.I)),None)
            # Cover/table of contents is not a chapter boundary.
            if heading and len(reading)<8:
                if page['visualStatus']!='complete':
                    heading=' '.join(u['sourceText'] for u in reading)
                current={'id':page['id']+'-chapter','title':heading,'pageIds':[]}
                chapters.append(current)
            if current is None:
                current={'id':f['id']+'-frontmatter','title':'Course overview · 课程导读','pageIds':[]}
                chapters.append(current)
            current['pageIds'].append(page['id'])
            page['chapterId']=current['id']
        f['chapters']=chapters


def quality(course):
    pages=[p for f in course['files'] for p in f['pages']]
    units=[u for p in pages for u in p['units']]
    ids=[u['id'] for u in units]
    errors=[]
    chapters=[c['id'] for f in course['files'] for c in f.get('chapters',[])]
    if course.get('readingOrder') and (len(course['readingOrder'])!=len(chapters) or set(course['readingOrder'])!=set(chapters)):errors.append('Invalid course reading order')
    if len(ids)!=len(set(ids)):
        errors.append('Duplicate content IDs')
    known=set(ids)
    figure_ids=set()
    for p in pages:
        for figure in p.get('figures',[]):
            if figure.get('id') in known or figure.get('id') in figure_ids:errors.append('Duplicate figure anchor: '+str(figure.get('id')))
            figure_ids.add(figure.get('id'))
            if figure.get('source')!=p['source']:errors.append('Invalid figure source: '+str(figure.get('id')))
            if not set(figure.get('relatedContentIds',[]))<=known:errors.append('Invalid figure content links: '+str(figure.get('id')))
    table_pages={}
    for p in pages:
        current={u['id'] for u in p['units']}
        active_ids={u['id'] for u in p['units'] if not u.get('reviewOnly')}
        page_figures={f['id'] for f in p.get('figures',[])}
        if any(not set(u.get('figureIds',[]))<=page_figures for u in p['units'] if not u.get('reviewOnly')):errors.append('Invalid figure origin links: '+p['id'])
        grouped=set()
        for group in p.get('headingGroups',[]):
            refs=group.get('contentIds',[])
            if len(refs)<2 or len(refs)!=len(set(refs)) or not set(refs)<=active_ids or grouped.intersection(refs):errors.append('Invalid heading group: '+str(group.get('id')))
            grouped.update(refs)
        occupied={}
        if not {u['id'] for u in p.get('rawUnits',[])}<=current:
            errors.append(f"Missing original units: {p['id']}")
        if any(u['source']!=p['source'] for u in p['units']):
            errors.append(f"Invalid source reference: {p['id']}")
        for u in p['units']:
            if u.get('supersededBy') and u['supersededBy'] not in current:
                errors.append('Invalid replacement anchor: '+u['id'])
            if u.get('translationStatus')=='complete' and not isinstance(u.get('translatedText'),str):
                errors.append('Missing translation: '+u['id'])
            tid=u.get('tableId')
            if tid:
                if tid in table_pages and table_pages[tid]!=p['id']:errors.append('Table anchor reused across pages: '+tid)
                table_pages[tid]=p['id']
                if not u.get('reviewOnly'):
                    cell=(tid,u.get('row'),u.get('col'))
                    if cell in occupied:errors.append('Overlapping table cell: '+u['id'])
                    occupied[cell]=u['id']
    for e in course['explanations']:
        if not e['relatedContentIds'] or not set(e['relatedContentIds'])<=known:
            errors.append('Invalid explanation anchors: '+e['id'])
    stats={'pages':len(pages),'units':len(units),'translated':sum(u.get('translationStatus')=='complete' for u in units),
           'visualValidated':sum(p['visualStatus']=='complete' for p in pages),'transcriptionValidated':sum(p['transcriptionStatus']=='complete' for p in pages),
           'uncertain':sum(u['uncertain'] for u in units),'explanations':len(course['explanations']),
           'formulaCount':sum(u['type']=='formula' for u in units),'tableCells':sum(u['type']=='table-cell' for u in units),
           'warnings':sum(len(p['warnings']) for p in pages),'errors':errors,'figures':len(figure_ids)}
    active=[u for u in units if not u.get('reviewOnly')]
    stats.update(readingUnits=len(active),readingTranslated=sum(u.get('translationStatus')=='complete' for u in active),
                 ocrCandidates=sum(bool(u.get('reviewOnly')) for u in units),
                 readingUncertain=sum(bool(u.get('uncertain')) for u in active))
    stats['unresolvedCandidates']=sum(bool(u.get('reviewOnly')) and not u.get('supersededBy') and not u.get('rejectedArtifact') for u in units)
    stats['complete']=not errors and stats['readingTranslated']==len(active) and not stats['readingUncertain'] and not stats['unresolvedCandidates'] and stats['visualValidated']==len(pages) and stats['transcriptionValidated']==len(pages)
    stats['reviewPages']=sum(bool(p.get('reviewRequired')) for p in pages)
    if stats['reviewPages']:stats['complete']=False
    return stats


def compile_course(paths,output,model=None,workers=4,ai=True,audit=True,explanations=True,progress=lambda *a:None,cancel=None,ocr_model=None,page_filter=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    from .extract import course_order_key
    paths=sorted(paths,key=course_order_key)
    digest=hashlib.sha256(('pipeline-v1'+''.join(hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths)).encode()).hexdigest()[:16]
    cache=Path('.course-cache')/digest;cache.mkdir(parents=True,exist_ok=True)
    extraction=cache/'extraction.json'
    if extraction.exists() and (output/'assets').exists() and (output/'sources').exists():
        files=json.loads(extraction.read_text('utf-8'))
    else:
        files=extract_files(paths,output,progress)
        write_json(extraction,files)
    model=model or Model()
    if ocr_model is None and getattr(model,'provider',None)=='siliconflow':
        from .config import local_settings
        name=local_settings().get('COURSE_OCR_MODEL','PaddlePaddle/PaddleOCR-VL-1.5')
        if name.lower()!='none':ocr_model=Model(provider='siliconflow',base_url=model.base_url,api_key=model.api_key,model=name)
    terms=dict(DEFAULT_TERMS)
    if (cache/'terminology.json').exists():
        terms.update(json.loads((cache/'terminology.json').read_text('utf-8')))
    course={'schemaVersion':1,'id':'course-'+digest,'title':'Behavioral Finance' if any('fudan' in f['name'].lower() for f in files) else Path(paths[0]).stem,
            'subtitle':'行为金融学 · Fall semester 2026' if any('fudan' in f['name'].lower() for f in files) else '双语课程讲义',
            'compiledAt':datetime.now(timezone.utc).isoformat(),'targetLanguage':'zh-CN','files':files,'explanations':[],
            'terminology':terms,'provenance':{'compiler':'coursebook 1.0','model':model.model if ai else None,'aiEnabled':ai,'visualAuditEnabled':audit}}
    pages=[p for f in files for p in f['pages']]
    # Build a deterministic course glossary before page translations, from all headings in a bounded sample.
    if ai and model.available and not (cancel and cancel.is_set()) and not (cache/'terminology.json').exists():
        try:
            result=model.request(prompts.GLOSSARY,{'terminology':terms,'headings':[p['title'] for p in pages][:400]},max_tokens=5000)
            terms.update({k:v for k,v in result.get('terminology',{}).items() if isinstance(k,str) and isinstance(v,str)})
            write_json(cache/'terminology.json',terms)
        except ModelError:
            pass
    lock=threading.Lock();done=0;halt=threading.Event()
    def stopped():
        return halt.is_set() or bool(cancel and cancel.is_set())
    def process(page):
        nonlocal done
        saved=cache/(page['id']+'.json')
        if saved.exists():
            result=json.loads(saved.read_text('utf-8'))
            page.clear();page.update(result['page'])
            exp=result.get('explanations',[])
        else:
            exp=[]
        try:
            if stopped() or page_filter is not None and page['number'] not in page_filter:
                return
            if ai and model.available:
                if ocr_model and page['visualStatus']!='complete' and (page.get('needsOCR') or page.get('imageCount')) and not page.get('ocrDraft'):
                    if stopped():return
                    progress('ocr',page['number'],len(pages),page['source']['file'])
                    page['ocrDraft']=ocr_model.request('','OCR:',image=output/page['image'],max_tokens=12000,json_output=False)
                    page['ocrModel']=ocr_model.model
                    write_json(saved,{'page':page,'explanations':exp})
                for stage,prompt,key in [('visual-validation',prompts.VISUAL,'visualStatus'),('transcription-audit',prompts.VISUAL+'\nINDEPENDENT SECOND PASS: verify every bullet, table cell, formula, note and label against the image. Only return additional omissions or corrections.', 'transcriptionStatus')]:
                    if stage=='transcription-audit' and not audit:
                        continue
                    if page[key]!='complete':
                        if stopped():return
                        progress(stage,page['number'],len(pages),page['source']['file'])
                        active=[u for u in page['units'] if not u.get('reviewOnly') and u.get('origin')!='local-ocr']
                        result=request_units(model,prompt,active,{'page':page['source'],'ocrDraft':page.get('ocrDraft',''),'protectedContentIds':[u['id'] for u in active if u.get('origin')=='conversation-visual-review'],'modelGeneratedContentIds':[u['id'] for u in active if u.get('origin')=='visual-transcription']},image=output/page['image'],max_tokens=18000)
                        if not active and not result.get('additions') and not result.get('tables'):raise ModelError('扫描页没有返回可用正文，未标记完成。')
                        merge_visual(page,result,stage)
                        replacements=[u for u in page['units'] if not u.get('reviewOnly') and u.get('origin')!='local-ocr']
                        if replacements:
                            for u in page['units']:
                                if u.get('origin')=='local-ocr':
                                    u['reviewOnly']=True
                                    same=next((v for v in replacements if normalize(v['sourceText'])==normalize(u['sourceText'])),None)
                                    pos=u.get('position') or [0,0,0,0]
                                    nearest=same or min(replacements,key=lambda v:abs((v.get('position') or [0,0])[1]-pos[1])+abs((v.get('position') or [0,0])[0]-pos[0])*.2)
                                    u['supersededBy']=nearest['id']
                        page[key]='complete'
                        page['validationMethod']='model-visual-audit'
                        write_json(saved,{'page':page,'explanations':exp})
                page['warnings']=[w for w in page['warnings'] if not any(x in w for x in ('模型服务 HTTP','处理失败：','本页图片文字已由本机英文 OCR','未配置模型：','模型请求失败：','模型额度不足','视觉结果不符合 schema','当前仅恢复已缓存','模型输出被截断','模型校正说明异常冗长'))]
                pending=[u for u in page['units'] if u['translationStatus']!='complete' and not u.get('reviewOnly')]
                for u in pending:
                    if u['type'] in ('formula','code') or re.fullmatch(r'[\d\s+−\-–.,()%*/=<>×:;\[\]{}±]+',u['sourceText']):
                        u.update(translatedText=u['sourceText'],translationStatus='complete',translationMethod='notation-preserved')
                pending=[u for u in pending if u['translationStatus']!='complete']
                for start in range(0,len(pending),24):
                    if stopped():return
                    batch=pending[start:start+24]
                    progress('translation',page['number'],len(pages),page['source']['file'])
                    result=request_units(model,prompts.TRANSLATE,batch,{'terminology':terms})
                    apply_translations(batch,result)
                    for u in batch:u['translationMethod']=model.model
                    write_json(saved,{'page':page,'explanations':exp})
                if apply_terminology(page,terms):
                    progress('terminology',page['number'],len(pages),page['source']['file'])
                    write_json(saved,{'page':page,'explanations':exp})
                if exp:page['explanationsGenerated']=True
                if explanations and not page.get('explanationsGenerated'):
                    if stopped():return
                    selected=[u for u in page['units'] if not u.get('reviewOnly') and u['type'] in ('paragraph','bullet','formula') and len(u['sourceText'])>35]
                    if selected:
                        progress('explanations',page['number'],len(pages),page['source']['file'])
                        result=request_units(model,prompts.EXPLANATION,selected,{'source':page['source']},max_tokens=3200)
                        known={u['id'] for u in page['units']}
                        for i,e in enumerate(result.get('explanations',[])[:2]):
                            refs=e.get('relatedContentIds',[])
                            if not isinstance(refs,list) or not refs or not set(refs)<=known:
                                raise ModelError('AI 解析引用了不存在的正文，拒绝建立错误关联。')
                            exp.append({'id':f"explanation-{page['id']}-{i+1}",'title':str(e.get('title','Knowledge explanation')),
                                        'relatedContentIds':refs,'intuition':str(e.get('intuition','')),'example':str(e.get('example','')),
                                        'commonMistake':str(e.get('commonMistake','')),'relatedConcepts':e.get('relatedConcepts',[]),
                                        'supplementary':True,'label':'AI 补充说明','source':page['source']})
                    page['explanationsGenerated']=True
            elif ai:
                page['warnings'].append('未配置模型：视觉校验与翻译待完成。')
        except ModelAuthorizationError as exc:
            halt.set()
            page['warnings'].append(str(exc))
            progress('blocked',page['number'],len(pages),str(exc))
        except Exception as exc:
            page['warnings'].append(str(exc) if isinstance(exc,ModelError) else f'处理失败：{type(exc).__name__}；可恢复重试。')
            progress('page-error',page['number'],len(pages),page['warnings'][-1])
        finally:
            # Also publish cached explanations and the last completed batch on cancellation.
            write_json(saved,{'page':page,'explanations':exp})
            with lock:
                course['explanations'].extend(exp)
                done+=1
                progress('page-complete',done,len(pages),page['title'])
    if ai:
        with ThreadPoolExecutor(max_workers=max(1,min(workers,8))) as pool:
            for future in as_completed([pool.submit(process,p) for p in pages]):
                future.result()
    build_sections(files)
    course['status']='blocked' if halt.is_set() else 'cancelled' if cancel and cancel.is_set() else 'finished'
    course['explanations'].sort(key=lambda e:(e['source']['file'],e['source']['page'],e['id']))
    course['quality']=quality(course)
    write_json(output/'course.json',course)
    write_json(output/'terminology.json',terms)
    write_json(output/'quality-report.json',course['quality'])
    return course
