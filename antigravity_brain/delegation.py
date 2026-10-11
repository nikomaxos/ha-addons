from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import uuid
import json

# Standard escalation reason codes
REASON_HISTORICAL_ANALYSIS = "HISTORICAL_ANALYSIS"
REASON_EXTERNAL_RESEARCH = "EXTERNAL_RESEARCH"
REASON_ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
REASON_MULTI_STEP_ANALYSIS = "MULTI_STEP_ANALYSIS"
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
REASON_TOOL_FAILURE = "TOOL_FAILURE"
REASON_GENERAL_ESCALATION = "GENERAL_ESCALATION"

@dataclass
class DelegationEnvelope:
    """Structured envelope passed from Light Agent to Heavy Agent."""
    user_query: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    conversation_id: Optional[str] = None
    reason_code: str = REASON_GENERAL_ESCALATION
    resolved_entities: List[str] = field(default_factory=list)
    light_context_summary: str = ""
    delegation_depth: int = 1
    max_depth: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_heavy_prompt(self) -> str:
        """Format the envelope into a high-clarity context prompt for the Heavy Agent."""
        parts = [
            f"ORIGINAL USER QUERY:\n{self.user_query}\n",
            f"DELEGATION REASON: {self.reason_code}",
        ]
        if self.resolved_entities:
            parts.append(f"CANDIDATE ENTITIES IDENTIFIED BY LIGHT AGENT: {', '.join(self.resolved_entities)}")
        if self.light_context_summary:
            parts.append(f"PREVIOUS CONVERSATION CONTEXT:\n{self.light_context_summary}")
        return "\n".join(parts)
