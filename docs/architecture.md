# 系统架构

## 模块

|模块|职责|依赖|
|---|---|---|
|orders|下单、幂等、取消、分页与恢复调度|独立SQLite，HTTP调用库存|
|inventory|商品、可用库存、占用与释放|独立SQLite|
|common|严格JSON、校验、统一错误、请求关联和事务工具|Spring Web、Bean Validation、SQLite JDBC|
|web|商品与订单页面、生成SDK、MSW|Vue、TypeScript、Vite|
|tools|启动、检查、契约、Hooks与归档|Node及锁定的开发依赖|

服务各自构建可执行Spring Boot JAR。common不包含业务表，不依赖业务服务。模块边界检查拒绝跨服务import和Maven依赖。

## 下单

Order先持久化PENDING_INVENTORY，再调用库存。Inventory以BEGIN IMMEDIATE和条件UPDATE，在同一事务扣库存并保存请求摘要和占用结果。相同订单ID重放结果，拒绝也持久化。

Order严格核对订单ID、商品ID、数量、状态和拒绝码，匹配的RESERVED转CONFIRMED，明确业务拒绝转REJECTED。网络异常或无效响应保留处理中，不推断库存操作失败。

## 取消与恢复

CONFIRMED先持久化CANCEL_PENDING，再请求释放。库存加回与RESERVED转RELEASED在同一事务完成。重复释放或迟到占用不能再次修改库存。Order核对RELEASED后条件更新CANCELLED。

调度器每秒扫描到期记录，每批最多20条。技术失败采用有界退避，五次后标needs_attention并保留处理中。重放原请求可继续尝试；重启自动扫描未超限记录。具体协议见[取消与库存释放](cancellation.md)。

## 存储

每次操作使用独立JDBC连接，短事务结束即关闭。WAL改善读写协作，busy_timeout为5秒；锁等待失败不作为业务拒绝。网络调用位于事务外，条件更新保护终态。列表与total在同一读事务内查询。

schema版本0到1在事务中增加取消时间字段，旧订单、幂等键和请求摘要保持兼容；未知更高版本拒绝启动。

## 接口与可观察性

Controller、DTO和注解为接口源。springdoc从隔离进程导出OpenAPI，SDK由契约生成。导出使用临时数据库，不操作本地数据。未知字段和错误类型拒绝，HTTP错误使用统一结构，原始异常文本不返回客户端。

X-Request-ID验证为UUID，否则生成新值。响应与结构化日志携带请求关联，Order沿HTTP调用传至Inventory。

## 运行范围

默认回环地址与合成商品数据。SQLite仍有单写事务限制，并发正确性测试不代表容量指标。认证、支付与生产部署需独立设计。
