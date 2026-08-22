import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from services.runtime_paths import resource_base, user_data_base, ensure_seeded, is_frozen
ensure_seeded()

# Anchor the working directory to the writable base so the handful of services
# that still use relative paths ("data/chats", "config/settings.json", ...) resolve
# correctly no matter how the app was launched (Finder launches with cwd="/").
os.chdir(str(user_data_base()))

from dotenv import load_dotenv
# API keys: user-data .env when frozen, project .env in dev. Real env vars still win.
load_dotenv(user_data_base() / ".env")

import markdown

from PySide6.QtCore import Qt, QTimer, QProcess, QUrl, QThread, Signal, QEvent, QRect, QPoint, QSize
from PySide6.QtGui import QTextCursor, QDesktopServices, QColor, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QSizePolicy, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QTextEdit, QPushButton, QComboBox, QListWidget, QListWidgetItem,
    QMessageBox, QCheckBox, QTextBrowser, QSplitter, QLineEdit, QFileDialog,
    QProgressBar, QDialog, QTabWidget, QFrame, QScrollArea, QStackedWidget, QLayout,
    QInputDialog, QMenu, QWidgetAction,
)

from services.ollama_client import OllamaClient, MUSE_GLIMMER_VARIANTS, muse_glimmer_default
from services.openai_client import OpenAIClientWrapper
from services.deepseek_client import DeepSeekClientWrapper
from services.kimi_client import KimiClientWrapper
from services.gemini_client import GeminiClientWrapper
from services.anthropic_client import AnthropicClientWrapper
from services.qwen_client import QwenClientWrapper
from services.resource_monitor import ResourceMonitor
from services.history_store import HistoryStore
from services.report_exporter import ReportExporter
from services.usage_tracker import UsageTracker
from services.pricing import CostEstimate, PricingUnavailable
from services.model_router import ModelRouter, ModelCandidate, RoutingPreferences
from services.database import init_db, get_setting, save_setting, get_connection
from services.registry import Registry
from services.validator import Validator
from services.run_logger import RunLogger

from agents.chat_agent import ChatAgent
from agents.writing_agent import WritingAgent
from agents.coding_agent import CodingAgent
from agents.osint_agent import OSINTAgent
from agents.bug_bounty_agent import BugBountyAgent
from agents.wifi_agent import WiFiAgent
from agents.osint_heavy_agent import OsintHeavyAgent
from agents.vpn_agent import VpnAgent
from services.agent_factory import AgentFactory


# Writable base = project root in dev, ~/Library/Application Support/Sentinel when frozen.
BASE_DIR = user_data_base()
# Read-only bundled resources (README, config defaults) = project root in dev, bundle when frozen.
RESOURCE_DIR = resource_base()
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CHATS_DIR = DATA_DIR / "chats"

# Sentinel value for the Saved Chats agent filter — not a real agent name.
ALL_AGENTS_FILTER = "All agents"
ALL_PROJECTS_FILTER = "All projects"
UNFILED_PROJECT_FILTER = "Unfiled"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
AGENTS_FILE = CONFIG_DIR / "agents.json"
COMMANDS_FILE = CONFIG_DIR / "commands.json"
TOOL_PROMPTS_FILE = CONFIG_DIR / "tool_prompts.json"
REGISTRY_FILE = CONFIG_DIR / "registry.json"
README_FILE = RESOURCE_DIR / "README.md"

# ── Per-agent recommended setup ──────────────────────────────────────────────
# Single source of truth for "which provider + model is right for THIS agent".
# Each panel pre-selects its entry on startup, and the recommended provider and
# model are painted red in their dropdowns so the user can always see what the
# recommendation was, even after switching to something else mid-session.
#
# `provider` must match an item in that panel's provider box. `model` is matched
# leniently (exact -> prefix -> substring) so a dated API id such as
# "claude-sonnet-4-6-20260112" still resolves from "claude-sonnet-4-6".
RECOMMENDED_COLOR = "#ff5555"

AGENT_RECOMMENDATIONS = {
    "osint": {
        "provider": "deepseek", "model": "deepseek-v4-flash",
        "reason": "Light, high-volume lookups and summaries — DeepSeek's flash tier "
                  "gives solid structured output at the lowest cost per query.",
    },
    "osint_heavy": {
        "provider": "anthropic", "model": "claude-opus-5",
        "reason": "Deep multi-source dossiers need the strongest long-context "
                  "synthesis. Low volume, so the higher token price is worth it.",
    },
    "wifi": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Generating correct Kali/aircrack command lines rewards precision; "
                  "Sonnet is accurate on tooling syntax without Opus pricing.",
    },
    "bug_bounty": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Vulnerability triage plus a readable HackerOne write-up — Sonnet "
                  "handles both the security reasoning and the report prose.",
    },
    "manager": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Forge writes real agent source files — code generation quality "
                  "matters more here than cost.",
    },
    "vpn": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "WireGuard/OpenVPN config and kill-switch reasoning rewards precise "
                  "command syntax; Sonnet is accurate on tooling without Opus pricing.",
    },
}

# agent key -> (provider box attribute, model box attribute)
AGENT_SETUP_WIDGETS = {
    "chat":        ("provider_box",             "model_box"),
    "osint":       None,  # OsintPanel owns its boxes (phase 4)
    "osint_heavy": None,  # OsintHeavyPanel owns its boxes (phase 4)
    "wifi":        None,  # WifiPanel owns its boxes (phase 4)
    "bug_bounty":  None,  # BugBountyPanel owns its boxes (phase 4)
    "manager":     None,  # ManagerPanel owns its boxes (phase 4)
    "vpn":         None,  # VpnPanel owns its boxes (phase 4)
}

AGENT_PRETTY_NAMES = {
    "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
    "wifi": "Beacon", "bug_bounty": "Bug Spray",
    "manager": "Forge", "vpn": "Tunnel", }


from ui.workers import (
    ChatWorker, SubprocessWorker, ModelPullWorker,
)
from ui.widgets import FlowLayout, KeyValue, Meter, SectionView
from ui.style import GLOBAL_STYLESHEET
from ui.tooltips import seed_tooltips
from ui.panels.base import PROVIDERS, build_provider_row
from ui.panels.bug_bounty import BugBountyPanel
from ui.panels.manager import ManagerPanel
from ui.panels.osint_heavy import OsintHeavyPanel
from ui.panels.vpn import VpnPanel
from ui.panels.wifi import WifiPanel
from ui.panels.osint import OsintPanel

class GodAI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Sentinel Fork")
        self.resize(1400, 900)
        # The run bar is a single row so the cost can sit right-aligned as the
        # design has it; a wrapping bar cannot right-align. That costs width, so
        # the minimum is set where the three panes still fit rather than letting
        # the splitter crush them.
        self.setMinimumSize(1200, 700)
        self.showMaximized()

        CONFIG_DIR.mkdir(exist_ok=True)
        DATA_DIR.mkdir(exist_ok=True)
        CHATS_DIR.mkdir(parents=True, exist_ok=True)

        init_db()

        self.commands = self.load_json(COMMANDS_FILE, {"General Chat": ""})
        self.tool_prompts = self.load_json(TOOL_PROMPTS_FILE, {
            "General Chat": {"system": "You are a helpful general assistant."}
        })
        self.agents_config = self.load_json(
            AGENTS_FILE,
            {"agents": ["chat", "writing", "coding", "osint"]},
        )
        self.settings = self.load_json(SETTINGS_FILE, {})

        self.ollama = OllamaClient()
        self.openai = OpenAIClientWrapper()
        self.deepseek = DeepSeekClientWrapper()
        self.kimi = KimiClientWrapper()
        self.gemini = GeminiClientWrapper()
        self.anthropic = AnthropicClientWrapper()
        self.qwen = QwenClientWrapper()
        self.monitor = ResourceMonitor()
        self.history = HistoryStore()
        self.report_exporter = ReportExporter()
        self.usage_tracker = UsageTracker()

        self.registry = Registry()
        self.validator = Validator(self.registry)
        self.active_project_id: str | None = None
        self.run_logger = RunLogger()
        # agent name -> context for an in-flight request (see authorize_request)
        self._pending_requests = {}
        # agent key -> the panel's own "reload the model list" callable, filled
        # in as each panel builds (see register_model_loader)
        self._model_loaders = {}
        # agent key -> panel, for the verticals that have moved to ui/panels/.
        # Everything that has to find a panel's widgets goes through this rather
        # than through `GodAI` attributes (see setup_widgets_for).
        self.panels: dict = {}

        self.agent_factory = AgentFactory(BASE_DIR)
        self._wifi_detected_adapter: dict = {}

        self.agent_instances = {
            "chat": ChatAgent(),
            "writing": WritingAgent(),
            "coding": CodingAgent(),
            "osint": OSINTAgent(),
            "bug_bounty": BugBountyAgent(),
            "wifi": WiFiAgent(),
            "osint_heavy": OsintHeavyAgent(),
            "vpn": VpnAgent(),
        }

        self.current_messages = []
        self.last_raw_osint = ""

        self.session_cost_total = 0.0
        self.session_request_count = 0
        self.last_request_cost = 0.0
        
        self.session_budget_eur = float(self.settings.get("session_budget_eur", 1.00))
        self.daily_budget_eur = float(self.settings.get("daily_budget_eur", 5.00))

        self.chat_worker: Optional[ChatWorker] = None
        self.active_run_id: Optional[str] = None
        self.chat_started_at: Optional[float] = None
        self.chat_elapsed_seconds = 0
        self.chat_estimated_seconds = 30

        self.pending_agent = ""
        self.pending_backend = ""
        self.pending_model = ""
        self.pending_command = ""
        self.pending_prompt = ""
        self.pending_messages = []

        # Tooltip state — toggled via the chip in the centre header bar
        self.tooltips_enabled = True

        self.build_ui()
        self._polish_tab_widgets()
        self._seed_tooltips()
        # Install global event filter so we can suppress ToolTip events when disabled
        from PySide6.QtWidgets import QApplication as _QApp
        _QApp.instance().installEventFilter(self)
        self.load_models()
        # Pre-select each agent's recommended provider/model and paint those
        # entries red in their dropdowns. Runs after every panel is built.
        self.install_agent_recommendations()
        self.muse_pull_worker: Optional[ModelPullWorker] = None
        self.refresh_muse_button()
        self.refresh_project_selector()
        self.load_history_list()
        self.update_resource_label()
        self.update_usage_labels()
        self.start_resource_timer()
        self.select_agent("chat")

    def _polish_tab_widgets(self):
        """Disable text elision and enable scroll buttons on every QTabWidget
        in the app so long tab titles never get cut off with ellipses."""
        for tabs in self.findChildren(QTabWidget):
            tabs.setElideMode(Qt.ElideNone)
            tabs.setUsesScrollButtons(True)
            tabs.setDocumentMode(False)
            # Let the tab bar expand and request its preferred (full) text size
            tab_bar = tabs.tabBar()
            if tab_bar is not None:
                tab_bar.setExpanding(False)
                tab_bar.setUsesScrollButtons(True)

    # ── Tooltips ────────────────────────────────────────────────────────────
    def _toggle_tooltips(self):
        """Enable or disable hover tooltips application-wide."""
        self.tooltips_enabled = self.tooltips_toggle_btn.isChecked()
        self.tooltips_toggle_btn.setText(
            "💡 Tooltips: On" if self.tooltips_enabled else "💡 Tooltips: Off"
        )

    def eventFilter(self, obj, event):
        """Swallow QEvent.ToolTip when tooltips are toggled off."""
        if event.type() == QEvent.ToolTip and not self.tooltips_enabled:
            return True
        return super().eventFilter(obj, event)

    def _set_tooltips(self, mapping: dict):
        """Helper: apply a {widget_attr_name: text} mapping in one call.

        A dotted name — "osint.provider_box" — addresses a widget inside a panel
        that has moved to `ui/panels/`; a bare one is still an attribute of the
        window. Both are skipped silently when absent, which is why a moved
        panel has to bring its tooltip names with it: nothing would report the
        loss.
        """
        for attr, text in mapping.items():
            if "." in attr:
                agent_key, _, widget_name = attr.partition(".")
                panel = self.panels.get(agent_key)
                widget = getattr(panel, widget_name, None) if panel else None
            else:
                widget = getattr(self, attr, None)
            if widget is not None:
                widget.setToolTip(text)

    def _seed_tooltips(self):
        seed_tooltips(self)

    def load_json(self, path: Path, default):
        if not path.exists():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def safe_key_status(self, cls):
        try:
            return "✅ available" if cls.key_available() else "❌ not set"
        except Exception:
            return "unknown"

    def estimate_chat_seconds(self, backend: str, model: str, prompt: str) -> int:
        words = max(1, len(prompt.split()))
        base = 10
        if backend == "ollama":
            if "8b" in model.lower():
                base = 35
            elif "1.5b" in model.lower():
                base = 12
            else:
                base = 25
        elif backend in {"openai", "deepseek", "kimi", "gemini"}:
            base = 15
        return min(180, max(10, base + words // 20))

    def estimate_chat_cost(self, backend, model, prompt):
        """Pre-flight cost estimate in EUR, plus the approximate token count.

        Prices come from the pricing table via UsageTracker — the same source
        that bills the request afterwards. This used to be a second hardcoded
        per-backend dict which had no entry for anthropic or qwen, so both were
        estimated at zero and sailed straight past the budget gate in
        Validator.validate() no matter how expensive the model was.
        """
        approx_input_tokens = max(1, int(len(prompt) / 4))
        approx_output_min = max(128, int(approx_input_tokens * 0.5))
        approx_output_max = max(500, int(approx_input_tokens * 1.8))
        approx_total_tokens = approx_input_tokens + approx_output_max

        if backend == "ollama":
            return 0.0, approx_total_tokens

        if hasattr(self.usage_tracker, "estimate_cost_range"):
            estimate = self.usage_tracker.estimate_cost_range(
                backend, model, approx_input_tokens, approx_output_min, approx_output_max)
        else:
            # Compatibility for injected/third-party trackers implementing the
            # original scalar API. Production UsageTracker always supplies a range.
            scalar = self.usage_tracker.calculate_cost_eur(
                backend, model, approx_input_tokens, approx_output_max)
            estimate = CostEstimate(True, scalar, scalar, approx_input_tokens,
                                    approx_output_min, approx_output_max)
        self._last_cost_range = estimate
        return (round(estimate.maximum_eur, 5) if estimate.available else float("inf")), approx_total_tokens

    def get_current_cost_estimate(self):
        raw_text = self.input_box.toPlainText().strip()

        if not raw_text:
            return 0.0, 0, None, None

        _, full_prompt = self.build_user_prompt(raw_text)
        backend, model = self.resolve_backend_model()

        estimated_cost, approx_tokens = self.estimate_chat_cost(
            backend,
            model,
            full_prompt
        )

        return estimated_cost, approx_tokens, backend, model
    
    def show_cost_history(self):
        from ui.dialogs import show_cost_history as _show_cost_history
        return _show_cost_history(self)
    def show_run_log(self):
        from ui.dialogs import show_run_log as _show_run_log
        return _show_run_log(self)
    def show_settings(self):
        from ui.dialogs import show_settings as _show_settings
        return _show_settings(self)
    def update_live_cost_estimate(self):
        if not hasattr(self, "live_estimate_label"):
            return


        estimated_cost, approx_tokens, backend, model = self.get_current_cost_estimate()

        if hasattr(self, "runbar_cost"):
            tokens = f"{approx_tokens/1000:.1f}k" if approx_tokens >= 1000 else str(approx_tokens)
            if backend == "ollama":
                self.runbar_cost.setText(f"free · {tokens} tok")
            elif estimated_cost == float("inf"):
                self.runbar_cost.setText(f"price unavailable · {tokens} tok")
            else:
                self.runbar_cost.setText(f"~€{estimated_cost:.2f} · {tokens} tok")

        if not backend:
            self.live_estimate_label.setText("")
        elif backend == "ollama":
            self.live_estimate_label.setText("")
        elif estimated_cost == float("inf"):
            reason = getattr(getattr(self, "_last_cost_range", None), "reason", "Unknown pricing")
            self.live_estimate_label.setText(f"⛔ {reason}")
        elif backend != "ollama":
            estimate = self._last_cost_range
            self.live_estimate_label.setText(
                f"€{estimate.minimum_eur:.4f}–€{estimate.maximum_eur:.4f} · paid API"
            )
        else:
            self.live_estimate_label.setText("")

    def show_cost_estimate_popup(self):
        estimated_cost, approx_tokens, backend, model = self.get_current_cost_estimate()

        if backend == "ollama":
            msg = (
                f"Agent: {self.agent_box.currentText()}\n"
                f"Backend: {backend}\n"
                f"Model: {model}\n"
                f"Approx tokens: {approx_tokens}\n\n"
                f"Estimated cost: €0.0000\n"
                f"This is local execution."
            )
        elif estimated_cost == float("inf"):
            reason = getattr(getattr(self, "_last_cost_range", None), "reason", "Unknown pricing")
            msg = f"Backend: {backend}\nModel: {model}\n\nCost unavailable: {reason}\nRequest will be blocked."
        else:
            estimate = self._last_cost_range
            msg = (
                f"Agent: {self.agent_box.currentText()}\n"
                f"Backend: {backend}\n"
                f"Model: {model}\n"
                f"Approx tokens: {approx_tokens}\n\n"
                f"Estimated cost: €{estimate.minimum_eur:.4f}–€{estimate.maximum_eur:.4f}\n"
                f"⚠ This may use a paid API."
            )

        QMessageBox.information(self, "Cost Estimate", msg)

    def format_seconds(self, total: int) -> str:
        total = max(0, int(total))
        return f"{total // 60:02d}:{total % 60:02d}"

    # ── Local-model memory guard ─────────────────────────────────────────────
    # Cloud models cost money and are gated by budget. Local models are free, so
    # they bypassed every check — yet they are the only ones that can wedge the
    # machine. This sizes the model against real memory before it is loaded.

    # A loaded model needs roughly its file size resident, plus KV cache and
    # runtime overhead. 1.15 is a deliberately mild allowance: the aim is to
    # catch "this will thrash", not to model llama.cpp allocation exactly.
    MEMORY_OVERHEAD_FACTOR = 1.15
    # Leave room for the OS and Sentinel itself rather than letting a model take
    # every last byte of physical RAM.
    MEMORY_HEADROOM_GB = 3.0

    def assess_local_model(self, model: str) -> dict | None:
        """Weigh a local model against this machine's memory.

        Returns None when the check does not apply (not a known local model, or
        the daemon is unreachable and the size is unknowable). Otherwise a dict
        with level "ok" | "tight" | "too_big", the numbers behind it, and a
        human-readable message.
        """
        import psutil

        size_bytes = self.ollama.model_size_bytes(model)
        if size_bytes is None:
            # Not pulled yet — fall back to the published download size for the
            # builds we ship a figure for, so the dropdown can grey them out.
            published_gb = MUSE_GLIMMER_VARIANTS.get(model)
            if published_gb is None:
                return None
            size_gb = float(published_gb)
        else:
            size_gb = size_bytes / 1e9

        needed_gb = size_gb * self.MEMORY_OVERHEAD_FACTOR
        vm = psutil.virtual_memory()
        total_gb = vm.total / 1e9
        available_gb = vm.available / 1e9

        if needed_gb > total_gb - self.MEMORY_HEADROOM_GB:
            level = "too_big"
            message = (
                f"{model} needs about {needed_gb:.1f} GB of memory, but this machine "
                f"only has {total_gb:.0f} GB in total. It cannot run here without "
                "swapping so hard the system becomes unresponsive."
            )
        elif needed_gb > available_gb:
            level = "tight"
            message = (
                f"{model} needs about {needed_gb:.1f} GB, but only {available_gb:.1f} GB "
                f"is free right now (of {total_gb:.0f} GB). It will fit, but expect "
                "heavy swapping and slow replies — closing other apps will help."
            )
        else:
            level = "ok"
            message = f"{model} needs ~{needed_gb:.1f} GB; {available_gb:.1f} GB free."

        return {
            "level": level,
            "model": model,
            "needed_gb": needed_gb,
            "available_gb": available_gb,
            "total_gb": total_gb,
            "message": message,
        }

    def check_memory_before_request(self, backend: str, model: str) -> bool:
        """Interactive pre-flight for local models. False means "do not run".

        Must be called from the GUI thread, before the worker is constructed.
        """
        if backend != "ollama":
            return True

        verdict = self.assess_local_model(model)
        if verdict is None or verdict["level"] == "ok":
            return True

        if verdict["level"] == "too_big":
            QMessageBox.critical(self, "Model Too Large For This Machine", verdict["message"])
            return False

        choice = QMessageBox.warning(
            self,
            "Low Memory",
            verdict["message"] + "\n\nRun it anyway?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return choice == QMessageBox.Yes

    def check_budget_before_request(self, estimated_cost: float, backend: str) -> bool:
        if backend == "ollama":
            return True

        today_total = self.usage_tracker.get_today_total()

        session_remaining = self.session_budget_eur - self.session_cost_total
        daily_remaining = self.daily_budget_eur - today_total

        if estimated_cost > session_remaining:
            QMessageBox.warning(
                self,
                "Session Budget Exceeded",
                f"This request is estimated at €{estimated_cost:.2f}, "
                f"but your remaining session budget is only €{session_remaining:.2f}."
            )
            return False

        if estimated_cost > daily_remaining:
            QMessageBox.warning(
                self,
                "Daily Budget Exceeded",
                f"This request is estimated at €{estimated_cost:.2f}, "
                f"but your remaining daily budget is only €{daily_remaining:.2f}."
            )
            return False

        return True

    def save_budget_limits(self):
        try:
            self.session_budget_eur = float(self.session_budget_input.text().strip())
            self.daily_budget_eur = float(self.daily_budget_input.text().strip())

            save_setting("session_budget_eur", str(self.session_budget_eur))
            save_setting("daily_budget_eur", str(self.daily_budget_eur))

            self.update_usage_labels()
            QMessageBox.information(self, "Budget Saved", "Budget limits saved.")

        except ValueError:
            QMessageBox.warning(self, "Invalid Budget", "Please enter valid numbers.")

    def reset_session_spend(self):
        self.session_cost_total = 0.0
        self.session_request_count = 0
        self.update_usage_labels()
        QMessageBox.information(self, "Session Reset", "Session spend has been reset.")

    def get_recommended_setup(self):
        agent = self.agent_box.currentText() if hasattr(self, "agent_box") else "chat"
        tool = self.tool_box.currentText() if hasattr(self, "tool_box") else "General Chat"
        command = self.command_box.currentText() if hasattr(self, "command_box") else "General Chat"
        prompt = self.input_box.toPlainText().strip() if hasattr(self, "input_box") else ""
        tool_config = self.tool_prompts.get(tool, {})
        tool_provider = tool_config.get("recommended_provider")
        tool_model = tool_config.get("recommended_model")
        
        if tool_provider:
            model = tool_model or self.model_box.currentText()

            # ===== CHECK API PERMISSION =====
            if tool_provider == "openai" and not self.allow_openai_checkbox.isChecked():
                return {
                    "mode": "Local only",
                    "provider": "ollama",
                    "model": self.model_box.currentText(),
                    "reason": f"{tool} recommends OpenAI, but API is disabled. Using local model."
                }

            if tool_provider == "deepseek" and not self.allow_deepseek_checkbox.isChecked():
                return {
                    "mode": "Local only",
                    "provider": "ollama",
                    "model": self.model_box.currentText(),
                    "reason": f"{tool} recommends DeepSeek, but API is disabled. Using local model."
                }

            if tool_provider == "kimi" and not self.allow_kimi_checkbox.isChecked():
                return {
                    "mode": "Local only",
                    "provider": "ollama",
                    "model": self.model_box.currentText(),
                    "reason": f"{tool} recommends Kimi, but API is disabled. Using local model."
                }

            if tool_provider == "gemini" and not self.allow_gemini_checkbox.isChecked():
                return {
                    "mode": "Local only",
                    "provider": "ollama",
                    "model": self.model_box.currentText(),
                    "reason": f"{tool} recommends Gemini, but API is disabled. Using local model."
                }

            if tool_provider == "anthropic" and not self.allow_anthropic_checkbox.isChecked():
                return {
                    "mode": "Local only",
                    "provider": "ollama",
                    "model": self.model_box.currentText(),
                    "reason": f"{tool} recommends Anthropic, but API is disabled. Using local model."
                }

            # ===== VALID CASE =====
            mode = "Local only" if tool_provider == "ollama" else "Hybrid allowed"

            return {
                "mode": mode,
                "provider": tool_provider,
                "model": model,
                "reason": f"{tool} tool recommends {tool_provider} for best results."
            }

        text = f"{agent} {tool} {command} {prompt}".lower()



        if any(k in text for k in ["debug", "error", "traceback", "python", "code", "refactor", "function", "class"]):
            if self.allow_anthropic_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "anthropic", "model": "claude-sonnet-4-6", "reason": "Coding/debugging task; Claude Sonnet is excellent for code analysis and generation."}
            if self.allow_kimi_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "kimi", "model": "kimi-k2.7-code", "reason": "Coding/debugging task; Kimi K2.7 Code is purpose-built for coding and long-context tool use."}
            if self.allow_deepseek_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "deepseek", "model": "deepseek-chat", "reason": "Coding/debugging task; DeepSeek is strong for code analysis."}
            if self.allow_openai_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "openai", "model": "gpt-4o-mini", "reason": "Coding/debugging task; OpenAI is reliable for code assistance."}
            return {"mode": "Local only", "provider": "ollama", "model": self.model_box.currentText(), "reason": "Coding task detected, but APIs are not enabled. Using local model."}

        if any(k in text for k in ["write", "rewrite", "email", "cv", "cover letter", "professional", "polish"]):
            if self.allow_anthropic_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "anthropic", "model": "claude-sonnet-4-6", "reason": "Writing task; Claude is highly recommended for polished professional text."}
            if self.allow_openai_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "openai", "model": "gpt-4o-mini", "reason": "Writing task; OpenAI is recommended for polished professional text."}
            if self.allow_gemini_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "gemini", "model": "gemini-1.5-flash", "reason": "Writing task; Gemini is a good API fallback."}
            return {"mode": "Local only", "provider": "ollama", "model": self.model_box.currentText(), "reason": "Writing task detected, but APIs are not enabled. Using local model."}

        if any(k in text for k in ["osint", "investigate", "research", "summarize sources", "analysis", "report"]):
            if self.allow_kimi_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "kimi", "model": "kimi-k2.7-code", "reason": "Analysis/OSINT-style task; Kimi's strong tool-use/agentic performance suits multi-step investigation."}
            if self.allow_deepseek_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "deepseek", "model": "deepseek-chat", "reason": "Analysis/OSINT-style task; DeepSeek is recommended."}
            if self.allow_gemini_checkbox.isChecked():
                return {"mode": "Hybrid allowed", "provider": "gemini", "model": "gemini-1.5-flash", "reason": "Analysis task; Gemini is suitable for broad summarization."}
            return {"mode": "Local only", "provider": "ollama", "model": self.model_box.currentText(), "reason": "Analysis task detected, but APIs are not enabled. Using local model."}

        return {
            "mode": "Local only",
            "provider": "ollama",
            "model": self.model_box.currentText(),
            "reason": "General/simple task. Local Ollama is free and private."
        }

    def apply_recommended_setup(self):
        self._applying_recommendation = True
        rec = self.get_recommended_setup()

        if hasattr(self, "execution_mode_box"):
            index = self.execution_mode_box.findText(rec["mode"])
            if index >= 0:
                self.execution_mode_box.setCurrentIndex(index)

        if hasattr(self, "provider_box"):
            index = self.provider_box.findText(rec["provider"])
            if index >= 0:
                self.provider_box.setCurrentIndex(index)

        self.load_provider_models()

        if hasattr(self, "model_box") and rec["model"] != "tts":
            index = self.model_box.findText(rec["model"])
            if index >= 0:
                self.model_box.setCurrentIndex(index)

        if hasattr(self, "recommendation_label"):
            self.recommendation_label.setText(
                f"Recommendation:\n"
                f"{rec['provider']} · {rec['model']}\n"
                f"{rec['reason']}"
            )

        self.update_live_cost_estimate()
        self._applying_recommendation = False

    def update_recommendation_label(self):
        if not hasattr(self, "recommendation_label"):
            return

        rec = self.get_recommended_setup()

        self.recommendation_label.setText(f"{rec['provider']} · {rec['model']}")
        if hasattr(self, "routing_rows"):
            self.routing_rows["Suggested"].set(rec["provider"], rec["reason"])
            self.routing_rows["Model"].set(rec["model"], rec["reason"])
            self.routing_rows["Mode"].set(rec.get("mode", "—"), rec["reason"])
        # Chat's recommendation moves with the tool/command/prompt, so repaint
        # the red dropdown markings whenever the label is refreshed.
        self.refresh_recommendation_marks("chat")

    def maybe_auto_apply_recommendation(self):
        if not hasattr(self, "auto_recommend_checkbox"):
            return

        if not self.auto_recommend_checkbox.isChecked():
            return

        if getattr(self, "_applying_recommendation", False):
            return
        if time.monotonic() < getattr(self, "_manual_selection_until", 0):
            return
        if not hasattr(self, "_recommendation_timer"):
            self._recommendation_timer = QTimer(self)
            self._recommendation_timer.setSingleShot(True)
            self._recommendation_timer.timeout.connect(self.apply_recommended_setup)
        self._recommendation_timer.start(350)

    def note_manual_model_selection(self, *_args) -> None:
        if not getattr(self, "_applying_recommendation", False):
            self._manual_selection_until = time.monotonic() + 5.0

    # ── Muse Glimmer (local, via Ollama) ─────────────────────────────────────

    def _set_chat_status(self, text: str) -> None:
        """Write to the chat status line, revealing it if it is still hidden."""
        label = getattr(self, "chat_status_label", None)
        if label is None:
            return
        label.setText(text)
        label.setVisible(bool(text))

    @staticmethod
    def _total_ram_gb() -> int:
        import psutil
        return round(psutil.virtual_memory().total / 1e9)

    def _muse_choice(self) -> tuple[str, int]:
        """The Muse Glimmer build best suited to this machine: (tag, size_gb)."""
        return muse_glimmer_default(self._total_ram_gb())

    def mark_oversized_models(self, combo) -> None:
        """Grey out local models this machine cannot physically run.

        Advisory only — the entry stays selectable, and run_backend() is the
        real gate. Colouring here just makes the limit visible before clicking.
        """
        if combo is None:
            return

        for i in range(combo.count()):
            # Never overwrite the red recommendation marking.
            if combo.itemData(i, Qt.ForegroundRole) is not None:
                continue
            verdict = self.assess_local_model(combo.itemText(i))
            if verdict is None:
                continue
            if verdict["level"] == "too_big":
                combo.setItemData(i, QColor("#666666"), Qt.ForegroundRole)
                combo.setItemData(i, f"⚠ {verdict['message']}", Qt.ToolTipRole)
            elif verdict["level"] == "tight":
                combo.setItemData(i, f"⚠ {verdict['message']}", Qt.ToolTipRole)

    def refresh_muse_button(self) -> None:
        """Show the pull button only while Muse Glimmer is not installed."""
        btn = getattr(self, "get_muse_btn", None)
        if btn is None:
            return

        # Installed at all? Any of the published builds counts.
        installed = any(
            self.ollama.is_model_installed(tag) for tag in MUSE_GLIMMER_VARIANTS
        )
        tag, size_gb = self._muse_choice()

        btn.setVisible(not installed)
        btn.setToolTip(
            f"Download Meta's Muse Glimmer ({tag}) into Ollama — ~{size_gb} GB. "
            "A 30B open-weights agentic model tuned for tool use, long tasks and "
            "failure recovery. Runs locally, so it is free and nothing leaves "
            "this machine."
        )

    def pull_muse_glimmer(self) -> None:
        if getattr(self, "muse_pull_worker", None) is not None and self.muse_pull_worker.isRunning():
            QMessageBox.information(self, "Already Downloading", "Muse Glimmer is already downloading.")
            return

        tag, size_gb = self._muse_choice()
        total_ram_gb = self._total_ram_gb()

        ram_note = ""
        if total_ram_gb and total_ram_gb < size_gb + 8:
            ram_note = (
                f"\n\n⚠ This machine has {total_ram_gb} GB of memory and the model needs "
                f"about {size_gb} GB resident. Expect heavy swapping and slow responses — "
                "Meta targets a 24–32 GB envelope. Close other apps before running it."
            )

        confirm = QMessageBox.question(
            self,
            "Download Muse Glimmer?",
            f"This downloads {tag} (~{size_gb} GB) into Ollama.\n\n"
            "Meta's 30B open-weights agentic model (Apache 2.0), tuned for tool use, "
            "long-running tasks and failure recovery. It runs locally — free, and no "
            f"data leaves this machine.{ram_note}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.get_muse_btn.setEnabled(False)
        self.muse_pull_worker = ModelPullWorker(self.ollama, tag)
        self.muse_pull_worker.progress_signal.connect(self._on_muse_pull_progress)
        self.muse_pull_worker.finished_signal.connect(self._on_muse_pull_finished)
        self.muse_pull_worker.error_signal.connect(self._on_muse_pull_error)
        self.muse_pull_worker.start()

    def _on_muse_pull_progress(self, status: str, done: int, total: int) -> None:
        if total > 0:
            pct = int(done / total * 100)
            self._set_chat_status(
                f"Muse Glimmer: {status} — {done / 1e9:.1f} / {total / 1e9:.1f} GB ({pct}%)"
            )
            self.tool_progress.setValue(pct)
        else:
            self._set_chat_status(f"Muse Glimmer: {status}")

    def _on_muse_pull_finished(self, model: str) -> None:
        self.tool_progress.setValue(100)
        self._set_chat_status(f"Muse Glimmer installed ({model}).")
        self.get_muse_btn.setEnabled(True)
        self.refresh_muse_button()
        # Bring it into the dropdown straight away if Ollama is the live provider.
        if self.provider_box.currentText() == "ollama":
            self.load_provider_models()
        QMessageBox.information(
            self,
            "Muse Glimmer Ready",
            f"{model} is installed.\n\nSelect provider 'ollama' and pick it from the "
            "Model list. It runs locally at no cost.",
        )

    def _on_muse_pull_error(self, message: str) -> None:
        self.tool_progress.setValue(0)
        self._set_chat_status("Muse Glimmer download failed.")
        self.get_muse_btn.setEnabled(True)
        QMessageBox.warning(self, "Download Failed", message)

    def models_for_provider(self, provider: str, context: str = "",
                            widget=None) -> list[str]:
        """Model ids offered by one provider, or [] for an unknown provider.

        Every client falls back to its own KNOWN_MODELS list when the API is
        unreachable, so this only returns empty for a name we don't handle.

        A `context` turns a failure from silent into recorded: the panels that
        loaded their own models used to note it on the model box as a tooltip,
        and that survives the move here.
        """
        clients = {
            "ollama": self.ollama,
            "openai": self.openai,
            "deepseek": self.deepseek,
            "kimi": self.kimi,
            "gemini": self.gemini,
            "anthropic": self.anthropic,
            "qwen": self.qwen,
        }
        client = clients.get(provider)
        if client is None:
            return []
        try:
            return list(client.list_models())
        except Exception as exc:
            if context:
                self._note_failure(f"{context}: load models", exc, widget)
            return []

    # ── The provider/model pair every agent panel owns ───────────────────────
    # One implementation, six panels. Each used to inline the same seven-branch
    # provider chain; two of them swallowed load failures silently and one
    # reported them, which is the kind of drift that duplication guarantees.

    def load_models_into(self, provider_box, model_box, context: str,
                         empty_placeholder: bool = False) -> None:
        """Fill `model_box` with the models of the provider next to it."""
        provider = provider_box.currentText()
        model_box.clear()
        models = self.models_for_provider(provider, context, model_box)
        if models:
            model_box.addItems(models)
            self.decorate_model_costs(provider, model_box)
        elif empty_placeholder:
            model_box.addItem(
                "(no local models)" if provider == "ollama" else "(unavailable)"
            )

    def decorate_model_costs(self, provider: str, model_box) -> None:
        """Attach cost-aware tooltips while preserving exact API model ids."""
        for index in range(model_box.count()):
            quote = self.usage_tracker.get_price_quote(provider, model_box.itemText(index))
            details = quote.label
            if quote.available and quote.verified_at:
                details += f" · verified {quote.verified_at}"
            if quote.region:
                details += f" · {quote.region}"
            if not quote.available and quote.reason:
                details += f" — {quote.reason}"
            model_box.setItemData(index, details, Qt.ToolTipRole)

    def setup_widgets_for(self, agent_key: str):
        """One agent's provider and model boxes, wherever they now live.

        A panel that has moved to `ui/panels/` owns its own combos; one that has
        not is still a pile of `GodAI` attributes named in `AGENT_SETUP_WIDGETS`.
        Everything that marks or pre-selects a recommendation asks here, so the
        two can coexist for as long as phase 4 takes.
        """
        panel = self.panels.get(agent_key)
        if panel is not None:
            return panel.provider_box, panel.model_box

        names = AGENT_SETUP_WIDGETS.get(agent_key)
        if not names:
            return None, None
        return getattr(self, names[0], None), getattr(self, names[1], None)

    def register_model_loader(self, agent_key: str, loader) -> None:
        """Record how to repopulate one agent's model box.

        Panels register while they build. Replaces a map of method *names* that
        had to be kept in step with the methods by hand.
        """
        self._model_loaders[agent_key] = loader

    def load_models_for(self, agent_key: str) -> None:
        """Repopulate one agent's model box, whichever panel owns it."""
        loader = self._model_loaders.get(agent_key)
        if loader is None:
            return
        try:
            loader()
        except Exception as exc:
            self._note_failure(f"{agent_key}: reload models", exc)

    # ── Per-agent recommended setup ──────────────────────────────────────────
    # Every agent panel gets its recommendation from AGENT_RECOMMENDATIONS
    # pre-selected on startup, and the recommended provider/model entries are
    # painted red inside their dropdowns. The red entry survives the user
    # switching to something else, so the original recommendation stays visible
    # for the whole session.

    @staticmethod
    def _find_model_index(combo, wanted: str) -> int:
        """Locate `wanted` in a model combo, tolerating dated API model ids.

        Providers return ids like "claude-sonnet-4-6-20260112" from the live API
        but bare names like "claude-sonnet-4-6" from the offline fallback list,
        so an exact match alone would silently miss. Tries exact, then prefix,
        then substring, and returns -1 when nothing matches.
        """
        if not wanted:
            return -1

        exact = combo.findText(wanted)
        if exact >= 0:
            return exact

        lowered = wanted.lower()
        for i in range(combo.count()):
            if combo.itemText(i).lower().startswith(lowered):
                return i
        for i in range(combo.count()):
            if lowered in combo.itemText(i).lower():
                return i
        return -1

    def _paint_recommended_item(self, combo, index: int, tooltip: str) -> None:
        """Colour one dropdown entry red + bold and clear any previous marking.

        Only the item's colour and tooltip change — never its text — because the
        panels read `currentText()` straight back as the provider/model name.
        """
        if combo is None:
            return

        # The stock combo popup ignores per-item colour under some styles; an
        # explicit QStyledItemDelegate makes ForegroundRole/FontRole take effect.
        if not combo.property("_rec_delegate"):
            from PySide6.QtWidgets import QStyledItemDelegate
            combo.setItemDelegate(QStyledItemDelegate(combo))
            combo.setProperty("_rec_delegate", True)

        default_font = combo.font()
        for i in range(combo.count()):
            combo.setItemData(i, None, Qt.ForegroundRole)
            combo.setItemData(i, default_font, Qt.FontRole)
            combo.setItemData(i, "", Qt.ToolTipRole)

        if index < 0:
            return

        marked_font = QFont(default_font)
        marked_font.setBold(True)
        combo.setItemData(index, QColor(RECOMMENDED_COLOR), Qt.ForegroundRole)
        combo.setItemData(index, marked_font, Qt.FontRole)
        combo.setItemData(index, tooltip, Qt.ToolTipRole)

    def _mark_deviation(self, combo, is_recommended: bool) -> None:
        """Tint a combo's border red while it holds a non-recommended value.

        The red dropdown entry is only visible once the list is open; this makes
        the deviation legible at a glance with the panel closed. The focus rule
        is repeated here because a widget-level stylesheet outranks the global
        one and would otherwise drop the green focus ring.
        """
        if combo is None:
            return

        if is_recommended:
            combo.setStyleSheet("")
        else:
            combo.setStyleSheet(
                f"QComboBox {{ border: 1px solid {RECOMMENDED_COLOR}; }}"
                "QComboBox:focus { border: 1px solid #3cff88; }"
            )

    def _recommendation_for(self, agent_key: str) -> dict | None:
        """Return {provider, model, reason} for an agent.

        Chat is the one agent whose recommendation is not fixed — it already has
        a live recommender that reacts to the selected tool, command and prompt
        text — so defer to that and let the red marking follow it around.
        """
        if agent_key == "chat":
            try:
                rec = self.get_recommended_setup()
            except Exception:
                return None
            return rec if rec.get("model") != "tts" else None

        return AGENT_RECOMMENDATIONS.get(agent_key)

    def refresh_recommendation_marks(self, agent_key: str) -> None:
        """Re-apply the red marking for one agent's provider and model boxes.

        Called after any model-list reload, since clearing a combo also drops the
        per-item colour data.
        """
        rec = self._recommendation_for(agent_key)
        if not rec:
            return

        provider_box, model_box = self.setup_widgets_for(agent_key)
        pretty = AGENT_PRETTY_NAMES.get(agent_key, agent_key)
        tooltip = (
            f"Recommended for {pretty}: {rec['provider']} · {rec['model']}\n"
            f"{rec['reason']}"
        )

        if provider_box is not None:
            idx = provider_box.findText(rec["provider"])
            self._paint_recommended_item(provider_box, idx, tooltip)
            provider_box.setToolTip(tooltip)
            self._mark_deviation(
                provider_box, provider_box.currentText() == rec["provider"]
            )

        if model_box is not None:
            idx = self._find_model_index(model_box, rec["model"])
            self._paint_recommended_item(model_box, idx, tooltip)
            model_box.setToolTip(tooltip)
            self._mark_deviation(
                model_box, idx >= 0 and model_box.currentIndex() == idx
            )
            # After the red marking, since _paint_recommended_item resets every
            # item's colour and would otherwise wipe the grey.
            self.mark_oversized_models(model_box)

    def _on_recommended_provider_changed(self, agent_key: str) -> None:
        """React to the user switching provider on an agent panel.

        Whenever the provider lands back on the recommended one, snap the model
        box to the recommended model too — otherwise the panel's loader leaves
        it on whatever happens to be first in the list. A deliberate model change
        afterwards is left alone.
        """
        rec = self._recommendation_for(agent_key)
        if rec:
            provider_box, model_box = self.setup_widgets_for(agent_key)
            if (provider_box is not None and model_box is not None
                    and provider_box.currentText() == rec["provider"]):
                idx = self._find_model_index(model_box, rec["model"])
                if idx >= 0:
                    model_box.setCurrentIndex(idx)

        self.refresh_recommendation_marks(agent_key)

    def apply_agent_recommendation(self, agent_key: str) -> None:
        """Pre-select this agent's recommended provider + model, then mark them."""
        if agent_key == "chat":
            # Chat has its own apply path that also updates the recommendation
            # panel and the live cost estimate.
            self.apply_recommended_setup()
            self.refresh_recommendation_marks("chat")
            return

        rec = AGENT_RECOMMENDATIONS.get(agent_key)
        if not rec:
            return

        provider_box, model_box = self.setup_widgets_for(agent_key)

        if provider_box is not None:
            idx = provider_box.findText(rec["provider"])
            if idx >= 0:
                provider_box.setCurrentIndex(idx)

        # Populate the model list for the provider we just selected. Setting the
        # provider fires currentTextChanged -> the panel's loader, but only when
        # the value actually changed, so call the loader directly to cover the
        # case where the recommended provider was already selected.
        self.load_models_for(agent_key)

        if model_box is not None:
            idx = self._find_model_index(model_box, rec["model"])
            if idx >= 0:
                model_box.setCurrentIndex(idx)

        self.refresh_recommendation_marks(agent_key)

    def install_agent_recommendations(self) -> None:
        """Apply every agent's recommended setup once, at startup, and keep the
        red markings in sync as the user changes providers or models later."""

        for agent_key in AGENT_SETUP_WIDGETS:
            provider_box, model_box = self.setup_widgets_for(agent_key)

            try:
                self.apply_agent_recommendation(agent_key)
            except Exception as e:
                print(f"[Recommendations] {agent_key}: {e}")

            # Re-mark after the panel's own loader has repopulated the model box.
            # Connected last, so it runs after the loader already wired up above.
            if provider_box is not None:
                provider_box.currentTextChanged.connect(
                    lambda _t, k=agent_key: self._on_recommended_provider_changed(k)
                )
            if model_box is not None:
                model_box.currentTextChanged.connect(
                    lambda _t, k=agent_key: self.refresh_recommendation_marks(k)
                )

    def build_ui(self):
        outer_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_widget = self.build_left_panel()
        center_widget = self.build_center_panel()
        right_widget = self.build_right_panel()
        self.update_recommendation_label()

        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([230, 870, 300])

        outer_layout.addWidget(splitter)
        self.apply_global_style()

    def build_left_panel(self) -> QWidget:
        left_widget = QWidget()
        left_widget.setObjectName("LeftPanel")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(4)

        fork_brand = QLabel("Sentinel Fork")
        fork_brand.setStyleSheet(
            "color: #3cff88; font-size: 15px; font-weight: 600; "
            "padding: 8px 4px 12px 4px;"
        )
        fork_brand.setToolTip("Independent fork of Sentinel v2")
        left_layout.addWidget(fork_brand)

        # Inner scrollable container holds all the agent categories so they never
        # get clipped or vertically squashed when the window is short.
        agents_header = QLabel("AGENTS")
        agents_header.setObjectName("RailHeading")
        left_layout.addWidget(agents_header)

        agents_scroll = QScrollArea()
        agents_scroll.setWidgetResizable(True)
        agents_scroll.setFrameShape(QFrame.NoFrame)
        agents_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        agents_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        agents_container = QWidget()
        agents_container.setStyleSheet("background: transparent;")
        agents_layout = QVBoxLayout(agents_container)
        agents_layout.setContentsMargins(0, 0, 0, 0)
        agents_layout.setSpacing(2)

        icons = {
            "chat": "▸", "osint": "◈", "osint_heavy": "◉",
            "manager": "✦",
            "wifi": "≋", "bug_bounty": "⌁", "vpn": "⇄", }
        labels = {
            "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
            "manager": "Forge",
            "wifi": "Beacon",
            "bug_bounty": "Bug Spray",
            "vpn": "Tunnel",
            # Without this the sidebar fell back to name.capitalize() and showed a
            # other surface (header title, registry) calls this one Publisher.
            }

        # Every section starts collapsed — launch shows just the category list,
        # and you open the one you want.
        # A flat list, in the order the work usually runs. The accordion this
        # replaced was built when there were fifteen agents; at six it was a
        # click between you and everything, and four headings for six rows.
        sidebar_agents = ["chat", "osint", "osint_heavy", "wifi", "bug_bounty", "vpn", "manager"]

        # Minimal sidebar row — clear separation via padding + hover fill
        agent_btn_style = """
            QPushButton#AgentBtn {
                text-align: left;
                padding: 14px 12px 14px 20px;
                background-color: transparent;
                border: none;
                border-left: 3px solid transparent;
                border-radius: 0;
                color: #a8b3ad;
                font-size: 16px;
                font-weight: normal;
            }
            QPushButton#AgentBtn:hover {
                background-color: #151816;
                color: #e8ece9;
            }
            QPushButton#AgentBtn:checked {
                background-color: rgba(60, 255, 136, 0.07);
                border-left: 3px solid #3cff88;
                color: #3cff88;
                font-weight: 500;
            }
        """

        self.agent_buttons = {}
        for name in sidebar_agents:
            btn = QPushButton(f"{icons.get(name, '⚙️')}  {labels.get(name, name.capitalize())}")
            btn.setObjectName("AgentBtn")
            btn.setStyleSheet(agent_btn_style)
            btn.setCheckable(True)
            btn.setMinimumHeight(40)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked, n=name: self.select_agent(n))
            agents_layout.addWidget(btn)
            self.agent_buttons[name] = btn

        agents_layout.addStretch()
        agents_scroll.setWidget(agents_container)
        left_layout.addWidget(agents_scroll, 1)

        # ── Divider ──────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #242424; background-color: #242424; max-height: 1px;")
        left_layout.addWidget(divider)

        saved_header = QLabel("Saved chats")
        saved_header.setStyleSheet(
            "color: #909090; font-weight: 600; font-size: 12px; "
            "padding: 8px 0 4px 4px; "
            "background: transparent;"
        )
        left_layout.addWidget(saved_header)

        self.project_filter = QComboBox()
        self.project_filter.currentIndexChanged.connect(self.project_changed)
        self.project_filter.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_filter.customContextMenuRequested.connect(self.show_project_context_menu)
        left_layout.addWidget(self.project_filter)

        history_tools = QHBoxLayout()
        history_tools.setSpacing(8)
        # Narrow the list to one agent. Populated from the chats that exist, so
        # it only ever offers agents you have actually used.
        self.history_agent_filter = QComboBox()
        self.history_agent_filter.addItem(ALL_AGENTS_FILTER)
        self.history_agent_filter.currentTextChanged.connect(self.load_history_list)
        history_tools.addWidget(self.history_agent_filter, 1)

        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search…")
        self.history_search.textChanged.connect(self.load_history_list)
        history_tools.addWidget(self.history_search, 2)
        left_layout.addLayout(history_tools)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.open_selected_chat)
        # Double-click renames: chat_title_from_data already prefers a stored
        # "title" over the truncated first prompt, it was just never written.
        self.history_list.itemDoubleClicked.connect(self.rename_selected_chat)
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        # Keep the saved-chats list bounded so the agents area always has room
        self.history_list.setMinimumHeight(120)
        self.history_list.setMaximumHeight(200)
        left_layout.addWidget(self.history_list)

        self.delete_chat_btn = QPushButton("Delete selected")
        self.delete_chat_btn.clicked.connect(self.delete_selected_chat)

        self.new_chat_btn = QPushButton("New chat")
        self.new_chat_btn.clicked.connect(self.new_chat)
        history_actions = QHBoxLayout()
        history_actions.setSpacing(8)
        history_actions.addWidget(self.new_chat_btn)
        history_actions.addWidget(self.delete_chat_btn)
        left_layout.addLayout(history_actions)

        left_widget.setMinimumWidth(230)
        left_widget.setMaximumWidth(300)

        left_widget.setStyleSheet("""
        QWidget#LeftPanel {
            background-color: #0f0f0f;
        }
        QWidget#LeftPanel QLineEdit {
            font-size: 12px;
            color: #ffffff;
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 8px;
            padding: 6px 10px;
        }
        QWidget#LeftPanel QLineEdit:focus {
            border: 1px solid #3cff88;
        }
        QWidget#LeftPanel QListWidget {
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 8px;
            font-size: 12px;
            color: #c8c8c8;
            padding: 4px;
        }
        QWidget#LeftPanel QListWidget::item {
            padding: 5px 8px;
            border-radius: 4px;
        }
        QWidget#LeftPanel QListWidget::item:hover {
            background-color: #1f1f1f;
        }
        QWidget#LeftPanel QListWidget::item:selected {
            background-color: rgba(60, 255, 136, 0.10);
            color: #3cff88;
        }
        QWidget#LeftPanel > QPushButton {
            font-size: 12px;
            font-weight: 600;
            color: #d0d0d0;
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 8px;
            padding: 8px 12px;
            margin-top: 6px;
        }
        QWidget#LeftPanel > QPushButton:hover {
            background-color: #1f1f1f;
            border: 1px solid #3cff88;
            color: #ffffff;
        }
        """)

        return left_widget

    def build_center_panel(self) -> QWidget:
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(24, 24, 24, 24)
        center_layout.setSpacing(16)

        # ── Agent header bar: big accent title + status pill ─────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.agent_title_label = QLabel("Chat")
        self.agent_title_label.setObjectName("AgentTitle")
        header_row.addWidget(self.agent_title_label)

        self.agent_subtitle_label = QLabel("")
        self.agent_subtitle_label.setObjectName("AgentSubtitle")
        self.agent_subtitle_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        header_row.addWidget(self.agent_subtitle_label, 0, Qt.AlignBottom)

        header_row.addStretch()

        self.agent_docs_btn = QPushButton("📖  Docs")
        self.agent_docs_btn.setObjectName("ChipBtn")
        self.agent_docs_btn.setToolTip("Open the documentation for the current agent.")
        self.agent_docs_btn.clicked.connect(self.show_agent_docs)
        self.agent_docs_btn.hide()

        self.tooltips_toggle_btn = QPushButton("💡 Tooltips: On")
        self.tooltips_toggle_btn.setObjectName("ChipBtn")
        self.tooltips_toggle_btn.setCheckable(True)
        self.tooltips_toggle_btn.setChecked(True)
        self.tooltips_toggle_btn.setToolTip(
            "Toggle hover tooltips across the entire app. Tooltips explain what each control does."
        )
        self.tooltips_toggle_btn.clicked.connect(self._toggle_tooltips)
        self.tooltips_toggle_btn.hide()

        self.agent_status_pill = QLabel("●  Ready")
        self.agent_status_pill.setObjectName("StatusPill")
        header_row.addWidget(self.agent_status_pill)

        center_layout.addLayout(header_row)


        self.normal_panel = QWidget()
        normal_layout = QVBoxLayout(self.normal_panel)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(10)

        # Row 1: command only
        # ── Run bar ───────────────────────────────────────────────────────────
        # One row instead of three. Everything here changes per request; the
        # things that change weekly — execution mode, the provider permissions,
        # the model tools — moved behind the gear. They were occupying the strip
        # directly above the input box permanently.
        self.agent_box = QComboBox()
        agent_items = self.agents_config.get("agents", [])
        for extra in ("manager",):
            if extra not in agent_items:
                agent_items = list(agent_items) + [extra]
        self.agent_box.addItems(agent_items)
        self.agent_box.hide()

        runbar_container = QWidget()
        runbar_container.setObjectName("RunBar")
        # A plain QWidget does not paint a stylesheet background unless asked;
        # without this the run bar has no surface and its controls float loose.
        runbar_container.setAttribute(Qt.WA_StyledBackground, True)
        runbar = QHBoxLayout(runbar_container)
        runbar.setContentsMargins(16, 16, 16, 16)
        runbar.setSpacing(10)

        self.tool_box = QComboBox()
        self.tool_box.setObjectName("ToolChip")
        self.tool_box.addItems(self.tool_prompts.keys())
        self.tool_box.setMinimumWidth(110)
        runbar.addWidget(self.tool_box)

        self.provider_box = QComboBox()
        self.provider_box.setObjectName("MachinePick")
        self.provider_box.addItems(PROVIDERS)
        self.provider_box.setMinimumWidth(90)
        runbar.addWidget(self.provider_box)

        dot = QLabel("·")
        dot.setObjectName("RunBarDot")
        runbar.addWidget(dot)

        self.model_box = QComboBox()
        self.model_box.setObjectName("MachinePick")
        self.model_box.setMinimumWidth(140)
        runbar.addWidget(self.model_box)

        # The one number that changes with every keystroke, next to the controls
        # that change it rather than in the far rail.
        runbar.addStretch()

        self.runbar_cost = QLabel("—")
        self.runbar_cost.setObjectName("RunBarCost")
        runbar.addWidget(self.runbar_cost)

        self.stop_chat_btn = QPushButton("Stop")
        self.stop_chat_btn.setObjectName("StopAction")
        self.stop_chat_btn.setEnabled(False)
        self.stop_chat_btn.clicked.connect(self.stop_current_task)
        runbar.addWidget(self.stop_chat_btn)

        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("RunAction")
        self.run_btn.clicked.connect(self.send_prompt)
        runbar.addWidget(self.run_btn)

        self.runbar_settings_btn = QPushButton("⚙")
        self.runbar_settings_btn.setObjectName("ChipBtn")
        self.runbar_settings_btn.setToolTip("Execution mode, provider permissions and model tools")
        runbar.addWidget(self.runbar_settings_btn)

        normal_layout.addWidget(runbar_container)

        # Labels other code still addresses, now unused on screen.
        self.tool_label = QLabel("Tool:")
        self.tool_label.hide()
        self.command_label = QLabel("Command:")
        self.command_label.hide()

        # ── Behind the gear ───────────────────────────────────────────────────
        settings_panel = QWidget()
        settings_panel.setObjectName("RunBarPopover")
        settings_panel.setAttribute(Qt.WA_StyledBackground, True)
        sp = QVBoxLayout(settings_panel)
        sp.setContentsMargins(16, 8, 16, 16)
        sp.setSpacing(8)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)
        command_row.addWidget(QLabel("Command"))
        self.command_box = QComboBox()
        self.command_box.addItems(self.commands.keys())
        self.command_box.setMinimumWidth(190)
        command_row.addWidget(self.command_box)
        command_row.addStretch()
        sp.addLayout(command_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("Mode"))
        self.execution_mode_box = QComboBox()
        self.execution_mode_box.addItems(["Local only", "Hybrid allowed", "Cloud only"])
        self.execution_mode_box.setMinimumWidth(150)
        mode_row.addWidget(self.execution_mode_box)
        mode_row.addStretch()
        sp.addLayout(mode_row)

        perms_label = QLabel("ALLOWED PAID PROVIDERS")
        perms_label.setObjectName("PopoverHeading")
        sp.addWidget(perms_label)

        perms_container = QWidget()
        perms = FlowLayout(perms_container, spacing=6)
        self.allow_openai_checkbox = QCheckBox("OpenAI")
        self.allow_deepseek_checkbox = QCheckBox("DeepSeek")
        self.allow_kimi_checkbox = QCheckBox("Kimi")
        self.allow_gemini_checkbox = QCheckBox("Gemini")
        self.allow_anthropic_checkbox = QCheckBox("Anthropic")
        self.allow_qwen_checkbox = QCheckBox("Qwen")
        for box in (self.allow_openai_checkbox, self.allow_deepseek_checkbox,
                    self.allow_kimi_checkbox, self.allow_gemini_checkbox,
                    self.allow_anthropic_checkbox, self.allow_qwen_checkbox):
            box.setChecked(False)
            perms.addWidget(box)
        sp.addWidget(perms_container)

        tools_label = QLabel("MODELS")
        tools_label.setObjectName("PopoverHeading")
        sp.addWidget(tools_label)

        request_label = QLabel("THIS REQUEST")
        request_label.setObjectName("PopoverHeading")
        sp.addWidget(request_label)

        request_container = QWidget()
        request_actions = FlowLayout(request_container, spacing=6)
        self.auto_route_btn = QPushButton("Auto route")
        self.auto_route_btn.setObjectName("ChipBtn")
        self.auto_route_btn.clicked.connect(self.auto_route_agent)
        request_actions.addWidget(self.auto_route_btn)

        self.recommend_setup_btn = QPushButton("Use recommended")
        self.recommend_setup_btn.setObjectName("ChipBtn")
        self.recommend_setup_btn.clicked.connect(self.apply_recommended_setup)
        request_actions.addWidget(self.recommend_setup_btn)

        self.auto_recommend_checkbox = QCheckBox("Auto-apply")
        self.auto_recommend_checkbox.setChecked(False)
        request_actions.addWidget(self.auto_recommend_checkbox)

        self.estimate_btn = QPushButton("Estimate cost")
        self.estimate_btn.setObjectName("ChipBtn")
        self.estimate_btn.clicked.connect(self.show_cost_estimate_popup)
        request_actions.addWidget(self.estimate_btn)

        self.export_btn = QPushButton("Export report")
        self.export_btn.setObjectName("ChipBtn")
        self.export_btn.clicked.connect(self.export_report)
        request_actions.addWidget(self.export_btn)
        sp.addWidget(request_container)

        tools_container = QWidget()
        tools = FlowLayout(tools_container, spacing=6)
        self.refresh_models_btn = QPushButton("Refresh models")
        self.refresh_models_btn.setObjectName("ChipBtn")
        self.refresh_models_btn.clicked.connect(self.load_provider_models)
        tools.addWidget(self.refresh_models_btn)

        # Hidden once Muse Glimmer is installed — it is then just another entry
        # in the model box.
        self.get_muse_btn = QPushButton("⬇ Get Muse Glimmer")
        self.get_muse_btn.setObjectName("ChipBtn")
        self.get_muse_btn.clicked.connect(self.pull_muse_glimmer)
        tools.addWidget(self.get_muse_btn)

        self.model_guide_btn = QPushButton("Model guide")
        self.model_guide_btn.setObjectName("ChipBtn")
        self.model_guide_btn.clicked.connect(self.show_model_guide)
        tools.addWidget(self.model_guide_btn)

        self.docs_btn = QPushButton("Docs")
        self.docs_btn.setObjectName("ChipBtn")
        self.docs_btn.clicked.connect(self.show_docs)
        tools.addWidget(self.docs_btn)
        sp.addWidget(tools_container)

        self.runbar_menu = QMenu(self)
        action = QWidgetAction(self.runbar_menu)
        action.setDefaultWidget(settings_panel)
        self.runbar_menu.addAction(action)
        self.runbar_settings_btn.setMenu(self.runbar_menu)

        self.model_box.currentTextChanged.connect(self.save_provider_model_preference)
        self.model_box.activated.connect(self.note_manual_model_selection)
        self.provider_box.activated.connect(self.note_manual_model_selection)

        self.input_box = QTextEdit()
        self.input_box.setObjectName("PromptInput")
        self.input_box.setPlaceholderText("Type your message here…")
        self.input_box.setMinimumHeight(110)
        self.input_box.setMaximumHeight(170)
        normal_layout.addWidget(self.input_box)

        self.send_btn = self.run_btn

        # ===== INPUT =====
        self.input_box.textChanged.connect(self.update_live_cost_estimate)
        self.input_box.textChanged.connect(self.update_recommendation_label)
        self.input_box.textChanged.connect(self.maybe_auto_apply_recommendation)

        # ===== TOOL / COMMAND =====
        self.command_box.currentTextChanged.connect(self.update_live_cost_estimate)
        self.command_box.currentTextChanged.connect(self.update_recommendation_label)

        self.tool_box.currentTextChanged.connect(self.update_live_cost_estimate)
        self.tool_box.currentTextChanged.connect(self.update_recommendation_label)

        # ===== PROVIDER =====
        # Chat keeps its own loader — it remembers a per-provider default model
        # and falls back to hand-written lists per API — but registers it like
        # any other panel so the recommendation system has one way in.
        self.register_model_loader("chat", self.load_provider_models)
        self.provider_box.currentTextChanged.connect(self.load_provider_models)
        self.provider_box.currentTextChanged.connect(self.update_live_cost_estimate)
        self.provider_box.currentTextChanged.connect(self.update_recommendation_label)

        # ===== MODEL =====
        self.model_box.currentTextChanged.connect(self.update_live_cost_estimate)

        # ===== MODE =====
        self.execution_mode_box.currentTextChanged.connect(self.update_live_cost_estimate)
        self.execution_mode_box.currentTextChanged.connect(self.update_recommendation_label)

        # ===== API CHECKBOXES =====
        self.allow_openai_checkbox.stateChanged.connect(self.update_live_cost_estimate)
        self.allow_openai_checkbox.stateChanged.connect(self.update_recommendation_label)

        self.allow_deepseek_checkbox.stateChanged.connect(self.update_live_cost_estimate)
        self.allow_deepseek_checkbox.stateChanged.connect(self.update_recommendation_label)

        self.allow_kimi_checkbox.stateChanged.connect(self.update_live_cost_estimate)
        self.allow_kimi_checkbox.stateChanged.connect(self.update_recommendation_label)

        self.allow_gemini_checkbox.stateChanged.connect(self.update_live_cost_estimate)
        self.allow_gemini_checkbox.stateChanged.connect(self.update_recommendation_label)

        self.allow_anthropic_checkbox.stateChanged.connect(self.update_live_cost_estimate)
        self.allow_anthropic_checkbox.stateChanged.connect(self.update_recommendation_label)

        self.chat_progress = QProgressBar()
        self.chat_progress.setMinimum(0)
        self.chat_progress.setMaximum(0)
        self.chat_progress.hide()
        normal_layout.addWidget(self.chat_progress)

        self.chat_status_label = QLabel("")
        self.chat_status_label.hide()
        normal_layout.addWidget(self.chat_status_label)

        center_layout.addWidget(self.normal_panel)

        self.manager_panel = self.panels["manager"] = ManagerPanel(self)
        center_layout.addWidget(self.manager_panel)

        self.osint_panel = self.panels["osint"] = OsintPanel(self)
        center_layout.addWidget(self.osint_panel)

        self.osint_heavy_panel = self.panels["osint_heavy"] = OsintHeavyPanel(self)
        center_layout.addWidget(self.osint_heavy_panel)

        self.wifi_panel = self.panels["wifi"] = WifiPanel(self)
        center_layout.addWidget(self.wifi_panel)

        self.bug_bounty_panel = self.panels["bug_bounty"] = BugBountyPanel(self)
        center_layout.addWidget(self.bug_bounty_panel)

        self.vpn_panel = self.panels["vpn"] = VpnPanel(self)
        center_layout.addWidget(self.vpn_panel)

        self.output_label = QLabel("OUTPUT")
        self.output_label.setStyleSheet(
            "font-size: 10px; font-weight: bold; color: #707070; "
            "letter-spacing: 1.5px; padding: 6px 0 2px 0; background: transparent;"
        )
        self.output_label.hide()
        center_layout.addWidget(self.output_label)

        self.output_box = QTextEdit()
        self.output_box.setObjectName("OutputBox")
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(130)
        self.output_box.hide()
        center_layout.addWidget(self.output_box, 1)

        self.load_provider_models()

        return center_widget

    def show_output_area(self):
        """Reveal the output label and box. Called when content arrives."""
        if hasattr(self, "output_label") and hasattr(self, "output_box"):
            self.output_label.setVisible(True)
            self.output_box.setVisible(True)

    def hide_output_area(self):
        """Hide the output label and box (e.g. after New Chat clears state)."""
        if hasattr(self, "output_label") and hasattr(self, "output_box"):
            self.output_label.setVisible(False)
            self.output_box.setVisible(False)
    
    def build_right_panel(self) -> QWidget:
        right_widget = QWidget()
        right_widget.setObjectName("RightPanel")

        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(0)

        # ── Inner container that holds all cards (scrollable) ───────────
        cards_container = QWidget()
        cards_container.setObjectName("RightCardsContainer")
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(4, 4, 4, 4)
        cards_layout.setSpacing(8)

        # ── Card 1: System ──────────────────────────────────────────────
        system_card = QGroupBox("SYSTEM")
        system_card.setObjectName("RightCard")
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(8, 8, 8, 8)
        system_layout.setSpacing(6)

        # Figures, not sentences: every one of these is "x of y", so it is drawn
        # as a proportion. "Used: 11.3 GB · Free: 9.4 GB" cannot be read at a
        # glance, and reading at a glance is the whole job of a status rail.
        self.resource_meters = {
            "RAM": Meter("RAM", "Physical memory in use"),
            "CPU": Meter("CPU", "Processor load across all cores"),
            "SWAP": Meter("SWAP", "Memory paged out to disk. Sustained high swap "
                                  "means real pressure; a large idle figure is "
                                  "usually just accumulated history."),
            "BATT": Meter("BATT", "Charge remaining"),
        }
        for meter in self.resource_meters.values():
            system_layout.addWidget(meter)

        self.realtime_monitor_btn = QPushButton("Realtime monitor")
        self.realtime_monitor_btn.setEnabled(False)
        system_layout.addWidget(self.realtime_monitor_btn)

        cards_layout.addWidget(system_card)

        # ── Card 2: Routing & Recommendation ────────────────────────────
        routing_card = QGroupBox("ROUTING")
        routing_card.setObjectName("RightCard")
        routing_layout = QVBoxLayout(routing_card)
        routing_layout.setContentsMargins(8, 8, 8, 8)
        routing_layout.setSpacing(6)

        # Rows, not prose. The reasoning sentence became the tooltip — it is
        # an explanation you want occasionally, not four wrapped lines you read
        # past every time.
        self.routing_rows = {
            "Suggested": KeyValue("Suggested", "—"),
            "Model": KeyValue("Model", "—"),
            "Mode": KeyValue("Mode", "—"),
        }
        for row in self.routing_rows.values():
            routing_layout.addWidget(row)

        # kept so the existing update paths still have something to write to
        self.route_result_label = QLabel()
        self.route_result_label.hide()
        self.recommendation_label = QLabel()
        self.recommendation_label.hide()

        cards_layout.addWidget(routing_card)

        # ── Card 3: Cost ────────────────────────────────────────────────
        cost_card = QGroupBox("COST")
        cost_card.setObjectName("RightCard")
        cost_layout = QVBoxLayout(cost_card)
        cost_layout.setContentsMargins(8, 8, 8, 8)
        cost_layout.setSpacing(6)

        self.cost_rows = {
            "last": KeyValue("Last request", "€0.00"),
            "session": KeyValue("This session", "€0.00"),
            "today": KeyValue("Today", "€0.00"),
            "requests": KeyValue("Requests", "0"),
        }
        for row in self.cost_rows.values():
            cost_layout.addWidget(row)

        # written to by the existing update paths, no longer shown
        self.live_estimate_label = QLabel(); self.live_estimate_label.hide()
        self.last_request_label = QLabel(); self.last_request_label.hide()
        self.session_cost_label = QLabel(); self.session_cost_label.hide()
        self.today_cost_label = QLabel(); self.today_cost_label.hide()
        self.request_count_label = QLabel(); self.request_count_label.hide()

        cards_layout.addWidget(cost_card)

        # ── Card 4: Budget ──────────────────────────────────────────────
        budget_card = QGroupBox("BUDGET")
        budget_card.setObjectName("RightCard")
        budget_layout = QVBoxLayout(budget_card)
        budget_layout.setContentsMargins(8, 8, 8, 8)
        budget_layout.setSpacing(6)

        # Spend is "x of y" too, and the one figure worth seeing without reading.
        self.budget_meters = {
            "SESSION": Meter("SESSION", "Spent this session against the session cap"),
            "DAILY": Meter("DAILY", "Spent today against the daily cap"),
            "PROJECT": Meter("PROJECT", "Spent today against the active project cap"),
        }
        for meter in self.budget_meters.values():
            budget_layout.addWidget(meter)
        self.budget_meters["PROJECT"].hide()

        # The caps themselves are set in Settings. A rail reports state; two
        # text fields and two buttons in it made the busiest block on screen out
        # of something changed once a month.
        self.session_budget_input = QLineEdit(str(int(self.session_budget_eur)))
        self.daily_budget_input = QLineEdit(str(int(self.daily_budget_eur)))
        self.save_budget_btn = QPushButton("Save Limits")
        self.save_budget_btn.clicked.connect(self.save_budget_limits)
        self.reset_session_budget_btn = QPushButton("Reset Session Spend")
        self.reset_session_budget_btn.clicked.connect(self.reset_session_spend)
        for widget in (self.session_budget_input, self.daily_budget_input,
                       self.save_budget_btn, self.reset_session_budget_btn):
            widget.hide()

        self.edit_budget_btn = QPushButton("Edit limits…")
        self.edit_budget_btn.setObjectName("RailLink")
        self.edit_budget_btn.clicked.connect(self.show_settings)
        budget_layout.addWidget(self.edit_budget_btn)

        cards_layout.addWidget(budget_card)

        # ── Card 5: Quick Actions ───────────────────────────────────────
        actions_card = QGroupBox("ACTIONS")
        actions_card.setObjectName("RightCard")
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(6)

        self.cost_history_btn = QPushButton("Cost history")
        self.cost_history_btn.clicked.connect(self.show_cost_history)
        actions_layout.addWidget(self.cost_history_btn)

        self.run_log_btn = QPushButton("Run log")
        self.run_log_btn.clicked.connect(self.show_run_log)
        actions_layout.addWidget(self.run_log_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.show_settings)
        actions_layout.addWidget(self.settings_btn)

        cards_layout.addWidget(actions_card)

        # ── Card 6: API Keys ────────────────────────────────────────────
        keys_card = QGroupBox("API KEYS")
        keys_card.setObjectName("RightCard")
        keys_layout = QVBoxLayout(keys_card)
        keys_layout.setContentsMargins(8, 8, 8, 8)
        keys_layout.setSpacing(4)

        # A tick and a cross in every row is five pieces of punctuation saying
        # what one word says. Present or absent, stated plainly, coloured.
        self.key_rows = {}
        for name, wrapper in (("OpenAI", OpenAIClientWrapper),
                              ("DeepSeek", DeepSeekClientWrapper),
                              ("Kimi", KimiClientWrapper),
                              ("Gemini", GeminiClientWrapper),
                              ("Anthropic", AnthropicClientWrapper)):
            ready = False
            try:
                ready = bool(wrapper.key_available())
            except Exception:
                ready = False
            row = KeyValue(name, "ready" if ready else "no key")
            row.value.setObjectName("KVValueOn" if ready else "KVValueOff")
            row.setToolTip(f"{name} API key {'found' if ready else 'not set'} in .env")
            self.key_rows[name] = row
            keys_layout.addWidget(row)

        # the old labels, still written to by the settings dialog
        self.openai_key_label = QLabel(); self.openai_key_label.hide()
        self.deepseek_key_label = QLabel(); self.deepseek_key_label.hide()
        self.kimi_key_label = QLabel(); self.kimi_key_label.hide()
        self.gemini_key_label = QLabel(); self.gemini_key_label.hide()
        self.anthropic_key_label = QLabel(); self.anthropic_key_label.hide()

        cards_layout.addWidget(keys_card)

        cards_layout.addStretch()

        # ── Scroll area wrapping all cards ──────────────────────────────
        scroll_area = QScrollArea()
        scroll_area.setWidget(cards_container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        right_layout.addWidget(scroll_area)

        right_widget.setMinimumWidth(260)
        right_widget.setMaximumWidth(320)

        # ── Sizing for buttons/inputs ───────────────────────────────────
        for w in [
            self.realtime_monitor_btn,
            self.save_budget_btn,
            self.reset_session_budget_btn,
            self.cost_history_btn,
            self.run_log_btn,
            self.settings_btn,
        ]:
            w.setFixedHeight(30)
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.session_budget_input.setFixedHeight(28)
        self.daily_budget_input.setFixedHeight(28)

        # ── VPN-Agent-inspired card stylesheet ──────────────────────────
        right_widget.setStyleSheet("""
        QWidget#RightPanel {
            background-color: #0d0f0e;
        }
        QWidget#RightCardsContainer {
            background-color: transparent;
        }

        /* Flat sections, not boxes: a hairline, a small heading, then rows.
           A rail is reference material — boxing each group makes six competing
           containers out of what should read as one column. */
        QGroupBox#RightCard {
            background: transparent;
            border: none;
            border-top: 1px solid #262d29;
            margin-top: 26px;
            padding: 16px 2px 2px 2px;
        }
        QGroupBox#RightCard::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 0px;
            top: 4px;
            padding: 0 8px 0 0;
            background: transparent;
            color: #5d6862;
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 2px;
        }

        QGroupBox#RightCard QLabel {
            font-size: 12px;
            font-weight: normal;
            color: #c8c8c8;
            letter-spacing: 0;
            border: none;
            background: transparent;
        }
        QLabel#ResourceLabel {
            background-color: transparent;
            border: none;
            padding: 0;
            font-size: 11px;
            color: #c8c8c8;
        }
        QFrame#CardDivider {
            background-color: #242424;
            color: #242424;
            max-height: 1px;
            border: none;
        }

        QGroupBox#RightCard QLineEdit {
            font-size: 12px;
            color: #ffffff;
            background-color: #0f0f0f;
            border: 1px solid #242424;
            border-radius: 6px;
            padding: 5px 10px;
        }
        QGroupBox#RightCard QLineEdit:focus {
            border: 1px solid #3cff88;
        }

        QGroupBox#RightCard QPushButton {
            font-size: 12px;
            font-weight: 500;
            color: #d0d0d0;
            background-color: #1a1a1a;
            border: 1px solid #262626;
            border-radius: 8px;
            padding: 8px 12px;
            text-align: left;
        }
        QGroupBox#RightCard QPushButton:hover {
            background-color: #232323;
            border: 1px solid #3cff88;
            color: #ffffff;
        }
        QGroupBox#RightCard QPushButton:pressed {
            background-color: #0f0f0f;
        }
        QGroupBox#RightCard QPushButton:disabled {
            color: #4a4a4a;
            background-color: #161616;
            border: 1px solid #1f1f1f;
        }
        """)

        return right_widget

    def load_provider_models(self):
        if not hasattr(self, "provider_box") or not hasattr(self, "model_box"):
            return

        provider = self.provider_box.currentText()
        previous_model = self.settings.get(f"default_model_{provider}", "")

        self.model_box.clear()

        try:
            if provider == "ollama":
                models = self.ollama.list_models()
                if not models:
                    models = list(OllamaClient.KNOWN_MODELS)

            elif provider == "openai":
                if not self.openai.client:
                    models = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"]
                else:
                    result = self.openai.client.models.list()
                    models = sorted(
                        m.id for m in result.data
                        if any(x in m.id.lower() for x in ["gpt", "o1", "o3", "o4"])
                    )

            elif provider == "deepseek":
                # Try API model list if available. Fallback to known/common names.
                try:
                    if self.deepseek.client:
                        result = self.deepseek.client.models.list()
                        models = sorted(m.id for m in result.data)
                    else:
                        models = []
                except Exception:
                    models = []

                if not models:
                    models = [
                        "deepseek-chat",
                        "deepseek-reasoner",
                        "deepseek-coder",
                        "deepseek-v4-pro",
                        "deepseek-v4-flash",
                    ]

            elif provider == "kimi":
                # Try API model list if available. Fallback to known/common names.
                try:
                    if self.kimi.client:
                        result = self.kimi.client.models.list()
                        models = sorted(m.id for m in result.data)
                    else:
                        models = []
                except Exception:
                    models = []

                if not models:
                    models = self.kimi.KNOWN_MODELS

            elif provider == "gemini":
                try:
                    if self.gemini.client:
                        result = self.gemini.client.models.list()
                        models = sorted(
                            m.name.replace("models/", "")
                            for m in result
                            if "generateContent" in getattr(m, "supported_actions", [])
                            or "generateContent" in getattr(m, "supported_generation_methods", [])
                        )
                    else:
                        models = []
                except Exception:
                    models = []

                if not models:
                    models = [
                        "gemini-1.5-flash",
                        "gemini-1.5-pro",
                        "gemini-2.0-flash",
                        "gemini-2.5-flash",
                        "gemini-2.5-pro",
                    ]

            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()

            else:
                models = []

            self.model_box.addItems(models)
            self.decorate_model_costs(provider, self.model_box)

            if previous_model:
                idx = self.model_box.findText(previous_model)
                if idx >= 0:
                    self.model_box.setCurrentIndex(idx)

            self.update_live_cost_estimate()

        except Exception as e:
            self.output_box.append(f"[Model Load Error] {e}")
            
    def save_provider_model_preference(self):
        if not hasattr(self, "provider_box") or not hasattr(self, "model_box"):
            return

        provider = self.provider_box.currentText()
        model = self.model_box.currentText()

        if not provider or not model:
            return

        self.settings[f"default_model_{provider}"] = model

        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            self.output_box.append(f"[Settings Save Error] {e}")   

    def apply_global_style(self):
        self.setStyleSheet(GLOBAL_STYLESHEET)

    # ──────────────────────────────────────────────────────────────────
    # OP IDENTITY PANEL
    # ──────────────────────────────────────────────────────────────────

    OSINT_TOOLS = [
        # id, display name, category, cost label, signup URL, .env key (or "")
        ("emailrep",       "EmailRep.io",        "Email",    "Free",       "https://emailrep.io",                           ""),
        ("urlscan",        "URLScan.io",          "Domain",   "Free",       "https://urlscan.io/user/register",              "URLSCAN_API_KEY"),
        ("virustotal",     "VirusTotal",          "Threat",   "Free",       "https://www.virustotal.com/gui/join-us",         "VIRUSTOTAL_API_KEY"),
        ("otx",            "AlienVault OTX",      "Threat",   "Free",       "https://otx.alienvault.com/",                   "OTX_API_KEY"),
        ("ipinfo",         "IPinfo.io",           "Network",  "Free",       "https://ipinfo.io/signup",                      "IPINFO_API_KEY"),
        ("abuseipdb",      "AbuseIPDB",           "Network",  "Free",       "https://www.abuseipdb.com/register",            "ABUSEIPDB_API_KEY"),
        ("greynoise",      "GreyNoise",           "Network",  "Free",       "https://www.greynoise.io/signup",               "GREYNOISE_API_KEY"),
        ("censys",         "Censys",              "Network",  "Free",       "https://search.censys.io/register",             "CENSYS_API_KEY"),
        ("securitytrails", "SecurityTrails",      "Domain",   "Free",       "https://securitytrails.com/app/signup",         "SECURITYTRAILS_API_KEY"),
        ("hunter",         "Hunter.io",           "Email",    "Free",       "https://hunter.io/users/sign_up",               "HUNTER_API_KEY"),
        ("breachdirectory","BreachDirectory",     "Breach",   "Free",       "https://breachdirectory.org",                   ""),
        ("hibp",           "HaveIBeenPwned",      "Breach",   "$3.50/mo",   "https://haveibeenpwned.com/API/Key",            "HIBP_API_KEY"),
        ("shodan",         "Shodan",              "Network",  "$49/mo",     "https://account.shodan.io/register",            "SHODAN_API_KEY"),
        ("dehashed",       "DeHashed",            "Breach",   "$5/mo",      "https://dehashed.com/register",                 "DEHASHED_API_KEY"),
        ("snusbase",       "Snusbase",            "Breach",   "$2/mo",      "https://snusbase.com/",                         "SNUSBASE_API_KEY"),
        ("leakcheck",      "LeakCheck",           "Breach",   "Paid",       "https://leakcheck.io/",                         "LEAKCHECK_API_KEY"),
        ("intelx",         "IntelligenceX",       "Dark Web", "Paid",       "https://intelx.io/",                            "INTELX_API_KEY"),
        ("domaintools",    "DomainTools",         "Domain",   "Paid",       "https://www.domaintools.com/",                  "DOMAINTOOLS_API_KEY"),
    ]

    def select_agent(self, agent_name):
        self.agent_box.setCurrentText(agent_name)
        for btn in self.agent_buttons.values():
            btn.setChecked(False)
        if agent_name in self.agent_buttons:
            self.agent_buttons[agent_name].setChecked(True)
        self.update_agent_ui(agent_name)

    def update_agent_ui(self, agent_name):
        self._current_agent = agent_name  # track for show_agent_docs()
        # ── Update the agent header bar (title + subtitle + status pill) ─
        agent_titles = {
            "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
            "wifi": "Beacon", "bug_bounty": "Bug Spray",
            "vpn": "Tunnel",
            "manager": "Forge", }
        agent_subtitles = {
            "chat":        "General reasoning, any provider",
            "osint":       "Open-source identity research",
            "osint_heavy": "Deep investigation and dossier",
            "wifi":        "Wireless reconnaissance",
            "bug_bounty":  "Vulnerability triage",
            "vpn":         "Self-hosted VPN design & kill switch",
            "manager":      "Build and register new agents",
            }
        if hasattr(self, "agent_title_label"):
            self.agent_title_label.setText(agent_titles.get(agent_name, agent_name.capitalize()))
        if hasattr(self, "agent_subtitle_label"):
            self.agent_subtitle_label.setText(agent_subtitles.get(agent_name, ""))
        if hasattr(self, "agent_status_pill"):
            self.agent_status_pill.setText("●  Ready")
            self.agent_status_pill.setStyleSheet("")
        is_manager = agent_name == "manager"
        is_osint = agent_name == "osint"
        is_osint_heavy = agent_name == "osint_heavy"
        is_wifi = agent_name == "wifi"
        is_bug_bounty = agent_name == "bug_bounty"
        is_vpn = agent_name == "vpn"
        is_custom = (is_manager
                     or is_osint or is_osint_heavy or is_wifi
                     or is_bug_bounty or is_vpn)

        self.normal_panel.setVisible(not is_custom)
        self.manager_panel.setVisible(is_manager)
        self.osint_panel.setVisible(is_osint)
        self.osint_heavy_panel.setVisible(is_osint_heavy)
        self.wifi_panel.setVisible(is_wifi)
        self.bug_bounty_panel.setVisible(is_bug_bounty)
        self.vpn_panel.setVisible(is_vpn)
        # Output area only relevant for standard (non-custom) agents like Chat.
        # Within those, auto-hide if there is no content yet — keeps the UI clean.
        standard_agent_with_output = not is_custom
        has_output_content = bool(self.output_box.toPlainText().strip())
        # The output area keeps its place whether or not it has content yet —
        # a column that reflows every time an answer arrives is disorienting.
        show_output = standard_agent_with_output
        self.output_label.setVisible(show_output)
        self.output_box.setVisible(show_output)

        if is_manager:
            self.output_label.setText("Forge Output")
            self.output_box.setPlainText("[Forge] Describe an idea above and click Analyze.")
        elif is_osint or is_osint_heavy or is_wifi or is_bug_bounty or is_vpn:
            pass
        else:
            self.output_label.setText("Output")

    def load_models(self):
        self.model_box.clear()
        try:
            models = self.ollama.list_models()
        except Exception:
            models = []
        if not models:
            models = list(OllamaClient.KNOWN_MODELS)
        self.model_box.addItems(models)
        self.update_live_cost_estimate()

    def build_tool_messages(self, selected_tool, full_prompt):
        tool_config = self.tool_prompts.get(selected_tool, {})
        system_prompt = tool_config.get("system", "You are a helpful assistant.")

        return self.apply_project_context([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt},
        ])

    def active_project(self) -> dict | None:
        if not self.active_project_id:
            return None
        return self.registry.get_project(self.active_project_id)

    def project_instructions(self) -> str:
        project = self.active_project()
        return str((project or {}).get("instructions") or "").strip()

    def apply_project_context(self, messages: list) -> list:
        """Return a copy with the active project's instructions injected once."""
        instructions = self.project_instructions()
        result = [dict(message) for message in messages]
        if not instructions:
            return result
        marker = "Project instructions:\n"
        if any(marker in str(message.get("content", "")) for message in result):
            return result
        block = f"{marker}{instructions}"
        for message in result:
            if message.get("role") == "system":
                existing = str(message.get("content") or "").rstrip()
                message["content"] = f"{existing}\n\n{block}" if existing else block
                break
        else:
            result.insert(0, {"role": "system", "content": block})
        return result

    def project_budget_context(self) -> dict:
        project = self.active_project()
        if not project:
            return {"project_name": "", "project_cost": 0.0, "project_budget": None}
        return {
            "project_name": project["name"],
            "project_cost": self.usage_tracker.get_project_total_today(project["id"]),
            "project_budget": project.get("budget_eur"),
        }

    def project_prompt_for_estimate(self, prompt: str) -> str:
        instructions = self.project_instructions()
        return f"{instructions}\n\n{prompt}" if instructions else prompt

    def auto_route_agent(self):
        raw_text = self.input_box.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Warning", "Please enter text first.")
            return

        selected_agent = self.agent_box.currentText()
        selected_tool = self.tool_box.currentText() if hasattr(self, "tool_box") else "General Chat"
        permissions = {
            "openai": self.allow_openai_checkbox.isChecked(), "deepseek": self.allow_deepseek_checkbox.isChecked(),
            "kimi": self.allow_kimi_checkbox.isChecked(), "gemini": self.allow_gemini_checkbox.isChecked(),
            "anthropic": self.allow_anthropic_checkbox.isChecked(), "qwen": self.allow_qwen_checkbox.isChecked(),
            "ollama": True,
        }
        task = "coding" if selected_tool == "Coding" else "writing" if selected_tool in {"Writing", "Rewrite"} else "general"
        router = ModelRouter(str(SETTINGS_FILE))
        complexity = router.classify_complexity(selected_agent, raw_text)
        input_tokens = max(1, len(self.project_prompt_for_estimate(raw_text)) // 4)
        candidates = []
        for provider in PROVIDERS:
            models = self.models_for_provider(provider)
            for model in models:
                estimate = self.usage_tracker.estimate_cost_range(
                    provider, model, input_tokens, max(128, input_tokens // 2), max(500, input_tokens * 2))
                candidates.append(ModelCandidate(
                    provider, model, enabled=self.registry.agent_allows_provider(selected_agent, provider),
                    credentials=permissions[provider], service_healthy=bool(models), model_available=True,
                    context_window=128_000, local=provider == "ollama",
                    latency="high" if provider == "ollama" else "low",
                    capabilities=frozenset({"general", complexity, task}), cost=estimate,
                ))
        remaining = min(self.session_budget_eur - self.session_cost_total,
                        self.daily_budget_eur - self.usage_tracker.get_today_total())
        recommendation = router.recommend(candidates, RoutingPreferences(
            task=task, complexity=complexity, required_context=input_tokens,
            budget_eur=max(0.0, remaining), local_only=self.execution_mode_box.currentText() == "Local only"))
        self._last_routing_recommendation = recommendation
        if recommendation.provider is None:
            self.route_result_label.setText("Router: no eligible model")
            return
        explanation = "; ".join(recommendation.reasons[:3])
        self.route_result_label.setText(
            f"Recommended: {recommendation.provider} · {recommendation.model} — {explanation}")

    def resolve_backend_model(self):
        provider = self.provider_box.currentText()
        model = self.model_box.currentText()
        execution_mode = self.execution_mode_box.currentText()

        allowed_apis = {
            "openai": self.allow_openai_checkbox.isChecked(),
            "deepseek": self.allow_deepseek_checkbox.isChecked(),
            "kimi": self.allow_kimi_checkbox.isChecked(),
            "gemini": self.allow_gemini_checkbox.isChecked(),
            "anthropic": self.allow_anthropic_checkbox.isChecked(),
            "qwen": self.allow_qwen_checkbox.isChecked(),
        }

        if execution_mode == "Local only":
            return "ollama", model if model else "deepseek-r1:8b"

        if execution_mode == "Cloud only":
            if provider == "ollama":
                raise RuntimeError("Cloud only mode selected, but provider is Ollama/local.")

            if provider not in allowed_apis:
                raise RuntimeError(f"Unknown cloud provider: {provider}")

            if not allowed_apis[provider]:
                raise RuntimeError(f"{provider} API is not enabled. Tick the checkbox first.")

            return provider, model

        if execution_mode == "Hybrid allowed":
            if provider == "ollama":
                return "ollama", model if model else "deepseek-r1:8b"

            if provider in allowed_apis and not allowed_apis[provider]:
                raise RuntimeError(f"{provider} API is not enabled. Tick the checkbox first.")

            return provider, model

        return "ollama", model if model else "deepseek-r1:8b"

    def build_user_prompt(self, raw_text: str):
        command_name = self.command_box.currentText()
        prefix = self.commands.get(command_name, "")
        if prefix.strip():
            return command_name, f"{prefix}\n\n{raw_text}"
        return command_name, raw_text

    def send_prompt(self):
        selected_agent = self.agent_box.currentText()

        if selected_agent == "manager":
            # Forge's Send goes to its own panel; the chat box is not its input.
            self.panels["manager"].analyze_idea()
            return

        raw_text = self.input_box.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Warning", "Please enter text first.")
            return

        selected_tool = self.tool_box.currentText() if hasattr(self, "tool_box") else "General Chat"
        command_name, full_prompt = self.build_user_prompt(raw_text)
        final_backend, final_model = self.resolve_backend_model()

        estimated_cost, approx_tokens = self.estimate_chat_cost(
            final_backend, final_model, self.project_prompt_for_estimate(full_prompt))

        api_permissions = {
            "allow_openai": self.allow_openai_checkbox.isChecked(),
            "allow_deepseek": self.allow_deepseek_checkbox.isChecked(),
            "allow_kimi": self.allow_kimi_checkbox.isChecked(),
            "allow_gemini": self.allow_gemini_checkbox.isChecked(),
            "allow_anthropic": self.allow_anthropic_checkbox.isChecked(),
            "allow_qwen": self.allow_qwen_checkbox.isChecked(),
        }

        validation = self.validator.validate(
            agent_name=selected_agent,
            tool_name=selected_tool,
            provider=final_backend,
            api_permissions=api_permissions,
            session_cost=self.session_cost_total,
            session_budget=self.session_budget_eur,
            daily_cost=self.usage_tracker.get_today_total(),
            daily_budget=self.daily_budget_eur,
            estimated_cost=estimated_cost,
            **self.project_budget_context(),
        )
        if not validation.allowed:
            QMessageBox.warning(self, "Request Blocked", validation.reason)
            return

        if not self.confirm_external_api_request(
            final_backend,
            final_model,
            estimated_cost,
            approx_tokens,
        ):
            return

        # Memory pre-flight sits with the other gates, before any UI state is
        # changed. Run it after the worker is armed and a cancel would strand a
        # disabled Send button and an open run-log entry.
        if not self.check_memory_before_request(final_backend, final_model):
            return

        try:
            if selected_tool in self.tool_prompts:
                messages = self.build_tool_messages(selected_tool, full_prompt)
            elif selected_agent in self.agent_instances:
                agent = self.agent_instances[selected_agent]
                messages = self.apply_project_context(agent.build_messages(full_prompt))
            else:
                messages = self.apply_project_context(
                    [{"role": "user", "content": full_prompt}])

            self.pending_agent = selected_agent
            self.pending_tool = selected_tool
            self.pending_backend = final_backend
            self.pending_model = final_model
            self.pending_command = command_name
            self.pending_messages = messages
            self.pending_prompt = full_prompt
            self.pending_usage = None
            self.pending_project = self.active_project_id

            self.show_output_area()
            self.output_box.clear()
            self.output_box.append("[Working]")
            self.output_box.append(f"Agent: {selected_agent}")
            self.output_box.append(f"Backend: {final_backend}")
            self.output_box.append(f"Model: {final_model}")
            self.output_box.append(f"Command: {command_name}")
            self.output_box.append("")
            self.output_box.append("Starting background worker...\n")

            self.route_result_label.setText(f"Router: {selected_agent} · {final_backend} · {final_model}")

            self.send_btn.setEnabled(False)
            self.stop_chat_btn.setEnabled(True)

            self.start_chat_timer(final_backend, final_model, full_prompt)

            self.active_run_id = self.run_logger.start(
                agent=selected_agent,
                tool=selected_tool,
                provider=final_backend,
                model=final_model,
                mode=self.execution_mode_box.currentText() if hasattr(self, "execution_mode_box") else "",
                prompt_summary=full_prompt,
            )

            self.chat_worker = ChatWorker(self.run_backend, final_backend, final_model, messages, full_prompt)
            self.chat_worker.status_signal.connect(self.handle_chat_status)
            self.chat_worker.token_signal.connect(self.handle_chat_token)
            self.chat_worker.finished_signal.connect(self.handle_chat_finished)
            self.chat_worker.usage_signal.connect(self.handle_chat_usage)
            self.chat_worker.error_signal.connect(self.handle_chat_error)
            self.chat_worker.start()

        except Exception as e:
            QMessageBox.warning(self, "Request failed", str(e))

    def confirm_external_api_request(self, backend, model, estimated_cost, approx_tokens):
        if backend == "ollama":
            return True

        message = (
            f"This request will use an external API.\n\n"
            f"Provider: {backend}\n"
            f"Model: {model}\n"
            f"Approx tokens: {approx_tokens}\n"
            f"Estimated cost/quota impact: ~€{estimated_cost:.2f}\n\n"
            f"Continue?"
        )

        result = QMessageBox.question(
            self,
            "Confirm External API Request",
            message,
            QMessageBox.Yes | QMessageBox.No,
        )

        return result == QMessageBox.Yes

    # ── Shared request guard (TODO.md #1) ───────────────────────────────
    # Any agent that can spend money must go through these. Only send_prompt()
    # used to, so the budget caps, the spend counters, the paid-API prompt and
    # Saved Chats all silently ignored every other agent.

    def _note_failure(self, context, exc, widget=None):
        """Record a swallowed exception instead of discarding it.

        These paths deliberately must not raise into the UI, but a bare
        `except: pass` made a failed model listing or history load look exactly
        like "there is nothing here". stderr is captured by the app launcher in
        /tmp/sentinel_launch.log; when a widget is given, the reason is also
        attached to it as a tooltip so it is visible without reading a log.
        """
        message = f"{context}: {type(exc).__name__}: {exc}"
        print(f"[warn] {message}", file=sys.stderr)
        if widget is not None:
            try:
                widget.setToolTip(f"Last error — {message}")
            except Exception:
                pass

    def current_api_permissions(self) -> dict:
        """The provider checkboxes, as the validator expects them."""
        return {
            "allow_openai": self.allow_openai_checkbox.isChecked(),
            "allow_deepseek": self.allow_deepseek_checkbox.isChecked(),
            "allow_kimi": self.allow_kimi_checkbox.isChecked(),
            "allow_gemini": self.allow_gemini_checkbox.isChecked(),
            "allow_anthropic": self.allow_anthropic_checkbox.isChecked(),
            "allow_qwen": self.allow_qwen_checkbox.isChecked(),
        }

    def _resolve_request_id(self, identifier):
        """Accept a request id, with a safe bridge for one legacy agent key.

        The bridge keeps older internal callers working during the v2 split. It
        deliberately refuses an ambiguous agent key instead of guessing when
        two runs of the same agent are active.
        """
        if identifier in self._pending_requests:
            return identifier
        matches = [
            request_id for request_id, context in self._pending_requests.items()
            if context.get("agent") == identifier
        ]
        return matches[0] if len(matches) == 1 else None

    def note_request_usage(self, request_id, usage):
        """Real token counts from the worker, when it reports them."""
        request_id = self._resolve_request_id(request_id)
        context = self._pending_requests.get(request_id)
        if context is not None:
            context["usage"] = usage

    def authorize_request(self, agent, provider, model, prompt, tool=None, label=None):
        """Budget-check and confirm one request. Return its id or ``None``.

        `tool` is a registry tool name and is validated as one — pass it only
        when the request really runs a registered tool (the chat panel does).
        The agent panels pick their own mode ("Person", "Deep Scan", …), which
        is not a registry entry: pass that as `label` instead, so it still shows
        up in the run log and Saved Chats without failing the tool check.

        Context is keyed by the run id rather than the agent, so concurrent runs
        of the same agent cannot overwrite one another.
        """
        estimated_cost, approx_tokens = self.estimate_chat_cost(
            provider, model, self.project_prompt_for_estimate(prompt))

        validation = self.validator.validate(
            agent_name=agent,
            tool_name=tool,
            provider=provider,
            api_permissions=self.current_api_permissions(),
            session_cost=self.session_cost_total,
            session_budget=self.session_budget_eur,
            daily_cost=self.usage_tracker.get_today_total(),
            daily_budget=self.daily_budget_eur,
            estimated_cost=estimated_cost,
            **self.project_budget_context(),
        )
        if not validation.allowed:
            QMessageBox.warning(self, "Request Blocked", validation.reason)
            return None

        if not self.confirm_external_api_request(provider, model, estimated_cost, approx_tokens):
            return None

        descriptor = label or tool or "-"
        run_id = self.run_logger.start(
            agent=agent,
            tool=descriptor,
            provider=provider,
            model=model,
            mode=self.execution_mode_box.currentText() if hasattr(self, "execution_mode_box") else "",
            prompt_summary=prompt,
        )
        request_id = run_id or f"request-{uuid4().hex}"
        self._pending_requests[request_id] = {
            "agent": agent,
            "tool": descriptor,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "usage": None,
            "run_id": run_id,
            "project": self.active_project_id,
        }
        return request_id

    def record_request(self, request_id, response, messages=None):
        """Bill, save and close out a request authorised by authorize_request()."""
        request_id = self._resolve_request_id(request_id)
        context = self._pending_requests.pop(request_id, None)
        if context is None:          # never authorised (or already recorded)
            return

        entry = self.usage_tracker.log_request(
            agent=context["agent"],
            backend=context["provider"],
            model=context["model"],
            prompt_text=context["prompt"],
            response_text=response,
            usage=context["usage"],
            project=context.get("project"),
        )

        self.last_request_cost = entry.get("cost_eur", entry.get("estimated_cost", 0.0))
        self.last_tool_name = f"{context['agent']}/{context['tool']} - {context['provider']}"
        self.session_cost_total += entry.get("estimated_cost", 0.0)
        self.session_request_count += 1
        self.update_usage_labels()

        if messages is None:
            messages = [{"role": "user", "content": context["prompt"]}]
        self.history.save_chat(
            agent=context["agent"],
            backend=context["provider"],
            model=context["model"],
            command=context["tool"],
            messages=messages + [{"role": "assistant", "content": response}],
            response=response,
            project=context.get("project"),
        )

        if context["run_id"]:
            self.run_logger.finish(
                run_id=context["run_id"],
                status="success",
                input_tokens=entry.get("input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
                cost_eur=entry.get("cost_eur", 0.0),
            )

        self.load_history_list()

    def abandon_request(self, request_id, reason="error"):
        """Drop a request that failed, so it is not billed and the log closes."""
        request_id = self._resolve_request_id(request_id)
        context = self._pending_requests.pop(request_id, None)
        if context and context["run_id"]:
            self.run_logger.finish(run_id=context["run_id"], status=reason)

    def run_backend(self, backend, model, messages, prompt):
        if backend == "ollama":
            # Runs on the worker thread, so this cannot prompt — it is the hard
            # floor only. Every agent funnels through here, so a model that
            # physically cannot fit is stopped once, for all of them, and the
            # message surfaces via each agent's existing error path instead of
            # freezing the machine for the full request timeout.
            verdict = self.assess_local_model(model)
            if verdict is not None and verdict["level"] == "too_big":
                raise RuntimeError(verdict["message"])

            if hasattr(self.ollama, "chat"):
                return self.ollama.chat(model=model, messages=messages)
            if hasattr(self.ollama, "generate"):
                return self.ollama.generate(model=model, prompt=prompt)

        if backend == "openai":
            if hasattr(self.openai, "stream_chat"):
                return self.openai.stream_chat(messages=messages, model=model)
            if hasattr(self.openai, "chat"):
                return self.openai.chat(messages=messages, model=model)
            if hasattr(self.openai, "generate"):
                return self.openai.generate(prompt, model=model)

        if backend == "deepseek":
            if hasattr(self.deepseek, "stream_chat"):
                return self.deepseek.stream_chat(messages=messages, model=model)
            if hasattr(self.deepseek, "chat"):
                return self.deepseek.chat(messages=messages, model=model)
            if hasattr(self.deepseek, "generate"):
                return self.deepseek.generate(prompt, model=model)

        if backend == "kimi":
            if hasattr(self.kimi, "stream_chat"):
                return self.kimi.stream_chat(messages=messages, model=model)
            if hasattr(self.kimi, "chat"):
                return self.kimi.chat(messages=messages, model=model)
            if hasattr(self.kimi, "generate"):
                return self.kimi.generate(prompt, model=model)

        if backend == "qwen":
            if hasattr(self.qwen, "stream_chat"):
                return self.qwen.stream_chat(messages=messages, model=model)
            if hasattr(self.qwen, "chat"):
                return self.qwen.chat(messages=messages, model=model)
            if hasattr(self.qwen, "generate"):
                return self.qwen.generate(prompt, model=model)

        if backend == "gemini":
            if hasattr(self.gemini, "stream_chat"):
                return self.gemini.stream_chat(messages=messages, model=model)

            if hasattr(self.gemini, "chat"):
                return self.gemini.chat(messages=messages, model=model)

            if hasattr(self.gemini, "generate"):
                return self.gemini.generate(prompt, model=model)

        if backend == "anthropic":
            if hasattr(self.anthropic, "stream_chat"):
                return self.anthropic.stream_chat(messages=messages, model=model)

            if hasattr(self.anthropic, "chat"):
                return self.anthropic.chat(messages=messages, model=model)

        raise RuntimeError(f"No compatible backend method found for backend: {backend}")

    def start_chat_timer(self, backend: str, model: str, prompt: str):
        self.chat_started_at = time.time()
        self.chat_elapsed_seconds = 0
        self.chat_estimated_seconds = self.estimate_chat_seconds(backend, model, prompt)
        self.chat_progress.setMinimum(0)
        self.chat_progress.setMaximum(0)
        self.chat_progress.show()
        self.chat_status_label.show()
        if not hasattr(self, "chat_timer"):
            self.chat_timer = QTimer(self)
            self.chat_timer.timeout.connect(self.update_chat_timer)
        self.chat_timer.start(1000)
        self.update_chat_timer()

    def update_chat_timer(self):
        elapsed = int(time.time() - self.chat_started_at) if self.chat_started_at else self.chat_elapsed_seconds
        remaining = max(0, self.chat_estimated_seconds - elapsed)
        self.chat_status_label.setText(
            f"Processing... elapsed {self.format_seconds(elapsed)} · rough remaining {self.format_seconds(remaining)}"
        )

    def stop_chat_timer(self):
        if hasattr(self, "chat_timer"):
            self.chat_timer.stop()
        self.chat_progress.hide()

    def handle_chat_status(self, text):
        self.output_box.moveCursor(QTextCursor.End)
        self.output_box.insertPlainText(text + "\n")
        self.output_box.ensureCursorVisible()

    def handle_chat_token(self, text):
        self.output_box.moveCursor(QTextCursor.End)
        self.output_box.insertPlainText(text)
        self.output_box.ensureCursorVisible()

    def handle_chat_finished(self, response):
        self.stop_chat_timer()
        self.send_btn.setEnabled(True)
        self.stop_chat_btn.setEnabled(False)

        self.current_messages = self.pending_messages + [{"role": "assistant", "content": response}]
        self.output_box.append("\n\n[Finished]")

        usage_entry = self.usage_tracker.log_request(
            agent=self.pending_agent,
            backend=self.pending_backend,
            model=self.pending_model,
            prompt_text=self.pending_prompt,
            response_text=response,
            usage=self.pending_usage,
            project=getattr(self, "pending_project", None),
        )

        self.last_request_cost = usage_entry.get("cost_eur", usage_entry.get("estimated_cost", 0.0))
        tool = getattr(self, "pending_tool", "General Chat")
        self.last_tool_name = f"{self.pending_agent}/{tool} - {self.pending_backend}"
        self.session_cost_total += usage_entry["estimated_cost"]
        self.session_request_count += 1
        self.update_usage_labels()

        run_id = getattr(self, "active_run_id", None)
        if run_id:
            self.run_logger.finish(
                run_id=run_id,
                status="success",
                input_tokens=usage_entry.get("input_tokens", 0),
                output_tokens=usage_entry.get("output_tokens", 0),
                cost_eur=usage_entry.get("cost_eur", 0.0),
            )
            self.active_run_id = None

        self.history.save_chat(
            agent=self.pending_agent,
            backend=self.pending_backend,
            model=self.pending_model,
            command=self.pending_command,
            messages=self.current_messages,
            response=response,
            project=getattr(self, "pending_project", None),
        )

        self.load_history_list()
        self.route_result_label.setText(f"Router: {self.pending_agent} · {self.pending_backend} · {self.pending_model}")

    def handle_chat_error(self, error):
        self.stop_chat_timer()
        self.output_box.append(f"\n[Error]\n{error}")
        self.send_btn.setEnabled(True)
        self.stop_chat_btn.setEnabled(False)

        run_id = getattr(self, "active_run_id", None)
        if run_id:
            self.run_logger.finish(run_id=run_id, status="error", error=error)
            self.active_run_id = None
        
    def handle_chat_usage(self, usage):
        self.pending_usage = usage

    def stop_chat_worker(self):
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.chat_worker.cancel()
            self.chat_worker.terminate()
            self.chat_worker.wait(2000)
            self.output_box.append("\n[Stopped] Chat request stopped by user.")
        self.stop_chat_timer()
        self.send_btn.setEnabled(True)
        self.stop_chat_btn.setEnabled(False)

        run_id = getattr(self, "active_run_id", None)
        if run_id:
            self.run_logger.cancel(run_id)
            self.active_run_id = None

    def stop_current_task(self):
        """The window's Stop button: cancel whatever is actually running.

        The 2026-08-19 cull left this method calling `self.author_worker`,
        `music_worker`, `webdesign_worker`, `fiverr_*_worker` and the audiobook
        process, none of which exist any more — so Stop raised `AttributeError`
        before it reached a single surviving agent. Every agent vertical is now a
        panel in `self.panels` that answers for itself (phase 4); only chat, which
        still lives on the window, is handled directly.
        """
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.stop_chat_worker()
            return

        for panel in self.panels.values():
            if panel.is_running():
                panel.stop()
                return

        self.output_box.append("\n[Info] No running task to stop.")

    def update_resource_label(self):
        """Drive the SYSTEM meters. The exact figures move to the tooltips —
        visible on demand, rather than crowding the glanceable number."""
        stats = self.monitor.snapshot()

        self.resource_meters["RAM"].set(
            stats["ram_percent"] / 100.0,
            f"{stats['ram_percent']:.0f}%",
            stats["ram_level"],
            f"{stats['ram_used_gb']:.1f} GB used · {stats['ram_available_gb']:.1f} GB free",
        )
        self.resource_meters["CPU"].set(
            stats["cpu_percent"] / 100.0,
            f"{stats['cpu_percent']:.0f}%",
            stats["cpu_level"],
        )
        self.resource_meters["SWAP"].set(
            stats["swap_percent"] / 100.0,
            f"{stats['swap_percent']:.0f}%",
            stats["swap_level"],
            f"{stats['swap_used_gb']:.1f} of {stats['swap_total_gb']:.1f} GB",
        )

        if stats["battery_percent"] is None:
            self.resource_meters["BATT"].set_unavailable()
        else:
            self.resource_meters["BATT"].set(
                stats["battery_percent"] / 100.0,
                f"{stats['battery_percent']:.0f}%",
                stats["battery_level"],
                stats["battery_note"],
            )

    def update_usage_labels(self):
        today_total = self.usage_tracker.get_today_total()
        today_requests = self.usage_tracker.get_total_requests_today()
        tool_name = getattr(self, "last_tool_name", "-")

        # ✅ updated last request label (now includes tool name)
        self.last_request_label.setText(
            f"Last Request Cost: €{self.last_request_cost:.2f} ({tool_name})"
        )
        if hasattr(self, "cost_rows"):
            self.cost_rows["last"].set(f"€{self.last_request_cost:.2f}", tool_name)
            self.cost_rows["session"].set(f"€{self.session_cost_total:.2f}")
            self.cost_rows["today"].set(f"€{today_total:.2f}")
            self.cost_rows["requests"].set(
                f"{today_requests} today · {self.session_request_count} session")

        # keep your existing labels
        self.session_cost_label.setText(f"Session Cost: €{self.session_cost_total:.2f}")
        self.today_cost_label.setText(f"Cost Today: €{today_total:.2f}")
        self.request_count_label.setText(
            f"Requests Today: {today_requests} | Session: {self.session_request_count}"
        )

        # budget calculations
        session_remaining = self.session_budget_eur - self.session_cost_total
        daily_remaining = self.daily_budget_eur - today_total

        if hasattr(self, "budget_meters"):
            # Filled by what is spent, not what is left: a bar that empties as
            # you spend reads as progress towards something good.
            for key, spent, cap in (
                ("SESSION", self.session_cost_total, self.session_budget_eur),
                ("DAILY", today_total, self.daily_budget_eur),
            ):
                fraction = (spent / cap) if cap > 0 else 0.0
                level = "red" if fraction >= 0.9 else "yellow" if fraction >= 0.6 else "green"
                remaining = cap - spent
                self.budget_meters[key].set(
                    fraction,
                    f"€{spent:.2f} / €{cap:.0f}",
                    level,
                    f"€{remaining:.2f} left of the €{cap:.2f} {key.lower()} cap",
                )
            project = self.active_project()
            project_meter = self.budget_meters["PROJECT"]
            if project and project.get("budget_eur") is not None:
                spent = self.usage_tracker.get_project_total_today(project["id"])
                cap = float(project["budget_eur"])
                fraction = (spent / cap) if cap > 0 else 0.0
                level = "red" if fraction >= 0.9 else "yellow" if fraction >= 0.6 else "green"
                project_meter.set(
                    fraction, f"€{spent:.2f} / €{cap:.0f}", level,
                    f"{project['name']}: €{cap - spent:.2f} remaining today",
                )
                project_meter.show()
            else:
                project_meter.hide()

    def start_resource_timer(self):
        self.resource_timer = QTimer(self)
        self.resource_timer.timeout.connect(self.update_resource_label)
        self.resource_timer.start(1000)

    def refresh_project_selector(self) -> None:
        if not hasattr(self, "project_filter"):
            return
        current = self.project_filter.currentData()
        self.project_filter.blockSignals(True)
        self.project_filter.clear()
        self.project_filter.addItem(ALL_PROJECTS_FILTER, "__all__")
        self.project_filter.addItem(UNFILED_PROJECT_FILTER, "__unfiled__")
        for project in self.registry.list_projects():
            self.project_filter.addItem(project["name"], project["id"])
        index = self.project_filter.findData(current)
        self.project_filter.setCurrentIndex(index if index >= 0 else 0)
        self.project_filter.blockSignals(False)
        selected = self.project_filter.currentData()
        self.active_project_id = (
            selected if selected not in {"__all__", "__unfiled__", None} else None
        )

    def project_changed(self, _index: int = -1) -> None:
        selected = self.project_filter.currentData() if hasattr(self, "project_filter") else "__all__"
        self.active_project_id = selected if selected not in {"__all__", "__unfiled__", None} else None
        project = self.active_project()
        if project:
            agent = project.get("default_agent") or "chat"
            if hasattr(self, "agent_box") and self.agent_box.findText(agent) >= 0:
                self.select_agent(agent)
            provider = project.get("default_provider") or ""
            model = project.get("default_model") or ""
            panel = self.panels.get(agent)
            provider_box = panel.provider_box if panel else getattr(self, "provider_box", None)
            model_box = panel.model_box if panel else getattr(self, "model_box", None)
            if provider and provider_box and provider_box.findText(provider) >= 0:
                provider_box.setCurrentText(provider)
            if model and model_box and model_box.findText(model) >= 0:
                model_box.setCurrentText(model)
            self.route_result_label.setText(f"Project: {project['name']}")
        elif hasattr(self, "route_result_label"):
            self.route_result_label.setText("Project: none")
        self.load_history_list()
        self.update_usage_labels()

    def show_project_context_menu(self, position) -> None:
        project = self.active_project()
        if not project:
            return
        menu = QMenu(self)
        save_defaults = menu.addAction("Save current setup as project defaults")
        if menu.exec(self.project_filter.mapToGlobal(position)) != save_defaults:
            return
        agent = getattr(self, "_current_agent", "chat")
        panel = self.panels.get(agent)
        provider_box = panel.provider_box if panel else getattr(self, "provider_box", None)
        model_box = panel.model_box if panel else getattr(self, "model_box", None)
        project.update({
            "default_agent": agent,
            "default_provider": provider_box.currentText() if provider_box else "",
            "default_model": model_box.currentText() if model_box else "",
        })
        self.registry.upsert_project(project)
        QMessageBox.information(self, "Project defaults saved", project["name"])

    def show_history_context_menu(self, position) -> None:
        item = self.history_list.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        assign = menu.addMenu("Assign to project")
        choices = {assign.addAction("Unfiled"): None}
        for project in self.registry.list_projects():
            choices[assign.addAction(project["name"])] = project["id"]
        selected = menu.exec(self.history_list.mapToGlobal(position))
        if selected in choices:
            self.history.assign_project(item.data(Qt.UserRole), choices[selected])
            self.load_history_list()

    def chat_title_from_data(self, path: Path, data: Optional[dict] = None) -> str:
        try:
            if data is None:
                data = self.history.load_chat(str(path))
            if data.get("title"):
                return data["title"]

            agent = data.get("agent", "chat")
            first_user = ""
            for msg in data.get("messages", []):
                if msg.get("role") == "user":
                    first_user = msg.get("content", "")
                    break

            clean = re.sub(r"\s+", " ", first_user).strip()
            if not clean:
                clean = path.stem
            return f"{agent}: {clean[:52].rstrip()}"
        except Exception:
            return path.stem

    def load_history_list(self):
        """Fill Saved Chats using the project, agent and text filters together.

        Every file is read once here and reused for both the filter options and
        the rows, so adding the filter costs no extra disk reads.
        """
        self.history_list.clear()
        query = self.history_search.text().strip().lower() if hasattr(self, "history_search") else ""
        try:
            loaded = []
            for file in sorted(CHATS_DIR.glob("*.json"), reverse=True):
                try:
                    data = self.history.load_chat(str(file))
                except Exception:
                    data = {}
                loaded.append((file, data))

            self._refresh_history_agent_filter(loaded)
            wanted = (self.history_agent_filter.currentText()
                      if hasattr(self, "history_agent_filter") else ALL_AGENTS_FILTER)
            project_wanted = (self.project_filter.currentData()
                              if hasattr(self, "project_filter") else "__all__")

            for file, data in loaded:
                if wanted != ALL_AGENTS_FILTER and data.get("agent", "chat") != wanted:
                    continue
                chat_project = data.get("project")
                if project_wanted == "__unfiled__" and chat_project:
                    continue
                if project_wanted not in {"__all__", "__unfiled__"} and chat_project != project_wanted:
                    continue
                title = self.chat_title_from_data(file, data)
                if query and query not in title.lower():
                    continue
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, str(file))
                self.history_list.addItem(item)
        except Exception as exc:
            self._note_failure("saved chats: load list", exc)

    def _refresh_history_agent_filter(self, loaded):
        """Keep the filter's options in step with the chats that exist.

        Signals are blocked while repopulating: the combo's own change signal
        calls back into load_history_list, which would recurse.
        """
        if not hasattr(self, "history_agent_filter"):
            return
        agents = sorted({data.get("agent", "chat") for _f, data in loaded})
        options = [ALL_AGENTS_FILTER] + agents
        current = self.history_agent_filter.currentText()
        if options == [self.history_agent_filter.itemText(i)
                       for i in range(self.history_agent_filter.count())]:
            return                                   # nothing changed
        self.history_agent_filter.blockSignals(True)
        self.history_agent_filter.clear()
        self.history_agent_filter.addItems(options)
        # keep the user's selection when its agent still has chats
        self.history_agent_filter.setCurrentText(
            current if current in options else ALL_AGENTS_FILTER
        )
        self.history_agent_filter.blockSignals(False)

    def rename_selected_chat(self, item):
        """Give a saved chat a name of your own instead of its first prompt."""
        path = item.data(Qt.UserRole) or item.text()
        try:
            data = self.history.load_chat(path)
        except Exception as exc:
            self._note_failure("saved chats: open for rename", exc)
            return

        current = data.get("title", "")
        new_title, ok = QInputDialog.getText(
            self, "Rename Chat", "Name for this chat:", text=current
        )
        if not ok:
            return

        new_title = new_title.strip()
        if new_title:
            data["title"] = new_title
        else:
            data.pop("title", None)      # cleared — fall back to the first prompt
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._note_failure("saved chats: save new name", exc)
            return
        self.load_history_list()

    def open_selected_chat(self, item):
        filepath = item.data(Qt.UserRole) or item.text()
        try:
            data = self.history.load_chat(filepath)
            project_id = data.get("project")
            project_index = self.project_filter.findData(project_id or "__unfiled__")
            if project_index >= 0:
                self.project_filter.setCurrentIndex(project_index)
            self.show_output_area()
            self.output_box.setPlainText(data.get("response", ""))

            first_user_message = ""
            for msg in data.get("messages", []):
                if msg.get("role") == "user":
                    first_user_message = msg.get("content", "")
                    break

            self.input_box.setPlainText(first_user_message)
            self.route_result_label.setText(
                f"Router: {data.get('agent')} · {data.get('backend')} · {data.get('model')}"
            )

            agent_name = data.get("agent", "chat")
            if self.agent_box.findText(agent_name) >= 0:
                self.select_agent(agent_name)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open saved chat:\n{e}")

    def delete_selected_chat(self):
        item = self.history_list.currentItem()
        if not item:
            QMessageBox.information(self, "No Selection", "Select a saved chat first.")
            return

        filepath = item.data(Qt.UserRole)
        confirm = QMessageBox.question(self, "Delete Chat", f"Delete saved chat?\n\n{item.text()}")
        if confirm != QMessageBox.Yes:
            return

        try:
            Path(filepath).unlink(missing_ok=True)
            self.load_history_list()
        except Exception as e:
            QMessageBox.warning(self, "Delete Failed", str(e))

    def new_chat(self):
        self.current_messages = []
        self.last_raw_osint = ""
        self.input_box.clear()
        self.output_box.clear()
        self.hide_output_area()
        self.route_result_label.setText("Router: not yet computed")

    def export_report(self):
        content = self.output_box.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Warning", "No output to export.")
            return
        title = self.agent_box.currentText() + "_report"
        filepath = self.report_exporter.export_text_report(title, content)
        QMessageBox.information(self, "Export Complete", f"Report saved to:\n{filepath}")

    def show_agent_docs(self):
        """Open the documentation dialog for the currently active agent."""
        agent_name = getattr(self, "_current_agent", "chat")

        # Map agent key → doc filename (same as the key for most)
        doc_file_map = {
            "chat": "chat", "osint": "osint", "osint_heavy": "osint_heavy",
            "wifi": "wifi", "bug_bounty": "bug_bounty",
            "vpn": "vpn",
            "manager": "manager", }
        doc_key = doc_file_map.get(agent_name, agent_name)

        # Read-only bundled resource (works in dev and in the frozen .app)
        docs_dir = RESOURCE_DIR / "docs" / "agents"
        doc_path = docs_dir / f"{doc_key}.md"

        # Read the markdown source
        if doc_path.exists():
            raw_md = doc_path.read_text(encoding="utf-8")
        else:
            raw_md = f"# No documentation found\n\nNo documentation file was found for **{agent_name}**.\n\nExpected path: `{doc_path}`"

        # Convert markdown to basic HTML (handles headings, bold, tables, code, lists)
        def md_to_html(text: str) -> str:
            import re
            lines = text.split("\n")
            html_lines = []
            in_table = False
            in_code = False
            i = 0
            while i < len(lines):
                line = lines[i]
                # Code block
                if line.startswith("```"):
                    if not in_code:
                        html_lines.append('<pre style="background:#1e1e1e;color:#d4d4d4;padding:10px;border-radius:6px;font-size:12px;overflow:auto;">')
                        in_code = True
                    else:
                        html_lines.append("</pre>")
                        in_code = False
                    i += 1
                    continue
                if in_code:
                    html_lines.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                    i += 1
                    continue
                # Table row
                if line.startswith("|"):
                    if not in_table:
                        html_lines.append('<table style="border-collapse:collapse;width:100%;margin:8px 0;">')
                        in_table = True
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    # Skip separator row
                    if all(re.match(r"^[-:]+$", c) for c in cells):
                        i += 1
                        continue
                    is_header = (i == 0 or not lines[i-1].startswith("|")) and \
                                i + 1 < len(lines) and re.match(r"^\|[-| :]+\|$", lines[i+1]) if i+1 < len(lines) else False
                    tag = "th" if is_header else "td"
                    row_html = "".join(
                        f'<{tag} style="border:1px solid #333;padding:6px 10px;text-align:left;">{c}</{tag}>'
                        for c in cells
                    )
                    html_lines.append(f"<tr>{row_html}</tr>")
                    i += 1
                    continue
                else:
                    if in_table:
                        html_lines.append("</table>")
                        in_table = False
                # Headings
                if line.startswith("#### "):
                    html_lines.append(f'<h4 style="color:#e8e8e8;margin:10px 0 4px;">{line[5:]}</h4>')
                elif line.startswith("### "):
                    html_lines.append(f'<h3 style="color:#3cff88;margin:14px 0 6px;">{line[4:]}</h3>')
                elif line.startswith("## "):
                    html_lines.append(f'<h2 style="color:#ffffff;border-bottom:1px solid #333;padding-bottom:4px;margin:18px 0 8px;">{line[3:]}</h2>')
                elif line.startswith("# "):
                    html_lines.append(f'<h1 style="color:#3cff88;font-size:20px;margin:0 0 4px;">{line[2:]}</h1>')
                # Blockquote / warning
                elif line.startswith("> "):
                    html_lines.append(f'<blockquote style="border-left:3px solid #f0a000;padding:6px 12px;margin:6px 0;background:#1e1a00;color:#f0c050;">{line[2:]}</blockquote>')
                # Unordered list
                elif line.startswith("- ") or line.startswith("* "):
                    html_lines.append(f'<li style="margin:2px 0;">{line[2:]}</li>')
                # Horizontal rule
                elif line.startswith("---"):
                    html_lines.append('<hr style="border:none;border-top:1px solid #333;margin:12px 0;">')
                # Blank line
                elif line.strip() == "":
                    html_lines.append("<br>")
                # Normal paragraph
                else:
                    html_lines.append(f"<p style='margin:3px 0;'>{line}</p>")
                i += 1
            if in_table:
                html_lines.append("</table>")
            if in_code:
                html_lines.append("</pre>")
            html = "\n".join(html_lines)
            # Inline: **bold**, `code`, *italic*
            html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
            html = re.sub(r"`([^`]+)`", r'<code style="background:#2a2a2a;padding:1px 5px;border-radius:3px;font-size:12px;">\1</code>', html)
            html = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html)
            return html

        html_content = md_to_html(raw_md)
        full_html = f"""
        <html><body style="background:#111111;color:#cccccc;font-family:sans-serif;font-size:13px;padding:4px 8px;">
        {html_content}
        </body></html>
        """

        # Build dialog
        agent_titles = {
            "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
            "wifi": "Beacon", "bug_bounty": "Bug Spray",
            "manager": "Forge", }
        title = agent_titles.get(agent_name, agent_name.upper())

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Docs — {title}")
        dialog.resize(760, 620)
        dialog.setStyleSheet("background-color: #111111;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        browser = QTextBrowser()
        browser.setHtml(full_html)
        browser.setStyleSheet(
            "QTextBrowser { background: #111111; color: #cccccc; border: none; }"
            "QScrollBar:vertical { background: #1a1a1a; width: 10px; }"
            "QScrollBar::handle:vertical { background: #333333; border-radius: 5px; }"
        )
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("ChipBtn")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setFixedWidth(100)
        layout.addWidget(close_btn, 0, Qt.AlignRight)

        dialog.exec()

    def show_model_guide(self):
        from ui.dialogs import show_model_guide as _show_model_guide
        return _show_model_guide(self)
    def show_docs(self, anchor: str = ""):
        dialog = QDialog(self)
        dialog.setWindowTitle("Documentation")
        dialog.resize(950, 700)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenLinks(False)

        if README_FILE.exists():
            text = README_FILE.read_text(encoding="utf-8")
            html = markdown.markdown(text, extensions=["toc", "tables"])
        else:
            html = "<h2>No README.md found</h2><p>Create README.md in the project root.</p>"

        browser.setHtml(html)

        def on_anchor_clicked(url):
            fragment = url.fragment()
            if fragment:
                browser.scrollToAnchor(fragment)

        browser.anchorClicked.connect(on_anchor_clicked)

        if anchor:
            QTimer.singleShot(50, lambda: browser.scrollToAnchor(anchor))

        layout.addWidget(browser)
        dialog.exec()

    def closeEvent(self, event):
        try:
            if self.chat_worker is not None and self.chat_worker.isRunning():
                self.chat_worker.cancel()
                self.chat_worker.terminate()
                self.chat_worker.wait(1000)
        except Exception as exc:
            self._note_failure("shutdown: stop background work", exc)
        event.accept()

SINGLE_INSTANCE_KEY = "sentinel-fork.single-instance.v2"


def _hand_off_to_running_instance() -> bool:
    """True when another copy is already running — it is asked to come forward.

    A local socket is the reliable signal here: a lock file can be left behind by
    a crash, and the .app launcher spawns a fresh python each time, so the OS
    can't dedupe the launch for us.
    """
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if not probe.waitForConnected(400):
        return False
    probe.write(b"raise")
    probe.waitForBytesWritten(400)
    probe.disconnectFromServer()
    return True


if __name__ == "__main__":
    app = QApplication([])

    # Second launch: focus the window that is already open and leave. The exit
    # code has to be 0 — the launcher raises an error dialog on anything else.
    if _hand_off_to_running_instance():
        sys.exit(0)

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)   # clear a socket left by a crash
    instance_server = QLocalServer()
    instance_server.listen(SINGLE_INSTANCE_KEY)

    window = GodAI()
    # Always open in fullscreen. The three panes need ~1000px before the
    # splitter starts squeezing panels, so a small default window is the state
    # the layout looks worst in.
    window.showFullScreen()

    def _raise_existing_window():
        instance_server.nextPendingConnection()      # drain the pending connection
        window.setWindowState(
            (window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive
        )
        window.show()
        window.raise_()
        window.activateWindow()

    instance_server.newConnection.connect(_raise_existing_window)

    app.exec()
