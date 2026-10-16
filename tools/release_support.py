"""Small shared release primitives; credentials stay in child-process memory."""
import hashlib,json,os,subprocess
from pathlib import Path

REPO='yunmyuki/coursebook'

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8');temp.replace(path)

def run(args,env=None,cwd=None,check=True):
    p=subprocess.run(args,env=env,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600)
    if check and p.returncode:raise RuntimeError(f'{args[0]} {args[1]} failed: {p.stderr[-1500:]}')
    return p

def github_env():
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    if run(['gh','auth','status'],env,check=False).returncode:
        p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,env=env,timeout=30)
        values=dict(s.split('=',1) for s in p.stdout.splitlines() if '=' in s)
        if not values.get('password'):raise RuntimeError('GitHub authentication required: gh auth login')
        env['GH_TOKEN']=values['password']
    return env

def gh_json(env,*args):return json.loads(run(['gh',*args],env).stdout)
