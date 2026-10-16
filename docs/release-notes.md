# Coursebook 2.2.1

把课程讲义，变成可以读、查、问、记的双语学习空间。本版重点改善解析精度，并将检验和发布流程自动化。

## 改进

- 从源 PDF 直接高清渲染 OCR 与图表区域，避免预览图二次裁剪损失小字；旋转和裁剪页坐标保持一致。
- 改善跨行段落与多栏阅读顺序，保留原始行及坐标；中文续行不插入多余空格。
- 可靠原生表格采用真实单元格边界，支持不等宽列、合并格和空格；不可靠网格与扫描表格继续区域 OCR。
- 记录文字来源、精确/估算坐标与渲染方法；版面置信度不冒充文字准确率。
- 已完成旧课程保留，不因升级自动产生整门课程重新识别费用；用户可选择重新识别单页。
- 新增可恢复的自动化检验发布入口、精简摘要、远端散列核验与压缩数据增量上传。

## 下载

[Windows](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.1) · [macOS](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.1-macos.1)

Windows 完整版包含 PPT/PPTX 转换组件；Lite 版处理 PDF，Office 组件可另装。Mac 提供 Apple Silicon macOS 14+ 与 Intel macOS 15+ 独立版本，PPT/PPTX 需安装 LibreOffice。

关闭旧程序，将新版解压到新目录，保留用户数据目录。课程、笔记及自定义连接配置继续使用；不要同时运行新旧应用访问同一数据目录。

## 验证与边界

[质量记录](https://github.com/yunmyuki/coursebook/blob/v2.2.1/docs/release-quality.md) · [解析改进](https://github.com/yunmyuki/coursebook/blob/v2.2.1/docs/parser-precision.md) · [自动化发布](https://github.com/yunmyuki/coursebook/blob/v2.2.1/docs/release-automation.md)

测试使用隔离夹具和模拟服务，不代表任意云端模型的识别准确率。复杂讲义仍需对照原页复核。正文编辑、页面清洗和 AI 助手需要本地应用；静态网站可独立离线阅读。

Windows 尚未 Authenticode 签名；Mac 为 ad-hoc 签名，尚未 Developer ID 签名与公证。发行附件附 SHA256 校验值，不含私人讲义、学习记录或 API Key。
