# StudyAgent Learning Studio 界面约定

使用 ui-ux-pro-max 的 AI-Native UI 检索方向，结合现有学习流程与用户要求：有明确品牌层次、可感知的动态交互，保持简洁。白银色内容区、深靛导航与蓝紫主色，浅深主题使用统一语义变量。全部图形由本项目 SVG/CSS 构建，字体使用本机系统字体，无新增远程字体、图像和动画框架依赖。

- 五个任务入口保留；课程创建、资料上传及执行详情按需展开。桌面导航可收起为图标栏，偏好保存在本机；手机使用资料抽屉。
- 首页以提问为核心，登录后缩短品牌区域和输入区；统计只展示资料、练习、错题、计划四项。
- 知识连接插画使用低频 CSS 轨道/纸片动效与轻微鼠标视差，有显式暂停按钮，离屏、后台和系统减少动画时暂停。导航指示器与页面切换提供空间连续反馈，卡片首次进入视野轻微淡入。避免添加不断闪烁的装饰与多套配色。
- 历史页包含短标题、搜索、记录卡片与明确的空状态。筛选当前加载记录，支持继续加载；保留查看来源快照与删除流程。
- 所有图标按钮有可读名称；主要点击区域至少 44px；键盘焦点、Tab 循环、Esc 关闭及弹窗焦点返回保留。支持 320px 手机与浅深色。
- 注册/登录以工作台内弹窗完成。游客可浏览、填写草稿，使用 Agent 时要求认证；登录保留问题，不自动提交。退出清理个人内容，身份/课程切换丢弃迟到响应。
- Agent 通过 SSE 展示真实规划、工具开始/完成与校验状态；只在完成来源校验后渲染回答。停止按钮断开连接，阻止后续步骤，保留草稿。当前工具/模型调用可能完成，已完成工具产生的文件不回滚。

参考：[ai-writing-assistant Sidebar](https://github.com/tbyang28/ai-writing-assistant/blob/feat/public-community/frontend/src/components/Sidebar.vue)、[AI stream controller](https://github.com/tbyang28/ai-writing-assistant/blob/feat/public-community/backend-ts/src/ai/ai.controller.ts)。借鉴工作区信息层次、收起导航与真实 AI 反馈，独立实现，未复制源码或截图素材。
