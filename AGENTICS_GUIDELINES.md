# Agentic Co-Development Guidelines

This document is for **LLMs and AI agents** picking up the To-O3DE
Project Converter. It captures the working model the project's
human developer (Gaian Helmers / Genome Studios) and the
co-developing LLMs have settled on across many sessions.

If you are a human reading this — it's still useful context for how
the codebase grew, what's load-bearing, and where the design memory
lives. But you can also work directly from the standard READMEs.

This file is **the primary funnel point** for any LLM session starting
on this project. Read it before the root README, before the source
files, before anything else.

---

## 1. The working model in one paragraph

This project is co-developed between a human (intent, taste,
verification) and LLM sessions (drafting, mechanical refactoring,
cross-cutting consistency). Every non-trivial feature has a locked
design memory (the **P**lan) and a living status log (the **W**orking
**D**ocumentation). Implementation is incrementally staged with
explicit Done-when criteria (the **I**mplementation phases) and
verified at every pivot point (**T**esting matrix). This is the
**P/I/T methodology** — referenced throughout the memories. Your job
as an LLM is to operate within this model, not to bypass it.

---

## 2. First-session orientation checklist

When you start cold on this project:

1. **Read this file in full.** You're here.
2. **Read [`README.md`](README.md)** for the user-facing framing.
3. **List `.serena/memories/`** to see the active feature clusters:
   ```python
   mcp__serena__list_memories()
   ```
4. **Read `.serena/memories/platform_abstraction/working_documentation`**
   — this is the most recent architectural state-of-the-union.
5. **Read `.serena/memories/<feature>/working_documentation`** for any
   feature the user mentions.
6. **Only then read source code** — and use `mcp__serena__find_symbol`
   / `get_symbols_overview` instead of full-file reads where possible.

Skipping steps 1–4 is the most common cause of LLM sessions
re-deriving locked decisions or proposing changes that conflict with
recorded design intent.

---

## 3. The P/I/T methodology

### P — Plan (`<feature>_plan.md`)

The **design-locked** memo per feature. Sections:

- **Goal** — one paragraph of intent.
- **Resolved Decisions (Q&A history)** — every locked design decision
  captured as a Q and an A. New decisions APPEND. Superseded
  decisions stay with a "supersedes Q-N" note. Never delete.
- **Design** — data shapes, module boundaries, contracts.
- **Implementation Plan** — numbered sub-phases (I.1 / I.2 / ...) with
  explicit "Done when" criteria.
- **Testing matrix** — proofs each implementation phase must produce.
- **Out of scope (deliberately)** — what was considered and excluded.

The plan is the **destination**. It's authoritative on what the
feature should be once shipped. If the code diverges from the plan,
either the code is wrong or the plan needs a new Q&A entry — never
silent drift.

### I — Implementation phases

Numbered sub-phases within a single feature (I.1, I.2, I.3…). Each
declares:

- What changes (specific files / symbols).
- Done-when criteria (the proof it shipped).
- Required pivot verification (manual user verification or automated
  tests that must pass before the next phase begins).

Phase boundaries are **pause points**. After landing I.N, you check
in with the user — let them verify behaviour in-app or in the test
suite — before proceeding to I.N+1. Better to land 6 small verified
increments than 1 large unverified blob.

### T — Testing matrix

Per feature, a table of proofs (T-1, T-2, …) declared in the plan.
Each implementation phase produces a subset of T-rows; "tests will
come later" is not acceptable. The form of the test varies:

- **Unit tests** for clean separable surfaces (resolver functions,
  hash composition, dataclass defaults).
- **Integration tests** for end-to-end emission (parse → profile →
  emit a `.material` and assert its content).
- **UI tests** for widget behaviour (engine dropdown switches active
  platform, dirty markers appear on the right rows).
- **User-verified sandbox proofs** when no automated form fits (entity
  / component runtime behaviour that needs the live O3DE editor).

Every numbered implementation phase declares its proofs before it
ships. See [`tests/README.md`](tests/README.md) for the running
suite.

### W — Working documentation (`working_documentation.md`)

The **living** journal per feature. Newest entries on top. Tracks
shipped pieces, build fixes, regressions, decisions in flight, what's
pending. Updated after every meaningful session.

Format per entry:

```markdown
## 2026-MM-DD — <one-line summary>

### What landed
- Bullet list of code changes.

### Verification
- T-N: proof statement → PASS/FAIL/pending.

### Behavioural notes
- Anything subtle that future-you needs to know.

### Open follow-ups
- Deferred work captured here, not in code TODOs.
```

The plan defines the destination. The working doc records the
journey. Both stay live for the feature's full lifetime.

---

## 4. Memory clustering

Plan / working-doc pairs live in **per-feature folders** under
`.serena/memories/`. Cluster sub-folders organise related work:

```
.serena/memories/
    project_system/              Base Conversion Project system
    project_scope/               F-2 — scope_root + per-stage source
    dependency_banner/           F-1 — startup dep warning
    scene_marking/               F-3 — multi-scene checklist
    prefab_marking/              F-4 — scrubbed prefab checklist
    mesh_preprocessing/          F-5 — mesh defaults + per-FBX overrides
    material_preprocessing/      F-6 — shader mapping editor
    output_propagation/          F-9 — emission propagation + patch worker
    orchestration/               F-8 — preflight + Run All
    profile_editor/              F-10 — future profile authoring UI (stub)
    platform_abstraction/        Five-phase refactor → SourcePlatform plugin contract
    state_management/            Sidecar removal + sync state
    terrain/                     Terrain materials importer
    material_conversion/         Material pipeline (label resolution)
    ui_reorganization/           UX-1 — banner + dashboard + tab order
    window_chrome/               UX-2 — frameless window
    project/                     Pre-system converter notes
```

Add a new folder when starting a new feature. The folder name is
short, lower-case, snake-case, and matches the feature's working
name.

Cross-link related memories with `[[memory-slug]]` syntax inside the
files — example: `[[platform-abstraction-plan]]`. The slug is the
`name:` frontmatter field of the target memory.

---

## 5. Memory artefact frontmatter

Every memory file should have a YAML frontmatter block:

```markdown
---
name: <short-kebab-case-slug>
description: <one-line summary — used to decide relevance>
metadata:
  type: <one of: project, feature, audit, plan, working_doc>
---
```

For project-level memos: `type: project`. For feature plans: `type:
feature` or `type: plan`. For living docs: `type: working_doc`.

The `description` shows up when a future LLM session lists memories —
make it specific enough to be useful (`"F-9 patch worker design +
status"` not `"patch worker stuff"`).

---

## 6. Working with the developing user

The human developer drives intent. The LLM drafts and verifies.
Important behaviours:

### 6.1 Defer to expressed user preferences

The user knows the project better than you do. When they redirect a
proposed approach, **update the plan's Q&A** with their reasoning —
that's the durable record. Don't re-propose the same approach in a
later session.

### 6.2 Don't be sycophantic

Direct, concise, technical. Skip "Great question!" and "I'll be
happy to help." Get to the work. If a request is unclear, ask one
focused question rather than offering three vague guesses.

### 6.3 Surface uncertainty explicitly

"I don't know if X works on Windows" beats "X should work." When the
user asks for an opinion on a hard design trade-off, give your
recommendation + the case against it + ask them to confirm.

### 6.4 Pause at natural pivot points

After landing a numbered phase, **stop** and let the user verify.
Don't barrel through I.1 → I.5 in one go even if it's mechanically
possible — the verification at each boundary is part of the
methodology, not a slowdown.

The exception: when the user says "work your way through to Phase E"
or similar. Then push through and report comprehensively at the end.

### 6.5 Don't manufacture documentation drift

If the user asks you to add a feature, don't simultaneously rewrite
unrelated working docs to make the codebase "more consistent". Stick
to the task. Documentation cleanup is its own task and only happens
on explicit user request.

### 6.6 Verify before claiming done

Run the test suite. Verify the compile. Don't say "shipped" until
you've watched a green pass. The pattern across this project is:
write code → verify → update memory → tell the user. Skipping the
verification step is the biggest LLM failure mode here.

---

## 7. Code style preferences

These are settled — don't propose alternatives.

- **Plain Python, no pytest.** The test suite uses `assert` statements
  + a custom harness (`tests/harness.py`). See `tests/README.md`.
- **Catppuccin Mocha dark theme** for all PySide6 UI. Constants are
  in `main_app.py::THEME_QSS`.
- **Section banner comments** in source files:
  ```python
  # ===========================================================================
  # SECTION NAME
  # Brief description.
  # ===========================================================================
  ```
- **Long docstrings on public surfaces.** The audit memos
  (`.serena/memories/platform_abstraction/audit.md` for example) are
  written so a third-party developer can pick up cold — keep
  source-level docstrings at the same fidelity.
- **Re-exports for backwards compatibility.** When a symbol moves
  during a refactor, the original location keeps a re-export with a
  comment pointing at the new home. See `integrated_asset_processor.py`
  for many examples.
- **No "TODO" comments in code.** Defer follow-ups to the feature's
  working doc instead. Code TODOs rot; memo entries get audited.

---

## 8. The conversion-language vocabulary

The project's stated goal is to **formalize a conversion language** —
a vocabulary of stages, scopes, marks, overrides, sync states, and
patches that other engines can mirror. When you write user-facing
text (memos, READMEs, code comments), use these terms consistently:

| Term | Meaning |
|---|---|
| **Stage** | One of: asset_processor, scene_converter, mesh_processor, material_processor, terrain_processor. A pipeline phase with its own settings + per-stage Process button. |
| **Scope** | The project's source-engine asset walking root (`Project.scope_root`). All scrubbers walk inside it. |
| **Mark** | User-selected subset of an inventory (selected_prefabs, selected_scenes, selected_materials). |
| **Override** | Per-asset configuration override. Materials carry `overrides[guid].profile / materialtype / textures`; meshes carry `overrides[mesh_guid].zero_position / default_position / default_rotation`. |
| **Profile** | A shader-to-materialtype + property-remap bundle. Profiles ship under `material_processor.shader_profiles` (see `DEFAULT_SHADER_PROFILE`). |
| **Sync state** | Per-stage state machine: unconfigured / ready / synchronized / unsynchronized / writing / error. Computed via input-hash comparison. |
| **Patch** | Surgical re-emission of just the assets whose input fingerprint changed (`IntegratedAssetProcessor.patch()`). |
| **State index** | Per-asset emission fingerprint record under `outputs.state_index` (materials / meshes / prefabs / textures). |
| **Mission Command** | The Dashboard surface. Hosts the Pre-flight panel + Pipeline Status cards + Activity Log. |
| **Pre-flight** | Per-stage check pass producing a `PreflightReport` (green / yellow with Acknowledge / red blocking). |
| **Source platform** | A plugin under `platforms/<engine>/` that teaches the converter how to read one source engine. |

---

## 9. Tooling preferences

### Serena MCP

Use Serena tools instead of full file reads whenever possible:

- `mcp__serena__list_memories` — list available memos.
- `mcp__serena__read_memory(name)` — read one memo.
- `mcp__serena__find_symbol(name_path_pattern, ...)` — locate a class
  or method without reading the whole file.
- `mcp__serena__get_symbols_overview(file)` — see what's in a file at
  a glance.
- `mcp__serena__search_for_pattern(...)` — text search across the
  project.

After completing a non-trivial change, call
`mcp__serena__write_memory` to capture project facts worth keeping.

### Subagents

Spawn subagents for parallelizable independent queries, or for
context-heavy log analysis. Don't spawn for trivial work — the
round-trip cost outweighs the benefit. See the user's
`~/.claude/CLAUDE.md` for project-level preferences if they're set.

### Test discipline

Before claiming a change is done:

1. Compile-check the touched files.
2. Run the relevant test module: `python tests/unit/test_<area>.py`.
3. Run the full suite for cross-cutting changes:
   `python tests/run_all.py`.
4. For UI changes, smoke-launch the GUI (`python main_app.py`) and
   manually verify the touched panel — Qt offscreen tests cover
   logic but not visual regressions.

---

## 10. Common failure modes (avoid these)

1. **Reading the source code first.** Always check memories first —
   the source is the *implementation* of decisions captured there.
   Reading source without context produces proposals that conflict
   with locked decisions.

2. **Editing the plan instead of appending.** Plans are append-only.
   When a decision changes, add a new Q&A; don't rewrite the old
   one.

3. **Claiming "done" without verification.** The test suite exists
   for a reason. Run it.

4. **Bundling unrelated work into one task.** If the user asked for
   one thing, do that thing. Saving "while I'm in here" cleanup for
   its own task lets the user review each change cleanly.

5. **Inventing API signatures.** When unsure, look up the symbol via
   Serena or read the relevant file. Don't guess what a method's
   parameters are.

6. **Ignoring or rewriting the user's terminology.** If they call
   something a "stage", call it a "stage". Don't substitute
   "pipeline step" because it sounds clearer to you. The vocabulary
   in §8 is load-bearing.

7. **Bypassing the platform abstraction.** Don't reach back into
   `IntegratedAssetProcessor` from plugin code. The
   `SourcePlatform` contract is the only allowed interface.

8. **Writing TODOs in code.** Defer to the feature's working doc.

---

## 11. When you're done with a session

1. Update the relevant feature's `working_documentation.md` with what
   landed (newest entry on top).
2. Run the test suite one final time.
3. Surface to the user: what shipped, what's pending, where the next
   natural pivot is.
4. Don't end on a question unless the question is load-bearing for
   their next action.

A good closing message:

> **Phase A.3 shipped.** `write_fbx_assetinfo` + math helpers moved to
> `targets/o3de/assetinfo_writer.py`. Suite green (96/96).
> Updated `platform_abstraction/working_documentation`.
> Pivot: Phase A.4 (Unity shader resolver move) is next. Want me to
> push through, or pause here?

A bad closing message:

> Done! Let me know if you have any questions or if you'd like me to
> do anything else! 🎉

---

## 12. Project-specific facts to load into context

These are unlikely to change but worth knowing on day one:

- **Python target**: 3.10+. Pillow is optional (smoothness →
  roughness alpha re-bake).
- **PySide6** is the GUI framework. The QApplication is created via
  `tests.fixtures.qt_app.get_qt_app()` in tests, lazily by
  `main_app.main()` otherwise.
- **`QT_QPA_PLATFORM=offscreen`** is set by the test harness so
  windowed tests don't need a display server.
- **`U2O_SKIP_CLOSE_PROMPT=1`** is set by the test harness so close
  events don't fire save-prompts during teardown.
- **File extensions**: `.u2oproj.json` for project files,
  `.material` for O3DE materials, `.assetinfo` for O3DE FBX
  sidecars, `.prefab` (Unity) and `.unity` (Unity scenes) for source
  files.
- **The repo lives under `D:/OffLocalDev/Unity_to_O3DE_Converter/`**
  on the user's machine. Path strings in tests + memories reflect
  this; don't normalise.
- **Catppuccin Mocha colours**: `#1e1e2e` (base), `#313244`
  (surface), `#45475a` (overlay), `#cdd6f4` (text), `#89b4fa`
  (blue), `#a6e3a1` (green), `#f9e2af` (yellow), `#f38ba8` (red),
  `#fab387` (peach), `#89dceb` (sky).

---

## 13. The hand-off

The whole point of this document is so that **a fresh LLM session
can pick up a feature mid-flight without you having to re-explain
the project**. If a session ends without:

- The relevant working doc updated,
- The test suite passing,
- A clear "next pivot" statement,

then the methodology has slipped. Catch yourself when it happens and
patch up before signing off.

---

## Further reading

- [`README.md`](README.md) — the user-facing project README.
- [`platforms/README.md`](platforms/README.md) — how to add a
  source-engine plugin.
- [`platforms/unity/README.md`](platforms/unity/README.md) — the
  Unity reference case study.
- [`tests/README.md`](tests/README.md) — the test suite layout +
  recipe for writing new tests.
- `.serena/memories/platform_abstraction/audit.md` — the
  cartography of platform-agnostic vs Unity-specific code.

The methodology described above is the result of dozens of sessions
of practical co-development. Following it makes the next session
shorter, less repetitive, and more aligned with the user's intent.
Skipping it makes the next session start by re-deriving things that
were already decided.
