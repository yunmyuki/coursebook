# 第三方组件

应用自身代码遵循仓库根目录 MIT License。该许可不替代第三方组件自己的许可。发行包中的 `THIRD-PARTY-NOTICES/`、组件内的 LICENSE / NOTICE，以及 `components.json` 提供实际版本与许可证文本。

- **LibreOffice 26.8.0**：仅完整版与 Office 组件包携带。基于官方 Windows x64 安装包，SHA256 为 `4aa6c6e1895f4055104effcb556bd3362d20c6ad707c149543304f395ef9db95`。保留原始二进制、渲染引擎、转换过滤器、字体与许可；去除独立拼写词典、帮助、图库、模板和安装 MSI，以减少下载体积。本应用不提供 LibreOffice 编辑器界面。
  - [官方许可](https://www.libreoffice.org/licenses/)
  - [对应版本源码](https://download.documentfoundation.org/libreoffice/src/26.8.0/)
  - 完整来源与省略文件清单在 `_internal/office/component-source.json`。
- **Python、pywebview、pythonnet、clr-loader**：本地运行时与 Windows 窗口。
- **pypdf、pdfplumber、pdfminer.six、pypdfium2 / PDFium、python-pptx、Pillow、lxml**：文档解析、转换与图片处理。
- **KaTeX**：静态阅读器公式渲染，许可在 `_internal/web/vendor/katex/`。
- **PyInstaller**：打包工具；其 bootloader exception 允许分发打包应用，参见随包通知。

系统 WebView2 没有随包分发。机器没有可用 WebView2 时，应用尝试使用默认浏览器。
