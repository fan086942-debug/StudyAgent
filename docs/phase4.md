# Phase 4：练习、错题、复习计划与学习工作台

当前版本 0.4.0，补齐学习记录与个性化闭环。重启服务后自动创建四张新表：`practice_attempts`、`wrong_questions`、`study_plans`、`conversations`；既有课程、文件、索引和生成记录继续使用，不修改旧表的列。

## 功能与使用

网页有五个工作区：学习工作台、复习与生成、历史题库、错题与计划、对话记录。侧边栏保留课程与资料选择，检索、生成与计划沿用所选资料范围。手机通过左上角按钮打开侧栏。

1. 在题库或生成的模拟卷展开「练习与自评」，输入作答与错因，选择需要再练或已掌握。
2. 错题本按课程保存原题快照、作答、备注和错误次数。同一题重复出错只增加次数；正确重练将其标记为已掌握，再次出错会恢复待复习状态。也可独立切换掌握状态。
3. 查看近七天练习次数、最近一次自评正确率和待复习知识点。统计以 Asia/Shanghai 日期分组；没有记录时正确率为 null，不显示虚构分数。
4. 安排 1–30 天、每天 10–180 分钟的计划。主题留空时优先使用未掌握错题知识点，其次试卷标签，最后使用资料名称。任务包含阅读、主动回忆、练习、错题复盘；所有指定主题至少被安排一次。主题、时间、任务完成状态存入 SQLite。
5. 每次 Agent / RAG 问答保存回答、原文来源和工具轨迹快照，可以从对话记录重新打开。新问题仍独立检索，不自动把旧回答当成新问题的证据。

练习结果来自用户自评，未实现自动评分。演示模式保持原文摘录与规则规划；计划安排是确定性的记录驱动策略，不能宣称有经过验证的学习效果或模型能力评估。

## Agent 工具

保留七个资料与生成工具，新增四个：

| 工具 | 行为 |
|---|---|
| `get_learning_progress` | 读取实际练习次数、自评正确率、错题与任务完成数 |
| `list_wrong_questions` | 读取当前范围内待复习错题及服务端题目快照 |
| `create_study_plan` | 按 topics / days / daily_minutes 创建计划；需要明确的计划请求 |
| `generate_weakness_review` | 按真实错题知识点检索资料并生成提纲；缺少错题标签或资料时返回受控错误 |

例如「查看我的学习进度」「看看我的错题」「安排 7 天复习计划，每天 30 分钟」「生成薄弱知识点复习资料」。demo 对复杂主题与时长表达使用有限规则；指定主题建议使用表单，API 模式按工具 Schema 规划。

学习统计与计划结果来自服务端真实记录。Agent 展示确定性摘要，不展示规划模型捏造的成绩。生成成功的记录使用实际保存状态展示预览入口，不把任务成果丢弃成“没有引用”。请求内重复工具调用命中缓存，不重复保存计划或生成成品。

## 数据与隔离

- 练习只接受服务端原题 ID 或生成成品 ID + 题目下标，不接受客户端伪造题干、答案或知识点。错题引用键按课程唯一；快照不依赖试卷重解析后的题目外键。
- 所有读取、练习、掌握标记、计划任务和对话预览校验课程归属。Agent 中课程与资料范围仍从请求注入；过滤后的统计和错题不会扩大资料范围。
- 原题与生成题的来源快照用于复盘，生成题仍不写入历史题库。
- 同一进程通过锁串行更新错题与计划 JSON，符合项目单 worker 边界。此版本未新增公网认证或多用户隔离。
- 前端通过课程切换序号丢弃过期响应，并取消尚未完成的浏览器提问请求。服务端已接收的工作可能继续完成，结果保留在原课程记录中。

## API

以下路径均以 `/api/courses/{course_id}` 开头：

| 方法 / 子路径 | 功能 |
|---|---|
| `GET /progress` | 学习概况、七天练习与薄弱知识点 |
| `POST /practice` | 保存原题 / 生成题 / 错题重练的自评 |
| `GET /wrongbook` | 分页错题；`include_mastered` 控制已掌握记录 |
| `PATCH /wrongbook/{id}` | `{mastered: true/false}` |
| `POST /plans` | `{topics: [], days: 7, daily_minutes: 30, document_ids: null}` |
| `GET /plans` | 分页计划历史 |
| `PATCH /plans/{id}/tasks/{task_id}` | `{completed: true/false}` |
| `GET /conversations` | 分页对话记录 |
| `GET /conversations/{id}` | 历史回答、来源与轨迹快照 |

## 界面

极光 / 海盐 / 落日三种配色、侧栏工作区导航、学习概况、原生 SVG 知识轨道。配色、深色主题与课程选择保存在浏览器本地。支持 Ctrl / Cmd + K 快捷操作、Ctrl / Cmd + Enter 提问、拖拽上传、请求耗时反馈、复制回答、答案折叠与任务勾选。动画主要使用 transform / opacity；遵循 prefers-reduced-motion。没有远程字体、外部图片或新增前端框架依赖。

## 资料删除与空初始化

首次访问不自动选择数据库第一门课程，默认展示空资料库与 0 份可用资料；新建课程没有预置上传。用户主动选择的课程保存在浏览器，已有课程数据不会被初始化流程清空。

`DELETE /api/documents/{document_id}` 在确认后删除上传原文件、当前与历史 Embedding 索引、正文分块、试卷、题目与无引用知识点。已有练习、错题、生成记录和对话快照保留。处理中的上传 / 重建 / 试卷解析通过同一组锁阻止删除；文件路径必须匹配当前 uploads 目录与该资料 ID。删除前持久化 `deleting` 状态，跨存储删除失败时停止检索并允许重试，避免缺少原文件或索引的记录仍显示可用。

隔离浏览器验收使用 `python -m scripts.documents_preview` 与 `scripts/browser_documents.cjs`，覆盖已有后台资料时首次空状态、取消保留、确认删除、范围与统计刷新、刷新恢复及手机弹窗。结果见 [资料验收](evaluation-documents-ui.json)。

单文件上传默认上限 **200 MB**，前端提示与校验读取 `/health` 的 `max_upload_mb`，后端流式保存时再次校验；`.env` 的 `MAX_UPLOAD_MB` 可设置 1–200 MB。

课程选择框下方的「删除当前课程」需要二次确认。`DELETE /api/courses/{course_id}` 清理该课程全部原文件、各代检索索引、分块、试卷、题目、知识点、练习、自评错题、生成资料、复习计划和对话历史。其他课程及模型配置保留，删除后回到空选择和空资料库。业务请求正在执行时返回 409；删除过程中阻止新业务请求和模型切换，避免旧任务重新写入课程。清理失败保留课程并可再次删除，已删除的资料不会恢复。仅支持既有本机单 worker 模式。

课程界面验收运行 `scripts/browser_courses.cjs`，使用上述隔离服务；覆盖取消、忙碌重试、手机深色弹窗、确认清理、其他课程保留、空状态及刷新。结果见 [课程验收](evaluation-courses-ui.json)。

## 扫描 PDF OCR

扫描页或仅有少量页眉文字的图片页自动执行本地中英文识别。文字页直接提取，混合 PDF 保留物理页码和引用位置。PDF 渲染使用 [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html)，识别使用 [RapidOCR](https://github.com/RapidAI/RapidOCR/tree/v1.4.4/python/rapidocr_onnxruntime)，模型随依赖安装；识别不调用用户的 LLM API，无需额外密钥。

`OCR_ENABLED=true` 默认启用，`OCR_DPI=180` 可设置 96–300。限制每个 PDF 1000 页、总提取文字 200 万字符，每页渲染最长边 2400 像素。识别结果可能含公式、表格或低清文字误差，资料列表会显示核查提示。

网页单份 PDF 上传与资料重试使用后台处理，快速返回后每两秒更新页数进度，关闭页面不影响后台任务。原接口默认同步；上传表单增加 `background=true` 返回 202 与 processing 记录，重试可使用 `?background=true`。处理中资料不参与检索，完成索引后才变为 ready。课程删除与模型切换会等待任务结束。

每页 OCR 结果保存在本机 `data/ocr/{document_id}/page-{number}.json`，按文件摘要、识别设置和缓存版本校验，中断或索引失败后重试复用已识别页；损坏缓存重新识别。资料和课程删除同步清理缓存。服务重启将未完成任务标为失败，由用户主动重试，不自动处理历史文件。

处理中资料提供「取消处理」。`POST /api/documents/{id}/cancel` 返回 202 与 cancelling 状态，在当前 OCR 页 / 解析步骤 / 远程请求结束后停止；不强制打断正在执行的识别推理或网络调用。取消检查覆盖 PDF 页边界、每批 16 个 Embedding 片段及每批 100 个索引写入。最终状态 cancelled，不参与检索，原文件与已完成 OCR 页缓存保留，点击「重试 / 重建」继续。停止完成前不能重试或删除，刷新仍显示当前状态；已经完成或失败的任务不能再次取消。进度和最终提交通过互斥锁协调，避免取消后被旧任务覆盖成 ready。

取消功能用 `tests/test_processing_cancel.py` 与 `scripts/browser_cancel.cjs` 验证排队取消、页内取消、部分索引清理、缓存复用、刷新状态及手机布局，使用合成资料和隔离数据库。

使用 `scripts/make_ocr_fixture.py` 生成合成测试扫描页，`scripts/browser_ocr.cjs` 在独立资料库验证上传、自动更新、检索页码与缓存删除。本次不重新导入或处理用户提供的教材。

## 前端模型连接

模式按钮与侧栏「模型连接」打开配置面板。填写 Base URL、模型名称与 API Key，测试接口及 Tool Calling，保存后重建完整模型服务组，无需重启。数据库、上传资料及当前 Embedding 索引保持一致；本地字词检索与远程 LLM 可以组合使用。环境中的 Embedding 设置仍需在 `.env` 配置并重启。

| 接口 | 行为 |
|---|---|
| `GET /api/connection` | 模式、接口地址、模型、是否已保存密钥、检索方式；不返回密钥 |
| `POST /api/connection/test` | 验证给定模型的工具调用能力；不保存或切换配置 |
| `PUT /api/connection` | `{mode, base_url, model, api_key}`；保存并立即启用，已有同地址密钥可留空复用 |

配置接口仅允许本机、当前来源访问。更换接口地址必须重新输入密钥，避免向新服务误发已有凭据。有任务处理中时返回 409；所有 API 业务请求通过计数锁保护，保证一次调用使用同一套服务。配置先原子写入本机 `data/model-connection.json`，成功后更新服务，失败时保留原配置。密钥不写入浏览器存储，关闭面板后清空输入。

浏览器链路使用 `python -m scripts.connection_preview` 启动隔离服务，再运行 `scripts/browser_connection.cjs`。独立数据目录与模拟上游用于检查连接、启用、Agent 工具调用、刷新恢复、切回 demo 和手机布局。记录见 [连接验收](evaluation-connection-ui.json)；测试不代表真实模型质量。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
node --check app/static/app.js
```

`scripts/browser_workspace.cjs` 在隔离的 demo 服务中验证：真实拖拽上传、三步 Agent 调用、原题与生成题练习、自评错题去重与掌握、计划勾选、Markdown 下载、刷新后持久化、对话重开、快捷操作、深色主题、课程切换迟到响应、320/390/768/1024/1440px 宽度和减少动画偏好。使用既有 Playwright / Edge，不增加运行依赖。旧的 Phase 2 / 3 浏览器脚本已更新工作区导航。

真实模型服务尚未在本次开发验收中调用。离线测试与 MockTransport 可验证协议和工程行为，不能代替真实语义检索、模型生成与解题质量评测。

2026-10-08 验收：全量 76 项测试通过（两条既有上游弃用警告）；Ruff 和 JavaScript 语法检查通过。工作台端到端流程、旧 Phase 2 / 3 流程通过，JavaScript 错误 0，五种屏幕宽度无横向溢出。结果见 [浏览器验收记录](evaluation-workspace-demo.json)，桌面与手机截图见 `screenshots/`。
