# TouHou Changelog

## v0.16.0

- Commit player actions, AI replies, state and turn receipts in one recoverable transaction; legacy clients can retain the existing append API.
- Preserve active coordinator stages during pruning and confirm cancellation before discarding pending turns.
- Verify every referenced history chunk and select only dependency-complete recovery snapshots.
- Recover pending turn IDs across reloads without automatically starting paid generation.
- Add rebuildable SQLite full-history search and bounded immutable memory-feature caching.
- Add scenario fact/isolation checks, response review, separate human scores and report export.
- Split high-frequency component styles and fix narrow/short viewport dialogs and long names.
- Add one-command local release orchestration and independent source/EXE/ZIP verification status. Save schema remains V11.

## v0.15.0

- Hardened save IDs and resolved storage paths; future save schemas cannot be downgraded. No import file-size limit was added.
- Expanded snapshot signatures and made imports/restores recoverable character/task transactions, with pre-restore backups and isolated workflow epochs.
- Added V11 immutable conversation archives, complete portable exports, full-history search, stable paging and independent branch edits.
- Ranked memory candidates globally across NPCs and unified canonical names, legacy IDs, portraits and evaluation personas through the NPC registry.
- Added bounded state responses, compact command receipts, paginated producer records and synthetic long-save benchmarks.
- Fixed mobile send-label clipping and added desktop/mobile, large-text and keyboard-height screenshot baselines.
- Added opt-in 24/60-turn production-pipeline evaluations with token/cost budgets and cancellation; automated tests use mock providers only.

## v0.14.1

- Restricted static routes to asset directories; cached asset URLs remain compatible without exposing the project root.
- Merged Patchouli's legacy identities across content and runtime services; V10 saves preserve original conflicting values, memories, and custom fields.
- Unified SVG, PNG, and multi-size Windows ICO assets with reproducible generation and integrity checks.
- Corrected release documentation, signing order, and extracted-ZIP verification; removed unused installer/log artifacts.
- Added static-access, identity-migration, branding, and documentation regression coverage.

## v0.14.0

- Preserved original memory archives and layered summaries with retrieval and restoration.
- Serialized character commands with persisted retry receipts and atomic state commits.
- Added continuous isolated production-turn evaluation, item effects, reputation outcomes, and NPC plans.
- Added incident variants, cycle-safe task identities, paginated virtual chat history, and stable message IDs.
- Added V9 save migration, embedded build fingerprints, verified-EXE packaging, and clean extracted-ZIP smoke tests.

## v0.13.0

- Added runtime service watchdogs, bounded AI concurrency, request timeouts, SSE heartbeats, and turn lock timeouts.
- Added opt-in live narrative evaluation with four fixed Touhou scenarios and privacy-safe reports.
- Added actionable inventory, equipment, gifts, reputation benefits, repeatable incident cycles, and persistent NPC agency.
- Expanded the producer console with structured content editing, validation, backups, restore, runtime timelines, memory maintenance, and diagnostic export.
- Added bounded memory deduplication and compression, optional onboarding, accessibility settings, IME-safe input, and configurable send keys.
- Added additive V8 save migration and repair while preserving unknown fields and existing private relationship content.

## v0.11.0

- Unified the playable frontend under Vue components and removed the legacy rendering chain.
- Split save records, producer tools, turn rules, consequences, NPC simulation, memory retrieval, and content validation into focused backend services.
- Added additive V1-V7 save repair, immutable migration backups, and migration reports.
- Added deterministic consequence propagation, offscreen NPC activity, optional local semantic memory, and deeper spellcard mastery.
- Added relationship pacing and boundary handling while preserving the existing private mature-content backend.
- Added AI retry, model fallback, prompt compression, developer-only runtime diagnostics, and state-safe prose rewrites.
- Added JSON Schema validation for locations, NPCs, schedules, events, incidents, and world information.
- Expanded automated Python, API, content, JavaScript, browser, and frozen-EXE verification.

The full dated Chinese log is maintained in `updatelog.md`.
