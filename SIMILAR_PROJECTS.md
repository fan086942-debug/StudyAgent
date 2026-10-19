# 相似项目对照

查阅日期：2026-10-19。以下能力来自项目自己的 GitHub README，本次没有安装或运行这些项目。建议只代表结合当前 StudyAgent 架构作出的工程判断。

| 项目 | 与 StudyAgent 相似的部分 | 值得参考的部分与限制 |
| --- | --- | --- |
| [ExamForge-AI](https://github.com/Adityam-21/ExamForge-AI) | FastAPI、ChromaDB、资料问答、页级引用、连续对话 | 优先参考由实际检索片段确定引用和页码，以及真实执行阶段反馈。README 明示没有账号系统，只支持 PDF，扫描件会拒绝；它不能直接解决复杂试卷原文抽取。 |
| [AI-Learning-Study-Assistant](https://github.com/ug8yogesh/AI-Learning-Study-Assistant) | PDF 问答、测验、学习记录、薄弱点和学习计划 | 功能目标最接近。可以参考学习闭环和工具划分；Streamlit、FAISS、Gemini 的技术栈与本项目不同，README 宣传的效果尚未独立验证。 |
| [Lumina AI](https://github.com/VaradHajare/Lumina-AI-Multi-Source-RAG-Chat-Agent) | 来源问答、测验、闪卡和摘要 | 浏览器端混合检索可减少服务端计算压力。README 也明确单来源最多 250 个片段、刷新会重新向量化，不能据此保证长教材完整召回。 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 文档解析、检索、来源引用和 Agent 工作流 | 参考复杂文档解析与可检查的切块流程。它是包含多项依赖服务的完整平台，官方 FAQ 说明需要较多资源，不适合作为当前免费小实例的直接替换。 |

当前优先顺序：真实文字提取 → 确定性来源定位 → 正确识别查旧题与出新题 → 真实模型回答 → 引用校验。后续用固定题目和已知来源做检索评估，再判断是否加入 BM25、语义 Embedding 或重排。

这次仅做对照分析，没有迁入第三方代码，也没有重新实现其他项目的整套架构。
