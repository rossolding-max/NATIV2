# Contributing

Welcome. This guide covers branch naming, commit messages, PR process, and code review expectations. Pair with `docs/dev_setup.md` (local environment) + `docs/code_conventions.md` (style + patterns).

---

## Branch naming

Format: `{type}/{short-description-in-kebab-case}`

| Type | When |
|---|---|
| `feature/` | New functionality |
| `fix/` | Bug fix |
| `chore/` | Tooling, dependencies, doc updates with no functional change |
| `refactor/` | Internal restructure without behaviour change |
| `test/` | New tests for existing behaviour |
| `spec/` | Spec doc updates (docs/, schemas/) without code change |

Examples:
- `feature/m4-agency-setup-endpoints`
- `fix/posting-detection-brand-handle-missing`
- `chore/upgrade-anthropic-sdk-0.40`
- `refactor/extract-pack-bundle-composer`
- `test/contract-tests-for-phase-3a`
- `spec/clarify-memo-tag-filter-semantics`

Branch from `main`. PR back to `main`. No long-lived branches.

---

## Commit messages

### Format

```
<type>: <short subject (<72 chars)>

<body explaining WHY this change is necessary, what's tricky about it,
and any context a future reader needs. Wrap at ~80 chars.>

<optional footer with refs to issues, milestones, GAP IDs, etc.>
```

`<type>` is the same as branch type (`feature`, `fix`, `chore`, `refactor`, `test`, `spec`).

### Subject rules

- Imperative mood ("Add X" not "Added X" or "Adds X").
- No trailing period.
- Specific (not "fix bug" — say which bug).

### Body rules

- Explain WHY, not WHAT. The diff shows WHAT.
- Reference docs/schemas/milestones where relevant.
- Note any breaking changes prominently (`BREAKING:` prefix on a line).

### Examples

```
feature: M11 discovery prep pack generation pipeline

Implements the M11 milestone per docs/project_plan.md — the first
AI pack that validates the coordinator + skill subagent architecture
end-to-end. Composes researcher (Exa brand research) + writer
(briefing + agenda + slides) + renderer. Auto-fires on substage
transition to initial_call_scheduled.

Per docs/test_plan.md § M11, ships with:
- 7 unit + integration tests
- 5 golden cassette scenarios (different niches × brand archetypes)
- 1 e2e test (full lifecycle)

LLM cost telemetry recorded via Langfuse; expected ~$0.30-0.80 per
prep pack at Opus 4.7.

Refs: M11
```

```
fix: Phase 4.8 detection scoring missing brand_handle signal

The G1 audit fix added social_handles to brand_industry_map but
the scoring algorithm in app/services/posting_detection.py was
still reading the (now-removed) deprecated handle field. Re-wire
to brand.social_handles.{platform} per docs/data_lineage.md
GAP-N1 fix.

Adds regression test that fails without this fix.

Refs: G1, GAP-N1
```

```
spec: clarify memo retrieval semantics for multiple tag keys

docs/data_lineage.md § 5 + schemas/memo.schema.json description
left ambiguous whether `read_memos(brand_id=X, industry_id=Y)`
means brand_id=X AND industry_id=Y (intersection) or OR.

Per design intent: AND across keys, OR within keys (multi-value).
Schema description tightened; data_lineage doc clarified.

No code change.
```

### Conventional Commits

Conventional Commits format is NOT enforced but is encouraged for readability. The above examples are compatible.

---

## Pull requests

### PR template

When you open a PR, the template auto-loads. Fill in every section:

```markdown
## Summary

<1-3 sentences. What does this PR do? Why?>

## Changes

- <bullet per logical change>
- <link to the milestone or spec being implemented>
- <link to any GAP IDs being fixed>

## Test plan

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Contract tests added/updated (if API surface changed)
- [ ] LLM eval cassettes added/re-recorded (if agent code changed)
- [ ] E2E test added/updated (if cross-phase flow changed)
- [ ] Manual testing performed (describe what you ran locally)

## Docs

- [ ] Workflow doc updated (docs/{phase}_workflow.md)
- [ ] Data lineage updated (docs/data_lineage.md) if cross-phase
- [ ] CLAUDE.md updated (if locked decisions changed)
- [ ] Schema migration written + reviewed

## Risk

- <breaking changes>
- <vendor dependencies added/changed>
- <cost / perf implications>

## Screenshots / output

<paste CLI output, before/after diff, screenshots if UI changed>
```

### Review requirements

| Type of change | Reviewers required |
|---|---|
| Schema change | 2 (one for schema, one for migration discipline) |
| Auth/security code (v2) | 2 (one must be security-cleared) |
| Agent code (LLM-touching) | 1 + cassette diff review |
| Vendor wrapper | 1 |
| Spec docs only | 1 |
| Code conventions / CONTRIBUTING / CLAUDE.md | 2 (these are durable team contracts) |
| Everything else | 1 |

### Merge requirements

Before a PR can merge:

- [ ] All CI gates green
- [ ] 1+ approving reviews (or 2+ per the table above)
- [ ] No unresolved review comments
- [ ] Branch up to date with `main` (rebase, not merge — keep history linear)
- [ ] Commit history is clean (squash WIP commits; keep meaningful commits)

### Merge method

**Squash merge** is the default. PR title becomes the squash commit subject; PR description becomes the body.

For multi-commit PRs where individual commits tell a coherent story (e.g. "schema change", "service implementation", "tests"), **rebase merge** is acceptable — coordinate with reviewer.

`merge` (merge commits) is forbidden — keeps history linear.

---

## Code review expectations

### Reviewer's job

- Verify correctness against the spec (docs + schemas).
- Check tests cover the change (per `docs/test_plan.md` for the relevant milestone/phase).
- Flag inconsistencies with code conventions (`docs/code_conventions.md`).
- Surface security concerns (PII in logs, secret leakage, SQL injection vectors).
- Question premature abstractions — push back if the change does more than the task needs.

### Author's job

- Self-review BEFORE requesting review (catch the obvious stuff).
- Respond to every comment (resolve, fix, or explain why not).
- Re-request review after fixes.
- Don't merge your own PR without approval.

### Tone

Reviews are collaborative. Suggest rather than command ("Consider X" rather than "Do X"). Author shouldn't take it personally. Reviewer shouldn't nitpick style if pre-commit hooks would catch it anyway.

---

## Versioning

The repo uses semantic versioning at the API level:

- `v0.1.0` — initial internal release (local-hosted, single-tenant)
- `v0.1.x` — bug fixes + non-breaking additions during v0.1
- `v0.2.0` — features deferred from v0.1 (industry KPI benchmarks, pitch_angles closed-loop, sibling commission auto-gen, etc.)
- `v1.0.0` — SaaS launch (multi-tenant, auth, hosted deployment)
- `v2.0.0` — major breaking changes (URL `/api/v2/`); coordinated cutover

The Python package version in `pyproject.toml` tracks the API version (kept in sync). DB migrations are independent of API version but carry SemVer for the schema layer (`schemas/*.schema.json` `$id` version field).

---

## Release process

1. Land all v{X.Y.Z} milestones on `main`.
2. Update `CHANGELOG.md` with grouped notes (Added / Changed / Fixed / Deprecated / Removed / Security).
3. Bump version in `pyproject.toml` + `app/config.py:Settings.nativ2_version`.
4. Commit: `chore: release v{X.Y.Z}`.
5. Tag: `git tag -s v{X.Y.Z} -m "Release v{X.Y.Z}"` (GPG-signed).
6. Push: `git push origin v{X.Y.Z}`.
7. CI runs the `test-release.yml` workflow.
8. On green: create GitHub Release with the CHANGELOG entry.

(`CHANGELOG.md` not yet committed; create on first release.)

---

## Reporting issues

For security vulnerabilities, see `SECURITY.md` — DO NOT open public issues.

For everything else: open a GitHub Issue with:
- Reproduction steps
- Expected vs actual behaviour
- Environment (OS, Python version, Docker version)
- Relevant logs (PII-redacted)
- Tag the issue with the relevant phase (`phase/4.5`, etc.) + type (`bug`, `feature`, `question`)

---

## Code of conduct

Be respectful. Disagreements happen; resolve them on merits. Personal attacks, harassment, or discriminatory language are not tolerated. Project maintainers will enforce.
