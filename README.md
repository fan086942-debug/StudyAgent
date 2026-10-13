# StudyAgent · 多源学习资料复习助手

Phase 4：多格式资料 RAG + 试卷结构化 + 学习 Agent + 复习生成 + 错题与复习计划。

项目使用 Python 3.11、FastAPI、SQLite / SQLAlchemy。核心检索、工具注册和执行循环直接写在代码里，便于阅读和面试讲解。支持有来源的问答、复习提纲、模拟练习、Markdown 下载，以及练习自评、错题本、学习统计、复习计划和历史问答。

## Windows 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 ，首次从服务器本机创建账号后进入工作台，接口文档在 `/docs`。首个账号承接原有课程与资料，后续账号使用独立学习空间。当前使用一个 worker；HTTPS 部署设置 `AUTH_COOKIE_SECURE=true`。账号与启动优化说明见 [登录与简洁工作台](docs/auth-and-startup.md)。

默认 `STUDY_MODE=demo`：使用确定性的字符特征哈希向量与资料摘录，方便零密钥验证解析、数据库、索引、接口和来源。**演示模式不使用语义 Embedding 或 LLM，不能代表真实模型问答质量。**

连接模型：点击右上角模式按钮或左侧「模型连接」，填写 OpenAI 兼容接口的 Base URL、模型 ID 和 API Key，点击「测试连接」验证工具调用，再「保存并启用」。立即生效，无需修改 `.env` 或重启；Agent、资料问答、复习生成和试卷抽取共用该连接。接口需支持 `/chat/completions`、Tool Calling 和 JSON 输出，测试只发出一次小型工具请求。相关资料片段会发送到所配置的模型服务。

首个账号的连接保存在 `data/model-connection.json`，后续账号保存在 `data/users/<用户ID>/model-connection.json`；密钥不会回传浏览器或写入 localStorage。新账号从演示模式开始，不继承首个账号或环境中的 LLM 密钥。文件属于忽略的本地数据，未提供密钥加密。保存的连接优先于默认 LLM 配置，允许切回离线演示，重启后继续生效。切换 LLM 不改变现有索引：默认仍用字词哈希检索，无需 Embedding API，但它不具备语义检索能力。

DeepSeek 官方接口填写 `https://api.deepseek.com`，Flash 的 API 模型 ID 为 `deepseek-flash`，不是官网展示名 `DeepSeek-V4.1-Flash`。当前适配使用非思考模式，支持连接测试中的强制工具调用和 Agent 后续工具轮次；其他厂商请求不添加该参数。协议依据见 [DeepSeek 接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

「测试连接」仅验证接口和基础工具调用，不等于长教材生成已通过。问答和生成使用 JSON 输出，兼容完整 JSON 代码围栏；结构异常最多进行一次格式纠正，仍保留引用校验，输出截断不盲目重复。整份资料学习缓存已校验的章节整理，相同资料再次提交时可续作，出题仍由网站 Agent 调用模型完成；删除资料/课程同时清理相关缓存。回答和失败提示展示模型报告的 tokens 用量，不能据此推算或退还服务商实际账单。真实接口的独立合成资料验收见 [模型验收](docs/evaluation-model-learning.json)。

如需真实语义 Embedding，在本地 `.env` 设置 `STUDY_MODE=api`，分别填写 LLM 与 Embedding 的 `BASE_URL`（包含 `/v1` 等实际前缀）、`API_KEY`、`MODEL`，并设置 Embedding 实际返回维度。修改 Embedding 配置需重启并重新索引；UI 提供重建入口。不同厂商的兼容程度与模型质量需真实验证。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

自动测试使用独立临时数据目录，不修改用户资料。真实 API 验收和离线测试分别记录。

## 依赖用途

| 依赖 | 用途 |
|---|---|
| fastapi / uvicorn | API、接口文档、ASGI 服务 |
| python-multipart | 文件上传 |
| pydantic / pydantic-settings | Schema、配置和环境变量 |
| sqlalchemy | SQLite ORM、事务 |
| chromadb | 本地持久化向量索引、metadata 过滤 |
| pypdfium2 / rapidocr-onnxruntime | PDF 逐页提取、渲染与本地中英文 OCR |
| pypdf | PDF 测试样本与密码保护校验 |
| python-pptx | 幻灯片、表格及备注提取 |
| python-docx | Word 标题、段落、表格 |
| httpx | 模型 HTTP 调用；测试 FastAPI 接口 |
| pytest / ruff | 测试与静态检查，仅开发使用 |
| reportlab | 生成可复现的测试 PDF，仅开发使用 |

## 学习与设计资料

- [架构与数据流](docs/architecture.md)
- [模块讲解与面试问题](docs/learning-notes.md)
- [评估方法与结果](docs/evaluation.md)
- [Phase 2 设计、运行与面试讲解](docs/phase2.md)
- [Phase 3 生成设计、使用与验收](docs/phase3.md)
- [Phase 4 学习闭环、Agent 工具与新版工作台](docs/phase4.md)

## 开发进度

Phase 1 / 2 / 3 / 4 代码已实现，离线单元 / 集成测试及真实浏览器流程已验证。**真实模型服务质量尚待验收**，不能把模拟 HTTP 测试或演示模式当成在线语义 RAG、试卷抽取或模型工具选择的质量验证。

### 已实现

- 课程创建、三格式上传、文件内容去重、处理状态与失败重试。
- PDF 物理页码、PPTX 幻灯片序号与备注、DOCX 标题 / 段落 / 表格定位。
- 切块、可替换 Embedding、Chroma 持久化、课程与文档过滤。
- 独立 LLM Provider、上下文长度控制、结构化回答与引用 ID 校验。
- 失败索引隔离、服务中断恢复、模型切换后重建提醒。
- 中文网页、来源原文、原文件入口、请求 ID、耗时与模型实际 usage。

### 直接体验

如果项目环境已安装，在项目目录运行：

```powershell
.\scripts\start.ps1
```

若 PowerShell 执行策略禁止运行脚本，直接使用前面的 `python -m uvicorn ...` 命令，无需修改系统策略。

1. 打开 http://127.0.0.1:8000 ，选择或创建课程。
2. 上传 PDF / PPTX / DOCX，等到资料显示「可检索」。
3. 输入问题，或勾选资料限定范围。
4. 对照来源卡片的原文和位置核查回答。

首次进入不自动选中已有课程，资料列表与可用资料计数默认为空；新建课程也不会预置示例资料。选择课程后才加载其已保存内容，返回时可以恢复上次主动选择的课程。每份已上传资料旁提供「删除」，确认后移除原文件、所有版本的向量索引及该试卷题目；已保存的复习资料、错题和对话快照保留。删除中途失败的资料会停止参与检索，点击「删除」可重试。

### 第四阶段：学习闭环与新版界面

打开工作台后通过侧栏切换五个工作区。题库与模拟卷的「练习与自评」可保存作答和错因，错题本支持重练与掌握标记；学习概况按真实记录展示，正确率来自最近一次自评。复习计划支持主题、天数、每天分钟数与任务勾选；Agent / RAG 回答自动保留历史快照。无需新增运行依赖，重启自动创建新增表。

新增学习记录、整份资料学习与教材/试卷关联工具，总计 13 个。可以问「查看我的学习进度」「看看我的错题」「安排7天复习计划，每天30分钟」「生成薄弱知识点复习资料」「总结这个 Word 的知识点」「根据 PPT 出复习卷」「教材对应试卷」「试卷对应教材」。指定主题建议使用计划表单。

指定知识点出题可以直接在学习 Agent 中输入「根据层次聚类出两道题目」或「给我出两道层次聚类的题目」。系统识别知识点、中文/数字题数及题型，检索当前资料范围后调用模型生成新题、参考答案和解析，保存后从回答下方预览、练习或下载。每次按知识点出题支持 1–12 道；已有历史题查询、普通概念问答和「不要出题」不会触发生成。真实 DeepSeek 的同句请求已用独立合成资料验证，见 [模型出题验收](docs/evaluation-topic-generation.json)；网页预览与导出见 [界面验收](docs/evaluation-topic-generation-ui.json)。

学习 Agent 支持自动保存的会话上下文：可以接着问「再来两道题」「解释第二题」「它怎么计算距离」。网页自动发送当前会话 ID，服务端保留最近 10 轮、最多 20,000 字符，最多 100 个会话；上下文保存在各账号的 SQLite 学习空间中，闲置两小时后清空；服务重启后可继续。刷新当前标签页可恢复会话和已勾选资料，切换课程/勾选资料范围或点击「新对话」会开启新会话；资料状态或文件发生变化时清空旧上下文。历史消息用于理解追问，事实依据仍来自本轮检索，生成题序号不会被当成历史试卷题号。连续出题携带已出题干，重复题不会保存。见 [真实模型多轮验收](docs/evaluation-agent-memory.json) 和 [本轮功能测试](docs/functional-review.md)。API 调用方可在 `/api/agent` 中提供 32 位小写十六进制 `session_id`；省略时保持独立请求。

「学习记录」和「当前对话」中的每条问答均提供「删除对话」。确认后删除已保存记录；若它属于仍保留的临时会话，同时重置该会话上下文，防止追问继续引用已删内容。对应会话正在处理时返回 409，请待处理完成后删除。刷新后删除结果仍生效，支持旧版记录与资料问答记录。API 为 `DELETE /api/courses/{course_id}/conversations/{conversation_id}`。

支持 PDF（扫描件可 OCR）、PPTX、DOCX；旧版 PPT / DOC 请先另存为 PPTX / DOCX。在资料旁点击「总结知识点」可逐段整理并保存；「复习与生成」也可选择只总结或同时出卷，再查看知识点总览。资料旁「找关联试题」、总结中的历史题按钮和题库中的「定位教材 / 课件依据」提供双向学习入口，关联卡片展示题目、匹配知识点及真实页/幻灯片/文档块位置，可直接进入练习。参考资料与试卷分别限定范围；未选择试卷时查找本课程全部已解析试卷。没有历史卷时可以根据资料生成新卷。

知识点标签匹配优先，未命中标签的题目还可按正文相似寻找候选关联；这不是经过语义模型验证的考点映射。已保存的总结按来源正文和位置检查有效性，删除或重建后失效的总结仅作为历史快照保留。具体实现与代码清理见 [通用学习模式与审计](docs/material-learning-audit.md)。

界面支持极光 / 海盐 / 落日三种配色与浅色 / 深色主题，点击右上角调色板切换，偏好自动保存。提供知识轨道、卡片光晕与轻微视差、点击反馈、滚动进度和回到顶部；遵循系统减少动画偏好。另支持拖拽上传、Ctrl / Cmd + K 快捷操作、Ctrl / Cmd + Enter 提问、加载计时、复制回答与手机资料抽屉。具体接口、数据隔离与使用边界见 [Phase 4 文档](docs/phase4.md)。

### 第三阶段：生成复习资料与模拟卷

重启服务后自动新增生成记录表，无新增依赖。在「生成复习资料与模拟卷」填写知识主题，沿用左侧资料选择范围；可生成复习提纲，或按题型、题数、难度生成模拟练习。每部分保留原文依据，历史记录可再次预览，并下载完整 Markdown 或不附答案的题目卷。

- 复习资料：概念总结、关键点、易错点与引用。
- 模拟卷：选择 / 简答 / 计算三种单一题型，1–12 道题、1–8 个主题、参考答案与解析。
- Agent 可直接输入「生成 A* 评价函数复习资料」，从回答中的入口查看成品。
- 演示模式仅做原文整理与摘录简答，不提供模型推理或真实难度评估；其他题型需 API 模式。
- 缺少依据、引用无效、题数不符或模型输出截断时拒绝保存，页面提示重试或补充资料。

详细流程与边界见 [Phase 3 文档](docs/phase3.md)。复现默认检索阈值下的四个原创离线用例：

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_generation --output data/evaluation-generation-demo.json
```

### 第二阶段：试卷与 Agent

无需新增运行依赖。重启服务后自动创建新增的四张表，保留原有课程、资料和索引。网页默认使用学习 Agent，也可切回 Phase 1「资料问答」。

```powershell
.\.venv\Scripts\python.exe -m scripts.make_exam_fixtures
```

1. 上传教材，再将 `data/exam-samples/2025期末练习卷.docx` 按「试卷」类别上传。
2. 在「历史题库」查看解析状态和题目。旧的试卷资料点击「解析题目」即可补提取。
3. 问「A* 以前怎么考过？」或「解释 2025 期末第 12 题」。展开「工具执行过程」核查参数和结果。
4. 点击题目卡片的「查看资料并分析此题」，查看参考资料、解析和关联题。

演示模式使用数字题号规则，提取选项与明示分值；仅从 `【知识点：…】` 提取显式标签，不推断难度或生成答案。API 模式按有界原文窗口抽取题目，标注知识点和难度，通过模型工具调用选择任务；服务必须支持 Chat Completions `tools` / `tool_calls`。页码来自解析器，知识点和难度是可出错的模型标注，需要人工核对。

`AGENT_MAX_STEPS` 限制总工具调用数，`AGENT_CONTEXT_CHARS` 限制发给规划模型的累计上下文字符数。`EXAM_BATCH_CHARS` 和 `EXAM_MAX_BATCHES` 限制原文抽取规模。试卷解析失败有独立状态，可重试，不影响已完成的 RAG 索引。

复现工具选择评估：

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_agent --output data/evaluation-agent-demo.json
```

[离线结果](docs/evaluation-agent-demo.json)：6 份原创资料、3 套试卷、13 道题、12 条问题，规则路由首工具命中 12/12。这个小样本指标不代表真实模型准确率；部分短查询在哈希检索下没有达到相似度阈值，报告保留实际来源数量。配置真实服务后可加 `--mode api`，会产生模型用量，答案仍需人工审核。

生成自编示例文件：

```powershell
.\.venv\Scripts\python.exe -m scripts.make_fixtures
```

文件位于 `data/samples`。示例问题：「A* 的 g(n) 表示什么？」。浏览器验证生成的示例课程已经留在本机数据中；新安装需要自己上传。

### 真实 API 验收

1. 编辑 `.env`，设置 `STUDY_MODE=api`，填好两套 Provider 配置。不要提交 `.env`。
2. 停止并重新启动服务。
3. 原演示索引会标记「需要重建」，点击「重试 / 重建」，或新建课程上传资料。
4. 再提问，确认界面为「API 模式」，核对回答、引用、无答案拒答和日志 usage。
5. 可以执行下面的 `--mode api` 评估。它会向配置服务发送自编资料和问题，产生实际 API 用量；输出仍需人工评价答案是否正确。

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate --mode api --output data/evaluation-api.json
```

模型服务须支持实际输入长度；如果提示上下文超限，降低 `CONTEXT_CHAR_BUDGET`。默认字符预算不是精确 Token 计数。`EMBEDDING_DIMENSIONS` 必须对应模型实际返回维度；本项目不自动修改模型输出维度。

### 复现演示评估

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate --output data/evaluation-demo.json
```

当前基线保存在 [docs/evaluation-demo.json](docs/evaluation-demo.json)，包含每条问题的期望来源、实际召回、回答、耗时和人工审核空字段。只有 3 份合成资料、24 条问题；不能用于宣称真实课程准确率。

### 复现依赖

`requirements.lock` 记录本机 Python 3.11 / Windows 已验证的完整依赖版本。优先在相同环境复现：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

锁文件包含开发依赖。其他平台应先验证兼容性，再生成自己的锁文件。当前测试依赖输出两条上游弃用警告，测试可通过；它们不代表运行时失败。

## API 概览

| 方法与路径 | 功能 |
|---|---|
| `POST /api/generate` | 生成并保存复习资料或模拟卷 |
| `POST /api/study` | 按整份资料分章 / 小节读取，生成重点与复习卷学习包，无需 topics |
| `GET /api/courses/{id}/artifacts` | 分页生成历史；子路径 /{artifact_id} 读详情、/{artifact_id}/download 下载 |
| `GET /health` | 服务状态和模式，不暴露密钥 |
| `POST /api/courses`、`GET /api/courses` | 创建、列出课程 |
| `DELETE /api/courses/{id}` | 删除课程、资料索引及全部学习记录 |
| `POST /api/courses/{id}/documents` | 上传并同步处理，成功返回 201 |
| `GET /api/courses/{id}/documents` | 资料列表、状态与错误 |
| `POST /api/documents/{id}/retry` | 失败重试或重新索引 |
| `POST /api/documents/{id}/cancel` | 停止资料解析 / OCR / 索引，保留原文件及页缓存 |
| `GET /api/documents/{id}/file` | 原文件，PDF 支持物理页定位 |
| `POST /api/search` | 检索片段，便于调试 |
| `POST /api/chat` | 回答、引用、阶段耗时与 usage |
| `POST /api/agent` | 自动选工具、观察、继续执行、最终回答及 trace |
| `GET /api/agent/tools` | 工具定义与 JSON Schema |
| `GET /api/courses/{id}/papers` | 试卷及独立解析状态 |
| `POST /api/documents/{id}/extract-questions` | 提取或重新解析试题 |
| `POST /api/courses/{id}/questions/search` | 按试卷、题号、关键词、知识点、题型查题 |
| `GET /api/courses/{id}/questions/{question_id}` | 获取具体题目及真实来源 |
| `POST /api/questions/{question_id}/analyze` | 结合课程资料分析指定题目 |
| `GET /api/courses/{id}/knowledge-points` | 已关联试题的知识点 |

提问 JSON：`{"course_id":"课程ID", "question":"A* 是什么？", "document_ids":["可选资料ID"]}`。省略 `document_ids` 表示整个课程；空数组视为无效输入，避免无意扩大查询范围。

`/api/agent`、`/api/chat`、单题分析使用同一提问结构。题库搜索示例：`{"paper_name":"2025", "number":"12"}`；题号在不同大题中可能重复，搜索返回多个候选，具体题目使用唯一 ID。

## 如何阅读代码

| 阅读顺序 | 文件 | 核心问题 |
|---|---|---|
| 1 | `app/main.py`、`app/core/config.py` | 服务如何启动、配置如何校验？ |
| 2 | `app/models/__init__.py`、`app/api/documents.py` | 课程和资料怎样持久化？ |
| 3 | `app/rag/parsers/`、`app/rag/chunker.py` | 原始文件如何变成有位置的片段？ |
| 4 | `app/rag/embedding.py`、`app/rag/vector_store.py` | 文本怎样变成向量并保存？ |
| 5 | `app/services/ingestion.py` | 多个步骤失败时怎么恢复？ |
| 6 | `app/rag/retriever.py`、`app/services/qa.py` | 怎样找证据、约束回答并校验引用？ |
| 7 | `tests/`、`scripts/evaluate.py` | 如何证明功能可用、量化效果？ |
| 8 | `app/services/exam_parser.py`、`app/services/exams.py` | 怎样切题、校验原文和保存关联？ |
| 9 | `app/agent/tools.py`、`planner.py`、`agent.py` | 怎样定义工具、规划、回传观察和结束循环？ |

## 已知边界

- 单文件上传上限默认 **200 MB**（200 × 1024 × 1024 字节），前后端统一读取 `/health` 的 `max_upload_mb`；`.env` 中 `MAX_UPLOAD_MB` 可设置 1–200 MB。
- 课程选择框下方的「删除当前课程」需要二次确认，清理该课程全部资料、索引及学习记录；其他课程与模型配置保留。删除后回到空资料库，失败可重试，已清理资料不会恢复。课程删除时阻止业务请求和模型切换，已有任务执行时返回 409。详情见 [Phase 4](docs/phase4.md)。
- 扫描 PDF 自动执行本地中英文 OCR，混合 PDF 保留原文字层和物理页码；公式、表格、复杂双栏和低清图片的识别仍需人工核查，不提供图像语义理解。
- DOCX 逐段 / 表格切块，短标题可能形成小片段；后续可按章节合并并保存位置范围。
- 纯向量检索基线，无 BM25 / Reranker；参数需在自己的课程开发集上调优。
- 引用 ID 校验与真实位置展示不能证明模型每一句话都被证据支持，需要人工 QA。
- 支持登录和用户学习空间隔离；保持单 worker，没有跨进程任务队列。Render 免费实例的本地 SQLite / 上传文件会在重启或部署后丢失，持久化部署需要外部存储或持久磁盘。
- 题库检索使用关键词与知识点关联，尚无独立题目向量索引；同义知识点只做全半角、空白和大小写归一化，不做语义合并。
- 规则题目解析支持常见数字题号，复杂多栏、公式、子题和答案混排需要人工核验；API 的长题跨窗口抽取也可能遗漏。
- 普通知识主题生成采用检索；整份资料学习包读取当前范围的全部已索引正文，按识别章节 / 小节分段整理再按章节题数蓝图出题。章节来自原文或 OCR 标题，不代表人工核对完整目录；只支持单一题型和 Markdown 导出，尚无人工编辑和生成任务队列。
- 对话历史保存回答、来源和工具轨迹快照；学习 Agent 的当前会话上下文保存到用户 SQLite，服务重启后可续接，资料问答（RAG）保持独立请求，没有跨新对话的自动记忆。
- 个性化基于用户练习自评与知识点标签；未实现自动评分、能力诊断或经过效果评测的自适应学习策略。

## Render 部署与响应优化

使用仓库中的 `.python-version`（Python 3.11），构建 `pip install .`，启动 `uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT`，保持一个 worker。空 Render 空间允许创建首个独立账号，HTTPS Cookie 自动启用。部署失败原因、性能实测和免费实例的数据限制见 [响应优化与 Render 部署](docs/performance-and-render.md)。
