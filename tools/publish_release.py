"""Resumable publication with local gates, remote SHA256 checks and native Mac CI.
Large ZIPs are reconstructed on GitHub from verified old bytes plus a small patch.
"""
import argparse,json,os,re,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
from release_support import REPO,digest,save,run,github_env,gh_json
from assemble_release import create
OUT=ROOT/'release'/__version__;TAG='v'+__version__

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base-version',required=True);args=ap.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.base_version):ap.error('Invalid base version')
    manifest=json.loads((OUT/'release-manifest.json').read_text('utf-8'))
    for item in manifest['artifacts']:
        p=OUT/item['file']
        if p.stat().st_size!=item['bytes'] or digest(p)!=item['sha256']:raise RuntimeError('Local asset hash mismatch: '+p.name)
    for name in ('exe-self-test','exe-window-test','browser-smoke','new-features-smoke','python-tests','source-tests','source-privacy-check','javascript-tests','lite-self-test','lite-window-test'):
        if not json.loads((OUT/(name+'.json')).read_text('utf-8-sig'))['ok']:raise RuntimeError('Quality gate: '+name)
    env=github_env();state_path=OUT/'publish-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    def record(**values):state.update(values);save(state_path,state)
    def gh(*cmd):return run(['gh',*cmd],env).stdout
    def api(path):return gh_json(env,'api',path)
    git=['git','-c','credential.helper=','-c','credential.helper=!gh auth git-credential']
    checkout=OUT/'publish-repo';remote='https://github.com/'+REPO+'.git'
    expected=(OUT/'base-commit.txt').read_text().strip()
    if 'head' not in state:
        if not checkout.exists():run(git+['clone','--branch','main','--single-branch',remote,str(checkout)],env)
        head=run(['git','rev-parse','HEAD'],env,checkout).stdout.strip()
        if head!=expected:raise RuntimeError('Unexpected checkout head; publication stopped')
        if api('repos/'+REPO+'/commits/main')['sha']!=expected:raise RuntimeError('Remote main changed; integrate before publishing')
        for p in (OUT/'github-source').rglob('*'):
            if p.is_file():
                target=checkout/p.relative_to(OUT/'github-source');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        run(['git','config','user.name','yunmyuki'],env,checkout);run(['git','config','user.email','yunmyuki@users.noreply.github.com'],env,checkout)
        run(['git','add','--all'],env,checkout);run(['git','commit','-m','Release Coursebook '+__version__],env,checkout)
        record(head=run(['git','rev-parse','HEAD'],env,checkout).stdout.strip())
    head=state['head'];current=api('repos/'+REPO+'/commits/main')['sha']
    if current==expected:run(git+['push','origin','HEAD:main'],env,checkout)
    elif current!=head:raise RuntimeError('Remote main differs from prepared release; no overwrite')
    tags=run(git+['ls-remote','--tags',remote,'refs/tags/'+TAG],env).stdout.strip()
    if tags and tags.split()[0]!=head:raise RuntimeError('Release tag points to another commit')
    if not tags:run(git+['push','origin',head+':refs/tags/'+TAG],env,checkout)
    def release():
        p=run(['gh','api','repos/'+REPO+'/releases/tags/'+TAG],env,check=False)
        if p.returncode==0:return json.loads(p.stdout)
        return next((r for r in api('repos/'+REPO+'/releases') if r['tag_name']==TAG),None)
    rel=release()
    if rel is None:
        gh('release','create',TAG,'--repo',REPO,'--verify-tag','--draft','--title','Coursebook '+__version__,'--notes-file',str(ROOT/'docs/release-notes.md'));rel=release()
    def upload(path):
        r=release();old=next((a for a in r['assets'] if a['name']==path.name),None)
        if old:
            if old['size']==path.stat().st_size and old.get('digest')=='sha256:'+digest(path):return
            raise RuntimeError('Existing remote asset differs: '+path.name)
        if not r['draft']:raise RuntimeError('Refusing to modify published release')
        print('Uploading '+path.name,flush=True)
        direct={k:v for k,v in env.items() if k.lower() not in ('http_proxy','https_proxy','all_proxy')}
        run(['gh','release','upload',TAG,str(path),'--repo',REPO],direct)
    def dispatch(workflow,key,fields=(),ref='main'):
        if state.get(key):return state[key]
        before={r['databaseId'] for r in gh_json(env,'run','list','--repo',REPO,'--workflow',workflow,'--json','databaseId','--limit','30')}
        gh('workflow','run',workflow,'--repo',REPO,'--ref',ref,*fields)
        for _ in range(12):
            runs=gh_json(env,'run','list','--repo',REPO,'--workflow',workflow,'--commit',head,'--event','workflow_dispatch','--json','databaseId','--limit','30')
            found=[r['databaseId'] for r in runs if r['databaseId'] not in before]
            if found:record(**{key:found[0]});return found[0]
            time.sleep(5)
        raise RuntimeError('Workflow dispatched but run ID not found: '+workflow)
    def wait_run(run_id,label):
        previous=None
        for _ in range(80):
            r=api(f'repos/{REPO}/actions/runs/{run_id}');status=(r['status'],r['conclusion'])
            if status!=previous:print(label+': '+str(status),flush=True);previous=status
            if r['head_sha']!=head:raise RuntimeError('Workflow source commit mismatch')
            if r['status']=='completed':
                if r['conclusion']!='success':raise RuntimeError(label+' failed: '+r['html_url'])
                return
            time.sleep(30)
        raise RuntimeError(label+' still pending; rerun to resume')
    mac=dispatch('macos-release.yml','macBuild')
    if rel['draft']:
        base=ROOT/'release'/args.base_version;base_manifest=json.loads((base/'release-manifest.json').read_text())
        bases=[base/n for n in ('Coursebook-Windows-x64-Lite.zip','Coursebook-Office-Windows-x64.zip')]
        for p in bases:
            expected_item=next(x for x in base_manifest['artifacts'] if x['file']==p.name)
            if digest(p)!=expected_item['sha256']:raise RuntimeError('Base archive hash mismatch')
        targets=[OUT/x['file'] for x in manifest['artifacts'] if x['file'].startswith(('Coursebook-Windows','Coursebook-Office'))]
        recipe=OUT/'assembly'
        if not state.get('recipeReady'):
            create(bases,targets,recipe)
            with (recipe/'assembly-patch.bin').open('rb') as stream:
                i=0
                while chunk:=stream.read(16*1024*1024):
                    (recipe/f'assembly-patch.bin.part{i:04d}').write_bytes(chunk);i+=1
            record(recipeReady=True)
        for p in [recipe/'assembly-manifest.json',*sorted(recipe.glob('assembly-patch.bin.part*'))]:upload(p)
        assembly=dispatch('assemble-release.yml','assemblyRun',('-f','base_tag=v'+args.base_version,'-f','target_tag='+TAG),ref=TAG)
        for item in manifest['artifacts']:
            if not item['file'].startswith(('Coursebook-Windows','Coursebook-Office')):upload(OUT/item['file'])
        for p in (OUT/'SHA256SUMS.txt',ROOT/'docs/release-quality.md'):upload(p)
        wait_run(assembly,'Windows archive assembly')
    for _ in range(80):
        checks=gh_json(env,'run','list','--repo',REPO,'--workflow','checks.yml','--commit',head,'--json','status,conclusion')
        if checks and all(r['status']=='completed' for r in checks):
            if any(r['conclusion']!='success' for r in checks):raise RuntimeError('Source CI failed')
            break
        time.sleep(15)
    else:raise RuntimeError('Source CI pending')
    remote_assets={a['name']:a for a in release()['assets']}
    assets=[OUT/i['file'] for i in manifest['artifacts']]+[OUT/'SHA256SUMS.txt',ROOT/'docs/release-quality.md']
    for p in assets:
        a=remote_assets.get(p.name,{})
        if a.get('size')!=p.stat().st_size or a.get('digest')!='sha256:'+digest(p):raise RuntimeError('Remote hash/size mismatch: '+p.name)
    if release()['draft']:
        for name in remote_assets:
            if name=='assembly-manifest.json' or name.startswith('assembly-patch.bin.part'):gh('release','delete-asset',TAG,name,'--repo',REPO,'--yes')
        gh('release','edit',TAG,'--repo',REPO,'--draft=false','--latest')
    manifest.update(published=True,releaseUrl=release()['html_url']);save(OUT/'release-manifest.json',manifest)
    save(OUT/'remote-verification.json',{'ok':True,'commit':head,'url':manifest['releaseUrl'],'artifacts':manifest['artifacts']})
    print('Windows release verified and public.',flush=True)
    wait_run(mac,'macOS native builds')
    publishing=dispatch('publish-macos.yml','macPublish',('-f','build_run_id='+str(mac)),ref=TAG)
    wait_run(publishing,'macOS publication')
    mac_release=api('repos/'+REPO+'/releases/tags/'+TAG+'-macos.1')
    if mac_release['draft']:raise RuntimeError('Mac release is still a draft')
    if not {'Coursebook-macOS-arm64.zip','Coursebook-macOS-x86_64.zip'}<={a['name'] for a in mac_release['assets']}:raise RuntimeError('Missing Mac architecture')
    save(OUT/'macos-remote-verification.json',{'ok':True,'commit':head,'url':mac_release['html_url'],'buildRun':mac,'publishRun':publishing})
    print(json.dumps({'ok':True,'windows':manifest['releaseUrl'],'macOS':mac_release['html_url']}),flush=True)

if __name__=='__main__':main()
