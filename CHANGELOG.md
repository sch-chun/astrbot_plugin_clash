# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

## [0.1.4] - 2026-08-21

### Added

- 新增下载基础 URL（`download_base_url`）和 GeoIP 数据库下载地址配置项，支持自定义镜像源。
- 新增无订阅初始化模式：未配置订阅链接时仅下载 mihomo 二进制并提示用户配置订阅，不再阻塞启动流程。
- 新增 `requirements.txt`，声明 Python 依赖。

### Changed

- 更新 Clash (mihomo) 版本至 v1.19.30。
- 优化初始化逻辑，无订阅场景下二进制下载完成后立即给出提示，用户体验更友好。

## [0.1.3] - 2026-08-11

### Added

- 新增代理模式设置功能：支持全局代理（Global）、规则代理（Rule）、直连（Direct）三种模式切换，前端 WebUI 与后端 API 同步更新。
- 新增代理模式切换的 Web API 路由，前端 Dashboard 支持实时切换。
- 重写 README，完整覆盖安装、配置、WebUI 用法、K8s 部署注意事项。

### Changed

- 更新版本号至 v0.1.3，同步 `metadata.yaml` 和 `main.py`。

## [0.1.2] - 2026-08-11

### Changed

- 统一文档和代码中的描述为 "Clash"（原为 mihomo），修正相关描述一致性。
- 新增日志级别配置项（`log_level`），支持 debug/info/warning/error 四级。

## [0.1.1] - 2026-08-09

### Added

- 新增代理管理 WebUI 页面（`pages/dashboard/`），提供代理状态监控和节点选择。
- 新增状态监控功能，实时展示 Clash 连接状态、延迟和流量信息。
- 更新配置和二进制管理逻辑，支持从 WebUI 启动/停止代理。

### Fixed

- 修复 `clash_manager.py` 中 `-f` 参数（config 路径拼接）的 bug。
- 移除 `listeners` 配置冲突，避免 Clash 启动时报端口占用错误。
- 新增配置文件测试功能，在启动 Clash 前验证 config 合法性。
- 修正混合代理端口的配置描述提示信息。

### Changed

- 更新默认 mihomo 版本至 v1.19.29。
- 更新版本号至 v0.1.1。

## [0.1.0] - 2026-08-08

### Added

- 初始版本：基于 mihomo（Clash Meta）二进制的代理管理插件。
- `src/clash_manager.py`：mihomo 二进制下载（按平台/架构自动选择）、配置文件生成、进程生命周期管理（启动/停止/重启）。
- `main.py`：插件入口，实现 `on_plugin_start` / `on_plugin_terminate` 生命周期钩子和 `/clash` 指令。
- `_conf_schema.json`：WebUI 配置 schema，包含订阅链接、端口、日志级别、mihomo 版本等配置项。
- `src/__init__.py`：包初始化文件。
- `.gitignore`：忽略 `data/` 目录（二进制、配置、日志等运行时产物）。
- README.md：基础说明文档。

### Key Features

- K8s 环境友好：通过 `subprocess` 管理 mihomo 二进制，不需要特权模式或 host network。
- 支持自定义订阅链接和混合代理端口。
- 二进制自动下载和版本管理，按 GitHub Release 选择对应平台版本。