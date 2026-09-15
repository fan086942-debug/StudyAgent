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

按模块实现并测试，完成后更新此处。尚未验证的能力不能视为已通过验收。
