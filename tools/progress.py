import itertools
import sys
import threading
import time
from contextlib import contextmanager

_output_lock = threading.Lock()
_paused = threading.Event()


@contextmanager
def pause_progress():
    _paused.set()
    with _output_lock:
        if sys.stdout.isatty():
            print('\r\033[2K', end='', flush=True)
    try:
        yield
    finally:
        _paused.clear()


class Spinner:
    def __init__(self, message):
        self.message = message
        self.stopped = threading.Event()
        self.thread = None
        self.started = None

    def animate(self):
        if self.started is None:
            return
        for frame in itertools.cycle(('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')):
            with _output_lock:
                if not _paused.is_set():
                    elapsed = time.monotonic() - self.started
                    print(f'\r\033[2K{frame} {self.message} · {elapsed:.1f} с', end='', flush=True)
            if self.stopped.wait(0.1):
                return

    def __enter__(self):
        self.started = time.monotonic()
        if sys.stdout.isatty():
            self.thread = threading.Thread(target=self.animate, daemon=True)
            self.thread.start()
        else:
            print(self.message + '…', flush=True)
        return self

    def __exit__(self, *args):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()
            with _output_lock:
                print('\r\033[2K', end='', flush=True)
        elapsed = time.monotonic() - self.started if self.started is not None else 0.0
        result = 'готово' if args[0] is None else 'прервано'
        print(f'{self.message} - {result} ({elapsed:.1f} с)', flush=True)
