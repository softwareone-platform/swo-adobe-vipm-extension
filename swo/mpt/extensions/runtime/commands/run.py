import click
from swo.mpt.extensions.runtime.master import Master


@click.command()
@click.option("--color/--no-color", default=True)
@click.option("--debug", is_flag=True, default=False)
@click.option("--reload", is_flag=True, default=False)
@click.option("--debug-py", default=None)
def run(color, debug, reload, debug_py):
    "Run the extension."

    if debug_py:
        import debugpy
        host, port = debug_py.split(":")
        debugpy.listen((host, int(port)))

    master = Master(
        {
            "color": color,
            "debug": debug,
            "reload": reload,
        },
    )
    master.run()
