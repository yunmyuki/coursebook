"""Publish only both tested native Mac artifacts from the designated workflow."""
import hashlib,json,os,subprocess,sys
from pathlib import Path

REPO='yunmyuki/coursebook'
TAG='v2.1.0-macos.1'
def gh(*args):return subprocess.check_output(['gh',*args],text=True).strip()
def main():
    run_id=os.environ['MAC_BUILD_RUN_ID']
    if not run_id.isdigit():raise ValueError('Numeric run ID required')
    run=json.loads(gh('api',f'repos/{REPO}/actions/runs/{run_id}'))
    assert run['path']=='.github/workflows/macos-release.yml' and run['conclusion']=='success'
    assert run['head_repository']['full_name']==REPO and run['head_branch']=='main'
    files=[];summaries=[]
    for arch in ('arm64','x86_64'):
        folder=Path('release/mac-publish')/arch
        gh('run','download',run_id,'--repo',REPO,'--name','Coursebook-macOS-'+arch,'--dir',str(folder))
        report=json.loads((folder/('quality-'+arch+'.json')).read_text())
        for key in ('ok','frozenSelfTest','keychain','nativeWindow','browserFlow','unpackedSelfTest'):assert report[key],key
        assert report['arch']==arch and report['version']=='2.1.0'
        package=folder/('Coursebook-macOS-'+arch+'.zip')
        with package.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        assert sha==report['sha256'] and package.stat().st_size==report['bytes']
        for name in ('self-test.json','window-test.json','unpacked-self-test.json','browser-smoke.json'):
            assert json.loads((folder/name).read_text())['ok'],name
        files += [str(package),str(folder/('quality-'+arch+'.json')),str(folder/('SHA256SUMS-'+arch+'.txt'))]
        summaries.append(f"- {arch}: {report['bytes']/1024**2:.1f} MiB；macOS {report['macOS']} 原生构建、窗口、钥匙串、模型推理与导出测试通过。")
    notes=Path('release/mac-publish/notes.md')
    notes.write_text('''Coursebook 首个 macOS 发行版，内置本地版面模型与 Python 运行时。

- Apple Silicon（M 系列）下载 `Coursebook-macOS-arm64.zip`，支持 macOS 14+。
- Intel 下载 `Coursebook-macOS-x86_64.zip`，支持 macOS 15+。
- 解压后将 `Coursebook.app` 拖到「应用程序」。PDF 可直接处理；PPT/PPTX 渲染需另外安装 LibreOffice。
- 数据保存在 `~/Library/Application Support/Coursebook`，API 配置使用系统钥匙串加密。
- 仅有 ad-hoc 签名，尚未 Apple Developer ID 签名或公证。首次打开可能需要在「系统设置 → 隐私与安全性」允许打开，不必关闭系统安全保护。
- 自动测试不替代所有 Mac 机型或讲义样本的实际验收，复杂页面仍应复核。

'''+ '\n'.join(summaries)+f'\n\n[安装与使用说明](https://github.com/{REPO}/blob/{run["head_sha"]}/docs/macos.md) · [构建记录]({run["html_url"]})\n',encoding='utf-8')
    gh('release','create',TAG,'--repo',REPO,'--target',run['head_sha'],'--title','Coursebook 2.1.0 · macOS','--draft','--notes-file',str(notes))
    gh('release','upload',TAG,*files,str(Path('release/mac-publish/arm64/README-macOS.md')),'--repo',REPO)
    release=json.loads(gh('release','view',TAG,'--repo',REPO,'--json','id'))
    remote=json.loads(gh('api',f'repos/{REPO}/releases/{release["id"]}')) if str(release['id']).isdigit() else None
    # gh's node ID differs from REST ID; locate the draft by its unique tag instead.
    if remote is None:
        releases=json.loads(gh('api',f'repos/{REPO}/releases'))
        remote=next(r for r in releases if r['tag_name']==TAG)
    assets={a['name']:a for a in remote['assets']}
    for file in files:
        p=Path(file)
        with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        assert assets[p.name]['digest']=='sha256:'+digest
        assert assets[p.name]['size']==p.stat().st_size
    gh('release','edit',TAG,'--repo',REPO,'--draft=false','--latest=false')
    print(gh('release','view',TAG,'--repo',REPO,'--json','url,isDraft,assets'))

if __name__=='__main__':main()
