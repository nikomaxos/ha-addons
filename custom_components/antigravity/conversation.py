import logging
from typing import Literal

import aiohttp
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import intent

_LOGGER = logging.getLogger(__name__)

DOMAIN = "antigravity"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    # Fast Agent (Light)
    fast_agent = AntigravityConversationAgent(
        hass, config_entry, "Antigravity Fast", "3.8 flash high", "fast"
    )
    # Heavy Agent (Direct)
    heavy_agent = AntigravityConversationAgent(
        hass, config_entry, "Antigravity Heavy", "heavy_direct", "heavy"
    )
    async_add_entities([fast_agent, heavy_agent])


class AntigravityConversationAgent(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    """Antigravity conversation agent."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str, model_name: str, id_suffix: str) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._attr_name = name
        self._model_name = model_name
        self._attr_unique_id = f"{entry.entry_id}_{id_suffix}"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return "*"

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence."""
        session = async_get_clientsession(self.hass)
        url = "http://192.168.50.10:8000/v1/chat/completions"
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": user_input.text}]
        }

        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as response:
                response.raise_for_status()
                data = await response.json()
                
                if "choices" in data and len(data["choices"]) > 0:
                    reply = data["choices"][0].get("message", {}).get("content", "Error: No content.")
                else:
                    reply = "Error: Invalid response format from Antigravity."
        except Exception as err:
            _LOGGER.error("Error calling Antigravity addon: %s", err)
            reply = f"Σφάλμα επικοινωνίας με τον Antigravity: {err}"

        import re
        speech_reply = re.sub(r'[*#_]', '', reply)

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(speech_reply)
        return conversation.ConversationResult(
            response=intent_response, conversation_id=user_input.conversation_id
        )
