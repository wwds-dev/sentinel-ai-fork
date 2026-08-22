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


# Agents with a panel of their own. Their provider/model boxes are reached the
# way the application reaches them — `setup_widgets_for` — because a panel that
# has moved to `ui/panels/` owns its combos and one that has not still hangs
# them off `GodAI` (phase 4 moves them one at a time).
PANEL_AGENTS = [
    "osint", "osint_heavy", "wifi", "bug_bounty", "manager", "vpn",
]


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

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_panel_owns_its_provider_and_model_boxes(self, win, agent):
        # A panel with no boxes cannot be recommended to, marked, or run.
        provider_box, model_box = win.setup_widgets_for(agent)
        assert provider_box is not None
        assert model_box is not None

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_provider_box_offers_every_provider(self, win, agent):
        box, _ = win.setup_widgets_for(agent)
        assert [box.itemText(i) for i in range(box.count())] == list(PROVIDERS)

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_model_box_is_populated_by_the_time_the_panel_is_built(
            self, win, agent):
        # Every client falls back to a hand-written list when its API is
        # unreachable, so this holds offline and with no API keys set.
        assert win.setup_widgets_for(agent)[1].count() > 0

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_switching_provider_reloads_the_model_list(self, win, agent):
        provider_box, model_box = win.setup_widgets_for(agent)
        before = provider_box.currentText()
        other = next(p for p in PROVIDERS if p != before)
        try:
            provider_box.setCurrentText(other)
            expected = win.models_for_provider(other)
            actual = [model_box.itemText(i) for i in range(model_box.count())]
            placeholders = ([], ["(unavailable)"], ["(no local models)"])
            assert actual == expected or (not expected and actual in placeholders)
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

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_panel_starts_on_its_recommended_provider_and_model(
            self, win, agent):
        import main
        rec = main.AGENT_RECOMMENDATIONS[agent]
        provider_box, model_box = win.setup_widgets_for(agent)
        assert provider_box.currentText() == rec["provider"]
        assert model_box.currentIndex() == win._find_model_index(
            model_box, rec["model"])

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_the_recommended_model_is_still_marked_after_a_reload(
            self, win, agent):
        # Clearing a combo drops every item's colour, so the marking has to be
        # re-applied after each load — the reason the loader and the marker are
        # both wired to the provider box.
        from PySide6.QtCore import Qt
        import main
        model_box = win.setup_widgets_for(agent)[1]
        win.load_models_for(agent)
        win.refresh_recommendation_marks(agent)
        idx = win._find_model_index(model_box, main.AGENT_RECOMMENDATIONS[agent]["model"])
        assert idx >= 0
        assert model_box.itemData(idx, Qt.ForegroundRole) is not None


class TestModelLoaderRegistry:

    @pytest.mark.parametrize("agent", PANEL_AGENTS + ["chat"])
    def test_every_agent_registers_a_loader(self, win, agent):
        assert callable(win._model_loaders.get(agent))

    @pytest.mark.parametrize("agent", PANEL_AGENTS)
    def test_load_models_for_refills_an_emptied_box(self, win, agent):
        model_box = win.setup_widgets_for(agent)[1]
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

class FakeAgentFactory:
    """Stands in for the thing that writes real files into agents/ and config/."""

    def __init__(self, success=True):
        self.created = []
        self.success = success

    def create_agent(self, spec):
        self.created.append(spec)
        if self.success:
            return {"success": True, "files_created": [f"agents/{spec['name']}_agent.py"]}
        return {"success": False, "errors": ["disk on fire"]}


class FakeHost:
    """The whole surface a panel is allowed to touch, and nothing else."""

    def __init__(self, models=("m1", "m2")):
        self.models = list(models)
        self.loaders = {}
        self.calls = []
        self.agent_instances = {"demo": object()}
        self.authorized = True
        self._request_n = 0
        self.agent_factory = FakeAgentFactory()

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
        if not self.authorized:
            return None
        self._request_n += 1
        return f"request-{self._request_n}"

    def record_request(self, agent, response, messages=None):
        self.calls.append(("record", agent, response, messages))

    def abandon_request(self, agent, reason="error"):
        self.calls.append(("abandon", agent, reason))

    def note_request_usage(self, agent, usage):
        self.calls.append(("usage", agent, usage))

    def apply_project_context(self, messages):
        return [dict(message) for message in messages]

    def run_backend(self, backend, model, messages, prompt):
        self.calls.append(("run", backend, model, messages, prompt))
        return "done"

    def _note_failure(self, context, exc, widget=None):
        self.calls.append(("failure", context))

    def show_agent_docs(self):
        self.calls.append(("docs",))


class FakeScanWorker(QObject):
    """A SubprocessWorker with the process taken out."""

    finished_signal = Signal(str)
    error_signal = Signal(str)
    instances = []

    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
        self.running = True
        FakeScanWorker.instances.append(self)

    def start(self):
        pass

    def isRunning(self):
        return self.running

    def cancel(self):
        self.running = False


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

    def test_record_abandon_and_usage_all_carry_the_request_id(self, panel):
        panel.authorize("first")
        panel.record("response", [{"role": "user"}])
        panel.authorize("second")
        panel.abandon("stopped")
        panel.authorize("third")
        panel.note_usage({"input_tokens": 5})
        assert panel.host.calls[-3:] == [
            ("abandon", "request-2", "stopped"),
            ("authorize", "demo", "deepseek", "deepseek-m1", "third", None, None),
            ("usage", "request-3", {"input_tokens": 5}),
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
        panel.authorize("hello")
        worker = panel.start_worker([], "hello")
        worker.usage_signal.emit({"input_tokens": 7})
        assert ("usage", "request-1", {"input_tokens": 7}) in panel.host.calls

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


# ─────────────────────────────────────────────────────────────────────────────
# 3. The first vertical to move: Trace
# ─────────────────────────────────────────────────────────────────────────────

class FakeOsintAgent:
    def __init__(self):
        self.calls = []

    def build_messages(self, target, query_type):
        self.calls.append((target, query_type))
        return [{"role": "user", "content": f"{query_type}:{target}"}]


@pytest.fixture
def trace(qapp, monkeypatch):
    """Trace built against a fake host — no `GodAI`, no window, no thread."""
    from ui.panels.osint import OsintPanel
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(OsintPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()

    host = FakeHost()
    host.agent_instances["osint"] = FakeOsintAgent()
    panel = OsintPanel(host)
    panel.target_input.setText("acme.com")
    return panel


class TestTracePanel:

    def test_it_builds_without_a_window(self, trace):
        assert trace.provider_box is not None
        assert trace.status_label.text() == "Idle"
        assert trace.stop_btn.isEnabled() is False

    def test_it_starts_hidden(self, trace):
        # The centre pane stacks every panel and shows one; a panel that forgets
        # to hide itself appears behind whichever agent is selected.
        assert trace.isHidden() is True

    def test_an_empty_target_never_reaches_the_guard(self, trace):
        trace.target_input.clear()
        trace.analyse()
        assert [c for c in trace.host.calls if c[0] == "authorize"] == []

    def test_no_model_never_reaches_the_guard(self, trace):
        trace.model_box.clear()
        trace.analyse()
        assert [c for c in trace.host.calls if c[0] == "authorize"] == []

    def test_a_blocked_request_starts_no_worker(self, trace):
        trace.host.authorized = False
        trace.analyse()
        assert FakeWorker.instances == []

    def test_the_query_type_is_passed_to_the_agent_and_the_guard(self, trace):
        trace.type_box.setCurrentText("Domain")
        trace.analyse()
        assert trace.host.agent_instances["osint"].calls == [("acme.com", "Domain")]
        authorize = [c for c in trace.host.calls if c[0] == "authorize"][-1]
        assert authorize[1] == "osint" and authorize[4] == "acme.com"
        assert authorize[6] == "Domain"

    def test_running_disables_analyse_and_enables_stop(self, trace):
        trace.analyse()
        assert trace.analyse_btn.isEnabled() is False
        assert trace.stop_btn.isEnabled() is True

    def test_tokens_stream_into_the_raw_box(self, trace):
        trace.analyse()
        trace.worker.token_signal.emit("## QUERY ")
        trace.worker.token_signal.emit("STRUCTURE")
        assert trace.stream_box.toPlainText() == "## QUERY STRUCTURE"
        assert trace.stream_box.isVisibleTo(trace) is True
        assert trace.sections.isVisibleTo(trace) is False

    def test_a_finished_answer_is_recorded_and_rendered_as_cards(self, trace):
        trace.analyse()
        trace.worker.finished_signal.emit(
            "## QUERY STRUCTURE\nS\n## GOOGLE DORKS\nd\n"
            "## PUBLIC SOURCES\np\n## SUMMARY\nx"
        )
        assert ("record", "request-1",
                "## QUERY STRUCTURE\nS\n## GOOGLE DORKS\nd\n"
                "## PUBLIC SOURCES\np\n## SUMMARY\nx", None) in trace.host.calls
        assert trace.sections.isVisibleTo(trace) is True
        assert trace.stream_box.isVisibleTo(trace) is False
        assert trace.status_label.text() == "Done."
        assert trace.analyse_btn.isEnabled() is True

    def test_an_error_abandons_the_request_so_it_is_not_billed(self, trace):
        trace.analyse()
        trace.worker.error_signal.emit("provider down")
        assert ("abandon", "request-1", "error") in trace.host.calls
        assert "provider down" in trace.stream_box.toPlainText()
        assert trace.status_label.text() == "Error."
        assert trace.analyse_btn.isEnabled() is True
        assert trace.stop_btn.isEnabled() is False

    def test_usage_reaches_the_host_without_the_panel_wiring_it(self, trace):
        trace.analyse()
        trace.worker.usage_signal.emit({"input_tokens": 11})
        assert ("usage", "request-1", {"input_tokens": 11}) in trace.host.calls

    def test_stop_cancels_and_restores_the_controls(self, trace):
        trace.analyse()
        worker = trace.worker
        trace.stop()
        assert worker.cancelled is True
        assert trace.status_label.text() == "Stopped."
        assert trace.analyse_btn.isEnabled() is True
        assert trace.stop_btn.isEnabled() is False

    def test_clear_empties_the_form_and_the_output(self, trace):
        trace.analyse()
        trace.worker.finished_signal.emit("## SUMMARY\nx")
        trace.clear()
        assert trace.target_input.text() == ""
        assert trace.stream_box.toPlainText() == ""
        assert trace.status_label.text() == "Idle"


class TestTraceSectionParsing:
    """Pure text handling — no widgets, no host."""

    ANSWER = (
        "## QUERY STRUCTURE\nstructured\n"
        "## GOOGLE DORKS\nsite:acme.com\n"
        "## PUBLIC SOURCES\nwhois\n"
        "## SUMMARY\nnext steps"
    )

    def test_each_heading_becomes_its_own_section(self):
        from ui.panels.osint import OsintPanel
        parsed = OsintPanel.parse_sections(self.ANSWER)
        assert parsed == {
            "structure": "structured", "dorks": "site:acme.com",
            "sources": "whois", "summary": "next steps",
        }

    def test_a_missing_heading_comes_back_empty_rather_than_absent(self):
        from ui.panels.osint import OsintPanel
        parsed = OsintPanel.parse_sections("## GOOGLE DORKS\nsite:acme.com")
        assert parsed["dorks"] == "site:acme.com"
        assert parsed["structure"] == "" and parsed["summary"] == ""

    def test_headings_are_matched_case_insensitively(self):
        from ui.panels.osint import OsintPanel
        assert OsintPanel.parse_sections("## google dorks\nx")["dorks"] == "x"


class TestWindowStopButton:
    """`stop_current_task` — the Stop button in the run bar.

    The 2026-08-19 cull left it calling `self.author_worker` and five other
    attributes that no longer exist, so Stop raised `AttributeError` for every
    agent before reaching any of them.
    """

    def test_stopping_with_nothing_running_does_not_raise(self, win):
        win.stop_current_task()

    def test_it_stops_a_running_panel(self, win, monkeypatch):
        from ui.panels.osint import OsintPanel
        monkeypatch.setattr(OsintPanel, "worker_class", FakeWorker)
        monkeypatch.setattr(win, "authorize_request", lambda *a, **k: True)
        panel = win.panels["osint"]
        panel.target_input.setText("acme.com")
        panel.analyse()
        worker = panel.worker
        try:
            win.stop_current_task()
            assert worker.cancelled is True
            assert panel.status_label.text() == "Stopped."
        finally:
            panel.worker = None
            panel.clear()

    def test_it_touches_no_attribute_that_no_longer_exists(self, win):
        # Every `self.x` the method reaches for directly must be one the window
        # has. Names looked up as strings with a default (`getattr(self, name,
        # None)`) are deliberately exempt — that is the safe form.
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(
            inspect.getsource(type(win).stop_current_task)))
        touched = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "self"
        }
        missing = sorted(a for a in touched if not hasattr(win, a))
        assert missing == [], f"stop_current_task reaches for {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Forge
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def forge(qapp, monkeypatch):
    """Forge against a fake host — including a factory that writes nothing."""
    from ui.panels.manager import ManagerPanel
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(ManagerPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()

    panel = ManagerPanel(FakeHost())
    panel.idea_input.setPlainText("An agent that reviews firewall logs")
    return panel


SPEC = '{"name": "fwreview", "label": "Firewall Review"}'


class TestForgePanel:

    def test_it_builds_without_a_window_and_starts_hidden(self, forge):
        assert forge.isHidden() is True
        assert forge.approve_btn.isEnabled() is False
        assert forge.reject_btn.isEnabled() is False

    def test_it_defaults_to_deepseek(self, forge):
        # Forge is the one panel that does not default to a cloud flagship.
        assert forge.provider == "deepseek"

    def test_an_empty_idea_never_reaches_the_guard(self, forge):
        forge.idea_input.setPlainText("   ")
        forge.analyze_idea()
        assert [c for c in forge.host.calls if c[0] == "authorize"] == []

    def test_a_second_run_while_busy_is_refused(self, forge):
        forge.analyze_idea()
        forge.analyze_idea()
        assert len(FakeWorker.instances) == 1

    def test_a_blocked_request_starts_no_worker(self, forge):
        forge.host.authorized = False
        forge.analyze_idea()
        assert FakeWorker.instances == []

    def test_a_blocked_request_leaves_the_panel_usable(self, forge):
        # The controls are disabled before the guard runs, so a refusal that
        # returns early used to leave Analyze dead until the app restarted.
        forge.host.authorized = False
        forge.analyze_idea()
        assert forge.analyze_btn.isEnabled() is True
        assert "Analyzing" not in forge.spec_display._raw

    def test_a_parsed_spec_enables_approval(self, forge):
        forge.analyze_idea()
        forge.worker.finished_signal.emit(SPEC)
        assert forge.pending_spec == {"name": "fwreview", "label": "Firewall Review"}
        assert forge.approve_btn.isEnabled() is True
        assert forge.reject_btn.isEnabled() is True
        assert "[Ready]" in forge.log.toPlainText()

    def test_an_unparseable_answer_leaves_approval_disabled(self, forge):
        # The response is still shown — the raw text is the only clue to why.
        forge.analyze_idea()
        forge.worker.finished_signal.emit("sorry, I could not do that")
        assert forge.pending_spec is None
        assert forge.approve_btn.isEnabled() is False
        assert "sorry, I could not do that" in forge.spec_display._raw

    def test_an_error_abandons_the_request(self, forge):
        forge.analyze_idea()
        forge.worker.error_signal.emit("provider down")
        assert ("abandon", "request-1", "error") in forge.host.calls
        assert forge.analyze_btn.isEnabled() is True
        assert "[Error]" in forge.log.toPlainText()

    def test_approving_asks_the_host_to_write_the_agent(self, forge):
        forge.analyze_idea()
        forge.worker.finished_signal.emit(SPEC)
        forge.approve_spec()
        assert forge.host.agent_factory.created == [
            {"name": "fwreview", "label": "Firewall Review"}
        ]
        assert "[Created]" in forge.log.toPlainText()
        assert forge.approve_btn.isEnabled() is False
        assert forge.pending_spec is None

    def test_a_failed_creation_is_reported_and_keeps_the_spec(self, forge):
        forge.host.agent_factory.success = False
        forge.analyze_idea()
        forge.worker.finished_signal.emit(SPEC)
        forge.approve_spec()
        assert "[Failed]" in forge.log.toPlainText()
        assert "disk on fire" in forge.log.toPlainText()
        assert forge.pending_spec is not None

    def test_approving_nothing_does_nothing(self, forge):
        forge.approve_spec()
        assert forge.host.agent_factory.created == []

    def test_rejecting_clears_the_spec(self, forge):
        forge.analyze_idea()
        forge.worker.finished_signal.emit(SPEC)
        forge.reject_spec()
        assert forge.pending_spec is None
        assert forge.spec_display._raw == ""
        assert forge.approve_btn.isEnabled() is False

    def test_stop_cancels_and_re_enables_analyse(self, forge):
        # Forge has no Stop button of its own; the window's Stop reaches it, and
        # before phase 4 it did not reach it at all.
        forge.analyze_idea()
        worker = forge.worker
        forge.stop()
        assert worker.cancelled is True
        assert forge.analyze_btn.isEnabled() is True
        assert "[Stopped]" in forge.log.toPlainText()

    def test_clear_resets_the_form(self, forge):
        forge.analyze_idea()
        forge.worker.finished_signal.emit(SPEC)
        forge.clear()
        assert forge.idea_input.toPlainText() == ""
        assert forge.spec_display._raw == ""
        assert forge.pending_spec is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Bug Spray
# ─────────────────────────────────────────────────────────────────────────────

class FakeBugBountyAgent:
    def __init__(self):
        self.calls = []

    def build_messages(self, target, program, scope_type, findings, nmap_output):
        self.calls.append((target, program, scope_type, findings, nmap_output))
        return [{"role": "user", "content": target}]


REPORT = (
    "## VULNERABILITY REPORT\n**Severity** High\nCVSS 8.1\n"
    "A bounty of $1,500 is typical.\n"
    "## Proof of Concept\ncurl …\n"
    "## Remediation\npatch it\n"
    "## SUBMISSION DRAFT\ndraft text"
)


@pytest.fixture
def spray(qapp, monkeypatch):
    from ui.panels.bug_bounty import BugBountyPanel

    monkeypatch.setattr(BugBountyPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()

    host = FakeHost()
    host.agent_instances["bug_bounty"] = FakeBugBountyAgent()
    panel = BugBountyPanel(host)
    panel.target_input.setText("https://target.example.com/app")
    return panel


class TestBugSprayPanel:

    def test_it_builds_hidden_with_saving_disabled(self, spray):
        assert spray.isHidden() is True
        assert spray.save_btn.isEnabled() is False
        assert spray.sections is not None

    def test_nothing_to_analyse_says_so_without_spending(self, spray):
        spray.target_input.clear()
        spray.analyse()
        assert "Enter a target" in spray.status_label.text()
        assert [c for c in spray.host.calls if c[0] == "authorize"] == []

    def test_no_model_says_so_without_spending(self, spray):
        spray.model_box.clear()
        spray.analyse()
        assert spray.status_label.text() == "Select a model first."
        assert [c for c in spray.host.calls if c[0] == "authorize"] == []

    def test_a_blocked_request_leaves_the_panel_usable(self, spray):
        spray.host.authorized = False
        spray.analyse()
        assert FakeWorker.instances == []
        assert spray.analyse_btn.isEnabled() is True
        assert spray.stop_btn.isEnabled() is False

    def test_every_input_reaches_the_agent(self, spray):
        spray.program_input.setText("HackerOne — Acme")
        spray.scope_box.setCurrentText("API / REST")
        spray.findings_input.setPlainText("401 on /admin")
        spray.analyse()
        assert spray.host.agent_instances["bug_bounty"].calls == [
            ("https://target.example.com/app", "HackerOne — Acme",
             "API / REST", "401 on /admin", ""),
        ]

    def test_tokens_stream_into_the_report_view(self, spray):
        spray.analyse()
        spray.worker.token_signal.emit("## VULN")
        spray.worker.token_signal.emit("ERABILITY")
        assert spray.stream_box.toPlainText() == "## VULNERABILITY"

    def test_a_finished_report_fills_the_sections(self, spray):
        from PySide6.QtWidgets import QLabel
        spray.analyse()
        spray.worker.finished_signal.emit(REPORT)
        bodies = [
            label.text() for label in spray.sections.findChildren(QLabel)
            if label.objectName() in ("SectionBody", "SectionMono")
        ]
        assert any("patch it" in body for body in bodies)
        assert any("draft text" in body for body in bodies)
        assert any("curl" in body for body in bodies)
        assert spray.save_btn.isEnabled() is True
        assert spray.status_label.text() == "Analysis complete."

    def test_a_finished_report_fills_the_indicators(self, spray):
        spray.analyse()
        spray.worker.finished_signal.emit(REPORT)
        assert spray.severity_label.text() == "High"
        assert spray.cvss_label.text() == "8.1"
        assert spray.bounty_label.text() == "$1,500"

    def test_indicators_stay_blank_when_the_answer_has_no_figures(self, spray):
        spray.analyse()
        spray.worker.finished_signal.emit("## VULNERABILITY REPORT\nno numbers here")
        assert spray.severity_label.text() == "—"
        assert spray.cvss_label.text() == "—"
        assert spray.bounty_label.text() == "—"

    def test_an_unsectioned_answer_still_shows_something(self, spray):
        # The section view falls back to the whole answer when the model ignores
        # the heading format.
        spray.analyse()
        spray.worker.finished_signal.emit("just prose, no headings")
        assert spray.sections._raw == "just prose, no headings"

    def test_an_error_abandons_the_request(self, spray):
        spray.analyse()
        spray.worker.error_signal.emit("provider down")
        assert ("abandon", "request-1", "error") in spray.host.calls
        assert spray.status_label.text() == "Error."
        assert spray.analyse_btn.isEnabled() is True

    def test_stop_cancels_and_restores_the_controls(self, spray):
        spray.analyse()
        worker = spray.worker
        spray.stop()
        assert worker.cancelled is True
        assert spray.status_label.text() == "Stopped."
        assert spray.analyse_btn.isEnabled() is True
        assert spray.stop_btn.isEnabled() is False

    def test_clear_resets_inputs_outputs_and_indicators(self, spray):
        spray.analyse()
        spray.worker.finished_signal.emit(REPORT)
        spray.clear()
        assert spray.target_input.text() == ""
        assert spray.sections._raw == ""
        assert spray.severity_label.text() == "—"
        assert spray.save_btn.isEnabled() is False

    def test_nmap_needs_a_target_or_a_command(self, spray):
        # Guard before any process is spawned — the test suite must never fork
        # a real scanner.
        spray.target_input.clear()
        spray.nmap_cmd_input.clear()
        spray.run_nmap()
        assert "[Error]" in spray.nmap_output.toPlainText()
        assert spray._nmap_process is None
        assert spray.nmap_run_btn.isEnabled() is True

    def test_the_scan_is_not_a_paid_request(self, spray):
        spray.target_input.clear()
        spray.run_nmap()
        assert [c for c in spray.host.calls if c[0] == "authorize"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Bloodhound
# ─────────────────────────────────────────────────────────────────────────────

class FakeOsintHeavyAgent:
    def __init__(self):
        self.calls = []

    def build_messages(self, target, target_type, scope, objective, image_metadata):
        self.calls.append((target, target_type, scope, objective, image_metadata))
        return [{"role": "user", "content": target}]


DOSSIER = (
    "## 1. OVERVIEW\nwho they are\n"
    "## 2. DIGITAL FOOTPRINT\naccounts\n"
    "## 3. INFRASTRUCTURE / SOCIAL\nhosts\n"
    "## 4. RISK & RED FLAGS\nTHREAT LEVEL: 7/10  CONFIDENCE: 82%  SOURCES REFERENCED: 14\n"
    "## 5. METHODOLOGY\nhow it was found"
)


@pytest.fixture
def hound(qapp, monkeypatch):
    from ui.panels.osint_heavy import OsintHeavyPanel
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(OsintHeavyPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()

    host = FakeHost()
    host.agent_instances["osint_heavy"] = FakeOsintHeavyAgent()
    panel = OsintHeavyPanel(host)
    panel.target_input.setText("acme.com")
    return panel


class TestBloodhoundPanel:

    def test_it_builds_hidden_with_structured_results(self, hound):
        assert hound.isHidden() is True
        assert hound.sections is not None
        assert hound.image_tab is not None
        assert hound.save_btn.isEnabled() is False

    def test_an_empty_target_never_reaches_the_guard(self, hound):
        hound.target_input.clear()
        hound.investigate()
        assert [c for c in hound.host.calls if c[0] == "authorize"] == []

    def test_a_blocked_request_leaves_the_panel_usable(self, hound):
        hound.host.authorized = False
        hound.investigate()
        assert FakeWorker.instances == []
        assert hound.investigate_btn.isEnabled() is True
        assert hound.stop_btn.isEnabled() is False

    def test_the_whole_brief_reaches_the_agent(self, hound):
        hound.type_box.setCurrentText("Organisation")
        hound.scope_box.setCurrentText("Deep Dive")
        hound.objective_input.setPlainText("map infrastructure")
        hound.investigate()
        assert hound.host.agent_instances["osint_heavy"].calls == [
            ("acme.com", "Organisation", "Deep Dive", "map infrastructure", ""),
        ]

    def test_the_scope_is_shown_as_the_depth_indicator(self, hound):
        hound.scope_box.setCurrentText("Quick Scan")
        hound.investigate()
        assert hound.depth_label.text() == "Quick Scan"

    def test_a_finished_dossier_fills_structured_cards(self, hound):
        from PySide6.QtWidgets import QLabel, QWidget
        hound.investigate()
        hound.worker.finished_signal.emit(DOSSIER)
        card_text = "\n".join(
            card.findChild(QLabel).text()
            for card in hound.sections.findChildren(QWidget)
            if card.objectName() == "SectionCard" and card.findChild(QLabel)
        )
        assert "Overview" in card_text
        assert hound.sections._raw == DOSSIER
        assert hound.save_btn.isEnabled() is True

    def test_a_finished_dossier_fills_the_indicators(self, hound):
        hound.investigate()
        hound.worker.finished_signal.emit(DOSSIER)
        assert hound.threat_label.text() == "7/10"
        assert hound.threat_bar.value() == 7
        assert hound.conf_label.text() == "82%"
        assert hound.sources_label.text() == "14"

    def test_an_error_abandons_the_request(self, hound):
        hound.investigate()
        hound.worker.error_signal.emit("provider down")
        assert ("abandon", "request-1", "error") in hound.host.calls
        assert hound.status_label.text() == "Error."

    def test_stop_restores_the_controls(self, hound):
        hound.investigate()
        hound.stop()
        assert hound.investigate_btn.isEnabled() is True
        assert hound.status_label.text() == "Stopped."

    def test_clear_resets_the_brief_the_results_and_the_image(self, hound):
        hound.investigate()
        hound.worker.finished_signal.emit(DOSSIER)
        hound.clear()
        assert hound.target_input.text() == ""
        assert hound.sections._raw == ""
        assert hound.threat_bar.value() == 0
        assert hound.image_label.text() == "No image selected"

    def test_an_attached_image_puts_its_metadata_in_the_prompt(self, hound, tmp_path):
        # No EXIF in a text file — the point is that the panel sends *something*
        # about the image rather than silently dropping it.
        fake = tmp_path / "target.jpg"
        fake.write_text("not really a jpeg")
        hound.set_image(str(fake))
        hound.investigate()
        metadata = hound.host.agent_instances["osint_heavy"].calls[-1][4]
        assert "No EXIF metadata could be extracted" in metadata

    def test_no_image_means_no_metadata_in_the_prompt(self, hound):
        hound.investigate()
        assert hound.host.agent_instances["osint_heavy"].calls[-1][4] == ""

    def test_attaching_an_image_fills_the_image_tab(self, hound, tmp_path):
        fake = tmp_path / "target.jpg"
        fake.write_text("not really a jpeg")
        hound.set_image(str(fake))
        assert hound.image_label.text() == "target.jpg"
        assert "Image OSINT" in hound.image_tab.toPlainText()
        assert "No EXIF data found" in hound.image_tab.toPlainText()


class TestBloodhoundParsing:
    """Dossier sections and EXIF — no widgets, no host."""

    def test_each_numbered_heading_becomes_a_section(self):
        from ui.panels.osint_heavy import OsintHeavyPanel
        parsed = OsintHeavyPanel.parse_sections(DOSSIER)
        assert parsed["overview"] == "who they are"
        assert parsed["footprint"] == "accounts"
        assert parsed["methodology"] == "how it was found"

    def test_missing_headings_come_back_empty(self):
        from ui.panels.osint_heavy import OsintHeavyPanel
        parsed = OsintHeavyPanel.parse_sections("## 1. OVERVIEW\nonly this")
        assert parsed["overview"] == "only this"
        assert parsed["risk"] == ""

    def test_gps_south_and_west_are_negative(self):
        from ui.panels.osint_heavy import gps_to_decimal
        assert gps_to_decimal((51, 30, 0), "N") == 51.5
        assert gps_to_decimal((51, 30, 0), "S") == -51.5
        assert gps_to_decimal((0, 7, 30), "W") == -0.125

    def test_unreadable_coordinates_are_zero_rather_than_an_exception(self):
        from ui.panels.osint_heavy import gps_to_decimal
        assert gps_to_decimal(("x", "y", "z"), "N") == 0.0
        assert gps_to_decimal((), "N") == 0.0

    def test_a_file_with_no_exif_is_not_an_error(self, tmp_path):
        from ui.panels.osint_heavy import exif_summary, extract_exif
        f = tmp_path / "plain.jpg"
        f.write_text("not really a jpeg")
        assert extract_exif(str(f)) == {}
        assert exif_summary(str(f)) == "No EXIF data found in this image."

    def test_a_missing_file_is_not_an_error(self):
        from ui.panels.osint_heavy import extract_exif
        assert extract_exif("/no/such/image.jpg") == {}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Tunnel
# ─────────────────────────────────────────────────────────────────────────────

class FakeVpnAgent:
    def __init__(self):
        self.prompts = []

    def build_messages(self, prompt):
        self.prompts.append(prompt)
        return [{"role": "user", "content": prompt}]


@pytest.fixture
def tunnel(qapp, monkeypatch):
    from ui.panels.vpn import VpnPanel
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(VpnPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()

    host = FakeHost()
    host.agent_instances["vpn"] = FakeVpnAgent()
    panel = VpnPanel(host)
    panel.question_input.setText("hotel wifi blocks UDP")
    return panel


class TestTunnelPanel:

    def test_it_builds_hidden_with_two_result_tabs(self, tunnel):
        assert tunnel.isHidden() is True
        assert tunnel.tabs.count() == 2

    def test_an_empty_question_never_reaches_the_guard(self, tunnel):
        tunnel.question_input.clear()
        tunnel.run()
        assert [c for c in tunnel.host.calls if c[0] == "authorize"] == []

    def test_the_deployment_setup_is_prepended_as_context(self, tunnel):
        tunnel.mode_box.setCurrentText("Native (home LAN)")
        tunnel.host_input.setText("203.0.113.9")
        tunnel.run()
        prompt = tunnel.host.agent_instances["vpn"].prompts[-1]
        assert prompt.startswith("Context —")
        assert "Native (home LAN)" in prompt
        assert "203.0.113.9" in prompt
        assert prompt.rstrip().endswith("hotel wifi blocks UDP")

    def test_the_mode_is_passed_as_the_guard_label(self, tunnel):
        tunnel.mode_box.setCurrentText("Remote (VPS)")
        tunnel.run()
        authorize = [c for c in tunnel.host.calls if c[0] == "authorize"][-1]
        assert authorize[6] == "Remote (VPS)"

    def test_an_answer_is_recorded_and_shown(self, tunnel):
        tunnel.run()
        tunnel.worker.finished_signal.emit("Use OpenVPN on 443.")
        assert ("record", "request-1", "Use OpenVPN on 443.", None) in tunnel.host.calls
        assert tunnel.advisor_box.toPlainText() == "Use OpenVPN on 443."
        assert tunnel.status_label.text() == "Done."

    def test_an_error_abandons_the_request(self, tunnel):
        tunnel.run()
        tunnel.worker.error_signal.emit("no route")
        assert ("abandon", "request-1", "error") in tunnel.host.calls
        assert "ERROR" in tunnel.advisor_box.toPlainText()

    def test_build_config_is_offline_and_costs_nothing(self, tunnel):
        tunnel.mode_box.setCurrentText("Remote (VPS)")
        tunnel.host_input.setText("203.0.113.9")
        tunnel.build_config()
        text = tunnel.config_box.toPlainText()
        assert "203.0.113.9" in text
        assert tunnel.tabs.currentIndex() == 1
        assert [c for c in tunnel.host.calls if c[0] == "authorize"] == []

    def test_stop_restores_the_controls(self, tunnel):
        tunnel.run()
        tunnel.stop()
        assert tunnel.run_btn.isEnabled() is True
        assert tunnel.status_label.text() == "Stopped."


# ─────────────────────────────────────────────────────────────────────────────
# 8. Beacon
# ─────────────────────────────────────────────────────────────────────────────

class FakeWifiAgent:
    def __init__(self):
        self.prompts = []

    def build_messages(self, prompt):
        self.prompts.append(prompt)
        return [{"role": "user", "content": prompt}]


@pytest.fixture
def beacon(qapp, monkeypatch):
    import ui.panels.wifi as wifi_mod
    from ui.panels.wifi import WifiPanel
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(wifi_mod, "SubprocessWorker", FakeScanWorker)
    monkeypatch.setattr(WifiPanel, "worker_class", FakeWorker)
    FakeWorker.instances.clear()
    FakeScanWorker.instances.clear()

    host = FakeHost()
    host.agent_instances["wifi"] = FakeWifiAgent()
    return WifiPanel(host)


class TestBeaconPanel:

    def test_it_builds_hidden_with_the_kali_form_collapsed(self, beacon):
        assert beacon.isHidden() is True
        assert beacon.kali_group.isHidden() is True

    def test_switching_to_kali_reveals_the_form_and_disables_ai(self, beacon):
        beacon.mode_box.setCurrentText("Kali Command Builder")
        assert beacon.kali_group.isHidden() is False
        assert beacon.ai_checkbox.isEnabled() is False

    def test_a_scan_runs_a_subprocess_not_a_paid_request(self, beacon):
        beacon.mode_box.setCurrentText("Scan Networks")
        beacon.run()
        assert FakeScanWorker.instances  # a scan was started
        assert [c for c in beacon.host.calls if c[0] == "authorize"] == []

    def test_ping_needs_a_target(self, beacon):
        beacon.mode_box.setCurrentText("Ping Test")
        beacon.target_input.clear()
        beacon.run()
        assert FakeScanWorker.instances == []
        assert beacon.run_btn.isEnabled() is True

    def test_a_scan_feeds_the_ai_pass_when_the_box_is_ticked(self, beacon):
        beacon.mode_box.setCurrentText("Scan Networks")
        beacon.ai_checkbox.setChecked(True)
        beacon.run()
        beacon.scan_worker.finished_signal.emit("agrCtlRSSI: -55\nlink auth: wpa2-psk")
        # raw indicators from the scan, then a paid analysis of it
        assert beacon.security_label.text() == "WPA2-PSK"
        assert beacon.signal_bar.value() == 90
        assert [c for c in beacon.host.calls if c[0] == "authorize"]
        assert beacon.mode_box.currentText() in beacon.host.agent_instances["wifi"].prompts[-1]

    def test_ai_answer_becomes_structured_sections(self, beacon):
        beacon._active_request_id = "request-1"
        beacon._on_finished(
            "1. SUMMARY\nconnected\n2. NETWORK FINDINGS\nchannel 6\n"
            "3. SECURITY OBSERVATIONS\nWPA2\n4. RECOMMENDATIONS\nuse WPA3"
        )
        assert "channel 6" in beacon.sections._raw
        assert beacon.sections.isHidden() is False

    def test_a_scan_without_ai_just_shows_the_raw_output(self, beacon):
        beacon.mode_box.setCurrentText("Scan Networks")
        beacon.ai_checkbox.setChecked(False)
        beacon.run()
        beacon.scan_worker.finished_signal.emit("agrCtlRSSI: -80")
        assert [c for c in beacon.host.calls if c[0] == "authorize"] == []
        assert beacon.save_btn.isEnabled() is True

    def test_the_kali_builder_is_offline(self, beacon):
        beacon.mode_box.setCurrentText("Kali Command Builder")
        beacon.ai_checkbox.setChecked(False)
        beacon.kali_bssid_input.setText("AA:BB:CC:DD:EE:FF")
        beacon.run()
        assert beacon.kali_cmd_box.toPlainText() != ""
        assert [c for c in beacon.host.calls if c[0] == "authorize"] == []
        assert beacon.save_btn.isEnabled() is True

    def test_kali_mode_disables_the_ai_pass(self, beacon):
        # Switching to Kali mode disables the AI checkbox, and the builder only
        # runs the explanation when the box is *enabled* and ticked — so in Kali
        # mode no paid request fires even with the box checked. This is the
        # behaviour moved verbatim from GodAI; a redesign is TODO, not this move.
        beacon.mode_box.setCurrentText("Kali Command Builder")
        beacon.ai_checkbox.setChecked(True)
        beacon.run()
        assert beacon.ai_checkbox.isEnabled() is False
        assert [c for c in beacon.host.calls if c[0] == "authorize"] == []

    def test_stop_cancels_a_scan_that_has_no_ai_worker_yet(self, beacon):
        # A scan can be running with no ChatWorker in existence; stop must reach it.
        beacon.mode_box.setCurrentText("Scan Networks")
        beacon.ai_checkbox.setChecked(False)
        beacon.run()
        scan = beacon.scan_worker
        assert beacon.is_running() is True
        beacon.stop()
        assert scan.cancelled if hasattr(scan, "cancelled") else not scan.isRunning()
        assert beacon.status_label.text() == "Stopped."

    def test_signal_indicator_reads_rssi(self, beacon):
        beacon._update_indicators("agrCtlRSSI: -40")
        assert beacon.signal_bar.value() == 100
        assert "-40 dBm" in beacon.signal_val_label.text()

    def test_clear_resets_everything(self, beacon):
        beacon.raw_box.setPlainText("stuff")
        beacon.target_input.setText("192.168.1.1")
        beacon.clear()
        assert beacon.raw_box.toPlainText() == ""
        assert beacon.target_input.text() == ""
        assert beacon.signal_bar.value() == 0
