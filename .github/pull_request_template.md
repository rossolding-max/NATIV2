<!--
Branch naming + commit conventions per CONTRIBUTING.md.
Allowed prefixes: feature/, fix/, chore/, refactor/, test/, spec/, docs/, perf/, style/
-->

## Summary

<!-- 1-3 sentences: what changed and why. Focus on WHY. -->

## Milestone / Scope

- [ ] Targets milestone: M__ (see `docs/project_plan.md`)
- [ ] Linked workflow doc(s): `docs/...`
- [ ] Schema change? (if yes: follow `CLAUDE.md` § "Schema discipline")

## Changes

- 
- 

## Test plan

- [ ] Unit tests added / updated
- [ ] Integration tests added / updated (if it touches DB, API, or vendor)
- [ ] State-machine tests added / updated (if it changes a state machine)
- [ ] LLM-eval cassettes recorded (if it touches an agent prompt)
- [ ] Manual testing: `just up && just test` green locally

## Risk

<!-- Breaking changes, vendor dependencies, cost implications, schema migrations. -->

## Docs

- [ ] Workflow doc updated (`docs/{phase}_workflow.md`)
- [ ] `docs/data_lineage.md` updated (if cross-phase data flow changes)
- [ ] `CLAUDE.md` updated (if a locked decision changes)
