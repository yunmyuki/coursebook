# Coursebook 2.2.2

把课程讲义，变成可以读、查、问、记的双语学习空间。本版重点降低模型配置门槛，让新用户更容易完成第一次编译。

## 改进

- **简单配置分为两组**：「OCR 识别」与「翻译与助手」，分别填写 API 地址、Key 和模型名称，并单独测试连接。翻译与助手共用文本模型，避免误用 OCR 做翻译或问答。
- **更完整的 API 入门教程**：逐步讲解注册、实名认证、创建 Key、复制模型 ID、测试连接及常见错误。推荐硅基流动并明确不是广告；免费 OCR 不代表翻译、问答免费，实际价格以服务商控制台为准。
- **首次使用自动打开教程**：即使已有课程或 Key，未看过教程的用户也会进入引导。主动跳过或完成后不重复弹出，侧栏可随时重开。
- 保留旧模型连接与加密密钥；切换简单/高级模式不再替换解析连接，高级配置仍支持三个独立模型。
- 增加本机数据来源提示和浏览器学习记录的工作区隔离，防止不同工作区误用浏览器缓存。发行包不预装私人课程或笔记。
- 自动化发布增加最终包隐私审计、全新工作区启动检查及显式签名状态校验。

## 下载

[Windows](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.2) · [macOS](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.2-macos.1)

Windows 完整版包含 PPT/PPTX 转换组件；Lite 版处理 PDF，Office 组件可另装。两个包均包含本地版面模型。Mac 提供 Apple Silicon macOS 14+ 与 Intel macOS 15+ 独立版本，PPT/PPTX 需安装 LibreOffice。

关闭旧程序，将新版解压到新目录，保留用户数据目录。课程、笔记及自定义连接继续使用；不要同时运行新旧应用访问同一数据目录。

## 验证与签名状态

[质量记录](https://github.com/yunmyuki/coursebook/blob/v2.2.2/docs/release-quality.md) · [配置教程](https://github.com/yunmyuki/coursebook/blob/v2.2.2/docs/quickstart.md) · [自动化发布](https://github.com/yunmyuki/coursebook/blob/v2.2.2/docs/release-automation.md)

测试使用隔离夹具与模拟模型，不消耗用户模型额度，也不代表任意云端模型的识别准确率。复杂讲义仍需复核。正文编辑、页面清洗及 AI 助手需要本地应用；静态网站可独立离线阅读。

**Windows 未签名：SignPath Foundation 申请审核中。** 本次显式发布未签名版本，不是自签名或已获得 SignPath 认可。Mac 为 ad-hoc 签名，尚未 Developer ID 签名与公证。附件提供 SHA256 校验值，不包含私人讲义、学习记录或 API Key。
