"""Validate real Windows binaries with isolated, synthetic workspaces."""
import argparse,json,os,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--lite',action='store_true');args=parser.parse_args()
    out=ROOT/'release'/__version__;test=ROOT/'tmp'/('release-'+__version__+('-lite' if args.lite else '-full'))
    test.mkdir(parents=True,exist_ok=True)
    if args.lite:
        with zipfile.ZipFile(out/'Coursebook-Windows-x64-Lite.zip') as z:
            assert z.testzip() is None
            z.extractall(test/'unpacked')
        exe=test/'unpacked/Coursebook/Coursebook.exe'
    else:exe=out/'app/Coursebook/Coursebook.exe'
    for mode in ('self-test','window-test'):
        report=out/(('lite-' if args.lite else 'exe-')+mode+'.json')
        command=[str(exe),'--'+mode,str(report),'--data-dir',str(test/mode)]
        if mode=='self-test' and not args.lite:command.append('--test-office')
        subprocess.run(command,check=True,timeout=240)
        value=json.loads(report.read_text('utf-8'));assert value['ok'],value
        if mode=='self-test':assert value['layoutInference'] and value['secureKeyRoundTrip']
        print('Passed '+report.name,flush=True)
    if args.lite:return
    server=subprocess.Popen([str(exe),'--serve-only','--port','8772','--data-dir',str(test/'reader')])
    env=dict(os.environ,RELEASE_PYTHON=sys.executable,TEST_PYTHON=sys.executable)
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                with opener.open('http://127.0.0.1:8772/api/status',timeout=2) as r:
                    status=json.load(r)
                if Path(status['dataPath']).resolve()==(test/'reader').resolve():break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('Isolated packaged server did not start')
        subprocess.run(['node','tools/release_browser.cjs'],cwd=ROOT,env=env,check=True,timeout=180)
    finally:server.terminate();server.wait(timeout=20)
    env['COURSEBOOK_TEST_EXE']=str(exe)
    subprocess.run(['node','tests/onboarding_cleanup_browser.cjs'],cwd=ROOT,env=env,check=True,timeout=180)
    (out/'new-features-smoke.json').write_text(json.dumps({'ok':True,'frozenServer':True,'onboarding':True,'cleanup':True,'editing':True,'offline':True}),encoding='utf-8')

if __name__=='__main__':main()
