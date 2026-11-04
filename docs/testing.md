# 测试

## 执行

```shell
node tools/harness.mjs down
npm --prefix web exec -- playwright install chromium
node tools/harness.mjs check --scope full
```

|范围|内容|
|---|---|
|quick|文档、模块边界、Java编译与格式、Node工具和HTTP测试、契约、SDK、前端构建与格式|
|affected|quick及Java业务测试；当前项目较小，保守运行全部业务测试|
|full|affected及Playwright真实服务、浏览器与MSW用例|

## Java与HTTP

JUnit覆盖并发库存保护、占用和释放幂等、冲突与拒绝重放、并发同键下单、取消状态和时间保护、严格下游校验、响应丢失、重试上限、重启恢复、旧schema与幂等摘要兼容、分页和终态保护。

HTTP回归包括405/406/415客户端错误、统一的500/503错误边界、健康检查成功响应与契约一致性。检查工具测试覆盖损坏、过期和范围不足的记录，缺少有效证据时不得结束代码任务。

Maven运行Spotless、编译和JUnit，测试使用临时目录与真实JDBC连接。node:test验证指纹、范围、Hook生命周期、模块边界、文档和归档；HTTP测试使用真实Java进程、动态端口与独立数据库，验证参数、统一错误、请求ID、业务HTTP状态、下单、取消及进程重启恢复，并按OpenAPI校验响应。

```shell
npm test
```

运行前先构建Java服务。测试关闭自行启动的进程。

## 前端

Playwright覆盖空态、筛选、真实下单和取消、库存变化、损坏存储、迟到响应、轮询生命周期、失败重试与移动端长文本。MSW协议用例验证幂等、库存、取消、错误和分页。完整检查启动真实Java后端。

## 结果与边界

```shell
node tools/harness.mjs report latest
```

结果保存范围、检查项、耗时、源码与Node版本指纹；current=false需重新检查，quick不能代替full。原始结果在忽略目录.harness。远端结果见[Actions](https://github.com/ash-629/fastapi-microservice-harness/actions)。

CI使用Linux与JDK 21，本地也在Windows运行。原生Hook处理器测试不等于客户端事件分发测试；未包含生产容量与完整安全审计的验证结论。
