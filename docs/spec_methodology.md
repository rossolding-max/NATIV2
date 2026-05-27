# Spec Methodology — From Idea to "Ready to Build"

**Status:** Generic SOP for taking a project from concept to a build-ready spec, using an AI coding assistant. NATIV2 is the worked example throughout — this entire repo (~30 docs + 17 schemas + 7 hygiene files + comprehensive test plan + project plan + v2 deferred requirements + build kickoff memo) was produced via this methodology over a focused session.

**Audience:** anyone starting a substantial software project who wants to use an AI coding assistant for the spec phase before any code is written.

**Why this exists:** "vibe coding" with an AI tends to produce working software faster than thinking through architecture upfront — but it accumulates design debt that becomes painful to refactor. This methodology front-loads the design work into a series of structured interviews + audits, so the dev team starts coding with the architecture locked + the gaps explicit. Slower at the start, much faster after.

---

## Prerequisites

### What you need BEFORE Phase 1

The AI assistant amplifies whatever you bring to the table. **You need genuine domain knowledge documented in advance.** No AI can architect a system whose domain you haven't thought through.

Concrete prerequisites:

1. **Workflow documentation** — at least sketch form. For NATIV2 this was 12+ workflow docs (one per phase) covering what happens in each, what data flows through, what edge cases matter. ~5,000-15,000 words per doc.
2. **Data model documentation** — entities + their key fields + relationships. For NATIV2 this was 15 JSON Schemas with rich descriptions covering every domain object.
3. **A README cataloguing every artefact** — so the AI can find things. For NATIV2 this was ~5,000 words listing every schema + doc + data file with a 1-paragraph description.
4. **Sample data files where applicable** — seed data (`industries.json`, `niches.json`, etc.) so the AI sees real examples.
5. **A decision-maker willing to answer questions decisively.** This methodology relies on focused Q&A rounds. If you punt every question with "what do you recommend?", you'll end up with bland defaults.

If you don't have prerequisites 1-3: spend a week writing them BEFORE starting Phase 1. The AI can help (ask it to draft from your verbal description), but you must verify every paragraph.

### What you need DURING the methodology

- ~10-30 focused hours over 1-3 weeks
- An AI coding assistant with strong agentic capabilities (the methodology was developed with Claude Code via the Claude Agent SDK)
- A git repo (every artefact gets committed)
- Patience to read what the assistant produces before saying "looks good"

---

## The 10 Phases

Sequential. Don't skip phases — each builds on the previous.

```
Phase 0  Domain spec foundation        (USER-OWNED; precondition to Phase 1)
   ↓
Phase 1  Architecture interview        (AI ASKS; USER ANSWERS in rounds)
   ↓
Phase 2  Architecture + project plan   (AI WRITES; USER REVIEWS)
   ↓
Phase 3  Data lineage audit            (AI MAPS; USER VERIFIES)
   ↓
Phase 4  Gap remediation               (AI FIXES; USER APPROVES)
   ↓
Phase 5  Test plan                     (AI ASKS + WRITES)
   ↓
Phase 6  Dev-readiness audit           (AI FINDS GAPS)
   ↓
Phase 7  Conventions + hygiene         (AI ASKS + WRITES)
   ↓
Phase 8  Simplification audit          (AI PROPOSES CUTS; USER APPROVES)
   ↓
Phase 9  Build kickoff memo            (AI WRITES)
   ↓
[Ready to build — dev team starts M0]
```

Per phase below: goal + inputs + outputs + template prompts + time estimate + "done when" + NATIV2 example.

---

## Phase 0 — Domain spec foundation

**This is YOUR work, not the AI's.** Don't ask an AI to invent your domain.

**Goal:** establish ground truth for what the system IS before designing how it works.

**Inputs:** Your head + interviews with subject matter experts + market research + competitive analysis + any existing data you can scrape together.

**Outputs:**
- One or more workflow documents per major business process
- JSON Schemas (or equivalent) for every entity in the domain
- A README cataloguing everything
- Seed data files where applicable

**Time estimate:** weeks-to-months depending on domain complexity. For NATIV2 the user had ~6 months of domain work + iterative spec refinement before AI assistance began.

**Done when:**
- A new contributor could read the workflow docs + schemas + README and understand what the system is meant to do
- You can point at any field on any schema and explain why it exists
- Cross-references between docs are stable (not changing day-to-day)

**NATIV2 example:**
- 12+ workflow docs (`docs/onboarding_workflow.md`, `docs/discovery_prep_workflow.md`, etc.)
- 15 JSON Schemas (`schemas/talent.schema.json`, `schemas/deal.schema.json`, etc.)
- `data/brand_industry_map.json` with 290 real brand records
- README with 1-paragraph descriptions of every artefact

---

## Phase 1 — Architecture interview

**Goal:** lock down the foundational "how" decisions through structured Q&A.

**Inputs:** Phase 0 output.

**Outputs:** a series of locked decisions (stack, deployment model, agent topology, integrations, etc.) captured in the conversation transcript + summarised at the end.

**Template prompt:**

```
I want to design the [system type — e.g. backend / full-stack / data
pipeline] architecture for [project name].

Structure this as an interview. Ask me clarifying questions in focused
rounds (3-4 questions per round). For each question, give me 3-4 options
with descriptions + recommend one. Lock decisions as we go.

Aim for [target depth — backend only / API surface / agent architecture /
data layer]. After each round, summarise what's locked + tell me what
the next round will cover.
```

**Key tactics:**

- **Use the AskUserQuestion (or equivalent) tool** — formal multi-choice questions force the AI to articulate options + force you to make explicit decisions.
- **Recommend an option** — the AI should always nominate a default. "What do you think?" without a recommendation produces decision fatigue.
- **Lock as you go** — after each round, state explicitly which decisions are locked + non-relitigable. Future rounds reference them.
- **Cap rounds** — 3-4 rounds of 3-4 questions = ~12-16 total decisions. Beyond that, decision fatigue degrades quality. If you need more decisions, do them in a Phase 2 interview later.
- **Pushback is welcome** — when the AI recommends X and you want Y for a reason the AI didn't consider, say so. The AI updates the model.

**Time estimate:** 1-3 hours of focused interview.

**Done when:**
- 12-20 decisions locked
- Each decision has a clear rationale (the AI summarised the trade-off you accepted)
- You can describe the system's architecture in one paragraph

**NATIV2 example:** 4 rounds × 3-4 questions = 14 decisions on:
- Stack (Python / FastAPI / SQLAlchemy / Postgres / Redis / S3 / Celery / Claude Agent SDK)
- Agent topology (coordinator + 4 skill subagents)
- LLM tier (Opus 4.7 everywhere)
- Memory model (memos with tag-filter retrieval; cross-deal cross-brand cross-industry)
- Context loading (hybrid bundles + augment tools)
- Secrets storage (pgcrypto)
- Deployment (local Docker Compose v0.1)
- Observability (Sentry + Langfuse)
- Build sequence (foundation first, all phases buildable with skip option)
- Code-gen approach (auto-gen Pydantic from JSON Schemas; hand-write SQLAlchemy)

---

## Phase 2 — Architecture + project plan synthesis

**Goal:** consolidate the interview into durable artefacts.

**Inputs:** Phase 1 locked decisions.

**Outputs:**
- `docs/architecture.md` — the "what we're building" doc (stack inventory + system diagram + components + integrations)
- `docs/project_plan.md` — the "how we'll build it" doc (dependency-ordered milestones M0...MN)
- Any new schemas that emerged from the architecture interview (e.g. NATIV2's `memo.schema.json` was specced during Phase 1 + created in Phase 2)

**Template prompt:**

```
Synthesize the locked decisions from our interview into two docs:

1. docs/architecture.md — sections: stack inventory (table), system
   component diagram (ASCII), [system-specific sections], integration
   layer, observability, schema-to-code pipeline, target repo layout.

2. docs/project_plan.md — dependency-ordered milestones (M0...MN) with
   per-milestone: inputs + outputs + acceptance criteria + skip-handling
   notes + interdependency checks.

Aim for substantive (not bullet-point summary). The dev team will read
these to start work.

Also create any new schemas that emerged from the interview (you
proposed [list]).
```

**Time estimate:** AI does the writing in ~10-20 min; you review for ~30-60 min.

**Done when:**
- Both docs exist + cross-reference each other
- New schemas validate (JSON Schema Draft 2020-12 or equivalent)
- README updated with entries for the new docs + schemas
- Committed + pushed to git

**NATIV2 example:**
- `docs/architecture.md` (425 lines / 13 sections)
- `docs/project_plan.md` (528 lines / 17 milestones M0-M17)
- `schemas/memo.schema.json` (142 lines)
- Commit `928c9a3`

---

## Phase 3 — Data lineage audit

**The single most valuable phase.** Catches things the spec misses.

**Goal:** map every cross-phase data flow with concrete schema paths. Find broken dependencies (consumer expects data nobody produces) + orphan fields (producer writes data nobody reads) + drift between consumer expectations + producer outputs.

**Inputs:** Phase 0 schemas + Phase 0 workflows + Phase 2 architecture.

**Outputs:** `docs/data_lineage.md` (or equivalent) with:
- §1 — master phase-to-phase flow graph table (every consumer's inputs from every producer with the exact schema path)
- §2 — per-phase IO catalog (inputs / outputs / computed fields per phase)
- §3 — reverse field index for high-traffic fields (writers + readers)
- §4 — gap analysis (every identified issue with severity + recommended action)

**Template prompt:**

```
Have you graphed out all of the interdependencies across the system,
including where outputs from one phase become inputs to another, plus
exactly where the data inputs for a given phase are extracted from in
a given schema?
```

(Yes, that's the literal prompt. The AI's first answer will be "no, not as a single artefact." Then it should propose building it.)

Followed by:

```
Build it.
```

**Time estimate:** AI does the writing in ~30-60 min; you skim-review for ~30 min.

**Done when:**
- The lineage doc covers every cross-phase flow (typically 50-150 rows in the master table for a system of NATIV2's complexity)
- Per-phase IO catalogs cover every phase
- Gap analysis identifies the missing/orphan/drift items
- The doc explicitly states "no broken runtime dependencies discovered" OR enumerates the ones found

**NATIV2 example:**
- `docs/data_lineage.md` (872 lines)
- ~110 cross-phase data flows catalogued
- 16 gaps identified (critical / high / low severity)
- Commit `56620c6`

---

## Phase 4 — Gap remediation

**Goal:** fix what can be fixed now; explicitly defer the rest with tracking.

**Inputs:** Phase 3 gap analysis.

**Outputs:**
- Schema + doc + workflow updates fixing the resolvable gaps
- Updates to the lineage doc marking each gap as ✅ FIXED / 🕒 DEFERRED v2 / 🛈 BY DESIGN

**Template prompt:**

```
Fix the gaps.
```

Optionally:

```
Fix only the critical + high-severity gaps. Defer low-severity to v2
with explicit tracking.
```

**Time estimate:** depends on gap count. NATIV2's 9 fixes took ~30 min of AI work.

**Done when:**
- Every gap from Phase 3 is marked [FIXED] / [DEFERRED] / [BY DESIGN] in the lineage doc
- All schema changes validate
- All cross-references resolve
- Committed

**NATIV2 example:** Commit `b8a4d12` fixed 9 gaps (added `agency_id` to 15 schemas; extracted `kpiMetric` to shared schema; documented status sync discipline; tightened template version enforcement; created contract template scaffold; sharpened audience_demographics snapshot timing; etc.).

---

## Phase 5 — Test plan

**Goal:** comprehensive test architecture covering every code surface.

**Inputs:** Phase 2 project plan + Phase 2 architecture + Phase 0 workflows.

**Outputs:** `docs/test_plan.md` covering:
- Test strategy (pyramid + categories + coverage targets)
- Per-milestone test deliverables (mirrors project plan)
- Per-app-phase test deliverables (mirrors architecture phases)
- Fixture strategy (synthetic + real)
- LLM/AI testing strategy where applicable
- CI pipeline structure
- Completion criteria

**Template prompt:**

```
Now write a complete suite of unit and e2e tests and other tests for
both 1) each phase of the project plan build and 2) each phase of the
app. [Backend/Frontend/Both] only. Plan and tests must also ensure
[deployment readiness — e.g. API surface ready for frontend; CLI ready
for ops; etc.] but initial testing will be of [target] in CLI.

Testing will first use a standard set of tests but then use an actual
example of [a real entity from your domain — agency / customer / user /
account] in CLI.

Ask me clarifications then build a plan to create these.
```

**Clarification rounds expected** (the AI should ask you):

- What's the canonical real-data fixture? (Real with PII / anonymised / fully synthetic)
- Test execution cost vs coverage trade-off (especially for expensive AI tests)
- Manual-test harness shape (CLI tool / HTTP scripts / pytest scenarios)
- Frontend readiness criteria (OpenAPI contract / stub frontend / mock service worker)
- Coverage target strictness

**Time estimate:** 30-60 min interview + 30-60 min AI writes the plan.

**Done when:**
- Plan exists covering all 4 layers (unit / integration / e2e / specialty like LLM eval)
- Per-milestone test deliverables defined for every milestone
- Per-phase test deliverables defined for every runtime phase
- Synthetic fixture spec + real-data protocol both documented
- CI gating + cost budgets explicit

**NATIV2 example:**
- `docs/test_plan.md` (1053 lines / 12 sections)
- Synthetic fixture: Acme Talent Agency + Riley Carter (fitness influencer)
- Real fixtures: local-only at `~/.nativ/test_fixtures/`
- Custom CLI tool: `nativ test ...`
- LLM eval: hybrid cassettes + nightly real (gated by $25 budget)
- 100% coverage target with metric per module type
- Commit `1b1c5f9`

---

## Phase 6 — Dev-readiness audit

**The "are we actually ready?" review.** Critical phase — catches missing conventions, hygiene files, unspecified design decisions, inconsistencies between docs.

**Goal:** surface everything implicit that should be explicit before a dev team starts.

**Inputs:** the entire repo state so far.

**Outputs:** a categorised audit report listing:
- 🔴 Critical (must fix before any coding starts)
- 🟡 Important (should fix early in the build)
- 🟢 Nice-to-have
- Inconsistencies between docs
- Implied things that should be made explicit
- Recommended actions

**Template prompt:**

```
Check that the code base is now ready for a dev team to jump in and
start building. Is anything missing, unclear, inconsistent? Anything
at all implied that needs to be made explicit? Any further guidance
that would be useful to ensure a clean build?
```

**Common gaps the AI will surface** (expect these):

- Authentication / authorization spec (often unspecified)
- API conventions (URL versioning / envelope / errors / pagination / idempotency / long-running ops)
- ID generation conventions (server vs client; per-record-type format)
- Code conventions doc (style / naming / async / exceptions / logging)
- Dev environment setup (Docker Compose / env vars / common commands)
- Configuration spec (every env var enumerated)
- Concurrency + idempotency patterns
- Error handling discipline
- Hygiene files (CONTRIBUTING / SECURITY / CLAUDE / .editorconfig / .pre-commit-config)
- Money + time conventions
- File upload patterns
- Soft-delete patterns
- Multi-tenant readiness if applicable

**Time estimate:** AI does audit in ~15-30 min; produces a categorised list.

**Done when:**
- You have a comprehensive list of gaps with severity
- For each gap, the AI has recommended a specific action
- You decide which gaps to fix in Phase 7

**NATIV2 example:** The audit surfaced 4 critical + 8 important + 7 nice-to-have + 7 inconsistencies. User decided to fix all of them (Phases 7 = Commits A + B).

---

## Phase 7 — Conventions + hygiene

**Goal:** close every gap from Phase 6.

**Inputs:** Phase 6 audit + user decisions on contentious points.

**Outputs:**
- New convention docs (auth, API, IDs, code, config, dev setup)
- Hygiene files (CONTRIBUTING.md, SECURITY.md, CLAUDE.md, .editorconfig, .pre-commit-config.yaml, .env.example, extended .gitignore)
- Inconsistency cleanups

**Template prompt:**

```
Do A and B [the recommended action plan from Phase 6 audit] — ask me
all the questions one by one and I'll answer.
```

**Interview pattern:**

The AI should ask one focused question at a time. Each question:
- Has 3-4 options + recommended
- Each option describes the trade-off
- You answer with the choice (or "Other" + your preferred answer)

Expect 10-20 questions covering:
- Auth mechanism (or "no auth v1" decision)
- API URL structure
- Long-running ops pattern
- Response envelope shape
- ID generation
- Pagination style
- Concurrency model
- File upload pattern
- Idempotency strategy
- Money type
- Stub frontend stack (or skip)
- Soft-delete scope
- Pre-commit hook aggressiveness
- Branch / commit conventions

**Time estimate:** 30-60 min interview + 1-2 hours AI writes the docs.

**Done when:**
- Every convention has a doc
- Every hygiene file exists
- Locked decisions table (in CLAUDE.md or equivalent) updated with v0.1-vs-v2 entries
- Inconsistencies resolved
- All cross-references resolve
- Committed (often as 2 commits: spec docs + hygiene/cleanups)

**NATIV2 example:**
- Commit A `bbf66fb` (2682 lines): 6 spec docs (auth + API + ID + code + config + dev_setup)
- Commit B `f5c195c` (1049 lines): 4 inconsistency cleanups + 7 hygiene files

---

## Phase 8 — Simplification audit

**Goal:** before committing to the build, remove what you don't need.

**Inputs:** Phase 7 complete spec.

**Outputs:**
- A categorised list of simplification candidates:
  - 🟢 Clear wins (cut now)
  - 🟡 Could go either way
  - 🔴 Don't cut (looks like a cut but is actually high-value)
- Applied simplifications committed to the codebase
- A "v2 deferred requirements" doc capturing everything deferred (so v2 work has a clear backlog)

**Template prompt:**

```
Looking at the design, app, architecture, workflows, data schema,
project plan, guidance / instructions, is there anything to simplify
or remove whilst maintaining core functionality?
```

Followed by:

```
Apply all [your S's and M's — or specific items] — capture any v2
requirements that are dropped for v1.
```

**What to expect the AI to flag for simplification:**

- Over-engineered API protocols (optimistic concurrency / cursor pagination / presigned uploads when datasets are small + single-operator)
- Premature parallelism (multiple worker queues when throughput is trivial)
- Premature frontend tooling (stub frontends, type generation pipelines when production frontend doesn't exist yet)
- Over-broad testing scope (5 cassette scenarios per pack when 3 catches drift)
- Hard gates that are overkill for v0.1 single-operator (Idempotency-Key on every endpoint vs only-where-it-matters)

**What to expect the AI to recommend KEEPING:**

- Multi-tenant readiness (agency_id everywhere) — cheap now, expensive to add later
- Decimal money — rounding errors compound
- Soft-delete — audit trail
- UTC discipline — timezone bugs are devastating
- Custom exception hierarchy — clean error-handling
- Memo system existence — fundamental capability

**The v2 deferred requirements doc is critical.** Without it, every "what about X?" question from the dev team has no answer. With it, every deferral is explicit + has a clear v2 work item.

**Time estimate:** AI audit ~30 min; user decisions ~15 min; AI applies changes ~30-60 min.

**Done when:**
- Simplifications applied
- `docs/v2_deferred_requirements.md` (or equivalent) exists with every deferral catalogued
- Each deferred item has: v0.1 behaviour (what we ship) + v2 work (what to add) + v0.1 hardcoding (where in code reflects the deferred behaviour) + v2 cost estimate
- Every V2-* ID referenced from other docs is defined in the v2 doc
- Committed

**NATIV2 example:**
- Commit `abb9767`: applied 11 simplifications (6 clear wins + 5 could-go-either-way)
- Created `docs/v2_deferred_requirements.md` (445 lines / 53 V2-* IDs across 11 categories)
- Saved ~2 weeks of v0.1 implementation work

---

## Phase 9 — Build kickoff memo

**Goal:** one doc the dev team reads BEFORE anything else.

**Inputs:** the entire repo state.

**Outputs:** a tight orientation memo (200-300 lines) covering:
- TL;DR + product in 60 seconds + where we are now
- Mandatory pre-build reading list (with time estimates)
- Read-before-coding triggers (intent → required reading)
- Locked decisions summary
- First-week plan
- Critical rules to internalize
- Common pitfalls
- Where the v2 stuff lives
- Where to ask questions
- Self-test questions
- Pre-PR checklist

**Template prompt:**

```
Now create a memo for a dev team to pick up and read ahead of the build
which points them to all the key docs and artifacts.
```

**Key design choices for the memo:**

- **15-min read max.** Longer = doesn't get read.
- **Self-test at end with NO answers.** Dev must find answers in the docs → learns doc structure.
- **Reading list is ORDERED** with time estimates. Don't say "read these"; say "read in this order, 2 hours total."
- **Locked decisions table** condensed from the main spec — saves the dev from hunting.
- **Common pitfalls** — explicit "don't do X" list. Saves a code review cycle.
- **Pointer hooks** — link from README ("New here? Start here") + from CLAUDE.md / equivalent ("Humans read this first; this file is for AI assistants").

**Time estimate:** AI writes in ~15-30 min; you review for ~15 min.

**Done when:**
- Memo exists + reads cleanly
- README links to it prominently from the top
- AI-context file (CLAUDE.md or equivalent) links to it as the human-facing counterpart
- Cross-references resolve

**NATIV2 example:**
- `docs/build_kickoff.md` (271 lines / 13 sections)
- README top callout: "👋 New here? Start with `docs/build_kickoff.md`"
- Commit `a5f0aa4`

---

## Anti-patterns to avoid

### Skip Phase 0 → architecture is guesswork

If the AI is inventing your domain instead of mapping your domain, the architecture will be generic + miss the real constraints. Spend the weeks on Phase 0.

### Skip Phase 3 → broken dependencies ship to production

The lineage audit catches issues that look correct at the schema level but break at the integration level. Worth its weight in gold.

### "Looks good, ship it" without reading

The AI produces 500-line docs in 30 minutes. If you don't read them, you don't know what was decided. Set aside time to read every artefact the AI produces before saying "looks good."

### Letting the AI design auth without you weighing in

Auth is a critical security decision with long-term implications. Always interview on auth — never let the AI default-pick.

### Adding "v2-ready" features prematurely

Every "future-proof for v2" decision adds v0.1 cost. Phase 8 simplification audit catches this — but you can pre-empt by defaulting to "ship v0.1 simply; capture v2 explicitly."

### Skipping the v2 deferred requirements doc

Without it, "we deferred X" becomes oral tradition that no one remembers in 6 months. With it, v2 has a written backlog from day 1.

### Letting one round of Q&A drag past 4-5 questions

Decision fatigue is real. After 4-5 questions in a row, your answers get sloppier. Split into multiple rounds.

### Building the spec in private + dumping on the dev team

The dev team needs the build kickoff memo + reading order + locked decisions. Without those, even a perfect spec produces confused builders.

---

## "Done when" — the final checklist

You're ready to hand to a dev team when:

- [ ] Phase 0 domain spec exists + is stable
- [ ] Phase 1 architecture decisions are locked in a single source of truth
- [ ] Phase 2 architecture doc + project plan exist + cross-reference each other
- [ ] Phase 3 data lineage doc exists with §1 master flow graph + §2 per-phase IO + §3 reverse index + §4 gap analysis
- [ ] Phase 4 gaps remediated; lineage doc marks each [FIXED] / [DEFERRED] / [BY DESIGN]
- [ ] Phase 5 test plan covers all 4 test layers + per-milestone deliverables + fixture strategy + CI gating
- [ ] Phase 6 dev-readiness audit complete; all critical + important gaps either fixed or explicitly accepted
- [ ] Phase 7 convention docs exist (auth, API, IDs, code, config, dev_setup) + hygiene files committed
- [ ] Phase 8 simplification audit applied; v2_deferred_requirements doc exists with every deferral catalogued
- [ ] Phase 9 build kickoff memo exists + is linked from README + AI-context file
- [ ] All cross-references between docs resolve
- [ ] All schemas validate
- [ ] All locked decisions appear in a single locked-decisions table (typically in your AI-context file)
- [ ] Self-test in the build kickoff memo can be passed by reading the docs

When all 13 ticked: dev team can start M0.

---

## Quick reference card

| Phase | Output | Template prompt (excerpt) |
|---|---|---|
| 0 | Workflows + schemas + README | (User-owned; precondition) |
| 1 | Locked architecture decisions | "Structure this as an interview. Ask me clarifying questions in focused rounds (3-4 per round)..." |
| 2 | Architecture + project plan docs | "Synthesize the locked decisions into [architecture.md + project_plan.md]..." |
| 3 | Data lineage doc | "Have you graphed out all of the interdependencies across the system...?" then "Build it." |
| 4 | Gap fixes | "Fix the gaps." |
| 5 | Test plan | "Write a complete suite of unit + e2e + other tests... Ask me clarifications then build a plan." |
| 6 | Dev-readiness audit | "Check that the code base is ready for a dev team to jump in. Is anything missing, unclear, inconsistent?" |
| 7 | Convention docs + hygiene files | "Do A and B — ask me all the questions one by one." |
| 8 | Simplifications + v2 deferred doc | "Is there anything to simplify or remove whilst maintaining core functionality?" then "Apply all your S's and M's — capture any v2 requirements." |
| 9 | Build kickoff memo | "Create a memo for a dev team to pick up and read ahead of the build." |

---

## Estimated total time

For a system of NATIV2's complexity (12-phase pipeline, 5 AI pack types, multi-vendor integrations, multi-tenant readiness):

| Phase | User time | AI time |
|---|---|---|
| 0 | Weeks-months (pre-existing) | n/a |
| 1 | 1-3 hours interview | ~30 min synthesis between rounds |
| 2 | 30-60 min review | ~30-60 min writing |
| 3 | 30 min skim review | ~30-60 min mapping |
| 4 | 30 min review | ~30 min fixes |
| 5 | 30-60 min interview + review | ~60-90 min writing |
| 6 | 30 min review of audit | ~30 min audit |
| 7 | 30-60 min interview + review | ~2 hours writing |
| 8 | 30 min reviewing simplification proposals | ~60-90 min applying |
| 9 | 15 min review | ~30 min writing |
| **Total** | **~5-10 hours** | **~6-10 hours** |

Calendar time: 1-3 weeks of focused work depending on how many sessions you can fit in.

---

## Adapting to smaller projects

The methodology scales down. For a simpler system (single-domain CRUD app, no AI agents, single deployment target):

- Phase 1: 1 round of 4 questions
- Phase 2: smaller architecture doc (~100 lines) + flat milestone list (~5-10 items)
- Phase 3: lineage doc is shorter (maybe just per-table CRUD operations)
- Phase 4: fewer gaps to fix
- Phase 5: test plan is ~300 lines (no LLM eval section)
- Phase 6: fewer gaps to audit
- Phase 7: fewer convention docs (maybe just API + dev_setup + code_conventions)
- Phase 8: fewer simplifications
- Phase 9: shorter memo (~100 lines)

Total time: ~2-3 days instead of 1-3 weeks.

The phase SEQUENCE doesn't change — only the depth at each phase. Don't skip phases even on small projects; Phase 3 (lineage) and Phase 8 (simplification) prevent the most painful issues.

---

## Adapting to existing codebases

If you're applying this to a codebase that already has working code (not a greenfield):

- **Phase 0 is partial.** You have schemas + code, but maybe not workflow docs. Reverse-engineer them from the code.
- **Phase 1 documents existing decisions rather than making new ones.** The questions become "is this still the right call?" rather than "what should we choose?"
- **Phase 3 (lineage) is even more valuable.** Existing code often has implicit data flows that have never been documented.
- **Phase 6 (dev-readiness audit) becomes "is this maintainable + extendable?"** rather than "is this ready for new devs?"
- **Phase 8 (simplification) becomes a genuine refactor candidate list.**

You can also pick specific phases. If you have a working app with strong code but no spec docs, run Phase 3 + Phase 6 + Phase 9 to produce documentation that didn't exist before.

---

## Final thoughts

The methodology's value isn't the docs it produces — it's the **decisions surfaced**. Every locked decision is a decision the team didn't have to argue about during the build. Every documented gap is a debug session avoided. Every v2 deferral is a "we already decided" answer instead of a "we'll figure it out later."

The AI is fast. You are the bottleneck. The methodology works because it imposes structure on the Q&A — focused rounds, decisive answers, explicit acknowledgement of what's been decided.

When something is unclear during the build, the answer should be in the docs. If it isn't, the methodology had a gap. Update the methodology.
