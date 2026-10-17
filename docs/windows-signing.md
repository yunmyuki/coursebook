# Windows 正式签名准备

2026-10-17：维护者已申请 SignPath Foundation，审核中。2.2.2 继续作为未签名版本发布；本文和脚本不代表 Coursebook 已获得信任签名。

## 推荐方案

1. **SignPath Foundation 免费开源计划**：适合 MIT 开源、公开发行和持续维护的 Coursebook。需要项目审核、可验证构建、团队 MFA 和每次发布人工批准；证书发布者是 SignPath Foundation。新项目能否通过审核不确定，不能承诺受理时间或一定获批。维护者已自行提交申请；审核结果以 SignPath 通知为准。官方：[申请](https://signpath.org/apply)、[资格与规则](https://signpath.org/terms.html)。批准后再接入其受约束的 GitHub 构建签名流程，不能把本地任意 EXE 上传当作已验证构建。
2. **Certum Open Source Code Signing in the Cloud**：付费备选，商店列价 €49 起（核查当日）；需要个人身份、地址及项目关系验证，仅限其允许的开源用途。中国申请者的证件、核验方式及支付支持需在购买前向官方确认。已有证书可通过 SimplySign Desktop 暴露给 Windows 证书库，用本项目 SignTool 脚本签名。官方：[商店](https://shop.certum.eu/buy-a-code-signing-certyficate)、[身份材料与用途限制](https://support.certum.eu/en/code-signing-required-documents/)。

微软 Artifact Signing 当前个人开发者资格限美国、加拿大，不作为中国个人开发者的默认方案：[官方前提](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)。有效签名能验证发布者和完整性，不保证立即消除所有 SmartScreen 提示。

## 已完成的工程接入

`tools/sign_windows.py` 支持 Windows 证书库中的 CA 代码签名证书，包括已由供应商客户端挂载的硬件/云端密钥。它验证私钥可用、证书用途和有效期，以 SHA256 签名，添加 RFC3161 时间戳，再用 SignTool 和 Windows Authenticode 双重校验；不创建自签名、不导出私钥、不把密码放进命令行。

```powershell
# 安装 Windows SDK 的 SignTool；通过 CA 客户端登录/启用签名密钥
$env:COURSEBOOK_SIGN_CERT_SHA1 = '证书指纹：40位十六进制'
# 可选：COURSEBOOK_SIGNTOOL、COURSEBOOK_SIGN_STORE=LocalMachine
# 可选：COURSEBOOK_TIMESTAMP_URL（供应商提供的 RFC3161 服务）
python tools/sign_windows.py --preflight
python tools/automate_release.py --base-version 2.2.1 --publish
```

发布现在默认要求签名。没有证书时在构建前失败，避免白做完整构建。签名在压缩及散列计算前完成；发布脚本重新验签，并检查完整/Lite ZIP 内 EXE 与已验签 EXE 的散列一致。审核期间维护者可显式使用 `--publish --allow-unsigned` 发布未签名版本；脚本核验 EXE 确实未签名，发布说明和质量记录必须披露状态，不会将不可信签名当作正式签名。

证件、账号登录、购买、PIN 和 MFA 由维护者在官方渠道完成，不能在仓库、聊天或发布日志中提交私钥或密码。

## SignPath 申请草稿（未提交）

- Project: Coursebook
- Repository: https://github.com/yunmyuki/coursebook
- Maintainer GitHub account: yunmyuki
- License: MIT
- Existing releases: https://github.com/yunmyuki/coursebook/releases
- Description: Coursebook is a local-first desktop application that converts PDF and PowerPoint lecture materials into source-linked bilingual learning websites, with notes, highlights, review tools and an optional user-configured AI study assistant.
- Windows artifact: Coursebook.exe, built with Python 3.12 and PyInstaller. Third-party runtimes, PP-DocLayoutV3 and optional LibreOffice are distributed with their notices; we request signing only for our application, not re-signing upstream binaries.
- Privacy: Courses and learning records are stored on the user's computer. User-configured model and search services receive content only when their related features are used. See https://github.com/yunmyuki/coursebook/blob/main/docs/privacy.md .
- Requested support: Evaluation for the Foundation's free open-source signing program and guidance for verifiable GitHub Actions builds.

提交前需维护者自行填写联系邮箱，确认所有仓库/签名账号 MFA、作者/审核者/批准者分工及对第三方组件的合规审查。不能把这些尚未确认的事项填成“已完成”。批准前不添加声称已受 SignPath 赞助或签名的徽章。
