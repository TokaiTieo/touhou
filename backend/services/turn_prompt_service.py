"""Prompt rendering boundary shared by state-changing turn routes."""

from typing import Any, Dict
from backend.services.history_context_service import format_history_for_ai as format_history  # noqa: F401
from backend.services.npc_attribution_service import ATTRIBUTION_RULES


def render_prompt(template: str, values: Dict[str, Any], ruling_text: str) -> str:
    # Prompt files contain literal JSON examples. Replace only named
    # placeholders so example braces are never interpreted as format fields.
    prompt = str(template)
    for key, value in values.items():
        prompt = prompt.replace("{" + str(key) + "}", str(value))
    return f"{ATTRIBUTION_RULES}\n{prompt}\n\n## 后端游戏规则预裁定（必须遵守）\n{ruling_text}"
