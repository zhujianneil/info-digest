"""信息精选系统 - 配置"""
import os
from pathlib import Path

# === 路径 ===
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "digest.db"

# === 飞书 ===
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "")
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

# === AI ===
HERMES_ENV = Path.home() / "AppData" / "Local" / "hermes" / ".env"
XIAOMI_API_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
XIAOMI_MODEL = "mimo-v2.5-pro"

# === Digest ===
DIGEST_MAX_ITEMS = 8
QUALITY_THRESHOLD = 5.0
DEDUP_WINDOW_HOURS = 48

# === 采集 ===
FETCH_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InfoDigest/1.0"


def _read_env_var(name):
    """从 hermes .env 读取环境变量"""
    if os.environ.get(name):
        return os.environ[name]
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == name and val.strip() and val.strip() != "***":
                return val.strip()
    return ""


def get_feishu_secret():
    return _read_env_var("FEISHU_APP_SECRET")


def get_xiaomi_api_key():
    # XIAOMI_API_KEY 用于 token-plan-cn.xiaomimimo.com
    key = _read_env_var("XIAOMI_API_KEY")
    if not key or len(key) < 20:
        key = _read_env_var("MINIMAX_API_KEY")
    return key
