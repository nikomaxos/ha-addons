import logging
import uuid
import re
from typing import Literal

import aiohttp
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import intent

try:
    from homeassistant.components.conversation import ChatLog
    from homeassistant.components.conversation.chat_log import AssistantContent
except ImportError:
    ChatLog = None
    AssistantContent = None

_LOGGER = logging.getLogger(__name__)

DOMAIN = "antigravity"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    fast_agent = AntigravityConversationAgent(
        hass, config_entry, "Antigravity Fast", "3.8 flash high", "fast"
    )
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

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: ChatLog,
    ) -> conversation.ConversationResult:
        """Process a sentence with chat_log context."""
        return await self._process_internal(user_input, chat_log=chat_log)

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a sentence (legacy / direct fallback)."""
        return await self._process_internal(user_input, chat_log=None)

    async def _process_internal(
        self,
        user_input: conversation.ConversationInput,
        chat_log: ChatLog | None = None,
    ) -> conversation.ConversationResult:
        """Common processor for conversation requests."""
        session = async_get_clientsession(self.hass)
        url = "http://192.168.50.10:8000/v1/chat/completions"

        # Check whether the query originated from a voice satellite/device or text chat UI
        is_voice = bool(user_input.satellite_id or user_input.device_id)

        conv_id = (
            user_input.conversation_id
            or (getattr(chat_log, "conversation_id", None) if chat_log else None)
            or uuid.uuid4().hex
        )

        messages = []
        if chat_log and hasattr(chat_log, "content"):
            for item in chat_log.content:
                content = getattr(item, "content", None)
                role = getattr(item, "role", None)
                if content and role in ("system", "user", "assistant"):
                    messages.append({"role": role, "content": content})

        if not messages and user_input.text:
            messages.append({"role": "user", "content": user_input.text})

        payload = {
            "model": self._model_name,
            "messages": messages,
            "conversation_id": conv_id,
            "is_voice": is_voice,
            "device_id": user_input.device_id,
            "satellite_id": user_input.satellite_id,
        }

        continue_conversation = False
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as response:
                response.raise_for_status()
                data = await response.json()

                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0].get("message", {})
                    reply = message.get("content", "Error: No content.")
                    continue_conversation = bool(
                        message.get("continue_conversation", data.get("continue_conversation", False))
                    )
                else:
                    reply = "Error: Invalid response format from Antigravity."
                
                conv_id = data.get("conversation_id", conv_id)
        except Exception as err:
            _LOGGER.error("Error calling Antigravity addon: %s", err)
            reply = f"Σφάλμα επικοινωνίας με τον Antigravity: {err}"

        if is_voice:
            speech_reply = re.sub(r'[*#_]', '', reply)
        else:
            speech_reply = reply

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(speech_reply)

        if chat_log and AssistantContent and hasattr(chat_log, "async_add_assistant_content_without_tools"):
            try:
                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(
                        agent_id=user_input.agent_id,
                        content=reply,
                    )
                )
            except Exception as e:
                _LOGGER.debug("Could not add assistant content to chat_log: %s", e)

        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=conv_id,
            continue_conversation=continue_conversation,
        )
