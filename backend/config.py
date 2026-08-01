# backend/config.py

import os
import sys
import shutil
from pathlib import Path
from dotenv import dotenv_values, load_dotenv
from backend.utils.secret_store import load_secret, save_secret

# ========== 路径配置 ==========
# 注意：PyInstaller单文件模式会提取datas到sys._MEIPASS
# 静态资源从 sys._MEIPASS 读取，用户数据必须保存在 exe 所在持久化目录
IS_FROZEN = getattr(sys, 'frozen', False)
EXECUTABLE_DIR = Path(sys.executable).parent if IS_FROZEN else Path(__file__).parent.parent
PORTABLE_MODE = os.environ.get("TOUHOU_PORTABLE", "").lower() in ("1", "true", "yes") or (EXECUTABLE_DIR / "portable.flag").exists()
DATA_DIR_OVERRIDE = os.environ.get("TOUHOU_DATA_DIR", "").strip()

if DATA_DIR_OVERRIDE:
    BASE_DIR = Path(sys._MEIPASS) if IS_FROZEN and hasattr(sys, '_MEIPASS') else Path(__file__).parent.parent
    DATA_DIR = Path(DATA_DIR_OVERRIDE).expanduser().resolve()
elif IS_FROZEN:
    # 单文件模式
    if hasattr(sys, '_MEIPASS'):
        # 静态资源基目录（临时提取目录）
        BASE_DIR = Path(sys._MEIPASS)
        local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        DATA_DIR = EXECUTABLE_DIR if PORTABLE_MODE else local_app_data / "TouHou"
    else:
        BASE_DIR = Path(sys.executable).parent
        DATA_DIR = EXECUTABLE_DIR if PORTABLE_MODE else Path(os.environ.get("LOCALAPPDATA", EXECUTABLE_DIR)) / "TouHou"
else:
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR


def migrate_legacy_runtime_data(legacy_dir: Path, data_dir: Path, bundled_worlds: Path = None) -> bool:
    """Idempotently migrate old portable data without overwriting a new profile."""
    if legacy_dir.resolve() == data_dir.resolve():
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    marker = data_dir / ".migration_v1_complete"
    if marker.exists():
        return False
    legacy_worlds = legacy_dir / "worlds"
    if legacy_worlds.exists() and not (data_dir / "worlds").exists():
        shutil.copytree(legacy_worlds, data_dir / "worlds")
    elif bundled_worlds and bundled_worlds.exists() and not (data_dir / "worlds").exists():
        shutil.copytree(bundled_worlds, data_dir / "worlds")
    legacy_env = legacy_dir / ".env"
    if legacy_env.exists() and not (data_dir / ".env").exists():
        shutil.copy2(legacy_env, data_dir / ".env")
    marker.write_text("migrated", encoding="ascii")
    return True


if IS_FROZEN and not PORTABLE_MODE:
    migrate_legacy_runtime_data(EXECUTABLE_DIR, DATA_DIR, BASE_DIR / "worlds")

print(f"BASE_DIR: {BASE_DIR}")
print(f"DATA_DIR: {DATA_DIR}")

WORLDS_DIR = DATA_DIR / "worlds"
PROMPTS_DIR = BASE_DIR / "prompts"
ENV_PATH = DATA_DIR / ".env"
SECRET_PATH = DATA_DIR / "config" / "api_key.dat"

load_dotenv(ENV_PATH, override=True, encoding="utf-8-sig")
_ENV_VALUES = dotenv_values(ENV_PATH, encoding="utf-8-sig") if ENV_PATH.exists() else {}


def _get_setting(name: str, default: str = "") -> str:
    """Non-empty local config wins; blank placeholders fall back to OS variables."""
    if name in _ENV_VALUES and _ENV_VALUES.get(name):
        return _ENV_VALUES.get(name) or ""
    return os.environ.get(name, default)

# ========== AI 配置（完全从环境变量读取）==========
DEEPSEEK_API_KEY = load_secret(SECRET_PATH) or _get_setting("DEEPSEEK_API_KEY", "")
if IS_FROZEN and DEEPSEEK_API_KEY and not SECRET_PATH.exists():
    try:
        save_secret(SECRET_PATH, DEEPSEEK_API_KEY)
        if ENV_PATH.exists():
            safe_lines = [line for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if not line.startswith("DEEPSEEK_API_KEY=")]
            safe_lines.insert(0, "DEEPSEEK_API_KEY=")
            ENV_PATH.write_text("\n".join(safe_lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"⚠️ API Key 安全迁移失败，将继续使用当前配置: {exc}")
if not DEEPSEEK_API_KEY:
    print("⚠️ 警告: .env 中未设置 DEEPSEEK_API_KEY，AI 功能将不可用，请在前端设置 API Key")

DEEPSEEK_BASE_URL = _get_setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _get_setting("DEEPSEEK_MODEL", "deepseek-v4-flash")

# AI 默认参数
DEFAULT_TEMPERATURE = float(_get_setting("DEFAULT_TEMPERATURE", "0.3"))
DEFAULT_TEMPERATURE_HIGH = float(_get_setting("DEFAULT_TEMPERATURE_HIGH", "0.8"))

# 调试模式
DEBUG = _get_setting("DEBUG", "False").lower() == "true"
PRIVATE_DEBUG = _get_setting("PRIVATE_DEBUG", "False").lower() == "true"

# ========== 应用配置 ==========
APP_HOST = _get_setting("APP_HOST", "127.0.0.1")
APP_PORT = int(_get_setting("APP_PORT", "8000"))
APP_DEBUG = _get_setting("APP_DEBUG", "False").lower() == "true"

# ========== 默认世界 ==========
DEFAULT_WORLD_ID = "world_touhou"

# ========== 辅助函数 ==========
def ensure_directories():
    """确保所有必要目录存在"""
    WORLDS_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 确保默认世界目录存在
    default_world_path = WORLDS_DIR / DEFAULT_WORLD_ID
    default_world_path.mkdir(parents=True, exist_ok=True)
    (default_world_path / "locations").mkdir(exist_ok=True)
    (default_world_path / "npcs").mkdir(exist_ok=True)
    (default_world_path / "sessions" / "characters").mkdir(parents=True, exist_ok=True)
