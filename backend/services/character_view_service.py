"""Bounded, versioned state responses independent from persistent save data."""

import copy
from backend.services.conversation_archive_service import history_count

STATE_FIELDS = (
    "character_id", "save_version", "state_revision", "content_schema_version", "profile", "status", "time",
    "player_state", "resources", "reputation", "relationships_map", "relationship_progress", "relationship_boundaries",
    "incident_state", "campaign_state", "onboarding", "gm_mode", "unlocked_locations", "current_goals",
    "inventory_state", "skill_experience", "spellcard_mastery", "spellcard_loadout", "usage_stats", "model_runtime",
)


def character_state(character):
    result = {key: copy.deepcopy(character[key]) for key in STATE_FIELDS if key in character}
    result.update(response_version=1, history_total=history_count(character))
    return result


def command_result(result):
    return {key: character_state(value) if key == "character" and isinstance(value, dict) else copy.deepcopy(value)
            for key, value in result.items()}
