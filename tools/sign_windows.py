"""Authenticode signing through a CA certificate in the Windows certificate store.
Supports hardware/cloud-backed keys exposed by the provider's Windows client.
Never creates self-signed certificates, exports keys, or accepts a PFX password.
"""
import argparse,json,os,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from course_compiler import __version__
from release_support import digest,save

def thumbprint(value):
    value=value.replace(' ','').upper()
    if not re.fullmatch('[A-F0-9]{40}',value):raise ValueError('Set COURSEBOOK_SIGN_CERT_SHA1 to the CA code-signing certificate thumbprint (40 hex characters).')
    return value

def signtool():
    configured=os.environ.get('COURSEBOOK_SIGNTOOL')
    if configured:
        if not Path(configured).is_file():raise RuntimeError('COURSEBOOK_SIGNTOOL does not exist')
        return configured
    found=shutil.which('signtool')
    if found:return found
    sdk=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Windows Kits/10/bin'
    candidates=sorted(sdk.glob('*/x64/signtool.exe'),reverse=True)
    if not candidates:raise RuntimeError('Install SignTool from the Microsoft Windows SDK, or set COURSEBOOK_SIGNTOOL.')
    return str(candidates[0])

def powershell(script,extra_env=None):
    # Do not inherit PowerShell 7 module paths into Windows PowerShell 5.1.
    # Otherwise Security can fail to autoload while the final JSON command exits 0.
    home=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0'
    env={k:v for k,v in os.environ.items() if k.lower()!='psmodulepath'}
    env.update(extra_env or {});env['PSModulePath']=str(home/'Modules')
    p=subprocess.run([str(home/'powershell.exe'),'-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop';"+script],capture_output=True,text=True,encoding='utf-8-sig',errors='replace',env=env,timeout=120)
    if p.returncode:raise RuntimeError('Windows certificate inspection failed: '+p.stderr[-500:])
    return json.loads(p.stdout)

def preflight():
    if os.name!='nt':raise RuntimeError('Windows signing requires Windows')
    thumb=thumbprint(os.environ.get('COURSEBOOK_SIGN_CERT_SHA1',''))
    machine=os.environ.get('COURSEBOOK_SIGN_STORE','CurrentUser')
    if machine not in ('CurrentUser','LocalMachine'):raise ValueError('Invalid certificate store')
    script=f"$c=Get-Item -LiteralPath 'Cert:/{machine}/My/{thumb}' -ErrorAction Stop; @{{subject=$c.Subject;issuer=$c.Issuer;privateKey=$c.HasPrivateKey;valid=($c.NotBefore -le (Get-Date) -and $c.NotAfter -gt (Get-Date));codeSigning=([bool]($c.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.3'))}} | ConvertTo-Json -Compress"
    c=powershell(script)
    if not all(c.get(k) for k in ('privateKey','valid','codeSigning')) or c['subject']==c['issuer']:raise RuntimeError('A valid CA-issued code-signing certificate with an accessible private key is required')
    return signtool(),thumb,machine

def verify(exe,tool=None):
    exe=Path(exe).resolve();tool=tool or signtool()
    subprocess.run([tool,'verify','/pa','/all',str(exe)],check=True,timeout=120,capture_output=True)
    c=powershell("$s=Get-AuthenticodeSignature -LiteralPath $env:COURSEBOOK_VERIFY_FILE; @{status=[string]$s.Status;thumbprint=$s.SignerCertificate.Thumbprint;subject=$s.SignerCertificate.Subject;issuer=$s.SignerCertificate.Issuer;timestamped=($null -ne $s.TimeStamperCertificate)} | ConvertTo-Json -Compress",{'COURSEBOOK_VERIFY_FILE':str(exe)})
    if c.get('status')!='Valid' or not c.get('timestamped') or c.get('subject')==c.get('issuer'):raise RuntimeError('Trusted Authenticode signature and RFC3161 timestamp are required')
    expected=os.environ.get('COURSEBOOK_SIGN_CERT_SHA1')
    if expected and c['thumbprint'].upper()!=thumbprint(expected):raise RuntimeError('Signature publisher does not match configured certificate')
    return {'ok':True,'version':__version__,'executableSha256':digest(exe),'signature':c}

def verify_unsigned(exe):
    """Explicit unsigned release only: never pass off an invalid signature as unsigned."""
    exe=Path(exe).resolve()
    c=powershell("$s=Get-AuthenticodeSignature -LiteralPath $env:COURSEBOOK_VERIFY_FILE; @{status=[string]$s.Status;hasSigner=($null -ne $s.SignerCertificate)} | ConvertTo-Json -Compress",{'COURSEBOOK_VERIFY_FILE':str(exe)})
    if c.get('status')!='NotSigned' or c.get('hasSigner'):raise RuntimeError('Unsigned publication requires an unsigned EXE, not an invalid or untrusted signature')
    return {'ok':True,'version':__version__,'executableSha256':digest(exe),'signature':c,'unsigned':True}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--preflight',action='store_true');ap.add_argument('--verify-only',action='store_true');ap.add_argument('--exe',type=Path,default=ROOT/'release'/__version__/'app/Coursebook/Coursebook.exe');ap.add_argument('--report',type=Path,default=ROOT/'release'/__version__/'windows-signature.json');args=ap.parse_args()
    if args.preflight:preflight();print('Signing configuration ready.');return
    if not args.exe.is_file():raise RuntimeError('Build Coursebook.exe before signing')
    if not args.verify_only:
        tool,thumb,store=preflight()
        timestamp=os.environ.get('COURSEBOOK_TIMESTAMP_URL','http://timestamp.digicert.com')
        from urllib.parse import urlsplit
        url=urlsplit(timestamp)
        if url.scheme not in ('http','https') or not url.netloc or url.username or url.password:raise ValueError('Invalid RFC3161 timestamp URL')
        command=[tool,'sign','/sha1',thumb,'/s','My','/fd','SHA256','/tr',timestamp,'/td','SHA256','/d','Coursebook']
        if store=='LocalMachine':command.append('/sm')
        subprocess.run(command+[str(args.exe.resolve())],check=True,timeout=300)
    report=verify(args.exe);save(args.report,report);print('Trusted Windows signature and timestamp verified.')

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);sys.exit(2)
