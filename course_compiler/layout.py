"""Local geometry checks. No model calls, no inferred or discarded source words."""
import re


def join_wrapped_lines(parts):
    """Join visual wraps without inserting artificial spaces between CJK glyphs."""
    result=''
    for part in parts:
        part=part.strip()
        if not part:continue
        cjk=r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]'
        separator='' if result and re.search(cjk+'$',result) and re.match(cjk,part) else ' '
        result+=separator+part if result else part
    return result


def region_paragraphs(lines,rules=()):
    """Split a detector region into paragraphs; never concatenate separate columns.

    Geometry remains available even when an OCR/text layer has no font metadata.
    In that case use conservative alignment/gap checks, rather than treating the
    entire detector box as one paragraph.
    """
    from .structure import same_style
    bullet=re.compile(r'^\s*(?:[•●▪◦‣]|[–—*]\s|\d+[.)]\s)')
    groups=[]
    for line in geometric_order(lines):
        if not line['text'].strip():continue
        merge=False
        if groups and not bullet.match(line['text']):
            previous=groups[-1][-1];a=previous['position'];b=line['position']
            h=max(a[3]-a[1],b[3]-b[1]);gap=b[1]-a[3]
            aligned=abs(a[0]-b[0])<=.018 or (bullet.match(groups[-1][0]['text']) and 0<=b[0]-a[0]<=.035)
            intersection=min(a[2],b[2])-max(a[0],b[0])
            separate=any(a[3]-.001<=r[1]<=b[1]+.001 and min(a[2],r[2])>max(a[0],r[0]) for r in rules)
            styles=(previous.get('typography',{}),line.get('typography',{}))
            styled=all(s.get('fontName') for s in styles)
            # Relative line spacing works for both slides and dense documents.
            merge=aligned and intersection>0 and -.003<=gap<=h*1.05 and not separate
            if styled:
                left={**styles[0],'fontName':font_family(styles[0]['fontName'])}
                right={**styles[1],'fontName':font_family(styles[1]['fontName'])}
                merge=merge and same_style(left,right)
            if re.search(r'[.!?。！？][\)\]”\x27"]?$',previous['text'].strip()) and a[2]-a[0]<(b[2]-b[0])*.85:
                merge=False
        if merge:groups[-1].append(line)
        else:groups.append([line])
    return groups


def font_family(name):
    # PDF subset prefixes identify embedded subsets, not different typefaces.
    return re.sub(r'^[A-Z]{6}\+', '', name or '')


def visible_page(page):
    """Use the same rotated CropBox canvas as the PDFium preview and crop renderer."""
    if not page.cropbox:return page
    a=page.bbox;b=page.cropbox
    box=(max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3]))
    return page.crop(box) if box!=a and box[2]>box[0] and box[3]>box[1] else page


def split_pdf_lines(page):
    """Keep columns apart before paragraph reconstruction or sending text hints."""
    from pdfplumber.utils import extract_text
    from .structure import typography
    lines=[];split_rows=0;ox,oy=page.bbox[:2]
    for line in page.extract_text_lines(y_tolerance=3, x_tolerance=2, return_chars=True):
        chars=sorted((c for c in line['chars'] if c.get('text','').strip()), key=lambda c:c['x0'])
        runs=[]
        for char in chars:
            if not runs or char['x0']-max(c['x1'] for c in runs[-1])>max(page.width*.025, float(char.get('size',10))*2.5):
                runs.append([])
            runs[-1].append(char)
        if len(runs)>1:split_rows+=1
        for run in runs:
            lines.append({'text':extract_text(run,x_tolerance=2,y_tolerance=3),
                          'position':[(min(c['x0'] for c in run)-ox)/page.width,(min(c['top'] for c in run)-oy)/page.height,
                                      (max(c['x1'] for c in run)-ox)/page.width,(max(c['bottom'] for c in run)-oy)/page.height],
                          'typography':typography(run)})
    rules=[]
    for edge in page.edges:
        if edge.get('orientation')=='h' and edge['x1']-edge['x0']>page.width*.12 and .03<(edge['top']-oy)/page.height<.97:
            box=[(edge['x0']-ox)/page.width,(edge['top']-oy)/page.height,(edge['x1']-ox)/page.width,(edge['bottom']-oy)/page.height]
            if not any(abs(box[1]-r[1])<.004 and abs(box[0]-r[0])<.01 and abs(box[2]-r[2])<.01 for r in rules):rules.append(box)
    vertical=[e for e in page.edges if e.get('orientation')=='v' and e['bottom']-e['top']>page.height*.18 and .05<(e['x0']-ox)/page.width<.95]
    # Sparse tables and split-column slides often have fewer than 14 vector objects.
    reasons=[]
    if split_rows>=2:reasons.append('repeated-column-gaps')
    if vertical:reasons.append('vertical-layout-divider')
    if len(rules)>=3:reasons.append('repeated-horizontal-rules')
    return lines, {'version':1,'complex':bool(reasons),'reasons':reasons,'splitRows':split_rows,'horizontalRules':rules}


def geometric_order(items, box_key='position'):
    """XY cut: spanning headings/footers, then independent columns inside each band."""
    if len(items)<2:return list(items)
    def gaps(axis):
        ranges=sorted((i[box_key][axis],i[box_key][axis+2]) for i in items)
        end=ranges[0][1];result=[]
        for start,stop in ranges[1:]:
            if start>end:result.append((start-end,(start+end)/2))
            end=max(end,stop)
        return result
    # Prefer vertical gutters; horizontal whitespace separates spanning regions.
    for axis,minimum in ((0,.025),(1,.008)):
        candidates=[g for g in gaps(axis) if g[0]>=minimum]
        if candidates:
            _,cut=max(candidates)
            before=[i for i in items if i[box_key][axis+2]<=cut]
            after=[i for i in items if i[box_key][axis]>=cut]
            if before and after and len(before)+len(after)==len(items):
                return geometric_order(before,box_key)+geometric_order(after,box_key)
    return sorted(items,key=lambda i:(i[box_key][1],i[box_key][0]))


def paragraph_continuation(previous,current,rules=()):
    """Require geometry and typography; a line break alone is never a paragraph."""
    a=previous['position'];b=current['position'];sa=previous.get('typography',{});sb=current.get('typography',{})
    if not sa.get('fontName') or font_family(sa['fontName'])!=font_family(sb.get('fontName')):return False
    if min(sa.get('dominance',0),sb.get('dominance',0))<.65 or abs(sa.get('fontSize',0)-sb.get('fontSize',0))>.6:return False
    h=a[3]-a[1];other=b[3]-b[1]
    if h<=0 or not .65<other/h<1.55:return False
    if abs(a[0]-b[0])>.012 or not -.003<=b[1]-a[3]<=min(h*.85,.025):return False
    if any(a[3]-.001<=r[1]<=b[1]+.001 and min(a[2],r[2])>max(a[0],r[0]) for r in rules):return False
    # A short, completed sentence followed by another line is ambiguous: keep it separate.
    if re.search(r'[.!?。！？][\)\]”\x27"]?$',previous['text'].strip()) and a[2]-a[0]<(b[2]-b[0])*.85:return False
    return True


def group_pdf_lines(lines,layout,bullet_pattern):
    from .structure import same_style,adjacent_heading
    groups=[]
    for line in geometric_order(lines):
        text=line['text'];box=line['position'];style=line['typography']
        bullet=bool(bullet_pattern.match(text));continuation=False
        if groups:
            previous=groups[-1];last=previous['lastLine']
            continuation=not bullet and previous['kind']=='title' and same_style(last['typography'],style) and adjacent_heading(last,line)
            if not bullet and previous['kind'] in ('paragraph','bullet') and paragraph_continuation(last,line,layout['horizontalRules']):
                previous['text']+='\n'+text
                previous['box']=[min(previous['box'][0],box[0]),min(previous['box'][1],box[1]),max(previous['box'][2],box[2]),max(previous['box'][3],box[3])]
                previous['lastLine']=line
                continue
        kind='bullet' if bullet else 'title' if continuation or not groups and box[1]<.35 else 'paragraph'
        groups.append({'text':text,'box':box,'kind':kind,'style':style,'lastLine':line})
    return groups
