"""Zeeho（极核）车辆图片实体：从 vehiclePicUrl 下载并显示。"""
import asyncio
import logging
from datetime import timedelta

import aiohttp

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=6)


class ZeehoImage(CoordinatorEntity, ImageEntity):
    """显示极核车辆图片。"""

    def __init__(self, coordinator, vin, vehicle_name):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_image"
        self._attr_name = f"Zeeho {vehicle_name} 图片"
        self._attr_icon = "mdi:car"
        self._session = aiohttp.ClientSession()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._vin)},
            "name": "ZEEHO",
            "manufacturer": "ZEEHO",
            "model": self.coordinator.data.get("vehicleName", "Unknown"),
            "configuration_url": "https://github.com/MX10085/zeeho-ev-homeassistant",
        }

    async def async_image(self):
        """返回车辆图片 bytes。"""
        url = self.coordinator.data.get("vehiclePicUrl")
        if not url:
            return None
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("下载车辆图片失败: %s", err)
        return None

    async def async_will_remove_from_hass(self):
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_will_remove_from_hass()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    vin = entry.data["vin"]
    vehicle_name = entry.data.get("vehicle_name", vin)
    async_add_entities([ZeehoImage(coordinator, vin, vehicle_name)], True)
