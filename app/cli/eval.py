"""``nativ test eval --pack X --record|--real``.

Runs the LLM eval suite for a pack type. M2 ships the discovery_prep pack
eval (cassette-based via vcrpy). M11+ pack milestones add their own evals.
"""

from __future__ import annotations

import subprocess

import typer

eval_app = typer.Typer()


@eval_app.callback(invoke_without_command=True)
def main(
    pack: str = typer.Option("discovery_prep", "--pack", help="Pack type to eval."),
    record: bool = typer.Option(False, "--record", help="Re-record cassettes."),
    real: bool = typer.Option(False, "--real", help="Run against live Anthropic API."),
) -> None:
    """Run the LLM eval suite for ``--pack``."""
    if pack != "discovery_prep":
        typer.echo(f"`nativ test eval --pack {pack}` lands with milestone M11+.")
        raise typer.Exit(code=0)

    args = ["uv", "run", "pytest", "tests/llm_eval/", "-q"]
    if real:
        args.extend(["-m", "live"])
        typer.echo("Running against LIVE Anthropic API (costs $).")
    if record:
        args.append("--llm-record")
        typer.echo("Re-recording cassettes.")
    result = subprocess.run(args, check=False)  # noqa: S603 — fixed-args CLI invocation
    raise typer.Exit(code=result.returncode)
