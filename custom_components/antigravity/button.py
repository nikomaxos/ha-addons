"""Button platform for Antigravity Brain."""
import logging
import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Antigravity button entities."""
    async_add_entities([
        AntigravityAuthButton(
            hass, config_entry,
            name="Connect Codex CLI",
            id_suffix="codex_auth",
            endpoint="http://192.168.50.10:8000/api/auth/codex/start",
            icon="mdi:robot"
        ),
        AntigravityAuthButton(
            hass, config_entry,
            name="Connect Antigravity CLI",
            id_suffix="agy_auth",
            endpoint="http://192.168.50.10:8000/api/auth/antigravity/start",
            icon="mdi:google"
        ),
    ])


class AntigravityAuthButton(ButtonEntity):
    """Button entity to trigger CLI authorization flows."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        id_suffix: str,
        endpoint: str,
        icon: str,
    ) -> None:
        """Initialize the button."""
        self.hass = hass
        self.entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{id_suffix}"
        self._endpoint = endpoint
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle button press."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(self._endpoint, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    _LOGGER.info("Successfully triggered auth via %s", self._endpoint)
                else:
                    _LOGGER.error("Auth trigger returned status %d from %s", response.status, self._endpoint)
        except Exception as err:
            _LOGGER.error("Failed to trigger auth via %s: %s", self._endpoint, err)
