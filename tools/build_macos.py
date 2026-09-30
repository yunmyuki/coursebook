"""Build a native Coursebook.app on each Mac architecture, with offline layout."""
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
from course_compiler.local_layout import install,verify,model_path

def main():
    if sys.platform!='darwin':raise SystemExit('Run this build on macOS.')
    arch=platform.machine()
    if arch not in ('arm64','x86_64'):raise SystemExit('Unsupported architecture')
    out=ROOT/'release/macos'/arch
    out.mkdir(parents=True,exist_ok=True)
    if not model_path().is_file():install()
    model=model_path();verify(model)
    notices=ROOT/'build/macos-notices';notices.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'docs/licenses/PP-DocLayoutV3',notices/'PP-DocLayoutV3',dirs_exist_ok=True)
    shutil.copy2(ROOT/'LICENSE',notices/'Coursebook-LICENSE')
    packages={}
    for dist in importlib.metadata.distributions():
        name=dist.metadata.get('Name','unknown');packages[name]=dist.version
        for file in dist.files or []:
            p=Path(dist.locate_file(file))
            if p.is_file() and any(token in p.name.lower() for token in ('license','copying','notice')) and p.suffix not in ('.py','.pyc'):
                target=notices/(name+'-'+dist.version)/str(file).replace('../','').replace('/', '_')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    (notices/'components.json').write_text(json.dumps({'python':sys.version,'arch':arch,'packages':packages},indent=2))
    for candidate in (Path(sys.base_prefix)/'LICENSE.txt',Path(sys.base_prefix)/'lib/python3.12/LICENSE.txt'):
        if candidate.is_file():shutil.copy2(candidate,notices/'Python-LICENSE.txt');break
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--noupx',
         '--name','Coursebook','--osx-bundle-identifier','com.coursebook.desktop','--target-architecture',arch,
         '--distpath',str(out),'--workpath',str(ROOT/'build/macos-work'), '--specpath',str(ROOT/'build'),
         '--add-data',str(ROOT/'web')+':web','--add-data',str(model)+':models/PP-DocLayoutV3',
         '--add-data',str(notices)+':THIRD-PARTY-NOTICES',
         '--collect-binaries','onnxruntime','--collect-data','onnxruntime',
         '--collect-all','webview','--collect-all','pypdfium2_raw','--hidden-import','webview.platforms.cocoa',
         '--hidden-import','keyring.backends.macOS']
    for module in ('matplotlib','pandas','scipy','torch','IPython','PyQt5','PyQt6','PySide6','tkinter','pytest','jupyter',
                   'onnxruntime.tools','onnxruntime.quantization','onnxruntime.transformers','onnx','clr','pythonnet'):
        cmd+=['--exclude-module',module]
    subprocess.run(cmd+[str(ROOT/'desktop_main.py')],cwd=ROOT,check=True)
    app=out/'Coursebook.app';plist=app/'Contents/Info.plist'
    info=plistlib.loads(plist.read_bytes())
    info.update(CFBundleDisplayName='Coursebook',CFBundleShortVersionString=__version__,CFBundleVersion=__version__,
                LSMinimumSystemVersion='14.0' if arch=='arm64' else '15.0',
                NSHighResolutionCapable=True,NSAppTransportSecurity={'NSAllowsLocalNetworking':True})
    plist.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)

if __name__=='__main__':main()
