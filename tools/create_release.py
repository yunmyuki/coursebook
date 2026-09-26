"""Allowlisted public release: no course material, workspace records or credentials.

prepare: attach notices and a headless Office component to an already built app.
package: require EXE self-test reports, then create ZIPs, hashes and a source tree.
"""
import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
OUT=ROOT/'release'/__version__
APP=OUT/'app/CourseCompiler'
OFFICE=APP/'_internal/office'
REPOSITORY='https://github.com/yunmyuki/coursebook'
DOCS=('quickstart.md','privacy.md','release-notes.md','release-quality.md','development.md','third-party.md')
SOURCE_FILES=('README.md','LICENSE','.gitignore','requirements.txt','requirements-desktop.txt','requirements-lock.txt','requirements-dev.txt','desktop_main.py','package.json')
SOURCE_TOOLS=('build_desktop.py','create_release.py','release_demo.py','release_browser.cjs','publish_release.py')
FORBIDDEN={'.env','.env.local','settings.json','library.json','course.json','course-data.js'}

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def safe_files(folder):
    files=sorted(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.relative_to(folder).parts)
    for p in files:
        parts=p.relative_to(folder).parts
        if p.is_symlink() or p.name in FORBIDDEN or any(s in ('local-data','.course-cache','input','notes','content','__pycache__') for s in parts):
            raise ValueError('Private or unexpected release file: '+str(p.relative_to(folder)))
    return files

def copy(source,dest):
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)

def prepare():
    if not(APP/'CourseCompiler.exe').is_file():raise RuntimeError('Build the EXE first')
    notices=APP/'THIRD-PARTY-NOTICES'
    names={'pywebview','pyinstaller','pythonnet','clr-loader','cffi','pypdf','pdfplumber','pdfminer-six','pdfminer.six','pypdfium2','pypdfium2-raw','python-pptx','pillow','lxml','bottle','proxy-tools','cryptography','charset-normalizer','numpy','typing-extensions','pycparser','packaging','setuptools','xlsxwriter'}
    components={}
    for dist in importlib.metadata.distributions(path=[str(ROOT/'.build-deps'),str(Path(sys.prefix)/'Lib/site-packages')]):
        name=dist.metadata.get('Name','').lower().replace('_','-')
        if name not in names:continue
        components[name]=dist.version
        for file in dist.files or []:
            p=Path(dist.locate_file(file))
            if p.is_file() and p.suffix not in ('.py','.pyc') and any(s in p.name.lower() for s in ('license','copying','notice')):
                copy(p,notices/(name+'-'+dist.version)/p.name)
    for name in ('LICENSE.txt','LICENSE'):
        if (Path(sys.prefix)/name).is_file():copy(Path(sys.prefix)/name,notices/('Python-'+name))
    (APP/'components.json').write_text(json.dumps({'python':sys.version.split()[0],'packages':components},indent=2),'utf-8')
    source=ROOT/'build/office-component'
    manifest=json.loads((ROOT/'tmp/office-download/manifest.json').read_text('utf-8'))
    original=Path(manifest['file'])
    if not original.is_file() or digest(original)!=manifest['sha256']:raise RuntimeError('Office download checksum mismatch')
    removed=[];count=0
    for p in sorted(source.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(source);parts=rel.parts
        # Only optional help, gallery, templates, spelling dictionaries and MSI.
        # Keep rendering libraries, fonts, filters, all locales and all licenses.
        omit=p.suffix=='.msi' or parts[0]=='help' or parts[:2] in (('share','gallery'),('share','template')) or (len(parts)>2 and parts[:2]==('share','extensions') and parts[2].startswith('dict-'))
        if omit:removed.append(rel.as_posix());continue
        copy(p,OFFICE/rel);count+=1
    (OFFICE/'component-source.json').write_text(json.dumps({'source':manifest['source'],'sha256':manifest['sha256'],'sourceCode':'https://download.documentfoundation.org/libreoffice/src/26.8.0/','packaging':'Headless subset; shipped binary files are unmodified.','omitted':removed},ensure_ascii=False,indent=2),'utf-8')
    for f in ('program/soffice.exe','LICENSE.html','license.txt','NOTICE'):
        if not(OFFICE/f).is_file():raise RuntimeError('Required Office file missing: '+f)
    print(json.dumps({'officeFiles':count,'omittedFiles':len(removed),'officeBytes':sum(p.stat().st_size for p in OFFICE.rglob('*') if p.is_file())}),flush=True)

def public_source():
    dest=OUT/'github-source'
    if dest.exists():raise RuntimeError('Source staging already exists; choose a new version or review it before replacing.')
    for name in SOURCE_FILES:copy(ROOT/name,dest/name)
    for dirname in ('course_compiler','web'):
        for p in (ROOT/dirname).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:copy(p,dest/p.relative_to(ROOT))
    for p in (ROOT/'tests').glob('test_*.py'):copy(p,dest/p.relative_to(ROOT))
    for name in ('reader.test.cjs','runtime.cjs'):copy(ROOT/'tests'/name,dest/'tests'/name)
    for name in SOURCE_TOOLS:copy(ROOT/'tools'/name,dest/'tools'/name)
    for name in DOCS:copy(ROOT/'docs'/name,dest/'docs'/name)
    for p in (ROOT/'docs/images').glob('*'):copy(p,dest/'docs/images'/p.name)
    for p in (ROOT/'.github').rglob('*'):
        if p.is_file():copy(p,dest/p.relative_to(ROOT))
    # A fresh checkout needs a writable directory for unittest temporary fixtures.
    copy(ROOT/'tmp/.gitkeep',dest/'tmp/.gitkeep')
    return dest

def archive(name,entries):
    path=OUT/name
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p,rel in entries:z.write(p,rel)
    with zipfile.ZipFile(path) as z:
        bad=z.testzip()
        if bad:raise RuntimeError('ZIP integrity failure: '+bad)
    return {'file':name,'bytes':path.stat().st_size,'sha256':digest(path),'url':REPOSITORY+'/releases/download/v'+__version__+'/'+name}

def package():
    for name in ('exe-self-test.json','exe-window-test.json','browser-smoke.json','python-tests.json'):
        report=json.loads((OUT/name).read_text('utf-8-sig'))
        if not report.get('ok'):raise RuntimeError('Release quality gate failed: '+name)
    if not json.loads((OUT/'exe-self-test.json').read_text('utf-8'))['officeRoundTrip']:raise RuntimeError('PPT validation required')
    for name in ('README.md','LICENSE'):copy(ROOT/name,APP/name)
    for name in DOCS:copy(ROOT/'docs'/name,APP/'docs'/name)
    for p in (ROOT/'docs/images').glob('*'):copy(p,APP/'docs/images'/p.name)
    (APP/'开始使用.txt').write_text('Course Compiler '+__version__+'\n\n解压整个文件夹，再双击 CourseCompiler.exe。不要只移动 exe。\n使用说明：docs/quickstart.md\n轻量版：处理 PDF；PPT/PPTX 需安装 LibreOffice 或添加 Office 组件。\n完整版：已包含 PPT/PPTX 转换组件。\n自己的模型 API 和密钥需在应用中配置；已有课程阅读和笔记无需联网。\n数据目录：%LOCALAPPDATA%\\Course Compiler\n更新时替换程序文件夹，保留数据目录。\n','utf-8-sig')
    files=safe_files(APP);source=public_source();source_files=safe_files(source)
    full=[(p,'CourseCompiler/'+p.relative_to(APP).as_posix()) for p in files]
    lite=[(p,n) for p,n in full if not p.is_relative_to(OFFICE)]
    office=[(p,n) for p,n in full if p.is_relative_to(OFFICE)]
    office.append((APP/'开始使用.txt','CourseCompiler/开始使用.txt'))
    demo=OUT/'CourseCompiler-Demo.zip'
    if not demo.is_file():raise RuntimeError('Generate the public demo before packaging')
    artifacts=[{'file':demo.name,'bytes':demo.stat().st_size,'sha256':digest(demo),'url':REPOSITORY+'/releases/download/v'+__version__+'/'+demo.name}]
    for name,entries in [('CourseCompiler-Windows-x64.zip',full),('CourseCompiler-Windows-x64-Lite.zip',lite),('CourseCompiler-Office-Windows-x64.zip',office),('CourseCompiler-Source.zip',[(p,'coursebook/'+p.relative_to(source).as_posix()) for p in source_files])]:
        item=archive(name,entries);artifacts.append(item);print(json.dumps(item),flush=True)
    (OUT/'SHA256SUMS.txt').write_text(''.join(a['sha256']+'  '+a['file']+'\n' for a in artifacts),'utf-8')
    (OUT/'release-manifest.json').write_text(json.dumps({'version':__version__,'repository':REPOSITORY,'published':False,'artifacts':artifacts},indent=2),'utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','package']);args=parser.parse_args()
    {'prepare':prepare,'package':package}[args.stage]()
