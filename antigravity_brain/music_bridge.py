"""Music Assistant & Audio Streaming Bridge for Antigravity Brain.

Provides unified music search, radio streaming, playlist playback,
and YouTube audio fallback across Home Assistant and Music Assistant (MASS).
"""

import os
import json
import logging
import subprocess
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger("antigravity.music_bridge")

# Configuration & Tokens
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
FALLBACK_HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIwYjVmZWY3OTEzNWE0Yzg3OTk5MDNmN2VhMjc5MjkxMCIsImlhdCI6MTc5MDY2NzI5NSwiZXhwIjoyMTA2MDI3Mjk1fQ.xus4LJeXeJFrYJMwqheHzL5tW7tr5EexUwFgM8Es8hk"

# If inside addon container with supervisor access
if SUPERVISOR_TOKEN:
    BASE_API_URL = "http://supervisor/core/api"
    AUTH_HEADER = f"Bearer {SUPERVISOR_TOKEN}"
else:
    BASE_API_URL = "http://192.168.50.10:8123/api"
    AUTH_HEADER = f"Bearer {FALLBACK_HA_TOKEN}"

HEADERS = {
    "Authorization": AUTH_HEADER,
    "Content-Type": "application/json",
}

MASS_CONFIG_ENTRY_ID = "01KK4T9XXYV9CR1SS6YDTEYH7A"

# Known Player Mappings
PLAYER_MAP = {
    # Satellites / Default smart speakers
    "satellites": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στα ηχεία του σπιτιού"
    },
    "satellite": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στα ηχεία του σπιτιού"
    },
    "speaker": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στο ηχείο"
    },
    "ηχείο": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στο ηχείο"
    },
    "ηχεία": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στα ηχεία"
    },
    "σαλόνι": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.notifications_group",
        "name": "στο σαλόνι"
    },
    "κουζίνα": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "ha_player": "media_player.lva_kouzina_media_player",
        "name": "στην κουζίνα"
    },
    "bluetooth": {
        "mass_player": "media_player.lva_bluetooth_speaker_media_player_2",
        "ha_player": "media_player.lva_bluetooth_speaker_media_player",
        "name": "στο Bluetooth ηχείο"
    },
    # Philips OLED TV
    "tv": {
        "mass_player": "media_player.65oled718_12",
        "ha_player": "media_player.65oled718_12",
        "name": "στην τηλεόραση Philips OLED"
    },
    "oled": {
        "mass_player": "media_player.65oled718_12",
        "ha_player": "media_player.65oled718_12",
        "name": "στην τηλεόραση Philips OLED"
    },
    "philips": {
        "mass_player": "media_player.65oled718_12",
        "ha_player": "media_player.65oled718_12",
        "name": "στην τηλεόραση Philips OLED"
    },
    "τηλεόραση": {
        "mass_player": "media_player.65oled718_12",
        "ha_player": "media_player.65oled718_12",
        "name": "στην τηλεόραση"
    },
    "τηλεοραση": {
        "mass_player": "media_player.65oled718_12",
        "ha_player": "media_player.65oled718_12",
        "name": "στην τηλεόραση"
    },
    # Hisense TV
    "hisense": {
        "mass_player": "media_player.hisense_vidaa_tv_7",
        "ha_player": "media_player.hisense_vidaa_tv_7",
        "name": "στην τηλεόραση Hisense"
    }
}

DEFAULT_PLAYER_KEY = "satellites"


def _resolve_target_player(player_hint: Optional[str] = None) -> Dict[str, str]:
    """Resolve player string or hint to target mass_player and ha_player."""
    if not player_hint:
        return PLAYER_MAP[DEFAULT_PLAYER_KEY]

    hint = player_hint.strip().lower()

    # Exact key match
    if hint in PLAYER_MAP:
        return PLAYER_MAP[hint]

    # Substring match
    for k, info in PLAYER_MAP.items():
        if k in hint:
            return info

    # Entity ID passed directly
    if hint.startswith("media_player."):
        if hint in ("media_player.notifications_group", "media_player.antigravity_satellites", "media_player.lva_kouzina_media_player", "media_player.lva_dca63226cf9d_media_player"):
            return PLAYER_MAP["satellites"]
        return {
            "mass_player": hint,
            "ha_player": hint,
            "name": hint
        }

    return PLAYER_MAP[DEFAULT_PLAYER_KEY]


def ensure_unmuted(entity_id: str) -> None:
    """Ensure that the target speaker is on, unmuted, and has volume."""
    try:
        # Check current state to turn on if in standby or off
        url_state = f"{BASE_API_URL}/states/{entity_id}"
        r = requests.get(url_state, headers=HEADERS, timeout=3)
        if r.status_code == 200:
            st = r.json().get("state")
            if st in ["off", "standby"]:
                requests.post(f"{BASE_API_URL}/services/media_player/turn_on", headers=HEADERS, json={"entity_id": entity_id}, timeout=4)

        url = f"{BASE_API_URL}/services/media_player/volume_mute"
        requests.post(url, headers=HEADERS, json={"entity_id": entity_id, "is_volume_muted": False}, timeout=4)
    except Exception as e:
        logger.warning(f"Error unmuting {entity_id}: {e}")


def search_mass(query: str, limit: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    """Search Music Assistant for radio, tracks, playlists, artists, albums."""
    try:
        url = f"{BASE_API_URL}/services/music_assistant/search?return_response=true"
        payload = {
            "config_entry_id": MASS_CONFIG_ENTRY_ID,
            "name": query
        }
        res = requests.post(url, headers=HEADERS, json=payload, timeout=8)
        if res.status_code == 200:
            data = res.json().get("service_response", {})
            return {
                "radio": data.get("radio", []),
                "playlists": data.get("playlists", []),
                "tracks": data.get("tracks", []),
                "albums": data.get("albums", []),
                "artists": data.get("artists", []),
            }
    except Exception as e:
        logger.warning(f"Error searching Music Assistant for '{query}': {e}")
    return {"radio": [], "playlists": [], "tracks": [], "albums": [], "artists": []}


def play_mass_media(mass_player_id: str, media_uri: str, media_type: str) -> bool:
    """Play a media item on a Music Assistant player."""
    try:
        ensure_unmuted(mass_player_id)
        url = f"{BASE_API_URL}/services/music_assistant/play_media"
        payload = {
            "entity_id": mass_player_id,
            "media_id": [media_uri],
            "media_type": media_type,
            "enqueue": "play"
        }
        res = requests.post(url, headers=HEADERS, json=payload, timeout=8)
        if res.status_code == 200:
            return True
        logger.warning(f"MASS play_media failed: {res.status_code} - {res.text}")
    except Exception as e:
        logger.warning(f"Error calling MASS play_media: {e}")
    return False


def play_youtube_stream(query_or_url: str, target_player: str) -> bool:
    """Download, cache, and stream YouTube audio via ha-play-youtube."""
    # Ensure speaker is unmuted
    ensure_unmuted(target_player)

    # Check for ha-play-youtube binary
    yt_bin = None
    for cand in ["/usr/local/bin/ha-play-youtube", "ha-play-youtube", "./ha-play-youtube"]:
        if os.path.exists(cand):
            yt_bin = cand
            break

    if yt_bin:
        try:
            cmd = [yt_bin, query_or_url, target_player]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if res.returncode == 0:
                return True
            logger.warning(f"ha-play-youtube error: {res.stderr}")
        except Exception as e:
            logger.warning(f"Error executing ha-play-youtube: {e}")
    else:
        logger.warning("ha-play-youtube script not found in system PATH.")

    return False


def play_music(query: str, player: Optional[str] = None, media_type: Optional[str] = None) -> str:
    """High-level unified music player: searches MASS first, falls back to YouTube audio streaming."""
    query = (query or "").strip()
    if not query:
        return "Παρακαλώ πες μου ποιο τραγούδι ή ραδιοφωνικό σταθμό θέλεις να παίξω."

    target_info = _resolve_target_player(player)
    mass_player = target_info["mass_player"]
    ha_player = target_info["ha_player"]
    player_name = target_info["name"]

    # 1. Search Music Assistant
    mass_results = search_mass(query, limit=5)

    # Check for Radio station match
    radios = mass_results.get("radio", [])
    if radios:
        radio = radios[0]
        radio_name = radio.get("name", query)
        radio_uri = radio.get("uri")
        if radio_uri:
            # Play on MASS player (LVA satellite or TV)
            if play_mass_media(mass_player, radio_uri, "radio"):
                return f"Παίζει ο σταθμός {radio_name} {player_name}."

    # Check for Playlist match
    playlists = mass_results.get("playlists", [])
    if playlists:
        pl = playlists[0]
        pl_name = pl.get("name", query)
        pl_uri = pl.get("uri")
        if pl_uri and play_mass_media(mass_player, pl_uri, "playlist"):
            return f"Παίζει η λίστα αναπαραγωγής {pl_name} {player_name}."

    # Check for Track match in MASS
    tracks = mass_results.get("tracks", [])
    if tracks:
        tr = tracks[0]
        tr_name = tr.get("name", query)
        tr_uri = tr.get("uri")
        if tr_uri and play_mass_media(mass_player, tr_uri, "track"):
            return f"Παίζει το κομμάτι {tr_name} {player_name}."

    # 2. Fallback to YouTube Audio Streaming (ha-play-youtube)
    # Excellent for specific songs, artist tracks, children's songs, nursery rhymes, etc.
    success = play_youtube_stream(query, ha_player)
    if success:
        return f"Ξεκίνησε η αναπαραγωγή για '{query}' {player_name}."

    return f"Δεν μπόρεσα να βρω ή να αναπαράγω το '{query}'. Παρακαλώ δοκίμασε ξανά."


def control_music(action: str, player: Optional[str] = None, volume: Optional[float] = None) -> str:
    """Control playback (pause, resume, stop, next, previous, volume)."""
    action = (action or "").strip().lower()
    target_info = _resolve_target_player(player)
    mass_player = target_info["mass_player"]
    ha_player = target_info["ha_player"]
    player_name = target_info["name"]

    # Target both MASS player and HA player to ensure state changes
    targets = list(dict.fromkeys([mass_player, ha_player]))

    try:
        if action in ["stop", "σταμάτα", "κλείσε", "τέλος"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/media_stop", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Η μουσική σταμάτησε."

        elif action in ["pause", "παύση", "περίμενε"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/media_pause", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Η μουσική τέθηκε σε παύση."

        elif action in ["resume", "play", "συνέχισε", "ξεκίνα"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/media_play", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Η αναπαραγωγή συνεχίζεται."

        elif action in ["next", "επόμενο", "άλλο"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/media_next_track", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Μετάβαση στο επόμενο κομμάτι."

        elif action in ["previous", "προηγούμενο"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/media_previous_track", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Μετάβαση στο προηγούμενο κομμάτι."

        elif action in ["volume_up", "δυνάμωσε", "πιο δυνατά"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/volume_up", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Δυνάμωσα την ένταση."

        elif action in ["volume_down", "χαμήλωσε", "πιο σιγά"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/volume_down", headers=HEADERS, json={"entity_id": t}, timeout=4)
            return "Χαμήλωσα την ένταση."

        elif action in ["volume_set", "ένταση"]:
            if volume is not None:
                # Normalize 0-100 to 0.0-1.0 if needed
                v = float(volume)
                if v > 1.0:
                    v = v / 100.0
                v = max(0.0, min(1.0, v))
                for t in targets:
                    requests.post(f"{BASE_API_URL}/services/media_player/volume_set", headers=HEADERS, json={"entity_id": t, "volume_level": v}, timeout=4)
                return f"Η ένταση ρυθμίστηκε στο {int(v * 100)}%."

        elif action in ["mute", "σίγαση"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/volume_mute", headers=HEADERS, json={"entity_id": t, "is_volume_muted": True}, timeout=4)
            return "Η ένταση τέθηκε σε σίγαση."

        elif action in ["unmute"]:
            for t in targets:
                requests.post(f"{BASE_API_URL}/services/media_player/volume_mute", headers=HEADERS, json={"entity_id": t, "is_volume_muted": False}, timeout=4)
            return "Η σίγαση απενεργοποιήθηκε."

    except Exception as e:
        logger.error(f"Error executing music control action '{action}': {e}")
        return f"Σφάλμα κατά τον έλεγχο μουσικής: {e}"

    return f"Άγνωστη ενέργεια ελέγχου μουσικής: {action}"
