"""Interactive Phase-1 talent-onboarding CLI wizard.

Walks the operator through the 10 onboarding steps (``docs/onboarding_workflow.md``)
by calling the same ``/api/v1/talents`` REST surface a UI would. Same code
path validated twice.

Usage::

    just dev-api    # in another terminal
    uv run nativ test phase 1
    # Non-interactive defaults (e.g. for the e2e test):
    uv run nativ test phase 1 --auto --skip-oauth

OAuth handling: the CLI cannot browser-launch the platform consent flow,
so Step 2 prints the authorize URL + state token and asks the operator to
visit the URL, complete consent, and paste back the redirected callback URL
(``…?code=…&state=…``). The wizard then forwards that URL to the callback
endpoint. With ``--skip-oauth``, Step 2 prints the authorize URL and moves
on without driving the callback — useful for ``--auto`` smoke runs.

``--skip-activate`` skips the final ``/activate`` POST (mandatory together
with ``--skip-oauth`` because activation requires ``scope_validated_at``
on every linked platform).
"""

from __future__ import annotations

import time
from pathlib import Path
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


def _prompt(label: str, default: str | None = None, *, auto: bool = False) -> str:
    if auto:
        if default is None:
            raise typer.BadParameter(f"--auto mode requires a default for {label!r}")
        return default
    return typer.prompt(label, default=default)


def _post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        path, json=payload, headers={"Idempotency-Key": f"talent-wizard-{int(time.time() * 1000)}"}
    )
    if r.status_code >= 400:
        typer.echo(f"  X {path} -> HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _patch_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = client.patch(
        path, json=payload, headers={"Idempotency-Key": f"talent-wizard-{int(time.time() * 1000)}"}
    )
    if r.status_code >= 400:
        typer.echo(f"  X {path} -> HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _get_json(client: httpx.Client, path: str) -> dict[str, Any]:
    r = client.get(path)
    if r.status_code >= 400:
        typer.echo(f"  X {path} -> HTTP {r.status_code}: {r.text}", err=True)
        raise typer.Exit(code=1)
    return r.json()


def _drive_oauth_callback(
    client: httpx.Client, *, platform: str, callback_url: str
) -> dict[str, Any]:
    """Forward the pasted ``?code=…&state=…`` URL to the callback endpoint."""
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


def _drive_questionnaire(
    client: httpx.Client, talent_id: str, *, auto: bool, max_iterations: int = 25
) -> None:
    """Loop /questionnaire/next + /answer until ``complete`` or limit reached."""
    typer.echo("\nStep 5 - Questionnaire")
    for i in range(max_iterations):
        q = _post_json(client, f"/api/v1/talents/{talent_id}/questionnaire/next", {})
        if q["data"].get("complete"):
            typer.echo(f"  / questionnaire complete after {i} answers")
            return
        field_path = q["data"]["field_path"]
        prompt = q["data"]["prompt"]
        if auto:
            default = _default_answer_for(field_path)
            value: Any = default
            typer.echo(f"  {field_path}: {default} (--auto)")
        else:
            value = typer.prompt(f"  {prompt} [{field_path}]")
        _post_json(
            client,
            f"/api/v1/talents/{talent_id}/questionnaire/answer",
            {"field_path": field_path, "value": value},
        )
    typer.echo(
        f"  ! questionnaire hit the {max_iterations}-iter cap; not all fields filled.",
        err=True,
    )


def _default_answer_for(field_path: str) -> Any:
    """Sensible canned answers for ``--auto`` mode."""
    return {
        "pronouns": "she/her",
        "contact.email": "talent@example.com",
        "contact.phone": "+1-555-0100",
        "billing_entity.legal_name": "Talent Co.",
        "billing_entity.country": "US",
    }.get(field_path, "auto-default")


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
    starter_slug: str = "management",
    timeout_seconds: float = 30.0,
    client: Any = None,
) -> dict[str, Any]:
    """Walk Phase 1 against the running API. Returns the final talent dict.

    ``client`` is an optional pre-built ``httpx.Client`` — useful for e2e
    tests that drive the wizard against an in-process ASGI transport
    instead of a network address. Pyright deliberately sees ``Any`` here
    because the e2e tests pass a Starlette ``TestClient`` proxy that
    quacks like an httpx client but is not a subclass.
    """
    name = talent_name or ("Auto Talent" if auto else None)
    typer.echo(f"NATIV2 Phase 1 - Talent Onboarding wizard (api={api_base_url})\n")
    client_ctx: Any
    if client is None:
        client_ctx = httpx.Client(base_url=api_base_url, timeout=timeout_seconds)
    else:
        client_ctx = _NullCM(client)
    with client_ctx as client:
        # Step 1 - Seed
        typer.echo("Step 1 - Talent identity")
        if name is None:
            name = _prompt("Talent name", default=None, auto=False)
        country = _prompt("Country (2-letter ISO)", default=talent_country, auto=auto)
        platform = _prompt("Initial platform", default=initial_platform, auto=auto)
        handle = _prompt(f"Talent {platform} handle", default=initial_handle, auto=auto)
        seed_resp = _post_json(
            client,
            "/api/v1/talents",
            {
                "name": name,
                "country": country,
                "initial_platform_name": platform,
                "initial_platform_handle": handle,
                "content_niches": ["lifestyle"],
            },
        )
        talent_id = seed_resp["data"]["talent_id"]
        typer.echo(f"  / created talent_id={talent_id} status={seed_resp['data']['status']}")

        # Step 2 - OAuth
        typer.echo("\nStep 2 - Platform OAuth (Meta + TikTok)")
        for plat in ("meta", "tiktok"):
            redirect_uri = _prompt(
                f"  {plat} redirect_uri",
                default="https://app.example.com/oauth/" + plat,
                auto=auto,
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
            authorize_url = oauth_resp["data"]["authorize_url"]
            state = oauth_resp["data"]["state"]
            typer.echo(f"  authorize_url: {authorize_url}")
            typer.echo(f"  state: {state}")
            if skip_oauth:
                typer.echo(f"  (skip-oauth): not driving the {plat} callback.")
                continue
            pasted = typer.prompt(f"  Paste the full {plat} redirect URL once consent is complete")
            cb_resp = _drive_oauth_callback(client, platform=plat, callback_url=pasted)
            typer.echo(f"  / {plat} callback: success={cb_resp['data'].get('success')}")

        # Step 3 - Media pack (optional; auto-skips in --auto mode)
        if not auto:
            typer.echo("\nStep 3 - Media pack upload (optional, leave blank to skip)")
            local_pack = typer.prompt("  Local file path", default="")
            if local_pack.strip():
                _upload_and_extract(client, talent_id, Path(local_pack.strip()))
        else:
            typer.echo("\nStep 3 - Media pack (skipped in --auto)")

        # Step 5 - Questionnaire
        _drive_questionnaire(client, talent_id, auto=auto)

        # Step 6 - Resolve industry for one brand
        typer.echo("\nStep 6 - Brand history industry resolution")
        brand = _prompt("  Past brand collaboration name (or blank to skip)", default="", auto=auto)
        if brand.strip():
            inference = _post_json(
                client,
                f"/api/v1/talents/{talent_id}/brands/resolve-industry",
                {"brand_name": brand.strip()},
            )
            data = inference["data"]
            typer.echo(
                f"  / {brand} -> industry_id={data['industry_id']} "
                f"source={data['source']} confidence={data['confidence']:.2f}"
            )

        # Step 7 - Similar-talent seed
        typer.echo("\nStep 7 - Similar talent seed")
        similar = _prompt(
            "  Manually-seeded similar talent name (blank to skip)",
            default="",
            auto=auto,
        )
        if similar.strip():
            _post_json(
                client,
                f"/api/v1/talents/{talent_id}/similar-talent",
                {"name": similar.strip(), "handles": ["@auto-seed"]},
            )

        # Step 7.5 - Contract template
        typer.echo("\nStep 7.5 - Contract template starter")
        starter = _prompt("  Starter slug", default=starter_slug, auto=auto)
        _post_json(
            client,
            f"/api/v1/talents/{talent_id}/contract-template/adopt-starter",
            {"starter_slug": starter},
        )
        gov_law = _prompt("  Governing law (jurisdiction)", default="California", auto=auto)
        _patch_json(
            client,
            f"/api/v1/talents/{talent_id}/contract-template",
            {"default_governing_law": gov_law},
        )

        # Step 8 - Activate
        if skip_activate:
            typer.echo(
                "\nStep 8 - Activate skipped (--skip-activate)."
                " Rerun without the flag once all platforms have scope_validated_at."
            )
        else:
            typer.echo("\nStep 8 - Activate")
            try:
                _post_json(client, f"/api/v1/talents/{talent_id}/activate", {})
            except typer.Exit:
                typer.echo(
                    "  ! activate failed - run /activate manually after OAuth callbacks "
                    "+ questionnaire are finished.",
                    err=True,
                )
                raise

        final = _get_json(client, f"/api/v1/talents/{talent_id}")["data"]
        typer.echo(f"\n/ Phase 1 complete. talent_id={final['talent_id']} status={final['status']}")
        return final


def _upload_and_extract(client: httpx.Client, talent_id: str, local_pack: Path) -> None:
    suffix = local_pack.suffix.lower()
    content_type = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "application/octet-stream")
    presign = _post_json(
        client,
        f"/api/v1/talents/{talent_id}/media-pack/upload-url",
        {},
    )
    upload_url = presign["data"]["upload_url"]
    key = presign["data"]["key"]
    with local_pack.open("rb") as fh, httpx.Client() as anon:
        put = anon.put(upload_url, content=fh.read(), headers={"Content-Type": content_type})
    if put.status_code >= 400:
        typer.echo(f"  X upload failed: HTTP {put.status_code} - {put.text}", err=True)
        raise typer.Exit(code=1)
    extract = _post_json(
        client,
        f"/api/v1/talents/{talent_id}/media-pack/extract",
        {"s3_keys": [key], "run_llm_extraction": False},
    )
    typer.echo(f"  / parsed {extract['data']['artefact_count']} artefact(s)")
