# astrbot_plugin_clash

在 AstrBot 插件中直接运行 Clash代理，适合 K8s 环境使用。

## 功能

- 启动时自动从载二进制
- 支持订阅地址（自动拉取并解析）
- 进程生命周期管理（启动/停止/重启）
- 自定义端口配置
- 订阅自动刷新
- 通过 `/clash` 指令管理

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `subscription_url` | string | `""` | Clash 订阅地址 |
| `auto_start` | boolean | `true` | 是否自动运行 |
| `mixed_port` | integer | `7890` | 混合端口（HTTP+SOCKS5），设为 0 则禁用 |
| `http_port` | integer | `7890` | HTTP 端口（mixed_port=0 时生效） |
| `socks_port` | integer | `7891` | SOCKS5 端口（mixed_port=0 时生效） |
| `api_port` | integer | `9090` | RESTful API 端口 |
| `api_secret` | string | `""` | API 密钥 |
| `clash_version` | string | `v1.18.10` | Clash 版本标签 |
| `subscription_refresh_minutes` | integer | `0` | 订阅刷新间隔（分钟） |

## 指令

- `/clash status` - 查看运行状态
- `/clash restart` - 重启 Clash
- `/clash stop` - 停止 Clash
- `/clash start` - 启动 Clash
- `/clash version` - 查看 Clash 版本
