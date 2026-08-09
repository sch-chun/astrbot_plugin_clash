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
from typing import Optional

import httpx
import yaml
from astrbot.api import logger

# mihomo (原 Clash Meta) 的 GitHub Releases
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


def _binary_name(os_name: str) -> str:
    return "mihomo.exe" if os_name == "windows" else "mihomo"


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

    async def ensure_binary(self, version: str = "v1.19.29") -> Path:
        """确保 mihomo 二进制存在；缺失则下载。返回二进制路径"""
        self.bin_dir.mkdir(parents=True, exist_ok=True)

        os_name, arch = _detect_arch()
        is_windows = os_name == "windows"
        ext = _asset_extension(os_name)
        bin_name = _binary_name(os_name)

        binary_path = self.bin_dir / bin_name

        # 已存在且大小合理 -> 跳过
        if binary_path.exists() and binary_path.stat().st_size > 1024 * 1024:
            logger.info(f"mihomo 二进制已存在: {binary_path}")
            self._binary_path = binary_path
            return binary_path

        # 尝试下载：优先 plain 名，失败则试 compatible 变体
        asset_names = [
            f"mihomo-{os_name}-{arch}-{version}.{ext}",
            f"mihomo-{os_name}-{arch}-compatible-{version}.{ext}",
        ]

        downloaded = False
        compressed_path = self.bin_dir / asset_names[0]

        for asset_name in asset_names:
            url = f"{MIHOMO_RELEASE_BASE}/{version}/{asset_name}"
            compressed_path = self.bin_dir / asset_name
            logger.info(f"尝试下载 mihomo: {url}")
            try:
                await self._download_file(url, compressed_path)
                downloaded = True
                break
            except Exception as e:
                logger.warning(f"下载失败 ({asset_name}): {e}")
                continue

        if not downloaded:
            raise RuntimeError(
                f"无法下载 mihomo {version}，请检查版本号是否正确。"
                f"已尝试: {asset_names}"
            )

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

        self._binary_path = binary_path
        logger.info(
            f"mihomo 已就绪: {binary_path} "
            f"({binary_path.stat().st_size / 1024 / 1024:.1f} MB)"
        )
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
        """拉取订阅配置；支持 base64 编码的 yaml 和裸 yaml"""
        assert self._subscription_url
        logger.info(f"拉取订阅配置: {self._subscription_url}")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(self._subscription_url)
            resp.raise_for_status()
            text = resp.text

        # 尝试当作 base64 解码（很多机场订阅是 base64 编码的 yaml）
        stripped = text.strip()
        if not stripped.startswith(("port:", "mixed-port:", "proxies:", "{")):
            try:
                import base64
                decoded = base64.b64decode(stripped).decode("utf-8")
                if decoded.strip().startswith(("port:", "mixed-port:", "proxies:")):
                    text = decoded
            except Exception:
                pass

        try:
            cfg = yaml.safe_load(text)
            if not isinstance(cfg, dict):
                raise RuntimeError("订阅内容不是有效的 YAML 对象")
            return cfg
        except yaml.YAMLError as e:
            raise RuntimeError(f"解析订阅 YAML 失败: {e}")

    def _default_config(self) -> dict:
        """生成默认的 mihomo 配置（使用标准顶层端口键，非 listeners 数组）"""
        cfg: dict = {
            "allow-lan": False,
            "mode": "rule",
            "log-level": "warning",
            "external-controller": f"127.0.0.1:{self.api_port}",
            "secret": self.api_secret or "",
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

        # 使用 mixed-port 或传统的 port+socks-port
        if self.mixed_port > 0:
            cfg["mixed-port"] = self.mixed_port
        else:
            cfg["port"] = self.http_port
            cfg["socks-port"] = self.socks_port

        return cfg

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
        else:
            cfg.pop("mixed-port", None)
            cfg["port"] = self.http_port
            cfg["socks-port"] = self.socks_port

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

        logger.info(f"已写入 Clash 配置: {config_path}")
        return config_path

    # -------------------- 进程管理 --------------------

    async def start(self, version: str = "v1.19.29") -> None:
        """下载/校验二进制，写入配置，启动进程"""
        if self.is_running():
            logger.warning("mihomo 已经在运行中")
            return

        await self.ensure_binary(version)
        config_path = await self.write_config()

        assert self._binary_path is not None

        # 先测试配置合法性
        logger.info("测试配置合法性...")
        test_proc = subprocess.Popen(
            [str(self._binary_path), "-d", str(self.work_dir), "-t"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = test_proc.communicate(timeout=10)
        if test_proc.returncode != 0:
            raise RuntimeError(f"配置测试失败:\n{stderr.decode(errors='replace')}")

        # 启动进程
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
        await self._wait_api(timeout=15.0)
        logger.info(f"mihomo 启动成功 (pid={self._process.pid})")

    async def _wait_api(self, timeout: float = 15.0) -> None:
        """等待外部 API 可访问"""
        url = f"http://127.0.0.1:{self.api_port}/version"
        headers = {}
        if self.api_secret:
            headers["Authorization"] = f"Bearer {self.api_secret}"

        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(timeout=3.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._process and self._process.poll() is not None:
                    raise RuntimeError(
                        f"mihomo 进程异常退出 (code={self._process.returncode})"
                    )
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

    async def restart(self, version: str = "v1.19.29") -> None:
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