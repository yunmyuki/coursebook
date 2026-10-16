"""Conservative ruled-table extraction with physical cell bounds, never guessed grids."""
import re
from .figures import valid_box,overlap,area


def reliable_text(text):
    return not re.search(r'[\ufffd\x00-\x08\ue000-\uf8ff]|\(cid:\d+\)|\.notdef',text)


def extract_tables(page):
    """Only complete ruled tables; scans, ambiguous grids and empty tables use OCR."""
    result=[];ox,oy=page.bbox[:2]
    settings={'vertical_strategy':'lines','horizontal_strategy':'lines','snap_tolerance':2,'join_tolerance':2,'intersection_tolerance':2}
    def normalized(b):return [(b[0]-ox)/page.width,(b[1]-oy)/page.height,(b[2]-ox)/page.width,(b[3]-oy)/page.height]
    for table in page.find_tables(settings):
        if len(table.cells)>1500:continue
        xs=sorted(set(v for b in table.cells for v in (b[0],b[2])))
        ys=sorted(set(v for b in table.cells for v in (b[1],b[3])))
        if len(xs)<3 or len(ys)<3:continue
        box=normalized(table.bbox)
        if not valid_box(box):continue
        cells=[];assigned=set();complete=True
        for bounds in table.cells:
            # Character centres assign each glyph once; boundary-crossing glyphs
            # invalidate the native fast path instead of silently truncating it.
            chars=[(i,c) for i,c in enumerate(page.chars) if bounds[0]<= (c['x0']+c['x1'])/2 <bounds[2] and bounds[1]<= (c['top']+c['bottom'])/2 <bounds[3]]
            if any(c['x0']<bounds[0]-1 or c['x1']>bounds[2]+1 or c['top']<bounds[1]-1 or c['bottom']>bounds[3]+1 for _,c in chars):complete=False
            assigned.update(i for i,_ in chars)
            from pdfplumber.utils import extract_text
            text=extract_text([c for _,c in chars],x_tolerance=2,y_tolerance=3) if chars else ''
            if not reliable_text(text):complete=False
            col=xs.index(bounds[0]);row=ys.index(bounds[1])
            cells.append({'text':text,'row':row,'col':col,'rowSpan':ys.index(bounds[3])-row,'colSpan':xs.index(bounds[2])-col,'bbox':normalized(bounds),'sourceEvidence':'native-table-grid'})
        all_chars={i for i,c in enumerate(page.chars) if table.bbox[0]<= (c['x0']+c['x1'])/2 <table.bbox[2] and table.bbox[1]<= (c['top']+c['bottom'])/2 <table.bbox[3]}
        if not complete or assigned!=all_chars or not any(c['text'].strip() for c in cells):continue
        # Never trust an extracted grid over raster text/images, even with an OCR layer.
        if any(overlap(box,normalized((im['x0'],im['top'],im['x1'],im['bottom'])))>0 for im in page.images):continue
        occupied=set()
        for c in cells:
            slots={(r,k) for r in range(c['row'],c['row']+c['rowSpan']) for k in range(c['col'],c['col']+c['colSpan'])}
            if slots&occupied:complete=False
            occupied.update(slots)
        if not complete or len(occupied)!=(len(xs)-1)*(len(ys)-1):continue
        coverage=[normalized((page.chars[i]['x0'],page.chars[i]['top'],page.chars[i]['x1'],page.chars[i]['bottom'])) for i in assigned]
        coverage.extend(normalized((e['x0'],e['top'],e['x1'],e['bottom'])) for e in page.edges if e.get('orientation') in ('h','v') and
                        table.bbox[0]-2<=e['x0'] and e['x1']<=table.bbox[2]+2 and table.bbox[1]-2<=e['top'] and e['bottom']<=table.bbox[3]+2)
        result.append({'bbox':box,'cells':sorted(cells,key=lambda c:(c['row'],c['col'])),'coverageBoxes':coverage,'sourceEvidence':'native-table-grid'})
    return result


def matching_table(region,tables):
    matches=[t for t in tables if valid_box(t.get('bbox')) and overlap(region,t['bbox'])/max(area(region),area(t['bbox']),1e-9)>.85]
    return matches[0] if len(matches)==1 else None
