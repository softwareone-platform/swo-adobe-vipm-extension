import click
from swo.mpt.extensions.runtime.master import Master


@click.command()
@click.option("--color/--no-color", default=True)
@click.option("--debug", is_flag=True, default=False)
@click.option("--reload", is_flag=True, default=False)
def run(color, debug, reload):
    "Run the extension."
    master = Master(
        {
            "color": color,
            "debug": debug,
            "reload": reload,
        },
    )
    master.run()
