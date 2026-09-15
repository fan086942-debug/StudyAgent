# StudyAgent · 多源学习资料复习助手

Phase 1：PDF / PPTX / DOCX → 解析 → Chunk → Embedding → Chroma → RAG → 回答与来源。

项目使用 Python 3.11、FastAPI、SQLite / SQLAlchemy，核心检索与问答流程直接写在代码里。当前阶段是 RAG 基础；Tool Calling、Agent Loop、试卷结构化与个性化是后续阶段。

## Windows 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 ，接口文档在 `/docs`。当前 MVP 用于本机单用户，使用一个 worker；不要直接暴露到公网。

默认 `STUDY_MODE=demo`：使用确定性的字符特征哈希向量与资料摘录，方便零密钥验证解析、数据库、索引、接口和来源。**演示模式不使用语义 Embedding 或 LLM，不能代表真实模型问答质量。**

真实模式：在本地 `.env` 设置 `STUDY_MODE=api`，分别填写 LLM 与 Embedding 的 `BASE_URL`（包含 `/v1` 等实际前缀）、`API_KEY`、`MODEL`，并设置 Embedding 实际返回维度。服务调用兼容的 `/chat/completions` 与 `/embeddings`。不同厂商的兼容程度需要真实验证。上传资料片段会发送到所配置的服务。

API Key 仅在本地 `.env` 保存。模式、Embedding 模型、服务地址或维度改变后需重新索引；UI 提供重建入口。修改配置后重启服务。

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
| pypdf | 文本型 PDF 的逐页提取 |
| python-pptx | 幻灯片、表格及备注提取 |
| python-docx | Word 标题、段落、表格 |
| httpx | 模型 HTTP 调用；测试 FastAPI 接口 |
| pytest / ruff | 测试与静态检查，仅开发使用 |
| reportlab | 生成可复现的测试 PDF，仅开发使用 |

## 学习与设计资料

- [架构与数据流](docs/architecture.md)
- [模块讲解与面试问题](docs/learning-notes.md)
- [评估方法与结果](docs/evaluation.md)

## 开发进度

Phase 1 代码已实现，离线单元 / 集成测试及真实浏览器流程已验证。**尚未接入真实模型服务验收**，不能把模拟 HTTP 测试或演示模式当成在线语义 RAG 质量验证。

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
| `GET /health` | 服务状态和模式，不暴露密钥 |
| `POST /api/courses`、`GET /api/courses` | 创建、列出课程 |
| `POST /api/courses/{id}/documents` | 上传并同步处理，成功返回 201 |
| `GET /api/courses/{id}/documents` | 资料列表、状态与错误 |
| `POST /api/documents/{id}/retry` | 失败重试或重新索引 |
| `GET /api/documents/{id}/file` | 原文件，PDF 支持物理页定位 |
| `POST /api/search` | 检索片段，便于调试 |
| `POST /api/chat` | 回答、引用、阶段耗时与 usage |

提问 JSON：`{"course_id":"课程ID", "question":"A* 是什么？", "document_ids":["可选资料ID"]}`。省略 `document_ids` 表示整个课程；空数组视为无效输入，避免无意扩大查询范围。

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

## 已知边界

- 文本 PDF 优先；复杂双栏、公式和图片理解、OCR 暂未实现。
- DOCX 逐段 / 表格切块，短标题可能形成小片段；后续可按章节合并并保存位置范围。
- 纯向量检索基线，无 BM25 / Reranker；参数需在自己的课程开发集上调优。
- 引用 ID 校验与真实位置展示不能证明模型每一句话都被证据支持，需要人工 QA。
- 本机单用户、单 worker；无登录权限系统与持久化任务队列，不直接用于公网多用户部署。
- 试卷暂作为普通文档；Agent Loop、题目解析、复习资料生成属于 Phase 2 / 3。
- 没有历史聊天记忆；每次问题独立检索。错题与个性化属于 Phase 4。
