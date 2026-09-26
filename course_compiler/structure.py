"""Conservative heading reconstruction from source typography, preserving every anchor."""
import re
from collections import Counter


def typography(chars):
    visible=[c for c in chars if str(c.get('text','')).strip()]
    if not visible:return {}
    styles=Counter((c.get('fontname',''),round(float(c.get('size',0)),1)) for c in visible)
    (font,size),count=styles.most_common(1)[0]
    return {'fontName':font,'fontSize':size,'dominance':round(count/len(visible),3)}


def same_style(a,b):
    return bool(a.get('fontName') and a.get('fontName')==b.get('fontName') and
                a.get('dominance',0)>=.85 and b.get('dominance',0)>=.85 and
                abs(a.get('fontSize',0)-b.get('fontSize',0))<=.6)


def adjacent_heading(a,b):
    x,y=a.get('position'),b.get('position')
    if not x or not y or y[1]>.65:return False
    height=x[3]-x[1];other=y[3]-y[1]
    aligned=abs(x[0]-y[0])<.018 or abs((x[0]+x[2])-(y[0]+y[2]))<.035
    return height>0 and .65<other/height<1.5 and -.005<=y[1]-x[3]<=height*.65 and aligned


def pdf_text_lines(page):
    return [{'text':line['text'],'position':[line['x0']/page.width,line['top']/page.height,line['x1']/page.width,line['bottom']/page.height],
             'typography':typography(line.get('chars',[]))}
            for line in page.extract_text_lines(y_tolerance=8,x_tolerance=2,return_chars=True) if line['text'].strip()]


def attach_typography(page):
    """Use exact source-line text matches; never infer styles from generated wording."""
    norm=lambda text:re.sub(r'\s+',' ',text).strip()
    for u in page.get('units',[]):
        if u.get('reviewOnly') or u.get('typography') or not u.get('position'):continue
        matches=[line for line in page.get('textLines',[]) if norm(line['text'])==norm(u['sourceText']) and abs(line['position'][1]-u['position'][1])<.025]
        if len(matches)==1:u['typography']=dict(matches[0]['typography'])


def restore_heading_groups(page):
    """Join only close, equally styled title lines. Text, translations and IDs stay intact."""
    attach_typography(page)
    active=[u for u in page.get('units',[]) if not u.get('reviewOnly')]
    groups=[];index=0
    # Existing groups may include a user's corrected wording; geometry still belongs to the source.
    for u in active:u.pop('headingGroupId',None)
    while index<len(active):
        first=active[index];members=[first];cursor=index+1
        if first['type']!='title':index+=1;continue
        while cursor<len(active) and len(members)<4:
            item=active[cursor];previous=members[-1]
            if item['type'] not in ('title','paragraph') or re.match(r'^\s*[•●▪◦–—]',item['sourceText']):break
            shared_title_shape=first.get('headingContainerId') and first.get('headingContainerId')==item.get('headingContainerId')
            if not shared_title_shape and (not same_style(previous.get('typography',{}),item.get('typography',{})) or not adjacent_heading(previous,item)):break
            if len(' '.join(u['sourceText'] for u in members+[item]))>320:break
            members.append(item);cursor+=1
        if len(members)>1:
            gid=first['id']+'-heading'
            for member in members:
                if member['type']!='title':
                    member.setdefault('structureCorrections',[]).append({'kind':'wrapped-heading','beforeType':member['type'],'afterType':'title','evidence':'matching source font, size, alignment and line gap'})
                    member['type']='title'
                member['headingGroupId']=gid
            breaks=[]
            for previous,item in zip(members,members[1:]):
                if item['sourceText'].startswith(('(', '（')) and previous['sourceText'].count('(')==previous['sourceText'].count(')'):breaks.append(item['id'])
            # Existing visually reviewed main titles help preserve a separate author/subtitle line.
            if page.get('validationMethod')=='model-visual-audit' and page.get('title')==first['sourceText']:breaks.append(members[1]['id'])
            groups.append({'id':gid,'contentIds':[u['id'] for u in members],'sourceText':' '.join(u['sourceText'] for u in members),'lineBreakBefore':list(dict.fromkeys(breaks)),'method':'source-typography-v1'})
            if index==0 and not breaks:page['title']=groups[-1]['sourceText']
            index=cursor
        else:index+=1
    page['headingGroups']=groups
    return groups
