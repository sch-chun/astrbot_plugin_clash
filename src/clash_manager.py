"""Clash 二进制下载、配置生成、进程管理"""
from __future__ import annotations

import asyncio
import gzip
import platform
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote
import re
import cpuinfo

from typing import Optional, Any
from asyncio.subprocess import Process

import httpx
import yaml
from astrbot.api import logger


def _detect_arch() -> tuple[str, str]:
    """根据当前平台返回 release 的 (os, arch)"""
    sys_platform = sys.platform.lower()
    machine = platform.machine().lower()

    if sys_platform.startswith("linux"):
        os_name = "linux"
    elif sys_platform.startswith("darwin"):
        os_name = "darwin"
    elif sys_platform.startswith("win"):
        os_name = "windows"
    elif sys_platform.startswith("freebsd"):
        os_name = "freebsd"
    else:
        os_name = "linux"

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine.startswith("armv7"):
        arch = "armv7"
    elif machine in ("i386", "i686"):
        arch = "386"
    else:
        arch = machine

    return os_name, arch


def _asset_extension(os_name: str) -> str:
    return "zip" if os_name == "windows" else "gz"


def _detect_go_amd64_level() -> str:
    """自动检测 CPU 支持的 GOAMD64 等级，仅用于 Windows AMD64"""
    try:
        info = cpuinfo.get_cpu_info()
        flags = [f.lower() for f in info.get('flags', [])]

        # 判断 v3
        if {'avx2', 'bmi1', 'bmi2', 'fma', 'lzcnt', 'movbe'}.issubset(set(flags)):
            return "v3"
        
        # 判断 v2
        if {'popcnt', 'sse4_1', 'sse4_2', 'ssse3'}.issubset(set(flags)):
            return "v2"
        return "v1"
    except Exception:
        return "v1"  # 保底


class ClashManager:
    """管理 Clash 二进制、配置和进程生命周期"""
    def __init__(
        self,
        bin_dir: Path,
        work_dir: Path,
        http_port: int = 7890,
        socks_port: int = 7891,
        api_port: int = 9090,
        api_secret: str = "",
        mixed_port: int = 0,
        log_level: str = "warning",
        download_base_url: str = "https://github.com/MetaCubeX/mihomo/releases/download",
        go_amd64_level: str = "auto",
        geoip_url: Optional[str] = None
    ) -> None:
        self.bin_dir = bin_dir
        self.work_dir = work_dir
        self.http_port = http_port
        self.socks_port = socks_port
        self.api_port = api_port
        self.api_secret = api_secret
        self.mixed_port = mixed_port
        self.log_level = log_level

        self._process: Optional[Process] = None
        self._binary_path: Optional[Path] = None
        self._subscription_url: Optional[str] = None
        self._custom_config: Optional[dict] = None

        self._stderr_errors = []
        self._proxy_ready = False  # 是否看到代理端口成功日志
        self._api_ready = False    # 是否看到 API 成功日志

        self.LOG_LEVELS = {"info": 0, "warning": 1, "error": 2}

        self.download_base_url = download_base_url

        self.go_amd64_level = go_amd64_level.lower()
        self._resolved_level = None

        self.geoip_url = geoip_url

    # -------------------- 二进制管理 --------------------

    def _resolve_level(self) -> str:
        """解析 go_amd64_level"""
        if self.go_amd64_level == "auto":
            if self._resolved_level is None:
                self._resolved_level = _detect_go_amd64_level()
                logger.info(f"自动检测到 CPU 等级: {self._resolved_level}")
            return self._resolved_level

        # 用户手动指定
        if self.go_amd64_level in ("v1", "v2", "v3", "compatible"):
            return self.go_amd64_level

        # 其它值视为 auto
        logger.warning(f"无效的 go_amd64_level: {self.go_amd64_level}，回退到自动检测")
        return _detect_go_amd64_level()

    async def ensure_binary(self, version: str = "v1.18.10") -> Path:
        """确保 Clash 二进制存在；缺失则下载。返回二进制路径"""
        self.bin_dir.mkdir(parents=True, exist_ok=True)

        os_name, arch = _detect_arch()
        is_windows = os_name == "windows"
        ext = _asset_extension(os_name)

        # 简化版二进制命名
        binary_filename = "mihomo.exe" if is_windows else "mihomo"
        binary_path = self.bin_dir / binary_filename

        version_file = self.bin_dir / ".version"

        # 检查版本文件
        current_version = None
        if version_file.exists():
            current_version = version_file.read_text().strip()

        # 如果二进制存在且版本匹配，直接返回
        if binary_path.exists() and current_version == version:
            logger.info(f"Clash 二进制已存在: {binary_path}")
            self._binary_path = binary_path
            return binary_path

        # 否则删除旧二进制（如果有）并重新下载
        if binary_path.exists():
            logger.info(f"版本变更 ({current_version} -> {version})，重新下载 Clash")
            binary_path.unlink()
        if version_file.exists():
            version_file.unlink()

        # 基础名称
        base = f"mihomo-{os_name}-{arch}"
        level_suffix = ""

        # 只有 AMD64 需要附加 GOAMD64 等级
        if arch == "amd64":

            # 解析等级
            level = self._resolve_level()
            if level:
                level_suffix = f"-{level}"
            else:
                logger.warning("无法自动检测 CPU 等级，将使用默认等级 compatible")
                level_suffix = "-compatible"

        # 下载 release asset
        asset_name = f"{base}{level_suffix}-{version}.{ext}"
        url = f"{self.download_base_url}/{version}/{asset_name}"
        compressed_path = self.bin_dir / asset_name

        logger.info(f"开始下载 Clash: {url}")
        try:
            await self._download_file(url, compressed_path)
        except Exception as e:

            # 尝试不带版本号（latest）的命名
            alt_asset_name = f"mihomo-{os_name}-{arch}.{ext}"
            alt_url = f"{self.download_base_url}/latest/download/{alt_asset_name}"
            logger.warning(f"指定版本下载失败: {e}，尝试 latest: {alt_url}")
            await self._download_file(alt_url, self.bin_dir / alt_asset_name)
            compressed_path = self.bin_dir / alt_asset_name

        # 解压
        logger.info(f"解压 Clash 到 {binary_path}")
        if ext == "gz":
            with gzip.open(compressed_path, "rb") as gz:
                with open(binary_path, "wb") as out:
                    shutil.copyfileobj(gz, out)
        else:  # zip
            with zipfile.ZipFile(compressed_path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(".exe") or name == "mihomo":
                        with zf.open(name) as src, open(binary_path, "wb") as out:
                            shutil.copyfileobj(src, out)
                        break

        # 加执行权限
        if not is_windows:
            current = binary_path.stat().st_mode
            binary_path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        # 清理压缩包
        try:
            compressed_path.unlink()
        except Exception:
            pass

        # 验证
        if not binary_path.exists() or binary_path.stat().st_size < 1024 * 1024:
            raise RuntimeError(f"Clash 二进制安装失败: {binary_path}")

        version_file.write_text(version)
        self._binary_path = binary_path
        logger.info(f"Clash 已就绪: {binary_path} ({binary_path.stat().st_size / 1024 / 1024:.1f} MB)")
        return binary_path

    @staticmethod
    async def _download_file(url: str, dest: Path, timeout: float = 60.0) -> None:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        f.write(chunk)

    # -------------------- 配置生成 --------------------

    def set_subscription(self, url: str) -> None:
        """设置订阅 URL，启动时拉取"""
        self._subscription_url = url

    def set_custom_config(self, config: dict) -> None:
        """使用自定义配置 dict（不通过订阅）"""
        self._custom_config = config

    async def _fetch_subscription(self) -> dict:
        assert self._subscription_url
        logger.info(f"拉取订阅配置: {self._subscription_url[:60]}...")

        # 设置 User-Agent 模拟 Clash 客户端
        headers = {
            "User-Agent": "clash-verge/v2.4.0"  # 或 "Clash"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(self._subscription_url, headers=headers)
            resp.raise_for_status()
            raw_text = resp.text.strip()

        # 现在 raw_text 应该是标准的 YAML 配置，直接解析
        try:
            cfg = yaml.safe_load(raw_text)
            if isinstance(cfg, dict):
                logger.info("订阅解析成功 (YAML)")
                return cfg
            else:
                raise RuntimeError("订阅返回的不是 YAML 字典")
        except yaml.YAMLError as e:

            # 如果仍然失败，可以尝试 Base64 解码等 fallback（可选）
            # 但鉴于 curl 已经成功，这里大概率不会失败
            raise RuntimeError(f"YAML 解析失败: {e}")

    def _default_config(self) -> dict:
        """生成默认的 Clash 配置（混合端口 + API）"""

        # 使用 mixed-port 同时提供 HTTP/SOCKS
        listeners: list[dict] = []
        if self.mixed_port > 0:
            listeners.append({
                "name": "mixed",
                "type": "mixed",
                "port": self.mixed_port,
                "listen": "127.0.0.1",
            })
        else:
            listeners.append({
                "name": "http",
                "type": "http",
                "port": self.http_port,
                "listen": "127.0.0.1",
            })
            listeners.append({
                "name": "socks",
                "type": "socks",
                "port": self.socks_port,
                "listen": "127.0.0.1",
            })

        return {
            "mixed-port": self.mixed_port if self.mixed_port > 0 else None,
            "port": None if self.mixed_port > 0 else self.http_port,
            "socks-port": None if self.mixed_port > 0 else self.socks_port,
            "allow-lan": False,
            "mode": "rule",
            "log-level": "warning",
            "external-controller": f"127.0.0.1:{self.api_port}",
            "external-controller-cors": {
                "allow-private-network": True,
                "allow-origins": ["*"],
                "allow-methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
                "allow-headers": ["*"],
                "expose-headers": ["*"],
            },
            "secret": self.api_secret or "",
            "listeners": listeners,
            "proxies": [],
            "proxy-groups": [
                {
                    "name": "manual",
                    "type": "select",
                    "proxies": ["DIRECT"],
                }
            ],
            "rules": [
                "MATCH,manual",
            ],
        }

    async def write_config(self) -> Path:
        """生成 config.yaml，返回配置文件路径"""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.work_dir / "config.yaml"

        if self._subscription_url:
            cfg = await self._fetch_subscription()
        elif self._custom_config:
            cfg = self._custom_config
        else:
            cfg = self._default_config()

        # 强制覆盖代理端口和 external-controller
        cfg["external-controller"] = f"127.0.0.1:{self.api_port}"
        if self.api_secret:
            cfg["secret"] = self.api_secret
        if self.mixed_port > 0:
            cfg["mixed-port"] = self.mixed_port
            cfg.pop("port", None)
            cfg.pop("socks-port", None)

        # 移除 listeners
        cfg.pop("listeners", None)

        # 写入 GeoIP 下载地址
        if self.geoip_url:
            url_lower = self.geoip_url.lower()

            # 如果是 .dat 文件，则启用 geodata-mode
            if url_lower.endswith(".dat"):
                cfg["geodata-mode"] = True
            cfg["geox-url"] = {
                "geoip": self.geoip_url,
            }
            

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

        logger.info(f"已写入 Clash 配置: {config_path}")
        return config_path

    # -------------------- 进程管理 --------------------

    def _should_log(self, level_str: str) -> bool:
        """判断该级别的日志是否应该打印"""
        current = self.LOG_LEVELS.get(level_str, 0)
        threshold = self.LOG_LEVELS.get(self.log_level, 0)
        return current >= threshold

    async def _read_output(self):
        """读取 stdout（包含所有日志），解析关键状态"""
        if self._process is None or self._process.stdout is None:
            logger.error("尝试读取未启动的 Clash 进程输出")
            return
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="ignore").strip()

            # 解析 level
            level = "info"
            match = re.search(r'level=(\w+)', decoded)
            if match:
                level = match.group(1).lower()

            # 根据配置决定是否打印
            if self._should_log(level):
                logger.info(f"[Clash] {decoded}")

            # 检测就绪标志
            if "Mixed(http+socks) proxy listening at" in decoded:
                self._proxy_ready = True
            if "RESTful API listening at" in decoded:
                self._api_ready = True

            # 检测错误
            if level == "error" and not (self._api_ready and self._proxy_ready):
                self._stderr_errors.append(decoded)

    async def start(self, version) -> None:
        """下载/校验二进制，写入配置，启动进程"""
        if self.is_running():
            logger.warning("Clash 已经在运行中")
            return

        await self.ensure_binary(version)
        await self.write_config()

        assert self._binary_path is not None

        # 使用异步子进程，捕获输出
        self._process = await asyncio.create_subprocess_exec(
            str(self._binary_path), "-d", str(self.work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

        # 启动 stderr 读取任务
        self._stderr_errors = []
        self._output_task = asyncio.create_task(self._read_output())

        try:
            await self._wait_for_ready(timeout=120.0)
        except Exception:

            # 如果异常，确保进程被终止
            await self._terminate_process()
            raise
        logger.info(f"Clash 启动成功 (pid={self._process.pid})")

    async def _wait_for_ready(self, timeout: float = 120.0):
        """等待 API 和代理端口都就绪，或检测到错误，超时则抛出异常"""
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:

            # 优先检查错误
            if self._stderr_errors:
                raise RuntimeError(f"Clash 启动错误: {self._stderr_errors[-1]}")

            # 检查进程是否退出
            if self._process and self._process.returncode is not None:
                error_msg = ""
                if self._process.stdout:
                    try:
                        remaining = await self._process.stdout.read()
                        error_msg = remaining.decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                raise RuntimeError(f"Clash 进程异常退出 (code={self._process.returncode})\n{error_msg}")
            
            # 检查是否两者都就绪
            if self._api_ready and self._proxy_ready:
                return
            await asyncio.sleep(0.2)

        # 超时，给出具体未就绪的原因
        if not self._api_ready:
            raise RuntimeError("等待 API 就绪超时")
        if not self._proxy_ready:
            raise RuntimeError("等待代理端口就绪超时")

    async def _terminate_process(self):
        """终止 Clash 进程并清理任务"""
        if self._process is None:
            return
        if self._process.returncode is not None:
            logger.warn(f"Clash 进程已退出 (code={self._process.returncode})，跳过终止")
            self._process = None
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()
        if hasattr(self, '_output_task') and self._output_task:
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass
        self._process = None
        self._output_task = None

    async def stop(self, timeout: float = 5.0) -> None:
        """停止 Clash 进程"""
        if not self._process:
            return
        logger.info(f"正在停止 Clash (pid={self._process.pid})")
        await self._terminate_process()
        logger.info("Clash 已停止")

    async def restart(self, version: str = "v1.18.10") -> None:
        """重启 Clash"""
        await self.stop()
        await self.start(version)

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "pid": self._process.pid if self._process and self.is_running() else None,
            "binary": str(self._binary_path) if self._binary_path else None,
            "http_port": self.http_port,
            "socks_port": self.socks_port,
            "api_port": self.api_port,
            "mixed_port": self.mixed_port,
        }

    def _api_base_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    def _api_headers(self) -> dict[str, str]:
        headers = {}
        if self.api_secret:
            headers["Authorization"] = f"Bearer {self.api_secret}"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        """发送请求到 Clash REST API，自动对路径参数进行 URL 编码"""

        # 分割路径，编码每个片段，再重新组合
        parts = path.split('/')
        encoded_parts = [quote(part, safe='') for part in parts if part != '']
        encoded_path = '/' + '/'.join(encoded_parts)
        url = f"{self._api_base_url()}{encoded_path}"
        headers = self._api_headers()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()

    async def get_proxies(self) -> dict:
        """获取所有代理信息"""
        return await self._request("GET", "/proxies")

    async def switch_proxy(self, group_name: str, node_name: str) -> None:
        """切换指定组的节点"""
        await self._request("PUT", f"/proxies/{group_name}", json={"name": node_name})

    async def test_delay(self, group_name: str, node_name: Optional[str] = None, timeout: int = 5000, url: str = "http://www.gstatic.com/generate_204") -> dict:
        """
        测试节点延迟
        - node_name 为空则测试该组全部节点
        - url 为测速目标地址
        - 返回 { node_name: delay } 或测试结果
        """
        params = {"timeout": timeout, "url": url}  # 同时传递 timeout 和 url
        if node_name:
            result = await self._request("GET", f"/proxies/{node_name}/delay", params=params)
            return {node_name: result.get("delay")}
        else:

            # 测试组内所有节点
            result = await self._request("GET", f"/group/{group_name}/delay", params=params)
            return result

    async def set_mode(self, mode: str) -> None:
        """切换运行模式: rule / global / direct"""
        try:
            await self._request("PATCH", "/configs", json={"mode": mode})
            logger.info(f"模式切换成功")
        except Exception as e:
            logger.error(f"模式切换失败: {e}")
            raise
        