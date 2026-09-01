"""Desktop lifecycle for the frozen application."""

import ctypes
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn


logger = logging.getLogger(__name__)
ERROR_ALREADY_EXISTS = 183
DEFAULT_STARTUP_TIMEOUT = 60.0
DEFAULT_WATCHDOG_INTERVAL = 30.0
DEFAULT_WATCHDOG_TIMEOUT = 3.0
DEFAULT_WATCHDOG_FAILURES = 3


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _write_startup_diagnostic(data_dir: Path, phase: str, status: str, **details) -> dict:
    path = Path(data_dir) / "logs" / "startup-diagnostics.json"
    payload = {
        "product": "TouHou",
        "pid": os.getpid(),
        "phase": phase,
        "status": status,
        "updated_at": datetime.now().isoformat(),
        **details,
    }
    _write_json_atomic(path, payload)
    return payload


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


def _runtime_watchdog_config() -> tuple[float, float, int]:
    def number(name: str, default: float, low: float, high: float) -> float:
        try:
            value = float(os.environ.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    interval = number("TOUHOU_WATCHDOG_INTERVAL", DEFAULT_WATCHDOG_INTERVAL, 5.0, 300.0)
    timeout = number("TOUHOU_WATCHDOG_TIMEOUT", DEFAULT_WATCHDOG_TIMEOUT, 0.5, 15.0)
    failures = int(number("TOUHOU_WATCHDOG_FAILURES", DEFAULT_WATCHDOG_FAILURES, 1, 10))
    return interval, timeout, failures


def _probe_runtime_health(url: str, timeout: float = DEFAULT_WATCHDOG_TIMEOUT) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _watch_runtime_health(
    stop_event: threading.Event,
    server_thread,
    url: str,
    on_failure,
    *,
    interval: float,
    timeout: float,
    failure_limit: int,
    probe=_probe_runtime_health,
) -> None:
    consecutive_failures = 0
    while not stop_event.wait(interval):
        if not server_thread.is_alive():
            on_failure("server_thread_exited", consecutive_failures + 1)
            return
        if probe(url, timeout):
            consecutive_failures = 0
            continue
        consecutive_failures += 1
        logger.warning("Runtime health probe failed (%s/%s)", consecutive_failures, failure_limit)
        if consecutive_failures >= failure_limit:
            on_failure("health_probe_timeout", consecutive_failures)
            return


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
    data_dir.mkdir(parents=True, exist_ok=True)
    probe_path = data_dir / ".touhou-write-probe"
    probe_path.write_text("ok", encoding="ascii")
    probe_path.unlink()
    _write_startup_diagnostic(data_dir, "preflight", "ok", data_path=str(data_dir))
    port = _available_port(host, preferred_port)
    url = f"http://{host}:{port}"
    logger.info("Desktop launch selected %s", url)
    started_at = datetime.now().isoformat()

    def write_runtime(status: str, phase: str, **details):
        _write_json_atomic(
            runtime_path,
            {
                "url": url,
                "port": port,
                "pid": os.getpid(),
                "status": status,
                "phase": phase,
                "started_at": started_at,
                "updated_at": datetime.now().isoformat(),
                **details,
            },
        )

    write_runtime("starting", "server_config")
    _write_startup_diagnostic(data_dir, "server_config", "ok", url=url)

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
    watchdog_stop = threading.Event()
    runtime_failure = threading.Event()
    watchdog_thread = None

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
    write_runtime("starting", "health_wait", timeout_seconds=startup_timeout)
    _write_startup_diagnostic(data_dir, "health_wait", "running", url=url, timeout_seconds=startup_timeout)
    if not _wait_for_server(host, port, startup_timeout, thread):
        server.should_exit = True
        thread.join(timeout=3)
        reason = "server_error" if server_errors else "thread_exited" if not thread.is_alive() else "timeout"
        detail = str(server_errors[0])[:500] if server_errors else ""
        write_runtime("failed", "health_wait", reason=reason, detail=detail)
        _write_startup_diagnostic(
            data_dir,
            "health_wait",
            "failed",
            reason=reason,
            detail=detail,
            log_file=str(data_dir / "logs" / "touhou.log"),
        )
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
    write_runtime("ready", "ready")
    _write_startup_diagnostic(data_dir, "ready", "ok", url=url)

    def runtime_failed(reason: str, failure_count: int):
        runtime_failure.set()
        server.should_exit = True
        write_runtime("failed", "runtime_watchdog", reason=reason, failure_count=failure_count)
        _write_startup_diagnostic(
            data_dir,
            "runtime_watchdog",
            "failed",
            reason=reason,
            failure_count=failure_count,
            log_file=str(data_dir / "logs" / "touhou.log"),
        )
        window = window_holder.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:
                logger.exception("Failed to close an unresponsive native window")
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"本地游戏服务已失去响应。请重新启动游戏。\n诊断日志：{data_dir / 'logs' / 'touhou.log'}",
                "东方异变录",
                0x10,
            )
        except Exception:
            logger.exception("Failed to show runtime watchdog warning")

    if os.environ.get("TOUHOU_DISABLE_WATCHDOG", "").lower() not in ("1", "true", "yes"):
        interval, health_timeout, failure_limit = _runtime_watchdog_config()
        watchdog_thread = threading.Thread(
            target=_watch_runtime_health,
            args=(watchdog_stop, thread, url, runtime_failed),
            kwargs={"interval": interval, "timeout": health_timeout, "failure_limit": failure_limit},
            name="touhou-watchdog",
            daemon=True,
        )
        watchdog_thread.start()

    def cleanup():
        watchdog_stop.set()
        if watchdog_thread is not None and watchdog_thread.is_alive():
            watchdog_thread.join(timeout=2)
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        try:
            runtime_path.unlink()
        except OSError:
            pass
        _write_startup_diagnostic(data_dir, "shutdown", "ok")
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
            while thread.is_alive() and not runtime_failure.wait(0.5):
                pass
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
    write_runtime("ready", "window")
    _write_startup_diagnostic(data_dir, "window", "running", url=url)
    try:
        try:
            webview.start(private_mode=False)
        except Exception:
            logger.exception("Native WebView failed; falling back to the default browser")
            window_holder["window"] = None
            webbrowser.open(url)
            while thread.is_alive() and not runtime_failure.wait(0.5):
                pass
    finally:
        cleanup()
