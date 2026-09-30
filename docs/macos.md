# Coursebook for macOS

下载与你的 Mac 芯片对应的 ZIP：Apple Silicon（M1/M2/M3/M4 等）选择 arm64；Intel 选择 x86_64。解压后将 **Coursebook.app** 拖到「应用程序」，双击打开。内置 Python 和本地版面模型，无需安装开发环境。

首版支持范围：Apple Silicon 为 macOS 14 或更高；Intel 为 macOS 15 或更高。构建与测试在对应架构的 GitHub Mac 主机执行，详细结果随包提供。

本版本仅使用临时本地签名（ad-hoc），尚未取得 Apple Developer ID 签名和公证。首次打开可能被 macOS 阻止；确认下载来源为本项目 GitHub 后，可在「系统设置 → 隐私与安全性」中允许打开。无需关闭系统安全保护。受组织管理的 Mac 可能不允许此操作。

PDF 可直接处理。PPT/PPTX 的页面渲染需要另外安装 [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)，并放在 `/Applications/LibreOffice.app`。为控制包体积，本版本没有附带 Office 转换组件。

课程与学习记录默认保存在 `~/Library/Application Support/Coursebook`；API Key 在本地配置中加密保存，加密主密钥放在 macOS 钥匙串。首次访问钥匙串可能出现系统授权提示。不会读取或打包开发者的课程及密钥。Windows 的加密 API Key 不能直接复制到 Mac，请重新填写。

支持本地版面分析与云端区域 OCR、双语阅读、复核、搜索、高亮、笔记、AI 助手和静态网站导出。云端 OCR、翻译、助手及联网搜索仍需配置相应服务。导出的学习网站可离线阅读。
