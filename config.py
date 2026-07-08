"""信息精选系统 - 配置 (Linux + 共享 investment-monitor)"""
import os
from pathlib import Path

# === 路径 ===
PROJECT_DIR = Path(__file__).parent
# 共享 investment-monitor 的数据库.
#   - 嵌进容器 (default): /app/data/investment.db
#   - 主机独立部署: 通过 INFO_DIGEST_DB 环境变量指向同一份 db
#     (用 sshfs/nfs 把 /app/data/investment.db 挂到主机,或拷一份到主机)
_DEFAULT_DB = Path("/app/data/investment.db")
DB_PATH = Path(os.environ.get("INFO_DIGEST_DB", str(_DEFAULT_DB)))

# === 飞书 ===
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "")
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

# === AI ===
# Linux 路径: ~/.hermes/.env (兼容 Windows AppData/Local/hermes)
# 容器嵌入时也可通过 INFO_DIGEST_ENV 指向其它位置 (例如 /app/.env)
_hermes_env_candidates = []
_info_digest_env = os.environ.get("INFO_DIGEST_ENV", "").strip()
if _info_digest_env:
    _hermes_env_candidates.append(Path(_info_digest_env))
_hermes_env_candidates += [
    Path("/home/ubuntu/.hermes/.env"),
    Path.home() / ".hermes" / ".env",
    Path("/app/.env"),  # 容器内兜底
    Path.home() / "AppData" / "Local" / "hermes" / ".env",  # 兼容 Win
]
HERMES_ENV = next((p for p in _hermes_env_candidates if p.exists()), _hermes_env_candidates[0])

# 默认走 investment-monitor 已在用的 MiniMax CN 端点;找不到 key 时退回 MiMo 公共端点
XIAOMI_API_BASE = "https://api.minimaxi.com/v1"
XIAOMI_MODEL = "MiniMax-Text-01"

# 本地 self-hosted RSSHub (跟 investment-monitor 同主机,经 docker host gateway)
RSSHUB_BASE = "http://host.docker.internal:1200"

# === Digest ===
DIGEST_MAX_ITEMS = 8
QUALITY_THRESHOLD = 5.0
DEDUP_WINDOW_HOURS = 48

# === 采集 ===
FETCH_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InfoDigest/1.0"


def _read_env_var(name):
    """优先从 os.environ 读 (容器内 docker run -e 已注入),fallback 到 .env 文件"""
    val = os.environ.get(name)
    if val and val.strip() and val.strip() != "***":
        return val.strip()
    # 容器外 (主机独立部署) 才走 .env 文件
    if HERMES_ENV.exists():
        try:
            for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip() == name and val.strip() and val.strip() != "***":
                    return val.strip()
        except Exception:
            pass
    return ""


def get_feishu_app_id():
    """app_id 也走 .env 兜底"""
    return _read_env_var("FEISHU_APP_ID") or FEISHU_APP_ID


def get_feishu_secret():
    return _read_env_var("FEISHU_APP_SECRET")


def get_feishu_chat_id():
    """chat_id 优先 FEISHU_CHAT_ID, fallback FEISHU_HOME_CHANNEL"""
    for env_name in ("FEISHU_CHAT_ID", "FEISHU_HOME_CHANNEL"):
        v = _read_env_var(env_name)
        if v:
            return v
    return FEISHU_CHAT_ID


def get_xiaomi_api_key():
    """优先用 investment-monitor 同款 MiniMax_CN_API_KEY,退回 MiMo/其它"""
    for env_name in ("MINIMAX_CN_API_KEY", "MINIMAX_API_KEY", "XIAOMI_API_KEY"):
        key = _read_env_var(env_name)
        if key and len(key) >= 20:
            return key
    return ""
