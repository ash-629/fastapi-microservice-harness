# 架构与业务语义

F01 Inventory 独立拥有 products、reservations；F02 Order 独立拥有 orders。两个服务分别为 uv workspace 成员，只通过 HTTP 协作。SQLite 使用独立文件与短写事务，网络调用发生在事务外。

R01 库存通过条件 UPDATE 保持非负；order_id 唯一，重复占用重放持久化结果。拒绝也持久化，后续补库存不改变历史结果。

R02 Order 首先持久化 PENDING_INVENTORY，再请求库存。RESERVED 转 CONFIRMED，明确业务拒绝转 REJECTED。超时和错误结构保留 PENDING。后台每秒扫描到期记录，失败退避，五次后 needs_attention，显式 reconcile 可再试。服务重启后从数据库恢复。

请求幂等键为 UUID；相同键与相同内容复用订单，不同内容返回409。写事务的唯一约束处理并发竞争。当前支持单商品订单与已确认订单取消，无支付、认证或库存过期。

API层提供统一错误和 request_id。schemas与路由声明为契约源，OpenAPI快照和SDK由命令生成；导出不创建数据库或启动服务。前端真正调用生成SDK，公共路径由Vite代理到相应服务。

架构检查目前机械验证跨服务导入；更细的依赖/分层约束仍需评审。库存业务拒绝通过内部200结果传递，公共下单转换为404/409，避免把网络代理错误误认为业务拒绝。

开发模式存储初始化为幂等建表与种子插入；Order的schema版本0→1会在短事务中增加取消申请/完成时间字段，保留旧数据。生产鉴权、多版本兼容、远端保护与部署不属于当前本地演示。

复测补充：请求模型先去除首尾空白再校验；下游占用结果严格校验类型，技术故障与契约错误区分；幂等冲突使用专用异常，其他内部异常不以409或原始文本暴露。列表与total在同一读事务中获取。检查证据覆盖源码与关键Python工具版本；检查过程中源码变化会使结果失败。

取消补充：CONFIRMED先持久化为CANCEL_PENDING，再通过幂等release释放库存，确认后变为CANCELLED。库存RESERVED→RELEASED与加回数量同事务完成；迟到reserve只重放RELEASED。重试耗尽保持CANCEL_PENDING并标needs_attention，显式重试可继续。详见[取消迭代](iterations/cancel-order.md)。

