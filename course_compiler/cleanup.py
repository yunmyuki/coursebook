"""Conservative, reversible, user-confirmed running-header/footer cleanup."""
import hashlib,json,math,re
from collections import defaultdict
from datetime import datetime,timezone
from .storage import atomic_json

def revision(course):
    return hashlib.sha256(json.dumps(course,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def signature(unit):
    if unit.get('reviewOnly') and not unit.get('cleanupHidden'):return None
    if unit.get('type') not in ('paragraph','caption','footnote') or unit.get('figureIds'):return None
    text=unit.get('sourceText','').strip();box=unit.get('position')
    if not isinstance(box,list) or len(box)!=4 or not all(isinstance(v,(int,float)) for v in box):return None
    if not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):return None
    edge='footer' if box[1]>=.87 else 'header' if box[3]<=.09 else None
    if not edge or len(text)>180 or '\n' in text or unit.get('corrections'):return None
    normalized=re.sub(r'\s+',' ',text).casefold()
    if re.search(r'\b(?:definition|theorem|lemma)\b|定义|定理',normalized) or re.match(r'(?:sources?|references?|来源|参考)\s*[:：]',normalized):return None
    counter=bool(re.fullmatch(r'(?:page\s*)?\d{1,4}(?:\s*[/of]+\s*\d{1,4})?|第?\s*\d{1,4}\s*页(?:\s*[/共]\s*\d{1,4}\s*页?)?',normalized))
    marker=re.search(r'\b(?:school|university|college|copyright)\b|大学|学院|版权所有|©',normalized)
    if not counter and not marker:return None
    # Only variable terminal page numbers are normalized; internal years stay intact.
    normalized=re.sub(r'(?:[·|—\-]\s*)?(?:page\s*|第\s*)?\d{1,4}(?:\s*[/of]+\s*\d{1,4})?\s*页?\s*$','{page}',normalized)
    return edge,normalized,round((box[1]+box[3])/2,1)

def proposals(course):
    result=[]
    for file in course['files']:
        groups=defaultdict(list)
        for page in file['pages']:
            for unit in page['units']:
                key=signature(unit)
                if key:groups[key].append((page,unit))
        for key,rows in groups.items():
            if len({p['id'] for p,u in rows})<max(3,math.ceil(len(file['pages'])*.6)):continue
            ids=[u['id'] for p,u in rows]
            result.append({'id':hashlib.sha256(('|'.join(ids)).encode()).hexdigest()[:20],
                'text':rows[0][1]['sourceText'],'file':rows[0][0]['source']['file'],
                'pages':sorted({p['number'] for p,u in rows}),'contentIds':ids,
                'kind':key[0],'hidden':all(u.get('cleanupHidden') for p,u in rows)})
    return result

def apply_cleanup(course,root):
    path=root/'cleanup'/(course['id']+'.json')
    if not path.exists():return
    hidden=json.loads(path.read_text('utf-8')).get('hidden',{})
    for file in course['files']:
        for page in file['pages']:
            for unit in page['units']:
                if unit.get('cleanupHidden'):
                    unit.pop('cleanupHidden',None);unit['reviewOnly']=False
                if not unit.get('reviewOnly') and hidden.get(unit['id'])==unit['sourceText']:
                    unit.update(cleanupHidden=True,reviewOnly=True)

def preview(store,cid):
    course=json.loads((store.course_path(cid)/'course.json').read_text('utf-8'))
    return {'revision':revision(course),'groups':proposals(course),'hiddenCount':sum(bool(u.get('cleanupHidden')) for f in course['files'] for p in f['pages'] for u in p['units'])}

def clean_course(store,cid,data):
    from .review import persist_course
    course=json.loads((store.course_path(cid)/'course.json').read_text('utf-8'))
    if data.get('revision')!=revision(course):raise ValueError('课程已更新，请重新打开清洗预览。')
    action=data.get('action');chosen=data.get('groupIds',[])
    if action not in ('hide','restore','restore-all') or not isinstance(chosen,list):raise ValueError('清洗操作无效。')
    groups={g['id']:g for g in proposals(course)}
    if any(not isinstance(i,str) or i not in groups for i in chosen):raise ValueError('清洗候选已变化，请刷新。')
    selected={uid for gid in chosen for uid in groups[gid]['contentIds']}
    for file in course['files']:
        for page in file['pages']:
            for u in page['units']:
                if action=='restore-all' and u.get('cleanupHidden') or u['id'] in selected:
                    if action=='hide':u.update(cleanupHidden=True,reviewOnly=True)
                    elif u.get('cleanupHidden'):u.pop('cleanupHidden');u['reviewOnly']=False
    hidden={u['id']:u['sourceText'] for f in course['files'] for p in f['pages'] for u in p['units'] if u.get('cleanupHidden')}
    from .pipeline import quality
    if quality(course)['errors']:raise ValueError('关联检查失败，未保存清洗。')
    atomic_json(store.root/'cleanup'/(cid+'.json'),{'hidden':hidden,'updatedAt':datetime.now(timezone.utc).isoformat()})
    persist_course(store,cid,course)
    return {'saved':True,'hiddenCount':len(hidden)}
