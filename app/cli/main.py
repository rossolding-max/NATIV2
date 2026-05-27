"""``nativ`` CLI entry point — typer app exposing the ``nativ test`` command tree.

Per ``docs/test_plan.md`` § 4.2. Subcommands light up per milestone:

- ``nativ test smoke {db,redis,minio,langfuse,llm,vendors}`` — works at M2.
- ``nativ test eval --pack X --record|--real`` — cassette eval (M2).
- ``nativ test fixtures status`` — works at M2 (queries Postgres).
- ``nativ test fixtures load synthetic`` — calls ``just seed`` (M1 brand import).
- ``nativ test phase`` / ``e2e`` / ``report`` — print "lands in M<X>" + exit 0.

Wired via ``pyproject.toml`` ``[project.scripts] nativ = "app.cli.main:app"``.
"""

from __future__ import annotations

import typer

from app.cli.eval import eval_app
from app.cli.fixtures import fixtures_app
from app.cli.smoke import smoke_app

app = typer.Typer(
    name="nativ",
    help="NATIV2 dev + test CLI. See `nativ test --help` for the test command tree.",
    no_args_is_help=True,
)

test_app = typer.Typer(name="test", help="Test runner commands.", no_args_is_help=True)
app.add_typer(test_app, name="test")

test_app.add_typer(smoke_app, name="smoke", help="Smoke tests (service connectivity).")
test_app.add_typer(eval_app, name="eval", help="LLM eval suite (cassette-based).")
test_app.add_typer(fixtures_app, name="fixtures", help="Fixture loading + status.")


# ── Phase walkthroughs ────────────────────────────────────────────────


from pathlib import Path  # noqa: E402

from app.cli.phase0_setup import DEFAULT_API_BASE, run_wizard  # noqa: E402


@test_app.command()
def phase(
    phase_id: str = typer.Argument(..., help="Phase to walk through (e.g. '0', '4.5')."),
    auto: bool = typer.Option(False, "--auto", help="Non-interactive mode."),
    skip_warmup: bool = typer.Option(
        False, "--skip-warmup", help="Phase 0 only: skip warmup poll."
    ),
    api_base_url: str = typer.Option(
        DEFAULT_API_BASE, "--api-base-url", help="Phase 0 only: base URL of the running API."
    ),
    logo: Path | None = typer.Option(  # noqa: B008
        None, "--logo", help="Phase 0 only: local logo file to upload."
    ),
) -> None:
    """Interactive phase walkthrough. M4 ships Phase 0; M5-M16 add their own."""
    if phase_id == "0":
        run_wizard(
            api_base_url=api_base_url,
            auto=auto,
            skip_warmup=skip_warmup,
            logo_path=logo,
        )
        return
    typer.echo(
        f"`nativ test phase {phase_id}` is not implemented yet. "
        "M4 ships Phase 0; M5-M16 land per-milestone (see docs/project_plan.md)."
    )


@test_app.command()
def e2e(
    pack: str | None = typer.Option(None, "--pack", help="Run e2e for a specific pack."),
) -> None:
    """End-to-end pipeline tests. First useful at M11 (discovery prep pack)."""
    _ = pack
    typer.echo("`nativ test e2e` lands at M11 (first AI pack milestone).")


@test_app.command()
def report() -> None:
    """Coverage + LLM-cost + perf report. Lands at M17 (production hardening)."""
    typer.echo("`nativ test report` lands at M17 (production hardening).")


if __name__ == "__main__":
    app()
