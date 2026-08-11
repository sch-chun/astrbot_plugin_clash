"""AstrBot 插件：Clash 代理管理器
启动时自动下载 Clash 二进制、加载订阅配置、运行进程；结束时清理。
"""
import asyncio
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

try:
    from astrbot.api.web import json_response, error_response
    from quart import request
except ImportError:
    from quart import jsonify as json_response, Response as error_response, request

from .src.clash_manager import ClashManager


# 数据存放目录：插件目录下 data/
_PLUGIN_DATA_DIR = Path(__file__).parent / "data"


class ClashPlugin(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.config = config
        self._manager: Optional[ClashManager] = None
        self._started = False

        context.register_web_api("/clash/status", self.status_api, ["GET"], "获取运行状态和代理组")
        context.register_web_api("/clash/proxies", self.proxies_api, ["GET"], "获取所有代理")
        context.register_web_api("/clash/switch", self.switch_api, ["POST"], "切换节点")
        context.register_web_api("/clash/delay", self.delay_api, ["GET"], "测试延迟")
        context.register_web_api("/clash/mode", self.set_mode_api, ["POST"], "设置代理模式")

    async def initialize(self) -> None:
        """插件启动：读取配置，下载/启动 Clash"""
        try:
            cfg = self.config or {}
            subscription_url = (cfg.get("subscription_url") or "").strip()
            mixed_port = int(cfg.get("mixed_port", 7890))
            http_port = int(cfg.get("http_port", 7890))
            socks_port = int(cfg.get("socks_port", 7891))
            api_port = int(cfg.get("api_port", 9090))
            api_secret = (cfg.get("api_secret") or "").strip()
            version = (cfg.get("clash_version") or "v1.19.29").strip()
            subscription_refresh_minutes = int(cfg.get("subscription_refresh_minutes", 0))
            log_level = (cfg.get("log_level") or "info").strip().lower()
            if log_level not in ["info", "warning", "error"]:
                log_level = "warning"

            bin_dir = _PLUGIN_DATA_DIR / "bin"
            work_dir = _PLUGIN_DATA_DIR / "config"

            self._manager = ClashManager(
                bin_dir=bin_dir,
                work_dir=work_dir,
                http_port=http_port,
                socks_port=socks_port,
                api_port=api_port,
                api_secret=api_secret,
                mixed_port=mixed_port,
                log_level=log_level
            )

            if subscription_url:
                self._manager.set_subscription(subscription_url)

            await self._manager.start(version=version)
            self._started = True

            # 如果启用订阅自动刷新
            if subscription_refresh_minutes > 0 and subscription_url:
                asyncio.create_task(self._refresh_loop(subscription_refresh_minutes * 60))
                logger.info(f"已启用订阅自动刷新，间隔 {subscription_refresh_minutes} 分钟")

            logger.info(
                f"✅ Clash 已就绪 (HTTP={http_port}, SOCKS={socks_port}, "
                f"Mixed={mixed_port}, API={api_port})"
            )
        except Exception as e:
            logger.error(f"❌ Clash 插件初始化失败: {e}", exc_info=True)

    async def _refresh_loop(self, interval_seconds: int) -> None:
        """定时刷新订阅"""
        try:
            while self._started and self._manager:
                await asyncio.sleep(interval_seconds)
                if not self._started:
                    return
                try:
                    logger.info("订阅定时刷新开始")
                    await self._manager.restart()
                except Exception as e:
                    logger.error(f"订阅刷新失败: {e}")
        except asyncio.CancelledError:
            return

    async def terminate(self) -> None:
        """插件卸载/停用：清理 Clash 进程"""
        self._started = False
        if self._manager:
            try:
                await self._manager.stop()
            except Exception as e:
                logger.warning(f"停止 Clash 时出错: {e}")
            self._manager = None
        logger.info("Clash 插件已关闭")

    # -------------------- 指令 --------------------

    @filter.command("clash")
    async def clash_command(self, event: AstrMessageEvent):
        """Clash 插件管理指令
        用法：
          /clash status         - 查看当前状态
          /clash restart        - 重启 Clash
          /clash stop           - 停止 Clash
          /clash start          - 启动 Clash
          /clash version        - 查看 Clash 版本
        """
        if not self._manager:
            yield event.plain_result("❌ Clash 插件未初始化")
            return

        args = (event.message_str or "").strip().split()
        sub = args[1] if len(args) > 1 else "status"

        if sub == "status":
            st = self._manager.status()
            lines = ["📊 Clash 状态:"]
            lines.append(f"  运行中: {'✅' if st['running'] else '❌'}")
            lines.append(f"  PID: {st['pid'] or '-'}")
            lines.append(f"  二进制: {st['binary'] or '-'}")
            lines.append(f"  HTTP 端口: {st['http_port']}")
            lines.append(f"  SOCKS 端口: {st['socks_port']}")
            lines.append(f"  API 端口: {st['api_port']}")
            if st["mixed_port"] > 0:
                lines.append(f"  Mixed 端口: {st['mixed_port']}")
            yield event.plain_result("\n".join(lines))

        elif sub == "restart":
            try:
                await self._manager.restart()
                yield event.plain_result("✅ Clash 已重启")
            except Exception as e:
                yield event.plain_result(f"❌ Clash 重启失败: {e}")

        elif sub == "stop":
            await self._manager.stop()
            self._started = False
            yield event.plain_result("✅ Clash 已停止")

        elif sub == "start":
            try:
                cfg = self.config or {}
                version = (cfg.get("clash_version") or "v1.19.29").strip()
                await self._manager.start(version=version)
                self._started = True
                yield event.plain_result("✅ Clash 已启动")
            except Exception as e:
                yield event.plain_result(f"❌ Clash 启动失败: {e}")

        elif sub == "version":
            try:
                import httpx
                url = f"http://127.0.0.1:{self._manager.api_port}/version"
                headers = {"Authorization": f"Bearer {self._manager.api_secret}"} if self._manager.api_secret else {}
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(url, headers=headers)
                    data = r.json()
                yield event.plain_result(
                    f"📦 Clash 版本: {data.get('version', '?')} (premium={data.get('premium', False)})"
                )
            except Exception as e:
                yield event.plain_result(f"❌ 获取版本失败: {e}")

        else:
            yield event.plain_result(
                "可用指令: status / restart / stop / start / version"
            )

    async def status_api(self):
        """返回运行状态 + 代理组简要信息"""
        if not self._manager or not self._manager.is_running():
            return json_response({"running": False})
        try:
            proxies = await self._manager.get_proxies()
            # 提取所有 select 类型的组及其当前节点
            groups = {}
            for name, data in proxies.get("proxies", {}).items():
                if data.get("type") == "Selector" and "all" in data:
                    groups[name] = {
                        "now": data.get("now"),
                        "all": data.get("all", [])
                    }

            # 获取当前模式
            configs = await self._manager._request("GET", "/configs")
            mode = configs.get("mode", "unknown")
            logger.info(f"Clash 状态 API 返回: running=True, groups={list(groups.keys())}, mode={mode}")
            return json_response({"running": True, "groups": groups, "mode": mode})
        except Exception as e:
            return error_response(str(e), status_code=500)

    async def proxies_api(self):
        """返回全部代理数据（用于前端展示）"""
        if not self._manager or not self._manager.is_running():
            return error_response("Clash 未运行", status_code=503)
        try:
            data = await self._manager.get_proxies()
            return json_response(data)
        except Exception as e:
            return error_response(str(e), status_code=500)

    async def switch_api(self):
        """切换节点"""
        if not self._manager or not self._manager.is_running():
            return error_response("Clash 未运行", status_code=503)
        payload = await request.get_json()
        group = payload.get("group")
        node = payload.get("node")
        if not group or not node:
            return error_response("缺少 group 或 node", status_code=400)
        try:
            await self._manager.switch_proxy(group, node)
            return json_response({"success": True})
        except Exception as e:
            logger.error(f"切换节点失败: {e}", exc_info=True)
            return error_response(str(e), status_code=500)

    async def delay_api(self):
        """测试延迟"""
        if not self._manager or not self._manager.is_running():
            return error_response("Clash 未运行", status_code=503)
        group = request.args.get("group")
        node = request.args.get("node")
        timeout = request.args.get("timeout", default=5000, type=int)
        url = request.args.get("url", default="http://www.gstatic.com/generate_204")  # 新增
        if not group:
            return error_response("缺少 group 参数", status_code=400)
        try:
            result = await self._manager.test_delay(group, node, timeout, url)  # 传递 url
            return json_response(result)
        except Exception as e:
            return error_response(str(e), status_code=500)

    async def set_mode_api(self):
        """设置 Clash 运行模式"""
        if not self._manager or not self._manager.is_running():
            return error_response("Clash 未运行", status_code=503)
        payload = await request.get_json()
        mode = payload.get("mode")
        if mode not in ("rule", "global", "direct"):
            return error_response("mode 必须是 rule/global/direct", status_code=400)
        try:
            await self._manager.set_mode(mode)
            return json_response({"success": True, "mode": mode})
        except Exception as e:
            return error_response(str(e), status_code=500)
