# astrbot_plugin_clash

在 AstrBot 插件进程内直接启动并管理 [Clash](https://github.com/MetaCubeX/mihomo) (Clash Meta) 代理，无需额外 sidecar 容器或宿主机安装，特别适合 K8s / Docker 等受限环境。

> 当前版本：**v0.1.3** · 最低 AstrBot 版本：**>= 4.24.0**（需要 `register_web_api` 与 Dashboard Pages 支持）

---

## ✨ 功能特性

- 🚀 **一键启动**：插件加载时自动下载二进制、解析订阅、启动进程
- 📡 **订阅支持**：自动从订阅链接拉取 YAML 配置；可配置自动刷新间隔
- 🔌 **多端口模式**：支持混合端口（HTTP+SOCKS5）或独立 HTTP / SOCKS 端口
- 🎨 **WebUI 控制面板**：AstrBot Dashboard 内置页面，支持：
  - 实时查看代理组与节点
  - 一键切换节点
  - 单节点 / 全量一键测速（延迟按绿/橙/红着色）
  - 切换代理模式（规则 / 全局 / 直连）
- 💬 **指令管理**：通过 `/clash` 指令控制启动 / 停止 / 重启 / 查看版本
- 🔁 **跨平台**：自动识别 linux / darwin / windows / freebsd × amd64 / arm64 / armv7 / 386
- 🛡️ **进程隔离**：使用 `start_new_session` 创建新进程组，插件卸载时彻底清理

---

## 📦 安装

在 AstrBot Dashboard → 插件市场搜索 **Clash 代理管理器**，或直接将本仓库作为本地插件安装。

> 也可手动放置：将整个目录复制到 AstrBot 的 `data/plugins/astrbot_plugin_clash/` 后重启 AstrBot。

---

## ⚙️ 配置

所有配置项位于 AstrBot → 插件配置 → Clash 代理管理器：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `subscription_url` | string | `""` | Clash 订阅地址（返回 YAML）。为空时使用内置默认配置 |
| `mixed_port` | int | `7890` | 混合代理端口（同时提供 HTTP + SOCKS5）。设为 `0` 时使用下方独立端口 |
| `http_port` | int | `7890` | HTTP 代理端口（仅 `mixed_port=0` 时生效） |
| `socks_port` | int | `7891` | SOCKS5 代理端口（仅 `mixed_port=0` 时生效） |
| `api_port` | int | `9090` | RESTful API 端口 |
| `api_secret` | string | `""` | API 鉴权密钥（可选，留空则不启用） |
| `clash_version` | string | `v1.19.29` | Clash 版本标签，留空使用默认值。指定版本下载失败会自动 fallback 到 latest |
| `subscription_refresh_minutes` | int | `0` | 订阅自动刷新间隔（分钟）。`0` 表示不自动刷新 |
| `log_level` | string | `warning` | Clash 日志转写到 AstrBot 的级别过滤：`info` / `warning` / `error` |

---

## 🚀 使用方法

### 指令

| 指令 | 说明 |
|------|------|
| `/clash status` | 查看运行状态（PID、端口、版本、二进制路径） |
| `/clash start` | 启动 Clash（首次启动由插件自动完成） |
| `/clash stop` | 停止 Clash 进程 |
| `/clash restart` | 重启 Clash（顺便重新拉取订阅） |
| `/clash version` | 通过 Clash API 查询当前实际运行版本 |

### WebUI

AstrBot Dashboard 内置本插件页面：

```
http://<你的 AstrBot 地址>:<端口>/dashboard/pages/plugin/clash/dashboard/index.html
```

> 路径中的 `clash` 与插件目录名一致，可在 Dashboard 的"插件"标签中找到入口。

WebUI 提供：

- **运行状态徽章**：实时显示是否运行中
- **模式切换**：规则 / 全局 / 直连 三个按钮一键切换
- **代理组卡片**：按订阅中的 Selector 组分类展示
- **节点切换**：点击节点名即可切换
- **测速**：每个节点右侧的"测速"按钮单点测速；顶部"一键测速"对当前模式下可见的全部节点并发测速
- **延迟着色**：< 100ms 绿色、< 300ms 橙色、>= 300ms 红色

### 让 AstrBot 自身走代理

启动成功后，在模型提供商界面代理地址配置填入 http://127.0.0.1:<设置的代理端口号> 即可让大模型请求走本插件启动的代理：

---

## 📁 项目结构

```
astrbot_plugin_clash/
├── main.py                 # 插件入口、指令、Web API 注册
├── _conf_schema.json       # 配置 schema（Dashboard 编辑器使用）
├── metadata.yaml           # 插件元信息
├── src/
│   └── clash_manager.py    #  二进制下载 / 配置生成 / 进程管理 / REST API 客户端
└── pages/
    └── dashboard/          # WebUI 三件套（HTML / CSS / JS）
        ├── index.html
        ├── style.css
        └── app.js
```

---

## 🐳 K8s / Docker 部署提示

- 本插件**不需要特权模式**，不挂载宿主网络
- 二进制与配置存储在 `data/plugins/astrbot_plugin_clash/data/` 下
  - `data/bin/mihomo` (或 `mihomo.exe`)：下载的二进制
  - `data/bin/.version`：当前二进制版本号（变更时自动重新下载）
  - `data/config/config.yaml`：运行时生成的配置
- 首次启动需联网下载 Clash（约 10–50 MB）；网络受限可提前放置二进制到 `data/bin/` 并写入 `data/bin/.version` 对应版本号

---

## 🔧 常见问题

**Q：订阅解析失败？**
A：确认订阅返回标准 YAML（非 Base64 编码）。本插件的 UA 为 `clash-verge/v2.4.0`，部分订阅服务对此敏感。

**Q：端口被占用？**
A：日志中若出现 `address already in use`，请修改 `mixed_port` / `http_port` / `socks_port` / `api_port` 配置项后重启。

**Q：怎么切换到更新的 Clash 版本？**
A：修改 `clash_version` 配置（如 `v1.19.29`），重启插件即可触发自动下载。

**Q：插件卸载后进程还在？**
A：正常情况下 `terminate()` 会通过 `terminate()` → `kill()` 兜底清理；若进程组逃逸，可手动 `pkill mihomo`。

---

## 📜 许可

AGPL 3.0
