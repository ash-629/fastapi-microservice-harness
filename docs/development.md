# 开发与命令

仓库入口见 README。Python成员各自声明依赖，uv.lock统一锁定；npm依赖通过package-lock.json锁定。

|命令 harness 后的参数|用途|
|---|---|
|doctor|检查Node/npm/Git、依赖、契约和锁文件，显示端口及原生Hook状态|
|up / down|启动或停止两个API和前端，端口8001/8002/5173|
|seed|只插入缺失商品，不重置库存|
|smoke|只读检查活动服务就绪|
|smoke --isolated|临时库与动态端口真实业务验证|
|reconcile --order-id UUID|对指定处理中订单恢复一次|
|contract generate|离线导出并生成客户端|
|contract check|临时生成并比较文件集合与内容|
|check --scope quick|静态、类型、架构、契约、前端构建|
|check --scope affected|quick加后端全部测试（小仓库保守范围）|
|check --scope full|affected加真实API浏览器测试|
|report latest|查看结果与 current 指纹是否仍有效|
|hooks install|为当前独立仓库设置本地Git hooksPath|
|staged|隔离导出Git index，检查静态、架构、契约与SDK；不修改工作区|
|task start / task finish|显式声明代码任务检查范围，完成时验证当前证据|
|package --output 源码外路径.zip|要求当前full通过，输出排除环境/数据库/日志的源码包，不覆盖已有文件|

命令前缀为 `python -m uv run --locked harness`，uv在PATH时可简写 `uv run --locked harness`。

## 协作步骤

新增功能使用 feature-delivery；改参数响应使用 api-change；修复故障使用 bugfix。先定义可观察验收，再修改模型和路由，生成SDK，同步页面与Mock，运行检查。生成文件不能手改。结构契约通过不替代业务断言。

开发纯前端：`cd web; npm run dev`，使用 src/mocks 的MSW数据时设置 VITE_MOCK=1（独立Mock模式）。真实模式不设置该值。

## Hooks 与质量边界

Git pre-commit检查暂存快照，源代码从临时index副本导入，依赖可复用本机已锁定安装。未暂存文件不会覆盖提交内容；不stash、不修改工作区。pre-push执行工作区affected反馈，最终提交内容仍由干净CI验证。CI尚未在远端运行。ZIP不带.git，安装Git Hooks前需要git init；提交前暂存所需项目文件。
Codex项目Hook需在客户端审阅和信任。SessionStart提示入口，PostToolUse记录显式任务是否变脏，Stop核对PASS、检查集合与内容指纹。代码任务先task start --scope affected（跨服务及工具变更用full）；缺少证据请求续跑一次，第二次仅报告阻碍以防循环；通过后task finish。纯咨询不启动代码任务。处理器协议已测试，原生事件加载仍待目标客户端验证，不能当作完整安全边界。

## 已知取舍

完整检查首次下载浏览器成本独立计算；affected当前保守运行全部后端测试。并发测试验证正确性，不代表生产吞吐。
本机依赖使用Python3.13.5；最低3.12。TestClient出现上游HTTPX弃用提示，测试仍通过，未来升级需重新验证。
Hooks处理器及暂存快照已执行测试；原生事件加载、远端CI、分支保护和新会话演示须在对应环境验证，不伪称已完成。详见[复测报告](../QA_REPORT.md)。

