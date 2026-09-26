"""Publish only the allowlisted source tree and verified release assets.

Requires gh + git and authentication for yunmyuki/coursebook. No token is printed
or persisted; existing Git credential-manager credentials may be used in memory.
"""
import hashlib
import json
import os
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
    for report in ('exe-self-test.json','exe-window-test.json','browser-smoke.json','python-tests.json'):
        if not json.loads((OUT/report).read_text('utf-8-sig')).get('ok'):raise RuntimeError('Quality gate failed: '+report)
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    if run(['gh','auth','status'],env,check=False).returncode:
        credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,env=env,timeout=30)
        values=dict(row.split('=',1) for row in credential.stdout.splitlines() if '=' in row)
        if not values.get('password'):raise RuntimeError('Authenticate first: gh auth login --hostname github.com --web')
        env['GH_TOKEN']=values['password']
    repo=json.loads(run(['gh','api','repos/'+REPO],env).stdout)
    if not repo.get('permissions',{}).get('push'):raise RuntimeError('Authenticated account cannot push to '+REPO)
    source=OUT/'github-source'
    remote='https://github.com/'+REPO+'.git'
    git=['git','-c','credential.helper=','-c','credential.helper=!gh auth git-credential']
    if run(git+['ls-remote',remote],env).stdout.strip():raise RuntimeError('Remote is not empty. Review and integrate existing history before publishing.')
    if run(['gh','release','view',TAG,'--repo',REPO],env,check=False).returncode==0:raise RuntimeError('Release already exists; refusing to overwrite')
    if not(source/'.git').exists():run(['git','init','-b','main'],env,source)
    run(['git','config','user.name','yunmyuki'],env,source)
    run(['git','config','user.email','yunmyuki@users.noreply.github.com'],env,source)
    if not run(['git','remote'],env,source).stdout.strip():run(['git','remote','add','origin',remote],env,source)
    run(['git','add','--all'],env,source)
    run(['git','commit','-m','Release Course Compiler '+__version__],env,source)
    run(git+['push','-u','origin','main'],env,source)
    print('Public source pushed to '+REPO,flush=True)
    run(['git','tag',TAG],env,source);run(git+['push','origin',TAG],env,source)
    run(['gh','release','create',TAG,'--repo',REPO,'--verify-tag','--draft','--title','Course Compiler '+__version__,'--notes-file',str(ROOT/'docs/release-notes.md')],env,source)
    assets.extend([OUT/'SHA256SUMS.txt',ROOT/'docs/release-quality.md'])
    for asset in assets:
        print('Uploading '+asset.name,flush=True)
        run(['gh','release','upload',TAG,str(asset),'--repo',REPO],env,source)
    run(['gh','release','edit',TAG,'--repo',REPO,'--draft=false','--latest'],env,source)
    published=json.loads(run(['gh','release','view',TAG,'--repo',REPO,'--json','url,isDraft,assets'],env).stdout)
    if published['isDraft'] or len(published['assets'])!=len(assets):raise RuntimeError('Release verification failed')
    manifest['published']=True;manifest['releaseUrl']=published['url']
    (OUT/'release-manifest.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    print(json.dumps({'published':True,'url':published['url'],'assets':len(published['assets'])}))

if __name__=='__main__':main()
