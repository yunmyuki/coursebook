"""Preserve figures as crops of the rendered original, with stable source anchors."""
import hashlib
from pathlib import Path
from PIL import Image

def valid_box(box):
    return isinstance(box,(list,tuple)) and len(box)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in box) and box[2]>box[0] and box[3]>box[1]

def area(b):return max(0,b[2]-b[0])*max(0,b[3]-b[1])
def overlap(a,b):return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def mark_figure_text(page):
    """Record visual origin without changing source text or content anchors."""
    for u in page['units']:
        if u.get('reviewOnly') or u['type']=='table-cell' or not valid_box(u.get('position')):continue
        u.pop('figureIds',None)
        refs=[f['id'] for f in page.get('figures',[]) if overlap(f['position'],u['position'])/max(area(u['position']),.000001)>=.6]
        if refs:
            u['figureIds']=refs
            u.setdefault('contentOrigin','figure-transcription')

def add_figure(page,output,box,kind='image',caption='',origin='source-crop'):
    if not valid_box(box):raise ValueError('图像区域坐标无效。')
    rounded=[round(v,4) for v in box]
    fid='figure-'+page['id']+'-'+hashlib.sha256(str(rounded).encode()).hexdigest()[:10]
    figures=page.setdefault('figures',[])
    same=next((f for f in figures if overlap(f['position'],box)/max(area(f['position']),area(box))>.94),None)
    if same:return same
    output=Path(output);image=output/page['image'];dest=output/'assets'/page['source']['fileId']/(fid+'.png');dest.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(image) as im:
        coords=(int(box[0]*im.width),int(box[1]*im.height),max(int(box[2]*im.width),int(box[0]*im.width)+1),max(int(box[3]*im.height),int(box[1]*im.height)+1))
        crop=im.crop(coords);crop.save(dest);width,height=crop.size
    related=[u['id'] for u in page['units'] if not u.get('reviewOnly') and valid_box(u.get('position')) and overlap(box,u['position'])/max(area(u['position']),.000001)>.3]
    f={'id':fid,'kind':kind if kind in ('image','chart','diagram') else 'image','image':dest.relative_to(output).as_posix(),'position':rounded,'source':dict(page['source']),'caption':caption,'width':width,'height':height,'relatedContentIds':related,'origin':origin}
    figures.append(f);return f

def native_figures(page,output):
    active=[u for u in page['units'] if not u.get('reviewOnly')]
    for box in page.get('imageRegions',[]):
        if not valid_box(box) or area(box)<.008:continue
        cells=[u for u in active if u['type']=='table-cell' and valid_box(u.get('position')) and overlap(box,u['position'])>.0001]
        # Scanned table pages are transcribed into cells, not presented as duplicate figures.
        if len(cells)>12 and len(cells)>len(active)*.5:continue
        add_figure(page,output,box,origin='pdf-image-region')
    mark_figure_text(page)
