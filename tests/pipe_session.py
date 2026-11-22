"""Paired pipe session for interactive stdin/stdout protocol tests."""

import os
import selectors
import subprocess
import time


class PipeSession:
    def __init__(self, command, environment):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, bufsize=0, env=environment)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.pending = b""
        self.observed = b""

    def expect(self, expected, timeout=5):
        deadline = time.monotonic() + timeout
        while len(self.pending) < len(expected):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise AssertionError(f"timed out before stdin EOF: wanted {expected!r}, got {self.pending!r}")
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise AssertionError(f"child closed stdout: wanted {expected!r}, got {self.pending!r}")
            self.pending += data
            self.observed += data
        if not self.pending.startswith(expected):
            raise AssertionError((expected, self.pending))
        self.pending = self.pending[len(expected):]

    def quiet(self):
        if self.pending:
            raise AssertionError(f"unexpected early output {self.pending!r}")
        if self.selector.select(0.1):
            data = os.read(self.process.stdout.fileno(), 65536)
            if data:
                raise AssertionError(f"sized read returned too early: {data!r}")
            raise AssertionError("child closed stdout before remaining input")

    def send(self, data):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def close_input(self):
        if self.process.stdin is not None:
            self.process.stdin.close()
            self.process.stdin = None

    def finish(self):
        self.close_input()
        out, error = self.process.communicate(timeout=10)
        self.observed += out
        if self.process.returncode:
            raise AssertionError((self.process.returncode, error))
        return self.observed, error

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate(timeout=5)
        self.selector.close()
        self.process.stdout.close()
        self.process.stderr.close()
