"""UI-owned background task: results cross signals, DB connections never do."""

import sys

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        # QThreads are invisible to debugpy unless registered; lets VS Code breakpoints hit.
        if "debugpy" in sys.modules:
            sys.modules["debugpy"].debug_this_thread()
        try:
            self.done.emit(self.function(self.progress.emit))
        except Exception as exc:
            # Translate at the display boundary; retain the diagnostic in the detail panel.
            self.failed.emit(str(exc))
