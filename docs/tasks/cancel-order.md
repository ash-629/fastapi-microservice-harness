# 真实增量：取消订单并释放库存

状态：C01–C07均已实现，本地全量验收通过；独立补丁回放全量通过。基线提交：1541caf。使用 feature-delivery 与 api-change，检查范围 full。

## 范围与验收

|编号|需求/规则|实现位置|验收|
|---|---|---|---|
|C01|仅CONFIRMED允许发起取消；PENDING_INVENTORY/REJECTED返回409，未知订单404|Order service/API|接口与状态迁移测试|
|C02|CONFIRMED→CANCEL_PENDING→CANCELLED；释放未知时保留处理中|Order service/reconcile|超时、恢复、重启测试|
|C03|以order_id幂等释放，RESERVED→RELEASED；库存最多加回一次|Inventory service/API|重复、并发、迟到占用请求测试|
|C04|取消/释放必须先验证订单、商品及数量；终态不可回退|两服务|错误输入及晚到结果测试|
|C05|保留旧数据，幂等增加取消申请和完成时间|Order schema migration|旧数据库升级及重复启动测试|
|C06|详情按钮、处理中/已取消状态、筛选和中文错误；只在释放确认后显示已取消|Vue、生成SDK、Mock|浏览器和Mock用例|
|C07|契约先行，生成SDK，保留失败/通过记录、diff和复现方式|contracts、tests、docs|contract check/full/Git Hooks|

API：POST /api/v1/orders/{order_id}/cancel，无请求体；已取消重放200，释放待确认202。PUT /internal/v1/reservations/{order_id}/release，携带原商品和数量；释放成功及重放200。

新增状态枚举影响前端、Mock与Order的库存客户端，属于内部消费者同步升级。已有下单接口保持原路径和幂等语义，已取消订单的下单重放返回当前订单，不重新扣减库存。

## 关键决定

- 处理中订单暂不能取消，避免“取消成功后又扣库存”的另一套协调协议；这是明确的本轮边界。
- 网络调用在本地事务提交之后，取消申请是持久化恢复依据。
- CANCEL_PENDING使用原有有界重试和needs_attention；再次取消或显式reconcile可幂等继续。
- 旧库升级只增加可空时间字段，不重置库存或删除订单。演示数据库已在停止服务后备份。
- 全程本地操作，不推送仓库，不声称已在新会话或原生Codex事件中实测。

## 迭代证据

源快照、原始运行记录位于`.harness/iterations/cancel-order`（不交付私人数据库）。完成后以版本提交、可重放脚本和下方实际记录交接。

已执行：初始8项新测试在基线失败；契约更新后前端编译指出两项新状态未处理；实现后全量54项Python与13项前端用例通过。协议适配器在缺少当前证据时返回block。独立基线+补丁回放同样全量通过，受影响组件逐文件文本一致。演示库升级后已逐表核对旧字段，原订单、商品和占用记录保留。提交与启动记录通过本地Git及运行目录确认。细节见[迭代文档](../iterations/cancel-order.md)。
