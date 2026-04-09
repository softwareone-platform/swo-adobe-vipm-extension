from typing import Annotated

import typer

from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.runtime.models import MetaConfig
from mpt_extension_sdk_v6.runtime.runner import run_extension
from mpt_extension_sdk_v6.settings.runtime import RuntimeSettings

app = typer.Typer(no_args_is_help=True, invoke_without_command=True)
meta_app = typer.Typer(no_args_is_help=True)
app.add_typer(meta_app, name="meta")


@app.command()
def run(
    local: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--local", help="Run with Uvicorn (local development mode)"),
    ] = False,
) -> None:
    """Start the extension server."""
    run_extension(local=local)


@meta_app.command("generate")
def generate_meta() -> None:
    """Generate the metadata file from the extension app."""
    runtime_settings = RuntimeSettings.load()
    runtime_settings.meta_config.to_file(runtime_settings.meta_file_path)
    typer.echo(f"Generated {runtime_settings.meta_file_path}")


@app.command()
def validate() -> None:
    """Validate that the generated metadata matches the checked-in file."""
    runtime_settings = RuntimeSettings.load()
    generated_meta = runtime_settings.meta_config
    try:
        checked_in_meta = MetaConfig.from_file(runtime_settings.meta_file_path)
    except ConfigError:
        generated_meta_path = runtime_settings.meta_file_path.with_name(
            f"{runtime_settings.meta_file_path.stem}.generated"
            f"{runtime_settings.meta_file_path.suffix}"
        )
        generated_meta.to_file(generated_meta_path)
        typer.secho(
            f"Checked-in meta.yaml was not found. Generated file written to {generated_meta_path}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from None

    if checked_in_meta != generated_meta:
        generated_meta_path = runtime_settings.meta_file_path.with_name(
            f"{runtime_settings.meta_file_path.stem}.generated"
            f"{runtime_settings.meta_file_path.suffix}"
        )
        generated_meta.to_file(generated_meta_path)
        typer.secho(
            "Checked-in meta.yaml does not match metadata generated from the extension app. "
            f"Regenerated file written to {generated_meta_path}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Metadata is valid: {runtime_settings.meta_file_path}")


@app.callback()
def callback():
    """Callback for the CLI."""


def main() -> None:
    """Main entry point for the `swoext` CLI."""
    app()


if __name__ == "__main__":
    main()
