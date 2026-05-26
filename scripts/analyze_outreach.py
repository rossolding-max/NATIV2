#!/usr/bin/env python3
"""
Roll every step record across all enrollments into A/B-sliceable aggregates.

Reads: data/pitch_enrollments/*.json
Writes: data/outreach_analytics/aggregates_*.json (gitignored)

Dimensions sliced (one output file each):
- by_angle              — primary angle effectiveness
- by_angle_pair         — primary + supporting angle combinations
- by_decision_role      — buyer vs influencer vs gatekeeper vs champion
- by_template           — template-level performance
- by_step_number        — when in the sequence do replies happen
- by_brand_tier         — typical_campaign_tier from the brand record
- by_brand_industry     — industry_id of the brands pitched
- by_talent             — per-talent reply rates
- by_send_dow           — day-of-week effects
- by_send_hour          — time-of-day effects
- by_subject_pattern    — length / question / emoji / starts_with
- by_sender_domain      — per-domain placement (if multi-domain roster)

Headline metric: reply rate (replied ÷ delivered). Per the v0.1 user
decision — most reliable signal in 2026 (Apple MPP makes opens noisy).

v0.1 explicit non-goal: this script DOES NOT auto-update
data/pitch_angles.json strength_scores. Output is for human review only.
Closed-loop tuning is a v2 deliverable. See docs/outreach_workflow.md.

Run: python3 scripts/analyze_outreach.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
ENROLLMENTS_DIR = ROOT / "data" / "pitch_enrollments"
OUT_DIR = ROOT / "data" / "outreach_analytics"


def load_enrollments():
    """Load every enrollment file. Returns list of (enrollment, brand_record)."""
    enrollments = []
    if not ENROLLMENTS_DIR.exists():
        return enrollments

    # Brand metadata for joining (brand_tier, industry, etc.)
    brand_map = {
        b["name"]: b
        for b in json.loads((ROOT / "data" / "brand_industry_map.json").read_text())["brands"]
    }
    # Normalize keys to lowercase for join
    brand_map_by_id = {
        # Reverse the slug -> name resolution: brand_id is slug of name
        # For simplicity, brand_id matches a normalized name
        _slug(b["name"]): b for b in brand_map.values()
    }

    for f in sorted(ENROLLMENTS_DIR.glob("*.json")):
        try:
            enr = json.loads(f.read_text())
        except json.JSONDecodeError:
            print(f"  skip (invalid JSON): {f.name}", file=sys.stderr)
            continue
        brand = brand_map_by_id.get(enr.get("brand_id"))
        enrollments.append((enr, brand))
    return enrollments


def _slug(s):
    """Normalize brand display name to slug (mirrors orchestrator logic)."""
    import re
    s = s.lower().strip()
    # Strip common corporate suffixes
    for suf in [" inc", " ltd", " plc", " llc", " co.", " corp"]:
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def step_metrics(step):
    """Extract metrics from a single step record. Returns dict of bools/ints."""
    summary = step.get("engagement_summary", {}) or {}
    outcome = step.get("outcome_classification", {}) or {}
    return {
        "sent": step.get("status") == "sent",
        "delivered": any(e["event"] == "delivered" for e in step.get("engagement_events", [])),
        "opens_total": summary.get("opens_total", 0),
        "human_opens": summary.get("human_opens", 0),
        "clicks_total": summary.get("clicks_total", 0),
        "unique_clicks": summary.get("unique_clicks", 0),
        "replied": summary.get("replied", False),
        "bounced": summary.get("bounced", False),
        "unsubscribed": summary.get("unsubscribed", False),
        "positive_reply": outcome.get("outcome") == "interested",
        "time_to_reply_seconds": summary.get("time_to_reply_seconds"),
        "cost_usd": (step.get("generation_meta") or {}).get("cost_usd", 0),
    }


def aggregate(records, key_fn, also_cost=True):
    """
    Generic aggregator. records = list of (step, brand, enrollment) tuples.
    key_fn(step, brand, enrollment) -> key string (or None to skip).
    Returns dict keyed by the slice, with per-slice metrics.
    """
    buckets = defaultdict(lambda: defaultdict(int))
    cost_buckets = defaultdict(float)
    times_to_reply = defaultdict(list)

    for step, brand, enr in records:
        key = key_fn(step, brand, enr)
        if key is None:
            continue
        m = step_metrics(step)
        for metric in ("sent", "delivered", "opens_total", "human_opens", "clicks_total",
                       "unique_clicks", "replied", "bounced", "unsubscribed", "positive_reply"):
            v = m[metric]
            if isinstance(v, bool):
                buckets[key][metric] += int(v)
            else:
                buckets[key][metric] += v
        if m["time_to_reply_seconds"]:
            times_to_reply[key].append(m["time_to_reply_seconds"])
        cost_buckets[key] += m["cost_usd"]

    out = {}
    for key, b in buckets.items():
        sent = b.get("sent", 0)
        delivered = b.get("delivered", 0)
        replied = b.get("replied", 0)
        positive = b.get("positive_reply", 0)
        out[key] = {
            "sample_count": sent,
            "delivered": delivered,
            "human_opens": b.get("human_opens", 0),
            "unique_clicks": b.get("unique_clicks", 0),
            "replied": replied,
            "positive_replies": positive,
            "bounced": b.get("bounced", 0),
            "unsubscribed": b.get("unsubscribed", 0),
            "delivery_rate": round(delivered / sent, 4) if sent else None,
            "human_open_rate": round(b.get("human_opens", 0) / delivered, 4) if delivered else None,
            "raw_open_rate_noisy": round(b.get("opens_total", 0) / delivered, 4) if delivered else None,
            "click_rate": round(b.get("unique_clicks", 0) / delivered, 4) if delivered else None,
            "reply_rate": round(replied / delivered, 4) if delivered else None,
            "positive_reply_rate": round(positive / delivered, 4) if delivered else None,
            "bounce_rate": round(b.get("bounced", 0) / sent, 4) if sent else None,
            "unsubscribe_rate": round(b.get("unsubscribed", 0) / delivered, 4) if delivered else None,
            "mean_time_to_reply_seconds": int(mean(times_to_reply[key])) if times_to_reply[key] else None,
        }
        if also_cost:
            cost = cost_buckets[key]
            out[key]["total_cost_usd"] = round(cost, 4)
            out[key]["cost_per_positive_reply_usd"] = round(cost / positive, 4) if positive else None
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    enrollments = load_enrollments()
    if not enrollments:
        print("No enrollments found. Run outreach first; this analyzer is empty until enrollments exist.")
        sys.exit(0)

    # Flatten to (step, brand, enrollment) tuples
    records = []
    for enr, brand in enrollments:
        for step in enr.get("steps", []):
            if step.get("status") not in ("sent", "skipped", "killed"):
                continue
            records.append((step, brand, enr))

    print(f"Loaded {len(enrollments)} enrollments, {len(records)} step records")

    if not records:
        print("No sent steps yet — analytics empty.")
        sys.exit(0)

    # ---- Define slicing key functions ----

    def k_angle_primary(step, brand, enr):
        gm = step.get("generation_meta") or {}
        return (gm.get("angles_used") or {}).get("primary")

    def k_angle_pair(step, brand, enr):
        gm = step.get("generation_meta") or {}
        au = gm.get("angles_used") or {}
        p, s = au.get("primary"), au.get("supporting")
        if not p:
            return None
        return f"{p}+{s}" if s else p

    def k_decision_role(step, brand, enr):
        # Pulled from brand_contact at enrollment time; not stored on step directly.
        # Inferred from the template_id mapping (default templates are role-keyed).
        # For richer slicing, the orchestrator should store contact.decision_role on the enrollment.
        # Fallback: infer from template_id.
        tid = enr.get("template_id", "")
        if tid.startswith("buyer-"):
            return "buyer"
        if tid.startswith("influencer-"):
            return "influencer"
        if tid.startswith("champion-"):
            return "champion"
        if tid.startswith("gatekeeper-"):
            return "gatekeeper"
        return "unknown"

    def k_template(step, brand, enr):
        return enr.get("template_id")

    def k_step_number(step, brand, enr):
        return f"step_{step.get('step_number')}"

    def k_brand_tier(step, brand, enr):
        return (brand or {}).get("typical_campaign_tier", "unknown")

    def k_brand_industry(step, brand, enr):
        return (brand or {}).get("industry_id", "unknown")

    def k_talent(step, brand, enr):
        return enr.get("talent_id")

    def k_send_dow(step, brand, enr):
        sm = step.get("smartlead_step_meta") or {}
        ts = sm.get("sent_at_utc")
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%A")
        except ValueError:
            return None

    def k_send_hour(step, brand, enr):
        sm = step.get("smartlead_step_meta") or {}
        local_ts = sm.get("sent_at_recipient_local") or sm.get("sent_at_utc")
        if not local_ts:
            return None
        try:
            dt = datetime.fromisoformat(local_ts.replace("Z", "+00:00"))
            return f"{dt.hour:02d}:00"
        except ValueError:
            return None

    def k_subject_pattern(step, brand, enr):
        gc = step.get("generated_content") or {}
        sm = gc.get("subject_meta") or {}
        bucket = "short" if sm.get("length_chars", 0) < 40 else "medium" if sm.get("length_chars", 0) < 60 else "long"
        has_q = "Q" if sm.get("has_question_mark") else "."
        has_em = "+emoji" if sm.get("has_emoji") else ""
        return f"{bucket}{has_q}{has_em}"

    def k_sender_domain(step, brand, enr):
        sm = step.get("smartlead_step_meta") or {}
        mailbox = sm.get("sent_via_mailbox", "")
        return mailbox.split("@")[-1] if "@" in mailbox else None

    # ---- Run aggregations ----
    aggregations = {
        "by_angle":           aggregate(records, k_angle_primary),
        "by_angle_pair":      aggregate(records, k_angle_pair),
        "by_decision_role":   aggregate(records, k_decision_role),
        "by_template":        aggregate(records, k_template),
        "by_step_number":     aggregate(records, k_step_number),
        "by_brand_tier":      aggregate(records, k_brand_tier),
        "by_brand_industry":  aggregate(records, k_brand_industry),
        "by_talent":          aggregate(records, k_talent),
        "by_send_dow":        aggregate(records, k_send_dow),
        "by_send_hour":       aggregate(records, k_send_hour),
        "by_subject_pattern": aggregate(records, k_subject_pattern),
        "by_sender_domain":   aggregate(records, k_sender_domain),
    }

    # ---- Write outputs ----
    timestamp = datetime.utcnow().isoformat() + "Z"
    for slice_name, data in aggregations.items():
        # Sort entries by reply_rate descending for human-friendly review
        sorted_entries = sorted(
            data.items(),
            key=lambda kv: (kv[1].get("reply_rate") or 0),
            reverse=True,
        )
        out_path = OUT_DIR / f"aggregates_{slice_name}.json"
        out_path.write_text(json.dumps({
            "$comment": (
                "Aggregated outreach metrics. Headline metric is `reply_rate` (replied / delivered). "
                "Apple Mail Privacy Protection makes raw open rates noisy; use `human_open_rate` "
                "(MPP-filtered) for honest open metrics. `positive_reply_rate` (replies classified as "
                "outcome=interested) is the truest conversion-leading-indicator but takes more samples "
                "to be statistically meaningful. Generated by scripts/analyze_outreach.py."
            ),
            "slice": slice_name,
            "generated_at": timestamp,
            "total_records_analyzed": len(records),
            "entries": dict(sorted_entries),
        }, indent=2) + "\n")

    print(f"Wrote {len(aggregations)} aggregation files to {OUT_DIR}")
    print("\nTop reply-rate slices (preview):")
    for slice_name in ("by_angle", "by_decision_role", "by_template", "by_step_number"):
        data = aggregations[slice_name]
        if not data:
            continue
        top = sorted(data.items(), key=lambda kv: kv[1].get("reply_rate") or 0, reverse=True)[:3]
        print(f"\n  {slice_name}:")
        for key, m in top:
            rr = m.get("reply_rate")
            pr = m.get("positive_reply_rate")
            print(f"    {key:40s}  reply={rr if rr is not None else '—'}  positive={pr if pr is not None else '—'}  (n={m['sample_count']})")


if __name__ == "__main__":
    main()
