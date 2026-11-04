# Java 后端

## 范围

两个独立 Spring Boot 服务替换原有后端；Vue 页面、HTTP 路径、JSON 字段和状态语义保持一致。Maven 管理 Java 模块，Node 统一开发工具，运行与检查不依赖其他后端解释器。

|能力|位置|验证方式|
|---|---|---|
|库存查询、占用与释放|services/inventory|接口、并发与幂等测试|
|下单、取消、分页与恢复|services/orders|状态机、故障和真实 HTTP 测试|
|严格参数、错误、请求关联|services/common|HTTP 边界与契约测试|
|前端与接口协作|contracts、web|生成 SDK 差异检查与 Playwright|
|开发反馈|tools、Skills、Hooks|任务范围、内容指纹、暂存快照与归档测试|
|本地数据兼容|SQLite schema 0/1|旧库升级和请求摘要兼容测试|

## 约束

Java 21，Spring Boot 3.5，独立 SQLite 数据库。common 仅共享基础设施，不包含业务表或跨服务访问。服务只通过 HTTP 协作；未知结果继续保留处理中状态。数据库事务不覆盖网络调用。

现有页面作为交互依据，OpenAPI 为字段与路径依据，已有业务测试作为异常和边界依据。业务范围不增加支付、认证或生产部署。

## 检查

迁移后执行 Maven 测试、Java 格式与模块边界检查、契约和 SDK 差异检查、Node 工具测试、前端构建及真实服务浏览器测试。归档只包含仓库文件和对应完整检查结果。
