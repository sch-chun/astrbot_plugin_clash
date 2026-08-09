"""Clash (mihomo) 二进制下载、配置生成、进程管理"""
from __future__ import annotations

import asyncio
import gzip
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote

from typing import Optional, Any

import httpx
import yaml
from astrbot.api import logger

# mihomo release asset 名模板
# 官方命名：mihomo-{os}-{arch}-{version}.gz （linux/freebsd/darwin/windows, amd64/arm64/...）
MIHOMO_RELEASE_BASE = "https://github.com/MetaCubeX/mihomo/releases/download"


def _detect_arch() -> tuple[str, str]:
    """根据当前平台返回 mihomo release 的 (os, arch)"""
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


class ClashManager:
    """管理 mihomo 二进制、配置和进程生命周期"""

    def __init__(
        self,
        bin_dir: Path,
        work_dir: Path,
        http_port: int = 7890,
        socks_port: int = 7891,
        api_port: int = 9090,
        api_secret: str = "",
        mixed_port: int = 0,
    ) -> None:
        self.bin_dir = bin_dir
        self.work_dir = work_dir
        self.http_port = http_port
        self.socks_port = socks_port
        self.api_port = api_port
        self.api_secret = api_secret
        self.mixed_port = mixed_port

        self._process: Optional[subprocess.Popen] = None
        self._binary_path: Optional[Path] = None
        self._subscription_url: Optional[str] = None
        self._custom_config: Optional[dict] = None

    # -------------------- 二进制管理 --------------------

    async def ensure_binary(self, version: str = "v1.18.10") -> Path:
        """确保 mihomo 二进制存在；缺失则下载。返回二进制路径"""
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
            logger.info(f"mihomo 二进制已存在: {binary_path}")
            self._binary_path = binary_path
            return binary_path

        # 否则删除旧二进制（如果有）并重新下载
        if binary_path.exists():
            logger.info(f"版本变更 ({current_version} -> {version})，重新下载 mihomo")
            binary_path.unlink()
        if version_file.exists():
            version_file.unlink()

        # 下载 release asset
        asset_name = f"mihomo-{os_name}-{arch}-{version}.{ext}"
        url = f"{MIHOMO_RELEASE_BASE}/{version}/{asset_name}"
        compressed_path = self.bin_dir / asset_name

        logger.info(f"开始下载 mihomo: {url}")
        try:
            await self._download_file(url, compressed_path)
        except Exception as e:
            # 尝试不带版本号（latest）的命名
            alt_asset_name = f"mihomo-{os_name}-{arch}.{ext}"
            alt_url = f"https://github.com/MetaCubeX/mihomo/releases/latest/download/{alt_asset_name}"
            logger.warning(f"指定版本下载失败: {e}，尝试 latest: {alt_url}")
            await self._download_file(alt_url, self.bin_dir / alt_asset_name)
            compressed_path = self.bin_dir / alt_asset_name

        # 解压
        logger.info(f"解压 mihomo 到 {binary_path}")
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
            raise RuntimeError(f"mihomo 二进制安装失败: {binary_path}")

        version_file.write_text(version)
        self._binary_path = binary_path
        logger.info(f"mihomo 已就绪: {binary_path} ({binary_path.stat().st_size / 1024 / 1024:.1f} MB)")
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

        # 关键：设置 User-Agent 模拟 Clash 客户端
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
        """生成默认的 mihomo 配置（混合端口 + API）"""
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

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

        logger.info(f"已写入 Clash 配置: {config_path}")
        return config_path

    # -------------------- 进程管理 --------------------

    async def start(self, version: str = "v1.18.10") -> None:
        """下载/校验二进制，写入配置，启动进程"""
        if self.is_running():
            logger.warning("mihomo 已经在运行中")
            return

        await self.ensure_binary(version)
        config_path = await self.write_config()

        assert self._binary_path is not None

        log_path = self.work_dir / "mihomo.log"
        log_file = open(log_path, "ab")

        logger.info(f"启动 mihomo: {self._binary_path} -d {self.work_dir}")
        self._process = subprocess.Popen(
            [str(self._binary_path), "-d", str(self.work_dir)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

        # 等待外部 API 起来
        await self._wait_api(timeout=120.0)
        logger.info(f"mihomo 启动成功 (pid={self._process.pid})")

    async def _wait_api(self, timeout: float = 15.0) -> None:
        """等待外部 API 可访问"""
        url = f"http://127.0.0.1:{self.api_port}/version"
        headers = {}
        if self.api_secret:
            headers["Authorization"] = f"Bearer {self.api_secret}"

        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient(timeout=3.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                if self._process and self._process.poll() is not None:
                    raise RuntimeError(f"mihomo 进程异常退出 (code={self._process.returncode})")
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError("等待 mihomo API 超时")

    async def stop(self, timeout: float = 5.0) -> None:
        """停止 mihomo 进程"""
        proc = self._process
        self._process = None
        if not proc:
            return
        if proc.poll() is not None:
            return

        logger.info(f"正在停止 mihomo (pid={proc.pid})")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("mihomo 未响应 SIGTERM，发送 SIGKILL")
                proc.kill()
                proc.wait(timeout=2.0)
        except Exception as e:
            logger.error(f"停止 mihomo 时出错: {e}")

    async def restart(self, version: str = "v1.18.10") -> None:
        """重启 mihomo"""
        await self.stop()
        await self.start(version)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

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
        """发送请求到 mihomo REST API，自动对路径参数进行 URL 编码"""
        # 分割路径，编码每个片段，再重新组合
        parts = path.split('/')
        encoded_parts = [quote(part, safe='') for part in parts if part != '']
        encoded_path = '/' + '/'.join(encoded_parts)
        url = f"{self._api_base_url()}{encoded_path}"
        headers = self._api_headers()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def get_proxies(self) -> dict:
        """获取所有代理信息"""
        return await self._request("GET", "/proxies")

    async def switch_proxy(self, group_name: str, node_name: str) -> None:
        """切换指定组的节点"""
        await self._request("PUT", f"/proxies/{group_name}", json={"name": node_name})

    async def test_delay(self, group_name: str, node_name: str = None, timeout: int = 5000) -> dict:
        """
        测试节点延迟
        - node_name 为空则测试该组全部节点
        - 返回 { node_name: delay } 或测试结果
        """
        if node_name:
            # 测试单个节点
            result = await self._request("GET", f"/proxies/{node_name}/delay", params={"timeout": timeout})
            return {node_name: result.get("delay")}
        else:
            # 测试组内所有节点（mihomo 支持 group 级别测试）
            result = await self._request("GET", f"/group/{group_name}/delay", params={"timeout": timeout})
            return result  # 格式类似 {"node1": 100, "node2": 200}
