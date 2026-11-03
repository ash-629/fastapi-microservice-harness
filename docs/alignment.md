# 需求对应表
依据：上级目录《方案与设计_v1.0_20261103.md》。页面依据第5章，架构依据第3章，字段依据第6章。
|编号|需求|位置|状态|
|---|---|---|---|
|F01|商品和库存查询|inventory_service|已实现（验证见README与任务记录）|
|F02|下单、查询、幂等、恢复|order_service|已实现（验证见README与任务记录）|
|P01|工作台、表单、列表、详情及各状态|web/src|已实现（验证见README与任务记录）|
|R01|非负库存、相同请求最多扣一次|repository与tests|已实现（验证见README与任务记录）|
|R02|未知结果保留处理中并恢复|order_service|已实现（验证见README与任务记录）|
|H01|AGENTS、3 Skills、Hooks|根目录|已实现（验证见README与任务记录）|
|H02|统一检查、证据和CI|tools/harness|已实现（验证见README与任务记录）|
|H03|契约、客户端和Mock|contracts与web|已实现（验证见README与任务记录）|
|H04|使用说明与演示|docs|已实现（验证见README与任务记录）|
P1订单取消不属于本轮首版范围。状态筛选作为首版可复现的增量案例实现。

Native Hooks事件、远端CI和新会话演示属于环境验证项；不计为已在目标环境实测。
