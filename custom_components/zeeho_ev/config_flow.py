"""Zeeho（极核）集成配置流程：手机号 + 短信验证码登录。"""
import base64
import logging

import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    API_OK_CODE,
    API_URL,
    BASIC_AUTH,
    CONF_CODE,
    CONF_PHONE,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    CONF_VIN,
    DOMAIN,
    MINE_BASE,
)
from . import _build_headers

_LOGGER = logging.getLogger(__name__)

AUTH_CODE_PATH = "/authCode/"
LOGIN_PATH = "/user/loginByPhone"


def _send_code(phone):
    """发送短信验证码。返回 (ok, message)。"""
    url = MINE_BASE + AUTH_CODE_PATH + phone
    try:
        resp = requests.get(url, headers=_build_headers(url), timeout=15)
    except requests.RequestException as err:
        _LOGGER.error("Zeeho 发送验证码失败：%s", err)
        return False, "cannot_connect"
    if resp.status_code != 200:
        return False, "cannot_connect"
    body = resp.json()
    if body.get("code") != API_OK_CODE:
        _LOGGER.error("Zeeho 发送验证码失败：code=%s msg=%s", body.get("code"), body.get("message"))
        return False, "send_failed"
    return True, ""


def _login_by_code(phone, code):
    """验证码登录。返回 (token_info, vin, err)。
    token_info 含 access_token / refresh_token / expires_in；err 为错误 key 或 ""。
    """
    url = MINE_BASE + LOGIN_PATH
    payload = {"phone": phone, "authCode": code}
    headers = _build_headers(url)
    headers["Authorization"] = BASIC_AUTH
    try:
        resp = requests.post(
            url, json=payload, headers=headers, timeout=20
        )
    except requests.RequestException as err:
        _LOGGER.error("Zeeho 验证码登录失败：%s", err)
        return None, None, "cannot_connect"

    if resp.status_code in (401, 403):
        return None, None, "auth"
    if resp.status_code != 200:
        return None, None, "cannot_connect"

    try:
        body = resp.json()
    except ValueError:
        return None, None, "cannot_connect"

    if body.get("code") != API_OK_CODE:
        _LOGGER.error("Zeeho 验证码登录业务失败：code=%s msg=%s", body.get("code"), body.get("message"))
        return None, None, "invalid_code"

    data = body.get("data", {})
    token_info = data.get("tokenInfo", {}) or {}
    access_token = token_info.get("access_token")
    if not access_token:
        return None, None, "invalid_code"

    # 通过 vehicleHomePage 自动获取 VIN（登录后第一个可访问的车辆）
    vin = _fetch_vin(access_token)
    return token_info, vin, ""


def _fetch_vin(token):
    """用 token 查询车辆列表，返回第一个 VIN（接口返回的是列表，字段名 vinNo）。"""
    url = API_URL
    try:
        resp = requests.get(
            url,
            headers={
                **_build_headers(url),
                "Authorization": f"Bearer {token}",
                "Accept": "*/*",
            },
            timeout=15,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if body.get("code") != API_OK_CODE:
        return None
    data = body.get("data") or []
    # 接口返回车辆列表
    if isinstance(data, list):
        if data and data[0].get("vinNo"):
            return data[0]["vinNo"]
        return None
    # 兼容 dict 形式
    if isinstance(data, dict):
        for key in ("vinNo", "vin", "vehicle"):
            item = data.get(key)
            if isinstance(item, dict) and item.get("vinNo"):
                return item["vinNo"]
            if isinstance(item, dict) and item.get("vin"):
                return item["vin"]
        return data.get("vinNo") or data.get("vin")
    return None


class ZeehoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Zeeho 配置流程：两步验证码登录。"""

    VERSION = 1

    def __init__(self):
        self._phone = None

    async def async_step_user(self, user_input=None):
        """第一步：输入手机号并发送验证码。"""
        errors = {}
        if user_input is not None:
            phone = (user_input.get(CONF_PHONE) or "").strip()
            if not phone or len(phone) != 11:
                errors[CONF_PHONE] = "invalid_phone"
            else:
                ok, err = await self.hass.async_add_executor_job(_send_code, phone)
                if not ok:
                    errors["base"] = err
                else:
                    self._phone = phone
                    return await self.async_step_code()

        schema = vol.Schema({vol.Required(CONF_PHONE): str})
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors,
            description_placeholders={},
        )

    async def async_step_code(self, user_input=None):
        """第二步：输入验证码并完成登录。"""
        errors = {}
        if user_input is not None:
            code = (user_input.get(CONF_CODE) or "").strip()
            if not code:
                errors[CONF_CODE] = "invalid_code"
            else:
                token_info, vin, err = await self.hass.async_add_executor_job(
                    _login_by_code, self._phone, code
                )
                if err:
                    errors["base"] = err
                elif not vin:
                    errors["base"] = "no_vehicle"
                else:
                    await self.async_set_unique_id(vin)
                    self._abort_if_unique_id_configured()
                    expires_in = int(token_info.get("expires_in") or 863999)
                    import time
                    return self.async_create_entry(
                        title=f"ZEEHO EV {vin}",
                        data={
                            CONF_TOKEN: token_info["access_token"],
                            CONF_VIN: vin,
                            CONF_PHONE: self._phone,
                            CONF_TOKEN_EXPIRES_AT: int(time.time()) + expires_in,
                        },
                    )

        schema = vol.Schema({vol.Required(CONF_CODE): str})
        return self.async_show_form(
            step_id="code", data_schema=schema, errors=errors,
            description_placeholders={"phone": self._phone or ""},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ZeehoOptionsFlow(config_entry)


class ZeehoOptionsFlow(config_entries.OptionsFlow):
    """选项流程：token 过期时重新验证码登录。"""

    def __init__(self, config_entry):
        # 注意：新版 HA 的 OptionsFlow.config_entry 是只读 property（运行时从
        # hass.config_entries 动态获取），不能在 __init__ 里赋值；构造参数
        # config_entry 作为局部变量仍可用来读取初始数据。
        self._phone = (config_entry.data.get(CONF_PHONE) or "").strip()

    async def async_step_init(self, user_input=None):
        """第一步：确认手机号并发送验证码。"""
        errors = {}
        if user_input is not None:
            phone = (user_input.get(CONF_PHONE) or "").strip()
            if not phone or len(phone) != 11:
                errors[CONF_PHONE] = "invalid_phone"
            else:
                ok, err = await self.hass.async_add_executor_job(_send_code, phone)
                if not ok:
                    errors["base"] = err
                else:
                    self._phone = phone
                    return await self.async_step_code()

        schema = vol.Schema({vol.Required(CONF_PHONE, default=self._phone or ""): str})
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_code(self, user_input=None):
        """第二步：输入验证码并更新 token。"""
        errors = {}
        if user_input is not None:
            code = (user_input.get(CONF_CODE) or "").strip()
            if not code:
                errors[CONF_CODE] = "invalid_code"
            else:
                token_info, vin, err = await self.hass.async_add_executor_job(
                    _login_by_code, self._phone, code
                )
                if err:
                    errors["base"] = err
                else:
                    import time
                    expires_in = int(token_info.get("expires_in") or 863999)
                    data = dict(self.config_entry.data)
                    data[CONF_TOKEN] = token_info["access_token"]
                    data[CONF_PHONE] = self._phone
                    data[CONF_TOKEN_EXPIRES_AT] = int(time.time()) + expires_in
                    # 更新 config entry 并强制重载，让新 token 生效
                    self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                    return self.async_create_entry(title="", data={})

        schema = vol.Schema({vol.Required(CONF_CODE): str})
        return self.async_show_form(
            step_id="code", data_schema=schema, errors=errors,
            description_placeholders={"phone": self._phone or ""},
        )
