<div align="center">

# coursebook

### 把课程讲义，变成可以读、查、问、记的双语学习空间。

PDF · PPTX · PPT → 完整原文 · 对照译文 · 原图表 · 按需 AI 助手

[下载 Windows 版](https://github.com/yunmyuki/coursebook/releases/tag/v2.0.0) · [快速开始](docs/quickstart.md) · [发布说明](docs/release-notes.md) · [反馈问题](https://github.com/yunmyuki/coursebook/issues)

![Windows x64](https://img.shields.io/badge/Windows-x64-0078D4?style=flat-square)
![MIT License](https://img.shields.io/badge/license-MIT-5645D4?style=flat-square)
![Local first](https://img.shields.io/badge/storage-local--first-555555?style=flat-square)

</div>

coursebook 是一款本地课程编译与阅读应用。导入一门课的多份讲义，生成按原页顺序组织、可追溯来源的双语学习网站。课程和学习记录保存在你的电脑上；导出的静态网站无需应用或后端即可阅读。

原名 Course Compiler，现统一使用 **coursebook**。当前源码与界面已采用新名称；已发布的 v2.0.0 安装包仍保留原名称和文件名。旧版下载链接、数据目录与学习记录继续兼容。

它以**保留讲义信息**为目标：原文、译文与 AI 助手回答明确区分。解析结果可以对照原页复核，AI 不会用摘要替换讲义正文。

![coursebook 双语阅读器，自制示例课程](docs/images/reader.png)

## 下载

当前版本：**2.0.0 · Windows 10/11 x64**。首次公开版本，尚未经过大规模设备兼容性验证。精确文件大小与校验值见对应 Release 附件。

| 发行包 | 适合你，如果… | 下载 |
| --- | --- | --- |
| 完整版 · 403.8 MiB | 需要直接处理 PDF、PPTX、PPT，无需另装转换工具 | [Windows x64 ZIP](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/CourseCompiler-Windows-x64.zip) |
| 轻量版 · 52.7 MiB | 主要处理 PDF，或电脑已安装 LibreOffice | [Windows x64 Lite ZIP](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/CourseCompiler-Windows-x64-Lite.zip) |
| Office 组件 · 351.1 MiB | 想为轻量版补充 PPT/PPTX 转换能力 | [Office ZIP](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/CourseCompiler-Office-Windows-x64.zip) |
| 源码 · 约 1.6 MiB | 希望自行运行、修改或构建 | [Source ZIP](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/CourseCompiler-Source.zip) |

[SHA256 校验文件](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/SHA256SUMS.txt) · [版本质量检查](docs/release-quality.md)

想先体验阅读？[下载自制示例课程](https://github.com/yunmyuki/coursebook/releases/download/v2.0.0/CourseCompiler-Demo.zip)，直接解压打开 `index.html`，或在应用中导入。示例译文为人工编写，无需 API 即可体验阅读。

解压整个文件夹，双击 `CourseCompiler.exe`。应用自带 Python；请保留 `_internal` 文件夹。窗口优先使用系统 WebView2，无法启动时会在默认浏览器打开本地界面。

## 从讲义到学习空间

1. **连接模型。** 默认只填写 API 地址、API Key 和模型名。共用模型需支持图片输入；高级设置可分别配置文档解析、翻译和 AI 助手。
2. **导入课程。** 拖入多个 PDF / PPTX / PPT，按文件顺序组织讲义。可靠文本直接提取；复杂页面交给视觉模型，保留原图、页码与位置。
3. **检查结果。** 对照原页复核疑点，修改原文或译文。保留原始识别文本与修改记录；暂停后可从缓存继续。
4. **阅读和提问。** 搜索内容、切换双语布局、选段向助手提问、记录笔记和高亮。
5. **导出带走。** 导出课程 ZIP，解压后打开 `index.html`。阅读、检索和浏览器内笔记无需后台服务。

![简洁的模型配置，自制测试环境](docs/images/settings.png)

## 让学习回到内容本身

| 能力 | 具体体验 |
| --- | --- |
| 原文与译文逐单元对应 | 标题、段落、列表和表格单元保留对应关系，切换左右对照或上下对照 |
| 来源可追溯 | 每个内容单元有稳定锚点，可定位到文件、原页与原图 |
| 图表留在正文 | 提取图表原图；从图表识别的文字有独立来源标记 |
| 适合长时间阅读 | 三栏阅读器、折叠目录、章节进度、多种字体、紧凑排版 |
| AI 学习助手 | 选段自动作为上下文，支持连续追问、课程搜索与可选联网搜索，回答带来源定位 |
| 等待过程可见 | 助手显示检索、整理回答等阶段，可停止请求；新回答不会打断历史消息阅读 |
| 个人学习工作区 | 右栏直接写笔记，管理高亮、书签与进度，支持备份 |
| 课程持续更新 | 添加新材料，预览建议插入位置，并由你确认或调整 |
| 成本可控 | 处理缓存、失败恢复、请求次数上限；不预生成知识解析 |

## 模型和联网搜索

可配置兼容接口，包括 OpenAI 兼容格式与 Anthropic 格式。共用连接使用视觉模型；翻译和学习助手可以使用独立文本模型。提供硅基流动、通义、DeepSeek 等连接预设，实际可用性取决于服务商、模型能力和账户权限。

联网搜索是可选功能，支持**博查、百度千帆、Tavily、Exa、Brave、SerpApi**；SerpApi 可选择 Google、Bing、百度引擎。各服务独立保存密钥，可先测试连接。Google/Bing 搜索通过 SerpApi 接入，不表示支持已经停用或限制新注册的旧版官方搜索 API。

模型与搜索服务由你选择、配置和付费。应用不附赠模型额度，也不会使用你的 ChatGPT 订阅额度。

## 本地保存与隐私

- Windows 发行版数据目录：`%LOCALAPPDATA%\Course Compiler`。课程、学习记录和助手对话在本地文件中保存，无远程数据库。
- API Key 使用 Windows DPAPI 加密，与当前 Windows 用户绑定。密钥不写入导出的课程网站。
- 编译和提问时，相关文字、页图、上下文会发送到你配置的模型服务。启用联网时，搜索词发送到你选择的搜索服务。
- 静态导出的课程包含讲义内容、原文件和页图；分享前请确认自己有权分享这些资料。个人笔记需要单独备份。

详见 [隐私与数据流](docs/privacy.md)。

## 当前边界

解析完整性是设计目标，不是准确率保证。复杂公式、密集表格、低清扫描件和阅读顺序仍可能需要人工复核。API 的请求上限不等于金额上限；价格和计费由服务商决定。

AI 助手及联网搜索需要运行本地应用并配置服务；直接打开导出的 HTML 时，这些在线功能不可用。静态网站的笔记保存在浏览器中，应定期导出备份。

目前提供 Windows x64 发行包；macOS、Linux、Windows ARM 尚未验证。不含自动更新或代码签名，Windows 可能提示未知发布者。

## 开发

```powershell
git clone https://github.com/yunmyuki/coursebook.git
cd coursebook
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m course_compiler serve --port 8768
```

打开 `http://127.0.0.1:8768`，在页面中配置自己的模型。开发与构建基于 Python 3.12；源码模式的 PPT 转换需要 LibreOffice。

```powershell
New-Item -ItemType Directory -Force tmp
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"
node tests/reader.test.cjs
```

[构建与发布指南](docs/development.md) · [报告问题](https://github.com/yunmyuki/coursebook/issues/new?template=bug_report.yml)

欢迎提交可复现的问题和改进建议。报告问题时请移除 API Key、私人讲义与学习记录。

## 许可证

项目代码使用 [MIT License](LICENSE)。第三方组件沿用各自许可证，包括 LibreOffice、PDFium、KaTeX、pywebview 与 Python。发行包保留第三方许可证和来源说明，见 [第三方组件](docs/third-party.md)。项目与这些组件的维护组织无隶属或背书关系。

页面截图使用项目自制示例，不包含用户课程资料。
