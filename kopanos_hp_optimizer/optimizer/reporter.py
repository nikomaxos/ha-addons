"""Reports: deterministic markdown table (always) + optional LLM *wording* of the narrative.

The LLM never decides anything: it only rephrases a deterministic draft. Its output is rejected
(fallback to template) if it is empty, too long, or contains any number not present in the facts.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import _normalize_brain_url

log = logging.getLogger(__name__)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
SYSTEM_PROMPT = (
    "Είσαι βοηθός που ξαναγράφει σύντομες αναφορές αντλίας θερμότητας σε φυσικά, ζεστά ελληνικά κατάλληλα για εκφώνηση HD φωνής (Google AI TTS). "
    "ΜΗΝ προσθέτεις, αφαιρείς ή αλλάζεις αριθμούς, συμπεράσματα ή συστάσεις. Μην εφευρίσκεις τίποτα. "
    "Χρησιμοποίησε φυσική ροή λόγου, απέφευγε σύμβολα, ωμές συντομογραφίες (όπως kWh, γράψε κιλοβατώρες) και άβολα σημεία στίξης. "
    "Χωρίς markdown, χωρίς λίστες. Μέχρι 3 προτάσεις."
)


def greek_fallback(summary: Any) -> str:
    """Natural Greek voice readout fallback for summary reports.

    Formats numbers with natural Greek speech flow and avoids robotic fragments like 'παύση μέχρι συνέχιση.'
    """
    if isinstance(summary, dict):
        kwh = summary.get("kwh")
        cost = summary.get("cost_eur")
        starts = summary.get("starts")
        paused_until = summary.get("paused_until")
        next_text = summary.get("next_text") or summary.get("next_action") or ""

        parts = []
        if kwh is not None:
            parts.append("Καλημέρα.")
            kwh_str = fmt(kwh, 1)
            cost_str = f", περίπου {fmt(cost, 2)} ευρώ" if cost is not None else ""
            starts_str = f", με {fmt(starts)} εκκινήσεις" if starts is not None else ""
            parts.append(f"Χθες η αντλία κατανάλωσε {kwh_str} κιλοβατώρες{cost_str}{starts_str}.")

        if paused_until:
            parts.append("Η αυτόματη βελτιστοποίηση είναι σε προσωρινή παύση.")
        elif next_text:
            if "παύση μέχρι συνέχιση" in next_text:
                parts.append("Η αυτόματη βελτιστοποίηση είναι σε προσωρινή παύση.")
            else:
                parts.append(f"{next_text.rstrip('.')}.")
        if not parts:
            parts.append("Καλημέρα. Η αναφορά της αντλίας θερμότητας είναι έτοιμη.")
        return " ".join(parts).strip()

    text = str(summary or "")
    if "παύση μέχρι συνέχιση" in text:
        text = text.replace("παύση μέχρι συνέχιση.", "Η αυτόματη βελτιστοποίηση είναι σε προσωρινή παύση.")
        text = text.replace("παύση μέχρι συνέχιση", "Η αυτόματη βελτιστοποίηση είναι σε προσωρινή παύση.")
    return text.strip()


def fmt(v: Any, nd: int = 2, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        s = f"{v:.{nd}f}" if isinstance(v, float) else str(v)
        return s.replace(".", ",") + suffix
    return str(v) + suffix


def delta_pct(cur: Optional[float], base: Optional[float]) -> str:
    if cur is None or base in (None, 0):
        return ""
    return f"{100 * (cur - base) / base:+.1f}%".replace(".", ",")


SIGNED_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _norm_signed_num(n: str) -> str:
    sign = "-" if n.startswith("-") else ("+" if n.startswith("+") else "")
    raw = n.lstrip("+-").replace(",", ".")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    val = raw.lstrip("0") or "0"
    if val == "0":
        return "0"
    return f"{sign}{val}"


def _nums(text: str) -> set:
    return {_norm_signed_num(n) for n in SIGNED_NUM_RE.findall(text or "")}


def validate_wording(candidate: Optional[str], facts_text: str, max_len: int = 700) -> Optional[str]:
    if not candidate or not isinstance(candidate, str):
        return None
    c = candidate.strip()
    if not c or len(c) > max_len:
        return None
    c_lower = c.lower()
    if "http://" in c_lower or "https://" in c_lower or "![" in c:
        return None
    if not _nums(c) <= _nums(facts_text):
        return None
    return c


# ---------------------------------------------------------------- providers
class WordingProvider:
    name = "none"

    def rephrase(self, draft: str) -> Optional[str]:  # pragma: no cover - interface
        return None


class BrainOpenAIProvider(WordingProvider):
    name = "brain_openai"

    def __init__(self, url: str, model: str, timeout: float = 30.0, session: Optional[requests.Session] = None):
        self.url = _normalize_brain_url(url)
        self.model = model
        self.timeout = timeout
        self.s = session or requests.Session()

    def rephrase(self, draft: str) -> Optional[str]:
        r = self.s.post(self.url, timeout=self.timeout, json={
            "model": self.model, "temperature": 0.3, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": draft}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class AnthropicProvider(WordingProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 30.0, session: Optional[requests.Session] = None):
        self._key, self.model, self.timeout = api_key, model, timeout
        self.s = session or requests.Session()

    def __repr__(self) -> str:
        return f"AnthropicProvider({self.model!r})"

    def rephrase(self, draft: str) -> Optional[str]:
        r = self.s.post("https://api.anthropic.com/v1/messages", timeout=self.timeout,
                        headers={"x-api-key": self._key, "anthropic-version": "2023-06-01",
                                 "content-type": "application/json"},
                        json={"model": self.model, "max_tokens": 400, "system": SYSTEM_PROMPT,
                              "messages": [{"role": "user", "content": draft}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))


def make_provider(opts: Any) -> WordingProvider:
    if opts.llm_provider == "brain_openai" and opts.llm_brain_url:
        return BrainOpenAIProvider(opts.llm_brain_url, opts.llm_model or "gemini-3.8-flash")
    if opts.llm_provider == "anthropic" and opts.anthropic_api_key:
        return AnthropicProvider(opts.anthropic_api_key, opts.anthropic_model)
    return WordingProvider()


# ---------------------------------------------------------------- report
class Reporter:
    def __init__(self, provider: Optional[WordingProvider] = None, event_cb=None):
        self.provider = provider or WordingProvider()
        self.event_cb = event_cb or (lambda k, m: None)

    def _word(self, draft: str) -> Tuple[str, str]:
        if self.provider.name == "none":
            return draft, "template"
        try:
            out = validate_wording(self.provider.rephrase(draft), draft)
        except Exception as e:  # noqa: BLE001
            self.event_cb("llm_error", f"{self.provider.name}: {type(e).__name__}")
            out = None
        return (out, self.provider.name) if out else (draft, "template")

    def build(self, *, cycle_date: str, mode: str, assignment: Optional[str], zone: Optional[str],
              action: str, kpi: Dict[str, Any], baseline: Dict[str, Any], ab: Optional[Dict[str, Any]],
              next_text: str, exclusions: List[str], max_hz: float = 22.0, eeprom_budget_max: int = 16) -> Dict[str, str]:
        b = baseline or {}
        rows = [
            ("kWh/HDD", fmt(kpi.get("kwh_per_hdd"), 3), fmt(b.get("kwh_per_hdd"), 3), delta_pct(kpi.get("kwh_per_hdd"), b.get("kwh_per_hdd"))),
            ("kWh · €", f"{fmt(kpi.get('kwh'), 2)} · {fmt(kpi.get('cost_eur'), 2)}€", f"{fmt(b.get('kwh'), 2)} · {fmt(b.get('cost_eur'), 2)}€", delta_pct(kpi.get("kwh"), b.get("kwh"))),
            ("Εκκινήσεις", fmt(kpi.get("starts")), fmt(b.get("starts"), 1), ""),
            ("Max Hz εκκ.", fmt(kpi.get("max_hz_after_start_mean"), 1), fmt(b.get("max_hz_after_start_mean"), 1), ""),
            (f"≤{int(max_hz)} Hz %", fmt(kpi.get("low_hz_ratio_pct"), 1), fmt(b.get("low_hz_ratio_pct"), 1), ""),
            ("Άνεση ±0,3°C", fmt(kpi.get("comfort_within_03_pct"), 1, "%"), fmt(b.get("comfort_within_03_pct"), 1, "%"), ""),
            ("EEPROM", f"{fmt(kpi.get('eeprom_writes'))} στον κύκλο · max ημέρας {fmt(kpi.get('eeprom_max_daily'))}/{int(eeprom_budget_max)}", "", ""),
        ]
        table = "| KPI | Προηγ. κύκλος | Baseline | Δ% |\n|---|---|---|---|\n" + "\n".join(
            f"| {a} | {c} | {d} | {e} |" for a, c, d, e in rows)
        asg = assignment or "—"
        title = f"🧠 HP Optimizer · Κύκλος {cycle_date} ({asg}) · Ζώνη {zone or '—'}"
        if ab and ab.get("effect_pct") is not None:
            ab_line = (f"Επίδραση A/B έως τώρα: {fmt(ab['effect_pct'], 1)}% (90% CI {fmt(ab.get('ci_low_pct'), 1)}…"
                       f"{fmt(ab.get('ci_high_pct'), 1)}, ζεύγη {ab.get('n_pairs')})"
                       + (" ✅ επιβεβαιωμένο" if ab.get("confirmed") else ""))
        else:
            ab_line = "Επίδραση A/B: δεν υπάρχουν ακόμη αρκετά έγκυρα ζεύγη"
        excl = f"Εξαιρέσεις: {', '.join(exclusions)}" if exclusions else "Έγκυρη μέρα για σύγκριση"
        draft = (f"Κύκλος {cycle_date}, λειτουργία {mode}. Κατανάλωση {fmt(kpi.get('kwh'), 2)} kWh "
                 f"({fmt(kpi.get('cost_eur'), 2)} €), {fmt(kpi.get('kwh_per_hdd'), 3)} kWh ανά βαθμοημέρα, "
                 f"{fmt(kpi.get('starts'))} εκκινήσεις, μέση εξωτερική {fmt(kpi.get('t_out_mean'), 1)} °C. "
                 f"Ενέργεια: {action}. Επόμενο: {next_text}.")
        narrative, source = self._word(draft)
        markdown = (f"**{title}**\n\n{narrative}\n\nΕνέργεια: {action}\n\n{table}\n\n{ab_line} · Επόμενο: {next_text}\n\n"
                    f"_{excl} · διατύπωση: {source}_")
        short = (f"{cycle_date} · {fmt(kpi.get('kwh'), 1)} kWh · {fmt(kpi.get('kwh_per_hdd'), 2)} kWh/HDD · "
                 f"{fmt(kpi.get('starts'))} εκκ.")[:255]
        tts_draft = greek_fallback({"kwh": kpi.get("kwh"), "cost_eur": kpi.get("cost_eur"),
                                    "starts": kpi.get("starts"), "next_text": next_text})
        tts, _ = self._word(tts_draft)
        return {"title": title, "markdown": markdown, "short": short, "tts": tts[:600], "wording": source}
