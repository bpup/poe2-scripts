"""Logging handler that feeds log records to a tkinter Text widget via a queue."""

from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from typing import Optional


class GuiLogHandler(logging.Handler):
    """Logging handler that pushes formatted records onto a thread-safe queue.

    The GUI consumer polls the queue and inserts text into a tkinter widget.
    """

    MAX_QUEUE_SIZE = 200  # drop oldest if queue grows too large

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self._queue: queue.Queue[str] = queue.Queue(maxsize=0)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put(msg, block=False)
        except queue.Full:
            pass  # drop silently — GUI is too far behind
        except Exception:
            self.handleError(record)

    def drain(self) -> str:
        """Pull all queued messages and return them as a single joined string."""
        parts: list[str] = []
        while True:
            try:
                parts.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return "\n".join(parts)


class LogPanel(ScrolledText):
    """Read-only ScrolledText panel that auto-consumes a GuiLogHandler."""

    def __init__(
        self,
        master: tk.Misc,
        handler: GuiLogHandler,
        poll_ms: int = 100,
        max_lines: int = 500,
        **kwargs: object,
    ) -> None:
        kwargs.setdefault("state", "disabled")
        kwargs.setdefault("wrap", tk.WORD)
        kwargs.setdefault("font", ("Consolas", 9))
        super().__init__(master, **kwargs)
        self._handler = handler
        self._poll_ms = poll_ms
        self._max_lines = max_lines
        self._scheduled: Optional[str] = None
        self._start_polling()

    def _start_polling(self) -> None:
        self._consume_once()

    def _consume_once(self) -> None:
        new_text = self._handler.drain()
        if new_text:
            self.configure(state="normal")
            self.insert(tk.END, new_text + "\n")
            self._trim()
            self.see(tk.END)
            self.configure(state="disabled")
        self._scheduled = self.after(self._poll_ms, self._consume_once)

    def _trim(self) -> None:
        lines = int(self.index("end-1c").split(".")[0])
        if lines > self._max_lines:
            self.delete("1.0", f"{lines - self._max_lines}.0")

    def destroy(self) -> None:
        if self._scheduled is not None:
            self.after_cancel(self._scheduled)
            self._scheduled = None
        super().destroy()
