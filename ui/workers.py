"""Background worker threads.

Moved verbatim out of main.py (see docs/refactor_plan.md, phase 1). These are
standalone QThread subclasses: they take everything they need as constructor
arguments and touch no application state, which is why they move first.
"""
import re
import subprocess
import time

from PySide6.QtCore import QThread, Signal


class ChatWorker(QThread):
    token_signal = Signal(str)
    status_signal = Signal(str)
    finished_signal = Signal(str)
    error_signal = Signal(str)
    usage_signal = Signal(dict)

    def __init__(self, run_backend_func, backend: str, model: str, messages: list, prompt: str):
        super().__init__()
        self.run_backend_func = run_backend_func
        self.backend = backend
        self.model = model
        self.messages = messages
        self.prompt = prompt
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def _emit_as_tokens(self, text: str):
        for part in re.split(r"(\s+)", text):
            if self._cancel_requested:
                return
            self.token_signal.emit(part)
            time.sleep(0.006)

    def run(self):
        try:
            self.status_signal.emit("Model processing started...")
            result = self.run_backend_func(
                self.backend,
                self.model,
                self.messages,
                self.prompt,
            )

            usage = None
            response_parts = []

            # ===== STREAMING CASE =====
            if hasattr(result, "__iter__") and not isinstance(result, (str, tuple, dict)):
                self.status_signal.emit("Streaming response...")

                for token in result:
                    if self._cancel_requested:
                        self.error_signal.emit("Request cancelled by user.")
                        return

                    response_parts.append(token)
                    self.token_signal.emit(token)

                response = "".join(response_parts)

                usage = {
                    "cost_type_override": "stream-estimated"
                }

            # ===== TUPLE (response, usage) =====
            elif isinstance(result, tuple):
                response, usage = result
                self._emit_as_tokens(response)

            # ===== NORMAL STRING RESPONSE =====
            else:
                response = result
                self._emit_as_tokens(response)

            if usage:
                self.usage_signal.emit(usage)

            self.finished_signal.emit(response)

        except Exception as e:
            self.error_signal.emit(str(e))


class SubprocessWorker(QThread):
    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, cmd: list):
        super().__init__()
        self._cmd = cmd
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            result = subprocess.run(self._cmd, capture_output=True, text=True, timeout=30)
            if self._cancelled:
                return
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\n\n[stderr]\n{result.stderr.strip()}"
            self.finished_signal.emit(output or "[No output returned]")
        except subprocess.TimeoutExpired:
            self.error_signal.emit("Command timed out after 30 seconds.")
        except FileNotFoundError as e:
            self.error_signal.emit(f"Command not found: {e}")
        except Exception as e:
            self.error_signal.emit(str(e))


class ModelPullWorker(QThread):
    """Downloads an Ollama model off the UI thread.

    progress_signal carries (status, completed_bytes, total_bytes); total is 0
    until Ollama has resolved the manifest.
    """
    progress_signal = Signal(str, int, int)
    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, client, model: str):
        super().__init__()
        self._client = client
        self._model = model

    def run(self):
        try:
            self._client.pull_model(
                self._model,
                on_progress=lambda status, done, total: self.progress_signal.emit(
                    status, int(done or 0), int(total or 0)
                ),
            )
            self.finished_signal.emit(self._model)
        except Exception as e:
            self.error_signal.emit(str(e))
