"""Interactive Phase-1 talent-onboarding CLI wizard.

Walks the operator through Phase 1 onboarding by calling the
``/api/v1/talents`` REST surface.

What this wizard captures (only TALENT-SPECIFIC fields — agency-wide
pieces like billing entity, VAT, contract template, default usage rights,
commission MODEL all live in agency onboarding, not here):

  Step 1: identity seed (name / country picker / initial platform handle)
  Step 2: Meta + TikTok OAuth (start URL; callback driven separately)
  Step 5: questionnaire (pronouns/bio/DOB/niches/languages/brand prefs/
           contact/target commission rate/rate card)
  Step 6: bulk-paste previous brands -> LLM tidies + resolves industries
  Step 7: bulk-paste similar creators -> LLM tidies into seed entries
  Step 8: activate

Media-pack extraction (Step 3 + 4) and contract-template adoption (Step
7.5) are intentionally out of the wizard — agency-supplied kits drift
and contract templates are agency-wide, not per-talent.

Usage::

    just dev-api     # in another terminal
    uv run nativ test phase 1
    # Non-interactive mode (e2e tests):
    uv run nativ test phase 1 --auto --skip-oauth --skip-activate
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import typer

DEFAULT_API_BASE = "http://127.0.0.1:8000"


class _NullCM:
    """Context manager that yields a pre-existing client without closing it."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __enter__(self) -> httpx.Client:
        return self._client

    def __exit__(self, *_exc: Any) -> None:
        return None


# ── HTTP helpers ──────────────────────────────────────────────────────


def _post_json(client: Any, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        path, json=payload, headers={"Idempotency-Key": f"talent-wizard-{int(time.time() * 1000)}"}
    )
    if r.status_code >= 400:
        typer.echo(f"  X {path} -> HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _get_json(client: Any, path: str) -> dict[str, Any]:
    r = client.get(path)
    if r.status_code >= 400:
        typer.echo(f"  X {path} -> HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


# ── Inline country list (v0.1 — broaden later) ────────────────────────


_COUNTRIES: list[tuple[str, str]] = [
    ("US", "United States"),
    ("GB", "United Kingdom"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("IE", "Ireland"),
    ("NZ", "New Zealand"),
    ("DE", "Germany"),
    ("FR", "France"),
    ("ES", "Spain"),
    ("IT", "Italy"),
    ("NL", "Netherlands"),
    ("BE", "Belgium"),
    ("SE", "Sweden"),
    ("NO", "Norway"),
    ("DK", "Denmark"),
    ("FI", "Finland"),
    ("PT", "Portugal"),
    ("CH", "Switzerland"),
    ("AT", "Austria"),
    ("PL", "Poland"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("SG", "Singapore"),
    ("HK", "Hong Kong"),
    ("IN", "India"),
    ("BR", "Brazil"),
    ("MX", "Mexico"),
    ("AR", "Argentina"),
    ("ZA", "South Africa"),
    ("AE", "United Arab Emirates"),
]


# ── Prompt rendering helpers ──────────────────────────────────────────


def _print_label(label: str, *, required: bool = False) -> None:
    """Render a single-line, coloured label. No help blurb."""
    suffix = " (required)" if required else "  (blank to skip)"
    typer.secho(f"\n  {label}{suffix}", fg=typer.colors.CYAN, bold=True)


def _echo_captured(field_path: str, value: Any) -> None:
    """Confirm what was captured so the operator can see the prompt advanced."""
    typer.secho(f"  ✓ {field_path} = {value!r}", fg=typer.colors.GREEN)


def _coerce_decimal(raw: str) -> float | None:
    cleaned = raw.strip().replace("%", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coerce_int(raw: str) -> int | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _prompt_enum_one_or_text(
    choices: Sequence[tuple[str, str]],
    *,
    hint: str = "  Pick one number OR type a custom value (blank to skip)",
) -> str | None:
    """Render the enum picker but accept free-text fallback."""
    if not choices:
        raw = typer.prompt(hint, default="", show_default=False).strip()
        return raw or None
    _render_enum_choices(choices)
    raw = typer.prompt(hint, default="", show_default=False)
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Numeric input → pick from the list.
    try:
        n = int(cleaned)
    except ValueError:
        return cleaned
    if 1 <= n <= len(choices):
        return choices[n - 1][0]
    return cleaned


def _coerce_iso_date(raw: str) -> str | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError:
        pass
    for sep in ("/", "-", "."):
        if sep in cleaned:
            parts = cleaned.split(sep)
            if len(parts) == 3:
                a, b, c = parts
                try:
                    if len(c) == 4:
                        a_i, b_i, c_i = int(a), int(b), int(c)
                        if a_i > 12:
                            return date(c_i, b_i, a_i).isoformat()
                        if b_i > 12:
                            return date(c_i, a_i, b_i).isoformat()
                        return date(c_i, b_i, a_i).isoformat()
                except (ValueError, TypeError):
                    return None
    return None


def _split_csv(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _render_enum_choices(choices: Sequence[tuple[str, str]], *, group_size: int = 12) -> None:
    for idx, (value, label) in enumerate(choices, start=1):
        if idx > 1 and (idx - 1) % group_size == 0:
            typer.echo("")
        typer.echo(f"    {idx:>3}) {label}  [{value}]")


def _prompt_enum_multi(
    choices: Sequence[tuple[str, str]],
    *,
    hint: str = "  Pick numbers (comma-separated), or blank to skip",
) -> list[str] | None:
    if not choices:
        typer.echo("    (no choices available — skipping)")
        return None
    _render_enum_choices(choices)
    raw = typer.prompt(hint, default="", show_default=False)
    parts = _split_csv(raw)
    if not parts:
        return None
    picked: list[str] = []
    for part in parts:
        try:
            n = int(part)
        except ValueError:
            typer.echo(f"    ! '{part}' is not a number — ignoring.", err=True)
            continue
        if 1 <= n <= len(choices):
            picked.append(choices[n - 1][0])
        else:
            typer.echo(f"    ! {n} is out of range — ignoring.", err=True)
    return picked or None


def _prompt_enum_one(
    choices: Sequence[tuple[str, str]],
    *,
    hint: str = "  Pick one number, or blank to skip",
) -> str | None:
    if not choices:
        return None
    _render_enum_choices(choices)
    raw = typer.prompt(hint, default="", show_default=False)
    if not raw.strip():
        return None
    try:
        n = int(raw.strip())
    except ValueError:
        return None
    if 1 <= n <= len(choices):
        return choices[n - 1][0]
    return None


def _prompt_rate_card() -> dict[str, Any] | None:
    """Per-platform pricing loop. Blank platform finishes the section."""
    typer.echo("    Format: per-platform pricing per deliverable. Blank platform to finish.")
    rate_card: dict[str, Any] = {}
    while True:
        platform = typer.prompt(
            "    Platform (instagram / tiktok / youtube / ...; blank to finish)",
            default="",
            show_default=False,
        ).strip()
        if not platform:
            break
        currency = typer.prompt("    Currency (ISO 4217, e.g. GBP / USD / EUR)", default="GBP")
        deliverables: dict[str, Any] = {}
        while True:
            deliverable = typer.prompt(
                "      Deliverable (reel / story / feed_post / ...; blank to finish)",
                default="",
                show_default=False,
            ).strip()
            if not deliverable:
                break
            price_raw = typer.prompt(f"      Price for {deliverable}")
            price = _coerce_decimal(price_raw)
            if price is None:
                typer.echo("      ! Couldn't read that as a number — skipping.", err=True)
                continue
            deliverables[deliverable] = {"price": price}
        if deliverables:
            rate_card[platform] = {"currency": currency, "deliverables": deliverables}
    return rate_card or None


# ── Auto-mode canned answers ──────────────────────────────────────────


def _default_answer_for(field_path: str) -> Any:
    table: dict[str, Any] = {
        "pronouns": "she/her",
        "legal_name": "Auto Talent (Legal)",
        "gender_identity": "female",
        "bio": "Auto-generated bio for the test talent.",
        "date_of_birth": "1995-06-15",
        "career_start_year": 2018,
        "content_niches": ["beauty"],
        "professional_roles": ["creator"],
        "content_pillars": ["GRWM"],
        "languages": ["en"],
        "brand_preferences.preferred_industries": ["beauty"],
        "brand_preferences.blocked_industries": ["gambling"],
        "brand_preferences.values_red_lines": ["diet culture"],
        "contact.email": "talent@example.com",
        "contact.phone": "+1-555-0100",
        "commission_override.rate": 0.20,
    }
    return table.get(field_path)


# ── Step 5 questionnaire renderer ─────────────────────────────────────


def _resolve_choices(choices_source: str | None) -> list[tuple[str, str]]:
    """Resolve enum choices (static -> taxonomy lookup)."""
    if not choices_source:
        return []
    from app.services.questionnaire import static_choices

    static = static_choices(choices_source)
    if static is not None:
        return list(static)
    try:
        from app.utils.taxonomies import get_taxonomies

        tx = get_taxonomies()
        if choices_source == "niches":
            return [(nid, n.get("label", nid)) for nid, n in tx.niches.items()]
        if choices_source == "industries":
            return [(iid, i.get("label", iid)) for iid, i in tx.industries.items()]
    except Exception as exc:
        typer.echo(
            f"    ! taxonomy '{choices_source}' unavailable ({exc!s}) — skipping",
            err=True,
        )
    return []


def _prompt_one_question(question: dict[str, Any], *, auto: bool) -> tuple[bool, Any]:
    """Render one question + collect an answer. Returns ``(was_answered, value)``."""
    field_path = question["field_path"]
    label = question["label"]
    kind = question["kind"]
    required = question["required"]
    choices_source = question.get("choices_source")

    _print_label(label, required=required)

    if auto:
        canned = _default_answer_for(field_path)
        if canned is None or canned == []:
            return False, None
        typer.echo(f"    (auto) {canned!r}")
        return True, canned

    if kind == "rate_card":
        value = _prompt_rate_card()
        return (value is not None, value)

    if kind == "enum_multi":
        choices = _resolve_choices(choices_source)
        value = _prompt_enum_multi(choices)
        return (value is not None, value)

    if kind == "enum_one":
        choices = _resolve_choices(choices_source)
        value = _prompt_enum_one(choices)
        return (value is not None, value)

    if kind == "enum_one_or_text":
        choices = _resolve_choices(choices_source)
        value = _prompt_enum_one_or_text(choices)
        return (value is not None, value)

    if kind == "multiline":
        raw = typer.prompt("    > ", default="", show_default=False)
        return (bool(raw.strip()), raw.strip() or None)

    if kind == "number_decimal":
        raw = typer.prompt("    > ", default="", show_default=False)
        if not raw.strip():
            return False, None
        coerced = _coerce_decimal(raw)
        if coerced is None:
            typer.echo("    ! Couldn't read that as a number — skipping.", err=True)
            return False, None
        return True, coerced

    if kind == "number_int":
        raw = typer.prompt("    > ", default="", show_default=False)
        if not raw.strip():
            return False, None
        coerced = _coerce_int(raw)
        if coerced is None:
            typer.echo("    ! Couldn't read that as an integer — skipping.", err=True)
            return False, None
        return True, coerced

    if kind == "date_iso":
        raw = typer.prompt("    > ", default="", show_default=False)
        if not raw.strip():
            return False, None
        coerced = _coerce_iso_date(raw)
        if coerced is None:
            typer.echo("    ! Couldn't parse that date — expected YYYY-MM-DD.", err=True)
            return False, None
        return True, coerced

    if kind == "csv":
        raw = typer.prompt("    > ", default="", show_default=False)
        if not raw.strip():
            return False, None
        return True, _split_csv(raw)

    # Default: free text (text / email / phone).
    raw = typer.prompt("    > ", default="", show_default=False)
    if not raw.strip():
        return False, None
    return True, raw.strip()


def _drive_questionnaire(client: Any, talent_id: str, *, auto: bool) -> None:
    """Walk the questionnaire locally, POST only when the operator answers."""
    from app.services.questionnaire import all_questions

    typer.echo("\nStep 5 — Questionnaire")
    current = _get_json(client, f"/api/v1/talents/{talent_id}")["data"]
    talent_data = dict(current.get("data") or {})
    answered = 0
    skipped = 0
    for q in all_questions():
        if _question_field_present(talent_data, q.field_path):
            continue
        question_dict = {
            "field_path": q.field_path,
            "label": q.label,
            "kind": q.kind,
            "required": q.required,
            "choices_source": q.choices_source,
        }
        was_answered, value = _prompt_one_question(question_dict, auto=auto)
        if not was_answered:
            skipped += 1
            continue
        _post_json(
            client,
            f"/api/v1/talents/{talent_id}/questionnaire/answer",
            {"field_path": q.field_path, "value": value},
        )
        _echo_captured(q.field_path, value)
        _set_local_path(talent_data, q.field_path, value)
        answered += 1
    typer.echo(f"  / questionnaire: {answered} answered, {skipped} skipped")


def _question_field_present(data: dict[str, Any], dotted_path: str) -> bool:
    cur: Any = data
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    if cur is None:
        return False
    if isinstance(cur, str) and not cur.strip():
        return False
    return not (isinstance(cur, list | dict) and not cur)


def _set_local_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cur = data
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


# ── Steps 6 + 7: bulk-paste with LLM tidy ─────────────────────────────


def _prompt_multiline_text(label: str, hint: str) -> str:
    """Collect free-form multi-line text. Empty line finishes input."""
    _print_label(label)
    typer.echo(f"    {hint}")
    typer.echo("    Paste / type below. Empty line to finish.")
    lines: list[str] = []
    while True:
        try:
            line = typer.prompt("    ", default="", show_default=False, prompt_suffix="")
        except typer.Abort:
            break
        if not line.strip() and lines:
            break
        if not line.strip():
            return ""
        lines.append(line)
    return "\n".join(lines).strip()


def _drive_brand_history(client: Any, talent_id: str, *, auto: bool) -> None:
    """Step 6 — bulk-paste past brand collaborations; LLM tidies."""
    if auto:
        return
    text = _prompt_multiline_text(
        "Step 6 — Past brand collaborations",
        "List every brand the talent has worked with (any format — names separated by spaces, newlines, commas).",
    )
    if not text:
        typer.echo("  (no brands entered)")
        return
    typer.echo("    parsing (LLM)...")
    resp = _post_json(client, f"/api/v1/talents/{talent_id}/brand-history/bulk", {"text": text})
    data = resp["data"]
    typer.echo(
        f"  / parsed {data['parsed_count']} brand(s); {data['added_count']} added to previous_brands[]"
    )
    for entry in data.get("entries") or []:
        ind = entry.get("industry_id") or "?"
        typer.echo(f"    - {entry['brand']:<30s}  industry={ind}")


def _drive_similar_talent(client: Any, talent_id: str, *, auto: bool) -> None:
    """Step 7 — bulk-paste comparable creators; LLM tidies into seed entries."""
    if auto:
        return
    text = _prompt_multiline_text(
        "Step 7 — Similar / comparable creators",
        "List creators you'd consider comparable to this talent.",
    )
    if not text:
        typer.echo("  (no similar creators entered)")
        return
    typer.echo("    parsing (LLM)...")
    resp = _post_json(client, f"/api/v1/talents/{talent_id}/similar-talent/bulk", {"text": text})
    data = resp["data"]
    typer.echo(
        f"  / parsed {data['parsed_count']} creator(s); {data['added_count']} added to similar_talent[]"
    )
    for entry in data.get("entries") or []:
        typer.echo(f"    - {entry['name']}")


# ── Top-level wizard ──────────────────────────────────────────────────


def _drive_oauth_callback(client: Any, *, platform: str, callback_url: str) -> dict[str, Any]:
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    state = (qs.get("state") or [None])[0]
    if not code or not state:
        typer.echo("  X pasted URL missing code or state query param.", err=True)
        raise typer.Exit(code=1)
    r = client.get(
        f"/api/v1/webhooks/{platform}/oauth_callback",
        params={"code": code, "state": state},
    )
    if r.status_code >= 400:
        typer.echo(f"  X callback failed: HTTP {r.status_code} - {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def run_wizard(
    *,
    api_base_url: str = DEFAULT_API_BASE,
    auto: bool = False,
    skip_oauth: bool = False,
    skip_activate: bool = False,
    talent_name: str | None = None,
    talent_country: str = "US",
    initial_platform: str = "instagram",
    initial_handle: str = "@auto-talent",
    timeout_seconds: float = 30.0,
    client: Any = None,
) -> dict[str, Any]:
    """Walk Phase 1 against the running API. Returns the final talent dict."""
    name = talent_name or ("Auto Talent" if auto else None)
    typer.echo(f"NATIV2 Phase 1 — Talent Onboarding wizard (api={api_base_url})")
    client_ctx: Any
    if client is None:
        client_ctx = httpx.Client(base_url=api_base_url, timeout=timeout_seconds)
    else:
        client_ctx = _NullCM(client)
    with client_ctx as client:
        # ── Step 1: identity seed ─────────────────────────────────────
        _print_label("Step 1 — Talent identity")
        if name is None:
            name = typer.prompt("    Talent name")

        if auto:
            country = talent_country
        else:
            _print_label("    Country")
            country = _prompt_enum_one(_COUNTRIES) or talent_country
        platform = (
            initial_platform
            if auto
            else typer.prompt(
                "    Initial platform (instagram / tiktok / youtube / ...)",
                default=initial_platform,
            )
        )
        handle = (
            initial_handle
            if auto
            else typer.prompt(
                f"    Talent {platform} handle (e.g. @kevincooney)", default=initial_handle
            )
        )
        seed_resp = _post_json(
            client,
            "/api/v1/talents",
            {
                "name": name,
                "country": country,
                "initial_platform_name": platform,
                "initial_platform_handle": handle,
            },
        )
        talent_id = seed_resp["data"]["talent_id"]
        _echo_captured("talent_id", talent_id)

        # ── Step 2: OAuth ─────────────────────────────────────────────
        _print_label("Step 2 — Platform OAuth (Meta + TikTok)")
        for plat in ("meta", "tiktok"):
            redirect_uri = (
                f"https://app.example.com/oauth/{plat}"
                if auto
                else typer.prompt(
                    f"    {plat} redirect_uri",
                    default=f"https://app.example.com/oauth/{plat}",
                )
            )
            oauth_resp = _post_json(
                client,
                f"/api/v1/talents/{talent_id}/platforms/start-oauth",
                {
                    "platform": plat,
                    "redirect_uri": redirect_uri,
                    "scopes": (
                        ["instagram_business_basic"] if plat == "meta" else ["user.info.basic"]
                    ),
                },
            )
            typer.echo(f"    {plat} authorize URL: {oauth_resp['data']['authorize_url']}")
            if skip_oauth:
                continue
            pasted = typer.prompt(
                f"    Paste the full {plat} redirect URL once consent is complete (blank to skip)",
                default="",
                show_default=False,
            )
            if not pasted.strip():
                continue
            cb_resp = _drive_oauth_callback(client, platform=plat, callback_url=pasted)
            typer.echo(f"    / {plat} callback: success={cb_resp['data'].get('success')}")

        # ── Step 5: questionnaire ─────────────────────────────────────
        _drive_questionnaire(client, talent_id, auto=auto)

        # ── Step 6: bulk brand history ────────────────────────────────
        _drive_brand_history(client, talent_id, auto=auto)

        # ── Step 7: bulk similar talent ───────────────────────────────
        _drive_similar_talent(client, talent_id, auto=auto)

        # ── Step 8: activate ──────────────────────────────────────────
        if skip_activate:
            typer.echo(
                "\nStep 8 — Activate skipped (--skip-activate)."
                " Rerun without the flag once every linked platform has scope_validated_at."
            )
        else:
            _print_label("Step 8 — Activate")
            try:
                _post_json(client, f"/api/v1/talents/{talent_id}/activate", {})
            except typer.Exit:
                typer.echo(
                    "    ! activate failed — finish OAuth + questionnaire then re-run.",
                    err=True,
                )
                raise

        final = _get_json(client, f"/api/v1/talents/{talent_id}")["data"]
        typer.echo(f"\n/ Phase 1 complete. talent_id={final['talent_id']} status={final['status']}")
        return final


__all__: tuple[str, ...] = ("DEFAULT_API_BASE", "run_wizard")
