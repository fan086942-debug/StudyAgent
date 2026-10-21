# 学习工作区覆盖规则

保留 MASTER 的深色导航与蓝紫品牌，参考 assistant-ui 与 shadcn/chatbot-template 的集中提问和清晰消息层次。核心提问位于资料范围卡片下，学习统计移至输入区之后。品牌场景缩短至 166px，减少首屏纵向长度。

回答与资料依据分为可用键盘切换的页签，正文用安全 DOM 渲染标题、列表、代码与引用；已验证的引用可直接定位原文卡片。模型文本不作为 HTML 注入。复习生成与练习结果放在学习工作台内，设置默认折叠，保存记录按需展开；不再提供独立“复习与生成”导航。题库、错题、自评、计划、下载和连续对话保持可用。移除侧栏“保留原文来源，学得更有把握”宣传语，保留功能性的引用与原文入口。

专业布局由 professional.css/professional.js 实现；无需引入 React 或 Next.js。遵守减少动画，保留动效暂停、导航收起、手机抽屉与明暗主题。

参考：https://github.com/assistant-ui/assistant-ui 与 https://github.com/shadcn-ui/chatbot-template/blob/main/components/chat.tsx 。独立实现信息结构和交互，无复制项目源码或素材。
