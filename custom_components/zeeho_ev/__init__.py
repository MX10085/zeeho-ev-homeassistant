"""Zeeho（极核）电动车 Home Assistant 集成。"""
import asyncio
import hashlib
import logging
import math
import random
import string
import time
import urllib.parse
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_OK_CODE,
    API_URL,
    APP_ID,
    APP_SECRET,
    BASIC_AUTH,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_BASIC_AUTH,
    CONF_REFRESH_TOKEN,
    CONF_REFRESH_TOKEN_EXPIRES_AT,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    CONF_VIN,
    DOMAIN,
    MINE_BASE,
    REFRESH_PATH,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=1)
REFRESH_BEFORE_EXPIRY = 24 * 60 * 60
REFRESH_RETRY_INTERVAL = 6 * 60 * 60


def _get_nonce():
    """生成 nonce：16 位随机字符 + 毫秒时间戳。"""
    rand16 = "".join(
        random.choice(string.ascii_letters + string.digits) for _ in range(16)
    )
    return rand16 + str(int(time.time() * 1000))


def _build_headers(url, app_id=None, app_secret=None):
    """按 RequestSignInterceptor 逻辑生成签名 headers（GET 无 body）。

    凭据可从参数传入（优先取配置条目中的值），缺省时回退到 const 默认值。
    """
    app_id = app_id or APP_ID
    app_secret = app_secret or APP_SECRET
    nonce = _get_nonce()
    ts = str(int(time.time() * 1000))
    param_str = f"appId={app_id}&nonce={nonce}&timestamp={ts}"

    parsed = urllib.parse.urlsplit(url)
    # GET: preSign = scheme://host:port/encodedPath + (?sortedQuery) + param + secret
    pre_sign = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        pairs = sorted(
            urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        )
        enc = "&".join(
            f"{k}={urllib.parse.quote(v, safe='~')}" for k, v in pairs
        )
        pre_sign += "?" + enc
    pre_sign += param_str + app_secret

    signature = hashlib.md5(
        hashlib.sha1(pre_sign.encode("utf-8")).hexdigest().encode("utf-8")
    ).hexdigest()

    return {
        "appId": app_id,
        "nonce": nonce,
        "timestamp": ts,
        "signature": signature,
        "Cfmoto-X-Param": param_str,
        "Cfmoto-X-Sign": signature,
        "Cfmoto-X-Sign-Type": "0",
        "Content-Type": "application/json",
        "User-Agent": "okhttp/4.9.2",
    }

# 逆地理缓存：位置未明显变化时不重复请求
_last_reverse_geo = {"key": None, "result": None, "time": None}
# 国内可达的免费逆地理服务（Nominatim 在大陆网络不可达）
# photon（OpenStreetMap 数据，含街道/小区名）优先，bigdatacloud（省市县）兜底
GEO_URLS = [
    "https://photon.komoot.io/reverse",
    "https://api.bigdatacloud.net/data/reverse-geocode-client",
]


# ---------- GCJ-02（火星坐标）→ WGS-84 转换 ----------
# 极核 API 返回的 location 是 GCJ-02（高德坐标系），而 photon/OSM 用 WGS-84，
# 必须转换否则街道/小区级地址会偏移约 500 米。
_GCJ_PI = math.pi
_GCJ_A = 6378245.0
_GCJ_EE = 0.00669342162296594323


def _gcj_transform_lat(x, y):
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * _GCJ_PI)
        + 20.0 * math.sin(2.0 * x * _GCJ_PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(y * _GCJ_PI)
        + 40.0 * math.sin(y / 3.0 * _GCJ_PI)
    ) * 2.0 / 3.0
    ret += (
        160.0 * math.sin(y / 12.0 * _GCJ_PI)
        + 320.0 * math.sin(y * _GCJ_PI / 30.0)
    ) * 2.0 / 3.0
    return ret


def _gcj_transform_lng(x, y):
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (
        20.0 * math.sin(6.0 * x * _GCJ_PI)
        + 20.0 * math.sin(2.0 * x * _GCJ_PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(x * _GCJ_PI)
        + 40.0 * math.sin(x / 3.0 * _GCJ_PI)
    ) * 2.0 / 3.0
    ret += (
        150.0 * math.sin(x / 12.0 * _GCJ_PI)
        + 300.0 * math.sin(x / 30.0 * _GCJ_PI)
    ) * 2.0 / 3.0
    return ret


def _gcj_out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def gcj02_to_wgs84(lng, lat):
    """GCJ-02 → WGS-84。中国境外原样返回。"""
    if _gcj_out_of_china(lng, lat):
        return lng, lat
    dlat = _gcj_transform_lat(lng - 105.0, lat - 35.0)
    dlng = _gcj_transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _GCJ_PI
    magic = math.sin(radlat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrtmagic) * _GCJ_PI)
    dlng = (dlng * 180.0) / (_GCJ_A / sqrtmagic * math.cos(radlat) * _GCJ_PI)
    return lng - dlng, lat - dlat


async def _reverse_geocode(session, lat, lon):
    """经纬度 → 地址（photon 优先带街道/小区名，bigdatacloud 兜底）。失败返回 None。"""
    import time

    if lat is None or lon is None:
        return None
    key = f"{lat:.4f},{lon:.4f}"
    now = time.time()
    cached = _last_reverse_geo
    if cached["key"] == key and cached["result"] and (now - cached["time"]) < 900:
        return cached["result"]

    for geo_url in GEO_URLS:
        try:
            if "photon" in geo_url:
                params = {"lat": str(lat), "lon": str(lon), "limit": 1}
                timeout = aiohttp.ClientTimeout(total=8)
            else:
                params = {
                    "latitude": str(lat),
                    "longitude": str(lon),
                    "localityLanguage": "zh",
                }
                timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(geo_url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    continue
                j = await resp.json()
                if "photon" in geo_url:
                    # photon: properties 里有 name(小区/街道)/district/city/state/country
                    feat = (j.get("features") or [{}])[0].get("properties", {})
                    # 只要街道 + 小区/地名（去掉国家/省/市前缀）
                    parts = [
                        feat.get("district"),
                        feat.get("name"),
                    ]
                else:
                    # bigdatacloud: countryName/principalSubdivision/city/locality
                    parts = [
                        j.get("countryName"),
                        j.get("principalSubdivision"),
                        j.get("city"),
                        j.get("locality"),
                    ]
                result = " ".join(p for p in parts if p)
                if result:
                    cached.update(key=key, result=result, time=now)
                    return result
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("逆地理失败(%s): %s", geo_url, err)
            continue
    return None


async def async_setup(hass: HomeAssistant, config: dict):
    """初始化 zeeho 组件。"""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """根据配置条目设置 zeeho。"""
    session = aiohttp.ClientSession()
    token_state = {
        "access_token": entry.data[CONF_TOKEN],
        "refresh_token": entry.data.get(CONF_REFRESH_TOKEN),
        "expires_at": entry.data.get(CONF_TOKEN_EXPIRES_AT) or 0,
        "next_attempt": 0,
    }
    refresh_lock = asyncio.Lock()
    vin = entry.data[CONF_VIN]
    url = f"{API_URL}{vin}"
    # 凭据优先取配置条目（防公开仓库泄露），缺省回退到 const 默认值
    app_id = entry.data.get(CONF_APP_ID) or APP_ID
    app_secret = entry.data.get(CONF_APP_SECRET) or APP_SECRET
    basic_auth = entry.data.get(CONF_BASIC_AUTH) or BASIC_AUTH

    async def _refresh_access_token():
        """用 refresh token 换取并持久化新 token。失败时保留旧 token。"""
        refresh_token = token_state.get("refresh_token")
        now = time.time()
        if not refresh_token:
            return False
        if now < token_state["next_attempt"]:
            return False

        async with refresh_lock:
            now = time.time()
            if now < token_state["next_attempt"]:
                return False
            token_state["next_attempt"] = now + REFRESH_RETRY_INTERVAL
            refresh_url = MINE_BASE + REFRESH_PATH
            headers = _build_headers(refresh_url, app_id, app_secret)
            headers["Authorization"] = basic_auth
            try:
                async with session.post(
                    refresh_url,
                    json={"refreshToken": refresh_token},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("极核令牌刷新失败：HTTP %s", resp.status)
                        return False
                    body = await resp.json()
            except (aiohttp.ClientError, ValueError, TypeError) as err:
                _LOGGER.warning("极核令牌刷新失败：%s", type(err).__name__)
                return False

            if body.get("code") != API_OK_CODE:
                _LOGGER.warning(
                    "极核令牌刷新失败：code=%s message=%s",
                    body.get("code"),
                    body.get("message", "未知"),
                )
                return False

            result = body.get("data") or {}
            token_info = result.get("tokenInfo") or result
            access_token = token_info.get("access_token")
            if not access_token:
                _LOGGER.warning("极核令牌刷新响应缺少 access_token")
                return False

            expires_in = int(token_info.get("expires_in") or 863999)
            new_refresh_token = token_info.get("refresh_token") or refresh_token
            expires_at = int(time.time()) + expires_in
            new_data = dict(entry.data)
            new_data[CONF_TOKEN] = access_token
            new_data[CONF_REFRESH_TOKEN] = new_refresh_token
            new_data[CONF_TOKEN_EXPIRES_AT] = expires_at
            refresh_expires_in = (
                token_info.get("refresh_expires_in")
                or token_info.get("refresh_token_expires_in")
            )
            if refresh_expires_in:
                new_data[CONF_REFRESH_TOKEN_EXPIRES_AT] = (
                    int(time.time()) + int(refresh_expires_in)
                )
            hass.config_entries.async_update_entry(entry, data=new_data)
            token_state.update(
                access_token=access_token,
                refresh_token=new_refresh_token,
                expires_at=expires_at,
                next_attempt=0,
            )
            hass.components.persistent_notification.async_dismiss(
                "zeeho_ev_relogin"
            )
            _LOGGER.info("极核访问令牌已自动续期")
            return True

    async def _notify_relogin():
        """发通知引导用户在选项里重新验证码登录。"""
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "极核登录已过期，请在选项里重新登录",
                "message": (
                    "极核 ZEEHO API 的登录已过期。请打开\n\n"
                    "「设置 → 设备与服务 → 极核 → 选项」\n\n"
                    "按提示输入手机号和收到的短信验证码，约 30 秒即可完成续期，无需删除集成。"
                ),
                "notification_id": "zeeho_ev_relogin",
            },
        )

    async def _check_token_expiry(_now=None):
        """每天检查 token 剩余有效期，快过期（≤2 天）时提醒。"""
        expires_at = entry.data.get(CONF_TOKEN_EXPIRES_AT) or 0
        if not expires_at:
            return
        remaining = expires_at - time.time()
        if remaining <= 2 * 86400:
            await _notify_relogin()

    async def async_update_data():
        """从极核 API 拉取车辆数据（vehicleHomePage 聚合接口）。"""
        expires_at = token_state.get("expires_at") or 0
        if expires_at and expires_at - time.time() <= REFRESH_BEFORE_EXPIRY:
            await _refresh_access_token()

        async def _request_vehicle_data():
            headers = _build_headers(url, app_id, app_secret)
            headers["Authorization"] = f"Bearer {token_state['access_token']}"
            headers["Accept"] = "*/*"
            return await session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            )

        try:
            async with await _request_vehicle_data() as resp:
                if resp.status in (401, 403):
                    refreshed = await _refresh_access_token()
                    if refreshed:
                        async with await _request_vehicle_data() as retry_resp:
                            if retry_resp.status == 200:
                                data = await retry_resp.json()
                            else:
                                await _notify_relogin()
                                raise UpdateFailed(
                                    f"令牌刷新后重试失败：HTTP {retry_resp.status}"
                                )
                    else:
                        await _notify_relogin()
                        raise UpdateFailed(
                            "认证失败：自动续期失败，请在「设备与服务 → 极核 → 选项」里重新登录"
                        )
                elif resp.status != 200:
                    raise UpdateFailed(f"API 请求失败：HTTP {resp.status}")
                else:
                    data = await resp.json()
        except aiohttp.ClientError as err:
            # 网络 / DNS / 连接超时等
            raise UpdateFailed(
                f"网络错误：无法连接 Zeeho API（{type(err).__name__}），请检查服务器网络与 DNS"
            ) from err
        except (ValueError, TypeError) as err:
            raise UpdateFailed(f"API 响应解析失败：{err}") from err

        if data.get("code") != API_OK_CODE:
            raise UpdateFailed(
                f"API 返回错误：code={data.get('code')}，message={data.get('message', '未知')}"
                "（token 可能失效，请重新配置）"
            )
        result = data.get("data", {})
        # 逆地理编码：解决地址"未知"（先把 GCJ-02 转 WGS-84，否则街道级偏移）
        loc = result.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is not None and lon is not None:
            wgs_lon, wgs_lat = gcj02_to_wgs84(lon, lat)
            addr = await _reverse_geocode(session, wgs_lat, wgs_lon)
            if addr:
                result["address"] = addr
        return result

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="zeeho coordinator",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator, "session": session}

    # 每天检查一次 token 剩余有效期，快过期时提醒
    from homeassistant.helpers.event import async_track_time_interval
    entry.async_on_unload(
        async_track_time_interval(hass, _check_token_expiry, timedelta(days=1))
    )
    await _check_token_expiry()

    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "device_tracker", "image"]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """卸载配置条目。"""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "device_tracker", "image"]
    )
    if unload_ok:
        session = hass.data[DOMAIN][entry.entry_id].get("session")
        if session is not None and not session.closed:
            await session.close()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
