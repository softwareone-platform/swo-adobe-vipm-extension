import logging
import signal
import threading
import time
from pathlib import Path

from swo.mpt.extensions.runtime.workers import start_event_consumer, start_gunicorn
from watchfiles import watch
from watchfiles.filters import PythonFilter
from watchfiles.run import start_process

logger = logging.getLogger(__name__)


HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)
PROCESS_CHECK_INTERVAL_SECS = 5


def _display_path(path):
    try:
        return f'"{path.relative_to(Path.cwd())}"'
    except ValueError:  # pragma: no cover
        return f'"{path}"'


class Master:
    def __init__(self, options):
        self.workers = {}
        self.options = options
        self.stop_event = threading.Event()
        self.monitor_event = threading.Event()
        self.watch_filter = PythonFilter(ignore_paths=None)
        self.watcher = watch(
            Path.cwd(),
            watch_filter=self.watch_filter,
            stop_event=self.stop_event,
            yield_on_timeout=True,
        )
        self.monitor_thread = None
        self.setup_signals_handler()

        match self.options["component"]:
            case "all":
                self.proc_targets = {
                    "event-consumer": start_event_consumer,
                    "gunicorn": start_gunicorn,
                }
            case "api":
                self.proc_targets = {
                    "gunicorn": start_gunicorn,
                }
            case "consumer":
                self.proc_targets = {
                    "event-consumer": start_event_consumer,
                }
            case _:
                self.proc_targets = {
                    "event-consumer": start_event_consumer,
                    "gunicorn": start_gunicorn,
                }

    def setup_signals_handler(self):
        for sig in HANDLED_SIGNALS:
            signal.signal(sig, self.handle_signal)

    def handle_signal(self, *args, **kwargs):
        self.stop_event.set()

    def start(self):
        for worker_type, target in self.proc_targets.items():
            self.start_worker_process(worker_type, target)
        self.monitor_thread = threading.Thread(target=self.monitor_processes)
        self.monitor_event.set()
        self.monitor_thread.start()

    def start_worker_process(self, worker_type, target):
        p = start_process(target, "function", (self.options,), {})
        self.workers[worker_type] = p
        logger.info(f"{worker_type.capitalize()} worker pid: {p.pid}")

    def monitor_processes(self):
        while self.monitor_event.is_set():
            exited_workers = []
            for worker_type, p in self.workers.items():
                if not p.is_alive():
                    if p.exitcode != 0:
                        logger.info(f"Process of type {worker_type} is dead, restart it")
                        self.start_worker_process(worker_type, self.proc_targets[worker_type])
                    else:
                        exited_workers.append(worker_type)
                        logger.info(f"{worker_type.capitalize()} worker exited")
            if exited_workers == list(self.workers.keys()):
                self.stop_event.set()

            time.sleep(PROCESS_CHECK_INTERVAL_SECS)

    def stop(self):
        self.monitor_event.clear()
        self.monitor_thread.join()
        for worker_type, process in self.workers.items():
            process.stop(sigint_timeout=5, sigkill_timeout=1)
            logger.info(f"{worker_type.capitalize()} process with pid {process.pid} stopped.")

    def restart(self):
        self.stop()
        self.start()

    def __iter__(self):
        return self

    def __next__(self):
        changes = next(self.watcher)
        if changes:
            return list({Path(c[1]) for c in changes})
        return None

    def run(self):
        self.start()
        if self.options.get("reload"):
            for files_changed in self:
                if files_changed:
                    logger.warning(
                        "Detected changes in %s. Reloading...",
                        ", ".join(map(_display_path, files_changed)),
                    )
                    self.restart()
        else:
            self.stop_event.wait()
        self.stop()
