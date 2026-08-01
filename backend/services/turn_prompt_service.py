"""Prompt rendering boundary shared by state-changing turn routes."""

from typing import Any, Dict, List


def format_history(history: List[Dict], max_count: int = 20) -> str:
    if not history:
        return "（无历史记录）"
    lines = []
    for item in history[-max_count:]:
        speaker = item.get("speaker") or ("玩家" if item.get("role") == "user" else "旁白")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{speaker}：{content}")
    return "\n".join(lines) or "（无历史记录）"


def render_prompt(template: str, values: Dict[str, Any], ruling_text: str) -> str:
    # Prompt files contain literal JSON examples. Replace only named
    # placeholders so example braces are never interpreted as format fields.
    prompt = str(template)
    for key, value in values.items():
        prompt = prompt.replace("{" + str(key) + "}", str(value))
    return f"{prompt}\n\n## 后端游戏规则预裁定（必须遵守）\n{ruling_text}"
