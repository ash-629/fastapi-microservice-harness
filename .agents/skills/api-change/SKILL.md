---
name: api-change
description: 修改接口参数、响应、错误或消费者契约。
---

识别提供方与消费者，说明兼容性。编辑Java DTO和Controller，用Maven Wrapper重新编译，再执行contract generate。同步前端、Mock并执行contract check、构建、接口测试和真实联调。不得手改生成文件。

命令入口：`node tools/harness.mjs`。开发说明见 docs/development.md；架构见 docs/architecture.md。

开始代码任务时运行 `node tools/harness.mjs task start --scope affected`，跨服务或工具变更使用 full。完成相应 check 后执行 task finish；失败应明确记录未通过的检查。
