---
name: api-change
description: 修改接口参数、响应、错误或消费者契约。
---

识别提供方与消费者，说明兼容性。编辑模型与路由，执行 contract generate。同步前端、Mock并执行 contract check、构建、接口测试和真实联调。不得手改生成文件。

命令入口：`uv run --locked harness`。开发说明见 docs/development.md；架构见 docs/architecture.md。

开始代码任务时运行 `python -m uv run --locked harness task start --scope affected`，跨服务或工具变更使用 full。完成相应 check 后执行 task finish；失败应明确记录未通过的检查。
