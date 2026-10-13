# 资料、出题、上下文与专业界面测试（2026-10-13）

## 结果

| 范围 | 验证 | 结果 |
| --- | --- | --- |
| 资料读取 | 上传 PDF/PPTX/DOCX；状态 ready、分块非空；真实模型分段读取三章自编资料 | 通过 |
| 查找与定位 | A* 题库查找；PDF 物理第 1 页；只返回已选资料；过期索引不返回；精确词边界及通配符 | 通过，修复短关键词定位漏查 |
| 出题 | 真实模型按主题出两题、连续再出两题；按三章重点出三题；答案与引用校验；题目卷不包含答案 | 通过 |
| 上下文 | 页面刷新恢复会话及已勾选资料；新进程恢复真实模型会话并继续出一题；删除、过期、资料变化和账号隔离 | 通过，新增 SQLite 持久化 |
| 密码 | 5 位拒绝，6 位及 1025 字符注册/登录；改变长密码末尾不能登录；浏览器完整输入 4096 字符 | 通过，至少 6 位，无长度上限 |
| 界面 | 五功能页在 320/375/390/768/1024/1440px 无横向溢出；浅深色、来源页签、键盘、正文注入防护及动效 | 通过，JavaScript 错误 0 |

完整 Python **202 项通过**，包含新增密码/持久化 7 项、精确定位 2 项。Ruff、前端语法和 Git 空白检查通过。浏览器完整学习闭环继续通过，见 [浏览器功能记录](evaluation-functional-review-ui.json)；新增主题/交互记录在 evaluation-studio-ui.json。

## 修复的具体问题

原文定位与语义检索原来共用相似度阈值。测试 PDF 有 A* 原文，短查询仍可能被哈希向量阈值过滤。locate_source 现在先在当前课程和 ready/有效索引资料中执行精确原文定位，保留页码、段落和来源；没有字面结果时回退原有语义检索。不会降低所有检索的相似度阈值，也不会扩大用户勾选范围。

上下文原来仅存于 AgentMemory，重启丢失；前端刷新也清空已勾选资料。现在每个用户数据库增加 agent_contexts，保存资料范围/指纹、主题、题干及最近回答。保留最近 10 轮、20,000 字符、最多 100 个会话及闲置两小时有效期，保持单 worker 的忙碌锁。对话删除与持久化上下文清理在同一个 SQLite 事务中提交，课程删除清理对应上下文；资料变化仍使旧证据失效。网页恢复原会话的勾选项，只保留仍可使用的资料。

密码未截断、未自动去除空格或改动旧账号密码；继续使用 scrypt 哈希和 HttpOnly Cookie。只取消最大长度限制并将最小长度改为 6。旧密码继续有效。

## 真实模型与测试边界

使用服务器既有 deepseek-flash 连接配置，读入合成资料，不读取正式教材或向正式空间上传测试文件。

- [按知识点出两题](evaluation-topic-generation.json)
- [连续追问与解释第二题](evaluation-agent-memory.json)
- [三章读取、每章出题与 RAG 问答](evaluation-model-learning.json)
- [新进程恢复与连续出一题](evaluation-model-context-restart.json)

演示模式仅使用原文摘录模板；摘录用尽时返回依据不足，不会为凑题数重复保存。真实模型生成题仍需核对原文，测试通过不能保证所有题目或任意资料均正确。上下文闲置两小时会过期，保留在同一标签页的会话 ID 用于恢复；跨浏览器通过对话历史查看，不自动接续标签页会话。

## GitHub 界面参考

检索并阅读 [assistant-ui](https://github.com/assistant-ui/assistant-ui) 的组件说明与原生聊天/工具卡片示例，以及 [shadcn/chatbot-template 的工作区实现](https://github.com/shadcn-ui/chatbot-template/blob/main/components/chat.tsx)。采用集中输入、回答与工具分层、可读正文、来源页签与快捷建议的交互思路，保留 StudyAgent 的课程资料导航与品牌。不复制源代码或素材，不迁移 React/Next.js，不引入新的远程资源或构建框架。

本轮资料测试和界面脚本为 scripts/browser_functional_review.cjs、scripts/browser_minimal_auth.cjs、scripts/browser_studio.cjs；真实模型恢复脚本为 scripts/model_restart_review.py。浏览器脚本只应对独立演示数据服务运行，默认 8767。测试截图为 screenshots/professional-*.png。
