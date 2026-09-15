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
