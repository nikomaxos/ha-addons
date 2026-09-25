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
    agent = AntigravityConversationAgent(hass, config_entry)
    async_add_entities([agent])


class AntigravityConversationAgent(
    conversation.ConversationEntity, conversation.AbstractConversationAgent
):
    """Antigravity conversation agent."""

    _attr_has_entity_name = True
    _attr_name = "Antigravity Brain"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = entry.entry_id

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
            "model": "3.8 flash high",
            "messages": [{"role": "user", "content": user_input.text}]
        }
        
        # If the API requires model (OpenAI spec)
        # payload["model"] = "gemini-3.8-flash"

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
            reply = f"Sorry, I had a problem talking to Antigravity: {err}"

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(reply)
        return conversation.ConversationResult(
            response=intent_response, conversation_id=user_input.conversation_id
        )
