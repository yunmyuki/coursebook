"""Bounded high-detail rendering for small document text; cached per source page."""
import hashlib
import math
import threading
from pathlib import Path
import pypdfium2 as pdfium

_RENDER_LOCK=threading.Lock()
REGION_VERSION='region-render-1'


def source_pdf(page,output):
    """Only resolve retained sources inside this course, including Office renders."""
    root=Path(output).resolve();file_id=page.get('source',{}).get('fileId')
    if not file_id:return None
    candidates=[root/'sources'/(file_id+'.pdf')]
    candidates.extend((root/'.intermediate'/file_id).glob('*.pdf'))
    return next((p for p in candidates if p.is_file() and p.resolve().is_relative_to(root)),None)


def render_region(page,output,box,cache,*,purpose='ocr',fallback=None,padding=0):
    """Render the source region, not an enlarged preview. Coordinates are top-left.

    PDFium's render crop is measured from (left, bottom, right, top) in the
    rotated visible canvas. Keep both content and crop boxes for provenance.
    """
    from PIL import Image
    from .figures import valid_box
    if not valid_box(box):raise ValueError('区域坐标无效。')
    if purpose not in ('ocr','figure'):raise ValueError('未知区域用途。')
    bounds=[max(0,box[0]-padding),max(0,box[1]-padding),min(1,box[2]+padding),min(1,box[3]+padding)]
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    source=source_pdf(page,output) if output is not None else None
    fallback=Path(fallback) if fallback else Path(output)/page['image']
    evidence={'contentBBox':list(box),'cropBBox':bounds,'renderVersion':REGION_VERSION}
    with _RENDER_LOCK:
        if source is None:
            signature=hashlib.sha256(fallback.read_bytes()+repr((bounds,REGION_VERSION)).encode()).hexdigest()
            target=cache/(signature+'.png')
            with Image.open(fallback) as im:
                w,h=im.size
                coords=(int(bounds[0]*w),int(bounds[1]*h),max(int(bounds[2]*w),int(bounds[0]*w)+1),max(int(bounds[3]*h),int(bounds[1]*h)+1))
                if not target.exists():im.crop(coords).convert('RGB').save(target)
                size=[coords[2]-coords[0],coords[3]-coords[1]]
            return target,{**evidence,'method':'preview-crop','fallbackReason':'source-pdf-unavailable','pixelSize':size}
        doc=pdfium.PdfDocument(str(source))
        try:
            pdf_page=doc[page['number']-1]
            try:
                w,h=pdf_page.get_size();rw=(bounds[2]-bounds[0])*w;rh=(bounds[3]-bounds[1])*h
                sizes=[l.get('typography',{}).get('fontSize',0) for l in page.get('textLines',[]) if
                       l.get('position') and l['position'][0]<bounds[2] and l['position'][2]>bounds[0] and
                       l['position'][1]<bounds[3] and l['position'][3]>bounds[1]]
                sizes=sorted(s for s in sizes if isinstance(s,(int,float)) and s>0)
                small=sizes[len(sizes)//5] if sizes else 8
                desired=max(3,32/small) if purpose=='ocr' else 3
                scale=min(desired,8,4090/max(rw,rh),math.sqrt(5900000/(rw*rh)))
                spec=(source.stat().st_size,source.stat().st_mtime_ns,page['number'],bounds,scale,purpose,REGION_VERSION)
                target=cache/(hashlib.sha256(repr(spec).encode()).hexdigest()+'.png')
                if not target.exists():
                    crop=(bounds[0]*w,(1-bounds[3])*h,(1-bounds[2])*w,bounds[1]*h)
                    bitmap=pdf_page.render(scale=scale,crop=crop)
                    try:
                        bitmap.to_pil().convert('RGB').save(target)
                    finally:bitmap.close()
                with Image.open(target) as im:size=list(im.size)
                evidence.update(method='source-pdf-region',scale=scale,pixelSize=size,rotation=pdf_page.get_rotation())
                return target,evidence
            finally:pdf_page.close()
        finally:doc.close()


def prepare_image(page,output):
    root=Path(output).resolve();fallback=root/page['image']
    source=source_pdf(page,output)
    if source is None:return fallback
    sizes=[l.get('typography',{}).get('fontSize',0) for l in page.get('textLines',[]) if len(l.get('text',''))>12]
    sizes=sorted(s for s in sizes if s>0)
    small=sizes[max(0,len(sizes)//5)] if sizes else 10
    width=page.get('width',960);height=page.get('height',540)
    scale=min(max(1700/max(width,height),24/small),2800/max(width,height),math.sqrt(6000000/(width*height)))
    signature=hashlib.sha256(f'{source.stat().st_size}:{source.stat().st_mtime_ns}:{page["number"]}:{scale:.4f}:v1'.encode()).hexdigest()[:12]
    target=fallback.parent/(f'page-{page["number"]:03d}-vision-{signature}.png')
    # PDFium rendering is serialized even when model requests run concurrently.
    with _RENDER_LOCK:
        if not target.exists():
            doc=pdfium.PdfDocument(str(source))
            try:
                pdf_page=doc[page['number']-1]
                try:
                    bitmap=pdf_page.render(scale=scale)
                    try:bitmap.to_pil().convert('RGB').save(target)
                    finally:bitmap.close()
                finally:pdf_page.close()
            finally:doc.close()
    return target
