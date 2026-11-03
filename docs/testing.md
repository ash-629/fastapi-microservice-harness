# 测试

## 运行检查

```shell
python -m uv run --locked harness check --scope affected
npm --prefix web exec -- playwright install chromium
python -m uv run --locked harness check --scope full
```

`full`包含真实HTTP与浏览器场景，运行前先用`harness down`停止本地服务。测试使用独立数据库，结束时关闭自行启动的进程。

检查范围：

|范围|内容|
|---|---|
|quick|锁文件、Ruff、文档链接、架构约束、契约与SDK、mypy、前端构建和格式|
|affected|quick及Python测试；当前仓库较小，保守运行全部Python测试|
|full|affected及Playwright浏览器和MSW协议用例|

## Python测试

- 正常下单、库存不足与统一错误响应。
- 数量、商品ID、UUID和分页参数边界。
- 同一幂等键的串行/并发请求，以及同键不同内容冲突。
- 有限库存的并发扣减、重复占用与拒绝结果重放。
- 下游超时、响应丢失、错误结构、重试耗尽及进程重启恢复。
- 正常取消、并发取消、重复释放和迟到的占用请求。
- 释放结果校验、取消处理中恢复、旧数据库升级及终态保护。
- 检查指纹、任务范围、Hook协议、Git暂存快照和源码归档。

## 前端测试

Playwright覆盖空态、筛选、真实服务下单与取消、库存变化、损坏存储、迟到响应、轮询生命周期、失败重试和移动端长文本。MSW协议用例验证Mock的幂等、库存变化、取消、错误与分页行为。

```shell
cd web
npm exec -- playwright test
```

Mock与真实服务分别验证，Mock通过不代表真实服务链路通过。

## 检查结果

```shell
python -m uv run --locked harness report latest
```

结果记录检查范围、各项状态、耗时和内容指纹。`current=false`表示源码或关键工具版本已变化，需要重新运行检查。quick不能代替full；失败或跳过的检查不能计为通过。

原始结果位于忽略目录`.harness/`。GitHub上的结果见[Actions](https://github.com/ash-629/fastapi-microservice-harness/actions)。

## 验证边界

CI在Linux运行完整检查，本地开发环境也使用Windows。原生Codex Hook的配置读取和事件支持取决于客户端版本及信任设置，处理器测试不等于客户端事件分发测试。

项目没有生产容量、访问控制或完整安全审计的验证结论。SQLite并发测试关注库存正确性，不作为吞吐能力指标。
