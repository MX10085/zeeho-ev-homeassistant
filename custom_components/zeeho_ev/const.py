DOMAIN = "zeeho_ev"
API_URL = "https://tapi.zeehoev.com/v1.0/app/cfmotoserverapp/vehicleHomePage/"
MINE_BASE = "https://tapi.zeehoev.com/v1.0/mine/cfmotoservermine"
API_OK_CODE = "10000"

CONF_VIN = "vin"
CONF_TOKEN = "token"
CONF_PHONE = "phone"
CONF_CODE = "auth_code"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_BASIC_AUTH = "basic_auth"

# ---------------------------------------------------------------------------
# 极核 API 凭据（登录 Basic、签名 APP_ID/APP_SECRET，逆向自 App）
#
# ⚠️ 安全：真实凭据不写在此文件！统一存放在 <config>/secrets.yaml：
#     zeeho_basic_auth / zeeho_app_id / zeeho_app_secret
#   secrets.yaml 位于用户本机 config 目录（不在本仓库内），公开仓库不会泄露。
#   读取失败时对应变量为空串，运行时代码会回退到配置条目里的自定义值；
#   若两者皆无，则接口调用会因缺少凭据而失败（属预期行为）。
# ---------------------------------------------------------------------------

import os
from pathlib import Path

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None


def _read_secret(name):
    """从 <config>/secrets.yaml 读取密钥；找不到时返回空串。"""
    if _yaml is None:
        return ""
    candidates = []
    env_cfg = os.environ.get("HOMEASSISTANT_CONFIG")
    if env_cfg:
        candidates.append(Path(env_cfg) / "secrets.yaml")
    # 组件位于 <config>/custom_components/zeeho_ev/，向上两级即 config 目录
    candidates.append(Path(__file__).resolve().parents[2] / "secrets.yaml")
    candidates.append(Path("/config/secrets.yaml"))  # HAOS / 容器标准路径
    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = _yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get(name) is not None:
                return str(data[name])
        except Exception:
            continue
    return ""


BASIC_AUTH = _read_secret("zeeho_basic_auth")
APP_ID = _read_secret("zeeho_app_id")
APP_SECRET = _read_secret("zeeho_app_secret")
