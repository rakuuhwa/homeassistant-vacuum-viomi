"""Config flow to configure Xiaomi Viomi."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from construct.core import ChecksumError
from homeassistant import config_entries
from homeassistant.components.xiaomi_miio import CONF_MODEL
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PLATFORM,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    DEVICE_DEFAULT_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from miio import DeviceException
from miio.device import DeviceInfo
from miio.integrations.vacuum.viomi.viomivacuum import ViomiVacuum

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEVICE_CONFIG = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TOKEN): vol.All(str, vol.Length(min=32, max=32)),
        vol.Optional(CONF_NAME, default=DEVICE_DEFAULT_NAME): str,
    }
)


class ViomiDeviceHub:
    """Class to async connect to a Viomi Device."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the entity."""
        self._hass = hass
        self._device: Optional[ViomiVacuum] = None
        self._device_info: Optional[DeviceInfo] = None

    @property
    def device(self):
        """Return the class containing all connections to the device."""
        return self._device

    @property
    def device_info(self):
        """Return the class containing device info."""
        return self._device_info

    async def async_device_is_connectable(self, host: str, token: str) -> bool:
        """Connect to the Xiaomi Device."""
        _LOGGER.debug("Initializing with host %s (token %s...)", host, token[:5])

        try:
            self._device = ViomiVacuum(host, token)
            self._device_info = await self._hass.async_add_executor_job(
                self._device.info
            )

            if self._device_info:
                _LOGGER.debug("%s detected", self._device_info.model)
        except DeviceException as error:
            if isinstance(error.__cause__, ChecksumError):
                raise ConfigEntryAuthFailed(error) from error

            _LOGGER.error(
                "DeviceException during setup of Viomi device with host %s",
                host,
            )
            return False

        return True


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    hub = ViomiDeviceHub(hass)

    if not await hub.async_device_is_connectable(data[CONF_HOST], data[CONF_TOKEN]):
        raise InvalidAuth

    DEVICE_CONFIG.extend({vol.Optional(CONF_PLATFORM): str})(data)

    name = data[CONF_NAME] if CONF_NAME in data else hub.device_info.model

    return {
        CONF_HOST: data[CONF_HOST],
        CONF_TOKEN: data[CONF_TOKEN],
        CONF_MODEL: hub.device_info.model,
        CONF_NAME: name,
        CONF_UNIQUE_ID: format_mac(hub.device_info.mac_address),
        CONF_MAC: format_mac(hub.device_info.mac_address),
    }


class XiaomiViomiFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a Xiaomi Viomi config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DEVICE_CONFIG)

        errors = {}
        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except (InvalidAuth, ConfigEntryAuthFailed):
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            unique_id = info[CONF_MAC]
            existing_entry = await self.async_set_unique_id(
                unique_id, raise_on_progress=False
            )

            if existing_entry:
                data = existing_entry.data.copy()
                data[CONF_HOST] = info[CONF_HOST]
                data[CONF_TOKEN] = info[CONF_TOKEN]
                data[CONF_NAME] = info[CONF_NAME] or existing_entry.title
                data[CONF_MODEL] = info[CONF_MODEL]

                self.hass.config_entries.async_update_entry(existing_entry, data=data)
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="already_configured")

            return self.async_create_entry(title=info[CONF_NAME], data=info)

        return self.async_show_form(
            step_id="user", data_schema=DEVICE_CONFIG, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
