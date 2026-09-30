"""Pinned PP-DocLayoutV3 export, CPU-only ORT; no Paddle or Torch dependency.

Contract verified against PaddleX layout_analysis and the official ONNX export.
The seventh output column is reading order, NOT confidence ordering.
"""
import hashlib
import importlib.util
import json
import threading
import time
from pathlib import Path
from PIL import Image
from .model import ModelError
from .paths import data_root,resource_root

REVISION='46bbdf188bb0a772c08aed74882ce7e51a8f1ea6'
SHA256='45bf71750b00739a41fc209f132eb104a4d6b5bb29483c9078164d8b87cf28ba'
SIZE=130502049
MODEL_URL=f'https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/resolve/{REVISION}/inference.onnx'
LABELS=('abstract','algorithm','aside_text','chart','content','display_formula','doc_title',
        'figure_title','footer','footer_image','footnote','formula_number','header','header_image',
        'image','inline_formula','number','paragraph_title','reference','reference_content','seal',
        'table','text','vertical_text','vision_footnote')
VERSION='doclayout-v3-onnx-2'
_lock=threading.RLock()
_sessions={}

def model_path(root=None):
    local=Path(root or data_root())/'models'/'PP-DocLayoutV3'/'inference.onnx'
    bundled=resource_root()/'models'/'PP-DocLayoutV3'/'inference.onnx'
    return local if local.exists() or not bundled.is_file() else bundled

def status(root=None):
    path=model_path(root)
    runtime=importlib.util.find_spec('onnxruntime') is not None
    installed=path.is_file() and path.stat().st_size==SIZE
    return {'runtimeAvailable':runtime,'installed':installed,'ready':runtime and installed,
            'bytes':SIZE,'path':str(path),'revision':REVISION,'sha256':SHA256}

def verify(path):
    if not path.is_file() or path.stat().st_size!=SIZE:
        raise ModelError('请先在高级模型设置中安装 PP-DocLayoutV3 版面组件（约 131 MB）。')
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=SHA256:
        raise ModelError('版面模型校验失败，请重新安装官方固定版本。')

def install(root=None,source=None,progress=lambda *a:None):
    """Optional fixed-source download or local import; validate before atomic replace."""
    import urllib.request
    import shutil
    # Installs always target writable user data, never the bundled resource.
    path=Path(root or data_root())/'models'/'PP-DocLayoutV3'/'inference.onnx';path.parent.mkdir(parents=True,exist_ok=True)
    from .cache_locks import request_lock
    with request_lock(str(path)):
        temp=path.with_suffix('.download')
        try:
            if source:
                with open(source,'rb') as src,temp.open('wb') as dest:shutil.copyfileobj(src,dest)
            else:
                with urllib.request.urlopen(MODEL_URL,timeout=60) as src,temp.open('wb') as dest:
                    total=0
                    while chunk:=src.read(1024*256):
                        total+=len(chunk)
                        if total>SIZE:raise ModelError('模型下载大小异常。')
                        dest.write(chunk);progress(total,SIZE)
            verify(temp);temp.replace(path)
        finally:
            if temp.exists():temp.unlink()
    return status(root)

def session(root=None):
    path=model_path(root)
    with _lock:
        signature=(str(path.resolve()),path.stat().st_mtime_ns if path.exists() else 0)
        if signature not in _sessions:
            verify(path)
            try:import onnxruntime as ort
            except ImportError:raise ModelError('本版本尚未安装 ONNX Runtime。开发环境请安装 requirements-layout.txt。') from None
            options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
            options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            loaded=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
            if {i.name for i in loaded.get_inputs()}!={'image','im_shape','scale_factor'}:
                raise ModelError('版面模型输入协议不匹配。')
            _sessions.clear();_sessions[signature]=loaded
        return _sessions[signature]

def decode(rows,width,height,threshold=.3):
    """Class-aware NMS, retain region order and confidence for audit."""
    from .figures import area,overlap,valid_box
    if getattr(rows,'ndim',0)!=2 or rows.shape[1] not in (7,8):
        raise ModelError('版面模型缺少阅读顺序输出，未降级成逐行排序。')
    candidates=[]
    for row in rows:
        cls=int(row[0]);score=float(row[1])
        if not 0<=cls<len(LABELS) or score<threshold:continue
        box=[max(0.,min(1.,float(v)/scale)) for v,scale in zip(row[2:6],(width,height,width,height))]
        if not valid_box(box):continue
        candidates.append({'label':LABELS[cls],'score':round(score,5),'bbox':box,
                           'modelOrder':float(row[6]),'orderTie':-float(row[7]) if len(row)==8 else 0})
    kept=[]
    for item in sorted(candidates,key=lambda r:-r['score']):
        def duplicate(old):
            inter=overlap(item['bbox'],old['bbox']);iou=inter/max(area(item['bbox'])+area(old['bbox'])-inter,1e-9)
            contained=inter/max(min(area(item['bbox']),area(old['bbox'])),1e-9)>.95
            return iou>(.6 if old['label']==item['label'] else .98) or (old['label']==item['label'] and contained)
        if not any(duplicate(k) for k in kept):kept.append(item)
    # Large slide backgrounds otherwise swallow all text in some exports.
    kept=[k for k in kept if not(k['label']=='image' and area(k['bbox'])>.93 and len(kept)>2)]
    for i,item in enumerate(sorted(kept,key=lambda r:(r['modelOrder'],r['orderTie']))):item['readingOrder']=i
    return sorted(kept,key=lambda r:r['readingOrder'])

def detect(image,cache,root=None):
    import numpy as np
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(Path(image).read_bytes()+VERSION.encode()+SHA256.encode()).hexdigest()
    saved=cache/(key+'.layout.json')
    if saved.exists():return {**json.loads(saved.read_text('utf-8')),'cacheHit':True}
    started=time.perf_counter();runtime=session(root)
    with Image.open(image) as source:
        width,height=source.size
        pixels=np.asarray(source.convert('RGB').resize((800,800),Image.Resampling.BICUBIC),dtype=np.float32)/255.
    feed={'image':pixels.transpose(2,0,1)[None], 'im_shape':np.array([[800,800]],dtype=np.float32),
          'scale_factor':np.array([[800/height,800/width]],dtype=np.float32)}
    # Bound RAM/CPU when multiple course pages are processed concurrently.
    with _lock:outputs=runtime.run(None,feed)
    rows=next((o for o in outputs if o.ndim==2 and o.shape[-1] in (7,8)),None)
    if rows is None:raise ModelError('版面模型未返回区域及阅读顺序。')
    result={'regions':decode(rows,width,height),'seconds':round(time.perf_counter()-started,3),
            'model':VERSION,'sha256':SHA256,'imageSize':[width,height]}
    from .storage import atomic_json
    atomic_json(saved,result)
    return result
