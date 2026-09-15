# 开发记录

## 模块 1：初始化

- 新增 `pyproject.toml`、`.gitignore`、`.env.example`。
- `app/core/config.py`：校验模式、切块参数、API 必填配置。
- `app/core/errors.py`：可展示的错误类型。
- `app/main.py`：应用工厂、健康检查、请求 ID、脱敏请求日志。
- `tests/test_bootstrap.py`：健康检查与非法配置测试。
- 运行方式：`python -m uvicorn app.main:create_app --factory`。
- 初次受限环境无法访问包索引，已申请联网安装到工作区虚拟环境。
- 测试结果随实际执行更新，不能把语法检查替代端到端验收。

## 模块 1–4：配置、数据、解析、切块与 Provider

- 依赖安装成功；首批 12 项测试通过。
- 核心验证：SQLite 唯一约束与外键，三格式实际文件来源，切块无丢字与跨页污染，Provider 输出和超时。
- 已保存第一个 Git 阶段提交。

## 模块 5：导入与向量索引

- 新增 `app/api/documents.py`、`app/services/ingestion.py`、`app/rag/vector_store.py`。
- 用 `processing / ready / failed / stale` 限制可见性，SQLite 保存权威文本，Chroma 保存可重建向量。
- 15 项测试通过，包括重复文件、Embedding 失败、重试与索引无重复。

## 模块 6：RAG 问答

- 新增 `app/rag/retriever.py`、`app/services/qa.py`、`app/api/chat.py` 和请求 / 来源 Schema。
- 先做课程范围过滤，再查询向量；来源从 SQLite 恢复，模型只看到 id 与证据文本。
- 18 项测试通过，包括文档过滤、课程隔离、持久化、虚构引用与页码拦截。

## 模块 7：网页、评估与收尾

- 新增 `app/static/`、启动与示例脚本、24 条问题评估脚本、依赖锁文件。
- 模拟 HTTP API 完整链路通过后累计 19 项测试。
- 浏览器实际验证：上传三文件、检索提问、三张来源卡片、移动端布局通过。
- 补充中断恢复、模型指纹失效、文件大小、路径、忙状态、部分索引写入与服务重试测试，累计 23 项通过。
- Ruff 检查、JavaScript 语法检查和 pip 依赖检查通过。
- 两条上游测试依赖弃用警告已记录；不隐去警告或误报为失败。
- 尚未配置真实模型密钥，真实语义 RAG 与 LLM 质量验收待完成。未开始 Phase 2。
