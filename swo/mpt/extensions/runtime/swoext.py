import click
from django.utils.module_loading import import_string
from swo.mpt.extensions.runtime import get_version
from swo.mpt.extensions.runtime.utils import show_banner


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"SoftwareOne Extension CLI, version {get_version()}")
    ctx.exit()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--version",
    is_flag=True,
    expose_value=False,
    is_eager=True,
    callback=print_version,
)
@click.pass_context
def cli(ctx):
    """SoftwareOne Extension CLI"""
    show_banner()


for cmd in map(
    import_string,
    (
        "swo.mpt.extensions.runtime.commands.run.run",
        "swo.mpt.extensions.runtime.commands.django.django",
    ),
):
    cli.add_command(cmd)


def make_django_command(name, django_command=None, help=None):
    "A wrapper to convert a Django subcommand a Click command"
    if django_command is None:
        django_command = name

    @click.command(
        name=name,
        help=help,
        add_help_option=False,
        context_settings=dict(ignore_unknown_options=True),
    )
    @click.argument("management_args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def inner(ctx, management_args):
        from swo.mpt.extensions.runtime.commands.django import django

        ctx.params["management_args"] = (django_command,) + management_args
        ctx.forward(django)

    return inner


cli.add_command(make_django_command("shell", help="Open Django console"))


def main():
    cli(standalone_mode=False)


if __name__ == "__main__":
    main()
