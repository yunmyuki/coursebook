"""Bounded high-detail rendering for small document text; cached per source page."""
import hashlib
import math
import threading
from pathlib import Path
import pypdfium2 as pdfium

_RENDER_LOCK=threading.Lock()


def prepare_image(page,output):
    root=Path(output).resolve();fallback=root/page['image']
    file_id=page.get('source',{}).get('fileId')
    if not file_id:return fallback
    candidates=[root/'sources'/(file_id+'.pdf')]
    candidates.extend((root/'.intermediate'/file_id).glob('*.pdf'))
    source=next((p for p in candidates if p.is_file() and p.resolve().is_relative_to(root)),None)
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
