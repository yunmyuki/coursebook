"""Exercise the real Mac bundle before making the distributable ZIP."""
import hashlib,json,os,platform,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__

def main():
    arch=platform.machine();out=ROOT/'release/macos'/arch
    app=out/'Coursebook.app';binary=app/'Contents/MacOS/Coursebook'
    test=ROOT/'tmp'/('macos-'+arch);test.mkdir(parents=True,exist_ok=True)
    # Source tests and the frozen app have different code-signing identities.
    # Remove only the synthetic source-test item on disposable hosted runners,
    # so the actual app creates and verifies its own Keychain access policy.
    if os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted':
        from keyring.backends.macOS import Keyring
        from keyring.errors import PasswordDeleteError
        from course_compiler.mac_security import SERVICE,ACCOUNT
        try:Keyring().delete_password(SERVICE,ACCOUNT)
        except PasswordDeleteError:pass
    for mode in ('self-test','window-test'):
        report=out/(mode+'.json')
        subprocess.run([str(binary),'--'+mode,str(report),'--data-dir',str(test/mode)],check=True,timeout=180)
        assert json.loads(report.read_text())['ok'],mode
    # The existing integration test imports a synthetic course and exercises export/file://.
    subprocess.run(['gh','release','download','v2.1.0','--repo','yunmyuki/coursebook','--pattern','CourseCompiler-Demo.zip',
                    '--dir',str(ROOT/'release'/__version__)],check=True)
    server=subprocess.Popen([str(binary),'--serve-only','--port','8772','--data-dir',str(test/'reader')])
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            try:
                with opener.open('http://127.0.0.1:8772/api/status',timeout=2):break
            except OSError:time.sleep(.5)
        else:raise RuntimeError('Bundled server did not start')
        subprocess.run(['node','tools/release_browser.cjs'],cwd=ROOT,check=True,timeout=180)
    finally:
        server.terminate();server.wait(timeout=15)
    shutil.copy2(ROOT/'release'/__version__/'browser-smoke.json',out/'browser-smoke.json')
    shutil.copy2(ROOT/'docs/macos.md',out/'README-macOS.md')
    package=out/('Coursebook-macOS-'+arch+'.zip')
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(package)],check=True)
    # Validate the extracted deliverable, including its executable bits and signature.
    unpacked=test/'unpacked';subprocess.run(['ditto','-x','-k',str(package),str(unpacked)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(unpacked/'Coursebook.app')],check=True)
    final_report=out/'unpacked-self-test.json'
    subprocess.run([str(unpacked/'Coursebook.app/Contents/MacOS/Coursebook'),'--self-test',str(final_report),
                    '--data-dir',str(test/'unpacked-data')],check=True,timeout=180)
    assert json.loads(final_report.read_text())['ok']
    with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    (out/('SHA256SUMS-'+arch+'.txt')).write_text(digest+'  '+package.name+'\n')
    (out/('quality-'+arch+'.json')).write_text(json.dumps({'ok':True,'arch':arch,'macOS':platform.mac_ver()[0],
        'version':__version__,'bytes':package.stat().st_size,'sha256':digest,'frozenSelfTest':True,
        'keychain':True,'nativeWindow':True,'browserFlow':True,'unpackedSelfTest':True,
        'developerIdSigned':False,'notarized':False,'bundledOffice':False},indent=2))

if __name__=='__main__':main()
