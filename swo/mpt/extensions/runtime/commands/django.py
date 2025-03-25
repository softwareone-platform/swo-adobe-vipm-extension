import click

from contextlib import nullcontext

from opentelemetry import trace


@click.command(add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@click.argument("management_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def django(ctx, management_args):
    "Execute Django subcommands."
    from swo.mpt.extensions.runtime.initializer import initialize

    initialize({
        "group": "swo.mpt.ext",
        "name": "app_config",
        "django_settings_module": "swo.mpt.extensions.runtime.djapp.conf.default",
    })
    from django.core.management import execute_from_command_line
    from django.conf import settings

    if settings.USE_APPLICATIONINSIGHTS:
        tracer = trace.get_tracer(__name__)
        tracer_context = tracer.start_as_current_span(
            f"Running Django command {management_args[0]}",
        )
    else:
        tracer_context = nullcontext()

    with tracer_context:
        execute_from_command_line(argv=[ctx.command_path] + list(management_args))
