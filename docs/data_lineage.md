# Data Lineage

**Status:** Locked v0.1 (2026-05-26). The wiring diagram for the system — every cross-phase data flow with concrete schema paths.

**Purpose:** detect orphan fields (nobody reads) + missing dependencies (consumer expects data nobody produces) + drift between consumer expectations and producer outputs. Single source of truth for "where does this field come from / where does it go?" Pairs with `docs/architecture.md` (the "what") + `docs/project_plan.md` (the "how").

## Conventions

- **Schema paths** use JSONPath-style notation: `talent.platforms[].api_credentials.access_token_ref` (dotted; `[]` for arrays).
- **Phase identifiers:** P0 / P1 / P1.5 / P2 / P3a / P3b / P4 / P4.5 / P4.6 / P4.7 / P4.8 / P4.9 / **A** (auto-archive).
- **Trigger event:** what causes the write or read (e.g. `agent_initiated`, `cron`, `state_transition: X→Y`, `webhook: Smartlead.reply`, `gate_pass: commercial`).
- **Mode:** how data moves — `write` (producer writes the field), `read` (consumer reads it live), `snapshot` (producer reads + freezes a copy at moment-in-time), `compute` (derived from other fields), `FK` (foreign-key reference; pointer not copy).

---

## §1 Phase-to-phase flow graph (master table)

Every cross-phase data flow. Grouped by consumer phase for easier "where does this consume from?" lookup.

### → Consuming P0 (Agency Setup)
No upstream phases — P0 is the root. All inputs are user-supplied via UI.

### → Consuming P1 (Talent Onboarding)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P0 | `agency_profile.default_commission_rate` | Default for talent's `commission_override` form prefill | read | Step 5 questionnaire |
| P0 | `agency_profile.default_commission_model` | Default for talent's `commission_override` form prefill | read | Step 5 questionnaire |
| P0 | `agency_profile.invoice_template.payment_instructions_markdown` | Preview shown when asking if talent needs `invoice_payment_override` | read | Step 5 questionnaire |
| static | `data/industries.json` | `talent.platforms[]` industry classification + `disclosure_defaults.style` country-default | read | Step 1 seed |
| static | `data/niches.json` | `talent.content_niches[]` options | read | Step 1 seed |
| static | `data/contract_template_starters/` (S3) | Source for talent's `contract_template.markdown_source` adoption | read | Step 7.5 |

### → Consuming P1.5 (Brand Deals capture)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P1 | `talent.id` | FK to associate brand_deal rows | FK | All ingestion paths |
| static | `brand_industry_map.brands[].name` | Resolve `brand_id` slug from brand display name | read | All ingestion paths |
| static | `data/industries.json` | Verify `industry_id` exists | read | All ingestion paths |

### → Consuming P2 (Brand Discovery)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P1 | `talent.content_niches[]` | Niche-driven industry mapping (Searches 5-7) | read | `discovery_run` cron |
| P1 | `talent.audience_demographics.*` | Demographic-bridge search (Search 8) | read | `discovery_run` cron |
| P1 | `talent.brand_preferences.blocked_industries[]` | Hard-filter exclusion | read | `discovery_run` cron |
| P1 | `talent.brand_preferences.preferred_industries[]` | Score boost (preferred_industry source) | read | `discovery_run` cron |
| P1 | `talent.brand_preferences.values_red_lines[]` | Warning flag (values_red_line_neutral) | read | `discovery_run` cron |
| P1 | `talent.brand_preferences.active_exclusivities[]` | Block competitor brands during exclusivity window | read | `discovery_run` cron |
| P1 | `talent.previous_brands[]` | Search 1 re-engagement candidates | read | `discovery_run` cron |
| P1 | `talent.similar_talent[]` | Searches 2/4 (worked-with + competitor-of-similar) | read | `discovery_run` cron |
| P1.5 | `brand_deal.deals[].ended_at + .cool_down_override_days + .do_not_recontact + .last_re_engagement_pitch_date` | Search 1 re-engagement timing + de-spam | read | `discovery_run` cron |
| static | `brand_industry_map.brands[]` (all fields) | Brand metadata for ranking + qualification + snapshotting | read | `discovery_run` cron |
| static | `data/industries.json` (incl. parent/sibling relationships, demographics) | Industry expansion (primary/secondary/tertiary) | read | `discovery_run` cron |
| static | `data/niches.json` | Niche → industry mapping | read | `discovery_run` cron |

### → Consuming P3a (Contact CRM)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P2 | `brand_candidates.candidates[] WHERE tier=primary AND qualification.tier IN [qualified, speculative]` | Target brand list for enrichment | read | Auto on P2 completion |
| static | `brand_industry_map.brands[].domain` | Apollo employee search seed | read | Per-brand enrichment |
| static | `brand_industry_map.brands[].typical_campaign_tier + .headcount` | Scaling `decision_role` classification (CMO at megabrand → influencer; IM Manager → buyer) | read | Per-contact classification |

### → Consuming P3b (Outreach)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P1 | `talent.*` (full profile) | Personalization fields in pitch generation | read | Per-step LLM generation |
| P1.5 | `brand_deal.deals[]` | Citation material in AI-generated pitches | read | Per-step LLM generation |
| P2 | `brand_candidates.candidates[]` | Brand list for outreach campaigns | read | Enrollment creation |
| P3a | `brand_contact.contacts[]` | Recipient details + decision_role per pitch | read | Enrollment creation |
| P3a | `brand_contact.contacts[].do_not_contact + .opt_out_at` | DNC enforcement | read | Enrollment creation |
| P3a | `brand_contact.contacts[].decision_role` | Drives template selection (buyer / influencer / champion / gatekeeper variants) | read | Template selection |
| P0 | `agency_profile.sending_mailboxes[0]` | Smartlead campaign source | read | Smartlead push |
| P0 | `agency_profile.default_signature_template` | Email footer (CAN-SPAM physical address) | read | Per-step LLM generation |
| P0 | `agency_profile.unsubscribe_email` | List-Unsubscribe header | read | Per-step LLM generation |
| static | `data/pitch_templates.json` | Step sequence + intent per step + branching rules | read | Per-enrollment |
| static | `data/pitch_angles.json` | Top-scoring angles for (brand×niche) → seed LLM prompt | read | Per-step LLM generation |
| static | `brand_industry_map.brands[].*` | Brand context for prompt | read | Per-step LLM generation |
| memo | scope=brand_relationship/objection_handler matching brand_id | Past brand interactions inform pitch | read | Per-step LLM generation |

### → Consuming P4 (Deal Lifecycle creation)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P3b | `pitch_enrollment.outcomeClassification.outcome = "interested"` | Trigger to create new deal in LEAD | webhook | Smartlead reply classified |
| P3b | `pitch_enrollment.enrollment_id` | Set `deal.originating_enrollment_id` | FK | Deal creation |
| P3b | `pitch_enrollment.outcomeClassification.extracted_signals.asked_for_meeting` | Pre-seed `deal.substage = initial_call_scheduled` if true | read | Deal creation |
| P3b | `pitch_enrollment.talent_id + .brand_id + .contact_id` | Populate `deal.talent_id + .brand_id + .primary_contact_id` | snapshot | Deal creation |
| P3a | `brand_contact.contacts[primary_contact_id].decision_role` | Snapshot to `deal.originating_decision_role_at_pitch` (anchors won-by-role analytics independent of future contact role changes) | snapshot | Deal creation |

### → Consuming P4.5 (Discovery Prep Pack)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4 | `deal.*` (full record incl. originating_enrollment_id) | Full deal context for prep pack generation | read | substage transition `*→initial_call_scheduled` |
| P3b | `pitch_enrollment.*` (via originating_enrollment_id) | Originating reply text as anchor citation in briefing notes | read | Pack gen |
| P1 | `talent.*` (full profile) | talent_overview / audience_snapshot / recent_work slides | read (bundle) | Pack gen |
| P1.5 | `brand_deal.deals[]` filtered to comparable industry/scope | Top 5 comparable case studies for recent_work slide + commercial_range computation | read (bundle) | Pack gen |
| P2 | `brand_candidates.candidates[brand_id]` | Brand qualification rationale for fit hypothesis | read | Pack gen |
| P3a | `brand_contact.contacts[primary_contact_id]` | About-the-contact section incl. decision_role + pitch_history | read (bundle) | Pack gen |
| static | `brand_industry_map.brands[brand_id]` | About-the-brand section base data | read (bundle) | Pack gen |
| static | `data/pitch_angles.json` filtered by brand×niche | Top-scoring angles seed fit_angle slide | read | Pack gen |
| P0 | `agency_profile.branding.*` | Logo + colors + fonts in renderer | read | Render stage |
| vendor (Exa) | external research | recent brand campaigns/news/competitor landscape | read | Pack gen Stage research |
| memo | scope=brand_relationship/industry_pattern matching brand_id OR industry_id | Past insights inform briefing | read | Pack gen |

### → Consuming P4.6 (Proposal Pack)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4.5 | `discovery_prep_pack.*` via `deal.lead.latest_prep_pack_id` | Forked slides (talent_overview + audience_snapshot + recent_work + fit_angle) | FK + selective read | Pack gen Stage D |
| P4.5 | `discovery_prep_pack.slides[i].slide_id` | Captured on forked slides as `forked_from_prep_slide_id` for traceability | FK | Pack gen Stage D |
| P4 | `deal.*` (full record) | Deal context | read (bundle) | Pack gen |
| P4 | `deal.lead.discovery_call_notes + brief_text` | Source for Stage B debrief extraction | read | Stage B |
| User | Agent-uploaded files (briefs, notes, transcripts) | `proposal_pack.context_artefacts[]` ingestion via extractor subagent | upload → parse | Stage A |
| P1 | `talent.*` | Talent overview + working_terms defaults inform commercial proposal | read (bundle) | Pack gen |
| P1.5 | `brand_deal.deals[]` filtered | Comparable fees inform commercial_range + recommendation slide | read (bundle) | Stage C |
| P2 | `brand_candidates.candidates[brand_id].legal_entity_override` (if set) | Brand legal entity preview (Tier 2 O4 proactive capture) | read | Pack gen |
| static | `brand_industry_map.brands[brand_id].legal_entity` (if set) | Brand legal entity fallback | read | Pack gen |
| static | `data/pitch_angles.json` | Recommendation slide angle | read | Pack gen |
| static | `brand_industry_map.brands[brand_id].*` | Brand context | read (bundle) | Pack gen |
| P0 | `agency_profile.branding.*` | Renderer branding | read | Render stage |
| memo | scope=brand_relationship/negotiation_pattern/objection_handler matching brand_id | Past negotiations inform proposal | read | Pack gen |

### → Consuming P4.7 (Contract Pack)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4 | `deal.proposal.*` (canonical commercials post commercial gate) | Source for fee_usd + deliverables + usage_rights + exclusivity + additional_compensation + payment_terms merge fields | read | Stage B merge extraction |
| P4 | `deal.lead.discovery_debrief` (populated by P4.6) | Informs conditional clause evaluation (e.g. EU brand → GDPR clause) | snapshot | Stage C clause eval |
| P4 | `deal.delivery.campaign_hashtags[]` | `{{campaign_hashtags_formatted}}` merge field (disclosure clause section 7.5) | read | Stage B merge extraction |
| P4.6 | `proposal_pack.*` (latest via deal.proposal.latest_proposal_pack_id) | Context_snapshot reference + commercial values verification | FK + snapshot | Pack gen |
| P1 | `talent.contract_template.markdown_source + merge_field_definitions + clause_applicability_rules + narrative_placeholders + default_governing_law + default_jurisdiction` | Template skeleton + rules driving the entire pipeline | read | Pack gen |
| P1 | `talent.contract_template.legal_reviewer_id` | Default reviewer identity for legal_review gate | read | Pack gen Stage F |
| P1 | `talent.billing_entity.legal_name + .country + .tax_id + .address` | Talent legal entity merge fields (FROM party) | snapshot | Stage B merge extraction |
| P1 | `talent.working_terms.default_usage_rights + .default_usage_duration_days + .revisions_included` | Default merge field values where deal-specific values absent | read | Stage B merge extraction |
| P1 | `talent.disclosure_defaults.style` | `{{disclosure_style}}` merge field (Section 7.5 FTC/ASA clause — O5 wiring) | read | Stage B merge extraction |
| P2 | `brand_candidate.legal_entity_override` (if set) | Brand legal entity merge fields (TO party) | snapshot | Stage B merge extraction |
| static | `brand_industry_map.brands[brand_id].legal_entity` | Brand legal entity fallback if no override | snapshot | Stage B merge extraction |
| User | Brand legal info uploads (W-9, registration, redlines) | `contract_pack.context_artefacts[]` | upload → parse | Stage A |
| P0 | `agency_profile.name + .billing_entity.* + .branding` | Agency party identification + branding | read | Pack gen |
| memo | scope=brand_relationship/negotiation_pattern matching brand_id | Past contract patterns + redlines | read | Pack gen |

### → Consuming P4.8 (Invoice Pipeline — Detection layer)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4 | `deal.delivery.posting_schedule[]` (unmatched entries) | List of expected posts to find | read | `poll_phase_4_8_detection_*` cron |
| P4 | `deal.delivery.campaign_hashtags[]` | +20pt match signal (G2 fix) | read | Match scoring |
| P4 | `deal.proposal.deliverables[].format` | +10pt content_type match signal | read | Match scoring |
| P1 | `talent.platforms[].api_credentials.access_token_ref` (decrypt) | Auth to Meta Graph + TikTok APIs | read (decrypt) | Cron poll |
| static | `brand_industry_map.brands[brand_id].social_handles.{platform}` | +30pt brand_handle match signal (G1 fix) | read | Match scoring |

### → Consuming P4.8 (Invoice Pipeline — Generation layer)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4.7 | `contract_pack.commercial_proposal.llm_proposed.payment_terms` | LLM-parse source for `deal.close.invoice_schedule[]` (one-time agent gate on contract execution) | read | `contract_executed_at` transition |
| P4 | `deal.close.invoice_schedule[]` (per entry, when trigger met) | Schedule entry fires its own invoice_pack | read | Trigger condition met |
| P4 | `deal.proposal.fee_usd + .deliverables[]` | Amount computation + line items | read | Per-invoice gen |
| P1 | `talent.billing_entity.*` | FROM party (when commission_model = agency_invoices_brand_pays_talent_net) — falls through to agency.billing_entity instead | read | Per-invoice gen |
| P1 | `talent.commission_override.commission_rate + .commission_model` | Per-talent override of agency defaults | read | Per-invoice gen |
| P1 | `talent.invoice_payment_override.payment_instructions_markdown + .preferred_payment_method` | Payment routing override | read | Per-invoice gen |
| P0 | `agency_profile.invoice_template.*` (markdown + numbering + tax + footer) | Template skeleton + atomic invoice number sequence | read + atomic increment | Per-invoice gen |
| P0 | `agency_profile.default_commission_rate + .default_commission_model` | Fallback commission values | read | Per-invoice gen |
| P0 | `agency_profile.billing_entity.*` | FROM party when commission_model = agency_invoices_brand_pays_talent_net | read | Per-invoice gen |
| P4.7 | `contract_pack.context_snapshot.brand_legal_entity_at_gen.*` | TO party on every invoice | snapshot | Per-invoice gen |
| P4 | `deal.delivery.posting_schedule[]` with `posted_at` set | `context_snapshot.matched_posts[]` for close-trigger invoices | snapshot | Per-invoice gen |

### → Consuming P4.9 (Performance Report — KPI capture layer)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4 | `deal.delivery.posting_schedule[]` with `posted_at` set | List of post URLs to poll Insights APIs for | read | `poll_phase_4_9_kpi_capture` daily cron |
| P4 | `deal.delivery.performance_capture_window_starts_at + _ends_at` | Window bounds (skip polling after end) | read | Daily cron |
| P1 | `talent.platforms[].api_credentials.access_token_ref` | Auth to Insights APIs | read (decrypt) | Daily cron |

### → Consuming P4.9 (Performance Report — Generation layer)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4 | `deal.delivery.interim_kpi_snapshots[]` | Source for per_post_kpis + aggregate kpis (most recent per post) | read | Stage A aggregate |
| P4 | `deal.delivery.posting_schedule[]` | Per-post metadata | read | Pack gen |
| P4 | `deal.delivery.performance_capture_window_*` | Frozen in context_snapshot | snapshot | Pack gen |
| P4 | `deal.proposal.fee_usd + .deliverables[]` | CPM/CPE/CPV computation | read | Stage A |
| P4 | `deal.lead.discovery_debrief.objectives_heard[]` | vs_brand_stated_targets benchmark source | snapshot | Stage B benchmarks |
| P1.5 | `brand_deal.deals[]` filtered to same industry+campaign_type | vs_talent_historical benchmark (averaged kpis) | read | Stage B benchmarks |
| static | `data/industry_kpi_benchmarks.json` (v2; absent v0.1) | vs_industry benchmark | read | Stage B benchmarks |
| P4.7 | `contract_pack.context_snapshot.brand_legal_entity_at_gen.*` | Brand identification on report cover | snapshot | Pack gen |
| P4.6 | `proposal_pack.*` (latest via deal.proposal.latest_proposal_pack_id) | Frozen in context_snapshot | snapshot | Pack gen |
| P0 | `agency_profile.branding.*` | Report cover + footer | read | Render |
| memo | scope=kpi_pattern/industry_pattern matching brand_id OR industry_id | Past KPI insights | read | Pack gen |

### → Consuming A (Auto-archive — closes the loop)
| Producer | Producer path | Consumer use | Mode | Trigger |
|---|---|---|---|---|
| P4.8 | `deal.close.all_invoices_paid_at` (set when all invoice_pack.payment_state.status = paid) | Gate condition 1 | read | `auto_archive_trigger_check` cron |
| P4.9 | `deal.close.final_kpis` (set on report send) | Gate condition 2 + becomes new brand_deal.kpis verbatim | snapshot | `auto_archive_trigger_check` cron |
| P4.9 | `deal.close.final_performance_report_attachment_id` (set on report send) | Gate condition 3 | read | `auto_archive_trigger_check` cron |
| P4 | `deal.*` (full record) | Source for new brand_deal record creation | read | Archive fire |
| P4 | `deal.originating_enrollment_id` | New brand_deal.originated_from_pitch_enrollment_id | FK | Archive fire |
| P4 | `deal.deal_id` | New brand_deal.archived_from_deal_id (bidirectional with deal.close.archived_to_brand_deal_id) | FK | Archive fire |

---

## §2 Per-phase IO catalog

For each phase: inputs (with source path) + outputs (with target path) + computed fields (with derivation rule).

### Phase 0 — Agency Setup

**Inputs:**
| Source | Path | Used for |
|---|---|---|
| User UI | (form input) | All `agency_profile.*` fields |

**Outputs:**
| Target | Path | When set |
|---|---|---|
| `agency_profile` | `.agency_id` | Step 7 final save |
| `agency_profile` | `.name + .domain + .website_url + .company_address + .unsubscribe_email` | Step 1 |
| `agency_profile` | `.branding.*` | Step 1.5 |
| `agency_profile` | `.agents[]` | Step 2 |
| `agency_profile` | `.sending_mailboxes[]` | Step 4 |
| `agency_profile` | `.default_signature_template` | Step 5 |
| `agency_profile` | `.invoice_template.*` | Step 5.5 |
| `agency_profile` | `.default_commission_rate + .default_commission_model` | Step 5.5 |
| `agency_profile` | `.billing_entity.*` | Step 5 / 5.5 |
| `agency_profile` | `.created_at + .updated_at` | Step 7 |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `agency_profile.sending_mailboxes[0].warmup_status` | Smartlead webhook → state machine (pending → in_progress → complete) | Continuously during Step 6 |
| `agency_profile.invoice_template.invoice_number_sequence` | Initialised to 1 (or imported value); atomic increment per invoice generation | Per P4.8 invoice gen |

### Phase 1 — Talent Onboarding

**Inputs:**
| Source | Path | Used for |
|---|---|---|
| P0 | `agency_profile.default_commission_rate + .default_commission_model` | Defaults shown in Step 5 commission prompt |
| P0 | `agency_profile.invoice_template.payment_instructions_markdown` | Preview when asking about payment override |
| static | `data/industries.json` | Industry classification options + disclosure_style country default |
| static | `data/niches.json` | content_niches options |
| static | S3: `agencies/{agency_id}/contract_template_starters/` | Source for talent's contract template Step 7.5 |
| Platform oAuth (Meta, TikTok, YouTube, etc.) | Tokens + scopes | `talent.platforms[].api_credentials` |
| User UI | (form input) | Everything else |
| Media pack upload | PDF/PPTX/PNG/JPG | LLM extraction → `talent.previous_brands[]` + `audience_demographics` + `rate_card` seed |
| AI research (Step 9 background) | Web search | Similar talent research |

**Outputs:**
| Target | Path | When |
|---|---|---|
| `talent` | All `.*` fields per `schemas/talent.schema.json` | Step 8 final save |
| `talent` | `.platforms[].api_credentials.access_token_ref` | Step 2 (encrypted in Postgres via pgcrypto) |
| `talent` | `.contract_template.*` | Step 7.5 |
| `talent` | `.commission_override.*` | Step 5 (only if non-default) |
| `talent` | `.invoice_payment_override.*` | Step 5 (only if non-default) |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `talent.platforms[].stats.last_updated` | Set on every API refresh | Step 2 connection + weekly `talent_stats_refresh` cron |
| `talent.similar_talent[].research.last_researched_at` | Set on background AI research completion | Step 9 |

### Phase 1.5 — Brand Deals

**Inputs:**
| Source | Path | Used for |
|---|---|---|
| P1 | `talent.id` | FK |
| static | `brand_industry_map.brands[].name → brand_id` | Brand resolution |
| static | `data/industries.json` | industry_id validation |
| Media pack | (parsed text) | Path 1 — AI extraction |
| Step 5 questionnaire | (form input) | Path 2 — guided entry |
| Platform Insights API (manual pull) | KPI data | Honesty-floor KPI population |

**Outputs:**
| Target | Path | When |
|---|---|---|
| `brand_deal.deals[]` | All `.*` per deal per `schemas/brand_deal.schema.json` | Per ingestion |
| `brand_deal.deals[].main_brand_contact_id` | FK to brand_contact (warm-intro source) | When captured |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `brand_deal.deals[].renewal_eligibility_date` | `ended_at + cool_down_override_days (or default 180)` | On `ended_at` or `cool_down_override_days` change |
| `brand_deal.deals[].kpis.cpm_usd` | `(fee_usd / impressions.value) × 1000` if both populated | On either field change |
| `brand_deal.deals[].kpis.cpe_usd` | `fee_usd / engagement_total.value` if both populated | On either field change |
| `brand_deal.deals[].kpis.ctr_pct` | `(link_clicks.value / impressions.value) × 100` if both populated | On either field change |

### Phase 2 — Brand Discovery

**Inputs:** see § 1 master table for the full list (16 inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `brand_candidates` | `.candidates[]` | Per discovery run (rewritten) |
| `brand_candidates` | `.blocked[]` (policy-filtered brands) | Per discovery run |
| `brand_candidates` | `.stats.*` (per-tier counts) | Per discovery run |
| `brand_candidates` | `.run_metadata.*` (durations, errors, writebacks) | Per discovery run |
| `brand_industry_map` | New entries from Search 15/16 growth loop | Per discovery run (cumulative) |
| `brand_industry_map.brands[].social_handles` | Captured during enrichment | Per discovery run (cumulative — G1 fix) |
| `brand_industry_map.brands[].legal_entity` | Captured opportunistically | Per discovery run (cumulative) |
| `brand_candidates.candidates[].first_surfaced_at + .last_surfaced_at` | Set/updated on each run | Per discovery run |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `brand_candidates.candidates[].score` | Sum of `sources[].weight`, capped 0-1 | Per discovery run |
| `brand_candidates.candidates[].tier` | Score thresholds → re-engage / primary / secondary / tertiary | Per discovery run |
| `brand_candidates.candidates[].qualification.score` | Sum of `qualification.signals[].weight`, capped 0-1 | Per discovery run |
| `brand_candidates.candidates[].qualification.tier` | Score thresholds → qualified / speculative / unqualified | Per discovery run |
| `brand_candidates.candidates[].qualification_filtered` | `qualification.score < threshold_applied` | Per discovery run |
| `brand_candidates.candidates[].found_in_searches` | `sources.length` | Per discovery run |
| `brand_candidates.candidates[].last_seen_in_searches` | Subset of sources from latest run only | Per discovery run |

**Preserved (NOT overwritten on re-run):**
- `brand_candidates.candidates[].status`
- `.assigned_to`
- `.user_notes`
- `.pitch_history[]` (legacy index — superseded by pitch_enrollment FK in v0.2)
- `.legal_entity_override` (O4 capture)

### Phase 3a — Contact CRM

**Inputs:**
| Source | Path | Used for |
|---|---|---|
| P2 | `brand_candidates.candidates[] WHERE tier=primary AND qualification.tier ∈ [qualified, speculative]` | Target brand list |
| static | `brand_industry_map.brands[].domain` | Apollo seed |
| static | `brand_industry_map.brands[].typical_campaign_tier + .headcount + .revenue` | decision_role scaling |
| Apollo API | Per-domain people search | Contact discovery |
| LinkedIn API | Profile + last_activity | Enrichment |
| Exa | Web search backup | Enrichment fallback |
| Hunter (v2) | Email verification | Email status |

**Outputs:**
| Target | Path | When |
|---|---|---|
| `brand_contact.contacts[]` | All `.*` per contact per `schemas/brand_contact.schema.json` | Per enrichment run |
| `brand_contact.contacts[].decision_role + .decision_role_rationale + .decision_authority_size_band` | LLM classification | Per enrichment run |
| `brand_contact.contacts[].qualification.*` | Signal-based scoring | Per enrichment run |
| `brand_contact.contacts[].do_not_contact + .opt_out_at` | DNC honour | On unsubscribe webhook or manual |
| `brand_contact.contacts[].first_discovered_at + .last_verified_at` | Lifecycle timestamps | Per enrichment run |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `brand_contact.contacts[].qualification.score` | Sum of signals[].weight, capped 0-1 | Per enrichment run |
| `brand_contact.contacts[].qualification.tier` | Score thresholds | Per enrichment run |
| `brand_contact.contacts[].confidence` | Weighted average across populated fields' source confidences | Per enrichment run |
| `brand_contact.contacts[].decision_authority_size_band` | seniority + brand_size combined heuristic | Per LLM classification |

**Preserved (NOT overwritten):** `.pitch_history[]` + `.tags + .notes + .champion_for_talents`

### Phase 3b — Outreach

**Inputs:** see § 1 master table (12+ inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `pitch_enrollment` | All `.*` per (talent, contact) per `schemas/pitch_enrollment.schema.json` | Per enrollment |
| `pitch_enrollment.steps[].generation_meta.*` | Full provenance (model, tokens, angles_used, prompt_hash) | Per LLM generation |
| `pitch_enrollment.steps[].engagement_events[]` | From Smartlead webhooks | Per webhook |
| `pitch_enrollment.steps[].outcome_classification.*` | LLM classification | On reply |
| `pitch_enrollment.created_deal_id` | FK to spawned deal (G3 bidirectional fix) | On `interested` classification |
| `brand_contact.contacts[].pitch_history[]` | Denormalised summary index with `enrollment_id` FK | Per enrollment + state transition |
| `brand_candidate.candidates[].pitch_history[]` | Legacy summary (v0.2 deprecation candidate) | Per enrollment |
| `brand_candidate.candidates[].status` | Updates on enrollment state changes (denormalised mirror) | Per enrollment state transition |
| `deal.*` | NEW deal created on `interested` reply | Reply classification webhook |
| `deal.originating_enrollment_id` | FK back to enrollment | Deal creation |
| `deal.originating_decision_role_at_pitch` | Snapshot of contact's decision_role | Deal creation |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `pitch_enrollment.steps[].engagement_summary.*` | Aggregated over `.engagement_events[]` | Per webhook arrival |
| `pitch_enrollment.steps[].engagement_summary.human_opens` | Excludes `likely_mpp: true` events | Per webhook arrival |
| `pitch_enrollment.steps[].engagement_summary.time_to_first_human_open_seconds` | first_human_open_at - sent_at | Per webhook arrival |
| `brand_contact.contacts[].pitch_history[].outcome` | Derived from `pitch_enrollment.outcomeClassification.outcome` via documented mapping (interested → replied_interested; etc.) | Per enrollment state transition |

### Phase 4 — Deal Lifecycle

**Inputs:** see § 1 master table (creation inputs) + the per-stage transitions consume from P4.5/4.6/4.7/4.8/4.9 outputs.

**Outputs:**
| Target | Path | When |
|---|---|---|
| `deal.deal_id + .talent_id + .brand_id + .primary_contact_id + .assigned_agent_id + .originating_*` | Creation | On `interested` reply |
| `deal.stage + .substage + .is_terminal + .is_won + .stage_history[]` | State transitions | Per agent action |
| `deal.next_action + .next_action_due_at` | Auto-set on transitions + reminder cron | Per transition + daily cron |
| `deal.expected_value_usd + .expected_close_date` | Agent input + estimate update | Manual + per LLM suggestion |
| `deal.actual_final_value_usd` | Set at archive | A trigger |
| `deal.loss.*` | Set on terminal-but-lost | Per substage → lost/disqualified/killed/contract_failed |
| `deal.lead.*` | Captured during LEAD stage | Per substage transition + P4.5/4.6 writes |
| `deal.proposal.*` | Captured during PROPOSAL stage | Per substage transition + P4.6 writes |
| `deal.contract.*` | Captured during CONTRACT stage | Per substage transition + P4.7 writes |
| `deal.delivery.*` | Captured during DELIVERY stage | Per substage transition + P4.8 detection writes + P4.9 KPI cron writes |
| `deal.close.*` | Captured during CLOSE stage | Per substage transition + P4.8/4.9 writes + A archive write |
| `deal.attachments[] + .notes[]` | Agent uploads + free-text notes | Per agent action |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `deal.substage` (when DELIVERY is active across multiple deliverables) | "least-progressed wins" across `content_drafts[]` + `posting_schedule[]` states | Per per-deliverable state change |
| `deal.delivery.performance_capture_window_starts_at` | First `posting_schedule[].posted_at` confirmed | On first detection confirmation |
| `deal.delivery.performance_capture_window_ends_at` | Last `posting_schedule[].posted_at` + 30d (default; configurable per agency) | On last detection confirmation |
| `deal.close.all_invoices_paid_at` | MAX of `invoice_pack.payment_state.payment_received_at` across all invoice_pack rows for this deal, but only when every `invoice_schedule[]` entry has invoice_pack with `status = paid` | On every invoice payment state change |
| `deal.is_terminal + .is_won` | Substage enum membership | On substage transition |

### Phase 4.5 — Discovery Prep Pack

**Inputs:** see § 1 master table (13 inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `discovery_prep_pack` | All `.*` per version per `schemas/discovery_prep_pack.schema.json` | Per pack version gen |
| `discovery_prep_pack.context_snapshot.*` | Frozen upstream data (talent_profile_updated_at, brand_candidate_updated_at, originating_reply_text, comparable_brand_deal_ids, top_scoring_angle_ids, external_research) | Per pack version gen |
| `discovery_prep_pack.export_artifacts[]` | S3 paths to rendered HTML / PDF / md | Per render |
| `discovery_prep_pack.agent_edits[]` | Direct edit audit | Per direct edit |
| `deal.lead.discovery_prep_pack_ids[]` | Append on each new version | Per version |
| `deal.lead.latest_prep_pack_id` | Point to current is_latest=true | Per version |
| `memo.*` | Optional learnings (brand_observation, talent_learning, etc.) | Per pack gen (agent decision) |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `discovery_prep_pack.is_latest` | Exactly one per deal at a time; new version flips parent to false | Per version |
| `discovery_prep_pack.generation.llm_passes[].cost_usd` | Computed from token usage × model rate | Per LLM call |

### Phase 4.6 — Proposal Pack

**Inputs:** see § 1 master table (14 inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `proposal_pack` | All `.*` per version | Per pack version gen |
| `proposal_pack.context_artefacts[]` | Uploaded files + parsed text + LLM summary | Per Stage A |
| `proposal_pack.commercial_proposal.llm_proposed.*` | LLM-proposed deliverables/fee/usage_rights/exclusivity/timeline/exclusions/payment_terms with rationale | Per Stage C |
| `proposal_pack.commercial_proposal.confirmed_at + .confirmed_by_agent_id + .confirmed_overrides[]` | The gate event | On commercial gate confirm |
| `proposal_pack.slides[]` | Generated only after commercial gate passed | Per Stage D |
| `proposal_pack.export_artifacts[]` | S3 paths | Per Stage E render |
| `deal.lead.discovery_debrief.*` | 10 structured fields from Stage B extraction | On Stage B agent confirm |
| `deal.lead.discovery_debrief.confirmed_at + .confirmed_by_agent_id` | Confirmation event | On Stage B agent confirm |
| `deal.proposal.deliverables[] + .fee_usd + .usage_rights_granted + .exclusivity + .additional_compensation + payment_terms` | Canonical commercial values | On commercial gate confirm |
| `deal.proposal.commercial_confirmed_at + .commercial_confirmed_by_agent_id` | The gate event mirrored | On commercial gate confirm |
| `deal.proposal.proposal_pack_ids[] + .latest_proposal_pack_id` | FK list + latest pointer | Per version |
| `deal.proposal.negotiation_log[].proposal_pack_version` | Bidirectional link | Per negotiation event |
| `memo.*` | Negotiation patterns, brand observations, objection handlers | Per pack gen |

### Phase 4.7 — Contract Pack

**Inputs:** see § 1 master table (15 inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `contract_pack` | All `.*` per version | Per pack version gen |
| `contract_pack.context_artefacts[]` | Brand legal info, brand-requested clauses, prior contracts, redlines | Per Stage A |
| `contract_pack.merge_field_values[]` | Per-field {value, source, confidence, needs_review} | Per Stage B |
| `contract_pack.conditional_clause_decisions[]` | Per clause: include/exclude + applicability_rationale | Per Stage C |
| `contract_pack.narrative_sections[]` | LLM-drafted with declared sources + word_count | Per Stage D |
| `contract_pack.composed_markdown` | Canonical contract source-of-truth | Per Stage E |
| `contract_pack.legal_review.*` | The gate state — required, reviewer_id, blocking_issues[], approved_at, approved_by_agent_id, previous_approvals[] | Per Stage F |
| `contract_pack.export_artifacts[]` | S3 paths to MD + DOCX + PDF (status: blocked_by_legal_gate until approved) | Per Stage G render |
| `deal.contract.contract_pack_ids[] + .latest_contract_pack_id` | FK list + latest pointer | Per version |
| `deal.contract.legal_reviewer_id` | Default from talent.contract_template; per-deal override | On pack gen |
| `deal.contract.draft_contract_attachment_id` | Auto-populated from latest pack's contract.pdf | On Stage G render |
| `deal.contract.amendment_log[]` (post-execution) | With `contract_pack_version` bidirectional link (G5 fix) | On amendment_request regen |
| `memo.*` | Brand observations, negotiation patterns | Per pack gen |

### Phase 4.8 — Invoice Pipeline (Detection)

**Inputs:** see § 1 master table.

**Outputs:**
| Target | Path | When |
|---|---|---|
| `deal.delivery.posting_schedule[i].posted_at + .post_url` | On agent confirmation | Per match confirmation |
| `deal.delivery.posting_schedule[i].posted_detection.method + .detected_at + .match_score + .match_signals + .candidate_post_ids_considered + .agent_confirmed_at + .agent_confirmed_by + .agent_rejection_note` | Detection provenance | Per detection cycle |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `posted_detection.match_score` | Sum of signal points (time_window 40 + brand_handle 30 + campaign_hashtag 20 + content_type 10) | Per scoring |

### Phase 4.8 — Invoice Pipeline (Generation)

**Inputs:** see § 1 master table.

**Outputs:**
| Target | Path | When |
|---|---|---|
| `invoice_pack` | All `.*` per (deal, sequence, version) | Per invoice gen |
| `invoice_pack.context_snapshot.*` | Frozen contract_pack_id + talent_billing + brand_legal + schedule_entry + matched_posts | Per gen |
| `invoice_pack.merge_field_values[]` | Deterministic extraction with provenance | Per gen |
| `invoice_pack.line_items[]` | Deliverable-mapped line items (LLM-drafted descriptions optional) | Per gen |
| `invoice_pack.amounts.*` | Subtotal + tax + total + currency + fx_rate | Per gen |
| `invoice_pack.composed_markdown` | Canonical | Per Stage C |
| `invoice_pack.export_artifacts[]` (md + pdf) | S3 paths | Per render |
| `invoice_pack.agent_review.sent_at + .sent_by_agent_id + .send_method + .sent_to_email` | On agent send | Per send action |
| `invoice_pack.payment_state.*` | Lifecycle (draft → sent → paid/overdue/etc.) | Per state change |
| `invoice_pack.payment_reminder_log[]` | Overdue cron + agent follow-up audit | Per cron + agent action |
| `deal.close.invoice_schedule[]` | LLM-parsed from contract.payment_terms; one-time agent gate | On `contract_executed_at` transition |
| `deal.close.invoice_schedule[i].fired_at + .invoice_pack_id` | When trigger met + pack generated | Per trigger fire |
| `deal.close.invoice_schedule[i].schedule_confirmed_at + .schedule_confirmed_by_agent_id` | One-time agent gate event | On schedule confirm |
| `deal.close.invoice_pack_ids[]` | Flat list of all versions | Per version |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `invoice_pack.amounts.subtotal_usd` | Sum of `line_items[].amount_usd` | Per gen |
| `invoice_pack.amounts.tax_amount_usd` | subtotal × tax_rate (if tax_handling != none) | Per gen |
| `invoice_pack.amounts.total_usd` | subtotal + tax_amount | Per gen |
| `invoice_pack.payment_state.due_at` | `agent_review.sent_at + (schedule_entry.payment_terms_days OR agency.default_payment_terms_days)` | On send |
| `invoice_pack.payment_state.status` (overdue) | `due_at < now AND status = sent` | Per overdue cron |
| `deal.close.invoice_schedule[i].amount_usd` | `deal.proposal.fee_usd × (percentage / 100)` | On schedule confirm |
| Invoice FROM party (commission resolution) | If `talent.commission_override.commission_model` set, use it; else `agency_profile.default_commission_model`. Maps to FROM = agency or talent per model. | Per gen |

### Phase 4.9 — Performance Report (KPI capture)

**Inputs:** see § 1 master table.

**Outputs:**
| Target | Path | When |
|---|---|---|
| `deal.delivery.interim_kpi_snapshots[]` | Per-post × per-day snapshot | Per daily cron |

### Phase 4.9 — Performance Report (Generation)

**Inputs:** see § 1 master table (12 inputs).

**Outputs:**
| Target | Path | When |
|---|---|---|
| `performance_report_pack` | All `.*` per version | Per pack version gen |
| `performance_report_pack.kpis.*` | Aggregated metrics in kpiMetric shape | Per Stage A |
| `performance_report_pack.per_post_kpis[]` | Per-deliverable breakdown | Per Stage A |
| `performance_report_pack.benchmark_comparisons.*` (3 sub-blocks) | vs_industry / vs_talent_historical / vs_brand_stated_targets | Per Stage B |
| `performance_report_pack.narrative_sections[]` | Executive_summary + what_worked + learnings + (optional) audience_resonance | Per Stage C |
| `performance_report_pack.composed_markdown` | Canonical | Per Stage D |
| `performance_report_pack.export_artifacts[]` (md + pdf + optional html) | S3 paths | Per Stage E render |
| `performance_report_pack.agent_review.sent_at + .sent_by_agent_id + .send_method + .sent_to_email` | On agent send | Per send action |
| `deal.close.performance_report_pack_ids[] + .latest_performance_report_pack_id` | FK list + latest pointer | Per version |
| `deal.close.final_performance_report_attachment_id` | Auto-populated = latest pack PDF | On agent send |
| `deal.close.final_kpis` | Verbatim copy of latest pack `kpis{}` | On agent send |
| `memo.*` | kpi_pattern, industry_pattern learnings | Per pack gen |

**Computed:**
| Path | Derivation | When |
|---|---|---|
| `performance_report_pack.kpis.reach.value` | Sum of `per_post_kpis[].kpis.reach.value` (most recent snapshot per post) | Per Stage A |
| `performance_report_pack.kpis.engagement_rate_pct.value` | Weighted average: `Σ(post.engagement_total) / Σ(post.impressions) × 100` | Per Stage A |
| `performance_report_pack.benchmark_comparisons.{set}.{kpi}.delta_pct` | `((this_value - benchmark_value) / benchmark_value) × 100` | Per Stage B |
| `performance_report_pack.benchmark_comparisons.{set}.{kpi}.performance_label` | LLM-rendered from delta_pct (e.g. "2.3x category", "+29% vs talent's historical") | Per Stage B |
| `performance_report_pack.kpis.cpm_usd.value` | `(deal.proposal.fee_usd / kpis.impressions.value) × 1000` | Per Stage A |

### A — Auto-archive (loop closure)

**Inputs:** see § 1 master table.

**Outputs:**
| Target | Path | When |
|---|---|---|
| `brand_deal.deals[]` (new entry) | All `.*` per `schemas/brand_deal.schema.json` from deal data | A fire |
| `brand_deal.deals[N].kpis` | Verbatim from `deal.close.final_kpis` | A fire |
| `brand_deal.deals[N].originated_from_pitch_enrollment_id` | From `deal.originating_enrollment_id` | A fire |
| `brand_deal.deals[N].archived_from_deal_id` | From `deal.deal_id` (bidirectional) | A fire |
| `deal.close.archived_to_brand_deal_id` | New brand_deal.deals[N].deal_id (bidirectional) | A fire |
| `deal.close.archived_at` | Now | A fire |
| `deal.stage = "archived" + .substage = "archived" + .is_terminal = true + .is_won = true` | Final transition | A fire |

---

## §3 Reverse field index

For high-traffic / cross-phase fields, who writes + who reads. Surfaces orphan + missing-dependency risks.

### `talent.platforms[].api_credentials.access_token_ref`
- **Writer:** P1 Step 2 (oAuth flow)
- **Readers:** P1 stats refresh (Step 2), P4.8 detection (`poll_phase_4_8_detection_*`), P4.9 KPI capture (`poll_phase_4_9_kpi_capture`), weekly `talent_stats_refresh`
- **Storage:** pgcrypto-encrypted column in Postgres; never serialised to JSON output
- **Lifecycle:** refreshed on oAuth re-auth; expires per platform policy (Meta 60d)

### `talent.contract_template.markdown_source + .merge_field_definitions + .clause_applicability_rules + .narrative_placeholders + .default_governing_law + .default_jurisdiction + .legal_reviewer_id`
- **Writer:** P1 Step 7.5 (talent onboarding contract setup)
- **Readers:** P4.7 contract_pack (every stage)
- **Cross-phase dependency:** if absent, contract_pack generation blocks at `contract_drafting` substage with explicit error per project plan M5 skip notes
- **Versioning:** `template_version` bump on any change; `context_snapshot.template_version_used` anchors past contract_packs

### `talent.disclosure_defaults.style`
- **Writer:** P1 Step 1 (country-default) + Step 5 (questionnaire confirm)
- **Reader:** P4.7 contract_pack as `{{disclosure_style}}` merge field (Section 7.5 — O5 wiring fix)
- **Orphan risk before O5:** previously unread; now wired ✓

### `talent.commission_override.commission_rate + .commission_model`
- **Writer:** P1 Step 5 questionnaire (only if non-default)
- **Reader:** P4.8 invoice generation (FROM-party determination + sibling commission invoice scaffolding)
- **Fallback chain:** absent → use `agency_profile.default_commission_*`

### `talent.invoice_payment_override.payment_instructions_markdown + .preferred_payment_method`
- **Writer:** P1 Step 5 questionnaire (only if talent routes payment to own account)
- **Reader:** P4.8 invoice generation (payment_instructions block)
- **Fallback chain:** absent → use `agency_profile.invoice_template.payment_instructions_markdown`

### `agency_profile.branding.*` (logo, colors, fonts, tagline)
- **Writer:** P0 Step 1.5
- **Readers:** P4.5 + P4.6 + P4.7 + P4.8 + P4.9 (all renderers)
- **Discipline:** single source of truth; rebrand once → propagates to all future generations

### `agency_profile.invoice_template.invoice_number_sequence`
- **Writer:** P0 Step 5.5 (init); P4.8 generation (atomic increment)
- **Reader:** P4.8 generation (read + increment in same transaction)
- **Critical:** must be atomic via `SELECT … FOR UPDATE`; per-agency uniqueness

### `agency_profile.default_commission_rate + .default_commission_model`
- **Writer:** P0 Step 5.5
- **Reader:** P4.8 invoice generation (fallback when no talent override)

### `brand_industry_map.brands[brand_id].social_handles.{platform}`
- **Writer:** P2 brand_enrichment (G1 fix — captured during follower-count enrichment); weekly `brand_handle_refresh` cron
- **Reader:** P4.8 detection scoring (brand_handle signal — +30pts)
- **Refresh:** weekly; `last_handle_change_at` flags rebrands
- **Gap before G1 fix:** unread; now wired ✓

### `brand_industry_map.brands[brand_id].legal_entity`
- **Writer:** P2 brand_enrichment (opportunistic) + P4.6 proactive capture (O4) + P4.7 inferred from uploads
- **Reader:** P4.7 contract_pack (brand TO-party merge fields)
- **Fallback chain:** absent → check `brand_candidate.legal_entity_override`; absent → agent uploads at P4.7 Stage A

### `pitch_enrollment.created_deal_id`
- **Writer:** P3b webhook handler on `interested` reply classification (G3 bidirectional fix)
- **Reader:** Analytics + audit views (no agent-runtime read in v0.1)
- **Pair:** `deal.originating_enrollment_id` (set during deal creation; bidirectional)

### `deal.originating_decision_role_at_pitch`
- **Writer:** P3b deal creation (R8 analytics threading)
- **Reader:** Outreach analyzer (won-deal-by-decision-role cross-cuts)
- **Snapshot semantics:** captured from `brand_contact.decision_role` at pitch time; doesn't change even if contact's role evolves

### `deal.lead.discovery_debrief.*`
- **Writer:** P4.6 Stage B (LLM extracts + agent confirms)
- **Readers:** P4.6 Stages C-D (commercial proposal + slide narrative); P4.7 conditional clause evaluation (e.g. EU brand → GDPR); P4.9 vs_brand_stated_targets benchmark
- **Cross-phase write:** Phase 4.6 writes a Phase 4 LEAD-block field (intentional — debrief lives where the call happened but is structured by the proposal flow)

### `deal.delivery.campaign_hashtags[]`
- **Writer:** P4.6 (LLM extracts from brief/debrief during proposal gen) OR P4.7 (legal clauses spec required hashtags); agent confirms (G2 fix)
- **Reader:** P4.8 detection scoring (campaign_hashtag signal — +20pts)
- **Empty array tolerance:** degrades to 3-signal matching (time + brand_handle + content_type only — max 80pts vs 100)

### `deal.delivery.posting_schedule[].posted_detection.*`
- **Writer:** P4.8 detection layer
- **Readers:** P4.9 KPI capture cron (only polls URLs with posted_at set); P4.8 invoice trigger evaluation (trigger_condition: first_post_live / all_deliverables_live)

### `deal.delivery.interim_kpi_snapshots[]`
- **Writer:** P4.9 daily KPI capture cron
- **Reader:** P4.9 performance report generation Stage A (aggregate to final kpis{})

### `deal.proposal.deliverables[] + .fee_usd + .usage_rights_granted + .exclusivity + .additional_compensation`
- **Writer:** P4.6 on commercial gate confirm (canonical values copied from `proposal_pack.commercial_proposal.confirmed_*` overrides)
- **Readers:** P4.7 contract_pack merge fields; P4.8 invoice generation; P4.9 CPM/CPE computation; A auto-archive → brand_deal.deals[].* verbatim

### `deal.close.invoice_schedule[].percentage + .amount_usd + .trigger_condition + .payment_terms_days`
- **Writer:** P4.8 LLM-parse of `contract_pack.commercial_proposal.payment_terms` + agent confirm gate (locks on confirm)
- **Reader:** P4.8 invoice generation (one entry per fire)

### `deal.close.all_invoices_paid_at`
- **Writer:** Computed by orchestrator on every `invoice_pack.payment_state.payment_received_at` change (when every schedule entry has paid invoice)
- **Reader:** A auto-archive (gate condition 1)

### `deal.close.final_kpis`
- **Writer:** P4.9 on `performance_report_pack.agent_review.sent_at` set
- **Readers:** A auto-archive (gate condition 3 + copies verbatim to new `brand_deal.deals[N].kpis`)

### `deal.close.final_performance_report_attachment_id`
- **Writer:** P4.9 on `performance_report_pack.agent_review.sent_at` set
- **Reader:** A auto-archive (gate condition 2)

### `deal.close.archived_to_brand_deal_id` ↔ `brand_deal.deals[N].archived_from_deal_id`
- **Writer (both):** A on archive fire (bidirectional)
- **Reader:** future deal views ("see archived record"); future brand_deal views ("see source deal")

### `memo.*` (any memo)
- **Writers:** Any subagent (researcher / writer / extractor / renderer) + deal_orchestrator + human_agent
- **Readers:** Any subagent invocation via `read_memos(...)` tag filters
- **Discipline:** every agent milestone (M11-M15) defines which memos it writes + reads (project_plan.md cross-cutting discipline)

#### Memo defaults table — "which scope + memo_type for which kind of learning?"

50 (5 scope × 10 memo_type) combinations are valid but only ~10 are commonly used. To reduce choice paralysis + standardise tagging across agents, use these defaults:

| Common learning | Default `scope` | Default `memo_type` | Tag with |
|---|---|---|---|
| "Agent X regenerated slide 4 with feedback Y; root cause was Z" | `deal_specific` | `agent_decision_audit` | `deal_id`, `pack_id` (via `created_in_pack_id`), `phase_context` |
| "Brand X requires GDPR addendum on all contracts" | `brand_relationship` | `brand_observation` | `brand_id`, `industry_id`, `topics: ["gdpr", "contract-clause"]`, `phase_context: contract` |
| "Brand X pushed back on whitelisting >60d; settled at 60d in 3 deals" | `brand_relationship` | `negotiation_pattern` | `brand_id`, `industry_id`, `topics: ["whitelisting", "usage-rights"]`, `phase_context: proposal` |
| "Activewear brands typically counter-offer at 70% of asking" | `industry_pattern` | `negotiation_pattern` | `industry_id`, `topics: ["pricing", "counter-offer"]`, `phase_context: proposal` |
| "Brand X consistently asks 'what's the audience overlap with our existing customers'" | `brand_relationship` | `objection_handler` | `brand_id`, `topics: ["audience-overlap", "discovery-questions"]`, `phase_context: lead` |
| "Talent's engagement rate dropped from 5.2% to 3.8% over Q2; affects future fee defensibility" | `talent_pattern` | `talent_learning` | `talent_id`, `topics: ["engagement-rate", "kpi-trend"]` |
| "Talent prefers 60d default usage rights vs the agency default of 90d" | `talent_pattern` | `talent_learning` | `talent_id`, `topics: ["usage-rights", "working-terms"]` |
| "Athletic Greens 2025 Q1 campaign overperformed; final ER 5.1% vs predicted 4.2%" | `deal_specific` | `kpi_pattern` | `deal_id`, `brand_id`, `topics: ["overperformance", "engagement-rate"]`, `phase_context: close` |
| "Across 5 fitness × activewear deals, IG reels outperform feed posts by ~40% on reach" | `industry_pattern` | `creative_insight` | `industry_id`, `topics: ["content-format", "ig-reels", "reach"]` |
| "Whitelisting > 60d is usually a redline across brands" | `cross_cutting` | `negotiation_pattern` | `topics: ["whitelisting", "redline"]`, `phase_context: cross_phase` |

**Discipline rules:**
- Always include at least 1 entry in `topics[]` (schema-enforced via `minItems: 1`).
- If the memo references specific brand(s) or talent(s), tag them — enables cross-deal retrieval.
- Use `cross_cutting` scope sparingly; most learnings fit a more specific scope.
- Prefer the most-specific scope that's still useful for retrieval. A brand-specific pattern in `industry_pattern` is overgeneralised; the same observation in `brand_relationship` will surface only when that brand is relevant.

### `deal.proposal.negotiation_log[].proposal_pack_version` ↔ `proposal_pack.generation.negotiation_log_entry_ref`
- **Writer (both):** P4.6 on `negotiation_response` regen (bidirectional)
- **Reader:** Audit views — "which pack version responded to which pushback?"

### `deal.contract.amendment_log[].contract_pack_version` ↔ `contract_pack.generation.amendment_log_entry_ref`
- **Writer (both):** P4.7 on `amendment_request` regen (bidirectional — G5 fix)
- **Reader:** Audit views

---

## §4 Gap analysis

Identified issues from this lineage exercise. Severity scale: 🔴 critical (breaks the flow) / 🟡 high (suboptimal / drift risk) / 🟢 low (cosmetic).

### ✅ GAP-01 — `agency_id` not in JSON schemas (multi-tenant readiness debt) — **FIXED**

**Issue:** Only `agency_profile.agency_id` exists at root. No other schema (talent, brand_candidate, brand_contact, brand_deal, deal, all packs, memo) had an `agency_id` field. The architecture spec notes "multi-tenant-ready via agency_id UUID column on every domain table" but this was described as a Postgres-layer column, not a JSON schema field.

**Impact:** When v2 multi-tenant SaaS ships, every JSON Schema would need to add `agency_id`. Any Pydantic codegen from current schemas won't include it. Field is technically optional today (v0.1 single tenant) but creates schema-version churn at v2 cutover.

**Severity:** 🔴 critical for v2; 🟢 cosmetic for v0.1.

**Fix applied:** Optional `agency_id` UUID field added to root of all 15 domain schemas (talent, brand_candidates, brand_contact, brand_deal, pitch_angle, pitch_template, pitch_enrollment, deal, discovery_prep_pack, proposal_pack, contract_pack, invoice_pack, performance_report_pack, brand_industry_map, memo). All carry the same description noting v0.1 optional / v2 required + cross-record query filter requirement.

### ✅ GAP-02 — `memo.agency_id` field missing (multi-tenant memo leakage risk) — **FIXED**

**Issue:** `memo.schema.json` had no agency scoping. In multi-tenant deploys, Agency A's memos could leak into Agency B's `read_memos` queries if the SQL filter doesn't include `agency_id`.

**Impact:** Sensitive cross-deal patterns visible across tenants.

**Severity:** 🔴 critical for v2; 🟡 worth fixing now for hygiene.

**Fix applied:** Covered by GAP-01 fix. `memo.schema.json` now has `agency_id` UUID field at root. Implementation discipline (called out in field description): all `read_memos` tool implementations MUST filter by current agency_id from the invoking deal's context.

### 🕒 GAP-03 — `data/industry_kpi_benchmarks.json` referenced but not yet shipped — **DEFERRED v0.2**

**Issue:** P4.9 `vs_industry` benchmark consumes from `data/industry_kpi_benchmarks.json`. Doc + schema reference it. v0.1 gracefully omits the section with a note ("industry benchmarks ship in v2").

**Impact:** Performance reports lose one of three benchmark sets in v0.1. Acknowledged graceful degradation — Performance report still ships with vs_talent_historical + vs_brand_stated_targets benchmarks.

**Severity:** 🟡 high (degraded output but doesn't block).

**Status:** v0.2 — ship `schemas/industry_kpi_benchmarks.schema.json` (proposed — not yet shipped) + `data/industry_kpi_benchmarks.json` with at least the activewear, CPG, beauty industries seeded. Documented as graceful-degradation in `docs/performance_report_workflow.md`.

### 🕒 GAP-04 — `data/pitch_angles.json` write path closed-loop deferred — **DEFERRED v0.2**

**Issue:** `analyze_outreach.py` captures outcomes but explicitly does NOT auto-update `pitch_angles.json.authored_strength_score`. The pitch_angles file is read-only from the orchestrator's perspective; human edits only.

**Impact:** No closed-loop quality improvement on pitch angle scoring in v0.1. Manual angle tuning required as agencies learn.

**Severity:** 🟡 high (slows compounding learning).

**Status:** v0.2 — closed-loop tuning. Documented in `docs/outreach_workflow.md` as a known v0.2 deferral. Until then, agencies should review angle performance monthly + adjust scores manually.

### 🕒 GAP-05 — `brand_candidates.candidates[].pitch_history[]` legacy index — **DEFERRED v0.2**

**Issue:** Three places track pitch attempts: `brand_candidate.pitch_history[]`, `brand_contact.pitch_history[]` (now redesigned as summary index pointing to enrollment), and `pitch_enrollment.*` (canonical). brand_candidate's is the most legacy + least precise.

**Impact:** Three sources of truth for the same concept = drift risk + agent confusion.

**Severity:** 🟡 high (already documented as v0.2 deprecation target).

**Status:** v0.2 — deprecate `brand_candidates.candidates[].pitch_history[]`. Migrate any UI reads to query pitch_enrollment via `brand_id` filter directly. Schema notes already mark it as legacy. v0.2 schema migration will remove the field.

### ✅ GAP-06 — `brand_candidates.candidates[].status` denormalisation sync timing — **FIXED**

**Issue:** `brand_candidates.candidates[].status` enum includes post-pitch states (pitched / responded / negotiating / closed_won / closed_lost) that are denormalised from canonical sources (pitch_enrollment + deal). Documented sync direction but no automatic sync job in the project plan.

**Impact:** Status field could drift from canonical state if not refreshed.

**Severity:** 🟡 high (could mislead agent UI).

**Fix applied:** Discipline documented in `docs/brand_discovery.md` § "brand_candidates.candidates[].status — sync discipline" with full table of canonical sources per status + trigger events + priority order for the `sync_brand_candidate_status` Celery task (project plan M9 + M10). Backfill discipline + failure mode also documented.

### ✅ GAP-07 — `agency_profile.invoice_template` template_version not enforced on changes — **FIXED**

**Issue:** Schema had `template_version + template_updated_at` fields. `invoice_pack.context_snapshot.agency_invoice_template_version` captures the version at gen. But there was no codified discipline saying "bump template_version on any change to markdown_source / tax_handling / footer". Risk: template silently changes; old invoice_packs reference a version string that no longer matches what's stored.

**Impact:** Audit trail drift.

**Severity:** 🟡 high (silent — could surface only during dispute).

**Fix applied:** 1) Schema field description (`agency_profile.schema.json` § invoice_template.template_version) tightened with explicit enforcement requirement + list of fields that trigger bump + semver format suggestion. 2) Discipline documented in `docs/agency_setup_workflow.md` § "Invoice template version bump enforcement" with implementation guidance (DB-level trigger or service-layer guard) + failure mode + rationale.

### ✅ GAP-08 — `talent.contract_template` versioning analogous to GAP-07 — **FIXED**

**Issue:** Same pattern as GAP-07 for contract templates. `talent.contract_template.template_version` existed but no enforced bump on `markdown_source` / merge field / clause / narrative changes. `contract_pack.context_snapshot.template_version_used` would silently drift.

**Severity:** 🟡 high (MORE critical than GAP-07 — contracts are legal instruments).

**Fix applied:** 1) Schema field description (`talent.schema.json` § contract_template.template_version) tightened with explicit enforcement + comprehensive field list + semver guidance + explicit "critical for legal audit trail" warning. 2) Discipline documented in `docs/onboarding_workflow.md` § "Contract template version bump enforcement" with cross-deal interaction notes (existing contract_packs stay anchored to prior version via context_snapshot).

### 🕒 GAP-09 — Sibling commission invoice auto-generation deferred to v0.2 — **DEFERRED v0.2**

**Issue:** When `commission_model = talent_invoices_brand_agency_invoices_talent`, the architecture says agency auto-generates a sibling commission invoice. Schema supports it (`invoice_pack` with offset sequence). But v0.1 explicitly defers implementation per `docs/invoice_workflow.md`.

**Impact:** Agencies using non-default commission models manually create the commission invoice in v0.1.

**Severity:** 🟡 high (degrades UX for non-default talents).

**Status:** v0.2 — implement auto-generation. v0.1 ships with UI nudge: "Generate sibling commission invoice manually". Documented in `docs/invoice_workflow.md`.

### ✅ GAP-10 — `data/contract_template_starters/` empty + gitignored — **FIXED**

**Issue:** Architecture references agency-curated starter templates that talent onboarding adopts (Step 7.5). The directory is gitignored (real legal language could be sensitive). No examples shipped.

**Impact:** Agency operators had no scaffold to write their first starter.

**Severity:** 🟡 high (cold-start friction).

**Fix applied:** Shipped `docs/contract_template_examples/generic_starter.md` — a comprehensive 16-section example contract template demonstrating all three placeholder types (deterministic `{{merge_field}}`, conditional `{{#if}}...{{/if}}`, narrative `{{narrative_*}}`) with detailed adoption notes. Explicitly disclaims it's not legal advice; agencies must lawyer-review + adapt to their jurisdiction.

### 🕒 GAP-11 — `pitch_template.json` authoring workflow — **DEFERRED**

**Issue:** Templates (`data/pitch_templates.json`) are static — no schema enforces a write workflow. Onboarding doesn't explicitly cover template creation.

**Impact:** Cold-start — agencies have nothing to base their first templates on (similar to GAP-10).

**Severity:** 🟢 low (templates rarely edited; ship generic defaults).

**Status:** Deferred. The 3-4 default templates already exist per `docs/outreach_workflow.md` spec. Authoring workflow is low-priority v0.2 work; agencies can edit `data/pitch_templates.json` directly in v0.1.

### ✅ GAP-12 — `pitch_enrollment.context_snapshot.*_snapshot_hash` fields not exercised — **FIXED (documented as forward-compat)**

**Issue:** `pitch_enrollment.context_snapshot` has `talent_snapshot_hash + contact_snapshot_hash + brand_snapshot_hash + snapshotted_at` fields. Designed for reproducibility ("if we re-generate later, compare what changed"). No re-generation workflow in v0.1.

**Impact:** Fields populated but never read. Storage overhead only.

**Severity:** 🟢 low.

**Fix applied:** Schema field descriptions tightened in `pitch_enrollment.schema.json` — context_snapshot top-level description explicitly notes "v0.1: populated by orchestrator on enrollment creation but no runtime reader exists yet. v0.2 will introduce a regeneration workflow that diffs against snapshotted_at + the three hashes". Per-hash field descriptions added (SHA-256 of canonicalised source data).

### ✅ GAP-13 — `brand_deal.deals[].audience_demographics_at_campaign_time` snapshot timing — **FIXED**

**Issue:** Schema noted this is "a snapshot of the talent's audience_demographics at the time the campaign ended". On A auto-archive, we have access to deal data + talent profile but the talent.audience_demographics may have evolved since campaign-end.

**Impact:** Snapshot may not reflect campaign-time demos (depends on archive timing).

**Severity:** 🟢 low (best-effort capture; documented as approximate).

**Fix applied:** Field description in `brand_deal.schema.json` updated to explicitly state v0.1 snapshot timing convention: "captured at auto-archive time, NOT at campaign-end. This is best-effort — audience_demographics may have evolved between campaign-end and archive (typically a 30-90d window)." Future-proof guidance for v0.2 included.

### 🕒 GAP-14 — Missing schema for `data/industries.json` + `data/niches.json` — **DEFERRED**

**Issue:** These data files are referenced throughout but only `pitch_template.schema.json` + `pitch_angle.schema.json` exist as schemas. `industries.json` + `niches.json` are referenced but have no formal schema.

**Impact:** Validation drift — fields could be added or shape evolved without explicit schema.

**Severity:** 🟢 low (data files are stable, hand-curated).

**Status:** Deferred. Adding `schemas/industries.schema.json` (proposed — not yet shipped) + `schemas/niches.schema.json` (proposed — not yet shipped) would formalise the shapes. Low priority — these files change rarely + are agency-curated reference data, not LLM input/output. Worth adding in v0.2 once shape is stable.

### ✅ GAP-15 — `kpiMetric` shape definition duplicated across schemas — **FIXED**

**Issue:** Same `kpiMetric` $def appeared in `brand_deal.schema.json` AND `performance_report_pack.schema.json`. They already had drifted slightly (performance_report had a top-level description but missing per-field descriptions; brand_deal had rich per-field descriptions but no top-level note).

**Impact:** Schema maintenance overhead + active drift risk realised.

**Severity:** 🟢 low (formal); 🟡 already drifting (real).

**Fix applied:** Created `schemas/_shared/kpi_metric.schema.json` as canonical definition (merged richer descriptions from brand_deal + top-level system-context note from performance_report). Updated both consumer schemas to `$ref` the shared file via their existing `$defs.kpiMetric` wrapper (preserves intra-schema `#/$defs/kpiMetric` references throughout each schema). Pydantic codegen + cross-file `$ref` resolution works. Same approach available for `debriefSignal` if it ever needs sharing.

### 🛈 GAP-16 — `discovery_prep_pack` slide types vs `proposal_pack` slide types — **RECLASSIFIED: BY DESIGN**

**Re-examined:** On closer inspection these are NOT near-identical. They share only 5 values (`title / talent_overview / audience_snapshot / recent_work / custom`); the remaining types are intentionally different:

- **discovery prep only (7):** `context / brand_observation / fit_angle / case_study / proof_point / process / next_steps` — these are pre-call exploration tools that don't make sense in a sent proposal.
- **proposal only (11):** `executive_summary / objectives_recap / recommendation / deliverables / timeline / investment / usage_rights / exclusivity / exclusions / agency_process / next_steps_proposal` — these are commercial-stage commitments that don't make sense in a pre-call prep deck.

**Conclusion:** Domain-correct modeling. Consolidating to a union would WEAKEN validation (e.g. discovery_prep_pack would accept an "investment" slide, which is nonsensical for that pack type). The 5-value overlap is the legitimate fork seam — talent_overview / audience_snapshot / recent_work fork from prep into proposal per the documented Phase 4.6 pattern.

**Status:** Not a real gap. Leave as-is.

---

## Summary

**Total cross-phase data flows catalogued:** ~110 in § 1 master table.

**Gap resolution status:**
- ✅ **9 fixed** in this commit: GAP-01 (agency_id × 15 schemas), GAP-02 (memo.agency_id — covered by GAP-01), GAP-06 (status sync discipline), GAP-07 (agency invoice_template version enforcement), GAP-08 (talent contract_template version enforcement), GAP-10 (starter template scaffold shipped), GAP-12 (snapshot_hash forward-compat documented), GAP-13 (audience_demographics snapshot timing clarified), GAP-15 (shared kpiMetric extraction)
- 🛈 **1 reclassified as by-design**: GAP-16 (slide type enums correctly different per domain)
- 🕒 **6 explicitly deferred to v0.2**: GAP-03 (industry benchmarks), GAP-04 (pitch_angles closed-loop), GAP-05 (brand_candidate.pitch_history deprecation), GAP-09 (sibling commission auto-gen), GAP-11 (pitch_template authoring), GAP-14 (industries/niches schemas)

**Remaining work for v0.2:** the 6 deferred items + Pydantic codegen wiring for cross-file `$ref` resolution (already supported by `datamodel-code-generator`; verify in M1 of project plan).

**No broken dependencies** — every consumer's required input is produced somewhere upstream. The audit tier-1 fixes (G1-G5) all hold.

**System integrity:** Strong. Every fix-able gap has been addressed in this commit. The 6 v0.2 deferrals are documented + tracked in their respective workflow docs.
