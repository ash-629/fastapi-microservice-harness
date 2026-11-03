# 面试演示

1. 查看AGENTS.md（短入口）、三个Skills和Hooks到统一CLI的关系。
2. doctor、up，浏览器下单，查看订单与库存联动，然后down。
3. 查看状态筛选的schema → contracts → 生成SDK → Vue参数 → 测试链路。
4. 在隔离副本给orders加入 `import inventory_service`，架构检查应失败；不要在最终交付保留该修改。test_harness.py已经以临时目录复现此拦截。
5. 查看 test_order_idempotency_and_loss：库存先提交、响应丢失、恢复不重复扣库存；test_restart_recovers验证真实进程启动恢复。
6. 执行 full，展示37项Python与9项前端测试、schema和SDK再生成校验、类型检查和构建。
7. 新会话从AGENTS及docs/tasks/implementation.md接手，再运行report latest判断证据是否过期。

全部数据均为本地合成数据。测试自动启动的服务在结束时关闭，不访问手工演示库。测试页面截图在web/test-results/workspace.png。
原生Codex事件与新会话流程仍需在演示客户端实际操作；本说明不等于已经完成该演示。


本轮新增回归与交付结论见[复测报告](../QA_REPORT.md)。Git暂存验证已经实现，Stop在显式task start之后检查证据并最多请求续跑一次，原生事件仍需目标客户端验证。
