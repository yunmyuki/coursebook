# 开发、构建与发布

## macOS 构建

在对应架构的 Mac 上安装 Python 3.12，执行 `pip install -r requirements-macos.txt` 和 `python tools/build_macos.py`，生成 `release/macos/<架构>/Coursebook.app`。Intel 的 cryptography 若从源码构建，应设置 `OPENSSL_STATIC=1`、`OPENSSL_DIR=$(brew --prefix openssl@3)`，避免与 Python 的 OpenSSL 动态库冲突。

GitHub 的 `macOS release` 工作流分别在 macos-14 arm64 与 macos-15-intel 上构建，运行源码回归、钥匙串、真实窗口、模型推理、HTTPS、阅读与离线导出测试。ZIP 使用 ditto 保留应用包权限和链接，再解压验证。通过两个架构的检查后，`Publish tested macOS release` 工作流接受构建 run ID，核对报告及 SHA256 后发布独立 Mac 标签，不覆盖已有 Windows 发行附件。

当前是 ad-hoc 签名，无 Developer ID 和公证。正式签名需要维护者自己的 Apple 开发者证书与公证凭据，不能用测试签名代替。不要将这些凭据或用户课程提交到仓库。

## 本地开发

使用 Windows x64、Python 3.12。`requirements.txt` 是运行依赖范围；`requirements-lock.txt` 记录本次构建的运行依赖版本。用虚拟环境安装依赖，避免混入其他项目库。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt -r requirements-desktop.txt
New-Item -ItemType Directory -Force tmp
python -m unittest discover -s tests -p "test_*.py"
node tests/reader.test.cjs
python tools/build_desktop.py
```

产物位于 `release/2.1.0/app/CourseCompiler/`。默认只构建轻量核心，不从开发工作区复制课程、环境文件或个人数据。依赖锁定不代表字节级可复现；编译时间、系统 DLL 和平台会影响最终散列。

## 发行检查

开发版默认使用本地版面分析 + 云端区域 OCR，另需 `python -m pip install -r requirements-layout.txt`。首次设置预选硅基 PaddleOCR-VL-1.5，翻译和 AI 助手预选独立的 Qwen 文本连接；已有用户的自定义设置不会自动覆盖。在高级模型设置安装/导入固定版本 PP-DocLayoutV3，模型存于用户数据目录的 `models/PP-DocLayoutV3/`。运行 `python tools/benchmark_hybrid.py <课程编号> --offline --pages 2 10 16` 可只检查本地布局与 OCR 分流；去掉 `--offline` 才会使用已配置硅基密钥调用区域 OCR。详细结果见 `hybrid-parsing-2026-09-30.md`。模型权重不复制进源码，2.1.0 的两个 Windows 包均包含运行时与模型，源码构建需要预先准备固定权重。

1. 在隔离数据目录执行 EXE `--self-test <报告路径> --data-dir <测试目录>`。
2. 完整版增加 `--test-office`，验证真实 PPTX 提取、表格、备注与 PPT 往返转换。
3. 执行 `--window-test <报告路径>`，验证真实 WebView2 窗口加载。
4. 用 `tools/release_demo.py` 生成自制示例，用 `tools/release_browser.cjs` 检查真实打包应用的导入、阅读和静态导出。
5. `tools/create_release.py package` 要求 Python、EXE、窗口与浏览器检查报告全部通过；生成完整版、轻量版、Office 组件和源码 ZIP、SHA256SUMS 与 manifest。

浏览器 QA 使用 Playwright 与 Chrome；安装 `npm install --no-save playwright` 并设置 `CHROME_PATH` 即可。自制示例的中文译文为人工固定夹具，不代表外部模型实测。

## Office 组件来源

从第三方说明中的官方源获取 26.8.0 Windows x64 MSI，核对 SHA256，执行管理员安装镜像提取到 `build/office-component`。`tmp/office-download/manifest.json` 应包含 `file`（本机 MSI 路径）、`source`（官方 HTTPS URL）和 `sha256`。随后运行 `python tools/create_release.py prepare`。

准备脚本仅省略帮助、图库、模板、独立拼写词典和 MSI，不改写官方二进制。打包前必须对该组件实际执行 PPT/PPTX 转换测试。不要仅因安装包缩小就省略核心渲染、字体或转换过滤器。

## GitHub 发布

公开源码来自 `release/2.1.0/github-source` 的明确文件清单，**不要直接上传整个开发工作区**。发行附件位于 `release/2.1.0/`。

登录 GitHub CLI 后执行 `python tools/publish_release.py`，脚本读取仓库、提交干净源码，在 GitHub 创建草稿 Release，上传 ZIP、校验值与质量记录，最后转为公开版本。从远端 main 的现有历史创建发行提交，以普通快进推送更新；拒绝覆盖已有标签或 Release。上传失败时草稿保留；检查现有远端状态后手动续传，不应直接重跑初始化步骤。

发布仓库：`https://github.com/yunmyuki/coursebook`。下载链接采用固定版本 `/releases/download/v2.1.0/<文件名>`。只有 Release 发布并上传附件后，README 的下载链接才可用。
