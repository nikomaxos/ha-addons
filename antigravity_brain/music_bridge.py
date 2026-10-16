"""Music Assistant & Audio Streaming Bridge for Antigravity Brain.

Provides unified music search, radio streaming, playlist playback,
and YouTube audio fallback across Home Assistant and Music Assistant (MASS).
"""

import logging
import os
import re
import subprocess
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Union

import requests

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

MASS_SPEAKER_PLAYERS = (
    "media_player.lva_kouzina_media_player_3",
    "media_player.lva_bluetooth_speaker_media_player_2",
)

MASS_RESULT_CATEGORIES = ("tracks", "playlists", "artists", "albums", "radio")
MEDIA_TYPE_BY_CATEGORY = {
    "tracks": "track",
    "playlists": "playlist",
    "artists": "artist",
    "albums": "album",
    "radio": "radio",
}

GROUP_PLAYER_HINTS = {
    "all",
    "all speakers",
    "everywhere",
    "media_player.antigravity_satellites",
    "media_player.notifications_group",
    "satellite",
    "satellites",
    "παντου",
    "σε ολα τα ηχεια",
    "στα ηχεια",
    "ηχεια",
    "ολα τα ηχεια",
}

KNOWN_RADIO_ALIASES = (
    "imagine 89.7",
    "imagine 897",
    "paidaki 97.5",
    "paidaki 975",
    "παιδακι 97.5",
    "παιδακι 975",
    "fly 104",
)

VALID_MEDIA_TYPES = {"track", "playlist", "artist", "album", "radio"}

# Known Player Mappings
PLAYER_MAP = {
    # Satellites / Default smart speakers
    "satellites": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "mass_players": MASS_SPEAKER_PLAYERS,
        "available_only": True,
        "ha_player": "media_player.notifications_group",
        "name": "στα ηχεία του σπιτιού"
    },
    "satellite": {
        "mass_player": "media_player.lva_kouzina_media_player_3",
        "mass_players": MASS_SPEAKER_PLAYERS,
        "available_only": True,
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
        "mass_players": MASS_SPEAKER_PLAYERS,
        "available_only": True,
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


def _normalize_text(value: str) -> str:
    """Case-fold text, remove accents, and normalize punctuation for matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^\w.]+", " ", without_accents.casefold()).strip()


def _copy_player_info(key: str) -> Dict[str, Any]:
    info = dict(PLAYER_MAP[key])
    if "mass_players" in info:
        info["mass_players"] = list(info["mass_players"])
    return info


def _resolve_target_player(player_hint: Optional[str] = None) -> Dict[str, Any]:
    """Resolve player string or hint to target mass_player and ha_player."""
    if not player_hint:
        return _copy_player_info(DEFAULT_PLAYER_KEY)

    hint = player_hint.strip().lower()
    normalized_hint = _normalize_text(hint)

    # Room media-player entities must be resolved before generic substring
    # aliases such as "speaker".
    if hint in (
        "media_player.lva_kouzina_media_player",
        "media_player.lva_kouzina_media_player_3",
    ):
        return _copy_player_info("κουζίνα")
    if hint in (
        "media_player.lva_bluetooth_speaker_media_player",
        "media_player.lva_bluetooth_speaker_media_player_2",
    ):
        return _copy_player_info("bluetooth")
    if normalized_hint in GROUP_PLAYER_HINTS:
        return _copy_player_info("satellites")

    # Exact key match
    if hint in PLAYER_MAP:
        return _copy_player_info(hint)

    # Substring match
    for k, info in PLAYER_MAP.items():
        if k in hint:
            return _copy_player_info(k)

    # Entity ID passed directly
    if hint.startswith("media_player."):
        if hint == "media_player.lva_dca63226cf9d_media_player":
            return _copy_player_info("satellites")
        return {
            "mass_player": hint,
            "mass_players": [hint],
            "ha_player": hint,
            "name": hint
        }

    return _copy_player_info(DEFAULT_PLAYER_KEY)


def _available_mass_players(player_ids: Sequence[str]) -> List[str]:
    """Return configured MASS players that Home Assistant reports as available."""
    available: List[str] = []
    inspected = False
    for entity_id in player_ids:
        try:
            response = requests.get(
                f"{BASE_API_URL}/states/{entity_id}", headers=HEADERS, timeout=3
            )
            if response.status_code != 200:
                continue
            inspected = True
            if response.json().get("state") not in ("unavailable", "unknown"):
                available.append(entity_id)
        except Exception as exc:
            logger.warning("Could not inspect MASS player %s: %s", entity_id, exc)

    # If state inspection itself is unavailable, still let MASS handle the
    # configured targets instead of skipping it and prematurely using fallback.
    return available if inspected else list(player_ids)


def _mass_players_for_target(target_info: Dict[str, Any]) -> List[str]:
    player_ids = list(
        dict.fromkeys(
            target_info.get("mass_players")
            or [target_info.get("mass_player")]
        )
    )
    player_ids = [entity_id for entity_id in player_ids if entity_id]
    if target_info.get("available_only"):
        return _available_mass_players(player_ids)
    return player_ids


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


def _empty_mass_results() -> Dict[str, List[Dict[str, Any]]]:
    return {category: [] for category in MASS_RESULT_CATEGORIES}


def search_mass(
    query: str,
    limit: int = 5,
    media_types: Optional[Union[str, Sequence[str]]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Search all configured MASS providers, including YouTube Music and radio."""
    results = _empty_mass_results()
    query = (query or "").strip()
    if not query:
        return results

    try:
        url = f"{BASE_API_URL}/services/music_assistant/search?return_response=true"
        payload = {
            "config_entry_id": MASS_CONFIG_ENTRY_ID,
            "name": query,
            # These are top-level service fields in the installed HA/MASS
            # integration, despite being grouped visually in the service UI.
            "limit": max(1, min(100, int(limit))),
            "library_only": False,
        }
        if media_types:
            payload["media_type"] = media_types

        res = requests.post(url, headers=HEADERS, json=payload, timeout=8)
        if res.status_code == 200:
            body = res.json()
            data = body.get("service_response", body)
            for category in MASS_RESULT_CATEGORIES:
                value = data.get(category, [])
                results[category] = value if isinstance(value, list) else []
            return results
        logger.warning(
            "MASS search failed for %r: HTTP %s - %s",
            query,
            res.status_code,
            res.text[:500],
        )
    except Exception as exc:
        logger.warning("Error searching Music Assistant for %r: %s", query, exc)
    return results


def play_mass_media(
    mass_player_id: Union[str, Sequence[str]],
    media_id: str,
    media_type: Optional[str] = None,
) -> bool:
    """Play a resolved URI or natural query on one or more MASS players."""
    if isinstance(mass_player_id, str):
        player_ids = [mass_player_id]
    else:
        player_ids = list(dict.fromkeys(mass_player_id))
    player_ids = [entity_id for entity_id in player_ids if entity_id]
    if not player_ids or not media_id:
        return False

    try:
        for entity_id in player_ids:
            ensure_unmuted(entity_id)

        url = f"{BASE_API_URL}/services/music_assistant/play_media"
        payload = {
            "entity_id": player_ids[0] if len(player_ids) == 1 else player_ids,
            # MASS accepts a resolved provider URI as well as a natural search
            # query here. It expects the value itself, not a one-item list.
            "media_id": media_id,
            "enqueue": "play"
        }
        if media_type:
            payload["media_type"] = media_type

        res = requests.post(url, headers=HEADERS, json=payload, timeout=12)
        if res.status_code == 200:
            return True
        logger.warning(
            "MASS play_media failed for %r (%s): HTTP %s - %s",
            media_id,
            media_type or "auto",
            res.status_code,
            res.text[:500],
        )
    except Exception as exc:
        logger.warning("Error calling MASS play_media for %r: %s", media_id, exc)
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


def _has_any_term(normalized_query: str, terms: Sequence[str]) -> bool:
    padded_query = f" {normalized_query} "
    return any(f" {term} " in padded_query for term in terms)


def _strip_play_words(normalized_query: str) -> str:
    """Remove common voice-command wrappers before exact-name comparisons."""
    words = normalized_query.split()
    ignored = {
        "βαλε",
        "βαλεμου",
        "παιξε",
        "παιξεμου",
        "play",
        "please",
        "τον",
        "το",
        "τη",
        "την",
        "μου",
    }
    while words and words[0] in ignored:
        words.pop(0)
    return " ".join(words)


def _explicit_track_request(query: str, media_type: Optional[str] = None) -> bool:
    if media_type == "track":
        return True
    normalized = _normalize_text(query)
    return _has_any_term(
        normalized,
        ("song", "track", "τραγουδι", "κομματι"),
    )


def _explicit_radio_request(query: str, media_type: Optional[str] = None) -> bool:
    if media_type == "radio":
        return True

    normalized = _normalize_text(query)
    if _has_any_term(
        normalized,
        ("fm", "radio", "station", "ραδιοφωνο", "σταθμο", "σταθμος"),
    ):
        return True

    # An explicit song/track request wins over a station alias such as
    # "Imagine" (which can also be a song title).
    if _explicit_track_request(query, media_type):
        return False

    bare_query = _strip_play_words(normalized)
    if any(alias in bare_query for alias in KNOWN_RADIO_ALIASES):
        return True
    return bare_query in {"fly", "imagine", "paidaki", "παιδακι"}


def _requested_media_type(query: str, media_type: Optional[str]) -> Optional[str]:
    requested = (media_type or "").strip().lower()
    if requested.endswith("s"):
        requested = requested[:-1]
    if requested in VALID_MEDIA_TYPES:
        return requested
    if _explicit_radio_request(query):
        return "radio"

    normalized = _normalize_text(query)
    if _has_any_term(normalized, ("song", "track", "τραγουδι", "κομματι")):
        return "track"
    if _has_any_term(normalized, ("playlist", "λιστα")):
        return "playlist"
    if _has_any_term(normalized, ("album", "αλμπουμ", "δισκο")):
        return "album"
    if _has_any_term(normalized, ("artist", "singer", "καλλιτεχνη", "τραγουδιστη")):
        return "artist"
    return None


def _radio_matches_query(query: str, radio: Dict[str, Any]) -> bool:
    query_name = _strip_play_words(_normalize_text(query))
    radio_name = _normalize_text(str(radio.get("name", "")))
    if not query_name or not radio_name:
        return False
    return query_name == radio_name or radio_name in query_name


def _ordered_result_categories(
    query: str,
    requested_media_type: Optional[str],
    mass_results: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    music_categories = ["tracks", "playlists", "artists", "albums"]
    preferred_category = {
        "track": "tracks",
        "playlist": "playlists",
        "artist": "artists",
        "album": "albums",
    }.get(requested_media_type)
    if preferred_category:
        music_categories.remove(preferred_category)
        music_categories.insert(0, preferred_category)

    radios = mass_results.get("radio", [])
    exact_station_match = any(_radio_matches_query(query, radio) for radio in radios)
    radio_first = _explicit_radio_request(query, requested_media_type) or (
        exact_station_match and not _explicit_track_request(query, requested_media_type)
    )
    if radio_first:
        return ["radio", *music_categories]
    return [*music_categories, "radio"]


def _ordered_items_for_category(
    category: str,
    query: str,
    mass_results: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    items = list(mass_results.get(category, []))
    if category != "radio":
        return items
    return sorted(items, key=lambda item: not _radio_matches_query(query, item))


def _playback_confirmation(
    category: str,
    item_name: str,
    player_name: str,
) -> str:
    if category == "radio":
        return f"Παίζει ο σταθμός {item_name} {player_name}."
    if category == "playlists":
        return f"Παίζει η λίστα αναπαραγωγής {item_name} {player_name}."
    if category == "artists":
        return f"Παίζει μουσική του καλλιτέχνη {item_name} {player_name}."
    if category == "albums":
        return f"Παίζει το άλμπουμ {item_name} {player_name}."
    return f"Παίζει το κομμάτι {item_name} {player_name}."


def play_music(query: str, player: Optional[str] = None, media_type: Optional[str] = None) -> str:
    """Play every music/radio request through MASS, with a last-resort fallback."""
    query = (query or "").strip()
    if not query:
        return "Παρακαλώ πες μου ποιο τραγούδι ή ραδιοφωνικό σταθμό θέλεις να παίξω."

    target_info = _resolve_target_player(player)
    mass_players = _mass_players_for_target(target_info)
    ha_player = target_info["ha_player"]
    player_name = target_info["name"]
    requested_media_type = _requested_media_type(query, media_type)

    # 1. Search Music Assistant across its configured providers (including
    # YouTube Music, the local library, and RadioBrowser/library radio).
    mass_results = search_mass(query, limit=5)
    for category in _ordered_result_categories(
        query, requested_media_type, mass_results
    ):
        for item in _ordered_items_for_category(category, query, mass_results):
            uri = item.get("uri")
            if not uri:
                continue
            item_type = item.get("media_type") or MEDIA_TYPE_BY_CATEGORY[category]
            if play_mass_media(mass_players, uri, item_type):
                return _playback_confirmation(
                    category, item.get("name", query), player_name
                )

    # 2. Let MASS resolve the natural query itself. This is intentionally tried
    # after URI results and before the standalone YouTube downloader because the
    # MASS resolver also has access to the configured YouTube Music provider.
    direct_media_types: List[Optional[str]] = []
    if requested_media_type:
        direct_media_types.append(requested_media_type)
    direct_media_types.append(None)
    for direct_media_type in dict.fromkeys(direct_media_types):
        if play_mass_media(mass_players, query, direct_media_type):
            return f"Ξεκίνησε μέσω Music Assistant η αναπαραγωγή για '{query}' {player_name}."

    # 3. Only after both MASS search/URI playback and MASS's direct resolver have
    # failed may the legacy cached YouTube stream path be used.
    logger.warning(
        "All MASS playback paths failed for %r on %s; trying YouTube fallback",
        query,
        mass_players,
    )
    success = play_youtube_stream(query, ha_player)
    if success:
        return f"Ξεκίνησε η αναπαραγωγή για '{query}' {player_name}."

    return f"Δεν μπόρεσα να βρω ή να αναπαράγω το '{query}'. Παρακαλώ δοκίμασε ξανά."


def control_music(action: str, player: Optional[str] = None, volume: Optional[float] = None) -> str:
    """Control playback (pause, resume, stop, next, previous, volume)."""
    action = (action or "").strip().lower()
    target_info = _resolve_target_player(player)
    mass_players = _mass_players_for_target(target_info)
    ha_player = target_info["ha_player"]

    # Target the MASS queue player(s) as well as the underlying HA player/group.
    # Queue actions such as next/previous must reach MASS, while native volume or
    # stop state can also need the underlying player.
    targets = list(dict.fromkeys([*mass_players, ha_player]))

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
