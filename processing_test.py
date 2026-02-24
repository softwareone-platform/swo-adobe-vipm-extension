from time import sleep

import typer


def main():
    num = 60
    with typer.progressbar(
        range(num),
        length=num,
        label=f"Migrating agreements",
        bar_template = f"[%(bar)s]  %(info)s - %(label)s",
        show_pos=True,
        show_percent=True,
        show_eta=True,
    ) as bar:
        for i in bar:
            bar.label = f"Processing {i}"
            sleep(1)

if __name__ == "__main__":
    main()
