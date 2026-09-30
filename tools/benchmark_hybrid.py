"""Run an explicit, bounded sample benchmark; never overwrite the saved course.

python tools/benchmark_hybrid.py COURSE_ID --pages 2 10 16 --request-limit 20
Use --offline for routing estimates without sending any document to a service.
"""
import argparse
import copy
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from course_compiler.storage import Store
from course_compiler.parsers import DocumentParser,commit_layout
from course_compiler.reparse import refresh_evidence
from course_compiler.requests_control import RequestBudget

def main():
    args=argparse.ArgumentParser();args.add_argument('course');args.add_argument('--pages',nargs='+',type=int,default=[2,10,16]);args.add_argument('--request-limit',type=int,default=20);args.add_argument('--offline',action='store_true');options=args.parse_args()
    store=Store();site=store.course_path(options.course);course=json.loads((site/'course.json').read_text('utf-8'))
    profile=copy.deepcopy(store.settings()['profiles']['parse'])
    if 'siliconflow.cn' not in profile['baseUrl']:raise ValueError('此样本脚本只复用已配置的硅基流动密钥。')
    profile.update(engine='local-layout-ocr',model='PaddlePaddle/PaddleOCR-VL-1.5',ocrFlavor='paddle')
    parser=DocumentParser(profile,store.root/'cache/hybrid-benchmark');parser.layout_root=store.root
    budget=RequestBudget(options.request_limit);parser.model.budget=budget
    if options.offline:
        def placeholder(system,data,**kwargs):
            return '<table><tr><td>OFFLINE PLACEHOLDER</td></tr></table>' if 'Table' in data else 'OFFLINE PLACEHOLDER'
        parser.model.request=placeholder
    results=[]
    for number in options.pages:
        page=copy.deepcopy(course['files'][0]['pages'][number-1]);refresh_evidence(page,site);start=time.perf_counter()
        result=parser.parse(page,site)
        results.append({'page':number,'seconds':round(time.perf_counter()-start,3),'result':result})
        print(json.dumps({'page':number,'seconds':results[-1]['seconds'],'metrics':result['hybridMetrics'],'usage':budget.snapshot()},ensure_ascii=False),flush=True)
    dest=Path('tmp/hybrid-benchmark-offline.json' if options.offline else 'tmp/hybrid-benchmark-live.json');dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps({'results':results,'usage':budget.snapshot()},ensure_ascii=False,indent=2),'utf-8')

if __name__=='__main__':main()
