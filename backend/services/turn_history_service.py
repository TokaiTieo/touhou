"""Chat messages committed alongside a turn; legacy callers opt out by default."""

import hashlib
from datetime import datetime

from backend.services.conversation_archive_service import history_count
from backend.services.npc_attribution_service import interaction_targets, npc_identity


def append_turn_history(context, result):
    turn, character = context.turn, context.character
    if not turn.record_history:
        return
    history = character.setdefault("conversation_history", [])
    saved = {}
    participants = [npc_identity(name) for name in interaction_targets(turn.action_text, turn.npc_name, turn.scene_npcs)]
    for role, speaker, content in (
        ("user", turn.player_name, turn.action_text),
        ("assistant", turn.npc_name if turn.kind == "npc_dialogue" else "旁白", result.get("description", "")),
    ):
        if not content:
            continue
        identity = hashlib.sha256(f"{character.get('timeline_epoch', '')}:{turn.turn_id}:{role}".encode()).hexdigest()
        message = {"message_id": f"turn_{identity}", "turn_id": turn.turn_id, "role": role,
                   "speaker": speaker, "content": content, "scene": turn.scene,
                   "npc_id": turn.npc_id if role == "assistant" and turn.kind == "npc_dialogue" else None,
                   "participants": participants,
                   "visibility": {"scope": "interaction_only", "audience": participants, "bystanders": "unknown"},
                   "is_dead": bool(result.get("is_dead")) if role == "assistant" else False,
                   "timestamp": datetime.now().isoformat(), "game_hour": character.get("time", {}).get("current_hour", 0),
                   "rating": None, "rewrite_candidates": []}
        history.append(message)
        saved[role] = {"message_id": message["message_id"], "message_index": history_count(character) - 1,
                       "rewrite_candidates": []}
    result["conversation"] = saved
