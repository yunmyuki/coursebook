"""Audit exact release archives and launch the real EXE with a fresh workspace.
Only counts, relative paths and hashes are recorded; never dump personal notes.
"""
import argparse,json,os,socket,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from release_support import digest,save
from course_compiler import __version__

def private_member(name):
    parts=PurePosixPath(name.replace('\\','/')).parts;lower=[p.lower() for p in parts]
    if '..' in parts or name.startswith(('/','\\')):return True
    if not lower:return False
    if lower[-1] in ('library.json','settings.json','course.json','course-data.js','onboarding.json','.env','cookies','history','preferences'):return True
    if lower[-1].startswith('.env.'):return True
    if any(p in ('local-data','.course-cache','courses','notes','input','assistant','ebwebview','browsermetrics') for p in lower):return True
    # _internal/webview is the pywebview dependency, not a browser user profile.
    if 'webview' in lower:
        i=lower.index('webview')
        if i==0 or lower[i-1]!='_internal':return True
    return False

def audit_archive(path):
    with zipfile.ZipFile(path) as z:
        bad=[i.filename for i in z.infolist() if private_member(i.filename)]
        if bad:raise ValueError('Private data paths found in '+path.name+': '+', '.join(bad[:10]))
        return {'file':path.name,'bytes':path.stat().st_size,'sha256':digest(path),'entries':len(z.infolist()),'privatePaths':0}

def fresh_launch(exe,root):
    root=Path(root).resolve()
    if root.exists():raise ValueError('Fresh-workspace test requires a new directory')
    root.mkdir(parents=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    proc=subprocess.Popen([str(Path(exe).resolve()),'--serve-only','--port',str(port),'--data-dir',str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for _ in range(100):
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:status=json.load(response)
                if Path(status['dataPath']).resolve()!=root:raise RuntimeError('Wrong server workspace')
                if status['courses'] or status['files']:raise RuntimeError('Fresh application contains unexpected course material')
                if any((root/'notes').glob('*.json')):raise RuntimeError('Fresh application contains personal notes')
                return {'ok':True,'version':status['version'],'courses':0,'files':0,'notes':0,'isolatedWorkspace':True}
            except OSError:
                if proc.poll() is not None:raise RuntimeError('EXE exited before fresh-workspace verification')
                time.sleep(.2)
        raise RuntimeError('Fresh-workspace startup timed out')
    finally:proc.terminate();proc.wait(timeout=20)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--version',default=__version__);ap.add_argument('--verify-github',action='store_true');args=ap.parse_args()
    import re
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version):ap.error('Invalid version')
    out=ROOT/'release'/args.version
    archives=[audit_archive(out/name) for name in ('Coursebook-Windows-x64.zip','Coursebook-Windows-x64-Lite.zip','Coursebook-Source.zip')]
    import hashlib
    for name in ('Coursebook-Windows-x64.zip','Coursebook-Windows-x64-Lite.zip'):
        with zipfile.ZipFile(out/name) as archive:
            if hashlib.sha256(archive.read('Coursebook/Coursebook.exe')).hexdigest()!=digest(out/'app/Coursebook/Coursebook.exe'):raise RuntimeError('Test executable differs from released ZIP')
    if args.verify_github:
        from release_support import github_env,gh_json,REPO
        r=gh_json(github_env(),'api',f'repos/{REPO}/releases/tags/v{args.version}');remote={a['name']:a for a in r['assets']}
        for a in archives:
            match=remote.get(a['file'],{})
            if match.get('digest')!='sha256:'+a['sha256'] or match.get('size')!=a['bytes']:raise RuntimeError('GitHub artifact differs from audited ZIP')
    report={'ok':True,'version':args.version,'githubMatched':args.verify_github,'archives':archives,'freshLaunch':fresh_launch(out/'app/Coursebook/Coursebook.exe',ROOT/'tmp'/('privacy-fresh-'+str(time.time_ns())))}
    save(out/'privacy-audit.json',report);print(json.dumps({'ok':True,'githubMatched':args.verify_github,'freshLaunch':report['freshLaunch']}))

if __name__=='__main__':main()
