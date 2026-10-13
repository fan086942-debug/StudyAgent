# Learning Studio 与真实 Agent 进度

在 G:\StudyAgent 上实现，沿用本项目 FastAPI、原生 HTML/JS、SQLite 账号和课程资料隔离。新增 workspace.css/workspace.js 统一品牌、色彩和动态交互。主功能完整保留，桌面导航可收起，登录与工作区合并。历史页可筛选当前已加载的对话、查看来源和删除。

## 参考项目评估

阅读 [ai-writing-assistant](https://github.com/tbyang28/ai-writing-assistant) 的 feat/public-community 分支 README、App.vue、Sidebar.vue、main.css、前端依赖、NestJS 启动与 AI controller，并查看其原生编辑器截图。采纳的是 [侧栏按工作场景收起](https://github.com/tbyang28/ai-writing-assistant/blob/feat/public-community/frontend/src/components/Sidebar.vue)、[流式状态与中止处理](https://github.com/tbyang28/ai-writing-assistant/blob/feat/public-community/backend-ts/src/ai/ai.controller.ts) 两个可用于学习产品的设计。界面与接口独立编写，未复制参考仓库代码/素材；未迁移 Vue/NestJS/PostgreSQL 架构。写作项目的正文 revision 防覆盖机制对当前问答工作区无直接用途，保留现有身份、课程与会话 epoch 保护。

## 进度接口

POST /api/agent/stream 使用现有 AgentRequest、Cookie 登录和资料范围校验。非法范围在流开始前返回普通 HTTP 错误；有效请求以 text/event-stream 返回 status、tool、result 或 error 事件。

- status 表示规划或来源校验；tool 表示真实工具开始/完成，包含步数、工具名、目的、状态与耗时。没有假百分比、原始工具参数或未校验答案。
- result 使用现有 AgentResponse，仅完成校验并保存后发送；原 POST /api/agent 仍可用。
- 工作线程独立持有模型连接使用计数，在流响应头返回后仍阻止模型切换与课程删除，直到执行结束。
- 断开连接设置线程取消标志；Agent 在规划和工具之间检查，未完成回答不保存。当前正在执行的模型/工具调用可完成，已生成的文件不回滚。停止不是外部模型请求的强制撤回或费用撤销。
- 流解析支持 UTF-8 分块和多事件，身份/课程切换继续丢弃迟到内容。工具失败与连接不完整均向用户反馈，草稿保留。

实现依据：[FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)。HTTPS 代理需允许流转发；服务返回 X-Accel-Buffering: no 与 Cache-Control: no-store。运行一个 worker，延续现有进程内任务锁设计。

## 验证

tests/test_agent_stream.py 覆盖真实工具事件、校验后保存、登录拒绝、非法资料范围、取消后不继续规划/不记入会话、断开后直到线程退出才释放任务锁、异常消息脱敏。

scripts/browser_minimal_auth.cjs 覆盖完整学习流程；scripts/browser_studio.cjs 覆盖导航收起与持久化、真实流式工具反馈、停止/草稿保护、历史搜索、动画运行/暂停/恢复/离屏与系统减少动画，以及 320/375/390/768/1024/1440px 下工作台和历史布局。必须对独立演示数据服务运行，默认端口 8767，不向正式库注册测试账号或上传验收资料。

截图位于 docs/screenshots/studio-*.png，机器验收记录位于 docs/evaluation-studio-ui.json。外部真实模型内容质量未在本次界面/进度改造中重新评估。
