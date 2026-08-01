"""Desktop lifecycle for the frozen application."""

import ctypes
import json
import logging
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


logger = logging.getLogger(__name__)
ERROR_ALREADY_EXISTS = 183
DEFAULT_STARTUP_TIMEOUT = 60.0


def _available_port(host: str, preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, preferred))
            return preferred
        except OSError:
            probe.bind((host, 0))
            return int(probe.getsockname()[1])


def _startup_timeout() -> float:
    try:
        configured = float(os.environ.get("TOUHOU_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT))
    except (TypeError, ValueError):
        configured = DEFAULT_STARTUP_TIMEOUT
    return max(10.0, min(180.0, configured))


def _wait_for_server(host: str, port: int, timeout: float = DEFAULT_STARTUP_TIMEOUT, server_thread=None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_thread is not None and not server_thread.is_alive():
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            if probe.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _acquire_single_instance(runtime_path: Path):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "TouHou_DongfangYibianlu_Instance")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            webbrowser.open(runtime.get("url", "http://127.0.0.1:8000"))
        except (OSError, json.JSONDecodeError):
            webbrowser.open("http://127.0.0.1:8000")
        return None
    return handle


def run_desktop(app, host: str, preferred_port: int, data_dir: Path) -> None:
    runtime_path = data_dir / "runtime.json"
    mutex = _acquire_single_instance(runtime_path)
    if mutex is None:
        return
    port = _available_port(host, preferred_port)
    url = f"http://{host}:{port}"
    logger.info("Desktop launch selected %s", url)
    data_dir.mkdir(parents=True, exist_ok=True)

    def write_runtime(status: str):
        runtime_path.write_text(
            json.dumps({
                "url": url,
                "port": port,
                "pid": os.getpid(),
                "status": status,
            }),
            encoding="utf-8",
        )

    write_runtime("starting")

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None
    )
    server = uvicorn.Server(config)
    window_holder = {"window": None}

    def shutdown():
        server.should_exit = True
        window = window_holder.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:
                logger.exception("Failed to close native window")

    app.state.shutdown_callback = shutdown
    server_errors = []

    def serve():
        try:
            server.run()
        except BaseException as exc:
            server_errors.append(exc)
            logger.exception("Embedded API server crashed")

    thread = threading.Thread(target=serve, name="touhou-api", daemon=True)
    thread.start()
    startup_timeout = _startup_timeout()
    if not _wait_for_server(host, port, startup_timeout, thread):
        server.should_exit = True
        thread.join(timeout=3)
        try:
            runtime_path.unlink()
        except OSError:
            pass
        ctypes.windll.kernel32.CloseHandle(mutex)
        if server_errors:
            detail = f"：{server_errors[0]}"
            raise RuntimeError(f"本地游戏服务启动失败{detail}")
        if not thread.is_alive():
            raise RuntimeError(
                f"本地游戏服务线程提前结束；诊断日志位于 {data_dir / 'logs' / 'touhou.log'}"
            )
        raise RuntimeError(
            f"本地游戏服务在 {int(startup_timeout)} 秒内未就绪，请稍后重试；"
            f"诊断日志位于 {data_dir / 'logs' / 'touhou.log'}"
        )
    logger.info("Embedded API server is healthy")
    write_runtime("ready")

    def cleanup():
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        try:
            runtime_path.unlink()
        except OSError:
            pass
        ctypes.windll.kernel32.CloseHandle(mutex)

    if os.environ.get("TOUHOU_SMOKE_TEST", "").lower() in ("1", "true", "yes"):
        smoke_seconds = max(1.0, float(os.environ.get("TOUHOU_SMOKE_SECONDS", "20")))
        deadline = time.time() + smoke_seconds
        while time.time() < deadline and thread.is_alive() and not server.should_exit:
            time.sleep(0.1)
        cleanup()
        return

    try:
        import webview
    except ImportError:
        logger.info("pywebview unavailable; falling back to the default browser")
        try:
            webbrowser.open(url)
            thread.join()
        finally:
            cleanup()
        return

    window = webview.create_window(
        "东方异变录",
        url=url,
        width=1440,
        height=900,
        min_size=(960, 640),
        confirm_close=False
    )
    window_holder["window"] = window
    logger.info("Opening native WebView window")
    try:
        try:
            webview.start(private_mode=False)
        except Exception:
            logger.exception("Native WebView failed; falling back to the default browser")
            window_holder["window"] = None
            webbrowser.open(url)
            thread.join()
    finally:
        cleanup()
