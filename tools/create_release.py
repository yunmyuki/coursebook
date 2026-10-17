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
APP=OUT/'app/Coursebook'
OFFICE=APP/'_internal/office'
REPOSITORY='https://github.com/yunmyuki/coursebook'
DOCS=('quickstart.md','privacy.md','release-notes.md','release-quality.md','development.md','third-party.md','hybrid-parsing-2026-09-30.md','hybrid-validation-2026-09-30.md','macos.md','iteration-onboarding-cleanup-editing.md','parser-precision.md','release-automation.md','windows-signing.md')
SOURCE_FILES=('README.md','LICENSE','.gitignore','requirements.txt','requirements-desktop.txt','requirements-lock.txt','requirements-dev.txt','requirements-layout.txt','requirements-macos.txt','desktop_main.py','package.json')
SOURCE_TOOLS=('build_desktop.py','test_windows_release.py','build_macos.py','test_macos_release.py','publish_macos.py','assemble_release.py','create_release.py','release_demo.py','release_browser.cjs','publish_release.py','benchmark_hybrid.py','benchmark_parser_precision.py','automate_release.py','release_support.py','sign_windows.py','audit_release_privacy.py')
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

def prepare(office_archive=None):
    if not(APP/'Coursebook.exe').is_file():raise RuntimeError('Build the EXE first')
    notices=APP/'THIRD-PARTY-NOTICES'
    names={'pywebview','pyinstaller','pythonnet','clr-loader','cffi','pypdf','pdfplumber','pdfminer-six','pdfminer.six','pypdfium2','pypdfium2-raw','python-pptx','pillow','lxml','bottle','proxy-tools','cryptography','charset-normalizer','numpy','typing-extensions','pycparser','packaging','setuptools','xlsxwriter','onnxruntime','coloredlogs','flatbuffers','protobuf','sympy','humanfriendly','mpmath'}
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
    from course_compiler.local_layout import verify
    verify(APP/'_internal/models/PP-DocLayoutV3/inference.onnx')
    for p in (ROOT/'docs/licenses/PP-DocLayoutV3').glob('*'):copy(p,notices/'PP-DocLayoutV3'/p.name)
    if office_archive:
        archive_path=Path(office_archive).resolve()
        checksums=dict((line.split()[1],line.split()[0]) for line in (archive_path.parent/'SHA256SUMS.txt').read_text().splitlines())
        if digest(archive_path)!=checksums.get(archive_path.name):raise RuntimeError('Prior Office archive checksum mismatch')
        with zipfile.ZipFile(archive_path) as z:
            if z.testzip():raise RuntimeError('Prior Office archive is damaged')
            for info in z.infolist():
                prefix=next((p for p in ('Coursebook/_internal/office/','CourseCompiler/_internal/office/') if info.filename.startswith(p)),None)
                if prefix is None or info.is_dir():continue
                target=(OFFICE/info.filename[len(prefix):]).resolve()
                if not target.is_relative_to(OFFICE.resolve()):raise RuntimeError('Invalid Office archive path')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info))
        for name in ('program/soffice.exe','LICENSE.html','license.txt','NOTICE','component-source.json'):
            if not (OFFICE/name).is_file():raise RuntimeError('Office file missing: '+name)
        print('Reused SHA256-verified Office component; original source metadata retained.',flush=True)
        return
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
    for name in ('reader.test.cjs','runtime.cjs','onboarding_cleanup_browser.cjs','iteration_server.py'):copy(ROOT/'tests'/name,dest/'tests'/name)
    for name in SOURCE_TOOLS:copy(ROOT/'tools'/name,dest/'tools'/name)
    for name in DOCS:copy(ROOT/'docs'/name,dest/'docs'/name)
    for p in (ROOT/'docs/licenses').rglob('*'):
        if p.is_file():copy(p,dest/p.relative_to(ROOT))
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
    for name in ('exe-self-test.json','exe-window-test.json','browser-smoke.json','new-features-smoke.json','python-tests.json','source-tests.json','source-privacy-check.json'):
        report=json.loads((OUT/name).read_text('utf-8-sig'))
        if not report.get('ok'):raise RuntimeError('Release quality gate failed: '+name)
    if not json.loads((OUT/'exe-self-test.json').read_text('utf-8'))['officeRoundTrip']:raise RuntimeError('PPT validation required')
    if not json.loads((OUT/'exe-self-test.json').read_text('utf-8')).get('layoutInference'):raise RuntimeError('Bundled ONNX inference validation required')
    for name in ('README.md','LICENSE'):copy(ROOT/name,APP/name)
    for name in DOCS:copy(ROOT/'docs'/name,APP/'docs'/name)
    for p in (ROOT/'docs/images').glob('*'):copy(p,APP/'docs/images'/p.name)
    (APP/'开始使用.txt').write_text('coursebook '+__version__+'\n\n解压整个文件夹，再双击 Coursebook.exe。不要只移动 exe。\n使用说明：docs/quickstart.md\n轻量版：处理 PDF；PPT/PPTX 需安装 LibreOffice 或添加 Office 组件。\n完整版：已包含 PPT/PPTX 转换组件。\n自己的模型 API 和密钥需在应用中配置；已有课程阅读和笔记无需联网。\n数据目录：%LOCALAPPDATA%\\Course Compiler\n更新时替换程序文件夹，保留数据目录。\n','utf-8-sig')
    files=safe_files(APP);source=OUT/'github-source'
    if not source.is_dir():raise RuntimeError('Stage and validate public_source() before packaging')
    source_files=safe_files(source)
    full=[(p,'Coursebook/'+p.relative_to(APP).as_posix()) for p in files]
    lite=[(p,n) for p,n in full if not p.is_relative_to(OFFICE)]
    office=[(p,n) for p,n in full if p.is_relative_to(OFFICE)]
    office.append((APP/'开始使用.txt','Coursebook/开始使用.txt'))
    demo=OUT/'Coursebook-Demo.zip'
    if not demo.is_file():raise RuntimeError('Generate the public demo before packaging')
    artifacts=[{'file':demo.name,'bytes':demo.stat().st_size,'sha256':digest(demo),'url':REPOSITORY+'/releases/download/v'+__version__+'/'+demo.name}]
    for name,entries in [('Coursebook-Windows-x64.zip',full),('Coursebook-Windows-x64-Lite.zip',lite),('Coursebook-Office-Windows-x64.zip',office),('Coursebook-Source.zip',[(p,'coursebook/'+p.relative_to(source).as_posix()) for p in source_files])]:
        item=archive(name,entries);artifacts.append(item);print(json.dumps(item),flush=True)
    (OUT/'SHA256SUMS.txt').write_text(''.join(a['sha256']+'  '+a['file']+'\n' for a in artifacts),'utf-8')
    (OUT/'release-manifest.json').write_text(json.dumps({'version':__version__,'repository':REPOSITORY,'published':False,'artifacts':artifacts},indent=2),'utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','package']);parser.add_argument('--office-archive',type=Path);args=parser.parse_args()
    if args.stage=='prepare':prepare(args.office_archive)
    else:package()
