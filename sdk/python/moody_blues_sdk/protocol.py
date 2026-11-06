"""Constants of ``mb-agent/1``, and the channel that carries it.

One JSON document per line. Your agent writes to the channel only through this SDK, and ``print``
is safe: the runtime moves it to stderr, so it can never corrupt the protocol stream.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from typing import Any, BinaryIO

PROTOCOL_VERSION = "mb-agent/1"
SDK_VERSION = "0.1.0"
MAX_MESSAGE_BYTES = 65_536

Message = dict[str, Any]


class Channel:
    """Writes messages to one file descriptor and reads them on a daemon thread."""

    def __init__(self, reader: BinaryIO, write_fd: int) -> None:
        self._reader = reader
        self._write_fd = write_fd
        self._write_lock = threading.Lock()

    def send(self, message: Message) -> None:
        data = json.dumps({"protocol": PROTOCOL_VERSION, **message}, separators=(",", ":"))
        encoded = data.encode("utf-8") + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ValueError(f"message is {len(encoded)} bytes; the limit is {MAX_MESSAGE_BYTES}")
        with self._write_lock:
            view = memoryview(encoded)
            while view:
                view = view[os.write(self._write_fd, view) :]

    def read(self) -> Message | None:
        """The next message, or None when the host has closed the stream."""
        line = self._reader.readline()
        return json.loads(line) if line else None

    def listen(self, handle: Callable[[Message | None], None]) -> None:
        def pump() -> None:
            while True:
                message = self.read()
                handle(message)
                if message is None:
                    return

        threading.Thread(target=pump, name="mb-agent-reader", daemon=True).start()
