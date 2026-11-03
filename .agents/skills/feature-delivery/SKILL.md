---
name: feature-delivery
description: 实现订单库存的新功能或行为变更。
---

明确验收与影响范围；按需读代码和文档。接口变化使用 api-change。实现业务及必要测试，运行 affected，跨服务再执行 full。记录真实验证和未验证项。

命令入口：`uv run --locked harness`。开发说明见 docs/development.md；架构见 docs/architecture.md。

开始代码任务时运行 `python -m uv run --locked harness task start --scope affected`，跨服务或工具变更使用 full。完成相应 check 后执行 task finish；失败需修复或如实交接。
