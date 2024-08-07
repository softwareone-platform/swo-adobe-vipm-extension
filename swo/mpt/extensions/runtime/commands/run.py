import click
from swo.mpt.extensions.runtime.master import Master


@click.command()
@click.argument("command", default="all", type=click.Choice(["all", "api", "consumer"]), metavar="[COMMAND]")
@click.option("--color/--no-color", default=True)
@click.option("--debug", is_flag=True, default=False)
@click.option("--reload", is_flag=True, default=False)
@click.option("--debug-py", default=None)
def run(command, color, debug, reload, debug_py):
    """Run the extension.

    \b
    COMMAND is the the name of the command to run. Possible values:
        * all - run both API and Event Consumer threads (default)
        * api - run only API thread
        * consumer - run only Event Consumer thread
    """

    if debug_py:
        import debugpy
        host, port = debug_py.split(":")
        debugpy.listen((host, int(port)))

    master = Master(
        {
            "color": color,
            "debug": debug,
            "reload": reload,
            "command": command,
        },
    )
    master.run()
