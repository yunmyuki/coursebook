"""Isolated browser fixture. Never uses local API keys or user courses."""
import copy,json,sys,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from course_compiler.app_server import make_server
from course_compiler.extract import unit
from course_compiler.pipeline import quality
from course_compiler.export import export_site
from course_compiler.storage import atomic_json
from tools.release_demo import build_demo

if __name__=='__main__':
    root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
    fixture=root/'fixture';fixture.mkdir(exist_ok=True)
    build_demo(root/'demo',root/'demo.zip')
    with zipfile.ZipFile(root/'demo.zip') as z:z.extractall(fixture)
    c=json.loads((fixture/'course.json').read_text('utf-8'))
    for f in c['files']:
        for p in f['pages']:
            u=unit(p['id'],999,f'INVESTMENT BANKING AND VALUATION · FUDAN SCHOOL OF MANAGEMENT {p["number"]}页','footnote',p['source'],[.1,.94,.9,.98])
            u.update(translatedText='固定页脚 '+str(p['number']),translationStatus='complete');p['units'].append(u);p['rawUnits'].append(copy.deepcopy(u))
    c['quality']=quality(c);atomic_json(fixture/'course.json',c);export_site(c,fixture,root/'fixture.zip')
    if '--prepare-only' in sys.argv:sys.exit(0)
    with patch('course_compiler.storage.local_settings',return_value={}):
        server=make_server(int(sys.argv[2]),root/'workspace')
        print('ready',flush=True)
        try:server.serve_forever()
        finally:server.server_close()
