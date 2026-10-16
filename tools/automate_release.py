"""One-command, resumable Windows QA/package + verified Windows/macOS publication.

python tools/automate_release.py --base-version 2.2.0 --publish
python tools/automate_release.py --status
Full command output stays in release/<version>/logs; only stage summaries print.
"""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
from release_support import digest,save,github_env,gh_json
import create_release as release

OUT=ROOT/'release'/__version__
STATE=OUT/'automation-state.json'

def input_signature():
    paths=[ROOT/p for p in release.SOURCE_FILES]
    paths += [ROOT/'tools'/p for p in release.SOURCE_TOOLS]
    paths += [p for folder in ('course_compiler','web','tests','.github') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'docs'/p for p in release.DOCS if p!='release-quality.md']
    return hashlib.sha256(''.join(str(p.relative_to(ROOT))+digest(p) for p in sorted(set(paths))).encode()).hexdigest()

def scan_source(folder):
    files=release.safe_files(folder);bad=[]
    patterns=(rb'gh[pousr]_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{40,}',rb'\bsk-[A-Za-z0-9]{24,}',rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    for path in files:
        if path.suffix.lower() in ('.py','.js','.cjs','.json','.md','.yml','.yaml','.txt','.html'):
            if any(re.search(p,path.read_bytes()) for p in patterns):bad.append(str(path.relative_to(folder)))
    if bad:raise RuntimeError('Public source privacy scan failed (paths only): '+', '.join(bad))
    return {'ok':True,'files':len(files),'method':'allowlist and credential-pattern scan; user credential files never read','credentialMatchesOrPrivateFiles':[]}

def isolated_source_copy(source,destination):
    """Regression fixtures may write caches; never run them in the public payload."""
    destination=Path(destination)
    if destination.exists():raise ValueError('Test checkout must be fresh')
    for path in release.safe_files(source):
        target=destination/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    return destination

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--publish',action='store_true');ap.add_argument('--base-version',default='2.2.0');ap.add_argument('--status',action='store_true');args=ap.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.base_version):ap.error('Invalid base version')
    state=json.loads(STATE.read_text('utf-8')) if STATE.exists() else {'version':__version__,'steps':{}}
    if args.status:
        print(json.dumps({k:v for k,v in state.items() if k!='steps'},ensure_ascii=False));print('Passed stages: '+', '.join(state['steps']));return
    if sys.version_info[:2]!=(3,12):raise RuntimeError('Release runtime must be Python 3.12')
    if json.loads((ROOT/'package.json').read_text())['version']!=__version__:raise RuntimeError('Version mismatch')
    sig=input_signature()
    if state.get('input')!=sig:
        if state.get('published'):raise RuntimeError('Published version is immutable; bump version first')
        state={'version':__version__,'input':sig,'steps':{}}
    OUT.mkdir(parents=True,exist_ok=True);logs=OUT/'logs';logs.mkdir(exist_ok=True)
    env=dict(os.environ);env['PYTHONPATH']=os.pathsep.join([str(ROOT/'.build-deps'),str(ROOT)])
    env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
    env['TEMP']=env['TMP']=str(ROOT/'tmp');env['RELEASE_PYTHON']=env['TEST_PYTHON']=sys.executable
    def command(name,args,cwd=ROOT):
        with (logs/(name+'.log')).open('w',encoding='utf-8') as log:
            p=subprocess.run(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=7200 if name=='publish' else 2400)
        if p.returncode:raise RuntimeError(f'{name} failed; see {logs/(name+".log")}')
    def step(name,action,outputs=()):
        previous=state['steps'].get(name)
        if previous and all(Path(p).is_file() and digest(p)==previous['outputs'].get(str(p)) for p in outputs):return
        state.update(stage=name,status='running');save(STATE,state);print('START '+name,flush=True);t=time.monotonic()
        action();state['steps'][name]={'seconds':round(time.monotonic()-t,2),'outputs':{str(p):digest(p) for p in outputs}}
        save(STATE,state);print('PASS '+name,flush=True)
    def tests(name,cwd):
        if name=='source-tests':cwd=isolated_source_copy(cwd,ROOT/'tmp'/('public-source-qa-'+str(time.time_ns())))
        command(name,[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],cwd)
        text=(logs/(name+'.log')).read_text('utf-8');match=re.search(r'Ran (\d+) tests',text)
        if not match:raise RuntimeError('Missing unittest summary')
        save(OUT/(name+'.json'),{'ok':True,'version':__version__,'tests':int(match[1]),'log':'logs/'+name+'.log'})
    def source_stage():
        dest=OUT/'github-source'
        if dest.exists():dest.rename(OUT/('source-previous-'+str(time.time_ns())))
        release.public_source();save(OUT/'source-privacy-check.json',scan_source(dest))
    def quality():
        count=json.loads((OUT/'python-tests.json').read_text())['tests']
        (ROOT/'docs/release-quality.md').write_text(f'''# Coursebook {__version__} 发行质量记录

由自动化发布入口生成。日期：{time.strftime('%Y-%m-%d')}。

- 工作区：{count} 项 Python 回归通过；JavaScript 语法与阅读器测试通过。
- Windows 成品：独立数据目录中的原生窗口、DPAPI、随包 ONNX 模型推理、PDF、PPTX/PPT 转换测试通过。
- 浏览器成品：课程导入、双语阅读、笔记持久化、新手引导、清洗、正文修改、静态导出及离线阅读通过。
- 发行门禁另外要求公开源码副本回归、隐私扫描、Lite ZIP 解压后的窗口与模型自检、所有压缩包完整性和 SHA256。
- GitHub 发布门禁核对实际远端附件大小与 SHA256、同一提交的源码 CI；失败则保留草稿。
- macOS arm64 / x86_64 在 GitHub 原生主机分别构建测试。独立 Mac Release 的 quality 报告及构建日志是实际验收依据。

测试使用隔离夹具与模拟服务，不调用真实付费 OCR，不代表所有模型、讲义或硬件的准确率。Windows 未 Authenticode 签名，Mac 未 Developer ID 签名或公证。

本轮改善源文件高清区域裁剪、跨行段落、多栏阅读顺序、原生表格物理定位和缓存兼容。算法说明见 [解析精度改进](parser-precision.md)。
''',encoding='utf-8')
    try:
        if args.publish:
            def preflight():
                auth=github_env();repo=gh_json(auth,'api','repos/'+release.REPOSITORY.split('github.com/')[1]);assert repo['permissions']['push']
                sha=gh_json(auth,'api','repos/yunmyuki/coursebook/commits/main')['sha']
                (OUT/'base-commit.txt').write_text(sha,'utf-8')
            step('github-preflight',preflight,[OUT/'base-commit.txt'])
        step('python-tests',lambda:tests('python-tests',ROOT),[OUT/'python-tests.json'])
        def js():
            for file in ('app','assistant','desktop','review'):command('syntax-'+file,['node','--check','web/'+file+'.js'])
            command('reader-tests',['node','tests/reader.test.cjs'])
            save(OUT/'javascript-tests.json',{'ok':True})
        step('javascript-tests',js,[OUT/'javascript-tests.json'])
        step('build',lambda:command('build',[sys.executable,'tools/build_desktop.py']),[OUT/'app/Coursebook/Coursebook.exe'])
        step('prepare',lambda:command('prepare',[sys.executable,'tools/create_release.py','prepare','--office-archive',str(ROOT/'release'/args.base_version/'Coursebook-Office-Windows-x64.zip')]),[OUT/'app/Coursebook/components.json'])
        step('demo',lambda:command('demo',[sys.executable,'tools/release_demo.py']),[OUT/'Coursebook-Demo.zip'])
        step('windows-qa',lambda:command('windows-qa',[sys.executable,'tools/test_windows_release.py']),[OUT/p for p in ('exe-self-test.json','exe-window-test.json','browser-smoke.json','new-features-smoke.json')])
        step('quality-record',quality,[ROOT/'docs/release-quality.md'])
        step('source-stage',source_stage,[OUT/'source-privacy-check.json',OUT/'github-source/course_compiler/__init__.py'])
        step('source-tests',lambda:tests('source-tests',OUT/'github-source'),[OUT/'source-tests.json'])
        step('package',lambda:command('package',[sys.executable,'tools/create_release.py','package']),[OUT/'SHA256SUMS.txt'])
        step('lite-qa',lambda:command('lite-qa',[sys.executable,'tools/test_windows_release.py','--lite']),[OUT/'lite-self-test.json',OUT/'lite-window-test.json'])
        if args.publish:
            state.update(stage='publish',status='running');save(STATE,state)
            # Publisher performs its own remote checkpoints and hash verification.
            command('publish',[sys.executable,'tools/publish_release.py','--base-version',args.base_version])
            state.update(published=True,releaseUrl='https://github.com/yunmyuki/coursebook/releases/tag/v'+__version__,macReleaseUrl='https://github.com/yunmyuki/coursebook/releases/tag/v'+__version__+'-macos.1')
        state.update(status='complete',stage='complete');save(STATE,state);print(json.dumps({'ok':True,'version':__version__,'published':state.get('published',False),'state':str(STATE)}),flush=True)
    except Exception as e:
        state.update(status='failed',error=str(e));save(STATE,state);print('FAILED: '+str(e),file=sys.stderr,flush=True);raise SystemExit(1)

if __name__=='__main__':main()
