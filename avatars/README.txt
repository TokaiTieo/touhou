Local NPC avatars go here.

Use PNG files named by NPC id, for example:
npc_reimu.png
npc_marisa.png

If a file is missing, the UI falls back to the character name initial.

The 2026-10-29 generation batch adds 33 square 1254x1254 PNG portraits.
All 94 NPCs in the shipped roster now have a matching image.
Official character designs were checked against THBWiki artwork; the two
unverified project-original characters use their local descriptions instead.
Reference URLs, prompts and image hashes are recorded in:
docs/avatar-generation-2026-10-29.json

Keep historical NPC IDs unchanged even when their romanization is misleading.
The NPC roster and identity service, not a guessed English name, determine
which portrait belongs to a character. Do not overwrite existing artwork
unless replacement was requested. Update the generation record after an edit.
