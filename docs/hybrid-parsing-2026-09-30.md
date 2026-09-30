# Coursebook 文档解析选型与混合流水线验证

调研与实测：2026-09-29 至 2026-09-30。价格和服务可用性按查询时官方页面记录；测试使用用户授权的本地讲义，未向 GitHub 上传讲义、密钥或模型缓存。

后续配置调整（2026-09-30）：按用户要求，开发版首次配置已将该混合流程设为默认，预选硅基 PaddleOCR-VL-1.5；翻译与 AI 助手保留独立文本模型。下文的“可选试验后端”描述调研落地时的状态，准确性与实测边界仍然适用。已有自定义设置不会被默认值强制覆盖。

## 结论与适用范围

**本地 PP-DocLayoutV3 + 云端区域 OCR 可实现，已作为可选试验后端接入。** 它很适合包含可靠文字层、复杂分栏、表格和图表的课程讲义。优势是客户端确定坐标、区域和阅读顺序，能跳过大量重复文字识别，并保留原文证据。它不保证每页比完整云端服务便宜或更快：扫描页和区域很多的页面会产生多个请求，免费服务的排队、限流也可能成为主要耗时。

当前保留原有视觉模型、GLM 完整版面接口、Paddle 完整服务。用户可在高级设置选择混合模式；不会自动改动已经保存的课程，也不会自动把整门课程重新付费处理。应先用代表性页面比较，然后选择课程使用的方案。

## 四种方案的实质区别

| 方案 | 本机执行 | 云端执行 | 主要收益 | 主要代价 | Coursebook 适配判断 |
|---|---|---|---|---|---|
| 1. 完整文档解析服务 | 上传、规范化、保存、复核 | 版面、阅读顺序、OCR、表格/公式结构 | 接入最短，客户端小；供应商维护流水线 | 页面通常全部上传；内部布局难修；依赖服务配额与接口 | 适合作为普通用户的便捷选项，以及扫描文档方案 |
| 2. OCR API + 官方 SDK | 通常包含渲染、版面、裁剪、拼装 | 区域识别 | 官方前后处理更完整，减少协议适配错误 | SDK 的运行时、模型和版本依赖可能很大 | 可行；“不能打包”并不准确，应区分可打包与是否适合轻量包 |
| 3. OCR API + 自建流水线 | 自选布局模型、文字层复用、区域分流、质量检查 | 必要区域 OCR | 成本/来源/锚点可控，能针对课程优化 | 自己承担漏框、合并单元格、阅读顺序、服务兼容的维护 | 本次采用的混合方案属于这一类 |
| 4. 通用视觉模型 | 渲染、提示词、结果校验 | 看整页并输出结构化内容 | 接口普及，对特殊页面适应灵活 | 容易重写、漏字、跨栏；坐标并非专门检测结果；输出 JSON 较长 | 保留作可选方案，不能只靠提示词承诺高保真 |

“调用了 SDK”不等于方案 2。GLM 的 `pip install glmocr` MaaS 模式只是转发到完整云端流水线，属于方案 1；`glmocr[selfhosted]` 才提供本地版面与并行区域识别。其识别后端支持 vLLM / SGLang 等，云端服务和本地版面是不同部署方式。[GLM 官方 SDK](https://github.com/zai-org/GLM-OCR/blob/main/README_zh.md)

Paddle 官方流水线已经支持把区域识别指向硅基流动；完整 SDK 不要求把 OCR 大模型装在用户电脑上。但版面、图像处理依赖仍在本地。其官方用法是 `PaddleOCRVL(pipeline_version="v1.5", vl_rec_backend="vllm-server", vl_rec_server_url="https://api.siliconflow.cn/v1", vl_rec_api_model_name="PaddlePaddle/PaddleOCR-VL-1.5", vl_rec_api_key=...)`。[PaddleOCR-VL 官方接入文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.md)

## 具体服务、项目与接入边界

| 候选 | 接入方式 | 返回内容 / 重要边界 | 本次验证程度 |
|---|---|---|---|
| 智谱 GLM-OCR 完整服务 | `POST https://open.bigmodel.cn/api/paas/v4/layout_parsing`；`model: glm-ocr`；`file` 为 URL/data URI | 完整页面结果及布局信息；不要与 `/chat/completions` 的单区域模型混用 | 官方文档核实；已有适配，未使用智谱密钥做新实测 |
| 百度 Unlimited-OCR | 百度官方入口申请服务；也可用官方开源模型经 vLLM/SGLang 部署 | 模型支持带位置标记的文档解析和多页输入；不是仅文字 OCR | 核实官方仓库与上线信息；本次未核实到稳定公开的正式 API 单价，不能把体验入口当免费生产服务 |
| 百度 PaddleOCR-VL 完整流水线服务 | 自托管官方 `/layout-parsing`，或按百度具体产品的 API/鉴权接入 | 通常有版面结果、Markdown、表格和图片；不同云产品鉴权不能直接混用 | 现有通用 Paddle 完整服务适配；不宣称兼容所有百度 AK/SK 接口 |
| 硅基流动 PaddleOCR-VL-1.5 | OpenAI 兼容 `/v1/chat/completions`，一张区域图 + 官方任务提示词 | 文字、LaTeX、OTSL 等区域结果；不是完整页面布局 JSON | **真实图表、表格调用通过** |
| GLM-OCR 区域模型 | 自建或供应商提供的 OpenAI 兼容聊天接口 | `Text Recognition:` / `Table Recognition:` / `Formula Recognition:` | 协议适配与单元测试；未对另一个供应商实测，不默认假定硅基流动提供该模型 |
| DeepSeek-OCR 区域模型 | 支持该模型的聊天端点；按官方 OCR/Markdown 提示词调用 | 可能含 grounding 标记；必须清理标记并保留原始响应 | 协议适配，未在本轮实测；上线状态需以提供商模型列表为准 |
| MinerU 精准 API | `POST /api/v4/extract/task` 或 `/api/v4/file-urls/batch`，随后轮询并获取结果 ZIP | JSON、Markdown、图像资产；轻量 Agent API 只返回 Markdown，不能直接代替精确锚点数据 | 文档核实，尚未接入本次后端 |

依据：[GLM 接口及价格](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr)、[Unlimited-OCR 官方仓库](https://github.com/baidu/Unlimited-OCR)、[硅基流动多模态接入](https://docs.siliconflow.cn/docs/userguide/capabilities/multimodal-vision)、[MinerU 官方 API](https://mineru.net/apiManage/docs)。

其他值得参考的开源项目：

- [PaddleX](https://github.com/PaddlePaddle/PaddleX)：本次核对了官方预处理和版面结果协议。官方导出可直接运行 ORT，无需引入整个 SDK。
- [GLM-OCR](https://github.com/zai-org/GLM-OCR)：可参考其“布局后区域识别”实现；裸模型 API 不等于该完整系统。
- [MinerU](https://github.com/opendatalab/MinerU)：涵盖文字层、版面、OCR 和多格式输出，功能更完整，但整体引入会扩大集成范围。当前主分支与旧版部署文档差异较大，需固定版本；当前许可证含附加条款，不能直接假定所有版本都等同于本项目 MIT。[许可证原文](https://raw.githubusercontent.com/opendatalab/MinerU/master/LICENSE.md)
- [RapidLayout](https://github.com/RapidAI/RapidLayout)：适合作为轻量版面模块候选，但更换版本时仍须验证 V3 的输出与阅读顺序，不能只比较检测框。
- [MonkeyOCR](https://github.com/Yuliang-Liu/MonkeyOCR)：可参考区域检测、识别、关系恢复的分工；其流水线不意味着任意 OCR API 都能直接替换模型。

## 本次实际实现

```text
PPT/PPTX → Office 渲染 + XML 原文/备注 ┐
PDF      → 文字层/字体/坐标 + 页面渲染 ├→ PP-DocLayoutV3（本地 CPU）
                                     ↓
                           区域分类 + 阅读顺序 + 置信度
                                     ↓
             可靠正文 → 复用文字层并恢复自然段落
             表格    → 整个表格区域 OCR → OTSL/HTML/Markdown 结构
             公式    → 公式 OCR → LaTeX
             图表图像→ 原图裁剪 + 可见文字 OCR + 原始文字标签补漏
             缺字/编码异常/扫描正文 → 区域 OCR
                                     ↓
               覆盖检查 → 来源、坐标、原始响应、待复核信息
                                     ↓
               结构化 JSON → 独立翻译 → 静态网站 + transcript.md
```

所有非空页面都经过本地布局检测。不会因为 PDF 能复制文字，就跳过图表或矢量图检查。PPTX 继续保留 XML 与独立 PDF 渲染证据，speaker notes 继续保留。

**布局运行时**：固定官方 ONNX 版本，RGB、800×800 双三次缩放、0–1 浮点、NCHW，传入 `im_shape` 与 `scale_factor`。使用输出的第七列阅读顺序，按类去除重复框；普通 PPT 使用矩形区域，尚未移植官方实例 mask 的多边形后处理。针对样本页，0.5 阈值漏掉中间栏，改为 0.3 并结合去重、文字层补漏，低置信 OCR 内容标记待复核。[官方 ONNX 权重](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_onnx/tree/46bbdf188bb0a772c08aed74882ce7e51a8f1ea6)

**文字层可信检查**：不仅检查是否有文字，也检查编码、区域归属、嵌入图片交叠以及文字行之外的未解释前景。检测到同一段的行按区域重新组合；显式 bullet 保持独立。区域以外的原始文字不丢弃。此像素检查是启发式，不能证明文字层与视觉内容完全一致。

**表格**：Paddle 的 `Table Recognition:` 实测返回 OTSL。实现 `<fcel>/<ecel>/<lcel>/<ucel>/<xcel>/<nl>` 解码，检查矩形合并关系，输出保留 rowspan/colspan 的表格。初始标记缺失时保留原始响应并把表格标为待复核，不静默丢掉首格。

**图表**：无论有无文字层，都保留源图裁剪。使用文字转录任务，不使用会推导数据/趋势的 Chart Recognition 作为正文。OCR 漏掉的可提取标签由文字层补回；对应来源明确标记为图中可见文字。未覆盖图像达到阈值时保留整页证据图并提示复核；整页证据图不会把普通正文错误标为图表文字。

**成本控制**：单页默认最多 32 个 OCR 区域，可配置 1–100；发请求前检查该页区域数。所有外发请求仍受全局请求预算限制；区域请求不自动重试，网络超时设置为 60 秒。相同裁剪、提示词、模型与地址复用缓存；先存原始成功响应，再做本地结构转换，因此修复格式适配不必重新调用模型。页面处理沿用现有受限并发，页内按区域执行，未拼成大图一次识别，以免破坏区域对应关系。

## 实测结果与准确性边界

Windows x64 / Python 3.12 / ONNX Runtime 1.23.2 CPU，单会话 4 个计算线程，推理串行保护，多个页面复用模型。不是独立公开评测集，也没有做硬件间泛化测试。

| 项目 | 实际结果 |
|---|---|
| 官方模型文件 | 130,502,049 字节，约 130.5 MB / 124.5 MiB |
| ORT Windows Python wheel 下载量 | 约 13.5 MB；不等于最终客户端增量包体 |
| 模型加载后的独立 Python 工作集 | 约 208.5 MiB；加载阶段峰值约 300.3 MiB，**不含完整应用/实际推理峰值** |
| 27 页 Overview 布局耗时 | 缓存中记录的首次检测中位数约 0.754 秒/页；包括本模块预处理，少数冷启动页含会话初始化；不含 PDF 提取、云端和翻译 |
| 三栏页第一次检测 | 约 1.6 秒，含模型冷启动 |
| 27 页检测区域 | 300 个 |
| 可直接使用文字层的区域 | 268 个 |
| 需发 OCR 的区域 | 32 个，单页最多 10 个 |
| 不需 OCR 的页面 | 11 / 27 |
| 检测框外文字 | 11 行，保留并插入阅读顺序 |

27 页结果是**本地路由审计**：OCR 使用占位输出，不是 27 页全部识别正确的证明，不计为完整 OCR 精度测试。

真实 API 样本：

| 文件物理页 | 问题 | 实际处理 | 结果 |
|---|---|---|---|
| Overview 2 | 三栏问题被跨栏串起来 | 5 个布局区域，5 个文字层复用，0 OCR | 三个问题分别包含完整续行 |
| Overview 10 | 柱状图的数值、年份遗漏 | 4 个文字层区域 + 1 个图表 OCR | 保留原图；OCR 单独只识别部分值，文字层检查补齐数值与年份 |
| Overview 16 | 双栏正文 + 薪酬表格 + 跨栏段落 | 10 个文字层区域 + 1 个表格 OCR | 保留左右栏次序，表格 5 行×2 列，底部段落不再断成两段；首格 OTSL 异常标为待复核 |

两个成功的 OCR 区域累计 usage：输入 1,672 tokens，输出 207 tokens。这里只是识别用量，不含翻译、AI 问答、失败请求或此前调试的重复请求。

本次出现过一次流式长等待（包括旧自动重试约 885 秒）及一次 HTTP 500。改为非流式、60 秒网络超时、单次尝试后，后续成功请求返回较快，但不能将一次低延迟当成 SLA。免费 API 的稳定性仍需真实长期批处理验证。

纯扫描文档的区域 OCR 分支已用测试覆盖，但尚未对大量真实扫描页做准确率评估。当前只验证了 Paddle 硅基后端的真实调用；GLM/DeepSeek 区域协议不宣称达到同等实测覆盖。

## 成本计算与选择

云端识别成本应按 `Σ(图像/提示词输入 tokens × 输入单价 + 输出 tokens × 输出单价) / 1,000,000` 计算。按页收费的服务则单独使用其页价。失败、重试、限流、缓存命中和文本翻译要分项记账；“区域数减少”不是“费用按同样比例减少”。

| 服务 | 查询时价格依据 | 对 Coursebook 的含义 |
|---|---|---|
| 硅基 PaddleOCR-VL-1.5 | 官方价格页列输入、输出免费 | 当前识别调用可以很低成本试验；不能承诺永久免费、无限额或稳定低延迟 |
| 智谱 GLM-OCR | 官方文档列输入/输出均 0.2 元 / 百万 tokens | 完整服务已经很便宜，不能仅为了省几分钱而增加复杂安装 |
| 硅基 Qwen3.8-27B | 官方价格页列输入 3 元、输出 12 元 / 百万 tokens | 更适合通用理解和问答；整页长 JSON 转录的成本通常高于小型专用 OCR，但须按实际 usage 比较 |
| Unlimited-OCR / MinerU 云端 | 本次没有核实到可长期承诺的统一生产单价 | 按账户控制台、套餐、限制实测；不把免费体验额度计入长期成本假设 |

价格来源：[硅基流动官方价格](https://siliconflow.cn/pricing)、[GLM-OCR 官方说明](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr)。例如假设一份材料合计使用 100 万输入、20 万输出 tokens，GLM 按上述牌价为 **0.24 元**；Qwen3.8-27B 为 **5.40 元**。这只是同用量价格演算，不表示它们处理同一文件会使用相同 tokens。

文字层丰富的课件优先试本次混合模式；整页扫描、多区域密集页、低配置机器可以优先比较完整 GLM/Paddle/MinerU 服务。先用同一批样本测试缺字率、数字/符号错误、表格行列、阅读顺序、P95 延迟和实际金额，不用公开模型榜单直接替代课程测试。

## 使用与后续产品化

1. 开发环境安装 `python -m pip install -r requirements-layout.txt`。本机本轮已安装。
2. 应用 → 模型设置 → 高级 → 文档解析 → **本地版面 · 硅基 OCR**，配置本人硅基密钥。翻译、AI 助手单独选文本模型。
3. 版面组件显示“已就绪”后可用；本机官方模型已经就绪。新机器可点击下载或导入固定版本 `inference.onnx`，均核对 SHA256 后原子安装。
4. 先用复核界面的“重新识别本页”验证。普通模式保留原上限；混合模式单页上限为 `min(全局请求上限, 2 × 区域上限 + 6)`，包括翻译请求，不代表必然花费该次数。
5. 编译/导出增加 `transcript.md`，包含原文锚点、公式、图像和保留合并结构的 HTML 表格。双语与学习数据仍以 JSON/静态网页为主，Markdown 不承载全部交互数据。

当前官方下载源位于 Hugging Face，部分中国网络可能访问困难。已提供校验后的离线导入；**尚未验证一个与本固定 ONNX 完全相同的国内官方镜像**，不自动换用社区不同输出协议的权重。后续正式发行应增加经验证的国内组件下载源；本轮未打包或发布新版。

模型固定版本：`46bbdf188bb0a772c08aed74882ce7e51a8f1ea6`；SHA256：`45bf71750b00739a41fc209f132eb104a4d6b5bb29483c9078164d8b87cf28ba`。模型 Apache-2.0、ORT 等运行组件各保留自己的许可，Coursebook 的 MIT 不替代它们。

实现入口：`local_layout.py`、`hybrid_parser.py`、`otsl.py`、`markdown_export.py`。复现实测使用 `tools/benchmark_hybrid.py`；`--offline` 只做本地路由审计，不调用云端。最终验收记录见同目录 `hybrid-validation-2026-09-30.md`。
