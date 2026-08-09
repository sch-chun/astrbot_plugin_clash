"""AstrBot 插件：Clash (mihomo) 代理管理器
启动时自动下载 mihomo 二进制、加载订阅配置、运行进程；结束时清理。
"""
import asyncio
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .src.clash_manager import ClashManager

# 数据存放目录：插件目录下 data/
DATA_DIR = Path(__file__).parent / "data"


@register(
    "astrbot_plugin_clash",
    "sch-chun",
    "Clash (mihomo) 代理管理器，启动时自动安装并运行，结束时自动终止",
    "0.1.0",
    "https://github.com/sch-chun/astrbot_plugin_clash",
)
class ClashPlugin(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.config = config
        self._manager: Optional[ClashManager] = None
        self._started = False
        self._version = "v1.19.29"

    def _read_config(self) -> dict:
        cfg = self.config or {}
        return {
            "subscription_url": (cfg.get("subscription_url") or "").strip(),
            "mixed_port": int(cfg.get("mixed_port", 7890)),
            "http_port": int(cfg.get("http_port", 7890)),
            "socks_port": int(cfg.get("socks_port", 7891)),
            "api_port": int(cfg.get("api_port", 9090)),
            "api_secret": (cfg.get("api_secret") or "").strip(),
            "version": (cfg.get("mihomo_version") or "v1.19.29").strip(),
            "auto_start": bool(cfg.get("auto_start", True)),
            "refresh_minutes": int(cfg.get("subscription_refresh_minutes", 0)),
        }

    def _build_manager(self, cfg: dict) -> ClashManager:
        manager = ClashManager(
            bin_dir=DATA_DIR / "bin",
            work_dir=DATA_DIR / "config",
            http_port=cfg["http_port"],
            socks_port=cfg["socks_port"],
            api_port=cfg["api_port"],
            api_secret=cfg["api_secret"],
            mixed_port=cfg["mixed_port"],
        )
        if cfg["subscription_url"]:
            manager.set_subscription(cfg["subscription_url"])
        return manager

    async def initialize(self) -> None:
        """插件启动：读取配置，下载/启动 Clash"""
        try:
            cfg = self._read_config()
            self._version = cfg["version"]

            if not cfg["auto_start"]:
                logger.info("Clash 插件配置 auto_start=false，跳过启动")
                return

            self._manager = self._build_manager(cfg)
            await self._manager.start(version=self._version)
            self._started = True

            # 启用订阅自动刷新
            if cfg["refresh_minutes"] > 0 and cfg["subscription_url"]:
                asyncio.create_task(
                    self._refresh_loop(cfg["refresh_minutes"] * 60)
                )
                logger.info(f"已启用订阅自动刷新，间隔 {cfg['refresh_minutes']} 分钟")

            logger.info(f"✅ Clash 已就绪 (pid={self._manager._process.pid if self._manager._process else '?'})")
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
                    await self._manager.restart(version=self._version)
                except Exception as e:
                    logger.error(f"订阅刷新失败: {e}")
        except asyncio.CancelledError:
            return

    async def terminate(self) -> None:
        """插件卸载/停用：清理 mihomo 进程"""
        self._started = False
        if self._manager:
            try:
                await self._manager.stop()
            except Exception as e:
                logger.warning(f"停止 mihomo 时出错: {e}")
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
          /clash version        - 查看 mihomo 版本
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
                await self._manager.restart(version=self._version)
                self._started = True
                yield event.plain_result("✅ Clash 已重启")
            except Exception as e:
                yield event.plain_result(f"❌ Clash 重启失败: {e}")

        elif sub == "stop":
            await self._manager.stop()
            self._started = False
            yield event.plain_result("✅ Clash 已停止")

        elif sub == "start":
            try:
                await self._manager.start(version=self._version)
                self._started = True
                yield event.plain_result("✅ Clash 已启动")
            except Exception as e:
                yield event.plain_result(f"❌ Clash 启动失败: {e}")

        elif sub == "version":
            try:
                import httpx
                url = f"http://127.0.0.1:{self._manager.api_port}/version"
                headers = {}
                if self._manager.api_secret:
                    headers["Authorization"] = f"Bearer {self._manager.api_secret}"
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(url, headers=headers)
                    data = r.json()
                yield event.plain_result(
                    f"📦 mihomo 版本: {data.get('version', '?')} "
                    f"(premium={data.get('premium', False)})"
                )
            except Exception as e:
                yield event.plain_result(f"❌ 获取版本失败: {e}")

        else:
            yield event.plain_result(
                "可用指令: status / restart / stop / start / version"
            )