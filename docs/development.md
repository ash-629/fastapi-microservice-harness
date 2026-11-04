# 开发指南

## 环境与构建

JDK 21+，Node.js 22.12+。JAVA_HOME指向JDK根目录。Maven Wrapper固定3.9.11，Spring Boot BOM与显式版本固定在pom.xml，两个npm锁文件进入版本控制。

```shell
npm ci
npm ci --prefix web
```

Windows执行 .\mvnw.cmd verify，macOS/Linux执行 ./mvnw verify。格式化使用Maven目标spotless:apply。IDE导入根pom.xml识别三个模块，两个可执行JAR位于services/orders/target和services/inventory/target。

## 命令

所有命令使用前缀node tools/harness.mjs。

|参数|用途|
|---|---|
|doctor|检查Java、Maven、Node/npm和必要文件|
|up / down|启动或停止两个服务与前端|
|smoke|只读检查服务就绪|
|smoke --isolated|使用临时数据库和动态端口验证真实HTTP流程|
|seed|插入缺失商品，不重置已有库存|
|reconcile --order-id UUID|对指定处理中订单继续尝试恢复|
|contract generate / check|从隔离Java进程导出OpenAPI并生成或比较SDK|
|check --scope quick/affected/full|分层检查|
|report latest|最近检查状态与指纹有效性|
|hooks install|配置当前仓库本地Git Hooks|
|staged|隔离编译和验证Git暂存快照|
|task start / task finish|声明任务范围并核对当前结果|
|package --output 路径.zip|根据当前full结果创建源码归档，不覆盖已有文件|

## 接口与前端协作

1. 定义行为和消费者影响。
2. 修改Java DTO、Controller与业务测试。
3. 用Maven Wrapper执行package，生成新的服务JAR。
4. 运行contract generate，检查契约和SDK差异。
5. 同步前端、MSW与测试，执行相应检查。

路径和JSON保持snake_case，SDK生成camelCase函数。Bean Validation与严格Jackson解析拒绝未知字段、字符串数量、小数数量和非法UUID。

web目录中运行npm run dev；VITE_MOCK=1启用MSW，真实模式通过Vite代理访问服务。前端调用生成SDK，类型检查、Mock与真实HTTP测试共同验证协作。

## Skills与Hooks

feature-development、api-change、bugfix提供简短流程。复杂变更记录在docs/plans。代码任务先task start，再修改和检查，最后task finish。Stop处理器核对范围、PASS状态、源码和Node版本指纹；阻止一次无有效结果的结束，第二次报告未解决原因以防循环。纯咨询不创建任务。

pre-commit将Git index导出到独立目录，编译Java并验证文档、模块边界、OpenAPI与SDK。源码完全来自暂存快照，本机依赖可以复用，不stash或覆盖工作区。pre-push运行affected，CI验证实际推送内容。原生Codex事件取决于客户端版本和信任设置。

从ZIP使用Git Hooks时先git init，暂存源码，再hooks install。

## 运行与故障定位

DB_PATH默认为.runtime/orders.sqlite3或inventory.sqlite3，PORT分别默认为8001和8002。INVENTORY_URL默认http://127.0.0.1:8002，RECOVERY_ENABLED默认true。两个服务绑定127.0.0.1；java -jar运行时可用Spring Boot参数覆盖。

- 系统仍使用旧JRE：设置JAVA_HOME，确认存在bin/javac。
- 端口冲突：先down，工具不会按端口批量终止其他进程。
- 契约漂移：先重新编译，再生成契约并检查差异。
- 记录达到重试上限：查看request_id与日志，重放原下单或取消请求以继续尝试幂等恢复。
