# 轻量化与启动优化

2026-10-28。目标是不改变功能，只减少首次打开和冷启动的等待。线上免费实例的最大等待仍来自 Render 休眠唤醒（约一分钟），因此同时加入 keep-warm 定时探测。

## 页面首次加载

- 样式从「入口 `app.css` + 6 个 `@import`」共 7 个阻塞请求，合并为 1 个 `/static/app.bundle.css` 请求。六个模块仍在 `app/static/` 中独立维护；服务端按原 `@layer` 顺序在内存中拼接并缓存，不生成第二份容易过期的 CSS 文件。`@charset` 在拼接时移除，`@layer` 顺序保持不变。
- 首页、CSS 和 JS 统一经过 gzip；静态 URL 带内容哈希时返回 `Cache-Control: public, max-age=31536000, immutable`，再次打开直接使用浏览器缓存，不再逐个文件协商。`index.html` 使用 `no-cache`，保证新部署立即生效。
- 首屏接口从串行改为并行：`/health` 在脚本解析时预取，与 `/api/auth/me` 同时发出；`/api/connection` 与 `/api/courses` 并行，课程资料 / 生成记录 / 学习进度仍并行。高延迟网络下的关键路径从 4–5 个往返降到 2–3 个。
- PDFium 与 python-docx 改为按需导入，只在原页预览、OCR 或 Word 导出时加载，降低冷进程启动和常驻内存。
- PDF 与 Word 下载不参与 gzip；`text/event-stream` 由 Starlette 默认排除，Agent 流式输出仍逐块发送。

本机同一 Windows / Python 3.11 环境、临时空数据目录实测（首次运行，含磁盘缓存影响，供相对比较）：

| 指标 | 优化前 | 优化后 |
| --- | --- | --- |
| 冷进程导入 `app.main` | 1419.6 ms | 1117.0 ms |
| 启动 lifespan | 478.7 ms | 140.2 ms |
| `/health` 报告的 `startup_ms` | 286.6 ms | 128.9 ms |
| 首屏 CSS 请求数 | 7 | 1 |
| 首屏静态请求总数 | 13 | 7 |

gzip 后首页 + CSS + 5 个 JS 合计约 66 KB。云端实际耗时受出口网络、实例 CPU 和是否休眠影响，不能直接外推本机数字。

修改 CSS 或 JS 后刷新内容哈希：

```text
.venv/Scripts/python.exe scripts/build_static_assets.py
```

## Render 免费实例不休眠

新增 `.github/workflows/keep-warm.yml`，每 5 分钟访问一次 `/health`。Render 免费实例约 15 分钟无流量休眠；持续探测可避免用户打开页面时等待容器启动。该工作流需要位于默认分支，且 Render 服务的 Auto-Deploy 保持开启才会随代码更新。GitHub 定时任务可能延迟，属于尽力而为；也可用 UptimeRobot 等外部监控指向 `/health` 作为等价方案。

免费实例 750 小时/月：31 天持续唤醒约 744 小时，仍在额度内；若同时有其他常驻服务，需要核算总额度。keep-warm 不改变账号、资料或模型行为，也不会让免费实例的磁盘变为持久化。

## 验证

新增静态资源测试覆盖：单 CSS 请求、gzip、内容哈希长缓存、未带版本号时重新验证、304、JS 长缓存。完整 Python 回归 290 项通过（206.92 秒），Ruff 通过；随后针对 gzip 排除项重跑 bootstrap / 流式 / 连接测试 19 项通过。流式输出继续使用 `text/event-stream`，不压缩、不缓冲。

## 部署

推送后需确认 Render 实际运行新提交：

```text
https://studyagent-jlh3.onrender.com/health
```

`commit` 应为新提交，`build` 为 `20261026-quiet-study-desk`。若 `commit` 未变化，检查 Render 服务的 Auto-Deploy 是否被 Dashboard 回滚关闭，再手动 Deploy latest commit。keep-warm 工作流只在默认分支生效。
