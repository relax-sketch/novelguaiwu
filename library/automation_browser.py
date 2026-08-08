"""启动并连接本项目专用的 Chrome profile。

浏览器状态放在用户本地目录，不写入项目数据库，也不复制或读取日常 Chrome
profile。第一次使用请用 ``--visible`` 登录一次，之后任务可自动以 headless
无图模式复用同一 profile。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import urlopen

from .automation_log import LOG_PATH, append_log


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(slots=True)
class BrowserConfig:
    """项目专用浏览器连接配置，可通过 LIBRARY_* 环境变量覆盖。"""

    automation_root: Path
    profile_root: Path
    harness_home: Path
    cdp_port: int = 9333
    daemon_name: str = "guaiwu-paiqu-auto"
    chrome_path: str | None = None
    headless: bool = False
    no_images: bool = True
    startup_timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "BrowserConfig":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.cwd()))
        root = Path(os.environ.get("LIBRARY_AUTOMATION_ROOT", local_app_data / "guaiwu-paiqu" / "browser"))
        return cls(
            automation_root=root,
            profile_root=Path(os.environ.get("LIBRARY_CHROME_PROFILE", root / "ChromeProfile")),
            harness_home=Path(os.environ.get("LIBRARY_BROWSER_HARNESS_HOME", root / "BrowserHarness")),
            cdp_port=max(1024, min(65535, int(os.environ.get("LIBRARY_CDP_PORT", "9333")))),
            daemon_name=os.environ.get("LIBRARY_BROWSER_NAME", "guaiwu-paiqu-auto"),
            chrome_path=os.environ.get("LIBRARY_CHROME_PATH") or None,
            headless=_env_bool("LIBRARY_BROWSER_HEADLESS", False),
            no_images=_env_bool("LIBRARY_BROWSER_NO_IMAGES", True),
            startup_timeout=max(3.0, float(os.environ.get("LIBRARY_BROWSER_STARTUP_TIMEOUT", "20"))),
        )

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.cdp_port}"

    def child_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        env = dict(base or os.environ)
        env.update({"BU_CDP_URL": self.cdp_url, "BU_NAME": self.daemon_name, "BH_HOME": str(self.harness_home)})
        return env


def _find_chrome(config: BrowserConfig) -> str:
    candidates = [
        config.chrome_path,
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise FileNotFoundError("找不到 Chrome，请设置 LIBRARY_CHROME_PATH")


def cdp_version(config: BrowserConfig) -> dict[str, Any] | None:
    try:
        with urlopen(f"{config.cdp_url}/json/version", timeout=2) as response:  # noqa: S310 - loopback only
            payload = json.loads(response.read().decode("utf-8"))
        return payload if payload.get("webSocketDebuggerUrl") else None
    except (OSError, URLError, ValueError, TimeoutError):
        return None


def start_chrome(config: BrowserConfig, *, headless: bool | None = None, no_images: bool | None = None, url: str = "about:blank") -> subprocess.Popen[Any]:
    config.profile_root.mkdir(parents=True, exist_ok=True)
    config.harness_home.mkdir(parents=True, exist_ok=True)
    options = [
        f"--remote-debugging-port={config.cdp_port}",
        f"--user-data-dir={config.profile_root}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if config.headless if headless is None else headless:
        options.append("--headless=new")
    if config.no_images if no_images is None else no_images:
        options.append("--blink-settings=imagesEnabled=false")
    options.append(url)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen([_find_chrome(config), *options], creationflags=creationflags)


def ensure_browser(config: BrowserConfig | None = None) -> BrowserConfig:
    config = config or BrowserConfig.from_env()
    if cdp_version(config):
        return config
    start_chrome(config)
    deadline = time.monotonic() + config.startup_timeout
    while time.monotonic() < deadline:
        if cdp_version(config):
            return config
        time.sleep(0.25)
    raise RuntimeError(f"专用 Chrome 未在 {config.startup_timeout:g} 秒内就绪：{config.cdp_url}")


def _run_harness_stream_once(command: list[str], program: str, *, timeout: int, env: dict[str, str], on_stdout_line: Any | None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=Path(__file__).resolve().parents[1], env=env)
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(program); proc.stdin.close()
    events: queue.Queue[tuple[str, str | None]] = queue.Queue()
    def pump(stream: Any, kind: str) -> None:
        for line in stream:
            events.put((kind, line))
        events.put((kind, None))
    threads = [threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True), threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True)]
    for thread in threads: thread.start()
    stdout_lines: list[str] = []; stderr_lines: list[str] = []; closed = set(); deadline = time.monotonic() + timeout
    while len(closed) < 2:
        if time.monotonic() > deadline:
            proc.kill(); append_log("harness_timeout", timeout=timeout); break
        try: kind, line = events.get(timeout=0.2)
        except queue.Empty: continue
        if line is None: closed.add(kind); continue
        if kind == "stdout":
            stdout_lines.append(line)
            if on_stdout_line: on_stdout_line(line.rstrip("\r\n"))
        else: stderr_lines.append(line)
    proc.wait(timeout=10)
    return subprocess.CompletedProcess(command, proc.returncode, "".join(stdout_lines), "".join(stderr_lines))


def run_harness(program: str, *, timeout: int, config: BrowserConfig | None = None, on_stdout_line: Any | None = None) -> subprocess.CompletedProcess[str]:
    config = ensure_browser(config)
    env = config.child_env()
    env["LIBRARY_AUTOMATION_LOG"] = str(LOG_PATH)
    command = ["uv", "run", "browser-harness"]
    append_log("harness_start", timeout=timeout, daemon=config.daemon_name, program_bytes=len(program.encode("utf-8")))
    proc = _run_harness_stream_once(command, program, timeout=timeout, env=env, on_stdout_line=on_stdout_line)
    append_log("harness_end", returncode=proc.returncode, stdout_bytes=len(proc.stdout.encode("utf-8")), stderr_tail=proc.stderr[-1000:])
    if proc.returncode and "PermissionError" in proc.stderr and f"bu-{config.daemon_name}.port" in proc.stderr:
        # 只重载当前项目的隔离 daemon；不删除或触碰其他项目的状态。
        subprocess.run([*command, "--reload"], text=True, encoding="utf-8", cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30, env=env)
        proc = _run_harness_stream_once(command, program, timeout=timeout, env=env, on_stdout_line=on_stdout_line)
    return proc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动本项目专用 Chrome profile")
    parser.add_argument("--headless", action="store_true", help="以 headless 模式启动；默认使用可见窗口")
    parser.add_argument("--with-images", action="store_true", help="启动时允许加载图片")
    parser.add_argument("--url", default="about:blank")
    args = parser.parse_args(argv)
    config = BrowserConfig.from_env()
    if cdp_version(config):
        print(f"专用 Chrome 已运行：{config.cdp_url}")
        return 0
    start_chrome(config, headless=args.headless, no_images=not args.with_images, url=args.url)
    ensure_browser(config)
    print(f"专用 Chrome 已就绪：{config.cdp_url}")
    print(f"profile：{config.profile_root}")
    print(f"Browser Harness：{config.harness_home}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
