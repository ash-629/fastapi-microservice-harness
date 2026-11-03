# 开发指南

## 环境

Python最低3.12，uv按.python-version选择版本。Node需满足^20.19.0或>=22.12.0。Python与前端依赖分别使用uv.lock和web/package-lock.json。

初次安装见根目录README。服务进程、运行数据和日志位于.runtime，检查结果位于.harness；这些目录不进入版本控制。

## 命令

所有命令使用前缀`python -m uv run --locked harness`。

|参数|用途|
|---|---|
|doctor|检查Node/npm/Git、依赖、契约、锁文件和端口|
|up / down|启动或停止两个API及前端|
|seed|插入缺失商品，不重置已有库存|
|smoke|只读检查活动服务就绪|
|smoke --isolated|临时数据库与动态端口的HTTP验证|
|reconcile --order-id UUID|对指定处理中订单尝试恢复|
|contract generate|离线导出OpenAPI并生成SDK|
|contract check|临时生成并比较契约及SDK|
|check --scope quick/affected/full|分层检查，详见测试说明|
|report latest|查看最近结果及内容指纹是否仍有效|
|hooks install|配置当前Git仓库的本地Hooks|
|staged|在隔离目录检查Git暂存快照|
|task start / task finish|声明代码任务范围、检查当前有效结果|
|package --output 路径.zip|完整检查通过后创建源码归档，不覆盖已有文件|

## 修改接口

1. 定义可观察行为，识别提供方和消费者。
2. 修改schemas、路由和错误模型。
3. 运行contract generate，查看契约及SDK差异。
4. 同步前端、Mock和测试。
5. 执行相应检查；跨服务或状态机变更使用full。

生成文件不手改。结构契约不能替代业务行为测试。

## 前端与Mock

单独启动前端：在web目录执行`npm run dev`。设置VITE_MOCK=1可使用MSW模式，真实模式不设置该值。

测试前端类型与格式：

```shell
npm --prefix web run build
npm --prefix web run format:check
```

## Skills与Hooks

项目提供feature-development、api-change、bugfix三个流程。复杂变更可在docs/plans记录目标、约束和验证结果。

代码任务先task start，再修改与检查，最后task finish。Stop处理器验证检查范围、PASS状态和内容指纹；缺少证据时请求续跑一次，第二次报告未通过原因以防循环。纯咨询不建立代码任务。

原生Codex Hooks需要客户端支持并信任配置；Git Hooks不依赖原生事件。pre-commit从index导出源码进行静态、架构和契约检查，不stash或覆盖工作区；pre-push运行工作区affected检查。远端CI验证实际推送的内容。

从源码ZIP开始使用Git时，先git init，再hooks install；提交前暂存所需项目文件。

## 常见问题

- 端口被占用：doctor显示占用状态；不会自动终止其他进程。
- full测试端口冲突：先down，再运行完整检查。
- 契约漂移：核对接口源，再运行contract generate并检查差异。
- 报告过期：修改内容后重新执行检查，不复用旧的通过结果。
- 订单持续处理中：查看request_id及服务日志，需要时执行指定订单的reconcile。
