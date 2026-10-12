# Coursebook 2.2.0

把课程讲义，变成可以读、查、问、记的双语学习空间。本版让第一次配置更容易，并让清洗和修正讲义成为阅读流程的一部分。

## 新增与改进

- **新手引导**：四步介绍功能、API 地址、模型名和 Key、导入与复核。支持跳过、恢复进度和从侧栏重看；直接进入真实配置页，保存后继续教程。连接测试需主动点击。
- **页面清洗**：检测同一文件中重复的页码、学校或版权等边缘固定标注，预览后勾选隐藏。支持恢复；保留原图、识别文本、稳定锚点，清洗结果同步到阅读、搜索和导出。
- **直接编辑正文**：段落旁 ✎、页角「编辑」和顶部「编辑正文」均可进入；支持搜索，修改原文、译文、表格单元和 LaTeX 公式。
- **可靠修正**：允许只保存原文，旧译文保留到历史并标为待更新；当前译文确实仍适用时可明确确认。未保存修改保护、其他窗口编辑冲突检测、笔记关联保留。
- 改善窄屏原页预览与编辑操作。Windows 程序和下载包统一使用 Coursebook 名称，保留旧版数据目录以兼容升级。

## 下载与升级

[Windows 下载](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.0) · [Mac 下载](https://github.com/yunmyuki/coursebook/releases/tag/v2.2.0-macos.1)

- **Windows 完整版**：PDF、PPTX、PPT 所需转换组件、本地版面模型和运行时齐备。
- **Windows 轻量版**：保留本地模型与 PDF 能力；PPT/PPTX 需本机 LibreOffice 或另下载 Office 组件。
- **Mac arm64 / x86_64**：分别支持 Apple Silicon macOS 14+ 和 Intel macOS 15+；PPT/PPTX 需安装 LibreOffice。
- 另有源码与自制示例课程。示例采用固定人工译文，阅读无需 API Key。

关闭旧应用，将新版解压到新目录。Windows 双击 `Coursebook.exe`；不要单独移动程序或删除 `_internal`。已有课程、学习记录与自定义 API 配置保留；不要同时运行新旧版本访问同一数据目录。升级前建议备份数据。

## 验证与边界

[质量记录](https://github.com/yunmyuki/coursebook/blob/v2.2.0/docs/release-quality.md) · [新功能说明](https://github.com/yunmyuki/coursebook/blob/v2.2.0/docs/iteration-onboarding-cleanup-editing.md)

清洗采用保守规则：同一文件中至少三页、覆盖至少 60% 页面的可靠边缘候选才会列入建议；不会自动删除知识点。缺少位置或与正文混合的标注可能无法建议，需要人工编辑。

测试采用隔离课程和模拟服务验证新流程，不代表所有云端模型均已实测。复杂讲义仍需对照原页复核。正文编辑、页面清洗和 AI 助手需要本地应用；导出的静态网站可独立离线阅读。

Windows 尚未 Authenticode 签名；Mac 为 ad-hoc 签名，尚未 Developer ID 签名及公证。包中不包含开发者讲义、个人记录或 API Key。各发行附件提供 SHA256 校验值。
