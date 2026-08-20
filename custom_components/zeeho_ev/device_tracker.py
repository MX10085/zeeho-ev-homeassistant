import logging
from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, CONF_VIN
import math

_LOGGER = logging.getLogger(__name__)

PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323

def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    wgs_lat = lat - dlat
    wgs_lng = lng - dlng
    return wgs_lng, wgs_lat

def _transform_lat(x, y):
    ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*PI) + 20.0*math.sin(2.0*x*PI)) * 2.0 / 3.0
    ret += (20.0*math.sin(y*PI) + 40.0*math.sin(y/3.0*PI)) * 2.0 / 3.0
    ret += (160.0*math.sin(y/12.0*PI) + 320.0*math.sin(y*PI/30.0)) * 2.0 / 3.0
    return ret

def _transform_lng(x, y):
    ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*PI) + 20.0*math.sin(2.0*x*PI)) * 2.0 / 3.0
    ret += (20.0*math.sin(x*PI) + 40.0*math.sin(x/3.0*PI)) * 2.0 / 3.0
    ret += (150.0*math.sin(x/12.0*PI) + 300.0*math.sin(x/30.0*PI)) * 2.0 / 3.0
    return ret

def out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    vin = entry.data[CONF_VIN]
    vehicle_name = entry.data.get("vehicle_name", vin)
    async_add_entities([ZeehoDeviceTracker(coordinator, vin, vehicle_name)])

class ZeehoDeviceTracker(CoordinatorEntity, TrackerEntity):
    def __init__(self, coordinator, vin, vehicle_name):
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_name = vehicle_name
        self._attr_unique_id = f"zeeho_ev_{vehicle_name}_tracker"
        self._attr_name = f"Zeeho {vehicle_name}"

    @property
    def latitude(self):
        loc = self.coordinator.data.get("location", {})
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            lng, lat = gcj02_to_wgs84(loc["longitude"], loc["latitude"])
            return lat
        return None

    @property
    def longitude(self):
        loc = self.coordinator.data.get("location", {})
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            lng, lat = gcj02_to_wgs84(loc["longitude"], loc["latitude"])
            return lng
        return None

    @property
    def location_accuracy(self):
        return 50

    @property
    def icon(self):
        return "mdi:motorbike"

    @property
    def extra_state_attributes(self):
        loc = self.coordinator.data.get("location", {})
        return {
            "altitude": loc.get("altitude"),
            "location_time": loc.get("locationTime"),
            "coordinate_system": loc.get("coordinateSystem"),
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._vin)},
            "name": "ZEEHO",
            "manufacturer": "ZEEHO",
            "model": self.coordinator.data.get("vehicleName", "Unknown"),
            "configuration_url": "https://github.com/MX10085/zeeho-ev-homeassistant",
        }
