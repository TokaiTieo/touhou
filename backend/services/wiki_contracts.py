"""Static pilot policy. Page membership is not in-world knowledge permission."""
import hashlib
import json
from dataclasses import dataclass


POLICY = 1
FILES = {
    "npc": ("npcs/npc_index.json", "npcs", ("name", "profile.identity", "location_id")),
    "place": ("locations/location_base.json", "locations", ("name", "description")),
    "book": ("world_info.json", "entries", ("title", "content")),
}


def checksum(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class PageSpec:
    id: str
    kind: str
    title: str
    readers: tuple
    scene: str
    book: str = ""

    def permits(self, reader, scene):
        return reader == "@host" or "*" in self.readers or reader in self.readers or bool(scene and self.scene == scene)


PILOT = (
    PageSpec("npc_reimu", "person", "博丽灵梦", ("npc_reimu",), "博丽神社"),
    PageSpec("npc_sanae", "person", "东风谷早苗", ("npc_sanae",), "守矢神社"),
    PageSpec("npc_sakuya", "person", "十六夜咲夜", ("npc_sakuya",), "红魔馆"),
    PageSpec("npc_remilia", "person", "蕾米莉亚", ("npc_remilia",), "红魔馆"),
    PageSpec("loc_hakurei", "place", "博丽神社", ("npc_reimu",), "博丽神社", "wi_loc_hakurei"),
    PageSpec("loc_moriya", "place", "守矢神社", ("npc_sanae",), "守矢神社", "wi_loc_moriya"),
    PageSpec("loc_scarlet", "place", "红魔馆", ("npc_sakuya", "npc_remilia"), "红魔馆", "wi_loc_scarlet"),
    PageSpec("scarlet", "faction", "红魔馆成员", ("npc_sakuya", "npc_remilia", "npc_patchouli", "npc_meiling", "npc_flandre"), "", "wi_faction_scarlet"),
    PageSpec("moriya", "faction", "守矢成员", ("npc_sanae", "npc_kanako", "npc_suwako"), "", "wi_faction_moriya"),
    PageSpec("spellcard", "rule", "符卡规则", ("*",), "", "wi_spellcard_rules"),
    PageSpec("incident", "rule", "异变解决惯例", ("*",), "", "wi_incident_custom"),
    PageSpec("outsider", "rule", "外来者", ("@host",), "", "wi_outsider"),
)
SPECS = {page.id: page for page in PILOT}
