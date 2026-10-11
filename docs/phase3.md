# Phase 3：复习资料与模拟卷

第三阶段在既有 RAG 和题库旁新增生成服务：按知识主题检索教材、课件、笔记，生成结构化内容，通过校验后保存，再供网页和 Agent 预览、下载。历史原题仍在 Phase 2 题库中，生成练习不写入历史题库。

## 使用

重启服务，SQLite 自动新增 `study_artifacts` 表，不改旧表结构，无新增依赖。

1. 创建课程并上传参考资料。左侧勾选资料可限定生成范围。
2. 在「生成复习资料与模拟卷」填写主题，例如「A* 评价函数，BFS 队列」。
3. 选择复习提纲，或设置模拟卷题数、题型、目标难度。
4. 点击「生成并保存」，对照原文快照核查内容。
5. 从生成记录再次打开，下载完整 Markdown 或不附参考答案的题目卷。

复习提纲含概念总结、关键点和有依据的易错点；模拟卷含题目、参考答案、解析和来源。题型支持选择、简答、计算，每次选择一种题型；题数 1–12，主题 1–8，每个主题至少一道题。生成是同步请求，处理中按钮禁用；单进程只允许一个生成请求，其余返回 409。

Agent 示例：「生成 A* 评价函数复习资料」「生成 A* 评价函数模拟卷 3道简答题」。生成工具返回记录入口，完整内容独立存储，避免把整份练习卷再次塞进规划模型上下文。API 模式由模型提取参数；demo 仅识别常见表达，复杂要求推荐使用表单。

## 演示与 API 模式

- demo：复习资料摘录检索原文；模拟卷仅生成「阅读材料并概括」的简答模板，参考答案也是原文摘录。原文片段不足时返回错误，不用重复题凑数。不评估难度，不生成选择题或计算题。
- api：通过现有兼容 Chat Completions 服务生成 JSON。题型、题数、主题覆盖、难度标签和引用受到校验；答案正确性、易错点准确性和难度合理性仍需人工核验。
- 未命中任何主题的可用依据时，整次生成失败，提示补充资料。不会只生成部分主题却把请求标为成功。
- 演示使用哈希检索，短查询可能没有命中；可写完整的知识短语。它不代表语义模型质量。

题目卷省略单独答案、解析和来源原文附录。demo 题干本身是阅读材料，依然含用于概括的内容；此功能不是防作弊或考试权限控制。

## 数据与来源

`study_artifacts` 保存课程、类别、标题、模式、时间、提醒及 JSON 快照。快照包括请求参数、结构化正文、实际检索原文和位置、模型 usage、耗时。只新增表，旧课程、资料、试题和索引不受影响。重新索引不改变已保存快照；原文件链接仍指向当前资料，因此历史快照是生成时依据，不保证与后续改动后的文件相同。

服务先核验课程与所选资料归属，再排除试卷。仅检索当前索引配置匹配的 ready 资料。每个主题独立检索，共用 `CONTEXT_CHAR_BUDGET`，按主题平分文本额度；相同 chunk 去重共享编号，每主题最多 8 个片段。每部分必须引用该主题检索到的来源，不能跨主题借用无关编号。

资料位置全部来自后端 Source；模型只收到来源 ID 和原文。校验拒绝不存在的引用、缺失主题、错误题数或题型、重复题干、截断 JSON、无效选择题选项与答案以及自行书写的页码。校验不等于事实核验：有效引用 ID 不能证明结论受到原文支持。

生成和验证全部成功后，才在单次 SQLite 事务中保存。失败不留半份成品，可重新点击生成。当前没有后台任务队列、断点续写或跨请求幂等键；请求中断后若服务已完成，先刷新历史，避免再次点击造成重复记录。Agent 仍使用本次请求内的重复调用缓存。

## API

| 方法与路径 | 功能 |
|---|---|
| `POST /api/generate` | 生成并保存，成功 201 |
| `GET /api/courses/{id}/artifacts?limit=30&offset=0` | 分页历史记录 |
| `GET /api/courses/{id}/artifacts/{artifact_id}` | 完整保存快照 |
| `GET /api/courses/{id}/artifacts/{artifact_id}/download?include_answers=true` | Markdown 下载，false 为题目卷 |

```json
{
  "course_id": "课程ID",
  "kind": "mock_exam",
  "topics": ["A* 评价函数"],
  "question_count": 3,
  "question_type": "short_answer",
  "difficulty": "medium",
  "document_ids": ["可选参考资料ID"]
}
```

`kind` 可为 `review` 或 `mock_exam`；省略 `document_ids` 使用整个课程的可用参考资料，空数组会被拒绝。review 忽略题数、题型与难度选项。不存在的课程返回 404，跨课程资料返回 400，资料不足或忙状态返回 409，非法输入返回 422，模型输出不合格返回 502，超时返回 504。

`GENERATION_MAX_TOKENS=8000` 控制单次模型输出上限；若服务输出上限较小，减少题数或调整配置。输入按字符控制，不是精确 Token 计数。未新增供应商参数或密钥设置。

## 阅读顺序与面试要点

1. `app/schemas/generation.py`：将自然语言产物变成可验证、可渲染的数据结构。
2. `app/services/generation.py`：限定范围、逐主题检索、统一编号、校验、事务保存和导出。
3. `app/llm/generation_provider.py`：独立模型边界、输出格式契约、截断处理与真实 usage。
4. `app/api/generation.py` 和 `app/static/app.js`：生成、历史、预览、答案折叠和下载。
5. `app/agent/tools.py`：注册两种生成工具，课程与文档范围由后端注入。
6. `tests/test_generation.py`：离线流程、模拟模型协议及拒绝路径。

为什么不用普通问答接口生成长文本？结构化生成需要覆盖多个主题、严格题数、答案分离和持久化，约束比一次问答更强。为什么保存完整来源快照？后续索引可以变化，历史产物仍需能够审计。为什么没有为生成练习创建 Question？Question 表表示历史原卷事实，模型生成内容不能混淆为原题。为什么采用单一题型？当前契约简单清楚；混合题型、总分蓝图、DOCX/PDF 导出和人工编辑可后续扩展。

## 验收与复现

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
node --check app/static/app.js
.\.venv\Scripts\python.exe -m scripts.evaluate_generation --output data/evaluation-generation-demo.json
```

默认阈值下的 4 个原创用例见 [离线结果](evaluation-generation-demo.json)，覆盖单主题复习、多主题复习、三道模板题和无依据拒绝。人工事实审核字段保持空白。加 `--mode api` 会读取本地配置并产生模型调用，不等于通过真实质量验收。

浏览器脚本 `scripts/browser_phase3.cjs` 使用 Playwright + Edge；`PLAYWRIGHT_MODULE` 指向已安装的 Playwright，`STUDY_URL` 指向独立 demo 服务。先执行：

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; from scripts.evaluate_generation import make_sample; make_sample(Path("data/phase3-notes.docx"))'
```

实际验证项目：上传原创笔记、复习摘录、三道模板题、答案展开、题目卷下载、刷新后历史读取、Agent 生成入口、390px 移动布局。真实模型质量尚未在线验收。
