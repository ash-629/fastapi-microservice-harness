---
name: bugfix
description: 复现并修复现有业务故障。
---

先复现最小失败路径，为实际不变量建立回归测试。定位事务、幂等与服务结果语义，修复根因并运行相关检查。记录原因与证据；只对可复用流程补规则。

命令入口：`uv run --locked harness`。开发说明见 docs/development.md；架构见 docs/architecture.md。

开始代码任务时运行 `python -m uv run --locked harness task start --scope affected`，跨服务或工具变更使用 full。完成相应 check 后执行 task finish；失败需修复或如实交接。
