"""What every agent panel shares: the provider/model row and the host wrappers.

Phase 3 of the split (`docs/refactor_plan.md`). Two things live here:

`build_provider_row` is a plain function, because the panels are still methods
on `GodAI` and cannot inherit anything yet. Every panel rebuilt the same
provider combo, model combo and reload wiring by hand — seven identical
`addItems` lists and six near-identical `*_load_models` bodies. They call this
instead, and keep owning the widgets it returns.

`AgentPanel` is the class those panels become in phase 4. It is composition,
not a mixin: a panel holds its host behind the `AgentHost` protocol rather than
sharing a namespace with it, which is what makes a panel constructible — and
therefore testable — without a whole `GodAI` window. It uses the same function,
so the two paths cannot drift.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from ui.widgets import FlowLayout
from ui.workers import ChatWorker

# The provider list every panel offered, written once. Order is the order shown.
PROVIDERS = (
    "ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen",
)

# Model combos are wide enough for a dated API model id ("claude-sonnet-4-6-20260112").
MODEL_BOX_WIDTH = 200


def flow_row(parent: QWidget | None = None,
             spacing: int = 6) -> tuple[QWidget, FlowLayout]:
    """A control row that wraps instead of pinning a minimum width on the pane.

    Returns the container and the layout to fill; the caller must keep the
    container — every widget added to the layout belongs to it, and dropping an
    unparented one takes the combos down with it ("Internal C++ object already
    deleted"), which no import or compile check can see. Passing a `parent`
    settles that at construction.
    """
    container = QWidget(parent)
    return container, FlowLayout(container, spacing=spacing)


def build_provider_row(
    host,
    layout,
    agent_key: str,
    *,
    default: str = "anthropic",
    labels: bool = True,
    model_width: int = MODEL_BOX_WIDTH,
    empty_placeholder: bool = False,
) -> tuple[QComboBox, QComboBox]:
    """Add "Provider: […] Model: […]" to `layout` and keep the two in step.

    The model box is filled from the selected provider immediately and again on
    every provider change, and the loader is registered with the host so the
    recommendation system can repopulate the box after it selects a provider
    programmatically.

    `labels` is off for the panels that never had them (Beacon, Tunnel);
    `empty_placeholder` is on for Forge, which shows "(no local models)" rather
    than an empty box. Both exist to keep this a refactor rather than a redesign.
    """
    provider_box = QComboBox()
    provider_box.addItems(PROVIDERS)
    provider_box.setCurrentText(default)
    if labels:
        layout.addWidget(QLabel("Provider:"))
    layout.addWidget(provider_box)

    model_box = QComboBox()
    model_box.setMinimumWidth(model_width)
    if labels:
        layout.addWidget(QLabel("Model:"))
    layout.addWidget(model_box)

    def load() -> None:
        host.load_models_into(
            provider_box, model_box, agent_key,
            empty_placeholder=empty_placeholder,
        )

    # `_t` is the new provider text, which `load` reads off the box itself.
    provider_box.currentTextChanged.connect(lambda _t: load())
    host.register_model_loader(agent_key, load)
    load()
    return provider_box, model_box


class AgentPanel(QWidget):
    """One agent's UI, talking to the application through `AgentHost`.

    Subclasses set `agent_key` and build their own widgets; everything they need
    from the application arrives through `self.host` and is wrapped below, so a
    panel never reaches into `GodAI` attributes that are not in the protocol.

    Nothing here is Qt-specific beyond the widget base — the wrappers are thin
    on purpose, since their value is the boundary they draw, not the code they
    save.
    """

    #: Key under `AGENT_SETUP_WIDGETS`, `AGENT_RECOMMENDATIONS`, the registry
    #: and the request guard. Every subclass sets it.
    agent_key: str = ""

    #: Pre-selected provider. Panels that cost money default to a cloud model;
    #: the recommendation system may override this at startup.
    default_provider: str = "anthropic"

    def __init__(self, host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.provider_box: QComboBox | None = None
        self.model_box: QComboBox | None = None
        self.worker = None
        self._active_request_id: str | None = None

    # ── Construction helpers ────────────────────────────────────────────
    def flow_row(self, spacing: int = 6) -> tuple[QWidget, FlowLayout]:
        """A wrapping control row owned by this panel."""
        return flow_row(self, spacing)

    def build_provider_row(self, layout, **kwargs) -> tuple[QComboBox, QComboBox]:
        kwargs.setdefault("default", self.default_provider)
        self.provider_box, self.model_box = build_provider_row(
            self.host, layout, self.agent_key, **kwargs
        )
        return self.provider_box, self.model_box

    # ── Current selection ───────────────────────────────────────────────
    @property
    def provider(self) -> str:
        return self.provider_box.currentText() if self.provider_box else ""

    @property
    def model(self) -> str:
        return self.model_box.currentText() if self.model_box else ""

    def load_models(self) -> None:
        """Refill the model box from the selected provider."""
        if self.provider_box is not None and self.model_box is not None:
            self.host.load_models_into(self.provider_box, self.model_box,
                                       self.agent_key)

    # ── The request guard ───────────────────────────────────────────────
    # A panel that spends money calls authorize() first and record() once the
    # response is in; abandon() on failure. Skipping them is how twelve of
    # thirteen agents came to spend outside the budget caps (TODO #1).

    def authorize(self, prompt: str, *, tool: str | None = None,
                  label: str | None = None) -> bool:
        """False means the request was blocked and must not be sent."""
        self._active_request_id = self.host.authorize_request(
            self.agent_key, self.provider, self.model, prompt,
            tool=tool, label=label,
        )
        return self._active_request_id is not None

    def record(self, response: str, messages: list | None = None) -> None:
        request_id, self._active_request_id = self._active_request_id, None
        if request_id is not None:
            self.host.record_request(request_id, response, messages)

    def abandon(self, reason: str = "error") -> None:
        request_id, self._active_request_id = self._active_request_id, None
        if request_id is not None:
            self.host.abandon_request(request_id, reason)

    def note_usage(self, usage: dict) -> None:
        if self._active_request_id is not None:
            self.host.note_request_usage(self._active_request_id, usage)

    # ── Running one request ─────────────────────────────────────────────
    #: Swapped by panels that drive a tool instead of a chat request, and by
    #: tests that would rather not start a thread.
    worker_class = ChatWorker

    def start_worker(self, messages: list, prompt: str, *,
                     on_token=None, on_finished=None, on_error=None):
        """Run one authorised request in a thread and keep a handle on it.

        The usage signal is connected here rather than by each caller: real
        token counts arriving from the provider are what turn an estimate into
        a billed amount, and a panel that forgot to connect it under-reported
        its own spending in silence.
        """
        messages = self.host.apply_project_context(messages)
        worker = self.worker_class(self.host.run_backend, self.provider,
                                   self.model, messages, prompt)
        if on_token is not None:
            worker.token_signal.connect(on_token)
        if on_finished is not None:
            worker.finished_signal.connect(on_finished)
        if on_error is not None:
            worker.error_signal.connect(on_error)
        worker.usage_signal.connect(self.note_usage)
        self.worker = worker
        worker.start()
        return worker

    def is_running(self) -> bool:
        """Whether this panel currently has a request in flight."""
        return self.worker is not None and self.worker.isRunning()

    def stop_worker(self) -> bool:
        """Cancel the in-flight request, if there is one. True if it was running."""
        if self.is_running():
            self.worker.cancel()
            return True
        return False

    def stop(self) -> None:
        """Stop this panel's work and put its controls back.

        The base only cancels; a panel that has a status label and buttons to
        restore overrides this. `stop_current_task` — the window's Stop button —
        calls it on whichever panel reports itself running.
        """
        self.stop_worker()

    # ── Shared services ─────────────────────────────────────────────────
    def agent(self):
        """This panel's backend agent instance."""
        return self.host.agent_instances[self.agent_key]

    def run_backend(self, messages: list, prompt: str):
        """Execute one request with the panel's current provider and model."""
        return self.host.run_backend(self.provider, self.model, messages, prompt)

    def note_failure(self, context: str, exc: Exception, widget=None) -> None:
        self.host._note_failure(f"{self.agent_key}: {context}", exc, widget)
