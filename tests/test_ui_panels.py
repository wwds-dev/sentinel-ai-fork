"""The shared panel base — `ui/panels/base.py` — and the host seam it uses.

Phase 3 of the `main.py` split (`docs/refactor_plan.md`). Six panels used to
build their own provider/model row and their own model loader; they now share
one of each. Two things are worth pinning:

1. Every panel still ends up with a populated model box wired to its provider —
   this is the behaviour the duplication used to provide, and losing it would
   not raise anything, it would just leave a combo empty.
2. `AgentPanel` works against a stand-in host, with no `GodAI` in sight. That is
   the whole point of composition over mixins, and it is what phase 4 relies on.

The window is built offscreen once per module: constructing `GodAI` is slow, and
every test here only reads widget state or calls one method on it.
"""

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.host import AgentHost
from ui.panels.base import PROVIDERS, AgentPanel, build_provider_row


# Agents with a panel of their own, and the widget attributes they own.
PANEL_AGENTS = {
    "osint":       ("osint_provider_box",       "osint_model_box"),
    "osint_heavy": ("osint_heavy_provider_box", "osint_heavy_model_box"),
    "wifi":        ("wifi_provider_box",        "wifi_model_box"),
    "bug_bounty":  ("bb_provider_box",          "bb_model_box"),
    "manager":     ("manager_provider_box",     "manager_model_box"),
    "vpn":         ("vpn_provider_box",         "vpn_model_box"),
}


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(qapp):
    """One offscreen `GodAI`. Modal dialogs are stubbed — nothing can click them."""
    from PySide6.QtWidgets import QMessageBox
    import main

    saved = (QMessageBox.warning, QMessageBox.question)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        yield main.GodAI()
    finally:
        QMessageBox.warning, QMessageBox.question = saved


# ─────────────────────────────────────────────────────────────────────────────
# 1. The rows the panels no longer build by hand
# ─────────────────────────────────────────────────────────────────────────────

class TestPanelProviderRows:

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_panel_owns_its_provider_and_model_boxes(self, win, agent, widgets):
        # The helper returns the boxes and the panel assigns them; a typo in the
        # assignment would leave the old attribute name unset.
        assert getattr(win, widgets[0], None) is not None
        assert getattr(win, widgets[1], None) is not None

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_provider_box_offers_every_provider(self, win, agent, widgets):
        box = getattr(win, widgets[0])
        assert [box.itemText(i) for i in range(box.count())] == list(PROVIDERS)

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_model_box_is_populated_by_the_time_the_panel_is_built(
            self, win, agent, widgets):
        # Every client falls back to a hand-written list when its API is
        # unreachable, so this holds offline and with no API keys set.
        assert getattr(win, widgets[1]).count() > 0

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_switching_provider_reloads_the_model_list(self, win, agent, widgets):
        provider_box, model_box = (getattr(win, w) for w in widgets)
        before = provider_box.currentText()
        other = next(p for p in PROVIDERS if p != before)
        try:
            provider_box.setCurrentText(other)
            expected = win.models_for_provider(other)
            actual = [model_box.itemText(i) for i in range(model_box.count())]
            assert actual == expected or (not expected and actual in ([], ["(unavailable)"]))
        finally:
            provider_box.setCurrentText(before)

    def test_labels_are_kept_where_the_panel_had_them(self, win):
        # Beacon and Tunnel never had "Provider:"/"Model:" labels; the flag that
        # preserves that is easy to get backwards, and nothing else would notice.
        from PySide6.QtWidgets import QLabel
        labels = {
            w.text() for w in win.wifi_panel.findChildren(QLabel)
            if w.text() in ("Provider:", "Model:")
        }
        assert labels == set()
        osint_labels = {
            w.text() for w in win.osint_panel.findChildren(QLabel)
            if w.text() in ("Provider:", "Model:")
        }
        assert osint_labels == {"Provider:", "Model:"}


class TestRecommendationsStillReachThePanels:
    """The registry replaced a map of loader method *names*.

    Selecting a recommended model only works if the model box was repopulated
    first, so a panel sitting on its recommended model is end-to-end proof that
    the recommendation system found this panel's loader.
    """

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_panel_starts_on_its_recommended_provider_and_model(
            self, win, agent, widgets):
        import main
        rec = main.AGENT_RECOMMENDATIONS[agent]
        provider_box, model_box = (getattr(win, w) for w in widgets)
        assert provider_box.currentText() == rec["provider"]
        assert model_box.currentIndex() == win._find_model_index(
            model_box, rec["model"])

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_the_recommended_model_is_still_marked_after_a_reload(
            self, win, agent, widgets):
        # Clearing a combo drops every item's colour, so the marking has to be
        # re-applied after each load — the reason the loader and the marker are
        # both wired to the provider box.
        from PySide6.QtCore import Qt
        import main
        model_box = getattr(win, widgets[1])
        win.load_models_for(agent)
        win.refresh_recommendation_marks(agent)
        idx = win._find_model_index(model_box, main.AGENT_RECOMMENDATIONS[agent]["model"])
        assert idx >= 0
        assert model_box.itemData(idx, Qt.ForegroundRole) is not None


class TestModelLoaderRegistry:

    @pytest.mark.parametrize("agent", list(PANEL_AGENTS) + ["chat"])
    def test_every_agent_registers_a_loader(self, win, agent):
        assert callable(win._model_loaders.get(agent))

    @pytest.mark.parametrize("agent,widgets", PANEL_AGENTS.items())
    def test_load_models_for_refills_an_emptied_box(self, win, agent, widgets):
        model_box = getattr(win, widgets[1])
        model_box.clear()
        win.load_models_for(agent)
        assert model_box.count() > 0

    def test_unknown_agent_key_is_a_no_op(self, win):
        win.load_models_for("no_such_agent")  # must not raise

    def test_a_failing_loader_is_recorded_not_raised(self, win, monkeypatch):
        noted = []
        monkeypatch.setattr(win, "_note_failure",
                            lambda ctx, exc, widget=None: noted.append(ctx))
        win._model_loaders["boom"] = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            win.load_models_for("boom")
        finally:
            del win._model_loaders["boom"]
        assert noted and "boom" in noted[0]


class TestLoadModelsInto:

    def test_unknown_provider_leaves_the_box_empty(self, win, qapp):
        from PySide6.QtWidgets import QComboBox
        provider_box, model_box = QComboBox(), QComboBox()
        provider_box.addItem("nonesuch")
        win.load_models_into(provider_box, model_box, "test")
        assert model_box.count() == 0

    def test_placeholder_only_where_a_panel_asked_for_one(self, win, qapp):
        from PySide6.QtWidgets import QComboBox
        provider_box, model_box = QComboBox(), QComboBox()
        provider_box.addItem("ollama")
        win.load_models_into(provider_box, model_box, "test",
                             empty_placeholder=True)
        # Either real models, or Forge's hint — never a silently empty box.
        assert model_box.count() > 0

    def test_a_failing_client_is_noted_rather_than_swallowed(self, win, qapp,
                                                             monkeypatch):
        """Two of the six panels used to discard this exception entirely."""
        from PySide6.QtWidgets import QComboBox

        class Exploding:
            def list_models(self):
                raise RuntimeError("provider down")

        noted = []
        monkeypatch.setattr(win, "qwen", Exploding())
        monkeypatch.setattr(win, "_note_failure",
                            lambda ctx, exc, widget=None: noted.append(ctx))
        provider_box, model_box = QComboBox(), QComboBox()
        provider_box.addItem("qwen")
        win.load_models_into(provider_box, model_box, "trace")
        assert noted == ["trace: load models"]
        assert model_box.count() == 0

    def test_no_context_keeps_the_old_silent_behaviour(self, win, monkeypatch):
        class Exploding:
            def list_models(self):
                raise RuntimeError("provider down")

        noted = []
        monkeypatch.setattr(win, "qwen", Exploding())
        monkeypatch.setattr(win, "_note_failure",
                            lambda *a, **k: noted.append(a))
        assert win.models_for_provider("qwen") == []
        assert noted == []


class TestAgentHostProtocol:

    def test_godai_satisfies_the_host_protocol(self, win):
        # The protocol is the contract phase 4 panels are written against; a
        # member renamed on GodAI must fail here, not in a panel months later.
        assert isinstance(win, AgentHost)


# ─────────────────────────────────────────────────────────────────────────────
# 2. AgentPanel, with no GodAI anywhere
# ─────────────────────────────────────────────────────────────────────────────

class FakeHost:
    """The whole surface a panel is allowed to touch, and nothing else."""

    def __init__(self, models=("m1", "m2")):
        self.models = list(models)
        self.loaders = {}
        self.calls = []
        self.agent_instances = {"demo": object()}
        self.authorized = True

    def load_models_into(self, provider_box, model_box, context,
                         empty_placeholder=False):
        self.calls.append(("load", provider_box.currentText(), context))
        model_box.clear()
        model_box.addItems([f"{provider_box.currentText()}-{m}" for m in self.models])

    def register_model_loader(self, agent_key, loader):
        self.loaders[agent_key] = loader

    def authorize_request(self, agent, provider, model, prompt,
                          tool=None, label=None):
        self.calls.append(("authorize", agent, provider, model, prompt, tool, label))
        return self.authorized

    def record_request(self, agent, response, messages=None):
        self.calls.append(("record", agent, response, messages))

    def abandon_request(self, agent, reason="error"):
        self.calls.append(("abandon", agent, reason))

    def note_request_usage(self, agent, usage):
        self.calls.append(("usage", agent, usage))

    def run_backend(self, backend, model, messages, prompt):
        self.calls.append(("run", backend, model, messages, prompt))
        return "done"

    def _note_failure(self, context, exc, widget=None):
        self.calls.append(("failure", context))


class FakeWorker(QObject):
    """A ChatWorker with the threads taken out."""

    token_signal = Signal(str)
    finished_signal = Signal(str)
    error_signal = Signal(str)
    usage_signal = Signal(dict)
    status_signal = Signal(str)

    instances = []

    def __init__(self, run_backend, provider, model, messages, prompt):
        super().__init__()
        self.args = (provider, model, messages, prompt)
        self.started = False
        self.cancelled = False
        self.running = True
        FakeWorker.instances.append(self)

    def start(self):
        self.started = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancelled = True


class DemoPanel(AgentPanel):
    agent_key = "demo"
    default_provider = "deepseek"
    worker_class = FakeWorker


@pytest.fixture
def panel(qapp):
    host = FakeHost()
    p = DemoPanel(host)
    _container, layout = p.flow_row()
    p.build_provider_row(layout)
    return p


class TestAgentPanel:

    def test_it_builds_without_a_window(self, panel):
        assert panel.provider_box is not None and panel.model_box is not None

    def test_it_starts_on_its_default_provider(self, panel):
        assert panel.provider == "deepseek"

    def test_it_asks_the_host_for_models_once_while_building(self, panel):
        assert [c for c in panel.host.calls if c[0] == "load"] == [
            ("load", "deepseek", "demo")
        ]

    def test_changing_provider_reloads_through_the_host(self, panel):
        panel.provider_box.setCurrentText("openai")
        assert ("load", "openai", "demo") in panel.host.calls
        assert panel.model == "openai-m1"

    def test_it_registers_its_loader_with_the_host(self, panel):
        assert callable(panel.host.loaders["demo"])

    def test_authorize_passes_the_panels_own_key_and_selection(self, panel):
        assert panel.authorize("prompt text", label="Person") is True
        assert panel.host.calls[-1] == (
            "authorize", "demo", "deepseek", "deepseek-m1", "prompt text",
            None, "Person",
        )

    def test_a_blocked_request_is_reported_as_false(self, panel):
        panel.host.authorized = False
        assert panel.authorize("prompt text") is False

    def test_record_abandon_and_usage_all_carry_the_agent_key(self, panel):
        panel.record("response", [{"role": "user"}])
        panel.abandon("stopped")
        panel.note_usage({"input_tokens": 5})
        assert panel.host.calls[-3:] == [
            ("record", "demo", "response", [{"role": "user"}]),
            ("abandon", "demo", "stopped"),
            ("usage", "demo", {"input_tokens": 5}),
        ]

    def test_run_backend_uses_the_current_selection(self, panel):
        panel.run_backend([{"role": "user"}], "hello")
        assert panel.host.calls[-1] == (
            "run", "deepseek", "deepseek-m1", [{"role": "user"}], "hello",
        )

    def test_agent_comes_from_the_host_registry(self, panel):
        assert panel.agent() is panel.host.agent_instances["demo"]

    def test_note_failure_is_prefixed_with_the_agent_key(self, panel):
        panel.note_failure("load models", RuntimeError("x"))
        assert panel.host.calls[-1] == ("failure", "demo: load models")

    def test_load_models_is_a_no_op_before_the_row_is_built(self, qapp):
        DemoPanel(FakeHost()).load_models()  # must not raise

    def test_a_bare_panel_reports_no_selection(self, qapp):
        bare = DemoPanel(FakeHost())
        assert (bare.provider, bare.model) == ("", "")


class TestAgentPanelRuns:

    @pytest.fixture(autouse=True)
    def _fresh_workers(self):
        FakeWorker.instances.clear()

    def test_start_worker_passes_the_current_selection(self, panel):
        worker = panel.start_worker([{"role": "user"}], "hello")
        assert worker.args == ("deepseek", "deepseek-m1", [{"role": "user"}], "hello")
        assert worker.started is True

    def test_the_panel_keeps_a_handle_on_its_worker(self, panel):
        worker = panel.start_worker([], "hello")
        assert panel.worker is worker

    def test_usage_is_reported_without_the_caller_wiring_it(self, panel):
        # The signal every panel had to remember to connect, and one didn't.
        worker = panel.start_worker([], "hello")
        worker.usage_signal.emit({"input_tokens": 7})
        assert ("usage", "demo", {"input_tokens": 7}) in panel.host.calls

    def test_optional_callbacks_are_connected_when_given(self, panel):
        seen = []
        worker = panel.start_worker(
            [], "hello",
            on_token=lambda t: seen.append(("token", t)),
            on_finished=lambda r: seen.append(("finished", r)),
            on_error=lambda e: seen.append(("error", e)),
        )
        worker.token_signal.emit("tok")
        worker.finished_signal.emit("done")
        worker.error_signal.emit("boom")
        assert seen == [("token", "tok"), ("finished", "done"), ("error", "boom")]

    def test_omitted_callbacks_are_not_required(self, panel):
        worker = panel.start_worker([], "hello")
        worker.token_signal.emit("tok")  # nothing connected; must not raise

    def test_stop_cancels_a_running_worker(self, panel):
        worker = panel.start_worker([], "hello")
        assert panel.stop_worker() is True
        assert worker.cancelled is True

    def test_stop_is_harmless_when_nothing_is_running(self, panel):
        assert panel.stop_worker() is False
        worker = panel.start_worker([], "hello")
        worker.running = False
        assert panel.stop_worker() is False
        assert worker.cancelled is False
