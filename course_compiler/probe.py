"""Explicit, small connection checks against the user's selected service."""
import tempfile
from pathlib import Path
from PIL import Image,ImageDraw
from .parsers import DocumentParser,make_model,validate_layout
from .requests_control import RequestBudget
from .model import ModelError

def probe(store,role,incoming):
    profile=store.probe_profile(role,incoming)
    parent=store.root/'probes';parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        output=Path(directory);budget=RequestBudget(2)
        if role=='parse':
            im=Image.new('RGB',(800,300),'white');ImageDraw.Draw(im).text((50,80),'coursebook\nSample value: 12.5%',fill='black',font_size=32);im.save(output/'probe.jpg')
            parser=DocumentParser(profile,output/'cache');parser.model.budget=budget
            parser.layout_root=store.root
            result=parser.parse({'image':'probe.jpg','rawText':''},output);validate_layout(result)
            message='图片解析与版面格式验证通过。实际讲义质量仍需复核。'
        else:
            model=make_model(profile,output/'cache');model.budget=budget;model.max_attempts=1
            result=model.request('Return JSON only: {"ok":true}.','Connection test.',max_tokens=64)
            if result.get('ok') is not True:raise ModelError('连接成功，但模型未按要求返回结构化结果。')
            message='文本模型连接与结构化输出验证通过。'
        return {'ok':True,'message':message,'usage':budget.snapshot()}
