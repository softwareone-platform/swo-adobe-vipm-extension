import click


@click.command(add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@click.argument("management_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def django(ctx, management_args):
    "Execute Django subcommands."
    from swo.mpt.extensions.runtime.initializer import initialize

    initialize({})
    from django.core.management import execute_from_command_line

    execute_from_command_line(argv=[ctx.command_path] + list(management_args))
