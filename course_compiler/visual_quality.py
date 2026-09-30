"""Source-based layout checks, independent of the model's own confidence."""
import copy
import re
from collections import Counter
from .figures import valid_box,overlap,area

QUALITY_VERSION=1


def tokens(text):
    # Keep currency/math signs and digits, and avoid relying on Chinese whitespace.
    return re.findall(r'[\u3400-\u9fff]|[a-z]+|\d+(?:[.,]\d+)*|[%$¥€£+−=<>±×÷~≈-]',text.casefold())


def regions(page):
    from .layout import group_pdf_lines
    from .extract import BULLET
    lines=page.get('textLines',[])
    if not lines:return []
    return [{'type':g['kind'],'text':g['text'].replace('\n',' '),'bbox':g['box']}
            for g in group_pdf_lines(lines,{'horizontalRules':page.get('layoutAnalysis',{}).get('horizontalRules',[])},BULLET)]


def related(a,b):
    if not valid_box(a) or not valid_box(b):return False
    return all((min(a[i+2],b[i+2])-max(a[i],b[i]))/max(min(a[i+2]-a[i],b[i+2]-b[i]),.000001)>.65 for i in (0,1))


def column_conflicts(blocks,source_regions):
    conflicts=[]
    for i,b in enumerate(blocks):
        if b.get('type','paragraph') not in ('paragraph','bullet','caption') or b.get('contentOrigin')=='figure-transcription':continue
        near=[r for r in source_regions if related(b['bbox'],r['bbox']) and len(tokens(r['text']))>=4]
        for a in near:
            for c in near:
                x,y=a['bbox'],c['bbox']
                if x[2]+.02<y[0] and min(x[3],y[3])-max(x[1],y[1])>.008:
                    conflicts.append(i);break
            if i in conflicts:break
    return conflicts


def check_layout(page,result,repair=True):
    """Repair only exact-content regroupings. Otherwise surface a specific review issue."""
    value=copy.deepcopy(result);source=regions(page);blocks=value.get('blocks',[])
    restored_labels=0
    # A chart crop preserves the picture, but does not replace its searchable text.
    # Recover missing labels from the reliable PDF text layer, without another model call.
    if repair:
        for line in page.get('textLines',[]):
            box=line['position'];text=line['text']
            if not tokens(text) or '\ufffd' in text or re.search(r'\(cid:\d+\)',text):continue
            figure=next((f for f in value.get('figures',[]) if not f.get('contextOnly') and overlap(box,f['bbox'])/max(area(box),.000001)>.8),None)
            if figure is None:continue
            available=Counter(t for b in blocks if related(box,b['bbox']) for t in tokens(b['text']))
            if Counter(tokens(text))-available:
                blocks.append({'type':'caption','text':text,'bbox':box,'contentOrigin':'figure-transcription','sourceEvidence':'native-text-layer',
                               **({'readingOrder':figure['readingOrder']+(restored_labels+1)*.0001} if 'readingOrder' in figure else {})})
                restored_labels+=1
        value['blocks']=blocks
    protected=[r['bbox'] for k in ('tables','figures') for r in value.get(k,[])]
    usable=[r for r in source if not any(related(r['bbox'],b) for b in protected)]
    bad=column_conflicts(blocks,usable);repairs=[]
    if restored_labels:repairs.append({'kind':'figure-label-recovery','count':restored_labels,'evidence':'verbatim native text inside original figure'})
    if repair and bad:
        # Grow the connected component: a row-wise model block can touch several
        # complete source paragraphs and another row in the same group of columns.
        chosen=set(bad);chosen_source=set()
        while True:
            previous=(len(chosen),len(chosen_source))
            chosen_source.update(i for i,r in enumerate(usable) if any(related(r['bbox'],blocks[j]['bbox']) for j in chosen))
            chosen.update(i for i,b in enumerate(blocks) if b.get('type','paragraph') in ('paragraph','bullet','caption') and b.get('contentOrigin')!='figure-transcription' and any(related(b['bbox'],usable[j]['bbox']) for j in chosen_source))
            if previous==(len(chosen),len(chosen_source)):break
        originals=[usable[i] for i in sorted(chosen_source)]
        model_words=Counter(t for i in chosen for t in tokens(blocks[i]['text']))
        source_words=Counter(t for r in originals for t in tokens(r['text']))
        if originals and model_words==source_words:
            replacements=[{**r,'type':'paragraph' if r['type']=='title' else r['type']} for r in originals]
            value['blocks']=[b for i,b in enumerate(blocks) if i not in chosen]+replacements
            for k in ('blocks','tables','figures'):
                for b in value.get(k,[]):b.pop('readingOrder',None)
            repairs.append({'kind':'column-regrouping','before':len(chosen),'after':len(replacements),'evidence':'source geometry and identical token multiplicity'})
    remaining=column_conflicts(value.get('blocks',[]),usable)
    issues=[]
    for i in remaining:
        b=value['blocks'][i];b['uncertain']=True
        issues.append({'kind':'cross-column','bbox':b['bbox'],'message':'一个正文单元跨越多个独立栏位，请重新识别本页或对照原页修正。'})
    value['localQuality']={'version':QUALITY_VERSION,'issues':issues,'repairs':repairs,'checkedRegions':len(source),
                           'evidence':'native-text-geometry' if source else 'no-native-text'}
    return value


def cached_page_issues(page):
    active=[u for u in page.get('units',[]) if not u.get('reviewOnly')]
    result={'blocks':[{'type':u['type'],'text':u['sourceText'],'bbox':u['position'],'contentOrigin':u.get('contentOrigin','source')} for u in active if u['type']!='table-cell' and valid_box(u.get('position'))],
            'figures':[{'bbox':f['position']} for f in page.get('figures',[])],
            'tables':[{'bbox':u['position']} for u in active if u['type']=='table-cell' and valid_box(u.get('position'))]}
    issues=check_layout(page,result,repair=False)['localQuality']['issues']
    if any(u.get('uncertain') for u in active):issues.append({'kind':'uncertain-content','message':'存在未解决的原文识别疑点。'})
    return issues
