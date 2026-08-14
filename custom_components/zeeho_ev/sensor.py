"""Zeeho（极核）传感器：电量、续航、总里程、车锁、地址、胎压、充电、OTA、信号。"""
import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfPressure, UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_info(coordinator, vin):
    # 所有 zeeho 实体归属同一设备
    return {
        "identifiers": {(DOMAIN, vin)},
        "name": "ZEEHO",
        "manufacturer": "ZEEHO",
        "model": coordinator.data.get("vehicleName", "Unknown"),
        "configuration_url": "https://github.com/MX10085/zeeho-ev-homeassistant",
    }


def _to_number(value):
    """将 API 返回的字符串数值安全转换为 float，失败返回 None。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    vin = entry.data["vin"]
    vehicle_name = entry.data.get("vehicle_name", vin)

    entities = [
        ZeehoBatterySensor(coordinator, vin, vehicle_name),
        ZeehoRangeSensor(coordinator, vin, vehicle_name),
        ZeehoMileageSensor(coordinator, vin, vehicle_name),
        ZeehoLockSensor(coordinator, vin, vehicle_name),
        ZeehoAddressSensor(coordinator, vin, vehicle_name),
        ZeehoTirePressureSensor(coordinator, vin, vehicle_name),
        ZeehoChargeSensor(coordinator, vin, vehicle_name),
        ZeehoOtaSensor(coordinator, vin, vehicle_name),
        ZeehoStatusSensor(coordinator, vin, vehicle_name),
        ZeehoSignalSensor(coordinator, vin, vehicle_name),
    ]
    async_add_entities(entities, True)


class ZeehoBatterySensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_battery"
        self._attr_name = f"Zeeho {vehicle_name} 电量"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_icon = "mdi:battery"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return _to_number(self.coordinator.data.get("bmssoc"))


class ZeehoRangeSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_range"
        self._attr_name = f"Zeeho {vehicle_name} 续航"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_icon = "mdi:map-marker-distance"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return _to_number(self.coordinator.data.get("hmiRidableMile"))


class ZeehoMileageSensor(CoordinatorEntity, SensorEntity):
    """总里程（totalRideMile）。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_mileage"
        self._attr_name = f"Zeeho {vehicle_name} 总里程"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_icon = "mdi:counter"
        self._attr_state_class = "total_increasing"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return _to_number(self.coordinator.data.get("totalRideMile"))


class ZeehoLockSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_lock"
        self._attr_name = f"Zeeho {vehicle_name} 车锁"
        self._attr_icon = "mdi:lock"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        state = self.coordinator.data.get("headLockState")
        if state == "1":
            return "已锁"
        if state == "0":
            return "未锁"
        return "未知"


class ZeehoAddressSensor(CoordinatorEntity, SensorEntity):
    """地址（逆地理编码，原集成地址为未知）。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_address"
        self._attr_name = f"Zeeho {vehicle_name} 地址"
        self._attr_icon = "mdi:map-marker"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return self.coordinator.data.get("address") or "未知"

    @property
    def extra_state_attributes(self):
        loc = self.coordinator.data.get("location") or {}
        return {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "location_time": loc.get("locationTime"),
        }


class ZeehoTirePressureSensor(CoordinatorEntity, SensorEntity):
    """胎压（pressure）。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_pressure"
        self._attr_name = f"Zeeho {vehicle_name} 胎压"
        self._attr_native_unit_of_measurement = "bar"
        self._attr_device_class = SensorDeviceClass.PRESSURE
        self._attr_icon = "mdi:gauge"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        v = _to_number(self.coordinator.data.get("pressure"))
        return v if v is not None and v > 0 else None

    @property
    def extra_state_attributes(self):
        return {"pressure_state": self.coordinator.data.get("pressureValue")}


class ZeehoChargeSensor(CoordinatorEntity, SensorEntity):
    """充电状态（chargeState）。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_charge"
        self._attr_name = f"Zeeho {vehicle_name} 充电状态"
        self._attr_icon = "mdi:power-plug"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        state = self.coordinator.data.get("chargeState")
        if state == "1":
            return "充电中"
        if state == "0":
            return "未充电"
        return "未知"


class ZeehoOtaSensor(CoordinatorEntity, SensorEntity):
    """OTA 软件版本。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_ota"
        self._attr_name = f"Zeeho {vehicle_name} 固件版本"
        self._attr_icon = "mdi:update"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return self.coordinator.data.get("otaVersion") or "未知"


class ZeehoStatusSensor(CoordinatorEntity, SensorEntity):
    """车辆在线状态。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_status"
        self._attr_name = f"Zeeho {vehicle_name} 状态"
        self._attr_icon = "mdi:car-connected"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return self.coordinator.data.get("rideState") or self.coordinator.data.get("onlineStatus") or "未知"


class ZeehoSignalSensor(CoordinatorEntity, SensorEntity):
    """GSM 信号强度。"""

    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_signal"
        self._attr_name = f"Zeeho {vehicle_name} 信号"
        self._attr_icon = "mdi:signal"

    @property
    def device_info(self):
        return _device_info(self.coordinator, self._vin)

    @property
    def native_value(self):
        return self.coordinator.data.get("gsmRxLevValue") or "未知"

    @property
    def extra_state_attributes(self):
        return {"gsm_rx_lev": self.coordinator.data.get("gsmRxLev")}
