# 自动化检验与发布

维护者只需维护版本号、发布说明与下载链接，然后运行一次入口。完整日志落盘，终端只输出阶段和失败位置，不需要让 AI 反复读取构建日志。

## 准备

Windows x64、Python 3.12、Node、Git、已登录的 GitHub CLI；按 development.md 准备构建依赖、Chrome、PP-DocLayoutV3。上一版 Windows Lite 与 Office ZIP 以及 release-manifest.json 保留在 `release/<上一版本>/`。不要删除它们，它们是经过散列校验的增量打包基线。

更新 `course_compiler/__init__.py`、package.json、README 下载链接、quickstart、development 和 release-notes 的版本。

```powershell
# 仅检验与打包
python tools/automate_release.py --base-version 2.2.1

# 检验、打包并发布 Windows + 两种 macOS 架构
python tools/automate_release.py --base-version 2.2.1 --publish

# 紧凑状态；完整日志不必逐行读取
python tools/automate_release.py --status
```

下一次发布的 base-version 改为这次已发布的版本。流水线不调用真实付费模型。

## 自动执行

1. GitHub 权限与 main 基线确认。
2. Python 回归、JavaScript 检查。
3. 构建、许可证整理、校验并复用 Office、生成公开自制示例。
4. 成品模型、转换、加密、原生窗口、浏览器阅读/编辑/导出检查。
5. 白名单生成公开源码、敏感文件与凭据模式检查、公开副本回归。
6. 压缩包完整性、SHA256、最终 Lite 解压检查。
7. 正常快进推送源码和新标签，创建草稿并触发原生 Mac 构建。
8. 从上一版 ZIP 重用相同压缩字节，只上传新增数据和配方，在 GitHub 重组。输出必须与本机已测试 ZIP 逐字节散列相同。
9. 验证远端附件大小与 SHA256、同一提交的源码 CI，公开 Windows Release；删除临时组装附件。
10. 等待两个 Mac 架构测试成功，再由绑定相同提交的发布工作流核验并公开 Mac Release。

## 中断、失败与续跑

状态记录位于 `release/<版本>/automation-state.json`、`publish-state.json`，日志在 `logs/`。修复环境或网络问题后重跑相同命令；输入未变化且校验记录一致的本地阶段跳过，远端草稿附件按散列核验后续传。

更改源码会使本地阶段失效。源码已推送后不得用同版本覆盖不同内容；需要新的修复版本。若只是 GitHub runner 的临时故障，可先在 GitHub 重跑原 run，成功后续跑本地入口。失败工作流不会被当作成功，也不会自动无限重试。

任何发布都需显式 `--publish`。已公开 Release 不覆写；远端 main 或标签偏离准备提交会停止。下载/上传失败保留本地包和远端草稿供续跑。凭据不写入状态文件或日志。

减少 token 来自阶段自动编排、断点与紧凑摘要；不通过跳过成品检查降低消耗。质量记录与 CI 是检查依据，不让模型逐项宣布未经执行的测试成功。

## 2.2.2 起的签名与隐私门禁

`--publish` 默认要求已配置的可信 Windows 代码签名证书，无证书在构建前停止。签名先于压缩，发布前再次验签，并对 ZIP 内 EXE 核对。详见 [签名准备](windows-signing.md)。新增 `tools/audit_release_privacy.py` 检查所有最终包的私有数据路径并用真实 EXE 在全新工作区启动；`--verify-github` 可核对已发布附件散列。

SignPath 审核期间，本次采用维护者明确选择的未签名发布：

```powershell
python tools/automate_release.py --base-version 2.2.1 --publish --allow-unsigned
```

此开关不跳过成品测试、隐私扫描、远端散列或源码 CI。发布前验证 EXE 状态为 NotSigned，并要求发布说明和质量记录披露未签名；不能与 `--require-signing` 同用。证书就绪后去掉此开关。
