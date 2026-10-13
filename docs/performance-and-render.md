# 响应优化与 Render 部署

2026-10-13。本轮保留 OCR、账号隔离、专业工作台、流式 Agent 和持久化上下文。

## 部署失败原因与修复

Render 日志显示 `No matching distribution found for rapidocr-onnxruntime<2,>=1.4`。项目所用 RapidOCR 1.4.x 不支持 Python 3.13 及以上；这次失败发生在安装依赖阶段，与是否使用免费实例无关。

仓库根目录 `.python-version` 固定 Python 3.11 系列，项目元数据声明 `>=3.11,<3.13`。保留扫描 PDF 的本地 OCR。Render 已有服务使用：

```text
Build Command: pip install .
Start Command: uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT
```

服务关联 `main` 分支时，推送触发自动部署。若服务环境中已有 `PYTHON_VERSION`，它优先于 `.python-version`：删除该覆盖值，或改为受支持的完整 3.11.x 版本，然后重新部署。构建失败时旧版本继续运行，不能把能打开网页当作最新版部署成功。

`/health` 新增 `build=20261013-fast-workspace` 与 `commit`（Render 注入的 `RENDER_GIT_COMMIT`），用于确认实际在线版本，不输出密钥。

## 响应性能

同一 Windows / Python 3.11 环境实测：静态页面、健康检查和身份接口通常 2–25ms；慢点位于首次外部模型调用。原 HTTPX 客户端为环境代理分别建立 TLS 上下文，重复解析磁盘证书，初始化耗时 34,519.5ms。

现在证书先读入内存、建立一个可验证的 TLS 上下文，并让客户端及代理连接池复用；继续开启证书和域名验证，继续支持代理及 `SSL_CERT_FILE` / `SSL_CERT_DIR`。同环境证书读取 52.1ms、上下文建立 24.8ms、客户端创建 94.4ms，合计约 171.3ms。小型真实模型请求（最多 8 个输出 token）首次 781.5ms、第二次 900.4ms；这不是长资料生成耗时承诺，也不能直接推断 Linux 云服务器收益。

客户端仍按需创建；连接超时最多 10 秒、连接池等待最多 5 秒，总请求超时沿用配置。保留连接复用。Agent 流式接口持续展示真实执行进度；取消后后台任务结束才释放模型连接租约，避免并发切换配置。

## 云端登录与数据

Render 自动启用 Secure Cookie，并读取反向代理的 HTTPS 协议，保持同源写入验证。空云端空间允许首次远程注册；若已有未归属的课程、文件或记录，拒绝远程领取。云端新账号始终使用独立学习空间，不继承服务器模型密钥。本机首个账号继续承接本机原有资料。

本项目目前使用 SQLite 和本地上传 / 向量文件。Render 免费 Web Service 闲置约 15 分钟会休眠，唤醒约需一分钟；免费实例的文件系统不持久化，重启、重新部署或休眠可能丢失账号、文件和记录。免费部署适合演示。需要长期保存资料时，必须另行接入持久化数据库与文件 / 索引存储，或使用付费持久磁盘；本轮没有购买或创建付费资源。

## 验证

针对 HTTP/TLS、云端注册、长密码、上下文和流式执行的 19 项测试通过。完整 Python 回归 207 项通过（196.38 秒），Ruff 检查通过；仅有两条上游弃用警告。云端测试覆盖空空间注册、旧资料拒绝远程领取、Secure Cookie、代理 HTTPS、跨站写入拒绝；HTTP 测试覆盖并发初始化一次、证书覆盖设置和代理复用。

参考：[Render Python 版本](https://render.com/docs/python-version)、[Render 部署](https://render.com/docs/deploys)、[Render 免费实例](https://render.com/docs/free)、[HTTPX TLS](https://www.python-httpx.org/advanced/ssl/)。
