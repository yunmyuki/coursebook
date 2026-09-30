"""Publish only the allowlisted source tree and verified release assets.

Requires gh + git and authentication for yunmyuki/coursebook. No token is printed
or persisted; existing Git credential-manager credentials may be used in memory.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
OUT=ROOT/'release'/__version__
REPO='yunmyuki/coursebook'
TAG='v'+__version__

def run(args,env,cwd=None,check=True):
    result=subprocess.run(args,env=env,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if check and result.returncode:raise RuntimeError('Command failed: '+args[0]+' '+args[1]+'; '+result.stderr[:1000])
    return result

def main():
    manifest=json.loads((OUT/'release-manifest.json').read_text('utf-8'))
    assets=[OUT/item['file'] for item in manifest['artifacts']]
    for item,path in zip(manifest['artifacts'],assets):
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=item['sha256']:raise RuntimeError('Asset checksum mismatch: '+path.name)
    print('Release asset checksums verified.',flush=True)
    for report in ('exe-self-test.json','exe-window-test.json','browser-smoke.json','python-tests.json','source-tests.json','lite-self-test.json','lite-window-test.json'):
        if not json.loads((OUT/report).read_text('utf-8-sig')).get('ok'):raise RuntimeError('Quality gate failed: '+report)
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    if run(['gh','auth','status'],env,check=False).returncode:
        credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,env=env,timeout=30)
        values=dict(row.split('=',1) for row in credential.stdout.splitlines() if '=' in row)
        if not values.get('password'):raise RuntimeError('Authenticate first: gh auth login --hostname github.com --web')
        env['GH_TOKEN']=values['password']
    repo=json.loads(run(['gh','api','repos/'+REPO],env).stdout)
    if not repo.get('permissions',{}).get('push'):raise RuntimeError('Authenticated account cannot push to '+REPO)
    source=OUT/'github-source';checkout=OUT/'publish-repo'
    remote='https://github.com/'+REPO+'.git'
    git=['git','-c','credential.helper=','-c','credential.helper=!gh auth git-credential']
    if run(['gh','release','view',TAG,'--repo',REPO],env,check=False).returncode==0:raise RuntimeError('Release already exists; refusing to overwrite')
    if run(git+['ls-remote','--tags',remote,'refs/tags/'+TAG],env).stdout.strip():raise RuntimeError('Tag already exists; refusing to overwrite')
    if checkout.exists():raise RuntimeError('Publish checkout exists; inspect its state before resuming publication.')
    run(git+['clone','--branch','main','--single-branch',remote,str(checkout)],env)
    # Preserve remote history and reject unreviewed changes since release preparation.
    expected=(OUT/'base-commit.txt').read_text('utf-8').strip()
    if run(['git','rev-parse','HEAD'],env,checkout).stdout.strip()!=expected:raise RuntimeError('Remote changed since review; integrate it before publication')
    for path in source.rglob('*'):
        if path.is_file():
            target=checkout/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    run(['git','config','user.name','yunmyuki'],env,checkout)
    run(['git','config','user.email','yunmyuki@users.noreply.github.com'],env,checkout)
    run(['git','add','--all'],env,checkout)
    run(['git','commit','-m','Release coursebook '+__version__],env,checkout)
    run(git+['push','origin','HEAD:main'],env,checkout)
    print('Public source pushed to '+REPO,flush=True)
    run(['git','tag',TAG],env,checkout);run(git+['push','origin',TAG],env,checkout)
    run(['gh','release','create',TAG,'--repo',REPO,'--verify-tag','--draft','--title','coursebook '+__version__,'--notes-file',str(ROOT/'docs/release-notes.md')],env,checkout)
    assets.extend([OUT/'SHA256SUMS.txt',ROOT/'docs/release-quality.md'])
    for asset in assets:
        print('Uploading '+asset.name,flush=True)
        run(['gh','release','upload',TAG,str(asset),'--repo',REPO],env,checkout)
    # Verify uploaded bytes before making the release public.
    draft=json.loads(run(['gh','release','view',TAG,'--repo',REPO,'--json','assets'],env).stdout)
    uploaded={a['name']:a for a in draft['assets']}
    for asset in assets:
        if asset.name not in uploaded or uploaded[asset.name]['size']!=asset.stat().st_size:raise RuntimeError('Upload size mismatch: '+asset.name)
    run(['gh','release','edit',TAG,'--repo',REPO,'--draft=false','--latest'],env,checkout)
    published=json.loads(run(['gh','release','view',TAG,'--repo',REPO,'--json','url,isDraft,assets'],env).stdout)
    if published['isDraft'] or len(published['assets'])!=len(assets):raise RuntimeError('Release verification failed')
    manifest['published']=True;manifest['releaseUrl']=published['url']
    (OUT/'release-manifest.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    print(json.dumps({'published':True,'url':published['url'],'assets':len(published['assets'])}))

if __name__=='__main__':main()
