"""Offline source/layout diagnostics. Never loads API credentials or calls cloud OCR.

Example: python tools/benchmark_parser_precision.py lecture.pdf --pages 2 10 16
Reports are diagnostic evidence, not OCR accuracy scores or billing estimates.
"""
import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from course_compiler.extract import extract_pdf
from course_compiler.visual_input import prepare_image,render_region
from course_compiler.local_layout import detect
from course_compiler.hybrid_parser import contains,FIGURES,trusted_native,native_blocks,parse
from course_compiler.figures import area


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('--pages',type=int,nargs='+',required=True,help='PDF physical page numbers, starting at 1')
    ap.add_argument('--output',type=Path,default=Path('tmp/parser-precision-benchmark'))
    ap.add_argument('--data-root',type=Path,default=Path('local-data'),help='Directory containing models/PP-DocLayoutV3')
    args=ap.parse_args()
    if min(args.pages)<1:ap.error('Page numbers start at 1')
    source=args.source.resolve();root=args.output.resolve()
    fid='lecture-'+hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    retained=root/'sources'/(fid+'.pdf');retained.parent.mkdir(parents=True,exist_ok=True)
    if not retained.exists():shutil.copy2(source,retained)
    start=time.monotonic()
    pages=extract_pdf(source,root,fid,page_numbers=set(args.pages))
    if {p['number'] for p in pages}!=set(args.pages):ap.error('One or more page numbers are outside the PDF')
    report={'apiCalls':0,'scope':'local extraction, layout, region rendering; no cloud OCR accuracy evaluation','pages':[]}
    for page in pages:
        image=prepare_image(page,root)
        layout=detect(image,root/'layout',args.data_root)
        regions=layout['regions'];assignments={i:[] for i in range(len(regions))}
        for line in page['textLines']:
            options=[i for i,r in enumerate(regions) if contains(r['bbox'],line['position'])]
            if options:
                chosen=min(options,key=lambda i:(0 if regions[i]['label'] in FIGURES|{'table'} else 1,area(regions[i]['bbox'])))
                assignments[chosen].append(line)
        entry={'page':page['number'],'nativeTableCandidates':len(page['nativeTables']),'layoutSeconds':layout['seconds'],'regions':[]}
        with Image.open(image) as raster:
            for i,region in enumerate(regions):
                trusted=trusted_native(region,assignments[i],raster,page)
                item={'label':region['label'],'bbox':region['bbox'],'readingOrder':region['readingOrder'],'nativeTextEligible':trusted}
                if trusted:
                    item['paragraphs']=[b['text'] for b in native_blocks(region,assignments[i],page['layoutAnalysis']['horizontalRules'])]
                else:
                    crop,meta=render_region(page,root,region['bbox'],root/'regions',fallback=image,padding=.002)
                    item.update(crop=crop.relative_to(root).as_posix(),rendering=meta)
                entry['regions'].append(item)
        # A real pipeline dry run is safe: its model double refuses every request.
        class CloudRequired(Exception):pass
        class NoCloud:
            def request(self,*a,**kw):raise CloudRequired()
        try:
            result=parse(page,image,NoCloud(),{'model':'offline-diagnostic'},root/'pipeline',root=args.data_root,output=root)
            entry['pipeline']={'status':'completed-without-ocr','metrics':result['hybridMetrics'],'blocks':result['blocks']}
        except CloudRequired:
            entry['pipeline']={'status':'cloud-region-required-not-executed'}
        report['pages'].append(entry)
    report['seconds']=round(time.monotonic()-start,3)
    target=root/'report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(pages)} pages; 0 cloud requests; diagnostics: {target}')


if __name__=='__main__':main()
