from typing import Annotated

import typer

from mpt_extension_sdk_v6.runtime.runner import run_extension

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    local: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--local", help="Run with Uvicorn (local development mode)"),
    ] = False,
) -> None:
    """Start the extension server."""
    run_extension(local=local)


@app.command()
def validate() -> None:
    """Validate meta.yaml consistency with registered route handlers."""
    typer.echo("validate command is not yet implemented", err=True)
    raise typer.Exit(code=1)


def main() -> None:
    """Main entry point for the `swoext` CLI."""
    app()


if __name__ == "__main__":
    main()
