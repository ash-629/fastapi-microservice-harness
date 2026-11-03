# Order Studio · FastAPI 微服务 Harness

两个独立FastAPI服务、Vue工作台及可执行AI开发流程。合成数据；本机验证Python3.13.5、Node25.3.0。Node最低要求为20.19或22.12以上，推荐22 LTS。

## 快速启动

```powershell
python -m pip install uv
python -m uv sync --all-packages --locked
npm --prefix web ci
python -m uv run --locked harness doctor
python -m uv run --locked harness up
```

浏览器打开 http://127.0.0.1:5173 。API文档在8001/docs、8002/docs。
停止：`python -m uv run --locked harness down`。

## 四项要求

|要求|实现|
|---|---|
|精简Skills/Hooks/AGENTS|AGENTS.md、.agents/skills三个技能、.codex配置与.githooks|
|快速高质量迭代|统一CLI、内容指纹、契约、业务测试、浏览器测试、CI|
|前后端协作|OpenAPI、生成SDK、MSW、真实联调|
|设计与使用|以下文档、命令和演示流程|

- [架构与业务语义](docs/architecture.md)
- [开发命令与限制](docs/development.md)
- [面试演示](docs/demo.md)
- [需求对应表](docs/alignment.md)
- [实现交接](docs/tasks/implementation.md)
- [交付前复测报告](QA_REPORT.md)

## 检查

```powershell
python -m uv run --locked harness check --scope affected
npm --prefix web exec -- playwright install chromium
python -m uv run --locked harness check --scope full
python -m uv run --locked harness report latest
```

完整检查前先down，防止测试端口冲突。首次下载浏览器单独计时。
Windows实测37个Python测试、9个Playwright用例（8个浏览器场景、1个MSW协议用例），以及Ruff、mypy、契约与客户端一致性、前端格式和构建检查通过。干净源码包解压后重新安装依赖也通过了全量验收。

代码任务先运行 `python -m uv run --locked harness task start --scope full`，检查通过后 `task finish`。Stop处理器会在显式代码任务缺少有效证据时请求续跑一次，防止循环；纯咨询不强制运行测试。原生Codex事件仍需目标客户端信任与实测。

Git pre-commit验证暂存快照，不修改工作区；CI配置已提供但尚未远端执行。ZIP不包含.git，若需要Git Hooks，请先 `git init`，再执行 `harness hooks install`，提交前将所需源码暂存。

生成干净交付包：全量检查通过后运行 `python -m uv run --locked harness package --output ../delivery/OrderStudio.zip`。输出应在源码目录外，已有同名文件不会覆盖。
