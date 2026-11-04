---
name: feature-development
description: 实现订单库存的新功能或行为变更。
---

明确预期行为与影响范围；按需读代码和文档。接口变化使用 api-change。实现业务及必要测试，运行 affected，跨服务再执行 full。记录验证结果和未验证项。

命令入口：`node tools/harness.mjs`。开发说明见 docs/development.md；架构见 docs/architecture.md。

开始代码任务时运行 `node tools/harness.mjs task start --scope affected`，跨服务或工具变更使用 full。完成相应 check 后执行 task finish；失败应明确记录未通过的检查。
