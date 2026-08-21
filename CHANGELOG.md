# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.1.4] - 2026-08-21

### Added

- 新增下载基础 URL（`download_base_url`）配置项，二进制下载支持自定义镜像源，便于内网/K8s 环境离线部署。
- 新增 GeoIP 数据库下载地址配置项，支持自定义 GeoIP 数据源。
- 新增无订阅初始化模式：未配置订阅链接时仅下载 mihomo 二进制并提示用户配置订阅，不再阻塞启动流程。
- 新增 `requirements.txt` 声明 Python 依赖。

### Changed

- 更新 Clash (mihomo) 版本至 v1.19.30。
- 重构二进制下载逻辑（`download_base_url` 拼接、GeoIP 数据库下载、失败 fallback），下载容错性增强。
- 优化初始化流程，无订阅场景下自动跳过订阅拉取并给出明确提示。

## [0.1.3] - 2026-08-11

### Added

- 新增代理模式设置功能：`/clash/mode` Web API 支持 rule / global / direct 三种模式切换（对应 Global/Rule/Direct）。
- 状态 API（`/clash/status`）新增 `mode` 字段，实时返回当前运行模式。
- WebUI 增加模式切换控件，前端 Dashboard 支持一键切换代理模式。
- 移除 `auto_start` 配置项（插件始终自动启动，简化配置模型）。

### Changed

- 重写 README，完整覆盖功能说明与 WebUI 用法（安装、命令、Dashboard 操作流程）。

## [0.1.2] - 2026-08-11

### Added

- 新增日志级别配置项（`log_level`），支持 info / warning / error 三级过滤，可通过配置控制 Clash 日志输出量。
- 进程输出异步读管道：新增 `_read_output()` 解析 stdout，识别 `level=` 日志级别并按配置过滤打印。

### Changed

- 统一文档和代码中的描述为 "Clash"（原 mihomo），修正注释、日志、类 docstring 的一致性。
- 进程管理重构：
  - 从 `subprocess.Popen` + 文件日志迁移到 `asyncio.create_subprocess_exec` + 管道读取，避免阻塞事件循环。
  - 新增 `_wait_for_ready()`：同时检测 RESTful API 与混合代理端口是否就绪，替换原单一 API 探活。
  - 新增 `_terminate_process()`：启动失败时自动清理子进程与输出任务，防止僵尸进程。
  - 端口占用检测：解析 "address already in use" 错误并给出明确报错，替换原 `_wait_api` 的超时模糊提示。

## [0.1.1] - 2026-08-09

### Changed

- 重构 `_conf_schema.json` 配置描述：统一将提示信息从 `description` 拆分为 `hint` 字段，WebUI 展示更清晰。
- 修正 `mixed_port` / `http_port` / `socks_port` 的交互提示，明确"mixed_port=0 时使用 http+socks 分别设置"的语义。

## [0.1.0] - 2026-08-08

### Added

- 初始版本：基于 mihomo（Clash Meta）二进制的代理管理插件。
- `metadata.yaml`：插件元数据（订阅地址、混合端口、API 端口、日志级别等配置的完全声明）。
- `src/clash_manager.py`：mihomo 二进制下载（按平台/架构自动选择 + `-compatible` 变体 fallback）、配置文件生成、进程生命周期管理。
- `main.py`：插件入口，实现 `on_plugin_start` / `on_plugin_terminate` 生命周期钩子与 `/clash` 指令。
- `_conf_schema.json`：WebUI 配置 schema。
- `src/__init__.py`：包初始化文件。
- `.gitignore`：忽略 `data/` 目录（二进制、配置、日志等运行时产物）。
- README.md：基础说明文档。
- LICENSE：开源许可。

### Key Features

- K8s 环境友好：通过 `subprocess` 管理 mihomo 二进制，不需要特权模式或 host network。
- 支持自定义订阅链接（User-Agent 模拟 Clash 客户端）与混合代理端口。
- 二进制自动下载和版本管理，按 GitHub Release 选择对应平台版本。

### Fixed

- 重写 `clash_manager.py`：修复 `-f` flag（config 路径参数）bug，移除 `listeners` 配置冲突，新增启动前配置合法性测试。
- 二进制下载优先使用 `version` 精确版本，失败时尝试 `-compatible` 变体，再尝试 latest。
- `main.py`：版本号与 `metadata.yaml` 同步，抽取 `_read_config()` 集中解析配置。
- 更新默认 mihomo 版本至 v1.19.29。

### Added (WebUI)

- 新增代理管理 WebUI 页面（`pages/dashboard/`）：app.js / index.html / style.css。
- 新增 Web API：
  - `GET /clash/status`：运行状态与代理组信息。
  - `GET /clash/proxies`：全部代理节点列表。
  - `POST /clash/switch`：切换代理节点。
  - `GET /clash/delay`：测试节点延迟。
- 订阅刷新机制：支持配置 `subscription_refresh_minutes` 定时重新拉取订阅。