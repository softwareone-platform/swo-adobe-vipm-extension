import click

from swo.mpt.extensions.runtime.master import Master


@click.command()
def run():
    "Run the extension."
    master = Master()
    master.run()
