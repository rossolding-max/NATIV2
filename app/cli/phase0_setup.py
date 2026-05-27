"""Interactive Phase-0 agency-setup CLI wizard.

Walks the operator through the 9 setup steps by calling the REST surface
shipped in PR 2. Same code path validated twice: the wizard is just
a thin client of the same endpoints a UI would call.

Usage:

    just dev-api    # in another terminal
    uv run nativ test phase 0 setup
    # or non-interactive defaults (e.g. for the e2e test):
    uv run nativ test phase 0 setup --auto --skip-warmup

Network behaviour: makes plain ``httpx`` calls to ``--api-base-url``
(default ``http://127.0.0.1:8000``). For local-file logo uploads the
wizard fetches a presigned PUT URL from the server and PUTs the file
bytes directly to MinIO/S3.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import typer

DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_DKIM_SELECTOR = "smartlead"


def _prompt(label: str, default: str | None = None, *, auto: bool = False) -> str:
    """Prompt the operator. In ``--auto`` mode, use the default (or raise)."""
    if auto:
        if default is None:
            raise typer.BadParameter(f"--auto mode requires a default for {label!r}")
        return default
    return typer.prompt(label, default=default)


def _post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        path, json=payload, headers={"Idempotency-Key": f"wizard-{int(time.time() * 1000)}"}
    )
    if r.status_code >= 400:
        typer.echo(f"  ✗ {path} → HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _patch_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.patch(
        path, json=payload, headers={"Idempotency-Key": f"wizard-{int(time.time() * 1000)}"}
    )
    if r.status_code >= 400:
        typer.echo(f"  ✗ {path} → HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _upload_logo(client: httpx.Client, logo_path: Path) -> str:
    """Upload a logo file via the presigned-PUT endpoint. Returns the public URL."""
    suffix = logo_path.suffix.lower()
    content_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
    }.get(suffix)
    if content_type is None:
        raise typer.BadParameter(f"unsupported logo extension {suffix!r}")
    size = logo_path.stat().st_size

    presign = _post_json(
        client,
        "/api/v1/agencies/me/branding/logo-upload-url",
        {"content_type": content_type, "size_bytes": size},
    )
    upload_url = presign["data"]["upload_url"]
    public_url = presign["data"]["public_url"]
    with logo_path.open("rb") as fh:
        with httpx.Client() as anon:
            r = anon.put(upload_url, content=fh.read(), headers={"Content-Type": content_type})
        if r.status_code >= 400:
            typer.echo(f"  ✗ logo PUT failed: HTTP {r.status_code} — {r.text}", err=True)
            raise typer.Exit(code=1)
    return public_url


def _wait_for_warmup(
    client: httpx.Client, *, interval_seconds: float = 60.0, skip: bool = False
) -> None:
    """Poll GET /me until warmup_status == complete OR --skip-warmup was set."""
    if skip:
        typer.echo("  (skip-warmup): leaving warmup_status untouched.")
        return
    typer.echo("Waiting for mailbox warmup to complete (Ctrl-C to stop and rerun later)...")
    while True:
        r = client.get("/api/v1/agencies/me")
        r.raise_for_status()
        data = r.json()["data"]
        status = data["data"]["sending_mailboxes"][0]["warmup_status"]
        if status == "complete":
            typer.echo("  ✓ warmup complete")
            return
        typer.echo(f"  … warmup_status={status} — sleeping {interval_seconds:.0f}s")
        time.sleep(interval_seconds)


def run_wizard(
    *,
    api_base_url: str = DEFAULT_API_BASE,
    auto: bool = False,
    skip_warmup: bool = False,
    logo_path: Path | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Walk through Phase 0 against the running API. Returns the final agency dict."""
    typer.echo(f"NATIV2 Phase 0 — Agency Setup wizard (api={api_base_url})\n")
    with httpx.Client(base_url=api_base_url, timeout=timeout_seconds) as client:
        # Step 1
        typer.echo("Step 1 — Agency identity")
        agency_slug = _prompt("Agency slug (lowercase, hyphens ok)", default="acme", auto=auto)
        name = _prompt("Agency name", default="Acme Talent", auto=auto)
        domain = _prompt("Agency domain", default="acme.com", auto=auto)
        company_address = _prompt("Company mailing address", default="1 Main St, City", auto=auto)
        website_url = _prompt("Agency website URL", default=f"https://{domain}", auto=auto)
        _post_json(
            client,
            "/api/v1/agencies",
            {
                "agency_slug": agency_slug,
                "name": name,
                "domain": domain,
                "company_address": company_address,
                "website_url": website_url,
            },
        )

        # Step 1.5 — Branding
        typer.echo("\nStep 1.5 — Branding")
        primary_color = _prompt("Primary brand color (#RRGGBB)", default="#0F4C81", auto=auto)
        text_color = _prompt("Body text color", default="#1A1A1A", auto=auto)
        branding_patch: dict[str, Any] = {"primary_color": primary_color, "text_color": text_color}
        if logo_path is not None:
            typer.echo(f"  Uploading logo from {logo_path}...")
            branding_patch["logo_url"] = _upload_logo(client, logo_path)
        _patch_json(client, "/api/v1/agencies/me/branding", branding_patch)

        # Step 2 — Agent
        typer.echo("\nStep 2 — Named agent")
        agent_id = _prompt("Agent slug", default="sarah", auto=auto)
        agent_name = _prompt("Agent name", default="Sarah Chen", auto=auto)
        agent_email = _prompt("Agent email", default=f"{agent_id}@{domain}", auto=auto)
        _patch_json(
            client,
            "/api/v1/agencies/me/agent",
            {"agent_id": agent_id, "name": agent_name, "email": agent_email},
        )

        # Step 3 — DNS
        typer.echo("\nStep 3 — DNS verification")
        dkim_selector = _prompt(
            "DKIM selector (default 'smartlead')", default=DEFAULT_DKIM_SELECTOR, auto=auto
        )
        dns_resp = _post_json(
            client, "/api/v1/agencies/me/dns/refresh", {"dkim_selector": dkim_selector}
        )
        if not dns_resp["data"]["verified"]:
            typer.echo("  ! DNS not yet verified. Add records in Smartlead UI, then rerun.")
            # DNS-verified is a hard gate: Step 4 (mailbox), Step 6 (warmup),
            # Step 7 (activate) all require Smartlead's domain config to be live.
            # Exit cleanly in BOTH interactive and ``--auto`` mode; under
            # respx-mocked Smartlead in tests, the mock returns verified=true
            # so the wizard progresses past this point.
            raise typer.Exit(code=0)

        # Step 4 — Mailbox
        typer.echo("\nStep 4 — Sending mailbox")
        mailbox_address = _prompt("Mailbox address", default=agent_email, auto=auto)
        smtp_host = _prompt("SMTP host", default="smtp.gmail.com", auto=auto)
        smtp_port = int(_prompt("SMTP port", default="465", auto=auto))
        smtp_username = _prompt("SMTP username", default=mailbox_address, auto=auto)
        smtp_password = _prompt("SMTP password (app-specific)", default="app-pw", auto=auto)
        imap_host = _prompt("IMAP host", default="imap.gmail.com", auto=auto)
        imap_port = int(_prompt("IMAP port", default="993", auto=auto))
        daily_cap = int(_prompt("Daily send cap", default="50", auto=auto))
        _post_json(
            client,
            "/api/v1/agencies/me/mailbox",
            {
                "agent_id": agent_id,
                "mailbox_address": mailbox_address,
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
                "smtp_username": smtp_username,
                "smtp_password": smtp_password,
                "imap_host": imap_host,
                "imap_port": imap_port,
                "daily_send_cap": daily_cap,
            },
        )

        # Step 5 — Signature
        typer.echo("\nStep 5 — Default signature template")
        sig_default = (
            f"Best,\n{{agent_name}} — {name}\n{{agency_address}}\nUnsubscribe: {{unsubscribe_link}}"
        )
        sig = _prompt(
            "Signature template (must include {agent_name}, {agency_address}, {unsubscribe_link})",
            default=sig_default,
            auto=auto,
        )
        _patch_json(client, "/api/v1/agencies/me/signature", {"default_signature_template": sig})

        # Step 5.5 — Invoice template
        typer.echo("\nStep 5.5 — Invoice template")
        terms_days = int(_prompt("Default payment terms (days)", default="30", auto=auto))
        tax_handling = _prompt(
            "Tax handling (none|vat_inclusive|vat_added|sales_tax)", default="none", auto=auto
        )
        invoice_footer = _prompt(
            "Invoice footer", default=f"Thank you for working with {name}.", auto=auto
        )
        payment_instructions = _prompt(
            "Payment instructions (markdown)", default="Bank transfer details: ...", auto=auto
        )
        _patch_json(
            client,
            "/api/v1/agencies/me/invoice-template",
            {
                "default_payment_terms_days": terms_days,
                "tax_handling": tax_handling,
                "invoice_footer": invoice_footer,
                "payment_instructions_markdown": payment_instructions,
            },
        )

        # Step 5.5b — Commission
        typer.echo("\nStep 5.5b — Commission defaults")
        rate = float(_prompt("Default commission rate (0.0-1.0)", default="0.20", auto=auto))
        model = _prompt(
            "Commission model",
            default="agency_invoices_brand_pays_talent_net",
            auto=auto,
        )
        _patch_json(
            client,
            "/api/v1/agencies/me/commission-defaults",
            {"default_commission_rate": rate, "default_commission_model": model},
        )

        # Step 6 — Wait for warmup
        typer.echo("\nStep 6 — Mailbox warmup")
        _wait_for_warmup(client, skip=skip_warmup)

        # Step 7 — Activate
        typer.echo("\nStep 7 — Activate")
        if skip_warmup:
            typer.echo(
                "  (skip-warmup): skipping /activate; rerun without "
                "--skip-warmup once warmup completes."
            )
        else:
            _post_json(client, "/api/v1/agencies/me/activate", {})

        # Final
        r = client.get("/api/v1/agencies/me")
        final = r.json()["data"]
        typer.echo(f"\n✓ Agency setup complete. status={final['status']}")
        return final


def _async_runner(
    *,
    api_base_url: str,
    auto: bool,
    skip_warmup: bool,
    logo_path: Path | None,
) -> dict[str, Any]:
    """Helper that allows the typer command to live in this module + be testable."""
    return run_wizard(
        api_base_url=api_base_url, auto=auto, skip_warmup=skip_warmup, logo_path=logo_path
    )


def run_wizard_typer(
    api_base_url: str = typer.Option(DEFAULT_API_BASE, "--api-base-url"),
    auto: bool = typer.Option(False, "--auto", help="Use default answers without prompting."),
    skip_warmup: bool = typer.Option(False, "--skip-warmup", help="Skip warmup poll + activate."),
    logo: Path | None = typer.Option(  # noqa: B008
        None, "--logo", help="Local path to a logo file to upload."
    ),
) -> None:
    """Typer-wrapped entry point so the CLI can call us directly."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    final = _async_runner(
        api_base_url=api_base_url, auto=auto, skip_warmup=skip_warmup, logo_path=logo
    )
    if final.get("status") != "active" and not skip_warmup:
        sys.exit(1)
