import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Frozen-app narrator worker dispatch ──────────────────────────────────────
# The packaged app can't run `python -m services.narrator.converter`, so it
# re-invokes its own executable with this sentinel. Handle it before importing
# the GUI stack so the audiobook worker process stays lightweight.
if "--narrator-worker" in sys.argv:
    sys.argv.remove("--narrator-worker")
    from services.narrator.converter import main as _narrator_main
    _narrator_main()
    sys.exit(0)

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
    QInputDialog,
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
from services.tool_runner import ToolRunner
from services.database import init_db, get_setting, save_setting, get_connection
from services.registry import Registry
from services.validator import Validator
from services.run_logger import RunLogger

from agents.audiobook_connector import AudiobookConnector
from agents.chat_agent import ChatAgent
from agents.writing_agent import WritingAgent
from agents.coding_agent import CodingAgent
from agents.osint_agent import OSINTAgent
from agents.manager_agent import ManagerAgent
from agents.author_agent import AuthorAgent
from agents.manuscript_agent import ManuscriptAgent
from agents.webdesign_agent import WebdesignAgent
from agents.music_agent import MusicAgent
from agents.bug_bounty_agent import BugBountyAgent
from agents.wifi_agent import WiFiAgent, KNOWN_ADAPTERS, detect_usb_adapters, build_kali_commands, AIRPORT
from agents.osint_heavy_agent import OsintHeavyAgent
from agents.fiverr_agent import FiverrAgent
from services.agent_factory import AgentFactory
from ui.book_widgets import (
    make_theme_box, make_size_box, make_voice_source_box,
    theme_key, size_key, unique_output_path,
)


# Writable base = project root in dev, ~/Library/Application Support/Sentinel AI when frozen.
BASE_DIR = user_data_base()
# Read-only bundled resources (README, config defaults) = project root in dev, bundle when frozen.
RESOURCE_DIR = resource_base()
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CHATS_DIR = DATA_DIR / "chats"

# Sentinel value for the Saved Chats agent filter — not a real agent name.
ALL_AGENTS_FILTER = "All agents"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
AGENTS_FILE = CONFIG_DIR / "agents.json"
COMMANDS_FILE = CONFIG_DIR / "commands.json"
TOOL_PROMPTS_FILE = CONFIG_DIR / "tool_prompts.json"
REGISTRY_FILE = CONFIG_DIR / "registry.json"
README_FILE = RESOURCE_DIR / "README.md"

SUPPORTED_EBOOKS = {".pdf", ".epub", ".txt", ".mobi"}

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
    "fiverr": {
        "provider": "openai", "model": "gpt-4o-mini",
        "reason": "Gig copy sits next to DALL·E logo generation — staying on OpenAI "
                  "keeps prompt style and image calls on one provider, cheaply.",
    },
    "author": {
        "provider": "anthropic", "model": "claude-fable-5",
        "reason": "Fable 5 is the creative-writing member of the Claude 5 family — "
                  "the closest fit for long-form fiction, character and dialogue work.",
    },
    "manuscript": {
        "provider": "anthropic", "model": "claude-haiku-4-5-20251001",
        "reason": "Sales metrics and todo tracking are light structured tasks — "
                  "Haiku is the fastest and cheapest fit.",
    },
    "music": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Release planning and distribution strategy — broad, practical "
                  "reasoning without needing Opus depth.",
    },
    "webdesign": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Strongest HTML/CSS/JS generation; produces working responsive "
                  "markup in one pass more often than the cheaper models.",
    },
    "manager": {
        "provider": "anthropic", "model": "claude-sonnet-5",
        "reason": "Forge writes real agent source files — code generation quality "
                  "matters more here than cost.",
    },
    "audiobook": {
        "provider": "openai", "model": "tts-1", "voice": "alloy",
        "reason": "Narrator is hard-wired to OpenAI TTS. Alloy is the most neutral, "
                  "even-paced voice — the safest default for hours of narration.",
    },
}

# agent key -> (provider box attribute, model box attribute)
AGENT_SETUP_WIDGETS = {
    "chat":        ("provider_box",             "model_box"),
    "osint":       ("osint_provider_box",       "osint_model_box"),
    "osint_heavy": ("osint_heavy_provider_box", "osint_heavy_model_box"),
    "wifi":        ("wifi_provider_box",        "wifi_model_box"),
    "bug_bounty":  ("bb_provider_box",          "bb_model_box"),
    "fiverr":      ("fiverr_provider_box",      "fiverr_model_box"),
    "author":      ("author_provider_box",      "author_model_box"),
    "manuscript":  ("manuscript_provider_box",  "manuscript_model_box"),
    "music":       ("music_provider_box",       "music_model_box"),
    "webdesign":   ("webdesign_provider_box",   "webdesign_model_box"),
    "manager":     ("manager_provider_box",     "manager_model_box"),
}

# agent key -> the panel's own "reload the model list" method, called after the
# provider is switched programmatically so the model box is populated before we
# try to select the recommended model in it.
AGENT_MODEL_LOADERS = {
    "chat":        "load_provider_models",
    "osint":       "osint_load_models",
    "osint_heavy": "osint_heavy_load_models",
    "wifi":        "wifi_load_models",
    "bug_bounty":  "bb_load_models",
    "fiverr":      "fiverr_load_models",
    "author":      "author_load_models",
    "manuscript":  "manuscript_load_models",
    "music":       "music_load_models",
    "webdesign":   "webdesign_load_models",
    "manager":     "manager_load_models",
}

AGENT_PRETTY_NAMES = {
    "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
    "wifi": "Beacon", "bug_bounty": "Bug Spray",
    "fiverr": "Atelier",
    "author": "Manuscript", "manuscript": "Publisher",
    "music": "Maestro", "webdesign": "Site Builder", "audiobook": "Narrator",
    "manager": "Forge", }


from ui.workers import (
    ChatWorker, SubprocessWorker, ModelPullWorker, FiverrImageWorker, ShortsWorker,
)
from ui.widgets import FlowLayout, CollapsibleSection, Meter
from ui.style import GLOBAL_STYLESHEET
from ui.tooltips import seed_tooltips

class GodAI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("GOD_AI")
        self.resize(1400, 900)
        self.setMinimumSize(1000, 600)
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
            {"agents": ["chat", "writing", "coding", "osint", "audiobook"]},
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
        self.tool_runner = ToolRunner()
        self.audiobook_connector = AudiobookConnector()

        self.registry = Registry()
        self.validator = Validator(self.registry)
        self.run_logger = RunLogger()
        # agent name -> context for an in-flight request (see authorize_request)
        self._pending_requests = {}

        self.manager_agent = ManagerAgent()
        self.agent_factory = AgentFactory(BASE_DIR)
        self.pending_spec: dict | None = None
        self.manager_worker: Optional[ChatWorker] = None
        self.author_worker: Optional[ChatWorker] = None
        self._last_author_response: str = ""
        self._author_is_continuing: bool = False
        self._author_export_done: bool = False
        self.author_pub_worker: Optional[ChatWorker] = None
        self.author_mkt_worker: Optional[ChatWorker] = None
        self.manuscript_worker: Optional[ChatWorker] = None
        self._manuscript_last_data: str = ""
        self.shorts_worker: Optional[ShortsWorker] = None
        self._last_short_path: str = ""
        self.quote_finder_worker: Optional[ChatWorker] = None
        self.calendar_worker: Optional[ChatWorker] = None
        self._calendar_slots: list = []
        self.music_worker: Optional[ChatWorker] = None
        self._last_music_response: str = ""
        self.bug_bounty_worker: Optional[ChatWorker] = None
        self._last_bb_response: str = ""
        self.webdesign_worker: Optional[ChatWorker] = None
        self._last_webdesign_response: str = ""
        self.osint_worker: Optional[ChatWorker] = None
        self.wifi_worker: Optional[ChatWorker] = None
        self.wifi_scan_worker: Optional[SubprocessWorker] = None
        self._last_wifi_response: str = ""
        self._wifi_detected_adapter: dict = {}
        self.osint_heavy_worker: Optional[ChatWorker] = None
        self._last_osint_heavy_response: str = ""
        self._osint_heavy_image_path: str = ""
        self.fiverr_image_worker: Optional[FiverrImageWorker] = None
        self.fiverr_text_worker: Optional[ChatWorker] = None
        self._fiverr_image_paths: list = []
        self._fiverr_current_tab: int = 0

        self.agent_instances = {
            "chat": ChatAgent(),
            "writing": WritingAgent(),
            "coding": CodingAgent(),
            "osint": OSINTAgent(),
            "author": AuthorAgent(),
            "webdesign": WebdesignAgent(),
            "music": MusicAgent(),
            "bug_bounty": BugBountyAgent(),
            "wifi": WiFiAgent(),
            "osint_heavy": OsintHeavyAgent(),
            "fiverr": FiverrAgent(),
            "manuscript": ManuscriptAgent(),
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

        self.audiobook_process: Optional[QProcess] = None

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
        Silently skips attributes that don't exist yet (panel not built)."""
        for attr, text in mapping.items():
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
        approx_output_tokens = max(250, int(approx_input_tokens * 1.2))
        approx_total_tokens = approx_input_tokens + approx_output_tokens

        if backend == "ollama":
            return 0.0, approx_total_tokens

        estimated_cost = self.usage_tracker.calculate_cost_eur(
            backend, model, approx_input_tokens, approx_output_tokens
        )

        return round(estimated_cost, 5), approx_total_tokens

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

        if self.agent_box.currentText() == "audiobook":
            return

        estimated_cost, approx_tokens, backend, model = self.get_current_cost_estimate()

        if backend == "ollama":
            self.live_estimate_label.setText(
                f"Estimated Request Cost: FREE (local execution)\n"
                f"{model} · ~{approx_tokens} tokens"
            )
        elif backend in {"openai", "deepseek", "kimi", "gemini"}:
            self.live_estimate_label.setText(
                f"Estimated Request Cost: ~€{estimated_cost:.2f}\n"
                f"{backend} · {model} · ~{approx_tokens} tokens\n"
                f"⚠ Paid API"
            )
        else:
            self.live_estimate_label.setText(
                f"Estimated Request Cost: ~€{estimated_cost:.2f}\n"
                f"{backend} · {model} · ~{approx_tokens} tokens"
            )

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
        else:
            msg = (
                f"Agent: {self.agent_box.currentText()}\n"
                f"Backend: {backend}\n"
                f"Model: {model}\n"
                f"Approx tokens: {approx_tokens}\n\n"
                f"Estimated cost: ~€{estimated_cost:.2f}\n"
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

        if agent == "audiobook":
            return {
                "mode": "Cloud only",
                "provider": "openai",
                "model": "tts",
                "reason": "Audiobook conversion uses OpenAI TTS only."
            }


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

    def update_recommendation_label(self):
        if not hasattr(self, "recommendation_label"):
            return

        rec = self.get_recommended_setup()

        self.recommendation_label.setText(
            f"Recommendation:\n"
            f"{rec['provider']} · {rec['model']}\n"
            f"{rec['reason']}"
        )
        # Chat's recommendation moves with the tool/command/prompt, so repaint
        # the red dropdown markings whenever the label is refreshed.
        self.refresh_recommendation_marks("chat")

    def maybe_auto_apply_recommendation(self):
        if not hasattr(self, "auto_recommend_checkbox"):
            return

        if not self.auto_recommend_checkbox.isChecked():
            return

        self.apply_recommended_setup()

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

    def models_for_provider(self, provider: str) -> list[str]:
        """Model ids offered by one provider, or [] for an unknown provider.

        Every client falls back to its own KNOWN_MODELS list when the API is
        unreachable, so this only returns empty for a name we don't handle.
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
        except Exception:
            return []

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
            # The audiobook branch reports a pseudo-model that has no combo entry.
            return rec if rec.get("model") != "tts" else None

        return AGENT_RECOMMENDATIONS.get(agent_key)

    def refresh_recommendation_marks(self, agent_key: str) -> None:
        """Re-apply the red marking for one agent's provider and model boxes.

        Called after any model-list reload, since clearing a combo also drops the
        per-item colour data.
        """
        rec = self._recommendation_for(agent_key)
        widgets = AGENT_SETUP_WIDGETS.get(agent_key)
        if not rec or not widgets:
            return

        provider_box = getattr(self, widgets[0], None)
        model_box = getattr(self, widgets[1], None)
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
        widgets = AGENT_SETUP_WIDGETS.get(agent_key)
        if rec and widgets:
            provider_box = getattr(self, widgets[0], None)
            model_box = getattr(self, widgets[1], None)
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
        widgets = AGENT_SETUP_WIDGETS.get(agent_key)
        if not rec or not widgets:
            return

        provider_box = getattr(self, widgets[0], None)
        model_box = getattr(self, widgets[1], None)

        if provider_box is not None:
            idx = provider_box.findText(rec["provider"])
            if idx >= 0:
                provider_box.setCurrentIndex(idx)

        # Populate the model list for the provider we just selected. Setting the
        # provider fires currentTextChanged -> the panel's loader, but only when
        # the value actually changed, so call the loader directly to cover the
        # case where the recommended provider was already selected.
        loader = getattr(self, AGENT_MODEL_LOADERS.get(agent_key, ""), None)
        if callable(loader):
            try:
                loader()
            except Exception as exc:
                self._note_failure("apply recommendation: reload models", exc)

        if model_box is not None:
            idx = self._find_model_index(model_box, rec["model"])
            if idx >= 0:
                model_box.setCurrentIndex(idx)

        self.refresh_recommendation_marks(agent_key)

    def _install_audiobook_recommendation(self) -> None:
        """Narrator has no provider/model choice — OpenAI TTS is hard-wired — so
        the only thing to recommend is the narration voice."""
        rec = AGENT_RECOMMENDATIONS.get("audiobook", {})
        voice_box = getattr(self, "audiobook_voice_box", None)
        voice = rec.get("voice")
        if voice_box is None or not voice:
            return

        tooltip = f"Recommended for Narrator: voice '{voice}'\n{rec['reason']}"
        idx = voice_box.findText(voice)
        if idx >= 0:
            voice_box.setCurrentIndex(idx)
        self._paint_recommended_item(voice_box, idx, tooltip)
        voice_box.setToolTip(tooltip)
        voice_box.currentTextChanged.connect(
            lambda _t: self._mark_deviation(
                voice_box, voice_box.currentText() == voice
            )
        )

    def install_agent_recommendations(self) -> None:
        """Apply every agent's recommended setup once, at startup, and keep the
        red markings in sync as the user changes providers or models later."""
        self._install_audiobook_recommendation()

        for agent_key in AGENT_SETUP_WIDGETS:
            widgets = AGENT_SETUP_WIDGETS[agent_key]
            provider_box = getattr(self, widgets[0], None)
            model_box = getattr(self, widgets[1], None)

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
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(4)

        # Inner scrollable container holds all the agent categories so they never
        # get clipped or vertically squashed when the window is short.
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
            "chat": "💬", "osint": "👹", "osint_heavy": "🔍",
            "audiobook": "🎧", "manager": "🏗",
            "author": "✍️", "webdesign": "🎨",
            "music": "🎵", "wifi": "📡", "fiverr": "💼",
            "bug_bounty": "🐛", "manuscript": "📚",
        }
        labels = {
            "chat": "Chat", "osint": "Trace", "osint_heavy": "Bloodhound",
            "audiobook": "Narrator", "manager": "Forge",
            "author": "Manuscript", "webdesign": "Site Builder",
            "music": "Maestro", "wifi": "Beacon",
            "fiverr": "Atelier", "bug_bounty": "Bug Spray",
            # Without this the sidebar fell back to name.capitalize() and showed a
            # second "Manuscript" entry, colliding with the author agent. Every
            # other surface (header title, registry) calls this one Publisher.
            "manuscript": "Publisher",
        }

        # Every section starts collapsed — launch shows just the category list,
        # and you open the one you want.
        categories = [
            ("General",            ["chat"],                                                False),
            ("Finance & Business", ["fiverr"],                                            False),
            ("Research",           ["osint", "osint_heavy", "wifi"],                       False),
            ("Security",           ["bug_bounty"],                                         False),
            ("Creative",           ["author", "manuscript", "music", "webdesign", "audiobook"],         False),
            ("System",             ["manager"],                                           False),
        ]

        # Minimal sidebar row — clear separation via padding + hover fill
        agent_btn_style = """
            QPushButton#AgentBtn {
                text-align: left;
                padding: 9px 8px 9px 12px;
                background-color: transparent;
                border: none;
                border-left: 2px solid transparent;
                border-radius: 0;
                color: #a8a8a8;
                font-size: 13px;
                font-weight: normal;
            }
            QPushButton#AgentBtn:hover {
                background-color: #161616;
                color: #ffffff;
            }
            QPushButton#AgentBtn:checked {
                background-color: rgba(60, 255, 136, 0.06);
                border-left: 2px solid #3cff88;
                color: #3cff88;
                font-weight: 600;
            }
        """

        self.agent_buttons = {}
        for title, agent_names, expanded in categories:
            section = CollapsibleSection(title, expanded=expanded)
            for name in agent_names:
                btn = QPushButton(f"{icons.get(name, '⚙️')}  {labels.get(name, name.capitalize())}")
                btn.setObjectName("AgentBtn")
                btn.setStyleSheet(agent_btn_style)
                btn.setCheckable(True)
                btn.setMinimumHeight(40)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                btn.clicked.connect(lambda checked, n=name: self.select_agent(n))
                section.addWidget(btn)
                self.agent_buttons[name] = btn
            agents_layout.addWidget(section)

        agents_layout.addStretch()
        agents_scroll.setWidget(agents_container)
        left_layout.addWidget(agents_scroll, 1)

        # ── Divider ──────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #242424; background-color: #242424; max-height: 1px;")
        left_layout.addWidget(divider)

        saved_header = QLabel("  SAVED CHATS")
        saved_header.setStyleSheet(
            "color: #707070; font-weight: bold; font-size: 10px; "
            "letter-spacing: 1.5px; padding: 8px 0 4px 8px; "
            "background: transparent;"
        )
        left_layout.addWidget(saved_header)

        # Narrow the list to one agent. Populated from the chats that exist, so
        # it only ever offers agents you have actually used.
        self.history_agent_filter = QComboBox()
        self.history_agent_filter.addItem(ALL_AGENTS_FILTER)
        self.history_agent_filter.currentTextChanged.connect(self.load_history_list)
        left_layout.addWidget(self.history_agent_filter)

        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search saved chats...")
        self.history_search.textChanged.connect(self.load_history_list)
        left_layout.addWidget(self.history_search)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.open_selected_chat)
        # Double-click renames: chat_title_from_data already prefers a stored
        # "title" over the truncated first prompt, it was just never written.
        self.history_list.itemDoubleClicked.connect(self.rename_selected_chat)
        # Keep the saved-chats list bounded so the agents area always has room
        self.history_list.setMinimumHeight(120)
        self.history_list.setMaximumHeight(200)
        left_layout.addWidget(self.history_list)

        self.delete_chat_btn = QPushButton("🗑 Delete Selected")
        self.delete_chat_btn.clicked.connect(self.delete_selected_chat)
        left_layout.addWidget(self.delete_chat_btn)

        self.new_chat_btn = QPushButton("✳️ New Chat")
        self.new_chat_btn.clicked.connect(self.new_chat)
        left_layout.addWidget(self.new_chat_btn)

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
        center_layout.setContentsMargins(20, 16, 20, 16)
        center_layout.setSpacing(12)

        # ── Agent header bar: big accent title + status pill ─────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.agent_title_label = QLabel("CHAT")
        self.agent_title_label.setObjectName("AgentTitle")
        header_row.addWidget(self.agent_title_label)

        header_row.addStretch()

        self.agent_docs_btn = QPushButton("📖  Docs")
        self.agent_docs_btn.setObjectName("ChipBtn")
        self.agent_docs_btn.setToolTip("Open the documentation for the current agent.")
        self.agent_docs_btn.clicked.connect(self.show_agent_docs)
        header_row.addWidget(self.agent_docs_btn)

        self.tooltips_toggle_btn = QPushButton("💡 Tooltips: On")
        self.tooltips_toggle_btn.setObjectName("ChipBtn")
        self.tooltips_toggle_btn.setCheckable(True)
        self.tooltips_toggle_btn.setChecked(True)
        self.tooltips_toggle_btn.setToolTip(
            "Toggle hover tooltips across the entire app. Tooltips explain what each control does."
        )
        self.tooltips_toggle_btn.clicked.connect(self._toggle_tooltips)
        header_row.addWidget(self.tooltips_toggle_btn)

        self.agent_status_pill = QLabel("●  READY")
        self.agent_status_pill.setObjectName("StatusPill")
        header_row.addWidget(self.agent_status_pill)

        center_layout.addLayout(header_row)

        # ── Subtitle: short function description under the title ────────
        self.agent_subtitle_label = QLabel("")
        self.agent_subtitle_label.setObjectName("AgentSubtitle")
        self.agent_subtitle_label.setWordWrap(True)
        center_layout.addWidget(self.agent_subtitle_label)

        self.normal_panel = QWidget()
        normal_layout = QVBoxLayout(self.normal_panel)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(10)

        # Row 1: command only
        top_row_1 = QHBoxLayout()

        self.agent_box = QComboBox()
        agent_items = self.agents_config.get("agents", [])
        for extra in ("manager", "author"):
            if extra not in agent_items:
                agent_items = list(agent_items) + [extra]
        self.agent_box.addItems(agent_items)
        self.agent_box.hide()

        self.tool_label = QLabel("Tool:")
        top_row_1.addWidget(self.tool_label)

        self.tool_box = QComboBox()
        self.tool_box.addItems(self.tool_prompts.keys())

        self.tool_box.setMinimumWidth(140)
        top_row_1.addWidget(self.tool_box)

        self.command_label = QLabel("Command:")
        top_row_1.addWidget(self.command_label)

        self.command_box = QComboBox()
        self.command_box.addItems(self.commands.keys())
        self.command_box.setMinimumWidth(180)
        top_row_1.addWidget(self.command_box)

        top_row_1.addStretch()
        normal_layout.addLayout(top_row_1)

        # Row 2: provider, model, model tools
        top_row_2_container = QWidget()
        top_row_2 = FlowLayout(top_row_2_container, spacing=6)

        self.provider_box = QComboBox()
        self.provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.provider_box.setMinimumWidth(120)
        top_row_2.addWidget(QLabel("Provider:"))
        top_row_2.addWidget(self.provider_box)

        self.model_box = QComboBox()
        self.model_box.setMinimumWidth(180)
        top_row_2.addWidget(QLabel("Model:"))
        top_row_2.addWidget(self.model_box)

        self.refresh_models_btn = QPushButton("Refresh Models")


        self.refresh_models_btn.setObjectName("ChipBtn")
        self.refresh_models_btn.clicked.connect(self.load_provider_models)
        top_row_2.addWidget(self.refresh_models_btn)

        # Offers a one-click pull of Meta's Muse Glimmer. Hidden once the model
        # is installed, since it is then just another entry in the model box.
        self.get_muse_btn = QPushButton("⬇ Get Muse Glimmer")
        self.get_muse_btn.setObjectName("ChipBtn")
        self.get_muse_btn.clicked.connect(self.pull_muse_glimmer)
        top_row_2.addWidget(self.get_muse_btn)

        self.model_guide_btn = QPushButton("Model Guide")


        self.model_guide_btn.setObjectName("ChipBtn")
        self.model_guide_btn.clicked.connect(self.show_model_guide)
        top_row_2.addWidget(self.model_guide_btn)

        self.docs_btn = QPushButton("Docs")


        self.docs_btn.setObjectName("ChipBtn")
        self.docs_btn.clicked.connect(self.show_docs)
        top_row_2.addWidget(self.docs_btn)

        normal_layout.addWidget(top_row_2_container)
        
        self.model_box.currentTextChanged.connect(self.save_provider_model_preference)

        # Row 3: execution mode and API permissions — wraps when the pane narrows.
        top_row_3_container = QWidget()
        top_row_3 = FlowLayout(top_row_3_container, spacing=6)

        self.execution_mode_box = QComboBox()
        self.execution_mode_box.addItems(["Local only", "Hybrid allowed", "Cloud only"])
        self.execution_mode_box.setMinimumWidth(120)
        top_row_3.addWidget(QLabel("Mode:"))
        top_row_3.addWidget(self.execution_mode_box)

        self.allow_openai_checkbox = QCheckBox("OpenAI")
        self.allow_openai_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_openai_checkbox)

        self.allow_deepseek_checkbox = QCheckBox("DeepSeek")
        self.allow_deepseek_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_deepseek_checkbox)

        self.allow_kimi_checkbox = QCheckBox("Kimi")
        self.allow_kimi_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_kimi_checkbox)

        self.allow_gemini_checkbox = QCheckBox("Gemini")
        self.allow_gemini_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_gemini_checkbox)

        self.allow_anthropic_checkbox = QCheckBox("Anthropic")
        self.allow_anthropic_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_anthropic_checkbox)

        self.allow_qwen_checkbox = QCheckBox("Qwen")
        self.allow_qwen_checkbox.setChecked(False)
        top_row_3.addWidget(self.allow_qwen_checkbox)

        normal_layout.addWidget(top_row_3_container)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("Type your message here...")
        self.input_box.setMinimumHeight(190)
        normal_layout.addWidget(self.input_box)

        # Single action row — wraps instead of truncating when the pane narrows.
        actions_container = QWidget()
        actions_row = FlowLayout(actions_container, spacing=6)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedHeight(34)
        self.send_btn.setObjectName("PrimaryAction")
        self.send_btn.clicked.connect(self.send_prompt)
        actions_row.addWidget(self.send_btn)

        self.stop_chat_btn = QPushButton("Stop")
        self.stop_chat_btn.setFixedHeight(34)
        self.stop_chat_btn.setEnabled(False)
        self.stop_chat_btn.setObjectName("DangerAction")
        self.stop_chat_btn.clicked.connect(self.stop_current_task)
        actions_row.addWidget(self.stop_chat_btn)

        self.auto_route_btn = QPushButton("Auto Route")
        self.auto_route_btn.setFixedHeight(32)
        self.auto_route_btn.clicked.connect(self.auto_route_agent)
        actions_row.addWidget(self.auto_route_btn)

        self.recommend_setup_btn = QPushButton("Use Recommended")
        self.recommend_setup_btn.setFixedHeight(32)
        self.recommend_setup_btn.clicked.connect(self.apply_recommended_setup)
        actions_row.addWidget(self.recommend_setup_btn)

        # "Auto-Apply" modifies "Use Recommended", so it follows it directly. Its
        # own trailing padding provides the gap before the cost/export buttons —
        # a spacer item would wrap as if it were a control.
        self.auto_recommend_checkbox = QCheckBox("Auto-Apply")
        self.auto_recommend_checkbox.setChecked(False)
        actions_row.addWidget(self.auto_recommend_checkbox)

        self.estimate_btn = QPushButton("Estimate Cost")
        self.estimate_btn.setFixedHeight(32)
        self.estimate_btn.clicked.connect(self.show_cost_estimate_popup)
        actions_row.addWidget(self.estimate_btn)

        self.export_btn = QPushButton("Export Report")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self.export_report)
        actions_row.addWidget(self.export_btn)

        normal_layout.addWidget(actions_container)

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

        self.build_audiobook_panel()
        center_layout.addWidget(self.audiobook_panel)

        self.build_manager_panel()
        center_layout.addWidget(self.manager_panel)

        self.build_author_panel()
        center_layout.addWidget(self.author_panel)

        self.build_manuscript_panel()
        center_layout.addWidget(self.manuscript_panel)

        self.build_music_panel()
        center_layout.addWidget(self.music_panel)

        self.build_osint_panel()
        center_layout.addWidget(self.osint_panel)

        self.build_osint_heavy_panel()
        center_layout.addWidget(self.osint_heavy_panel)

        self.build_webdesign_panel()
        center_layout.addWidget(self.webdesign_panel)

        self.build_wifi_panel()
        center_layout.addWidget(self.wifi_panel)

        self.build_fiverr_panel()
        center_layout.addWidget(self.fiverr_panel)

        self.build_bug_bounty_panel()
        center_layout.addWidget(self.bug_bounty_panel)

        self.output_label = QLabel("OUTPUT")
        self.output_label.setStyleSheet(
            "font-size: 10px; font-weight: bold; color: #707070; "
            "letter-spacing: 1.5px; padding: 6px 0 2px 0; background: transparent;"
        )
        self.output_label.hide()
        center_layout.addWidget(self.output_label)

        self.output_box = QTextEdit()
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
    
    def build_audiobook_panel(self):
        self.audiobook_panel = QWidget()
        panel_layout = QVBoxLayout(self.audiobook_panel)
        panel_layout.setContentsMargins(0, 4, 0, 0)
        panel_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        books_group = QGroupBox("Select a Book to Convert")
        books_layout = QVBoxLayout(books_group)
        books_layout.setSpacing(4)

        self.audiobook_book_list = QListWidget()
        self.audiobook_book_list.setMinimumHeight(150)
        self.audiobook_book_list.currentItemChanged.connect(lambda *_: self.estimate_audiobook_cost_from_selection())
        books_layout.addWidget(self.audiobook_book_list)

        books_btn_row = QHBoxLayout()
        books_btn_row.setSpacing(6)

        self.audiobook_refresh_btn = QPushButton("🔄 Refresh List")
        self.audiobook_refresh_btn.clicked.connect(self.refresh_audiobook_books)
        books_btn_row.addWidget(self.audiobook_refresh_btn)

        books_btn_row.addStretch()

        self.stop_btn = QPushButton("⛔ Stop")
        self.stop_btn.clicked.connect(self.stop_current_task)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        books_btn_row.addWidget(self.stop_btn)

        self.audiobook_start_btn = QPushButton("▶ Start")
        self.audiobook_start_btn.clicked.connect(self.start_selected_audiobook_book)
        self.audiobook_start_btn.setMinimumWidth(130)
        self.audiobook_start_btn.setObjectName("PrimaryAction")
        books_btn_row.addWidget(self.audiobook_start_btn)
        books_layout.addLayout(books_btn_row)

        settings_group = QGroupBox("Conversion Settings")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setVerticalSpacing(4)
        settings_layout.setHorizontalSpacing(6)

        settings_layout.addWidget(QLabel("Input Folder:"), 0, 0, 1, 2)
        self.audiobook_input_path = QLineEdit()
        self.audiobook_input_path.setReadOnly(True)
        settings_layout.addWidget(self.audiobook_input_path, 1, 0)

        self.audiobook_open_input_btn = QPushButton("Open")
        self.audiobook_open_input_btn.clicked.connect(self.open_audiobook_input_folder)
        settings_layout.addWidget(self.audiobook_open_input_btn, 1, 1)

        settings_layout.addWidget(QLabel("Output Folder:"), 2, 0, 1, 2)
        self.audiobook_output_path = QLineEdit()
        self.audiobook_output_path.setReadOnly(True)
        settings_layout.addWidget(self.audiobook_output_path, 3, 0)

        self.audiobook_change_output_btn = QPushButton("Change")
        self.audiobook_change_output_btn.clicked.connect(self.change_audiobook_output_folder)
        settings_layout.addWidget(self.audiobook_change_output_btn, 3, 1)

        voice_chunk_row = QHBoxLayout()
        voice_chunk_row.setSpacing(8)
        voice_chunk_row.addWidget(QLabel("Voice:"))
        self.audiobook_voice_box = QComboBox()
        self.audiobook_voice_box.addItems(["alloy", "verse", "aria", "coral", "sage"])
        voice_chunk_row.addWidget(self.audiobook_voice_box)
        voice_chunk_row.addWidget(QLabel("Chunk Tokens:"))
        self.audiobook_chunk_input = QLineEdit("1400")
        self.audiobook_chunk_input.setMaximumWidth(80)
        voice_chunk_row.addWidget(self.audiobook_chunk_input)
        settings_layout.addLayout(voice_chunk_row, 4, 0, 1, 2)

        self.audiobook_cost_label = QLabel("Estimated cost: not calculated")
        self.audiobook_cost_label.setWordWrap(True)
        settings_layout.addWidget(self.audiobook_cost_label, 5, 0, 1, 2)

        top_row.addWidget(books_group, 1)
        top_row.addWidget(settings_group, 1)
        panel_layout.addLayout(top_row)

        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(4)

        self.tool_progress = QProgressBar()
        self.tool_progress.setMinimum(0)
        self.tool_progress.setMaximum(100)
        self.tool_progress.setValue(0)
        self.tool_progress.setTextVisible(True)
        progress_layout.addWidget(self.tool_progress)

        self.audiobook_status_label = QLabel("[Ready] Select a book and click Start.")
        progress_layout.addWidget(self.audiobook_status_label)

        panel_layout.addWidget(progress_group)
        self.audiobook_panel.hide()

    def build_manager_panel(self):
        self.manager_panel = QWidget()
        self.manager_panel.setObjectName("ManagerPanel")
        layout = QVBoxLayout(self.manager_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Idea input ──────────────────────────────────────────────
        idea_group = QGroupBox("Describe Your Agent Idea")
        idea_group.setObjectName("ManagerIdeaBox")
        idea_layout = QVBoxLayout(idea_group)

        self.manager_idea_input = QTextEdit()
        self.manager_idea_input.setPlaceholderText(
            "Example: A cybersecurity agent that helps analyse logs, detect anomalies, "
            "and suggest mitigations. Should prefer local models for privacy."
        )
        self.manager_idea_input.setMinimumHeight(100)
        self.manager_idea_input.setMaximumHeight(160)
        idea_layout.addWidget(self.manager_idea_input)

        idea_btn_row = QHBoxLayout()

        self.manager_provider_box = QComboBox()
        self.manager_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.manager_provider_box.setCurrentText("deepseek")
        idea_btn_row.addWidget(QLabel("Provider:"))
        idea_btn_row.addWidget(self.manager_provider_box)

        self.manager_model_box = QComboBox()
        self.manager_model_box.setMinimumWidth(200)
        idea_btn_row.addWidget(QLabel("Model:"))
        idea_btn_row.addWidget(self.manager_model_box)

        idea_btn_row.addStretch()

        self.manager_analyze_btn = QPushButton("Analyze Idea")
        self.manager_analyze_btn.setMinimumWidth(140)
        self.manager_analyze_btn.setObjectName("PrimaryAction")
        self.manager_analyze_btn.clicked.connect(self.manager_analyze_idea)
        idea_btn_row.addWidget(self.manager_analyze_btn)

        self.manager_clear_btn = QPushButton("Clear")
        self.manager_clear_btn.clicked.connect(self.manager_clear)
        idea_btn_row.addWidget(self.manager_clear_btn)

        idea_layout.addLayout(idea_btn_row)
        layout.addWidget(idea_group)

        # ── Generated spec ───────────────────────────────────────────
        spec_group = QGroupBox("Generated Spec (review before approving)")
        spec_group.setObjectName("ManagerSpecBox")
        spec_layout = QVBoxLayout(spec_group)

        self.manager_spec_display = QTextEdit()
        self.manager_spec_display.setReadOnly(True)
        self.manager_spec_display.setMinimumHeight(180)
        self.manager_spec_display.setPlaceholderText("Spec will appear here after analysis...")
        self.manager_spec_display.setStyleSheet("font-family: monospace; font-size: 12px;")
        spec_layout.addWidget(self.manager_spec_display)

        approve_row = QHBoxLayout()

        self.manager_approve_btn = QPushButton("Approve & Create Agent")
        self.manager_approve_btn.setEnabled(False)
        self.manager_approve_btn.setMinimumWidth(200)
        self.manager_approve_btn.setObjectName("PrimaryAction")
        self.manager_approve_btn.clicked.connect(self.manager_approve_spec)
        approve_row.addWidget(self.manager_approve_btn)

        self.manager_reject_btn = QPushButton("Reject / Clear Spec")
        self.manager_reject_btn.setEnabled(False)
        self.manager_reject_btn.clicked.connect(self.manager_reject_spec)
        approve_row.addWidget(self.manager_reject_btn)

        approve_row.addStretch()
        spec_layout.addLayout(approve_row)
        layout.addWidget(spec_group)

        # ── Creation log ─────────────────────────────────────────────
        log_group = QGroupBox("Creation Log")
        log_group.setObjectName("ManagerLogBox")
        log_layout = QVBoxLayout(log_group)

        self.manager_log = QTextEdit()
        self.manager_log.setReadOnly(True)
        self.manager_log.setMinimumHeight(100)
        self.manager_log.setStyleSheet("font-family: monospace; font-size: 12px;")
        log_layout.addWidget(self.manager_log)
        layout.addWidget(log_group)

        self.manager_panel.hide()

        self.manager_provider_box.currentTextChanged.connect(self.manager_load_models)
        self.manager_load_models()


    def build_author_panel(self):
        self.author_panel = QWidget()
        self.author_panel.setObjectName("AuthorPanel")
        layout = QVBoxLayout(self.author_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Project bar ──────────────────────────────────────────────────────
        project_bar = QWidget()
        project_bar.setObjectName("AuthorProjectBar")
        pb_layout = FlowLayout(project_bar, spacing=8)
        pb_layout.setContentsMargins(4, 4, 4, 4)
        pb_layout.setSpacing(8)

        pb_layout.addWidget(QLabel("Title:"))
        self.author_title_input = QLineEdit()
        self.author_title_input.setPlaceholderText("Project title…")
        self.author_title_input.setMinimumWidth(160)
        pb_layout.addWidget(self.author_title_input)

        pb_layout.addWidget(QLabel("Author:"))
        self.author_name_input = QLineEdit()
        self.author_name_input.setPlaceholderText("Pen name…")
        pb_layout.addWidget(self.author_name_input)

        pb_layout.addWidget(QLabel("Type:"))
        self.author_content_type_box = QComboBox()
        self.author_content_type_box.addItems(["Fiction", "Non-Fiction"])
        self.author_content_type_box.currentTextChanged.connect(self._author_on_content_type_changed)
        pb_layout.addWidget(self.author_content_type_box)

        pb_layout.addWidget(QLabel("Genre:"))
        self.author_genre_box = QComboBox()
        self.author_genre_box.addItems([
            "Literary Fiction", "Thriller", "Fantasy", "Sci-Fi", "Horror",
            "Romance", "Historical", "Mystery", "Short Story", "Screenplay",
            "Poetry", "Blog / Essay", "Other",
        ])
        pb_layout.addWidget(self.author_genre_box)

        pb_layout.addWidget(QLabel("Tone:"))
        self.author_tone_box = QComboBox()
        self.author_tone_box.addItems([
            "Neutral", "Dark", "Humorous", "Lyrical", "Tense", "Romantic",
            "Gritty", "Whimsical", "Philosophical", "Commercial",
        ])
        pb_layout.addWidget(self.author_tone_box)

        pb_layout.addWidget(QLabel("POV:"))
        self.author_pov_box = QComboBox()
        self.author_pov_box.addItems([
            "Third Person Limited", "First Person",
            "Third Person Omniscient", "Second Person",
        ])
        pb_layout.addWidget(self.author_pov_box)

        layout.addWidget(project_bar)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet("color: #444;")
        layout.addWidget(divider)

        self.author_next_step_label = QLabel("")
        self.author_next_step_label.setWordWrap(True)
        self.author_next_step_label.setStyleSheet(
            "background: rgba(60,255,136,0.08); border: 1px solid rgba(60,255,136,0.25); "
            "border-radius: 6px; padding: 8px 10px; color: #3cff88; font-size: 12px;"
        )
        layout.addWidget(self.author_next_step_label)

        # ── Book Profile (collapsed by default — persisted, injected into every mode) ──
        profile_section = CollapsibleSection("📖  Book Profile", expanded=False)

        profile_row1 = QWidget()
        pr1 = QHBoxLayout(profile_row1)
        pr1.setContentsMargins(4, 0, 4, 0)
        pr1.setSpacing(8)
        pr1.addWidget(QLabel("Hook:"))
        self.author_profile_hook_input = QLineEdit()
        self.author_profile_hook_input.setPlaceholderText("One-sentence pitch — the core promise of the book…")
        pr1.addWidget(self.author_profile_hook_input)
        profile_section.addWidget(profile_row1)

        profile_row2 = QWidget()
        pr2 = QHBoxLayout(profile_row2)
        pr2.setContentsMargins(4, 0, 4, 0)
        pr2.setSpacing(8)
        pr2.addWidget(QLabel("Target reader:"))
        self.author_profile_reader_input = QLineEdit()
        self.author_profile_reader_input.setPlaceholderText("e.g. Women 25-40 navigating modern dating apps")
        pr2.addWidget(self.author_profile_reader_input)
        profile_section.addWidget(profile_row2)

        profile_row3 = QWidget()
        pr3 = QHBoxLayout(profile_row3)
        pr3.setContentsMargins(4, 0, 4, 0)
        pr3.setSpacing(8)
        pr3.addWidget(QLabel("Comp titles:"))
        self.author_profile_comps_input = QLineEdit()
        self.author_profile_comps_input.setPlaceholderText("e.g. For readers of [Title A] and [Title B]")
        pr3.addWidget(self.author_profile_comps_input)
        profile_section.addWidget(profile_row3)

        profile_row4 = QWidget()
        pr4 = QHBoxLayout(profile_row4)
        pr4.setContentsMargins(4, 0, 4, 0)
        pr4.setSpacing(8)
        pr4.addWidget(QLabel("Publishing path:"))
        self.author_profile_path_box = QComboBox()
        self.author_profile_path_box.addItems(["Undecided", "Self-Publishing (KDP)", "Traditional"])
        pr4.addWidget(self.author_profile_path_box)
        pr4.addStretch()
        self.author_profile_save_btn = QPushButton("💾  Save Profile")
        self.author_profile_save_btn.clicked.connect(self.author_save_profile)
        pr4.addWidget(self.author_profile_save_btn)
        profile_section.addWidget(profile_row4)

        layout.addWidget(profile_section)

        # ── Main workspace ────────────────────────────────────────────────────
        workspace_splitter = QSplitter(Qt.Horizontal)

        # Left: editable manuscript tabs
        self.author_tabs = QTabWidget()

        self.author_draft_box = QTextEdit()
        self.author_draft_box.setPlaceholderText(
            "Your draft appears here. You can type and edit directly alongside the AI."
        )
        self.author_tabs.addTab(self.author_draft_box, "✍️  Draft")

        self.author_outline_box = QTextEdit()
        self.author_outline_box.setPlaceholderText("Chapter and scene outline…")
        self.author_tabs.addTab(self.author_outline_box, "📋  Outline")

        self.author_characters_box = QTextEdit()
        self.author_characters_box.setPlaceholderText("Character profiles, arcs, relationships…")
        self.author_tabs.addTab(self.author_characters_box, "👤  Characters")

        self.author_world_box = QTextEdit()
        self.author_world_box.setPlaceholderText("World-building notes, lore, setting, rules…")
        self.author_tabs.addTab(self.author_world_box, "🌍  World Notes")

        self.author_chapters_tab = QWidget()
        ct_layout = QVBoxLayout(self.author_chapters_tab)
        ct_layout.setContentsMargins(6, 6, 6, 6)
        ct_layout.setSpacing(6)

        self.author_chapters_stats_label = QLabel("No chapters detected yet.")
        self.author_chapters_stats_label.setStyleSheet("font-size: 12px; color: #888;")
        ct_layout.addWidget(self.author_chapters_stats_label)

        self.author_chapters_list = QListWidget()
        self.author_chapters_list.itemDoubleClicked.connect(self._author_jump_to_chapter)
        ct_layout.addWidget(self.author_chapters_list, 1)

        author_chapters_refresh_btn = QPushButton("🔄  Refresh Chapters")
        author_chapters_refresh_btn.clicked.connect(self._author_refresh_chapters)
        ct_layout.addWidget(author_chapters_refresh_btn)

        self._author_chapter_offsets: list = []
        self.author_tabs.addTab(self.author_chapters_tab, "📑  Chapters")
        self.author_tabs.currentChanged.connect(self._author_on_tab_changed)

        workspace_splitter.addWidget(self.author_tabs)

        # Right: control sidebar
        sidebar = QWidget()
        sidebar.setObjectName("AuthorSidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(270)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(8, 4, 4, 4)
        sb.setSpacing(6)

        sb.addWidget(QLabel("Direction:"))
        self.author_direction_input = QTextEdit()
        self.author_direction_input.setPlaceholderText(
            "Describe what to write, the next scene, or give revision instructions…"
        )
        self.author_direction_input.setFixedHeight(90)
        sb.addWidget(self.author_direction_input)

        sb.addWidget(QLabel("Task:"))
        self.author_task_box = QComboBox()
        # Populated by _author_on_content_type_changed() once the panel finishes building —
        # the task list depends on the Type combo (Fiction/Non-Fiction) in the Project Bar.
        sb.addWidget(self.author_task_box)

        sb.addWidget(QLabel("Provider:"))
        self.author_provider_box = QComboBox()
        self.author_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.author_provider_box.setCurrentText("anthropic")
        sb.addWidget(self.author_provider_box)

        sb.addWidget(QLabel("Model:"))
        self.author_model_box = QComboBox()
        sb.addWidget(self.author_model_box)

        self.author_write_btn = QPushButton("✍️  Write")
        self.author_write_btn.setMinimumHeight(34)
        self.author_write_btn.setStyleSheet(
            "QPushButton { background-color: #1a1a4d; border: 1px solid #7c7cff;"
            " font-weight: bold; color: #c0c0ff; }"
            "QPushButton:hover { background-color: #22227a; }"
        )
        self.author_write_btn.clicked.connect(self.author_write)
        sb.addWidget(self.author_write_btn)

        self.author_continue_btn = QPushButton("▶  Continue")
        self.author_continue_btn.setMinimumHeight(34)
        self.author_continue_btn.setStyleSheet(
            "QPushButton { background-color: #1a2d1a; border: 1px solid #3cff88;"
            " font-weight: bold; color: #3cff88; }"
            "QPushButton:hover { background-color: #1e3d1e; }"
        )
        self.author_continue_btn.clicked.connect(self.author_continue)
        sb.addWidget(self.author_continue_btn)

        self.author_stop_btn = QPushButton("⬛  Stop")
        self.author_stop_btn.setEnabled(False)
        self.author_stop_btn.setMinimumHeight(34)
        self.author_stop_btn.setStyleSheet(
            "QPushButton { background-color: #2b1010; border: 1px solid #ff4444;"
            " color: #ff5555; font-weight: bold; }"
            "QPushButton:hover { background-color: #3d1515; }"
        )
        self.author_stop_btn.clicked.connect(self.author_stop)
        sb.addWidget(self.author_stop_btn)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #444;")
        sb.addWidget(sep1)

        word_group = QGroupBox("Words")
        word_group.setObjectName("AuthorWordGroup")
        wg_layout = QVBoxLayout(word_group)
        wg_layout.setContentsMargins(4, 4, 4, 4)
        self.author_word_count_label = QLabel("0")
        self.author_word_count_label.setAlignment(Qt.AlignCenter)
        self.author_word_count_label.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: #f0c040;"
        )
        wg_layout.addWidget(self.author_word_count_label)
        sb.addWidget(word_group)

        scene_group = QGroupBox("Scenes / Chapters")
        scene_group.setObjectName("AuthorSceneGroup")
        sg_layout = QVBoxLayout(scene_group)
        sg_layout.setContentsMargins(4, 4, 4, 4)
        self.author_scene_count_label = QLabel("0")
        self.author_scene_count_label.setAlignment(Qt.AlignCenter)
        self.author_scene_count_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #a0a0ff;"
        )
        sg_layout.addWidget(self.author_scene_count_label)
        sb.addWidget(scene_group)

        sb.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #444;")
        sb.addWidget(sep2)

        self.author_save_btn = QPushButton("💾  Save Draft")
        self.author_save_btn.setEnabled(False)
        self.author_save_btn.clicked.connect(self.author_save)
        sb.addWidget(self.author_save_btn)

        sb.addWidget(QLabel("Author name (for export):"))
        self.author_export_author_input = QLineEdit()
        self.author_export_author_input.setPlaceholderText("e.g. Celeste Morgan")
        sb.addWidget(self.author_export_author_input)

        export_row = QHBoxLayout()
        self.author_export_format_box = QComboBox()
        self.author_export_format_box.addItems(["EPUB", "DOCX", "PDF"])
        export_row.addWidget(self.author_export_format_box)
        self.author_export_btn = QPushButton("📤  Export Book")
        self.author_export_btn.clicked.connect(self.author_export_book)
        export_row.addWidget(self.author_export_btn)
        sb.addLayout(export_row)

        self.author_clear_btn = QPushButton("Clear All")
        self.author_clear_btn.clicked.connect(self.author_clear)
        sb.addWidget(self.author_clear_btn)

        workspace_splitter.addWidget(sidebar)
        workspace_splitter.setSizes([760, 240])

        # ── Mode toggle row: Write | Publish & Market ────────────────────────
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)

        self.author_mode_write_btn = QPushButton("✍️  Write")
        self.author_mode_write_btn.setCheckable(True)
        self.author_mode_write_btn.setChecked(True)
        self.author_mode_write_btn.setMinimumHeight(32)
        self.author_mode_write_btn.setStyleSheet(
            "QPushButton { background-color: #1a1a4d; border: 1px solid #7c7cff;"
            " font-weight: bold; color: #c0c0ff; border-radius: 0; }"
            "QPushButton:checked { background-color: #22227a; border: 2px solid #a0a0ff; }"
            "QPushButton:hover { background-color: #22227a; }"
        )
        self.author_mode_write_btn.clicked.connect(lambda: self._author_set_mode("write"))
        mode_row.addWidget(self.author_mode_write_btn)

        self.author_mode_pubmkt_btn = QPushButton("📣  Publish & Market")
        self.author_mode_pubmkt_btn.setCheckable(True)
        self.author_mode_pubmkt_btn.setMinimumHeight(32)
        self.author_mode_pubmkt_btn.setStyleSheet(
            "QPushButton { background-color: #2d1a0e; border: 1px solid #ff9944;"
            " font-weight: bold; color: #ffb366; border-radius: 0; }"
            "QPushButton:checked { background-color: #3d2210; border: 2px solid #ffa855; }"
            "QPushButton:hover { background-color: #3d2210; }"
        )
        self.author_mode_pubmkt_btn.clicked.connect(lambda: self._author_set_mode("pubmkt"))
        mode_row.addWidget(self.author_mode_pubmkt_btn)

        layout.addLayout(mode_row)

        # ── Content stack (Write / Publish & Market) ─────────────────────────
        self.author_content_stack = QStackedWidget()
        self.author_content_stack.addWidget(workspace_splitter)   # page 0: write

        # ── Publish & Market composite widget ────────────────────────────────
        pubmkt_widget = QWidget()
        pm_layout = QVBoxLayout(pubmkt_widget)
        pm_layout.setContentsMargins(0, 4, 0, 0)
        pm_layout.setSpacing(6)

        # Sub-mode toggle: Publish | Market
        sub_row = QHBoxLayout()
        sub_row.setSpacing(0)

        self.author_sub_publish_btn = QPushButton("📄  Publish")
        self.author_sub_publish_btn.setCheckable(True)
        self.author_sub_publish_btn.setChecked(True)
        self.author_sub_publish_btn.setMinimumHeight(28)
        self.author_sub_publish_btn.setStyleSheet(
            "QPushButton { background-color: #1a2d1a; border: 1px solid #3cff88;"
            " font-weight: bold; color: #3cff88; border-radius: 0; }"
            "QPushButton:checked { background-color: #1e3d1e; border: 2px solid #3cff88; }"
            "QPushButton:hover { background-color: #1e3d1e; }"
        )
        self.author_sub_publish_btn.clicked.connect(lambda: self._author_set_sub_mode("publish"))
        sub_row.addWidget(self.author_sub_publish_btn)

        self.author_sub_market_btn = QPushButton("📢  Market")
        self.author_sub_market_btn.setCheckable(True)
        self.author_sub_market_btn.setMinimumHeight(28)
        self.author_sub_market_btn.setStyleSheet(
            "QPushButton { background-color: #2d1a0e; border: 1px solid #ff9944;"
            " font-weight: bold; color: #ffb366; border-radius: 0; }"
            "QPushButton:checked { background-color: #3d2210; border: 2px solid #ffa855; }"
            "QPushButton:hover { background-color: #3d2210; }"
        )
        self.author_sub_market_btn.clicked.connect(lambda: self._author_set_sub_mode("market"))
        sub_row.addWidget(self.author_sub_market_btn)

        pm_layout.addLayout(sub_row)

        self.author_sub_stack = QStackedWidget()

        # ── Publish page ──────────────────────────────────────────────────────
        publish_page = QWidget()
        pub_outer = QHBoxLayout(publish_page)
        pub_outer.setContentsMargins(0, 0, 0, 0)
        pub_outer.setSpacing(8)

        self.author_pub_output = QTextEdit()
        self.author_pub_output.setPlaceholderText(
            "Generated publishing document appears here. Fully editable."
        )
        pub_outer.addWidget(self.author_pub_output, 1)

        pub_ctrl = QWidget()
        pub_ctrl.setObjectName("AuthorPubCtrl")
        pub_ctrl.setMinimumWidth(210)
        pub_ctrl.setMaximumWidth(270)
        pc = QVBoxLayout(pub_ctrl)
        pc.setContentsMargins(6, 0, 0, 0)
        pc.setSpacing(5)

        pc.addWidget(QLabel("Output Type:"))
        self.author_pub_type_box = QComboBox()
        self.author_pub_type_box.addItems([
            "Synopsis — 1 Page", "Synopsis — 3 Page", "Query Letter",
            "Book Proposal", "Back-Cover Blurb", "Author Bio", "Chapter Breakdown",
        ])
        pc.addWidget(self.author_pub_type_box)

        pc.addWidget(QLabel("Word Count Target:"))
        self.author_pub_wordcount_input = QLineEdit()
        self.author_pub_wordcount_input.setPlaceholderText("e.g. 80,000")
        pc.addWidget(self.author_pub_wordcount_input)

        pc.addWidget(QLabel("Comp Titles:"))
        self.author_pub_comps_input = QLineEdit()
        self.author_pub_comps_input.setPlaceholderText("e.g. Gone Girl meets Dark Places")
        pc.addWidget(self.author_pub_comps_input)

        pc.addWidget(QLabel("Pitch Tone:"))
        self.author_pub_pitch_tone_box = QComboBox()
        self.author_pub_pitch_tone_box.addItems(["Professional", "Conversational", "High-Concept"])
        pc.addWidget(self.author_pub_pitch_tone_box)

        pc.addWidget(QLabel("Extra Notes:"))
        self.author_pub_notes_input = QTextEdit()
        self.author_pub_notes_input.setPlaceholderText("Target audience, themes, hook, extra context…")
        self.author_pub_notes_input.setFixedHeight(65)
        pc.addWidget(self.author_pub_notes_input)

        pc.addStretch()

        self.author_pub_generate_btn = QPushButton("Generate")
        self.author_pub_generate_btn.setMinimumHeight(34)
        self.author_pub_generate_btn.setStyleSheet(
            "QPushButton { background-color: #1a2d1a; border: 1px solid #3cff88;"
            " font-weight: bold; color: #3cff88; }"
            "QPushButton:hover { background-color: #1e3d1e; }"
        )
        self.author_pub_generate_btn.clicked.connect(self.author_pub_generate)
        pc.addWidget(self.author_pub_generate_btn)

        self.author_pub_stop_btn = QPushButton("Stop")
        self.author_pub_stop_btn.setEnabled(False)
        self.author_pub_stop_btn.setStyleSheet(
            "QPushButton { background-color: #2b1010; border: 1px solid #ff4444;"
            " color: #ff5555; font-weight: bold; }"
            "QPushButton:hover { background-color: #3d1515; }"
        )
        self.author_pub_stop_btn.clicked.connect(self.author_pub_stop)
        pc.addWidget(self.author_pub_stop_btn)

        self.author_pub_copy_btn = QPushButton("Copy to Clipboard")
        self.author_pub_copy_btn.clicked.connect(self.author_pub_copy)
        pc.addWidget(self.author_pub_copy_btn)

        self.author_pub_save_btn = QPushButton("Save as File")
        self.author_pub_save_btn.setEnabled(False)
        self.author_pub_save_btn.clicked.connect(self.author_pub_save)
        pc.addWidget(self.author_pub_save_btn)

        pub_outer.addWidget(pub_ctrl)
        self.author_sub_stack.addWidget(publish_page)   # sub-page 0

        # ── Market page ───────────────────────────────────────────────────────
        market_page = QWidget()
        mkt_outer = QHBoxLayout(market_page)
        mkt_outer.setContentsMargins(0, 0, 0, 0)
        mkt_outer.setSpacing(8)

        self.author_mkt_output = QTextEdit()
        self.author_mkt_output.setPlaceholderText(
            "Generated marketing copy appears here. Fully editable."
        )
        mkt_outer.addWidget(self.author_mkt_output, 1)

        mkt_ctrl = QWidget()
        mkt_ctrl.setObjectName("AuthorMktCtrl")
        mkt_ctrl.setMinimumWidth(210)
        mkt_ctrl.setMaximumWidth(270)
        mc = QVBoxLayout(mkt_ctrl)
        mc.setContentsMargins(6, 0, 0, 0)
        mc.setSpacing(5)

        mc.addWidget(QLabel("Platform:"))
        self.author_mkt_platform_box = QComboBox()
        self.author_mkt_platform_box.addItems([
            "Amazon Description", "KDP Listing", "Goodreads Blurb", "Instagram Post",
            "Twitter / X Thread", "TikTok Caption", "Pinterest Pin Description",
            "YouTube Description", "Newsletter", "Press Release", "Book Club Questions",
            "ARC Outreach Email", "Launch Team Email", "Podcast Pitch", "Author Website Bio",
        ])
        mc.addWidget(self.author_mkt_platform_box)

        mc.addWidget(QLabel("Hook / Logline:"))
        self.author_mkt_hook_input = QLineEdit()
        self.author_mkt_hook_input.setPlaceholderText("One sentence that sells the book")
        mc.addWidget(self.author_mkt_hook_input)

        mc.addWidget(QLabel("Comp Titles:"))
        self.author_mkt_comps_input = QLineEdit()
        self.author_mkt_comps_input.setPlaceholderText("e.g. Reaper's Creek meets Harlan Coben")
        mc.addWidget(self.author_mkt_comps_input)

        mc.addWidget(QLabel("Tone:"))
        self.author_mkt_tone_box = QComboBox()
        self.author_mkt_tone_box.addItems(["Punchy", "Literary", "Warm", "Hype", "Mysterious"])
        mc.addWidget(self.author_mkt_tone_box)

        mc.addWidget(QLabel("Extra Notes:"))
        self.author_mkt_notes_input = QTextEdit()
        self.author_mkt_notes_input.setPlaceholderText("Target audience, mood, key themes…")
        self.author_mkt_notes_input.setFixedHeight(65)
        mc.addWidget(self.author_mkt_notes_input)

        mc.addStretch()

        self.author_mkt_generate_btn = QPushButton("Generate")
        self.author_mkt_generate_btn.setMinimumHeight(34)
        self.author_mkt_generate_btn.setStyleSheet(
            "QPushButton { background-color: #2d1a0e; border: 1px solid #ff9944;"
            " font-weight: bold; color: #ffb366; }"
            "QPushButton:hover { background-color: #3d2210; }"
        )
        self.author_mkt_generate_btn.clicked.connect(self.author_mkt_generate)
        mc.addWidget(self.author_mkt_generate_btn)

        self.author_mkt_stop_btn = QPushButton("Stop")
        self.author_mkt_stop_btn.setEnabled(False)
        self.author_mkt_stop_btn.setStyleSheet(
            "QPushButton { background-color: #2b1010; border: 1px solid #ff4444;"
            " color: #ff5555; font-weight: bold; }"
            "QPushButton:hover { background-color: #3d1515; }"
        )
        self.author_mkt_stop_btn.clicked.connect(self.author_mkt_stop)
        mc.addWidget(self.author_mkt_stop_btn)

        self.author_mkt_copy_btn = QPushButton("Copy to Clipboard")
        self.author_mkt_copy_btn.clicked.connect(self.author_mkt_copy)
        mc.addWidget(self.author_mkt_copy_btn)

        self.author_mkt_save_btn = QPushButton("Save as File")
        self.author_mkt_save_btn.setEnabled(False)
        self.author_mkt_save_btn.clicked.connect(self.author_mkt_save)
        mc.addWidget(self.author_mkt_save_btn)

        mkt_outer.addWidget(mkt_ctrl)
        self.author_sub_stack.addWidget(market_page)   # sub-page 1

        pm_layout.addWidget(self.author_sub_stack, 1)
        self.author_content_stack.addWidget(pubmkt_widget)   # page 1

        layout.addWidget(self.author_content_stack, 1)

        self.author_status_label = QLabel("")
        self.author_status_label.setStyleSheet("font-size: 12px; color: #888; padding: 2px 4px;")
        layout.addWidget(self.author_status_label)

        self.author_draft_box.textChanged.connect(self._author_update_counts)

        self.author_panel.hide()

        self.author_provider_box.currentTextChanged.connect(self.author_load_models)
        self.author_load_models()

        self._author_on_content_type_changed(self.author_content_type_box.currentText())
        self._author_load_profile()

    # ── Music Agent Panel ─────────────────────────────────────────────────────
    def build_music_panel(self):
        self.music_panel = QWidget()
        self.music_panel.setObjectName("MusicPanel")
        layout = QVBoxLayout(self.music_panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Setup form ──────────────────────────────────────────────────────
        setup_group = QGroupBox("Artist Setup")
        setup_group.setObjectName("MusicSetupGroup")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Artist / Project Name:"), 0, 0)
        self.music_artist_input = QLineEdit()
        self.music_artist_input.setPlaceholderText("e.g. Nova Drift, DJ Phantom, The Hollow Road")
        setup_layout.addWidget(self.music_artist_input, 0, 1)

        setup_layout.addWidget(QLabel("Genre:"), 0, 2)
        self.music_genre_box = QComboBox()
        self.music_genre_box.addItems([
            "Pop", "Rock", "Hip-Hop", "Electronic", "Jazz", "Classical",
            "R&B", "Metal", "Indie", "Folk", "Country", "Latin", "Reggae",
            "Ambient", "World", "Other",
        ])
        setup_layout.addWidget(self.music_genre_box, 0, 3)

        setup_layout.addWidget(QLabel("Release Type:"), 1, 0)
        self.music_release_type_box = QComboBox()
        self.music_release_type_box.addItems(["Single", "EP (3–6 tracks)", "Album (7+ tracks)", "Mixtape"])
        setup_layout.addWidget(self.music_release_type_box, 1, 1)

        setup_layout.addWidget(QLabel("Distributor:"), 1, 2)
        self.music_distributor_box = QComboBox()
        self.music_distributor_box.addItems([
            "Not signed up yet", "DistroKid", "TuneCore", "CD Baby", "Amuse", "AWAL", "Other",
        ])
        setup_layout.addWidget(self.music_distributor_box, 1, 3)

        setup_layout.addWidget(QLabel("Target Audience (optional):"), 2, 0)
        self.music_audience_input = QLineEdit()
        self.music_audience_input.setPlaceholderText(
            "e.g. 18–25 fans of lo-fi hip-hop, gym-goers, indie bedroom pop listeners"
        )
        setup_layout.addWidget(self.music_audience_input, 2, 1, 1, 3)

        setup_layout.addWidget(QLabel("Describe Your Music:"), 3, 0)
        self.music_query_input = QTextEdit()
        self.music_query_input.setPlaceholderText(
            "Describe your sound, influences, vibe, and anything specific about this release "
            "(e.g. dark trap beats with melodic hooks, influenced by Travis Scott and Frank Ocean, "
            "releasing a 4-track EP about late-night city life)…"
        )
        self.music_query_input.setFixedHeight(70)
        setup_layout.addWidget(self.music_query_input, 3, 1, 1, 3)

        layout.addWidget(setup_group)

        # ── Provider row ────────────────────────────────────────────────────
        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)

        self.music_provider_box = QComboBox()
        self.music_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.music_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.music_provider_box)

        self.music_model_box = QComboBox()
        self.music_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.music_model_box)

        self.music_analyse_btn = QPushButton("Generate Plan")
        self.music_analyse_btn.setMinimumWidth(140)
        self.music_analyse_btn.setObjectName("PrimaryAction")
        self.music_analyse_btn.clicked.connect(self.music_analyse)
        provider_row.addWidget(self.music_analyse_btn)

        self.music_stop_btn = QPushButton("Stop")
        self.music_stop_btn.setEnabled(False)
        self.music_stop_btn.setObjectName("DangerAction")
        self.music_stop_btn.clicked.connect(self.music_stop)
        provider_row.addWidget(self.music_stop_btn)

        self.music_help_btn = QPushButton("Help")


        self.music_help_btn.setObjectName("ChipBtn")
        self.music_help_btn.setToolTip("Open Music Agent documentation")
        self.music_help_btn.clicked.connect(self.show_agent_docs)
        provider_row.addWidget(self.music_help_btn)

        layout.addWidget(provider_row_container)

        # ── Results area (tabs + sidebar) ───────────────────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.music_tabs = QTabWidget()

        self.music_profile_box = QTextBrowser()
        self.music_profile_box.setOpenExternalLinks(False)
        self.music_tabs.addTab(self.music_profile_box, "Artist Profile")

        self.music_release_box = QTextBrowser()
        self.music_tabs.addTab(self.music_release_box, "Release Setup")

        self.music_distribution_box = QTextBrowser()
        self.music_tabs.addTab(self.music_distribution_box, "Distribution")

        self.music_strategy_box = QTextBrowser()
        self.music_tabs.addTab(self.music_strategy_box, "Spotify Strategy")

        self.music_income_box = QTextBrowser()
        self.music_tabs.addTab(self.music_income_box, "Income Roadmap")

        results_splitter.addWidget(self.music_tabs)

        # ── Sidebar indicators ──────────────────────────────────────────────
        indicators_widget = QWidget()
        indicators_layout = QVBoxLayout(indicators_widget)
        indicators_layout.setContentsMargins(6, 6, 6, 6)
        indicators_layout.setSpacing(8)

        release_group = QGroupBox("Release Type")
        release_group.setObjectName("MusicReleaseGroup")
        release_layout = QVBoxLayout(release_group)
        self.music_release_label = QLabel("—")
        self.music_release_label.setAlignment(Qt.AlignCenter)
        self.music_release_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #3cff88;")
        release_layout.addWidget(self.music_release_label)
        indicators_layout.addWidget(release_group)

        genre_group = QGroupBox("Genre")
        genre_group.setObjectName("MusicGenreGroup")
        genre_layout = QVBoxLayout(genre_group)
        self.music_genre_label = QLabel("—")
        self.music_genre_label.setAlignment(Qt.AlignCenter)
        self.music_genre_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4db8ff;")
        genre_layout.addWidget(self.music_genre_label)
        indicators_layout.addWidget(genre_group)

        dist_group = QGroupBox("Distributor")
        dist_group.setObjectName("MusicDistGroup")
        dist_layout = QVBoxLayout(dist_group)
        self.music_dist_label = QLabel("—")
        self.music_dist_label.setAlignment(Qt.AlignCenter)
        self.music_dist_label.setWordWrap(True)
        self.music_dist_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0c040;")
        dist_layout.addWidget(self.music_dist_label)
        indicators_layout.addWidget(dist_group)

        steps_group = QGroupBox("Procedure")
        steps_group.setObjectName("MusicStepsGroup")
        steps_layout = QVBoxLayout(steps_group)
        self.music_steps_label = QLabel(
            "1. Artist Profile\n2. Release Setup\n3. Distribution\n4. Spotify Strategy\n5. Income Roadmap"
        )
        self.music_steps_label.setStyleSheet("font-size: 11px; color: #aaa;")
        steps_layout.addWidget(self.music_steps_label)
        indicators_layout.addWidget(steps_group)

        indicators_layout.addStretch()

        self.music_save_btn = QPushButton("Save Full Plan")
        self.music_save_btn.setEnabled(False)
        self.music_save_btn.clicked.connect(self.music_save)
        indicators_layout.addWidget(self.music_save_btn)

        self.music_clear_btn = QPushButton("Clear")
        self.music_clear_btn.clicked.connect(self.music_clear)
        indicators_layout.addWidget(self.music_clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([700, 200])

        layout.addWidget(results_splitter, 1)

        self.music_status_label = QLabel("")
        self.music_status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.music_status_label)

        self.music_panel.hide()

        self.music_provider_box.currentTextChanged.connect(self.music_load_models)
        self.music_load_models()

    # ── NFL Prop Bet Panel ───────────────────────────────────────────────────
    def build_osint_panel(self):
        self.osint_panel = QWidget()
        self.osint_panel.setObjectName("OSINTPanel")
        layout = QVBoxLayout(self.osint_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Target form ──────────────────────────────────────────────────────
        setup_group = QGroupBox("Target")
        setup_group.setObjectName("OSINTSetupBox")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Target:"), 0, 0)
        self.osint_target_input = QLineEdit()
        self.osint_target_input.setPlaceholderText(
            "Enter name, username, email, domain, company, phone, or IP…"
        )
        setup_layout.addWidget(self.osint_target_input, 0, 1, 1, 3)

        setup_layout.addWidget(QLabel("Query Type:"), 1, 0)
        self.osint_type_box = QComboBox()
        self.osint_type_box.addItems([
            "Auto-detect", "Person", "Username", "Email",
            "Domain", "Company", "Phone", "IP Address",
        ])
        setup_layout.addWidget(self.osint_type_box, 1, 1)

        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)
        provider_row.addWidget(QLabel("Provider:"))
        self.osint_provider_box = QComboBox()
        self.osint_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.osint_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.osint_provider_box)

        provider_row.addWidget(QLabel("Model:"))
        self.osint_model_box = QComboBox()
        self.osint_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.osint_model_box)


        self.osint_analyse_btn = QPushButton("Structure Query")
        self.osint_analyse_btn.setMinimumWidth(150)
        self.osint_analyse_btn.setObjectName("PrimaryAction")
        self.osint_analyse_btn.clicked.connect(self.osint_analyse)
        provider_row.addWidget(self.osint_analyse_btn)

        self.osint_stop_btn = QPushButton("Stop")
        self.osint_stop_btn.setEnabled(False)
        self.osint_stop_btn.setObjectName("DangerAction")
        self.osint_stop_btn.clicked.connect(self.osint_stop)
        provider_row.addWidget(self.osint_stop_btn)

        setup_layout.addWidget(provider_row_container, 2, 0, 1, 4)
        layout.addWidget(setup_group)

        # ── Output tabs ───────────────────────────────────────────────────────
        self.osint_tabs = QTabWidget()

        self.osint_structure_box = QTextBrowser()
        self.osint_structure_box.setOpenExternalLinks(False)
        self.osint_tabs.addTab(self.osint_structure_box, "Query Structure")

        dorks_widget = QWidget()
        dorks_layout = QVBoxLayout(dorks_widget)
        dorks_layout.setContentsMargins(0, 4, 0, 0)
        dorks_layout.setSpacing(4)
        self.osint_dorks_box = QTextBrowser()
        self.osint_dorks_box.setOpenExternalLinks(False)
        dorks_layout.addWidget(self.osint_dorks_box, 1)
        copy_dorks_btn = QPushButton("Copy Dorks")
        copy_dorks_btn.setMaximumWidth(120)
        copy_dorks_btn.clicked.connect(self._osint_copy_dorks)
        dorks_layout.addWidget(copy_dorks_btn)
        self.osint_tabs.addTab(dorks_widget, "Google Dorks")

        self.osint_sources_box = QTextBrowser()
        self.osint_sources_box.setOpenExternalLinks(False)
        self.osint_tabs.addTab(self.osint_sources_box, "Public Sources")

        self.osint_summary_box = QTextBrowser()
        self.osint_summary_box.setOpenExternalLinks(False)
        self.osint_tabs.addTab(self.osint_summary_box, "Summary & Next Steps")

        layout.addWidget(self.osint_tabs, 1)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        self.osint_status_label = QLabel("Idle")
        self.osint_status_label.setStyleSheet("font-size: 12px; color: #888;")
        bottom_row.addWidget(self.osint_status_label)
        bottom_row.addStretch()
        osint_clear_btn = QPushButton("Clear")
        osint_clear_btn.clicked.connect(self.osint_clear)
        bottom_row.addWidget(osint_clear_btn)
        layout.addLayout(bottom_row)

        self.osint_panel.hide()

        self.osint_provider_box.currentTextChanged.connect(self.osint_load_models)
        self.osint_load_models()

    # ── OSINT Pro (Heavy) panel ──────────────────────────────────────────────
    def build_osint_heavy_panel(self):
        self.osint_heavy_panel = QWidget()
        self.osint_heavy_panel.setObjectName("OSINTHeavyPanel")
        layout = QVBoxLayout(self.osint_heavy_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Investigation Brief ──────────────────────────────────────────────
        brief_group = QGroupBox("Investigation Brief")
        brief_group.setObjectName("OSINTHeavyBriefBox")
        brief_layout = QGridLayout(brief_group)
        brief_layout.setSpacing(6)

        brief_layout.addWidget(QLabel("Target:"), 0, 0)
        self.osint_heavy_target_input = QLineEdit()
        self.osint_heavy_target_input.setPlaceholderText(
            "Name, username, email, domain, IP, phone number, or organisation…"
        )
        brief_layout.addWidget(self.osint_heavy_target_input, 0, 1, 1, 3)

        brief_layout.addWidget(QLabel("Target Type:"), 1, 0)
        self.osint_heavy_type_box = QComboBox()
        self.osint_heavy_type_box.addItems([
            "Person", "Username", "Email Address", "Domain / IP",
            "Organisation", "Phone Number", "Auto-detect",
        ])
        brief_layout.addWidget(self.osint_heavy_type_box, 1, 1)

        brief_layout.addWidget(QLabel("Scope:"), 1, 2)
        self.osint_heavy_scope_box = QComboBox()
        self.osint_heavy_scope_box.addItems(["Quick Scan", "Standard Investigation", "Deep Dive"])
        self.osint_heavy_scope_box.setCurrentText("Standard Investigation")
        brief_layout.addWidget(self.osint_heavy_scope_box, 1, 3)

        brief_layout.addWidget(QLabel("Objective:"), 2, 0)
        self.osint_heavy_objective_input = QTextEdit()
        self.osint_heavy_objective_input.setPlaceholderText(
            "What are you trying to establish? e.g. verify identity, map infrastructure, check breach exposure, assess threat level…"
        )
        self.osint_heavy_objective_input.setFixedHeight(60)
        brief_layout.addWidget(self.osint_heavy_objective_input, 2, 1, 1, 3)

        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)
        provider_row.addWidget(QLabel("Provider:"))
        self.osint_heavy_provider_box = QComboBox()
        self.osint_heavy_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.osint_heavy_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.osint_heavy_provider_box)

        provider_row.addWidget(QLabel("Model:"))
        self.osint_heavy_model_box = QComboBox()
        self.osint_heavy_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.osint_heavy_model_box)


        self.osint_heavy_investigate_btn = QPushButton("Investigate")
        self.osint_heavy_investigate_btn.setMinimumWidth(140)
        self.osint_heavy_investigate_btn.setObjectName("PrimaryAction")
        self.osint_heavy_investigate_btn.clicked.connect(self.osint_heavy_investigate)
        provider_row.addWidget(self.osint_heavy_investigate_btn)

        self.osint_heavy_stop_btn = QPushButton("Stop")
        self.osint_heavy_stop_btn.setEnabled(False)
        self.osint_heavy_stop_btn.setObjectName("DangerAction")
        self.osint_heavy_stop_btn.clicked.connect(self.osint_heavy_stop)
        provider_row.addWidget(self.osint_heavy_stop_btn)

        brief_layout.addWidget(provider_row_container, 3, 0, 1, 4)
        layout.addWidget(brief_group)

        # ── Target Image (optional) ──────────────────────────────────────────
        image_group = QGroupBox("Target Image  —  optional, enables EXIF analysis & face search links")
        image_group.setObjectName("OSINTHeavyImageBox")
        image_outer = QVBoxLayout(image_group)
        image_outer.setSpacing(4)
        image_outer.setContentsMargins(6, 4, 6, 4)
        image_top_row = QHBoxLayout()
        self.osint_heavy_image_label = QLabel("No image selected")
        self.osint_heavy_image_label.setStyleSheet("color: #666; font-style: italic;")
        self.osint_heavy_image_label.setMinimumWidth(200)
        image_top_row.addWidget(self.osint_heavy_image_label, 1)
        osint_browse_btn = QPushButton("Browse…")
        osint_browse_btn.setMaximumWidth(90)
        osint_browse_btn.clicked.connect(self._osint_heavy_browse_image)
        image_top_row.addWidget(osint_browse_btn)
        osint_clear_img_btn = QPushButton("Clear Image")
        osint_clear_img_btn.setMaximumWidth(90)
        osint_clear_img_btn.clicked.connect(self._osint_heavy_clear_image)
        image_top_row.addWidget(osint_clear_img_btn)
        image_outer.addLayout(image_top_row)
        self.osint_heavy_exif_display = QTextEdit()
        self.osint_heavy_exif_display.setReadOnly(True)
        self.osint_heavy_exif_display.setFixedHeight(52)
        self.osint_heavy_exif_display.setPlaceholderText(
            "EXIF metadata will appear here after selecting an image…"
        )
        self.osint_heavy_exif_display.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #aaa;"
        )
        image_outer.addWidget(self.osint_heavy_exif_display)
        layout.addWidget(image_group)

        # ── Results splitter: tabs left, indicators right ────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.osint_heavy_tabs = QTabWidget()

        self.osint_heavy_overview_box = QTextBrowser()
        self.osint_heavy_overview_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_overview_box, "Overview")

        self.osint_heavy_footprint_box = QTextBrowser()
        self.osint_heavy_footprint_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_footprint_box, "Digital Footprint")

        self.osint_heavy_infra_box = QTextBrowser()
        self.osint_heavy_infra_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_infra_box, "Infra / Social")

        self.osint_heavy_risk_box = QTextBrowser()
        self.osint_heavy_risk_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_risk_box, "Risk & Red Flags")

        self.osint_heavy_method_box = QTextBrowser()
        self.osint_heavy_method_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_method_box, "Methodology")

        self.osint_heavy_dossier_box = QTextBrowser()
        self.osint_heavy_dossier_box.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_dossier_box, "Full Dossier")

        self.osint_heavy_image_tab = QTextBrowser()
        self.osint_heavy_image_tab.setOpenExternalLinks(True)
        self.osint_heavy_tabs.addTab(self.osint_heavy_image_tab, "Image OSINT")

        results_splitter.addWidget(self.osint_heavy_tabs)

        # ── Indicators sidebar ───────────────────────────────────────────────
        indicators_widget = QWidget()
        indicators_layout = QVBoxLayout(indicators_widget)
        indicators_layout.setContentsMargins(8, 0, 0, 0)
        indicators_layout.setSpacing(10)

        threat_group = QGroupBox("Threat Level")
        threat_group.setObjectName("OSINTHeavyThreatBox")
        threat_layout = QVBoxLayout(threat_group)
        self.osint_heavy_threat_bar = QProgressBar()
        self.osint_heavy_threat_bar.setRange(0, 10)
        self.osint_heavy_threat_bar.setValue(0)
        self.osint_heavy_threat_bar.setTextVisible(False)
        self.osint_heavy_threat_bar.setFixedHeight(16)
        self.osint_heavy_threat_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: #cc2200; }"
        )
        threat_layout.addWidget(self.osint_heavy_threat_bar)
        self.osint_heavy_threat_label = QLabel("—")
        self.osint_heavy_threat_label.setAlignment(Qt.AlignCenter)
        threat_layout.addWidget(self.osint_heavy_threat_label)
        indicators_layout.addWidget(threat_group)

        conf_group = QGroupBox("Confidence")
        conf_group.setObjectName("OSINTHeavyConfBox")
        conf_layout = QVBoxLayout(conf_group)
        self.osint_heavy_conf_label = QLabel("—")
        self.osint_heavy_conf_label.setAlignment(Qt.AlignCenter)
        self.osint_heavy_conf_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #dd88ff;")
        conf_layout.addWidget(self.osint_heavy_conf_label)
        indicators_layout.addWidget(conf_group)

        sources_group = QGroupBox("Sources")
        sources_group.setObjectName("OSINTHeavySourcesBox")
        sources_layout = QVBoxLayout(sources_group)
        self.osint_heavy_sources_label = QLabel("—")
        self.osint_heavy_sources_label.setAlignment(Qt.AlignCenter)
        self.osint_heavy_sources_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4db8ff;")
        sources_layout.addWidget(self.osint_heavy_sources_label)
        indicators_layout.addWidget(sources_group)

        depth_group = QGroupBox("Depth")
        depth_group.setObjectName("OSINTHeavyDepthBox")
        depth_layout = QVBoxLayout(depth_group)
        self.osint_heavy_depth_label = QLabel("—")
        self.osint_heavy_depth_label.setAlignment(Qt.AlignCenter)
        self.osint_heavy_depth_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaaaff;")
        depth_layout.addWidget(self.osint_heavy_depth_label)
        indicators_layout.addWidget(depth_group)

        indicators_layout.addStretch()

        self.osint_heavy_save_btn = QPushButton("Save Report")
        self.osint_heavy_save_btn.setEnabled(False)
        self.osint_heavy_save_btn.clicked.connect(self.osint_heavy_save)
        indicators_layout.addWidget(self.osint_heavy_save_btn)

        self.osint_heavy_clear_btn = QPushButton("Clear")
        self.osint_heavy_clear_btn.clicked.connect(self.osint_heavy_clear)
        indicators_layout.addWidget(self.osint_heavy_clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([680, 220])

        layout.addWidget(results_splitter, 1)

        self.osint_heavy_status_label = QLabel("")
        self.osint_heavy_status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.osint_heavy_status_label)

        self.osint_heavy_panel.hide()

        self.osint_heavy_provider_box.currentTextChanged.connect(self.osint_heavy_load_models)
        self.osint_heavy_load_models()


    # ── OSINT Light handlers ──────────────────────────────────────────────────
    def osint_load_models(self):
        provider = self.osint_provider_box.currentText()
        self.osint_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
            for m in models:
                self.osint_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("osint: load models", exc, self.osint_model_box)

    def osint_analyse(self):
        target = self.osint_target_input.text().strip()
        query_type = self.osint_type_box.currentText()
        provider = self.osint_provider_box.currentText()
        model = self.osint_model_box.currentText()

        if not target:
            QMessageBox.warning(self, "Missing Input", "Please enter a target.")
            return
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        agent = self.agent_instances["osint"]
        messages = agent.build_messages(target, query_type)

        if not self.authorize_request("osint", provider, model, target, label=query_type):
            return

        self._osint_clear_tabs()
        self._last_osint_response = ""
        self.osint_status_label.setText("Structuring query…")
        self.osint_analyse_btn.setEnabled(False)
        self.osint_stop_btn.setEnabled(True)

        self.osint_worker = ChatWorker(self.run_backend, provider, model, messages, target)
        self.osint_worker.token_signal.connect(self._osint_on_token)
        self.osint_worker.finished_signal.connect(self._osint_on_finished)
        self.osint_worker.usage_signal.connect(lambda u: self.note_request_usage("osint", u))
        self.osint_worker.error_signal.connect(self._osint_on_error)
        self.osint_worker.start()

    def _osint_on_token(self, token: str):
        self._last_osint_response = getattr(self, "_last_osint_response", "") + token
        self.osint_structure_box.setPlainText(self._last_osint_response)
        self.osint_structure_box.moveCursor(QTextCursor.End)

    def _osint_on_finished(self, full_response: str):
        self._last_osint_response = full_response
        self.record_request("osint", full_response)
        self._populate_osint_tabs(full_response)
        self.osint_status_label.setText("Done.")
        self.osint_analyse_btn.setEnabled(True)
        self.osint_stop_btn.setEnabled(False)

    def _osint_on_error(self, error: str):
        self.abandon_request("osint")
        separator = "─" * 50
        self.osint_structure_box.setPlainText(
            f"⚠  ERROR\n{separator}\n{error}\n{separator}"
        )
        self.osint_status_label.setText("Error.")
        self.osint_analyse_btn.setEnabled(True)
        self.osint_stop_btn.setEnabled(False)

    def osint_stop(self):
        if self.osint_worker is not None and self.osint_worker.isRunning():
            self.osint_worker.cancel()
        self.osint_status_label.setText("Stopped.")
        self.osint_analyse_btn.setEnabled(True)
        self.osint_stop_btn.setEnabled(False)

    def osint_clear(self):
        self._osint_clear_tabs()
        self.osint_target_input.clear()
        self.osint_status_label.setText("Idle")
        self._last_osint_response = ""

    def _osint_clear_tabs(self):
        for box in (
            self.osint_structure_box,
            self.osint_dorks_box,
            self.osint_sources_box,
            self.osint_summary_box,
        ):
            box.clear()

    def _osint_copy_dorks(self):
        text = self.osint_dorks_box.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.osint_status_label.setText("Dorks copied to clipboard.")

    def _populate_osint_tabs(self, text: str):
        sections = self._parse_osint_sections(text)
        self.osint_structure_box.setPlainText(sections.get("structure", text))
        self.osint_dorks_box.setPlainText(sections.get("dorks", ""))
        self.osint_sources_box.setPlainText(sections.get("sources", ""))
        self.osint_summary_box.setPlainText(sections.get("summary", ""))

    def _parse_osint_sections(self, text: str) -> dict:
        import re
        patterns = {
            "structure": r"##\s*QUERY STRUCTURE(.*?)(?=##\s*GOOGLE DORKS|$)",
            "dorks":     r"##\s*GOOGLE DORKS(.*?)(?=##\s*PUBLIC SOURCES|$)",
            "sources":   r"##\s*PUBLIC SOURCES(.*?)(?=##\s*SUMMARY|$)",
            "summary":   r"##\s*SUMMARY.*?(.*?)$",
        }
        result = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            result[key] = m.group(1).strip() if m else ""
        return result

    # ── OSINT Pro (Heavy) handlers ───────────────────────────────────────────
    def osint_heavy_load_models(self):
        provider = self.osint_heavy_provider_box.currentText()
        self.osint_heavy_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
            for m in models:
                self.osint_heavy_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("osint_heavy: load models", exc, self.osint_heavy_model_box)

    def osint_heavy_investigate(self):
        target = self.osint_heavy_target_input.text().strip()
        target_type = self.osint_heavy_type_box.currentText()
        scope = self.osint_heavy_scope_box.currentText()
        objective = self.osint_heavy_objective_input.toPlainText().strip()
        provider = self.osint_heavy_provider_box.currentText()
        model = self.osint_heavy_model_box.currentText()

        if not target:
            QMessageBox.warning(self, "Missing Input", "Please enter a target identifier.")
            return
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        image_metadata = ""
        if self._osint_heavy_image_path:
            image_metadata = self._extract_image_exif_for_prompt(self._osint_heavy_image_path)

        agent = self.agent_instances["osint_heavy"]
        messages = agent.build_messages(target, target_type, scope, objective, image_metadata)

        self._osint_heavy_clear_displays()
        self._last_osint_heavy_response = ""
        self.osint_heavy_depth_label.setText(scope)
        self.osint_heavy_status_label.setText("Investigating…")
        self.osint_heavy_investigate_btn.setEnabled(False)
        self.osint_heavy_stop_btn.setEnabled(True)
        self.osint_heavy_save_btn.setEnabled(False)

        if not self.authorize_request("osint_heavy", provider, model, target):
            return
        self.osint_heavy_worker = ChatWorker(self.run_backend, provider, model, messages, target)
        self.osint_heavy_worker.token_signal.connect(self._osint_heavy_on_token)
        self.osint_heavy_worker.finished_signal.connect(self._osint_heavy_on_finished)
        self.osint_heavy_worker.usage_signal.connect(lambda u: self.note_request_usage("osint_heavy", u))
        self.osint_heavy_worker.error_signal.connect(self._osint_heavy_on_error)
        self.osint_heavy_worker.start()

    def _osint_heavy_on_token(self, token: str):
        self._last_osint_heavy_response += token
        self.osint_heavy_dossier_box.setPlainText(self._last_osint_heavy_response)
        self.osint_heavy_dossier_box.moveCursor(QTextCursor.End)

    def _osint_heavy_on_finished(self, full_response: str):
        self.record_request("osint_heavy", full_response)
        self._last_osint_heavy_response = full_response
        self._populate_osint_heavy_tabs(full_response)
        self._update_osint_heavy_indicators(full_response)
        self.osint_heavy_status_label.setText("Investigation complete.")
        self.osint_heavy_investigate_btn.setEnabled(True)
        self.osint_heavy_stop_btn.setEnabled(False)
        self.osint_heavy_save_btn.setEnabled(True)
        self.osint_heavy_tabs.setCurrentIndex(0)

    def _osint_heavy_on_error(self, error: str):
        self.abandon_request("osint_heavy")
        self.osint_heavy_dossier_box.setPlainText(f"[Error] {error}")
        self.osint_heavy_status_label.setText("Error.")
        self.osint_heavy_investigate_btn.setEnabled(True)
        self.osint_heavy_stop_btn.setEnabled(False)

    def osint_heavy_stop(self):
        if self.osint_heavy_worker is not None and self.osint_heavy_worker.isRunning():
            self.osint_heavy_worker.cancel()
        self.osint_heavy_status_label.setText("Stopped.")
        self.osint_heavy_investigate_btn.setEnabled(True)
        self.osint_heavy_stop_btn.setEnabled(False)

    def osint_heavy_save(self):
        if not self._last_osint_heavy_response:
            return
        target = self.osint_heavy_target_input.text().strip().replace(" ", "_").replace("/", "-") or "target"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"osint_dossier_{target}_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save OSINT Dossier", str(DATA_DIR / default_name), "Text files (*.txt);;All files (*)"
        )
        if path:
            Path(path).write_text(self._last_osint_heavy_response, encoding="utf-8")
            self.osint_heavy_status_label.setText(f"Saved to {Path(path).name}")

    def osint_heavy_clear(self):
        self._osint_heavy_clear_displays()
        self.osint_heavy_target_input.clear()
        self.osint_heavy_objective_input.clear()
        self.osint_heavy_status_label.setText("")
        self._last_osint_heavy_response = ""
        self._osint_heavy_clear_image()

    def _osint_heavy_clear_displays(self):
        for box in (
            self.osint_heavy_overview_box,
            self.osint_heavy_footprint_box,
            self.osint_heavy_infra_box,
            self.osint_heavy_risk_box,
            self.osint_heavy_method_box,
            self.osint_heavy_dossier_box,
            self.osint_heavy_image_tab,
        ):
            box.clear()
        self.osint_heavy_threat_bar.setValue(0)
        self.osint_heavy_threat_label.setText("—")
        self.osint_heavy_conf_label.setText("—")
        self.osint_heavy_sources_label.setText("—")
        self.osint_heavy_depth_label.setText("—")
        self.osint_heavy_save_btn.setEnabled(False)

    def _populate_osint_heavy_tabs(self, text: str):
        sections = self._parse_osint_heavy_sections(text)
        self.osint_heavy_overview_box.setPlainText(sections.get("overview", ""))
        self.osint_heavy_footprint_box.setPlainText(sections.get("footprint", ""))
        self.osint_heavy_infra_box.setPlainText(sections.get("infra", ""))
        self.osint_heavy_risk_box.setPlainText(sections.get("risk", ""))
        self.osint_heavy_method_box.setPlainText(sections.get("methodology", ""))
        self.osint_heavy_dossier_box.setPlainText(text)

    def _parse_osint_heavy_sections(self, text: str) -> dict:
        patterns = {
            "overview":    r"##\s*1\.\s*OVERVIEW(.*?)(?=##\s*2\.|$)",
            "footprint":   r"##\s*2\.\s*DIGITAL FOOTPRINT(.*?)(?=##\s*3\.|$)",
            "infra":       r"##\s*3\.\s*INFRASTRUCTURE.*?(.*?)(?=##\s*4\.|$)",
            "risk":        r"##\s*4\.\s*RISK.*?(.*?)(?=##\s*5\.|$)",
            "methodology": r"##\s*5\.\s*METHODOLOGY.*?(.*?)$",
        }
        result = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            result[key] = m.group(1).strip() if m else ""
        return result

    def _update_osint_heavy_indicators(self, text: str):
        threat_m = re.search(r"THREAT LEVEL[:\s]+(\d+)\s*/\s*10", text, re.IGNORECASE)
        if threat_m:
            level = int(threat_m.group(1))
            self.osint_heavy_threat_bar.setValue(min(level, 10))
            self.osint_heavy_threat_label.setText(f"{level}/10")

        conf_m = re.search(r"CONFIDENCE[:\s]+(\d+)\s*%", text, re.IGNORECASE)
        if conf_m:
            self.osint_heavy_conf_label.setText(f"{conf_m.group(1)}%")

        sources_m = re.search(r"SOURCES REFERENCED[:\s]+(\d+)", text, re.IGNORECASE)
        if sources_m:
            self.osint_heavy_sources_label.setText(sources_m.group(1))

    # ── OSINT Pro image helpers ──────────────────────────────────────────────
    def _osint_heavy_browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Target Image", str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp *.heic);;All files (*)"
        )
        if not path:
            return
        self._osint_heavy_image_path = path
        self.osint_heavy_image_label.setText(Path(path).name)
        self.osint_heavy_image_label.setStyleSheet("color: #dd88ff; font-style: normal;")
        self.osint_heavy_exif_display.setPlainText(self._extract_image_exif_display(path))
        self._osint_heavy_populate_image_tab(path)

    def _osint_heavy_clear_image(self):
        self._osint_heavy_image_path = ""
        self.osint_heavy_image_label.setText("No image selected")
        self.osint_heavy_image_label.setStyleSheet("color: #666; font-style: italic;")
        self.osint_heavy_exif_display.clear()
        self.osint_heavy_image_tab.clear()

    def _extract_image_exif_raw(self, path: str) -> dict:
        try:
            from PIL import Image as PILImage
            from PIL.ExifTags import TAGS, GPSTAGS
            img = PILImage.open(path)
            raw = img._getexif()
            if not raw:
                return {}
            result = {}
            for tag_id, value in raw.items():
                tag = TAGS.get(tag_id, str(tag_id))
                if tag == "GPSInfo" and isinstance(value, dict):
                    result["GPSInfo"] = {GPSTAGS.get(k, k): v for k, v in value.items()}
                elif isinstance(value, (str, int, float, bytes)):
                    result[tag] = value
            return result
        except Exception:
            return {}

    def _gps_to_decimal(self, dms, ref: str) -> float:
        try:
            d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
            decimal = d + m / 60 + s / 3600
            return round(-decimal if ref in ("S", "W") else decimal, 6)
        except Exception:
            return 0.0

    def _extract_image_exif_display(self, path: str) -> str:
        exif = self._extract_image_exif_raw(path)
        if not exif:
            return "No EXIF data found in this image."
        parts = []
        for key in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
            if key in exif:
                parts.append(f"Date: {exif[key]}")
                break
        device = (str(exif.get("Make", "")) + " " + str(exif.get("Model", ""))).strip()
        if device:
            parts.append(f"Device: {device}")
        if exif.get("Software"):
            parts.append(f"Software: {str(exif['Software'])[:40]}")
        gps = exif.get("GPSInfo", {})
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = self._gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
            lon = self._gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
            parts.append(f"GPS: {lat}°, {lon}°")
        return "  ·  ".join(parts) if parts else "EXIF present but no key fields extracted."

    def _extract_image_exif_for_prompt(self, path: str) -> str:
        exif = self._extract_image_exif_raw(path)
        if not exif:
            return "No EXIF metadata could be extracted (data may have been stripped)."
        lines = [f"Image file: {Path(path).name}"]
        for key in ("DateTimeOriginal", "DateTime", "Make", "Model", "Software",
                    "LensMake", "LensModel", "ImageWidth", "ImageLength",
                    "Orientation", "Flash", "FocalLength"):
            if key in exif:
                lines.append(f"  {key}: {exif[key]}")
        gps = exif.get("GPSInfo", {})
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = self._gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
            lon = self._gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
            lines.append(f"  GPS Coordinates: {lat}, {lon}")
            lines.append(f"  Google Maps link: https://maps.google.com/?q={lat},{lon}")
            if gps.get("GPSAltitude"):
                lines.append(f"  GPS Altitude: {gps['GPSAltitude']} m")
            if gps.get("GPSImgDirection"):
                lines.append(f"  Camera direction: {gps['GPSImgDirection']} degrees")
        return "\n".join(lines)

    def _osint_heavy_populate_image_tab(self, path: str):
        exif = self._extract_image_exif_raw(path)
        fname = Path(path).name
        gps_block = ""
        gps = exif.get("GPSInfo", {})
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = self._gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
            lon = self._gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
            gps_block = (
                f'<h3 style="color:#f0c040;">GPS Coordinates Extracted</h3>'
                f"<p><b>Coordinates:</b> {lat}, {lon}</p>"
                f'<p><a href="https://maps.google.com/?q={lat},{lon}">Google Maps</a>'
                f' &nbsp;|&nbsp; <a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15">OpenStreetMap</a>'
                f' &nbsp;|&nbsp; <a href="https://suncalc.org/#/{lat},{lon},14/">SunCalc</a></p>'
            )
        exif_rows = ""
        for key in ("DateTimeOriginal", "DateTime", "DateTimeDigitized",
                    "Make", "Model", "Software", "LensMake", "LensModel",
                    "ImageWidth", "ImageLength", "Orientation", "Flash", "FocalLength"):
            if key in exif:
                exif_rows += f"<tr><td style='color:#888;padding-right:14px;'>{key}</td><td>{exif[key]}</td></tr>"
        no_exif = (
            "<p style='color:#ff8888;'>No EXIF data found — the image may have been stripped "
            "(common with screenshots, social media downloads, and edited files). This itself can be a signal.</p>"
            if not exif else ""
        )
        html = (
            "<html><body style='font-family:monospace;font-size:12px;color:#ccc;background:#1a1a1a;padding:8px;'>"
            f"<h2 style='color:#dd88ff;'>Image OSINT &mdash; {fname}</h2>"
            f"{no_exif}{gps_block}"
            "<h3 style='color:#4db8ff;'>Reverse Image Search</h3>"
            "<p style='color:#aaa;'>Upload the image at each service to search for matches:</p><ul>"
            "<li><a href='https://tineye.com'>TinEye</a> &mdash; reverse image search with date history</li>"
            "<li><a href='https://images.google.com'>Google Images</a> &mdash; click the camera icon to upload</li>"
            "<li><a href='https://yandex.com/images'>Yandex Images</a> &mdash; strong face/person matching</li>"
            "<li><a href='https://www.bing.com/visualsearch'>Bing Visual Search</a> &mdash; Microsoft image search</li>"
            "</ul>"
            "<h3 style='color:#ff88aa;'>Face Recognition Services</h3>"
            "<p style='color:#aaa;'>Upload the image to search for the person across the public web:</p><ul>"
            "<li><a href='https://pimeyes.com'>PimEyes</a> &mdash; facial recognition across billions of public images</li>"
            "<li><a href='https://facecheck.id'>FaceCheck.ID</a> &mdash; face search across social media profiles</li>"
            "<li><a href='https://lenso.ai'>Lenso.ai</a> &mdash; AI-powered reverse image and face search</li>"
            "</ul>"
            "<h3 style='color:#3cff88;'>Extracted EXIF Metadata</h3>"
            + ("<table>" + exif_rows + "</table>" if exif_rows else "<p style='color:#888;'>No key EXIF fields found.</p>")
            + "<br><p style='color:#555;font-size:11px;'>For authorised investigative use only.</p>"
            "</body></html>"
        )
        self.osint_heavy_image_tab.setHtml(html)
        self.osint_heavy_tabs.setCurrentIndex(self.osint_heavy_tabs.indexOf(self.osint_heavy_image_tab))

    # ── Web Design panel ────────────────────────────────────────────────────
    def build_webdesign_panel(self):
        self.webdesign_panel = QWidget()
        self.webdesign_panel.setObjectName("WebdesignPanel")
        layout = QVBoxLayout(self.webdesign_panel)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(10)

        # ── Quick Setup ──────────────────────────────────────────────
        setup_group = QGroupBox("Quick Setup")
        setup_group.setObjectName("WebdesignSetupBox")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Page Type:"), 0, 0)
        self.webdesign_type_box = QComboBox()
        self.webdesign_type_box.addItems([
            "Landing Page", "Portfolio", "Dashboard", "Form", "Blog", "Component / Widget", "Other"
        ])
        setup_layout.addWidget(self.webdesign_type_box, 0, 1)

        setup_layout.addWidget(QLabel("Style:"), 0, 2)
        self.webdesign_style_box = QComboBox()
        self.webdesign_style_box.addItems(["Minimal", "Dark", "Corporate", "Playful", "Brutalist"])
        setup_layout.addWidget(self.webdesign_style_box, 0, 3)

        setup_layout.addWidget(QLabel("Colour Palette:"), 1, 0)
        self.webdesign_palette_input = QLineEdit()
        self.webdesign_palette_input.setPlaceholderText("e.g. #1a1a2e, #e94560  or  'ocean blues'")
        setup_layout.addWidget(self.webdesign_palette_input, 1, 1)

        setup_layout.addWidget(QLabel("Framework:"), 1, 2)
        self.webdesign_framework_box = QComboBox()
        self.webdesign_framework_box.addItems(["Vanilla", "Tailwind", "Bootstrap"])
        setup_layout.addWidget(self.webdesign_framework_box, 1, 3)

        setup_layout.addWidget(QLabel("Brief:"), 2, 0)
        self.webdesign_brief_input = QTextEdit()
        self.webdesign_brief_input.setPlaceholderText(
            "Describe what you want built — sections, features, content, interactions, etc."
        )
        self.webdesign_brief_input.setFixedHeight(70)
        setup_layout.addWidget(self.webdesign_brief_input, 2, 1, 1, 3)

        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)
        provider_row.addWidget(QLabel("Provider:"))
        self.webdesign_provider_box = QComboBox()
        self.webdesign_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.webdesign_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.webdesign_provider_box)

        provider_row.addWidget(QLabel("Model:"))
        self.webdesign_model_box = QComboBox()
        self.webdesign_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.webdesign_model_box)


        self.webdesign_generate_btn = QPushButton("Generate")
        self.webdesign_generate_btn.setMinimumWidth(140)
        self.webdesign_generate_btn.setObjectName("PrimaryAction")
        self.webdesign_generate_btn.clicked.connect(self.webdesign_generate)
        provider_row.addWidget(self.webdesign_generate_btn)

        self.webdesign_stop_btn = QPushButton("Stop")
        self.webdesign_stop_btn.setEnabled(False)
        self.webdesign_stop_btn.setObjectName("DangerAction")
        self.webdesign_stop_btn.clicked.connect(self.webdesign_stop)
        provider_row.addWidget(self.webdesign_stop_btn)

        setup_layout.addWidget(provider_row_container, 3, 0, 1, 4)
        layout.addWidget(setup_group)

        # ── Results: tabs left, sidebar right ───────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.webdesign_tabs = QTabWidget()

        self.webdesign_html_box = QTextEdit()
        self.webdesign_html_box.setReadOnly(True)
        self.webdesign_tabs.addTab(self.webdesign_html_box, "HTML")

        self.webdesign_css_box = QTextEdit()
        self.webdesign_css_box.setReadOnly(True)
        self.webdesign_tabs.addTab(self.webdesign_css_box, "CSS")

        self.webdesign_js_box = QTextEdit()
        self.webdesign_js_box.setReadOnly(True)
        self.webdesign_tabs.addTab(self.webdesign_js_box, "JS")

        results_splitter.addWidget(self.webdesign_tabs)

        # Sidebar
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 0, 0, 0)
        sidebar_layout.setSpacing(10)

        responsive_group = QGroupBox("Responsive")
        responsive_group.setObjectName("WebdesignResponsiveBox")
        responsive_layout = QVBoxLayout(responsive_group)
        self.webdesign_responsive_label = QLabel("—")
        self.webdesign_responsive_label.setAlignment(Qt.AlignCenter)
        self.webdesign_responsive_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4db8ff;")
        responsive_layout.addWidget(self.webdesign_responsive_label)
        sidebar_layout.addWidget(responsive_group)

        framework_group = QGroupBox("Framework Used")
        framework_group.setObjectName("WebdesignFrameworkBox")
        framework_layout = QVBoxLayout(framework_group)
        self.webdesign_framework_label = QLabel("—")
        self.webdesign_framework_label.setAlignment(Qt.AlignCenter)
        self.webdesign_framework_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        framework_layout.addWidget(self.webdesign_framework_label)
        sidebar_layout.addWidget(framework_group)

        lines_group = QGroupBox("Lines of Code")
        lines_group.setObjectName("WebdesignLinesBox")
        lines_layout = QVBoxLayout(lines_group)
        self.webdesign_lines_label = QLabel("—")
        self.webdesign_lines_label.setAlignment(Qt.AlignCenter)
        self.webdesign_lines_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #3cff88;")
        lines_layout.addWidget(self.webdesign_lines_label)
        sidebar_layout.addWidget(lines_group)

        sidebar_layout.addStretch()

        self.webdesign_copy_btn = QPushButton("Copy All")
        self.webdesign_copy_btn.setEnabled(False)
        self.webdesign_copy_btn.clicked.connect(self.webdesign_copy_all)
        sidebar_layout.addWidget(self.webdesign_copy_btn)

        self.webdesign_save_btn = QPushButton("Save .html")
        self.webdesign_save_btn.setEnabled(False)
        self.webdesign_save_btn.clicked.connect(self.webdesign_save)
        sidebar_layout.addWidget(self.webdesign_save_btn)

        self.webdesign_clear_btn = QPushButton("Clear")
        self.webdesign_clear_btn.clicked.connect(self.webdesign_clear)
        sidebar_layout.addWidget(self.webdesign_clear_btn)

        results_splitter.addWidget(sidebar)
        results_splitter.setSizes([680, 200])

        layout.addWidget(results_splitter, 1)

        self.webdesign_status_label = QLabel("")
        self.webdesign_status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.webdesign_status_label)

        self.webdesign_panel.hide()

        self.webdesign_provider_box.currentTextChanged.connect(self.webdesign_load_models)
        self.webdesign_load_models()


    # ── Wi-Fi Adapter panel ──────────────────────────────────────────────────
    def build_wifi_panel(self):
        self.wifi_panel = QWidget()
        self.wifi_panel.setObjectName("WiFiPanel")
        layout = QVBoxLayout(self.wifi_panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Quick Setup ─────────────────────────────────────────────────────
        setup_group = QGroupBox("Quick Setup")
        setup_group.setObjectName("WiFiSetupGroup")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.wifi_mode_box = QComboBox()
        self.wifi_mode_box.addItems([
            "Interface Info", "Scan Networks", "Signal Monitor",
            "Ping Test", "Kali Command Builder",
        ])
        self.wifi_mode_box.currentTextChanged.connect(self._wifi_on_mode_changed)
        setup_layout.addWidget(self.wifi_mode_box, 0, 1)

        setup_layout.addWidget(QLabel("Interface:"), 0, 2)
        self.wifi_interface_box = QComboBox()
        self.wifi_interface_box.addItems(["en0", "en1", "en2", "en3"])
        setup_layout.addWidget(self.wifi_interface_box, 0, 3)

        setup_layout.addWidget(QLabel("Target Host:"), 1, 0)
        self.wifi_target_input = QLineEdit()
        self.wifi_target_input.setPlaceholderText("e.g. 192.168.1.1  (used for Ping Test)")
        setup_layout.addWidget(self.wifi_target_input, 1, 1, 1, 3)

        layout.addWidget(setup_group)

        # ── Kali sub-form ───────────────────────────────────────────────────
        self.wifi_kali_group = QGroupBox("Kali Command Builder")
        self.wifi_kali_group.setObjectName("WiFiKaliGroup")
        kali_layout = QGridLayout(self.wifi_kali_group)
        kali_layout.setSpacing(6)

        kali_layout.addWidget(QLabel("Operation:"), 0, 0)
        self.wifi_kali_op_box = QComboBox()
        self.wifi_kali_op_box.addItems([
            "Handshake Capture", "Deauth Attack", "WPS Audit", "PMKID Attack",
        ])
        kali_layout.addWidget(self.wifi_kali_op_box, 0, 1)

        kali_layout.addWidget(QLabel("Adapter:"), 0, 2)
        self.wifi_kali_adapter_box = QComboBox()
        self.wifi_kali_adapter_box.addItems([
            "TL-WN722N (AR9271)",
            "AWUS036ACH (RTL8812AU)",
            "TL-WN725N V3 (RTL8188EU)",
        ])
        kali_layout.addWidget(self.wifi_kali_adapter_box, 0, 3)

        kali_layout.addWidget(QLabel("BSSID:"), 1, 0)
        self.wifi_kali_bssid_input = QLineEdit()
        self.wifi_kali_bssid_input.setPlaceholderText("e.g. AA:BB:CC:DD:EE:FF")
        kali_layout.addWidget(self.wifi_kali_bssid_input, 1, 1)

        kali_layout.addWidget(QLabel("Channel:"), 1, 2)
        self.wifi_kali_channel_input = QLineEdit()
        self.wifi_kali_channel_input.setPlaceholderText("e.g. 6")
        kali_layout.addWidget(self.wifi_kali_channel_input, 1, 3)

        kali_layout.addWidget(QLabel("Network (ESSID):"), 2, 0)
        self.wifi_kali_essid_input = QLineEdit()
        self.wifi_kali_essid_input.setPlaceholderText("e.g. MyHomeNetwork")
        kali_layout.addWidget(self.wifi_kali_essid_input, 2, 1, 1, 3)

        layout.addWidget(self.wifi_kali_group)
        self.wifi_kali_group.hide()

        # ── Provider / action row ────────────────────────────────────────────
        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)

        self.wifi_provider_box = QComboBox()
        self.wifi_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.wifi_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.wifi_provider_box)

        self.wifi_model_box = QComboBox()
        self.wifi_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.wifi_model_box)

        self.wifi_run_btn = QPushButton("Run")
        self.wifi_run_btn.setMinimumWidth(110)
        self.wifi_run_btn.setObjectName("PrimaryAction")
        self.wifi_run_btn.clicked.connect(self.wifi_run)
        provider_row.addWidget(self.wifi_run_btn)

        self.wifi_detect_btn = QPushButton("Detect Adapters")
        self.wifi_detect_btn.setToolTip("Scan USB bus for connected Wi-Fi adapters")
        self.wifi_detect_btn.clicked.connect(self.wifi_detect_adapters)
        provider_row.addWidget(self.wifi_detect_btn)

        self.wifi_stop_btn = QPushButton("Stop")
        self.wifi_stop_btn.setEnabled(False)
        self.wifi_stop_btn.setObjectName("DangerAction")
        self.wifi_stop_btn.clicked.connect(self.wifi_stop)
        provider_row.addWidget(self.wifi_stop_btn)

        self.wifi_help_btn = QPushButton("Help")


        self.wifi_help_btn.setObjectName("ChipBtn")
        self.wifi_help_btn.clicked.connect(self.show_agent_docs)
        provider_row.addWidget(self.wifi_help_btn)

        layout.addWidget(provider_row_container)

        ai_row = QHBoxLayout()
        self.wifi_ai_checkbox = QCheckBox("AI Analysis — feed results to LLM for interpretation")
        self.wifi_ai_checkbox.setChecked(True)
        ai_row.addWidget(self.wifi_ai_checkbox)
        ai_row.addStretch()
        layout.addLayout(ai_row)

        # ── Results splitter ─────────────────────────────────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.wifi_tabs = QTabWidget()

        self.wifi_raw_box = QTextBrowser()
        self.wifi_raw_box.setOpenExternalLinks(False)
        self.wifi_tabs.addTab(self.wifi_raw_box, "Raw Output")

        self.wifi_analysis_box = QTextBrowser()
        self.wifi_tabs.addTab(self.wifi_analysis_box, "AI Analysis")

        self.wifi_kali_cmd_box = QTextBrowser()
        self.wifi_tabs.addTab(self.wifi_kali_cmd_box, "Kali Commands")

        results_splitter.addWidget(self.wifi_tabs)

        # ── Sidebar indicators ───────────────────────────────────────────────
        indicators_widget = QWidget()
        indicators_layout = QVBoxLayout(indicators_widget)
        indicators_layout.setContentsMargins(6, 6, 6, 6)
        indicators_layout.setSpacing(8)

        adapter_group = QGroupBox("Adapter")
        adapter_group.setObjectName("WiFiAdapterGroup")
        adapter_layout = QVBoxLayout(adapter_group)
        self.wifi_adapter_label = QLabel("Not detected")
        self.wifi_adapter_label.setAlignment(Qt.AlignCenter)
        self.wifi_adapter_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #4db8ff;")
        self.wifi_adapter_label.setWordWrap(True)
        adapter_layout.addWidget(self.wifi_adapter_label)
        indicators_layout.addWidget(adapter_group)

        chipset_group = QGroupBox("Chipset")
        chipset_group.setObjectName("WiFiChipsetGroup")
        chipset_layout = QVBoxLayout(chipset_group)
        self.wifi_chipset_label = QLabel("—")
        self.wifi_chipset_label.setAlignment(Qt.AlignCenter)
        self.wifi_chipset_label.setStyleSheet("font-size: 12px; color: #aaa;")
        chipset_layout.addWidget(self.wifi_chipset_label)
        indicators_layout.addWidget(chipset_group)

        caps_group = QGroupBox("Capabilities")
        caps_group.setObjectName("WiFiCapsGroup")
        caps_layout = QVBoxLayout(caps_group)
        self.wifi_monitor_label = QLabel("Monitor  —")
        self.wifi_inject_label = QLabel("Injection  —")
        self.wifi_monitor_label.setStyleSheet("font-size: 12px;")
        self.wifi_inject_label.setStyleSheet("font-size: 12px;")
        caps_layout.addWidget(self.wifi_monitor_label)
        caps_layout.addWidget(self.wifi_inject_label)
        indicators_layout.addWidget(caps_group)

        signal_group = QGroupBox("Signal (RSSI)")
        signal_group.setObjectName("WiFiSignalGroup")
        signal_layout = QVBoxLayout(signal_group)
        self.wifi_signal_bar = QProgressBar()
        self.wifi_signal_bar.setMinimum(0)
        self.wifi_signal_bar.setMaximum(100)
        self.wifi_signal_bar.setValue(0)
        self.wifi_signal_bar.setTextVisible(True)
        signal_layout.addWidget(self.wifi_signal_bar)
        self.wifi_signal_val_label = QLabel("—")
        self.wifi_signal_val_label.setAlignment(Qt.AlignCenter)
        self.wifi_signal_val_label.setStyleSheet("font-size: 11px; color: #aaa;")
        signal_layout.addWidget(self.wifi_signal_val_label)
        indicators_layout.addWidget(signal_group)

        sec_group = QGroupBox("Security")
        sec_group.setObjectName("WiFiSecGroup")
        sec_layout = QVBoxLayout(sec_group)
        self.wifi_security_label = QLabel("—")
        self.wifi_security_label.setAlignment(Qt.AlignCenter)
        self.wifi_security_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        sec_layout.addWidget(self.wifi_security_label)
        indicators_layout.addWidget(sec_group)

        indicators_layout.addStretch()

        self.wifi_save_btn = QPushButton("Save Output")
        self.wifi_save_btn.setEnabled(False)
        self.wifi_save_btn.clicked.connect(self.wifi_save)
        indicators_layout.addWidget(self.wifi_save_btn)

        self.wifi_clear_btn = QPushButton("Clear")
        self.wifi_clear_btn.clicked.connect(self.wifi_clear)
        indicators_layout.addWidget(self.wifi_clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([680, 220])
        layout.addWidget(results_splitter, 1)

        self.wifi_status_label = QLabel("")
        self.wifi_status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.wifi_status_label)

        self.wifi_panel.hide()

        self.wifi_provider_box.currentTextChanged.connect(self.wifi_load_models)
        self.wifi_load_models()

    # ── Wi-Fi handlers ───────────────────────────────────────────────────────
    def _wifi_on_mode_changed(self, mode: str):
        is_kali = mode == "Kali Command Builder"
        self.wifi_kali_group.setVisible(is_kali)
        self.wifi_ai_checkbox.setEnabled(not is_kali)
        if is_kali:
            self.wifi_tabs.setCurrentIndex(2)

    def wifi_load_models(self):
        provider = self.wifi_provider_box.currentText()
        self.wifi_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
        except Exception:
            models = []
        self.wifi_model_box.addItems(models)

    def wifi_detect_adapters(self):
        self.wifi_status_label.setText("Scanning USB bus...")
        self.wifi_detect_btn.setEnabled(False)
        adapters = detect_usb_adapters()
        self.wifi_detect_btn.setEnabled(True)

        if not adapters or "error" in adapters[0]:
            err = adapters[0].get("error", "Unknown error") if adapters else "No adapters found"
            self.wifi_adapter_label.setText("None found")
            self.wifi_chipset_label.setText("—")
            self.wifi_monitor_label.setText("Monitor  —")
            self.wifi_inject_label.setText("Injection  —")
            self.wifi_raw_box.setPlainText(f"[Adapter Detection]\nNo known Wi-Fi adapters detected on USB bus.\n{err}")
            self.wifi_status_label.setText("No known adapters detected.")
            self._wifi_detected_adapter = {}
            return

        adapter = adapters[0]
        self._wifi_detected_adapter = adapter
        self.wifi_adapter_label.setText(adapter.get("name", "Unknown"))
        self.wifi_chipset_label.setText(adapter.get("chipset", "—"))

        mon_ok = adapter.get("monitor", False)
        inj_ok = adapter.get("inject", False)
        self.wifi_monitor_label.setText(f"Monitor  {'✅' if mon_ok else '❌'}")
        self.wifi_inject_label.setText(f"Injection  {'✅' if inj_ok else '❌'}")
        self.wifi_monitor_label.setStyleSheet(f"font-size: 12px; color: {'#3cff88' if mon_ok else '#ff5555'};")
        self.wifi_inject_label.setStyleSheet(f"font-size: 12px; color: {'#3cff88' if inj_ok else '#ff5555'};")

        bands = adapter.get("bands", "—")
        driver = adapter.get("driver_note", "")
        iface = adapter.get("kali_iface", "wlan0")
        report = (
            f"[Adapter Detected]\n"
            f"Name    : {adapter.get('name')}\n"
            f"Chipset : {adapter.get('chipset')}\n"
            f"Bands   : {bands}\n"
            f"Monitor : {'Yes' if mon_ok else 'No'}\n"
            f"Inject  : {'Yes' if inj_ok else 'No'}\n"
            f"Kali IF : {iface}\n"
            f"Note    : {driver}\n"
        )
        if len(adapters) > 1:
            report += f"\n[+] {len(adapters) - 1} additional adapter(s) also detected.\n"
        self.wifi_raw_box.setPlainText(report)
        self.wifi_tabs.setCurrentIndex(0)
        self.wifi_status_label.setText(f"Detected: {adapter.get('name')} ({adapter.get('chipset')})")

    def wifi_run(self):
        mode = self.wifi_mode_box.currentText()

        if mode == "Kali Command Builder":
            self._wifi_run_kali_builder()
            return

        self._wifi_clear_displays()
        self._last_wifi_response = ""
        self.wifi_run_btn.setEnabled(False)
        self.wifi_stop_btn.setEnabled(True)
        self.wifi_save_btn.setEnabled(False)
        self.wifi_status_label.setText(f"Running: {mode}…")
        self.wifi_tabs.setCurrentIndex(0)

        iface = self.wifi_interface_box.currentText()

        if mode == "Interface Info":
            cmd = ["networksetup", "-listallhardwareports"]
        elif mode == "Scan Networks":
            cmd = [AIRPORT, "-s"]
        elif mode == "Signal Monitor":
            cmd = [AIRPORT, "-I"]
        elif mode == "Ping Test":
            target = self.wifi_target_input.text().strip()
            if not target:
                QMessageBox.warning(self, "Missing Target", "Enter a target host or IP for Ping Test.")
                self.wifi_run_btn.setEnabled(True)
                self.wifi_stop_btn.setEnabled(False)
                return
            cmd = ["ping", "-c", "8", target]
        else:
            cmd = [AIRPORT, "-I"]

        self.wifi_scan_worker = SubprocessWorker(cmd)
        self.wifi_scan_worker.finished_signal.connect(self._wifi_scan_finished)
        self.wifi_scan_worker.error_signal.connect(self._wifi_scan_error)
        self.wifi_scan_worker.start()

    def _wifi_run_kali_builder(self):
        op = self.wifi_kali_op_box.currentText()
        adapter_name = self.wifi_kali_adapter_box.currentText()
        bssid = self.wifi_kali_bssid_input.text().strip()
        channel = self.wifi_kali_channel_input.text().strip()
        essid = self.wifi_kali_essid_input.text().strip()

        adapter_map = {
            "TL-WN722N (AR9271)": {"name": "TL-WN722N", "chipset": "AR9271", "monitor": True, "inject": True, "kali_iface": "wlan0", "driver_note": "ath9k_htc — works out of the box on Kali."},
            "AWUS036ACH (RTL8812AU)": {"name": "AWUS036ACH", "chipset": "RTL8812AU", "monitor": True, "inject": True, "kali_iface": "wlan0", "driver_note": "Install driver in Kali: sudo apt install realtek-rtl88xxau-dkms"},
            "TL-WN725N V3 (RTL8188EU)": {"name": "TL-WN725N V3", "chipset": "RTL8188EU", "monitor": True, "inject": False, "kali_iface": "wlan0", "driver_note": "Limited injection support — passive monitoring only."},
        }
        adapter = adapter_map.get(adapter_name, list(adapter_map.values())[0])
        cmds = build_kali_commands(op, adapter, bssid, channel, essid)

        self.wifi_kali_cmd_box.setPlainText(cmds)
        self.wifi_tabs.setCurrentIndex(2)
        self._last_wifi_response = cmds
        self.wifi_save_btn.setEnabled(True)
        self.wifi_status_label.setText(f"Kali commands generated: {op}")

        if self.wifi_ai_checkbox.isEnabled() and self.wifi_ai_checkbox.isChecked():
            model = self.wifi_model_box.currentText()
            if model:
                provider = self.wifi_provider_box.currentText()
                prompt = f"Explain the following Kali Linux Wi-Fi attack command sequence for an authorised penetration test. Break down what each step does and what to watch for:\n\n{cmds}"
                agent = self.agent_instances["wifi"]
                messages = agent.build_messages(prompt)
                if not self.authorize_request("wifi", provider, model, prompt):
                    return
                self.wifi_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
                self.wifi_worker.token_signal.connect(self._wifi_on_token)
                self.wifi_worker.finished_signal.connect(self._wifi_on_finished)
                self.wifi_worker.usage_signal.connect(lambda u: self.note_request_usage("wifi", u))
                self.wifi_worker.error_signal.connect(self._wifi_on_error)
                self.wifi_worker.start()
                self.wifi_tabs.setCurrentIndex(1)

    def _wifi_scan_finished(self, raw: str):
        self.wifi_raw_box.setPlainText(raw)
        self.wifi_status_label.setText("Scan complete.")
        self._update_wifi_indicators(raw)

        if self.wifi_ai_checkbox.isChecked():
            model = self.wifi_model_box.currentText()
            if not model:
                self.wifi_run_btn.setEnabled(True)
                self.wifi_stop_btn.setEnabled(False)
                return
            mode = self.wifi_mode_box.currentText()
            provider = self.wifi_provider_box.currentText()
            prompt = f"Mode: {mode}\n\nRaw output:\n{raw}\n\nAnalyse this Wi-Fi scan result."
            agent = self.agent_instances["wifi"]
            messages = agent.build_messages(prompt)
            if not self.authorize_request("wifi", provider, model, prompt):
                return
            self.wifi_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
            self.wifi_worker.token_signal.connect(self._wifi_on_token)
            self.wifi_worker.finished_signal.connect(self._wifi_on_finished)
            self.wifi_worker.usage_signal.connect(lambda u: self.note_request_usage("wifi", u))
            self.wifi_worker.error_signal.connect(self._wifi_on_error)
            self.wifi_worker.start()
            self.wifi_tabs.setCurrentIndex(1)
            self.wifi_status_label.setText("Running AI analysis…")
        else:
            self._last_wifi_response = raw
            self.wifi_run_btn.setEnabled(True)
            self.wifi_stop_btn.setEnabled(False)
            self.wifi_save_btn.setEnabled(True)

    def _wifi_scan_error(self, error: str):
        self.wifi_raw_box.setPlainText(f"[Error]\n{error}")
        self.wifi_status_label.setText("Error running scan.")
        self.wifi_run_btn.setEnabled(True)
        self.wifi_stop_btn.setEnabled(False)

    def _wifi_on_token(self, token: str):
        self._last_wifi_response += token
        self.wifi_analysis_box.setPlainText(self._last_wifi_response)
        self.wifi_analysis_box.moveCursor(QTextCursor.End)

    def _wifi_on_finished(self, full_response: str):
        self.record_request("wifi", full_response)
        self._last_wifi_response = full_response
        self.wifi_analysis_box.setPlainText(full_response)
        self.wifi_status_label.setText("Analysis complete.")
        self.wifi_run_btn.setEnabled(True)
        self.wifi_stop_btn.setEnabled(False)
        self.wifi_save_btn.setEnabled(True)

    def _wifi_on_error(self, error: str):
        self.abandon_request("wifi")
        self.wifi_analysis_box.setPlainText(f"[Error] {error}")
        self.wifi_status_label.setText("Error.")
        self.wifi_run_btn.setEnabled(True)
        self.wifi_stop_btn.setEnabled(False)

    def wifi_stop(self):
        if self.wifi_scan_worker is not None and self.wifi_scan_worker.isRunning():
            self.wifi_scan_worker.cancel()
        if self.wifi_worker is not None and self.wifi_worker.isRunning():
            self.wifi_worker.cancel()
        self.wifi_status_label.setText("Stopped.")
        self.wifi_run_btn.setEnabled(True)
        self.wifi_stop_btn.setEnabled(False)

    def wifi_save(self):
        if not self._last_wifi_response:
            return
        mode = self.wifi_mode_box.currentText().lower().replace(" ", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"wifi_{mode}_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Wi-Fi Output", str(DATA_DIR / default_name), "Text files (*.txt);;All files (*)"
        )
        if path:
            Path(path).write_text(self._last_wifi_response, encoding="utf-8")
            self.wifi_status_label.setText(f"Saved to {Path(path).name}")

    def wifi_clear(self):
        self._wifi_clear_displays()
        self.wifi_target_input.clear()
        self.wifi_kali_bssid_input.clear()
        self.wifi_kali_channel_input.clear()
        self.wifi_kali_essid_input.clear()
        self.wifi_status_label.setText("")
        self._last_wifi_response = ""

    def _wifi_clear_displays(self):
        self.wifi_raw_box.clear()
        self.wifi_analysis_box.clear()
        self.wifi_kali_cmd_box.clear()
        self.wifi_signal_bar.setValue(0)
        self.wifi_signal_val_label.setText("—")
        self.wifi_security_label.setText("—")
        self.wifi_save_btn.setEnabled(False)

    def _update_wifi_indicators(self, raw: str):
        rssi_m = re.search(r"agrCtlRSSI:\s*(-\d+)", raw)
        if rssi_m:
            rssi = int(rssi_m.group(1))
            quality = max(0, min(100, 2 * (rssi + 100)))
            self.wifi_signal_bar.setValue(quality)
            self.wifi_signal_val_label.setText(f"{rssi} dBm")
            bar_color = "#3cff88" if quality >= 60 else "#f0c040" if quality >= 30 else "#ff5555"
            self.wifi_signal_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 3px; }}"
            )

        sec_m = re.search(r"link auth:\s*(\S+)", raw, re.IGNORECASE)
        if sec_m:
            self.wifi_security_label.setText(sec_m.group(1).upper())
        elif "WPA3" in raw:
            self.wifi_security_label.setText("WPA3")
        elif "WPA2" in raw:
            self.wifi_security_label.setText("WPA2")
        elif "WPA" in raw:
            self.wifi_security_label.setText("WPA")
        elif "WEP" in raw:
            self.wifi_security_label.setText("WEP")
            self.wifi_security_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff5555;")


    # ── Web Design handlers ──────────────────────────────────────────────────
    def webdesign_load_models(self):
        provider = self.webdesign_provider_box.currentText()
        self.webdesign_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
            for m in models:
                self.webdesign_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("webdesign: load models", exc, self.webdesign_model_box)

    def webdesign_generate(self):
        page_type = self.webdesign_type_box.currentText()
        style = self.webdesign_style_box.currentText()
        palette = self.webdesign_palette_input.text().strip()
        framework = self.webdesign_framework_box.currentText()
        brief = self.webdesign_brief_input.toPlainText().strip()
        provider = self.webdesign_provider_box.currentText()
        model = self.webdesign_model_box.currentText()

        if not brief:
            QMessageBox.warning(self, "Missing Input", "Please enter a brief describing what you want built.")
            return
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        prompt_parts = [
            f"Page Type: {page_type}",
            f"Style: {style}",
            f"Framework: {framework}",
        ]
        if palette:
            prompt_parts.append(f"Colour Palette: {palette}")
        prompt_parts.append(f"\nBrief:\n{brief}")

        prompt = "\n".join(prompt_parts)
        agent = self.agent_instances["webdesign"]
        messages = agent.build_messages(prompt)

        self._webdesign_clear_displays()
        self._last_webdesign_response = ""
        self.webdesign_status_label.setText("Generating...")
        self.webdesign_generate_btn.setEnabled(False)
        self.webdesign_stop_btn.setEnabled(True)
        self.webdesign_save_btn.setEnabled(False)
        self.webdesign_copy_btn.setEnabled(False)

        if not self.authorize_request("webdesign", provider, model, prompt):
            return
        self.webdesign_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
        self.webdesign_worker.token_signal.connect(self._webdesign_on_token)
        self.webdesign_worker.finished_signal.connect(self._webdesign_on_finished)
        self.webdesign_worker.usage_signal.connect(lambda u: self.note_request_usage("webdesign", u))
        self.webdesign_worker.error_signal.connect(self._webdesign_on_error)
        self.webdesign_worker.start()

    def _webdesign_on_token(self, token: str):
        self._last_webdesign_response += token
        self.webdesign_html_box.setPlainText(self._last_webdesign_response)
        self.webdesign_html_box.moveCursor(QTextCursor.End)

    def _webdesign_on_finished(self, full_response: str):
        self.record_request("webdesign", full_response)
        self._last_webdesign_response = full_response
        self._populate_webdesign_tabs(full_response)
        self._update_webdesign_indicators(full_response)
        self.webdesign_status_label.setText("Generation complete.")
        self.webdesign_generate_btn.setEnabled(True)
        self.webdesign_stop_btn.setEnabled(False)
        self.webdesign_save_btn.setEnabled(True)
        self.webdesign_copy_btn.setEnabled(True)

    def _webdesign_on_error(self, error: str):
        self.abandon_request("webdesign")
        self.webdesign_html_box.setPlainText(f"[Error] {error}")
        self.webdesign_status_label.setText("Error.")
        self.webdesign_generate_btn.setEnabled(True)
        self.webdesign_stop_btn.setEnabled(False)

    def webdesign_stop(self):
        if self.webdesign_worker is not None and self.webdesign_worker.isRunning():
            self.webdesign_worker.cancel()
        self.webdesign_status_label.setText("Stopped.")
        self.webdesign_generate_btn.setEnabled(True)
        self.webdesign_stop_btn.setEnabled(False)

    def webdesign_save(self):
        if not self._last_webdesign_response:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"webdesign_{ts}.html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save HTML File", str(DATA_DIR / default_name),
            "HTML files (*.html);;All files (*)"
        )
        if path:
            full_html = self._extract_full_html(self._last_webdesign_response)
            Path(path).write_text(full_html, encoding="utf-8")

    def webdesign_copy_all(self):
        if not self._last_webdesign_response:
            return
        full_html = self._extract_full_html(self._last_webdesign_response)
        QApplication.clipboard().setText(full_html)
        self.webdesign_status_label.setText("Copied to clipboard.")

    def webdesign_clear(self):
        self._webdesign_clear_displays()
        self.webdesign_brief_input.clear()
        self.webdesign_status_label.setText("")
        self._last_webdesign_response = ""

    def _webdesign_clear_displays(self):
        self.webdesign_html_box.clear()
        self.webdesign_css_box.clear()
        self.webdesign_js_box.clear()
        self.webdesign_responsive_label.setText("—")
        self.webdesign_framework_label.setText("—")
        self.webdesign_lines_label.setText("—")
        self.webdesign_save_btn.setEnabled(False)
        self.webdesign_copy_btn.setEnabled(False)

    def _extract_full_html(self, text: str) -> str:
        import re as _re
        m = _re.search("```(?:html)?\\s*\\n(.*?)```", text, _re.DOTALL | _re.IGNORECASE)
        return m.group(1).strip() if m else text.strip()

    def _populate_webdesign_tabs(self, text: str):
        import re as _re
        # Full HTML in first tab
        full = self._extract_full_html(text)
        self.webdesign_html_box.setPlainText(full)

        # Extract <style> blocks into CSS tab
        css_parts = _re.findall(r"<style[^>]*>(.*?)</style>", full, _re.DOTALL | _re.IGNORECASE)
        self.webdesign_css_box.setPlainText("\n\n".join(p.strip() for p in css_parts) if css_parts else "")

        # Extract <script> blocks into JS tab
        js_parts = _re.findall(r"<script[^>]*>(.*?)</script>", full, _re.DOTALL | _re.IGNORECASE)
        self.webdesign_js_box.setPlainText("\n\n".join(p.strip() for p in js_parts) if js_parts else "")

    def _update_webdesign_indicators(self, text: str):
        import re as _re
        full = self._extract_full_html(text)

        # Responsive detection
        if "viewport" in full.lower() or "@media" in full.lower():
            self.webdesign_responsive_label.setText("Mobile-first")
        else:
            self.webdesign_responsive_label.setText("Desktop")

        # Framework
        fw = self.webdesign_framework_box.currentText()
        self.webdesign_framework_label.setText(fw)

        # Line count
        line_count = len(full.splitlines())
        self.webdesign_lines_label.setText(str(line_count))

    # ── NFL Prop Bet handlers ────────────────────────────────────────────────
    def build_fiverr_panel(self):
        self.fiverr_panel = QWidget()
        self.fiverr_panel.setObjectName("FiverrPanel")
        layout = QVBoxLayout(self.fiverr_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        brief_group = QGroupBox("Client Brief")
        brief_group.setObjectName("FiverrBriefBox")
        brief_layout = QGridLayout(brief_group)
        brief_layout.setSpacing(6)

        brief_layout.addWidget(QLabel("Business Name:"), 0, 0)
        self.fiverr_name_input = QLineEdit()
        self.fiverr_name_input.setPlaceholderText("e.g. Apex Fitness Studio")
        brief_layout.addWidget(self.fiverr_name_input, 0, 1, 1, 3)

        brief_layout.addWidget(QLabel("Industry / Niche:"), 1, 0)
        self.fiverr_industry_input = QLineEdit()
        self.fiverr_industry_input.setPlaceholderText("e.g. fitness, law firm, bakery")
        brief_layout.addWidget(self.fiverr_industry_input, 1, 1)

        brief_layout.addWidget(QLabel("Style:"), 1, 2)
        self.fiverr_style_box = QComboBox()
        self.fiverr_style_box.addItems(["Minimalist", "Bold", "Vintage", "Playful", "Corporate", "Luxury", "Futuristic"])
        brief_layout.addWidget(self.fiverr_style_box, 1, 3)

        brief_layout.addWidget(QLabel("Primary Colors:"), 2, 0)
        self.fiverr_colors_input = QLineEdit()
        self.fiverr_colors_input.setPlaceholderText("e.g. navy blue and gold")
        brief_layout.addWidget(self.fiverr_colors_input, 2, 1)

        brief_layout.addWidget(QLabel("# Concepts:"), 2, 2)
        from PySide6.QtWidgets import QSpinBox
        self.fiverr_count_spin = QSpinBox()
        self.fiverr_count_spin.setRange(1, 4)
        self.fiverr_count_spin.setValue(2)
        brief_layout.addWidget(self.fiverr_count_spin, 2, 3)

        brief_layout.addWidget(QLabel("Notes:"), 3, 0)
        self.fiverr_notes_input = QTextEdit()
        self.fiverr_notes_input.setPlaceholderText("Optional: tagline, mood, target audience, competitors to avoid...")
        self.fiverr_notes_input.setFixedHeight(55)
        brief_layout.addWidget(self.fiverr_notes_input, 3, 1, 1, 3)

        # Row 1: Provider + Model (their own row so they don't squeeze the action buttons)
        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)
        provider_row.addWidget(QLabel("Text Provider:"))
        self.fiverr_provider_box = QComboBox()
        self.fiverr_provider_box.addItems(["anthropic", "openai", "deepseek", "kimi", "gemini", "qwen", "ollama"])
        self.fiverr_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.fiverr_provider_box)

        provider_row.addWidget(QLabel("Model:"))
        self.fiverr_model_box = QComboBox()
        self.fiverr_model_box.setMinimumWidth(180)
        provider_row.addWidget(self.fiverr_model_box, 1)
        brief_layout.addWidget(provider_row_container, 4, 0, 1, 4)

        # Row 2: All four action buttons get their own row with full width
        action_row = QHBoxLayout()
        action_row.addStretch()

        self.fiverr_generate_btn = QPushButton("Generate Logos")
        self.fiverr_generate_btn.setMinimumWidth(140)
        self.fiverr_generate_btn.setObjectName("PrimaryAction")
        self.fiverr_generate_btn.clicked.connect(self.fiverr_generate_logos)
        action_row.addWidget(self.fiverr_generate_btn)

        self.fiverr_delivery_btn = QPushButton("Delivery Msg")
        self.fiverr_delivery_btn.setMinimumWidth(130)
        self.fiverr_delivery_btn.setObjectName("PrimaryAction")
        self.fiverr_delivery_btn.clicked.connect(self.fiverr_write_delivery)
        action_row.addWidget(self.fiverr_delivery_btn)

        self.fiverr_gig_btn = QPushButton("Gig Description")
        self.fiverr_gig_btn.setMinimumWidth(140)
        self.fiverr_gig_btn.setObjectName("PrimaryAction")
        self.fiverr_gig_btn.clicked.connect(self.fiverr_write_gig)
        action_row.addWidget(self.fiverr_gig_btn)

        self.fiverr_stop_btn = QPushButton("Stop")
        self.fiverr_stop_btn.setEnabled(False)
        self.fiverr_stop_btn.setObjectName("DangerAction")
        self.fiverr_stop_btn.clicked.connect(self.fiverr_stop)
        action_row.addWidget(self.fiverr_stop_btn)

        brief_layout.addLayout(action_row, 5, 0, 1, 4)
        layout.addWidget(brief_group)

        results_splitter = QSplitter(Qt.Horizontal)
        self.fiverr_tabs = QTabWidget()

        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(6)
        preview_top_container = QWidget()
        preview_top = FlowLayout(preview_top_container, spacing=6)
        self.fiverr_preview_status = QLabel("No logos generated yet.")
        self.fiverr_preview_status.setStyleSheet("color: #888; font-style: italic;")
        preview_top.addWidget(self.fiverr_preview_status)
        self.fiverr_save_images_btn = QPushButton("Save All Images")
        self.fiverr_save_images_btn.setEnabled(False)
        self.fiverr_save_images_btn.clicked.connect(self.fiverr_save_images)
        preview_top.addWidget(self.fiverr_save_images_btn)
        preview_layout.addWidget(preview_top_container)
        self.fiverr_logo_grid = QWidget()
        self.fiverr_logo_grid_layout = QHBoxLayout(self.fiverr_logo_grid)
        self.fiverr_logo_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.fiverr_logo_grid_layout.setSpacing(12)
        preview_layout.addWidget(self.fiverr_logo_grid)
        preview_layout.addStretch()
        self.fiverr_tabs.addTab(preview_widget, "Logo Preview")

        self.fiverr_delivery_box = QTextEdit()
        self.fiverr_delivery_box.setPlaceholderText(
            "Click 'Write Delivery Msg' to generate a professional client delivery message..."
        )
        self.fiverr_tabs.addTab(self.fiverr_delivery_box, "Delivery Message")

        self.fiverr_gig_box = QTextEdit()
        self.fiverr_gig_box.setPlaceholderText(
            "Click 'Write Gig Description' to generate a Fiverr listing..."
        )
        self.fiverr_tabs.addTab(self.fiverr_gig_box, "Gig Description")

        results_splitter.addWidget(self.fiverr_tabs)

        from PySide6.QtWidgets import QTableWidget, QHeaderView
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 0, 0, 0)
        sidebar_layout.setSpacing(10)
        sidebar.setMaximumWidth(190)

        status_group = QGroupBox("Status")
        status_group.setObjectName("FiverrStatusBox")
        status_layout = QVBoxLayout(status_group)
        self.fiverr_status_label = QLabel("Idle")
        self.fiverr_status_label.setWordWrap(True)
        self.fiverr_status_label.setStyleSheet("font-size: 12px; color: #888;")
        status_layout.addWidget(self.fiverr_status_label)
        sidebar_layout.addWidget(status_group)

        cost_group = QGroupBox("Est. Cost")
        cost_group.setObjectName("FiverrCostBox")
        cost_layout = QVBoxLayout(cost_group)
        self.fiverr_cost_label = QLabel("—")
        self.fiverr_cost_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #3cff88;")
        cost_note = QLabel("DALL-E 3: ~$0.04/image\n(standard quality)")
        cost_note.setStyleSheet("font-size: 10px; color: #666;")
        cost_note.setWordWrap(True)
        cost_layout.addWidget(self.fiverr_cost_label)
        cost_layout.addWidget(cost_note)
        sidebar_layout.addWidget(cost_group)

        order_group = QGroupBox("Order Log")
        order_group.setObjectName("FiverrOrderBox")
        order_layout = QVBoxLayout(order_group)
        self.fiverr_order_table = QTableWidget(0, 3)
        self.fiverr_order_table.setHorizontalHeaderLabels(["Business", "#", "Status"])
        self.fiverr_order_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.fiverr_order_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.fiverr_order_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.fiverr_order_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fiverr_order_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fiverr_order_table.setAlternatingRowColors(True)
        self.fiverr_order_table.verticalHeader().setVisible(False)
        order_layout.addWidget(self.fiverr_order_table)
        self.fiverr_clear_btn = QPushButton("Clear")
        self.fiverr_clear_btn.clicked.connect(self.fiverr_clear)
        order_layout.addWidget(self.fiverr_clear_btn)
        sidebar_layout.addWidget(order_group)

        results_splitter.addWidget(sidebar)
        results_splitter.setSizes([700, 180])
        layout.addWidget(results_splitter)

        self.fiverr_panel.hide()
        self.fiverr_provider_box.currentTextChanged.connect(self.fiverr_load_models)
        self.fiverr_load_models()

    # ── Fiverr handlers ──────────────────────────────────────────────────────
    def fiverr_load_models(self):
        provider = self.fiverr_provider_box.currentText()
        self.fiverr_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
            for m in models:
                self.fiverr_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("fiverr: load models", exc, self.fiverr_model_box)

    def _fiverr_get_brief(self) -> dict:
        return {
            "business_name": self.fiverr_name_input.text().strip(),
            "industry": self.fiverr_industry_input.text().strip(),
            "style": self.fiverr_style_box.currentText(),
            "colors": self.fiverr_colors_input.text().strip(),
            "notes": self.fiverr_notes_input.toPlainText().strip(),
        }

    def fiverr_generate_logos(self):
        brief = self._fiverr_get_brief()
        if not brief["business_name"]:
            QMessageBox.warning(self, "Missing Input", "Please enter a business name.")
            return
        if not OpenAIClientWrapper.key_available():
            QMessageBox.warning(self, "No API Key", "OPENAI_API_KEY is required for DALL-E 3 image generation.")
            return

        count = self.fiverr_count_spin.value()
        provider = self.fiverr_provider_box.currentText()
        model = self.fiverr_model_box.currentText()

        agent = self.agent_instances["fiverr"]
        messages = agent.build_image_prompt_request(brief)

        self.fiverr_status_label.setText("Building image prompt...")
        self.fiverr_generate_btn.setEnabled(False)
        self.fiverr_delivery_btn.setEnabled(False)
        self.fiverr_gig_btn.setEnabled(False)
        self.fiverr_stop_btn.setEnabled(True)
        self._fiverr_clear_logo_grid()

        if not self.authorize_request("fiverr", provider, model, messages[-1]["content"] if messages else ""):
            return
        self.fiverr_text_worker = ChatWorker(self.run_backend, provider, model, messages, "")
        self.fiverr_text_worker.finished_signal.connect(self._fiverr_on_prompt_ready)
        self.fiverr_text_worker.usage_signal.connect(lambda u: self.note_request_usage("fiverr", u))
        self.fiverr_text_worker.error_signal.connect(self._fiverr_on_text_error)
        self.fiverr_text_worker.start()
        self._fiverr_pending_count = count
        self._fiverr_pending_brief = brief

    def _fiverr_on_prompt_ready(self, image_prompt: str):
        self.record_request("fiverr", image_prompt)
        image_prompt = image_prompt.strip()
        count = self._fiverr_pending_count
        brief = self._fiverr_pending_brief
        save_dir = DATA_DIR / "fiverr_output" / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.fiverr_status_label.setText(f"Generating {count} concept(s)...")
        self.fiverr_cost_label.setText(f"~${0.04 * count:.2f}")

        self.fiverr_image_worker = FiverrImageWorker(self.openai, image_prompt, count, save_dir)
        self.fiverr_image_worker.image_ready_signal.connect(self._fiverr_on_image_ready)
        self.fiverr_image_worker.all_done_signal.connect(self._fiverr_on_all_done)
        self.fiverr_image_worker.error_signal.connect(self._fiverr_on_image_error)
        self.fiverr_image_worker.status_signal.connect(lambda s: self.fiverr_status_label.setText(s))
        self.fiverr_image_worker.start()

        row = self.fiverr_order_table.rowCount()
        self.fiverr_order_table.insertRow(row)
        from PySide6.QtWidgets import QTableWidgetItem
        self.fiverr_order_table.setItem(row, 0, QTableWidgetItem(brief.get("business_name", "")))
        self.fiverr_order_table.setItem(row, 1, QTableWidgetItem(str(count)))
        self.fiverr_order_table.setItem(row, 2, QTableWidgetItem("Generating"))
        self._fiverr_order_row = row

    def _fiverr_on_image_ready(self, path: str, index: int):
        from PySide6.QtGui import QPixmap
        lbl = QLabel()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(pixmap)
        else:
            lbl.setText(f"[Concept {index + 1}]")
        lbl.setToolTip(path)
        lbl.setAlignment(Qt.AlignCenter)
        self.fiverr_logo_grid_layout.addWidget(lbl)
        self._fiverr_image_paths.append(path)
        self.fiverr_preview_status.setText(f"Concept {index + 1} ready — {Path(path).name}")
        self.fiverr_tabs.setCurrentIndex(0)

    def _fiverr_on_all_done(self, paths: list):
        self._fiverr_image_paths = paths
        self.fiverr_status_label.setText(f"Done — {len(paths)} logo(s) generated.")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)
        self.fiverr_save_images_btn.setEnabled(True)
        if hasattr(self, "_fiverr_order_row"):
            from PySide6.QtWidgets import QTableWidgetItem
            self.fiverr_order_table.setItem(self._fiverr_order_row, 2, QTableWidgetItem("Done"))

    def _fiverr_on_image_error(self, error: str):
        self.fiverr_status_label.setText(f"Error: {error}")
        self.fiverr_preview_status.setText(f"[Error] {error}")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)
        if hasattr(self, "_fiverr_order_row"):
            from PySide6.QtWidgets import QTableWidgetItem
            self.fiverr_order_table.setItem(self._fiverr_order_row, 2, QTableWidgetItem("Error"))

    def _fiverr_on_text_error(self, error: str):
        self.abandon_request("fiverr")
        self.fiverr_status_label.setText(f"Error: {error}")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)

    def fiverr_write_delivery(self):
        brief = self._fiverr_get_brief()
        provider = self.fiverr_provider_box.currentText()
        model = self.fiverr_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return
        agent = self.agent_instances["fiverr"]
        messages = agent.build_messages("Write a professional delivery message for this logo order.", brief)
        self.fiverr_delivery_box.clear()
        self.fiverr_status_label.setText("Writing delivery message...")
        self.fiverr_generate_btn.setEnabled(False)
        self.fiverr_delivery_btn.setEnabled(False)
        self.fiverr_gig_btn.setEnabled(False)
        self.fiverr_stop_btn.setEnabled(True)
        self.fiverr_tabs.setCurrentIndex(1)
        if not self.authorize_request("fiverr", provider, model, messages[-1]["content"] if messages else ""):
            return
        self.fiverr_text_worker = ChatWorker(self.run_backend, provider, model, messages, "")
        self.fiverr_text_worker.token_signal.connect(self._fiverr_on_delivery_token)
        self.fiverr_text_worker.finished_signal.connect(self._fiverr_on_delivery_done)
        self.fiverr_text_worker.usage_signal.connect(lambda u: self.note_request_usage("fiverr", u))
        self.fiverr_text_worker.error_signal.connect(self._fiverr_on_text_error)
        self.fiverr_text_worker.start()

    def _fiverr_on_delivery_token(self, token: str):
        self.fiverr_delivery_box.moveCursor(QTextCursor.End)
        self.fiverr_delivery_box.insertPlainText(token)

    def _fiverr_on_delivery_done(self, _full: str):
        self.record_request("fiverr", _full)
        self.fiverr_status_label.setText("Delivery message ready.")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)

    def fiverr_write_gig(self):
        brief = self._fiverr_get_brief()
        provider = self.fiverr_provider_box.currentText()
        model = self.fiverr_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return
        agent = self.agent_instances["fiverr"]
        messages = agent.build_messages("Write a complete Fiverr gig description for logo design services.", brief)
        self.fiverr_gig_box.clear()
        self.fiverr_status_label.setText("Writing gig description...")
        self.fiverr_generate_btn.setEnabled(False)
        self.fiverr_delivery_btn.setEnabled(False)
        self.fiverr_gig_btn.setEnabled(False)
        self.fiverr_stop_btn.setEnabled(True)
        self.fiverr_tabs.setCurrentIndex(2)
        if not self.authorize_request("fiverr", provider, model, messages[-1]["content"] if messages else ""):
            return
        self.fiverr_text_worker = ChatWorker(self.run_backend, provider, model, messages, "")
        self.fiverr_text_worker.token_signal.connect(self._fiverr_on_gig_token)
        self.fiverr_text_worker.finished_signal.connect(self._fiverr_on_gig_done)
        self.fiverr_text_worker.usage_signal.connect(lambda u: self.note_request_usage("fiverr", u))
        self.fiverr_text_worker.error_signal.connect(self._fiverr_on_text_error)
        self.fiverr_text_worker.start()

    def _fiverr_on_gig_token(self, token: str):
        self.fiverr_gig_box.moveCursor(QTextCursor.End)
        self.fiverr_gig_box.insertPlainText(token)

    def _fiverr_on_gig_done(self, _full: str):
        self.record_request("fiverr", _full)
        self.fiverr_status_label.setText("Gig description ready.")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)

    def fiverr_stop(self):
        if self.fiverr_image_worker is not None and self.fiverr_image_worker.isRunning():
            self.fiverr_image_worker.cancel()
        if self.fiverr_text_worker is not None and self.fiverr_text_worker.isRunning():
            self.fiverr_text_worker.cancel()
        self.fiverr_status_label.setText("Stopped.")
        self.fiverr_generate_btn.setEnabled(True)
        self.fiverr_delivery_btn.setEnabled(True)
        self.fiverr_gig_btn.setEnabled(True)
        self.fiverr_stop_btn.setEnabled(False)

    def fiverr_save_images(self):
        if not self._fiverr_image_paths:
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "Choose folder to save logos")
        if not dest_dir:
            return
        import shutil
        for src in self._fiverr_image_paths:
            shutil.copy(src, dest_dir)
        self.fiverr_status_label.setText(f"Saved {len(self._fiverr_image_paths)} image(s).")

    def fiverr_clear(self):
        self._fiverr_clear_logo_grid()
        self.fiverr_delivery_box.clear()
        self.fiverr_gig_box.clear()
        self.fiverr_status_label.setText("Idle")
        self.fiverr_cost_label.setText("—")
        self.fiverr_preview_status.setText("No logos generated yet.")
        self.fiverr_save_images_btn.setEnabled(False)
        self._fiverr_image_paths = []

    def _fiverr_clear_logo_grid(self):
        while self.fiverr_logo_grid_layout.count():
            item = self.fiverr_logo_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def author_load_models(self):
        provider = self.author_provider_box.currentText()
        self.author_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
            for m in models:
                self.author_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("author: load models", exc, self.author_model_box)

    def _author_on_content_type_changed(self, content_type: str):
        fiction_tasks = [
            "Write Scene", "Continue Draft", "Generate Outline",
            "Develop Characters", "Build World", "Write Dialogue", "Revise / Improve",
        ]
        nonfiction_tasks = [
            "Write Chapter", "Continue Draft", "Generate Outline",
            "Strengthen Argument", "Add Case Study / Example", "Tighten Structure", "Revise / Improve",
        ]
        tasks = nonfiction_tasks if content_type == "Non-Fiction" else fiction_tasks
        current = self.author_task_box.currentText()
        self.author_task_box.blockSignals(True)
        self.author_task_box.clear()
        self.author_task_box.addItems(tasks)
        if current in tasks:
            self.author_task_box.setCurrentText(current)
        self.author_task_box.blockSignals(False)

    def _compute_next_step_tip(self) -> str:
        """Pick the single most useful next action, checked against real app state.
        Ordered write → publish → market, so it walks the whole book lifecycle."""
        import os

        profile = self._author_get_book_profile()
        draft_words = len(self.author_draft_box.toPlainText().split())
        outline = self.author_outline_box.toPlainText().strip()

        # ── Writing phase ──
        if not profile["title"]:
            return ("📖  Start here — fill in Title, Author and Type in the Project Bar, then open "
                    "Book Profile and click Save Profile. Everything downstream reuses it.")
        if not profile["hook"] or not profile["target_reader"]:
            return ("📖  Complete your Book Profile (Hook + Target reader). These two fields shape "
                    "every blurb, description and social caption you'll generate later.")
        if draft_words == 0 and not outline:
            return ("✍️  No draft yet — set Task to Generate Outline, describe the book in Direction, "
                    "and click Write. Outline first is faster than drafting blind.")
        if draft_words == 0:
            return ("✍️  Outline exists but no draft — switch Task to "
                    f"{'Write Chapter' if profile['content_type'] == 'Non-Fiction' else 'Write Scene'} "
                    "and start drafting. Use Continue to extend.")
        if draft_words < 5000:
            return (f"✍️  Draft is {draft_words:,} words — keep going with Write / Continue. "
                    "Add 'Chapter 1', 'Chapter 2' heading lines as you go so Chapters and Export pick them up.")
        if not self._author_export_done:
            return (f"📤  {draft_words:,} words written — export a formatted copy (EPUB / DOCX / PDF) "
                    "from the Write sidebar to see how it reads as a real book.")

        # ── Publishing phase ──
        todos = self._get_pending_todo_titles()
        if any("Upload to Amazon KDP" in t for t in todos):
            return ("📣  Draft exported. Next: generate a Back-Cover Blurb in Publish mode, then a "
                    "KDP Listing in Market mode — that one output covers your description, categories, "
                    "keywords and pricing. Then create your KDP account and upload.")
        if any("cover files" in t for t in todos):
            return ("🎨  Cover files are still on your checklist — KDP needs 3000×4500px at 300dpi. "
                    "This is the one step the app can't do for you; hire a designer or use Canva/Reedsy.")

        # ── Marketing phase ──
        if not os.environ.get("PUBLISHDRIVE_API_KEY", "").strip():
            return ("🔌  Book is live-ready. Connect PublishDrive (see the Connections panel) to pull "
                    "real sales data in, or skip it and drop KDP CSV reports into data/kdp_reports/ instead.")
        if any("Create TikTok, Instagram" in t for t in todos):
            return ("📱  Set up your TikTok / Instagram / Pinterest accounts (same username on all three), "
                    "then use Quote Finder → Calendar to batch a few weeks of posts in one pass.")
        if any("TikTokers/BookTokers" in t for t in todos):
            return ("🎬  Content pipeline is ready — generate quote graphics and shorts, then pitch "
                    "BookTok creators in your niche with a free copy plus ready-made clips.")
        return ("✅  Core pipeline complete. Keep the Calendar filled, watch sales on the Overview tab, "
                "and work through whatever's left on your Publishing Todos.")

    def _get_pending_todo_titles(self) -> list:
        """Pending, non-engineering todo titles — the advisor only nudges toward real
        publishing/marketing work, never the (Dev) roadmap items."""
        import sqlite3
        from services.database import DB_PATH
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT title FROM manuscript_todos WHERE status != 'done' AND platform != 'engineering'"
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _refresh_next_step_tip(self):
        tip = self._compute_next_step_tip()
        for attr in ("author_next_step_label", "manuscript_next_step_label"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(f"Next step:   {tip}")

    def _author_get_book_profile(self) -> dict:
        return {
            "title": self.author_title_input.text().strip(),
            "author": self.author_name_input.text().strip(),
            "content_type": self.author_content_type_box.currentText(),
            "genre": self.author_genre_box.currentText(),
            "hook": self.author_profile_hook_input.text().strip(),
            "target_reader": self.author_profile_reader_input.text().strip(),
            "comp_titles": self.author_profile_comps_input.text().strip(),
            "publishing_path": self.author_profile_path_box.currentText(),
        }

    def _author_build_book_profile_block(self) -> str:
        """Formats the Book Profile into a system-prompt block shared by Write/Publish/Market
        — the point being you set this once and stop re-explaining the book on every request."""
        p = self._author_get_book_profile()
        lines = []
        if p["title"]:
            lines.append(f"Title: {p['title']}")
        if p["author"]:
            lines.append(f"Author: {p['author']}")
        lines.append(f"Content type: {p['content_type']}")
        if p["genre"]:
            lines.append(f"Genre: {p['genre']}")
        if p["hook"]:
            lines.append(f"Hook: {p['hook']}")
        if p["target_reader"]:
            lines.append(f"Target reader: {p['target_reader']}")
        if p["comp_titles"]:
            lines.append(f"Comp titles: {p['comp_titles']}")
        if p["publishing_path"] and p["publishing_path"] != "Undecided":
            lines.append(f"Publishing path: {p['publishing_path']}")
        if not lines:
            return ""
        return (
            "BOOK CONTEXT — ground every response in this; don't ask the user to re-explain it.\n\n"
            + "\n".join(lines)
        )

    def author_save_profile(self):
        import json
        from services.database import save_setting
        save_setting("author_book_profile", json.dumps(self._author_get_book_profile()))
        self.author_status_label.setText("[Saved] Book profile.")
        self._refresh_next_step_tip()

    def _author_load_profile(self):
        import json
        from services.database import get_setting
        raw = get_setting("author_book_profile", "")
        if not raw:
            return
        try:
            profile = json.loads(raw)
        except Exception:
            return
        self.author_title_input.setText(profile.get("title", ""))
        self.author_name_input.setText(profile.get("author", ""))
        if profile.get("content_type"):
            self.author_content_type_box.setCurrentText(profile["content_type"])
        if profile.get("genre"):
            idx = self.author_genre_box.findText(profile["genre"])
            if idx >= 0:
                self.author_genre_box.setCurrentIndex(idx)
        self.author_profile_hook_input.setText(profile.get("hook", ""))
        self.author_profile_reader_input.setText(profile.get("target_reader", ""))
        self.author_profile_comps_input.setText(profile.get("comp_titles", ""))
        if profile.get("publishing_path"):
            self.author_profile_path_box.setCurrentText(profile["publishing_path"])

    def _author_build_prompt(self, direction: str) -> str:
        task = self.author_task_box.currentText()
        genre = self.author_genre_box.currentText()
        tone = self.author_tone_box.currentText()
        pov = self.author_pov_box.currentText()
        title = self.author_title_input.text().strip()
        parts = [f"Task: {task}"]
        if title:
            parts.append(f"Project: {title}")
        parts += [f"Genre: {genre}", f"Tone: {tone}", f"POV: {pov}"]
        if direction:
            parts.append(f"Direction:\n{direction}")
        return "\n".join(parts)

    def _author_build_consistency_context(self, recent_draft_text: str = "") -> str:
        """Auto-inject established Characters/World + a recent-draft excerpt so every
        Write/Continue call stays consistent with the story so far."""
        characters = self.author_characters_box.toPlainText().strip()
        world = self.author_world_box.toPlainText().strip()
        sections = []
        if characters:
            sections.append(f"ESTABLISHED CHARACTERS (stay consistent — do not contradict):\n{characters}")
        if world:
            sections.append(f"ESTABLISHED WORLD (stay consistent — do not contradict):\n{world}")
        if recent_draft_text:
            sections.append(
                "RECENT STORY TEXT (end of the current draft — continue consistently, don't repeat it):\n"
                + recent_draft_text[-3000:]
            )
        if not sections:
            return ""
        return (
            "CONTINUITY CONTEXT — ground every response in this; do not contradict "
            "established characters, world rules, or recent events.\n\n" + "\n\n".join(sections)
        )

    def _author_start_worker(self, provider: str, model: str, prompt: str, recent_draft_text: str = ""):
        agent = self.agent_instances["author"]
        consistency_context = self._author_build_consistency_context(recent_draft_text)
        book_profile_context = self._author_build_book_profile_block()
        content_type = self.author_content_type_box.currentText()
        messages = agent.build_messages(
            prompt, consistency_context=consistency_context,
            book_profile_context=book_profile_context, content_type=content_type,
        )
        self.author_status_label.setText("[Working…]")
        self.author_write_btn.setEnabled(False)
        self.author_continue_btn.setEnabled(False)
        self.author_stop_btn.setEnabled(True)
        if not self.authorize_request("author", provider, model, prompt):
            return
        self.author_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
        self.author_worker.token_signal.connect(self._author_on_token)
        self.author_worker.finished_signal.connect(self._author_on_finished)
        self.author_worker.usage_signal.connect(lambda u: self.note_request_usage("author", u))
        self.author_worker.error_signal.connect(self._author_on_error)
        self.author_worker.start()

    def author_write(self):
        direction = self.author_direction_input.toPlainText().strip()
        if not direction:
            QMessageBox.warning(self, "Missing Input", "Please enter a direction.")
            return
        provider = self.author_provider_box.currentText()
        model = self.author_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return
        self._author_is_continuing = False
        existing = self.author_draft_box.toPlainText().strip()
        self.author_draft_box.clear()
        self._last_author_response = ""
        prompt = self._author_build_prompt(direction)
        self._author_start_worker(provider, model, prompt, recent_draft_text=existing)

    def author_continue(self):
        direction = self.author_direction_input.toPlainText().strip()
        provider = self.author_provider_box.currentText()
        model = self.author_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return
        existing = self.author_draft_box.toPlainText().strip()
        parts = []
        if existing:
            parts.append(f"Existing draft so far:\n\n{existing}")
        if direction:
            parts.append(f"Continue with:\n{direction}")
        else:
            parts.append("Continue from where the draft left off.")
        continuation_note = "\n\n".join(parts)
        self._author_is_continuing = True
        self._last_author_response = ""
        # Append a separator then stream new content
        if existing:
            cursor = self.author_draft_box.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText("\n\n")
            self.author_draft_box.setTextCursor(cursor)
        prompt = self._author_build_prompt(continuation_note)
        # Recent draft text is already embedded in full inside `continuation_note` above —
        # don't pass it again here, that would just duplicate it in the prompt.
        self._author_start_worker(provider, model, prompt)

    def _author_on_token(self, token: str):
        self._last_author_response += token
        cursor = self.author_draft_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.author_draft_box.setTextCursor(cursor)

    def _author_update_counts(self):
        text = self.author_draft_box.toPlainText()
        word_count = len(text.split()) if text.strip() else 0
        self.author_word_count_label.setText(str(word_count))
        scene_count = len(re.findall(
            r"^(chapter|scene|act|part|prologue|epilogue|---|\*\*\*)",
            text, re.MULTILINE | re.IGNORECASE,
        ))
        self.author_scene_count_label.setText(str(scene_count))

    def _author_on_finished(self, full_response: str):
        self.record_request("author", full_response)
        self._populate_author_tabs(full_response)
        word_count = len(self.author_draft_box.toPlainText().split())
        self.author_status_label.setText(f"[Done] {word_count:,} words")
        self.author_write_btn.setEnabled(True)
        self.author_continue_btn.setEnabled(True)
        self.author_stop_btn.setEnabled(False)
        self.author_save_btn.setEnabled(True)
        self._refresh_next_step_tip()

    def _author_on_error(self, error: str):
        self.abandon_request("author")
        self.author_status_label.setText(f"[Error] {error}")
        self.author_write_btn.setEnabled(True)
        self.author_continue_btn.setEnabled(True)
        self.author_stop_btn.setEnabled(False)

    def author_stop(self):
        if self.author_worker is not None and self.author_worker.isRunning():
            self.author_worker.cancel()
        self.author_write_btn.setEnabled(True)
        self.author_continue_btn.setEnabled(True)
        self.author_stop_btn.setEnabled(False)
        self.author_status_label.setText("[Stopped]")

    def author_save(self):
        text = self.author_draft_box.toPlainText()
        if not text.strip():
            return
        title = self.author_title_input.text().strip() or "author_draft"
        safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Draft", str(BASE_DIR / f"{safe}.txt"),
            "Text Files (*.txt);;Markdown Files (*.md)"
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.author_status_label.setText(f"[Saved] {path}")

    def author_export_book(self):
        text = self.author_draft_box.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Nothing to Export", "The Draft tab is empty.")
            return
        fmt = self.author_export_format_box.currentText().lower()
        title = self.author_title_input.text().strip() or "Untitled Manuscript"
        author_name = self.author_export_author_input.text().strip() or "Unknown Author"

        safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
        filters = {"epub": "EPUB Files (*.epub)", "docx": "DOCX Files (*.docx)", "pdf": "PDF Files (*.pdf)"}
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Book", str(BASE_DIR / f"{safe}.{fmt}"), filters[fmt]
        )
        if not path:
            return

        from services.book_exporter import export_book
        try:
            export_book(text, title, author_name, fmt, Path(path))
            self.author_status_label.setText(f"[Done] Exported {fmt.upper()} to {Path(path).name}")
            self._author_export_done = True
            self._refresh_next_step_tip()
        except Exception as e:
            self.author_status_label.setText(f"[Error] {e}")

    def author_clear(self):
        self._author_clear_displays()
        self.author_direction_input.clear()
        self.author_title_input.clear()
        self.author_status_label.setText("")
        self._last_author_response = ""

    def _author_clear_displays(self):
        for box in (self.author_draft_box, self.author_outline_box,
                    self.author_characters_box, self.author_world_box):
            box.clear()
        self.author_word_count_label.setText("0")
        self.author_scene_count_label.setText("0")
        self.author_save_btn.setEnabled(False)

    def _populate_author_tabs(self, response: str):
        task = self.author_task_box.currentText()
        sections = self._parse_author_sections(response)
        if sections.get("outline"):
            self.author_outline_box.setPlainText(sections["outline"])
        if sections.get("characters"):
            self.author_characters_box.setPlainText(sections["characters"])
        if sections.get("world"):
            self.author_world_box.setPlainText(sections["world"])
        # Route clean content to the appropriate tab based on task
        if task == "Generate Outline" and not sections.get("outline"):
            self.author_outline_box.setPlainText(response)
        elif task == "Develop Characters" and not sections.get("characters"):
            self.author_characters_box.setPlainText(response)
        elif task == "Build World" and not sections.get("world"):
            self.author_world_box.setPlainText(response)
        elif not self._author_is_continuing and not sections.get("outline") and not sections.get("characters"):
            # Fresh write with no section markers — put full response in draft
            self.author_draft_box.setPlainText(sections.get("draft") or response)

    def _parse_author_sections(self, text: str) -> dict:
        patterns = {
            "draft":      r"\[DRAFT\](.*?)(?=\[OUTLINE\]|\[CHARACTER\]|\[WORLD\]|$)",
            "outline":    r"\[OUTLINE\](.*?)(?=\[DRAFT\]|\[CHARACTER\]|\[WORLD\]|$)",
            "characters": r"\[CHARACTER\](.*?)(?=\[DRAFT\]|\[OUTLINE\]|\[WORLD\]|$)",
            "world":      r"\[WORLD\](.*?)(?=\[DRAFT\]|\[OUTLINE\]|\[CHARACTER\]|$)",
        }
        result = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            result[key] = m.group(1).strip() if m else ""
        return result

    def _author_on_tab_changed(self, index: int):
        if self.author_tabs.widget(index) is self.author_chapters_tab:
            self._author_refresh_chapters()

    def _author_refresh_chapters(self):
        """Re-derive the chapter list from the current Draft text — chapters aren't a
        separate stored model, they're parsed live from Draft using the same heading
        detection as book export, so there's never a second source of truth to drift."""
        from services.book_exporter import split_into_chapters, find_chapter_offsets

        text = self.author_draft_box.toPlainText()
        self.author_chapters_list.clear()
        self._author_chapter_offsets = []

        if not text.strip():
            self.author_chapters_stats_label.setText("No chapters detected yet — write something in Draft first.")
            return

        chapters = split_into_chapters(text)
        heading_offsets = find_chapter_offsets(text)
        total_words = len(text.split())

        offsets = []
        oi = 0
        for heading, _body in chapters:
            if heading:
                offsets.append(heading_offsets[oi] if oi < len(heading_offsets) else 0)
                oi += 1
            else:
                offsets.append(0)
        self._author_chapter_offsets = offsets

        for i, (heading, body) in enumerate(chapters):
            label = heading or "(untitled opening — no chapter headings found yet)"
            words = len(body.split())
            item = QListWidgetItem(f"{i + 1}. {label}   —   {words:,} words")
            self.author_chapters_list.addItem(item)

        chapter_word = "chapter" if len(chapters) == 1 else "chapters"
        self.author_chapters_stats_label.setText(
            f"{len(chapters)} {chapter_word} · {total_words:,} words total"
        )

    def _author_jump_to_chapter(self, item):
        row = self.author_chapters_list.row(item)
        if row < 0 or row >= len(self._author_chapter_offsets):
            return
        cursor = self.author_draft_box.textCursor()
        cursor.setPosition(self._author_chapter_offsets[row])
        self.author_draft_box.setTextCursor(cursor)
        self.author_tabs.setCurrentWidget(self.author_draft_box)
        self.author_draft_box.ensureCursorVisible()

    # ── Author mode / sub-mode switching ─────────────────────────────────────
    def _author_set_mode(self, mode: str):
        is_write = mode == "write"
        self.author_mode_write_btn.setChecked(is_write)
        self.author_mode_pubmkt_btn.setChecked(not is_write)
        self.author_content_stack.setCurrentIndex(0 if is_write else 1)

    def _author_set_sub_mode(self, mode: str):
        is_pub = mode == "publish"
        self.author_sub_publish_btn.setChecked(is_pub)
        self.author_sub_market_btn.setChecked(not is_pub)
        self.author_sub_stack.setCurrentIndex(0 if is_pub else 1)

    # ── Publish handlers ──────────────────────────────────────────────────────
    def author_pub_generate(self):
        provider = self.author_provider_box.currentText()
        model = self.author_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model in the Write sidebar.")
            return

        title   = self.author_title_input.text().strip()
        genre   = self.author_genre_box.currentText()
        tone    = self.author_tone_box.currentText()
        doc_type = self.author_pub_type_box.currentText()
        wc      = self.author_pub_wordcount_input.text().strip()
        comps   = self.author_pub_comps_input.text().strip()
        pitch_tone = self.author_pub_pitch_tone_box.currentText()
        notes   = self.author_pub_notes_input.toPlainText().strip()

        parts = [f"Task: Generate a {doc_type}"]
        if title:
            parts.append(f"Book Title: {title}")
        parts += [f"Genre: {genre}", f"Tone: {tone}", f"Pitch Tone: {pitch_tone}"]
        if wc:
            parts.append(f"Manuscript Word Count: {wc}")
        if comps:
            parts.append(f"Comp Titles: {comps}")
        if notes:
            parts.append(f"Additional Notes:\n{notes}")

        prompt = "\n".join(parts)
        agent = self.agent_instances["author"]
        messages = agent.build_publish_messages(prompt, book_profile_context=self._author_build_book_profile_block())

        self.author_pub_output.clear()
        self.author_status_label.setText(f"[Working…] Generating {doc_type}…")
        self.author_pub_generate_btn.setEnabled(False)
        self.author_pub_stop_btn.setEnabled(True)
        self.author_pub_save_btn.setEnabled(False)

        if not self.authorize_request("author", provider, model, prompt):
            return
        self.author_pub_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
        self.author_pub_worker.token_signal.connect(self._author_pub_on_token)
        self.author_pub_worker.finished_signal.connect(self._author_pub_on_finished)
        self.author_pub_worker.usage_signal.connect(lambda u: self.note_request_usage("author", u))
        self.author_pub_worker.error_signal.connect(self._author_pub_on_error)
        self.author_pub_worker.start()

    def _author_pub_on_token(self, token: str):
        cursor = self.author_pub_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.author_pub_output.setTextCursor(cursor)

    def _author_pub_on_finished(self, full_response: str):
        self.record_request("author", full_response)
        self.author_status_label.setText(
            f"[Done] {self.author_pub_type_box.currentText()} generated"
        )
        self.author_pub_generate_btn.setEnabled(True)
        self.author_pub_stop_btn.setEnabled(False)
        self.author_pub_save_btn.setEnabled(True)

    def _author_pub_on_error(self, error: str):
        self.abandon_request("author")
        self.author_status_label.setText(f"[Error] {error}")
        self.author_pub_generate_btn.setEnabled(True)
        self.author_pub_stop_btn.setEnabled(False)

    def author_pub_stop(self):
        if self.author_pub_worker is not None and self.author_pub_worker.isRunning():
            self.author_pub_worker.cancel()
        self.author_pub_generate_btn.setEnabled(True)
        self.author_pub_stop_btn.setEnabled(False)
        self.author_status_label.setText("[Stopped]")

    def author_pub_copy(self):
        text = self.author_pub_output.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.author_status_label.setText("[Copied to clipboard]")

    def author_pub_save(self):
        text = self.author_pub_output.toPlainText().strip()
        if not text:
            return
        title = self.author_title_input.text().strip() or "publish"
        safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
        doc_type = re.sub(r"\s+", "_", self.author_pub_type_box.currentText().lower())
        default_name = f"{safe}_{doc_type}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Publishing Document", str(BASE_DIR / default_name),
            "Text Files (*.txt);;Markdown Files (*.md)"
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.author_status_label.setText(f"[Saved] {path}")

    # ── Market handlers ───────────────────────────────────────────────────────
    def author_mkt_generate(self):
        provider = self.author_provider_box.currentText()
        model = self.author_model_box.currentText()
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model in the Write sidebar.")
            return

        title    = self.author_title_input.text().strip()
        genre    = self.author_genre_box.currentText()
        platform = self.author_mkt_platform_box.currentText()
        hook     = self.author_mkt_hook_input.text().strip()
        comps    = self.author_mkt_comps_input.text().strip()
        mkt_tone = self.author_mkt_tone_box.currentText()
        notes    = self.author_mkt_notes_input.toPlainText().strip()

        parts = [f"Task: Generate {platform} copy"]
        if title:
            parts.append(f"Book Title: {title}")
        parts += [f"Genre: {genre}", f"Tone: {mkt_tone}"]
        if hook:
            parts.append(f"Hook / Logline: {hook}")
        if comps:
            parts.append(f"Comp Titles: {comps}")
        if notes:
            parts.append(f"Additional Notes:\n{notes}")

        prompt = "\n".join(parts)
        agent = self.agent_instances["author"]
        messages = agent.build_market_messages(prompt, book_profile_context=self._author_build_book_profile_block())

        self.author_mkt_output.clear()
        self.author_status_label.setText(f"[Working…] Generating {platform} copy…")
        self.author_mkt_generate_btn.setEnabled(False)
        self.author_mkt_stop_btn.setEnabled(True)
        self.author_mkt_save_btn.setEnabled(False)

        if not self.authorize_request("author", provider, model, prompt):
            return
        self.author_mkt_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
        self.author_mkt_worker.token_signal.connect(self._author_mkt_on_token)
        self.author_mkt_worker.finished_signal.connect(self._author_mkt_on_finished)
        self.author_mkt_worker.usage_signal.connect(lambda u: self.note_request_usage("author", u))
        self.author_mkt_worker.error_signal.connect(self._author_mkt_on_error)
        self.author_mkt_worker.start()

    def _author_mkt_on_token(self, token: str):
        cursor = self.author_mkt_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.author_mkt_output.setTextCursor(cursor)

    def _author_mkt_on_finished(self, full_response: str):
        self.record_request("author", full_response)
        self.author_status_label.setText(
            f"[Done] {self.author_mkt_platform_box.currentText()} copy generated"
        )
        self.author_mkt_generate_btn.setEnabled(True)
        self.author_mkt_stop_btn.setEnabled(False)
        self.author_mkt_save_btn.setEnabled(True)

    def _author_mkt_on_error(self, error: str):
        self.abandon_request("author")
        self.author_status_label.setText(f"[Error] {error}")
        self.author_mkt_generate_btn.setEnabled(True)
        self.author_mkt_stop_btn.setEnabled(False)

    def author_mkt_stop(self):
        if self.author_mkt_worker is not None and self.author_mkt_worker.isRunning():
            self.author_mkt_worker.cancel()
        self.author_mkt_generate_btn.setEnabled(True)
        self.author_mkt_stop_btn.setEnabled(False)
        self.author_status_label.setText("[Stopped]")

    def author_mkt_copy(self):
        text = self.author_mkt_output.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.author_status_label.setText("[Copied to clipboard]")

    def author_mkt_save(self):
        text = self.author_mkt_output.toPlainText().strip()
        if not text:
            return
        title = self.author_title_input.text().strip() or "marketing"
        safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
        platform = re.sub(r"[\s/]+", "_", self.author_mkt_platform_box.currentText().lower())
        default_name = f"{safe}_{platform}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Marketing Copy", str(BASE_DIR / default_name),
            "Text Files (*.txt);;Markdown Files (*.md)"
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.author_status_label.setText(f"[Saved] {path}")

    # ── Manuscript panel builder ──────────────────────────────────────────────
    def build_manuscript_panel(self):
        self.manuscript_panel = QWidget()
        self.manuscript_panel.setObjectName("ManuscriptPanel")
        layout = QVBoxLayout(self.manuscript_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Top bar: period selector + refresh button ─────────────────────────
        top_bar = QWidget()
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(4, 4, 4, 4)
        tb.setSpacing(8)

        tb.addWidget(QLabel("Period:"))
        self.manuscript_period_box = QComboBox()
        self.manuscript_period_box.addItems(["Last 30 days", "This month", "Last 7 days", "All time"])
        tb.addWidget(self.manuscript_period_box)

        self.manuscript_refresh_btn = QPushButton("⟳  Refresh Data")
        self.manuscript_refresh_btn.clicked.connect(self.manuscript_refresh)
        tb.addWidget(self.manuscript_refresh_btn)

        self.manuscript_ingest_btn = QPushButton("📥  Ingest KDP CSV")
        self.manuscript_ingest_btn.clicked.connect(self.manuscript_ingest_kdp)
        tb.addWidget(self.manuscript_ingest_btn)

        tb.addStretch()
        layout.addWidget(top_bar)

        self.manuscript_next_step_label = QLabel("")
        self.manuscript_next_step_label.setWordWrap(True)
        self.manuscript_next_step_label.setStyleSheet(
            "background: rgba(60,255,136,0.08); border: 1px solid rgba(60,255,136,0.25); "
            "border-radius: 6px; padding: 8px 10px; color: #3cff88; font-size: 12px;"
        )
        layout.addWidget(self.manuscript_next_step_label)

        # ── Connections: which 3rd-party services are actually configured ─────
        connections_section = CollapsibleSection("🔌  Connections", expanded=False)
        self.manuscript_connections_layout = QVBoxLayout()
        self.manuscript_connections_layout.setContentsMargins(4, 2, 4, 2)
        self.manuscript_connections_layout.setSpacing(3)
        connections_container = QWidget()
        connections_container.setLayout(self.manuscript_connections_layout)
        connections_section.addWidget(connections_container)

        connections_refresh_btn = QPushButton("🔄  Refresh Status")
        connections_refresh_btn.clicked.connect(self._refresh_connections_status)
        connections_section.addWidget(connections_refresh_btn)

        layout.addWidget(connections_section)
        self._refresh_connections_status()

        self.manuscript_tabs = QTabWidget()
        layout.addWidget(self.manuscript_tabs, 1)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setContentsMargins(0, 0, 0, 0)

        # ── Main area: metrics display + Q&A sidebar ─────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Left: metrics summary display
        self.manuscript_metrics_box = QTextBrowser()
        self.manuscript_metrics_box.setPlaceholderText("Click Refresh Data to load publishing metrics…")
        splitter.addWidget(self.manuscript_metrics_box)

        # Right: Q&A sidebar
        sidebar = QWidget()
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(8, 4, 4, 4)
        sb.setSpacing(6)
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(280)

        sb.addWidget(QLabel("Ask about your book:"))
        self.manuscript_query_input = QTextEdit()
        self.manuscript_query_input.setPlaceholderText(
            "e.g. What did I earn this month?\nWhich platform is performing best?"
        )
        self.manuscript_query_input.setFixedHeight(90)
        sb.addWidget(self.manuscript_query_input)

        sb.addWidget(QLabel("Provider:"))
        self.manuscript_provider_box = QComboBox()
        self.manuscript_provider_box.addItems(["anthropic", "openai", "deepseek", "kimi", "gemini", "qwen"])
        self.manuscript_provider_box.currentTextChanged.connect(self.manuscript_load_models)
        sb.addWidget(self.manuscript_provider_box)

        sb.addWidget(QLabel("Model:"))
        self.manuscript_model_box = QComboBox()
        sb.addWidget(self.manuscript_model_box)

        self.manuscript_ask_btn = QPushButton("💬  Ask")
        self.manuscript_ask_btn.setMinimumHeight(34)
        self.manuscript_ask_btn.clicked.connect(self.manuscript_ask)
        sb.addWidget(self.manuscript_ask_btn)

        sb.addStretch()

        # Todos section
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #444;")
        sb.addWidget(sep)

        sb.addWidget(QLabel("Publishing Todos:"))
        self.manuscript_todo_list = QListWidget()
        self.manuscript_todo_list.setMinimumHeight(120)
        sb.addWidget(self.manuscript_todo_list)

        self.manuscript_todo_input = QLineEdit()
        self.manuscript_todo_input.setPlaceholderText("Add todo…")
        sb.addWidget(self.manuscript_todo_input)

        todo_btn_row = QHBoxLayout()
        self.manuscript_add_todo_btn = QPushButton("Add")
        self.manuscript_add_todo_btn.clicked.connect(self.manuscript_add_todo)
        self.manuscript_done_todo_btn = QPushButton("Done")
        self.manuscript_done_todo_btn.clicked.connect(self.manuscript_mark_todo_done)
        todo_btn_row.addWidget(self.manuscript_add_todo_btn)
        todo_btn_row.addWidget(self.manuscript_done_todo_btn)
        sb.addLayout(todo_btn_row)

        splitter.addWidget(sidebar)
        overview_layout.addWidget(splitter)
        self.manuscript_tabs.addTab(overview_tab, "Overview")

        self.build_manuscript_quote_finder_tab()
        self.manuscript_tabs.addTab(self.manuscript_quote_finder_tab, "Quote Finder")

        self.build_manuscript_graphics_tab()
        self.manuscript_tabs.addTab(self.manuscript_graphics_tab, "Quote Graphics")

        self.build_manuscript_shorts_tab()
        self.manuscript_tabs.addTab(self.manuscript_shorts_tab, "Shorts")

        self.build_manuscript_calendar_tab()
        self.manuscript_tabs.addTab(self.manuscript_calendar_tab, "Calendar")

        # Status bar
        self.manuscript_status_label = QLabel("")
        self.manuscript_status_label.setStyleSheet("font-size: 12px; color: #888; padding: 2px 4px;")
        layout.addWidget(self.manuscript_status_label)

        self.manuscript_panel.hide()

    def build_manuscript_quote_finder_tab(self):
        self.manuscript_quote_finder_tab = QWidget()
        layout = QVBoxLayout(self.manuscript_quote_finder_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Manuscript text:"))
        self.quote_finder_text = QTextEdit()
        self.quote_finder_text.setPlaceholderText(
            "Paste a chapter or excerpt here, or load a file below…"
        )
        self.quote_finder_text.setFixedHeight(140)
        layout.addWidget(self.quote_finder_text)

        load_row = QHBoxLayout()
        self.quote_finder_load_btn = QPushButton("📄  Load File…")
        self.quote_finder_load_btn.clicked.connect(self.quote_finder_load_file)
        load_row.addWidget(self.quote_finder_load_btn)
        load_row.addWidget(QLabel("Supports .txt, .pdf, .epub, .mobi"))
        load_row.addStretch()
        layout.addLayout(load_row)

        settings_row_container = QWidget()
        settings_row = FlowLayout(settings_row_container, spacing=6)
        settings_row.addWidget(QLabel("Quotes:"))
        self.quote_finder_count_box = QComboBox()
        self.quote_finder_count_box.addItems(["5", "10", "15", "20"])
        self.quote_finder_count_box.setCurrentText("10")
        settings_row.addWidget(self.quote_finder_count_box)

        settings_row.addWidget(QLabel("Theme:"))
        self.quote_finder_theme_box = make_theme_box()
        settings_row.addWidget(self.quote_finder_theme_box)

        settings_row.addWidget(QLabel("Voice:"))
        self.quote_finder_voice_source_box = make_voice_source_box()
        self.quote_finder_voice_source_box.currentTextChanged.connect(self.quote_finder_load_voices)
        settings_row.addWidget(self.quote_finder_voice_source_box)

        self.quote_finder_voice_box = QComboBox()
        settings_row.addWidget(self.quote_finder_voice_box)

        settings_row.addWidget(QLabel("Attribution:"))
        self.quote_finder_attribution = QLineEdit()
        self.quote_finder_attribution.setPlaceholderText("You Don't Chase")
        settings_row.addWidget(self.quote_finder_attribution)

        layout.addWidget(settings_row_container)

        self.quote_finder_suggest_btn = QPushButton("🔍  Suggest Quotes")
        self.quote_finder_suggest_btn.setMinimumHeight(34)
        self.quote_finder_suggest_btn.clicked.connect(self.quote_finder_suggest)
        layout.addWidget(self.quote_finder_suggest_btn)

        layout.addWidget(QLabel("Candidates — 🖼 makes a graphic, 🎬 makes a narrated short:"))
        self.quote_finder_list = QListWidget()
        layout.addWidget(self.quote_finder_list, 1)

        self._quote_finder_short_buttons: list = []
        self._quote_finder_busy = False
        self.quote_finder_load_voices()

    def build_manuscript_graphics_tab(self):
        self.manuscript_graphics_tab = QWidget()
        row = QHBoxLayout(self.manuscript_graphics_tab)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(12)

        # Left: controls
        controls = QWidget()
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        controls.setMaximumWidth(280)

        cl.addWidget(QLabel("Quote:"))
        self.quote_graphic_text = QTextEdit()
        self.quote_graphic_text.setPlaceholderText("You over-text. You explain yourself. You wait.")
        self.quote_graphic_text.setFixedHeight(90)
        cl.addWidget(self.quote_graphic_text)

        cl.addWidget(QLabel("Attribution (optional):"))
        self.quote_graphic_attribution = QLineEdit()
        self.quote_graphic_attribution.setPlaceholderText("You Don't Chase")
        cl.addWidget(self.quote_graphic_attribution)

        cl.addWidget(QLabel("Theme:"))
        self.quote_graphic_theme_box = make_theme_box()
        cl.addWidget(self.quote_graphic_theme_box)

        cl.addWidget(QLabel("Size:"))
        self.quote_graphic_size_box = make_size_box()
        cl.addWidget(self.quote_graphic_size_box)

        self.quote_graphic_generate_btn = QPushButton("✨  Generate Graphic")
        self.quote_graphic_generate_btn.setMinimumHeight(34)
        self.quote_graphic_generate_btn.clicked.connect(self.manuscript_generate_quote_graphic)
        cl.addWidget(self.quote_graphic_generate_btn)

        self.quote_graphic_open_folder_btn = QPushButton("📂  Open Folder")
        self.quote_graphic_open_folder_btn.clicked.connect(self.manuscript_open_graphics_folder)
        cl.addWidget(self.quote_graphic_open_folder_btn)

        cl.addStretch()
        row.addWidget(controls)

        # Right: preview
        self.quote_graphic_preview = QLabel("Preview will appear here.")
        self.quote_graphic_preview.setAlignment(Qt.AlignCenter)
        self.quote_graphic_preview.setStyleSheet(
            "background: #1a1a1a; border: 1px solid #333; color: #666;"
        )
        self.quote_graphic_preview.setMinimumSize(320, 320)
        row.addWidget(self.quote_graphic_preview, 1)

    def build_manuscript_shorts_tab(self):
        self.manuscript_shorts_tab = QWidget()
        row = QHBoxLayout(self.manuscript_shorts_tab)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(12)

        # Left: controls
        controls = QWidget()
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        controls.setMaximumWidth(280)

        cl.addWidget(QLabel("Quote (also narrated):"))
        self.shorts_quote_text = QTextEdit()
        self.shorts_quote_text.setPlaceholderText("You over-text. You explain yourself. You wait.")
        self.shorts_quote_text.setFixedHeight(90)
        cl.addWidget(self.shorts_quote_text)

        cl.addWidget(QLabel("Attribution (optional):"))
        self.shorts_attribution = QLineEdit()
        self.shorts_attribution.setPlaceholderText("You Don't Chase")
        cl.addWidget(self.shorts_attribution)

        cl.addWidget(QLabel("Theme:"))
        self.shorts_theme_box = make_theme_box()
        cl.addWidget(self.shorts_theme_box)

        cl.addWidget(QLabel("Voice source:"))
        self.shorts_voice_source_box = make_voice_source_box()
        self.shorts_voice_source_box.currentTextChanged.connect(self.shorts_load_voices)
        cl.addWidget(self.shorts_voice_source_box)

        self.shorts_voice_box = QComboBox()
        cl.addWidget(self.shorts_voice_box)

        self.shorts_generate_btn = QPushButton("🎬  Generate Short")
        self.shorts_generate_btn.setMinimumHeight(34)
        self.shorts_generate_btn.clicked.connect(self.manuscript_generate_short)
        cl.addWidget(self.shorts_generate_btn)

        btn_row = QHBoxLayout()
        self.shorts_play_btn = QPushButton("▶  Play")
        self.shorts_play_btn.setEnabled(False)
        self.shorts_play_btn.clicked.connect(self.manuscript_play_short)
        self.shorts_open_folder_btn = QPushButton("📂  Folder")
        self.shorts_open_folder_btn.clicked.connect(self.manuscript_open_shorts_folder)
        btn_row.addWidget(self.shorts_play_btn)
        btn_row.addWidget(self.shorts_open_folder_btn)
        cl.addLayout(btn_row)

        cl.addStretch()
        row.addWidget(controls)

        # Right: preview (static frame of the short — no inline video player)
        self.shorts_preview = QLabel("Preview will appear here.")
        self.shorts_preview.setAlignment(Qt.AlignCenter)
        self.shorts_preview.setStyleSheet(
            "background: #1a1a1a; border: 1px solid #333; color: #666;"
        )
        self.shorts_preview.setMinimumSize(320, 320)
        row.addWidget(self.shorts_preview, 1)

        self.shorts_load_voices()

    def build_manuscript_calendar_tab(self):
        self.manuscript_calendar_tab = QWidget()
        layout = QVBoxLayout(self.manuscript_calendar_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        from PySide6.QtWidgets import QDateEdit
        from PySide6.QtCore import QDate

        layout.addWidget(QLabel(
            "Builds a posting schedule from the candidates on the Quote Finder tab — "
            "run Suggest Quotes there first."
        ))

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Weeks:"))
        self.calendar_weeks_box = QComboBox()
        self.calendar_weeks_box.addItems(["1", "2", "4"])
        settings_row.addWidget(self.calendar_weeks_box)

        settings_row.addWidget(QLabel("Start:"))
        self.calendar_start_date = QDateEdit()
        self.calendar_start_date.setDate(QDate.currentDate())
        self.calendar_start_date.setCalendarPopup(True)
        settings_row.addWidget(self.calendar_start_date)

        self.calendar_tiktok_check = QCheckBox("TikTok")
        self.calendar_tiktok_check.setChecked(True)
        settings_row.addWidget(self.calendar_tiktok_check)

        self.calendar_instagram_check = QCheckBox("Instagram")
        self.calendar_instagram_check.setChecked(True)
        settings_row.addWidget(self.calendar_instagram_check)

        self.calendar_pinterest_check = QCheckBox("Pinterest")
        self.calendar_pinterest_check.setChecked(True)
        settings_row.addWidget(self.calendar_pinterest_check)

        settings_row.addStretch()
        layout.addLayout(settings_row)

        settings_row2 = QHBoxLayout()
        settings_row2.addWidget(QLabel("Theme:"))
        self.calendar_theme_box = make_theme_box()
        settings_row2.addWidget(self.calendar_theme_box)

        settings_row2.addWidget(QLabel("Voice:"))
        self.calendar_voice_source_box = make_voice_source_box()
        self.calendar_voice_source_box.currentTextChanged.connect(self.calendar_load_voices)
        settings_row2.addWidget(self.calendar_voice_source_box)

        self.calendar_voice_box = QComboBox()
        settings_row2.addWidget(self.calendar_voice_box)

        settings_row2.addWidget(QLabel("Attribution:"))
        self.calendar_attribution = QLineEdit()
        self.calendar_attribution.setPlaceholderText("You Don't Chase")
        settings_row2.addWidget(self.calendar_attribution)

        settings_row2.addStretch()
        layout.addLayout(settings_row2)

        btn_row = QHBoxLayout()
        self.calendar_generate_btn = QPushButton("📅  Generate Calendar")
        self.calendar_generate_btn.setMinimumHeight(34)
        self.calendar_generate_btn.clicked.connect(self.manuscript_generate_calendar)
        btn_row.addWidget(self.calendar_generate_btn)

        self.calendar_export_btn = QPushButton("📤  Export Calendar (CSV)")
        self.calendar_export_btn.clicked.connect(self.manuscript_export_calendar_csv)
        btn_row.addWidget(self.calendar_export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        from PySide6.QtWidgets import QTableWidget
        self.calendar_table = QTableWidget(0, 6)
        self.calendar_table.setHorizontalHeaderLabels(["Date", "Platform", "Format", "Quote", "Caption", ""])
        self.calendar_table.setColumnWidth(0, 90)
        self.calendar_table.setColumnWidth(1, 80)
        self.calendar_table.setColumnWidth(2, 70)
        self.calendar_table.setColumnWidth(3, 260)
        self.calendar_table.setColumnWidth(5, 40)
        self.calendar_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.calendar_table, 1)

        self._calendar_slots = []
        self.calendar_load_voices()

    # ── Manuscript handlers ───────────────────────────────────────────────────
    def manuscript_load_models(self):
        provider = self.manuscript_provider_box.currentText()
        self.manuscript_model_box.clear()
        try:
            if provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            else:
                models = []
            for m in models:
                self.manuscript_model_box.addItem(m)
        except Exception as exc:
            self._note_failure("manuscript: load models", exc, self.manuscript_model_box)

    def _refresh_connections_status(self):
        """Shows which 3rd-party API keys are actually configured (checked from the running
        process's environment — restart the app after editing .env for changes to appear).
        Services with no API at all (KDP, Draft2Digital, IngramSpark, BookBub, TikTok/IG/Pinterest)
        aren't listed here since there's nothing to check — their account-creation steps are on
        the Publishing Todos list below (hover the ℹ️ items)."""
        import os

        while self.manuscript_connections_layout.count():
            item = self.manuscript_connections_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        note = QLabel(
            "API-key-based services only — KDP/Draft2Digital/IngramSpark/BookBub/social accounts "
            "have no API to check; see the ℹ️ Publishing Todos below for those."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #777; font-size: 11px;")
        self.manuscript_connections_layout.addWidget(note)

        checks = [
            ("PublishDrive", bool(os.environ.get("PUBLISHDRIVE_API_KEY", "").strip()),
             "publishdrive.com → Settings → API", False),
            ("ElevenLabs", bool(os.environ.get("ELEVENLABS_API_KEY", "").strip()),
             "elevenlabs.io → Profile → API Keys", True),
            ("Anthropic", self.anthropic.key_available(), "console.anthropic.com → API Keys", False),
            ("OpenAI", self.openai.key_available(), "platform.openai.com → API Keys", False),
            ("DeepSeek", self.deepseek.key_available(), "platform.deepseek.com → API Keys", False),
            ("Gemini", self.gemini.key_available(), "aistudio.google.com → API Keys", False),
        ]
        for name, connected, where, optional in checks:
            opt_tag = " (optional)" if optional else ""
            if connected:
                text = f"✅  {name}{opt_tag} — Connected"
                color = "#3cff88"
            else:
                text = f"⚪  {name}{opt_tag} — Not connected · get a key at {where}"
                color = "#999999"
            row = QLabel(text)
            row.setStyleSheet(f"color: {color}; font-size: 12px;")
            self.manuscript_connections_layout.addWidget(row)

    def manuscript_refresh(self):
        """Fetch PublishDrive data and display summary."""
        from services.publishdrive_client import PublishDriveClient
        import json
        self.manuscript_status_label.setText("[Fetching…]")
        try:
            client = PublishDriveClient()
            data = client.get_last_30_days()
            self.manuscript_metrics_box.setPlainText(json.dumps(data, indent=2))
            self.manuscript_status_label.setText("[Done] Data refreshed.")
            self._manuscript_last_data = json.dumps(data)
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")

    def manuscript_ingest_kdp(self):
        """Ingest any new KDP CSV files from data/kdp_reports/."""
        from services.kdp_csv_parser import ingest_new_reports
        ingested = ingest_new_reports()
        if ingested:
            self.manuscript_status_label.setText(f"[Done] Ingested: {', '.join(ingested)}")
        else:
            self.manuscript_status_label.setText("[Info] No new KDP reports found.")

    def manuscript_ask(self):
        """Send a query to ManuscriptAgent with current data as context."""
        query = self.manuscript_query_input.toPlainText().strip()
        if not query:
            return
        provider = self.manuscript_provider_box.currentText()
        model = self.manuscript_model_box.currentText()
        if not model:
            self.manuscript_status_label.setText("[Error] Please select a model.")
            return
        agent = self.agent_instances["manuscript"]
        messages = agent.build_messages(query, context_json=self._manuscript_last_data)
        self.manuscript_status_label.setText("[Thinking…]")
        self.manuscript_ask_btn.setEnabled(False)
        if not self.authorize_request("manuscript", provider, model, query):
            return
        self.manuscript_worker = ChatWorker(self.run_backend, provider, model, messages, query)
        self.manuscript_worker.token_signal.connect(self._manuscript_on_token)
        self.manuscript_worker.finished_signal.connect(self._manuscript_on_finished)
        self.manuscript_worker.usage_signal.connect(lambda u: self.note_request_usage("manuscript", u))
        self.manuscript_worker.error_signal.connect(self._manuscript_on_error)
        self.manuscript_worker.start()

    def _manuscript_on_token(self, token: str):
        cursor = self.manuscript_metrics_box.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.manuscript_metrics_box.setTextCursor(cursor)

    def _manuscript_on_finished(self, _full_response: str):
        self.record_request("manuscript", _full_response)
        self.manuscript_status_label.setText("[Done]")
        self.manuscript_ask_btn.setEnabled(True)

    def _manuscript_on_error(self, error: str):
        self.abandon_request("manuscript")
        self.manuscript_status_label.setText(f"[Error] {error}")
        self.manuscript_ask_btn.setEnabled(True)

    def manuscript_add_todo(self):
        title = self.manuscript_todo_input.text().strip()
        if not title:
            return
        import sqlite3
        from services.database import DB_PATH
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO manuscript_todos (created_at, updated_at, title) VALUES (?, ?, ?)",
            (now, now, title)
        )
        conn.commit()
        conn.close()
        self.manuscript_todo_input.clear()
        self._load_manuscript_todos()

    def manuscript_mark_todo_done(self):
        item = self.manuscript_todo_list.currentItem()
        if not item:
            return
        todo_id = item.data(Qt.UserRole)
        import sqlite3
        from services.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE manuscript_todos SET status='done', updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), todo_id)
        )
        conn.commit()
        conn.close()
        self._load_manuscript_todos()

    def _load_manuscript_todos(self):
        import sqlite3
        from services.database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT id, title, status, platform, notes FROM manuscript_todos ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        self.manuscript_todo_list.clear()
        for row_id, title, status, platform, notes in rows:
            check = "✅" if status == "done" else "○"
            tag = f"[{platform}] " if platform else ""
            info = " ℹ️" if notes else ""
            item = QListWidgetItem(f"{check} {tag}{title}{info}")
            item.setData(Qt.UserRole, row_id)
            if notes:
                item.setToolTip(notes)
            self.manuscript_todo_list.addItem(item)
        self._refresh_next_step_tip()

    def manuscript_generate_quote_graphic(self):
        quote = self.quote_graphic_text.toPlainText().strip()
        if not quote:
            QMessageBox.warning(self, "Missing Quote", "Please enter a quote.")
            return
        from PySide6.QtGui import QPixmap
        from services.quote_graphics import render_quote_graphic, GRAPHICS_DIR
        import time

        attribution = self.quote_graphic_attribution.text().strip()
        theme = theme_key(self.quote_graphic_theme_box)
        size_name = size_key(self.quote_graphic_size_box)
        output_path = unique_output_path(GRAPHICS_DIR, "quote", ".png")
        try:
            render_quote_graphic(quote, output_path, theme=theme, size_name=size_name, attribution=attribution)
            pixmap = QPixmap(str(output_path))
            scaled = pixmap.scaled(320, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.quote_graphic_preview.setPixmap(scaled)
            self.manuscript_status_label.setText(f"[Done] Saved {output_path.name}")
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")

    def manuscript_open_graphics_folder(self):
        from services.quote_graphics import GRAPHICS_DIR
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(GRAPHICS_DIR)))

    def shorts_load_voices(self):
        from ui.book_widgets import populate_voice_box
        populate_voice_box(self.shorts_voice_box, self.shorts_voice_source_box.currentText())

    def manuscript_generate_short(self):
        quote = self.shorts_quote_text.toPlainText().strip()
        if not quote:
            QMessageBox.warning(self, "Missing Quote", "Please enter a quote.")
            return
        from PySide6.QtGui import QPixmap
        from services.quote_graphics import render_quote_graphic
        from services.shorts_generator import SHORTS_DIR
        import time

        attribution = self.shorts_attribution.text().strip()
        theme = theme_key(self.shorts_theme_box)
        use_elevenlabs = self.shorts_voice_source_box.currentText() == "ElevenLabs"
        voice_id = self.shorts_voice_box.currentData() or "default"

        output_path = unique_output_path(SHORTS_DIR, "short", ".mp4")
        image_path = output_path.with_suffix(".png")

        try:
            render_quote_graphic(quote, image_path, theme=theme, size_name="vertical", attribution=attribution)
            pixmap = QPixmap(str(image_path))
            scaled = pixmap.scaled(320, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.shorts_preview.setPixmap(scaled)
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")
            return

        self.shorts_generate_btn.setEnabled(False)
        self.shorts_play_btn.setEnabled(False)
        self._last_short_path = ""
        self.manuscript_status_label.setText("[Narrating…]")

        self.shorts_worker = ShortsWorker(quote, image_path, output_path, use_elevenlabs, voice_id)
        self.shorts_worker.status_signal.connect(self.manuscript_status_label.setText)
        self.shorts_worker.done_signal.connect(self._shorts_on_done)
        self.shorts_worker.error_signal.connect(self._shorts_on_error)
        self.shorts_worker.start()

    def _shorts_on_done(self, output_path: str):
        self._last_short_path = output_path
        self.manuscript_status_label.setText(f"[Done] Saved {Path(output_path).name}")
        self.shorts_generate_btn.setEnabled(True)
        self.shorts_play_btn.setEnabled(True)

    def _shorts_on_error(self, error: str):
        self.manuscript_status_label.setText(f"[Error] {error}")
        self.shorts_generate_btn.setEnabled(True)

    def manuscript_play_short(self):
        if self._last_short_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_short_path))

    def manuscript_open_shorts_folder(self):
        from services.shorts_generator import SHORTS_DIR
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SHORTS_DIR)))

    # ── Quote Finder handlers ─────────────────────────────────────────────────
    def quote_finder_load_voices(self):
        from ui.book_widgets import populate_voice_box
        populate_voice_box(self.quote_finder_voice_box, self.quote_finder_voice_source_box.currentText())

    def quote_finder_load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Manuscript File", "",
            "Text / Ebook Files (*.txt *.pdf *.epub *.mobi)"
        )
        if not path:
            return
        from services.narrator.converter import load_text
        try:
            text = load_text(Path(path))
            self.quote_finder_text.setPlainText(text)
            self.manuscript_status_label.setText(f"[Loaded] {Path(path).name} ({len(text):,} chars)")
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")

    def quote_finder_suggest(self):
        text = self.quote_finder_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Missing Text", "Paste or load manuscript text first.")
            return
        provider = self.manuscript_provider_box.currentText()
        model = self.manuscript_model_box.currentText()
        if not model:
            self.manuscript_status_label.setText("[Error] Select a model on the Overview tab.")
            return
        count = int(self.quote_finder_count_box.currentText())
        # Cap input to keep cost bounded — plenty of text to find a strong batch of quotes.
        truncated = text[:30000]

        agent = self.agent_instances["manuscript"]
        messages = agent.build_quote_suggestions_messages(truncated, count=count)
        self.manuscript_status_label.setText("[Finding quotes…]")
        self.quote_finder_suggest_btn.setEnabled(False)
        if not self.authorize_request("manuscript", provider, model, truncated):
            return
        self.quote_finder_worker = ChatWorker(self.run_backend, provider, model, messages, truncated)
        self.quote_finder_worker.finished_signal.connect(self._quote_finder_on_finished)
        self.quote_finder_worker.usage_signal.connect(lambda u: self.note_request_usage("manuscript", u))
        self.quote_finder_worker.error_signal.connect(self._quote_finder_on_error)
        self.quote_finder_worker.start()

    def _quote_finder_on_finished(self, full_response: str):
        self.record_request("manuscript", full_response)
        self.quote_finder_suggest_btn.setEnabled(True)
        quotes = self._parse_quote_list(full_response)
        self.quote_finder_list.clear()
        self._quote_finder_short_buttons = []
        if not quotes:
            self.manuscript_status_label.setText("[Error] Could not parse quotes from response.")
            return
        for q in quotes:
            item = QListWidgetItem()
            row = self._build_quote_suggestion_row(q)
            item.setSizeHint(row.sizeHint())
            self.quote_finder_list.addItem(item)
            self.quote_finder_list.setItemWidget(item, row)
        self.manuscript_status_label.setText(f"[Done] Found {len(quotes)} quotes.")

    def _quote_finder_on_error(self, error: str):
        self.abandon_request("manuscript")
        self.quote_finder_suggest_btn.setEnabled(True)
        self.manuscript_status_label.setText(f"[Error] {error}")

    def _parse_quote_list(self, text: str) -> list:
        from services.llm_parsing import parse_string_list
        return parse_string_list(text)

    def _build_quote_suggestion_row(self, quote: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(6)

        label = QLabel(quote)
        label.setWordWrap(True)
        h.addWidget(label, 1)

        graphic_btn = QPushButton("🖼")
        graphic_btn.setFixedWidth(36)
        graphic_btn.setToolTip("Generate quote graphic")
        graphic_btn.clicked.connect(lambda checked=False, q=quote: self.quote_finder_generate_graphic(q))
        h.addWidget(graphic_btn)

        short_btn = QPushButton("🎬")
        short_btn.setFixedWidth(36)
        short_btn.setToolTip("Generate narrated short")
        short_btn.clicked.connect(lambda checked=False, q=quote, b=short_btn: self.quote_finder_generate_short(q, b))
        h.addWidget(short_btn)
        self._quote_finder_short_buttons.append(short_btn)

        return row

    def quote_finder_generate_graphic(self, quote: str):
        from services.quote_graphics import render_quote_graphic, GRAPHICS_DIR
        import time
        theme = theme_key(self.quote_finder_theme_box)
        attribution = self.quote_finder_attribution.text().strip()
        output_path = unique_output_path(GRAPHICS_DIR, "quote", ".png")
        try:
            render_quote_graphic(quote, output_path, theme=theme, size_name="square", attribution=attribution)
            self.manuscript_status_label.setText(f"[Done] Saved {output_path.name}")
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")

    def quote_finder_generate_short(self, quote: str, button: QPushButton):
        if self._quote_finder_busy:
            QMessageBox.information(self, "Busy", "A short is already generating — please wait for it to finish.")
            return
        from services.quote_graphics import render_quote_graphic
        from services.shorts_generator import SHORTS_DIR
        import time

        theme = theme_key(self.quote_finder_theme_box)
        attribution = self.quote_finder_attribution.text().strip()
        use_elevenlabs = self.quote_finder_voice_source_box.currentText() == "ElevenLabs"
        voice_id = self.quote_finder_voice_box.currentData() or "default"

        output_path = unique_output_path(SHORTS_DIR, "short", ".mp4")
        image_path = output_path.with_suffix(".png")
        try:
            render_quote_graphic(quote, image_path, theme=theme, size_name="vertical", attribution=attribution)
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")
            return

        self._quote_finder_busy = True
        for b in self._quote_finder_short_buttons:
            b.setEnabled(False)
        button.setText("…")
        self.manuscript_status_label.setText("[Narrating…]")

        self.shorts_worker = ShortsWorker(quote, image_path, output_path, use_elevenlabs, voice_id)
        self.shorts_worker.status_signal.connect(self.manuscript_status_label.setText)
        self.shorts_worker.done_signal.connect(lambda path, b=button: self._quote_finder_short_done(path, b))
        self.shorts_worker.error_signal.connect(lambda err, b=button: self._quote_finder_short_error(err, b))
        self.shorts_worker.start()

    def _quote_finder_short_done(self, output_path: str, button: QPushButton):
        self._last_short_path = output_path
        self.manuscript_status_label.setText(f"[Done] Saved {Path(output_path).name}")
        button.setText("🎬")
        self._quote_finder_busy = False
        for b in self._quote_finder_short_buttons:
            b.setEnabled(True)

    def _quote_finder_short_error(self, error: str, button: QPushButton):
        self.manuscript_status_label.setText(f"[Error] {error}")
        button.setText("⚠")
        self._quote_finder_busy = False
        for b in self._quote_finder_short_buttons:
            b.setEnabled(True)

    # ── Calendar handlers ─────────────────────────────────────────────────────
    def calendar_load_voices(self):
        from ui.book_widgets import populate_voice_box
        populate_voice_box(self.calendar_voice_box, self.calendar_voice_source_box.currentText())

    def _calendar_quotes_from_finder(self) -> list:
        quotes = []
        for i in range(self.quote_finder_list.count()):
            widget = self.quote_finder_list.itemWidget(self.quote_finder_list.item(i))
            if widget:
                label = widget.findChild(QLabel)
                if label:
                    quotes.append(label.text())
        return quotes

    def manuscript_generate_calendar(self):
        quotes = self._calendar_quotes_from_finder()
        if not quotes:
            QMessageBox.warning(self, "No Quotes", "Run 'Suggest Quotes' on the Quote Finder tab first.")
            return

        platforms = []
        if self.calendar_tiktok_check.isChecked():
            platforms.append("TikTok")
        if self.calendar_instagram_check.isChecked():
            platforms.append("Instagram")
        if self.calendar_pinterest_check.isChecked():
            platforms.append("Pinterest")
        if not platforms:
            QMessageBox.warning(self, "No Platforms", "Select at least one platform.")
            return

        provider = self.manuscript_provider_box.currentText()
        model = self.manuscript_model_box.currentText()
        if not model:
            self.manuscript_status_label.setText("[Error] Select a model on the Overview tab.")
            return

        weeks = int(self.calendar_weeks_box.currentText())
        start_date = self.calendar_start_date.date().toPython()

        from services.content_calendar import build_calendar
        slots = build_calendar(quotes, weeks, start_date, platforms)
        if not slots:
            self.manuscript_status_label.setText("[Error] Could not build a calendar.")
            return
        self._calendar_slots = slots

        items = [{"quote": s.quote, "platform": s.platform.lower()} for s in slots]
        items_json = json.dumps(items)
        agent = self.agent_instances["manuscript"]
        messages = agent.build_calendar_caption_messages(items_json)
        self.manuscript_status_label.setText("[Writing captions…]")
        self.calendar_generate_btn.setEnabled(False)
        if not self.authorize_request("manuscript", provider, model, items_json):
            return
        self.calendar_worker = ChatWorker(self.run_backend, provider, model, messages, items_json)
        self.calendar_worker.finished_signal.connect(self._calendar_on_captions_done)
        self.calendar_worker.usage_signal.connect(lambda u: self.note_request_usage("manuscript", u))
        self.calendar_worker.error_signal.connect(self._calendar_on_captions_error)
        self.calendar_worker.start()

    def _calendar_on_captions_done(self, full_response: str):
        self.record_request("manuscript", full_response)
        self.calendar_generate_btn.setEnabled(True)
        captions = self._parse_quote_list(full_response)
        for i, slot in enumerate(self._calendar_slots):
            slot.caption = captions[i] if i < len(captions) else ""
        self._populate_calendar_table()
        self.manuscript_status_label.setText(f"[Done] {len(self._calendar_slots)}-post calendar generated.")

    def _calendar_on_captions_error(self, error: str):
        self.abandon_request("manuscript")
        self.calendar_generate_btn.setEnabled(True)
        self._populate_calendar_table()
        self.manuscript_status_label.setText(f"[Error] Captions failed ({error}) — schedule shown, captions blank.")

    def _populate_calendar_table(self):
        from PySide6.QtWidgets import QTableWidgetItem
        self.calendar_table.setRowCount(len(self._calendar_slots))
        for row, slot in enumerate(self._calendar_slots):
            self.calendar_table.setItem(row, 0, QTableWidgetItem(slot.day.strftime("%Y-%m-%d")))
            self.calendar_table.setItem(row, 1, QTableWidgetItem(slot.platform))
            self.calendar_table.setItem(row, 2, QTableWidgetItem(slot.format))
            self.calendar_table.setItem(row, 3, QTableWidgetItem(slot.quote))
            self.calendar_table.setItem(row, 4, QTableWidgetItem(slot.caption))

            icon = "🖼" if slot.format == "graphic" else "🎬"
            btn = QPushButton(icon)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda checked=False, r=row, b=btn: self.calendar_generate_asset(r, b))
            self.calendar_table.setCellWidget(row, 5, btn)

    def calendar_generate_asset(self, row: int, button: QPushButton):
        if row >= len(self._calendar_slots):
            return
        slot = self._calendar_slots[row]
        from services.quote_graphics import render_quote_graphic
        import time

        theme = theme_key(self.calendar_theme_box)
        attribution = self.calendar_attribution.text().strip()

        if slot.format == "graphic":
            from services.quote_graphics import GRAPHICS_DIR
            output_path = unique_output_path(GRAPHICS_DIR, "quote", ".png")
            try:
                render_quote_graphic(slot.quote, output_path, theme=theme, size_name="square", attribution=attribution)
                self.manuscript_status_label.setText(f"[Done] Saved {output_path.name}")
            except Exception as e:
                self.manuscript_status_label.setText(f"[Error] {e}")
            return

        if self._quote_finder_busy:
            QMessageBox.information(self, "Busy", "A short is already generating — please wait for it to finish.")
            return
        from services.shorts_generator import SHORTS_DIR
        use_elevenlabs = self.calendar_voice_source_box.currentText() == "ElevenLabs"
        voice_id = self.calendar_voice_box.currentData() or "default"
        output_path = unique_output_path(SHORTS_DIR, "short", ".mp4")
        image_path = output_path.with_suffix(".png")
        try:
            render_quote_graphic(slot.quote, image_path, theme=theme, size_name="vertical", attribution=attribution)
        except Exception as e:
            self.manuscript_status_label.setText(f"[Error] {e}")
            return

        self._quote_finder_busy = True
        button.setEnabled(False)
        self.manuscript_status_label.setText("[Narrating…]")
        self.shorts_worker = ShortsWorker(slot.quote, image_path, output_path, use_elevenlabs, voice_id)
        self.shorts_worker.status_signal.connect(self.manuscript_status_label.setText)
        self.shorts_worker.done_signal.connect(lambda path, b=button: self._calendar_short_done(path, b))
        self.shorts_worker.error_signal.connect(lambda err, b=button: self._calendar_short_error(err, b))
        self.shorts_worker.start()

    def _calendar_short_done(self, output_path: str, button: QPushButton):
        self._last_short_path = output_path
        self.manuscript_status_label.setText(f"[Done] Saved {Path(output_path).name}")
        button.setEnabled(True)
        self._quote_finder_busy = False

    def _calendar_short_error(self, error: str, button: QPushButton):
        self.manuscript_status_label.setText(f"[Error] {error}")
        button.setEnabled(True)
        self._quote_finder_busy = False

    def manuscript_export_calendar_csv(self):
        if not self._calendar_slots:
            QMessageBox.warning(self, "No Calendar", "Generate a calendar first.")
            return
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Calendar", str(BASE_DIR / "content_calendar.csv"), "CSV Files (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Platform", "Format", "Quote", "Caption"])
            for slot in self._calendar_slots:
                writer.writerow([slot.day.strftime("%Y-%m-%d"), slot.platform, slot.format, slot.quote, slot.caption])
        self.manuscript_status_label.setText(f"[Done] Exported calendar to {Path(path).name}")

    # ── Music handlers ────────────────────────────────────────────────────────
    def music_load_models(self):
        provider = self.music_provider_box.currentText()
        self.music_model_box.clear()
        try:
            if provider == "ollama":
                models = self.ollama.list_models()
            elif provider == "openai":
                models = self.openai.list_models()
            elif provider == "deepseek":
                models = self.deepseek.list_models()
            elif provider == "kimi":
                models = self.kimi.list_models()
            elif provider == "gemini":
                models = self.gemini.list_models()
            elif provider == "anthropic":
                models = self.anthropic.list_models()
            elif provider == "qwen":
                models = self.qwen.list_models()
            else:
                models = []
        except Exception:
            models = []
        self.music_model_box.addItems(models)

    def music_analyse(self):
        description = self.music_query_input.toPlainText().strip()
        artist = self.music_artist_input.text().strip()
        genre = self.music_genre_box.currentText()
        release_type = self.music_release_type_box.currentText()
        distributor = self.music_distributor_box.currentText()
        audience = self.music_audience_input.text().strip()
        provider = self.music_provider_box.currentText()
        model = self.music_model_box.currentText()

        if not description:
            QMessageBox.warning(self, "Missing Input", "Please describe your music in the text box.")
            return
        if not model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        prompt_parts = []
        if artist:
            prompt_parts.append(f"Artist / Project Name: {artist}")
        prompt_parts += [
            f"Genre: {genre}",
            f"Release Type: {release_type}",
            f"Current Distributor: {distributor}",
        ]
        if audience:
            prompt_parts.append(f"Target Audience: {audience}")
        prompt_parts.append(f"\nMusic Description:\n{description}")
        prompt = "\n".join(prompt_parts)

        agent = self.agent_instances["music"]
        messages = agent.build_messages(prompt)

        self._music_clear_displays()
        self._last_music_response = ""
        self.music_release_label.setText(release_type.split(" ")[0])
        self.music_genre_label.setText(genre)
        self.music_dist_label.setText(distributor if distributor != "Not signed up yet" else "None yet")
        self.music_status_label.setText("Generating Spotify plan…")
        self.music_analyse_btn.setEnabled(False)
        self.music_stop_btn.setEnabled(True)
        self.music_save_btn.setEnabled(False)

        if not self.authorize_request("music", provider, model, prompt):
            return
        self.music_worker = ChatWorker(self.run_backend, provider, model, messages, prompt)
        self.music_worker.token_signal.connect(self._music_on_token)
        self.music_worker.finished_signal.connect(self._music_on_finished)
        self.music_worker.usage_signal.connect(lambda u: self.note_request_usage("music", u))
        self.music_worker.error_signal.connect(self._music_on_error)
        self.music_worker.start()

    def _music_on_token(self, token: str):
        self._last_music_response += token
        self.music_profile_box.setPlainText(self._last_music_response)
        self.music_profile_box.moveCursor(QTextCursor.End)

    def _music_on_finished(self, full_response: str):
        self.record_request("music", full_response)
        self._last_music_response = full_response
        self._populate_music_tabs(full_response)
        self.music_status_label.setText("Plan complete — tabs populated.")
        self.music_analyse_btn.setEnabled(True)
        self.music_stop_btn.setEnabled(False)
        self.music_save_btn.setEnabled(True)

    def _music_on_error(self, error: str):
        self.abandon_request("music")
        self.music_profile_box.setPlainText(f"[Error] {error}")
        self.music_status_label.setText("Error.")
        self.music_analyse_btn.setEnabled(True)
        self.music_stop_btn.setEnabled(False)

    def music_stop(self):
        if self.music_worker is not None and self.music_worker.isRunning():
            self.music_worker.cancel()
        self.music_status_label.setText("Stopped.")
        self.music_analyse_btn.setEnabled(True)
        self.music_stop_btn.setEnabled(False)

    def music_save(self):
        if not self._last_music_response:
            return
        artist = self.music_artist_input.text().strip().lower().replace(" ", "_") or "artist"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"spotify_plan_{artist}_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Spotify Plan", str(DATA_DIR / default_name), "Text files (*.txt);;All files (*)"
        )
        if path:
            Path(path).write_text(self._last_music_response, encoding="utf-8")
            self.music_status_label.setText(f"Saved to {Path(path).name}")

    def music_clear(self):
        self._music_clear_displays()
        self.music_query_input.clear()
        self.music_artist_input.clear()
        self.music_audience_input.clear()
        self.music_status_label.setText("")
        self._last_music_response = ""

    def _music_clear_displays(self):
        for box in (
            self.music_profile_box,
            self.music_release_box,
            self.music_distribution_box,
            self.music_strategy_box,
            self.music_income_box,
        ):
            box.clear()
        self.music_release_label.setText("—")
        self.music_genre_label.setText("—")
        self.music_dist_label.setText("—")
        self.music_save_btn.setEnabled(False)

    def _populate_music_tabs(self, text: str):
        sections = self._parse_music_sections(text)
        self.music_profile_box.setPlainText(sections.get("profile", text))
        self.music_release_box.setPlainText(sections.get("release", ""))
        self.music_distribution_box.setPlainText(sections.get("distribution", ""))
        self.music_strategy_box.setPlainText(sections.get("strategy", ""))
        self.music_income_box.setPlainText(sections.get("income", ""))

    def _parse_music_sections(self, text: str) -> dict:
        patterns = {
            "profile":      r"1\.\s*ARTIST PROFILE(.*?)(?=2\.\s*RELEASE SETUP|$)",
            "release":      r"2\.\s*RELEASE SETUP(.*?)(?=3\.\s*DISTRIBUTION GUIDE|$)",
            "distribution": r"3\.\s*DISTRIBUTION GUIDE(.*?)(?=4\.\s*SPOTIFY STRATEGY|$)",
            "strategy":     r"4\.\s*SPOTIFY STRATEGY(.*?)(?=5\.\s*INCOME ROADMAP|$)",
            "income":       r"5\.\s*INCOME ROADMAP(.*?)$",
        }
        result = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            result[key] = m.group(1).strip() if m else ""
        return result

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
        cards_layout.setContentsMargins(2, 2, 2, 2)
        cards_layout.setSpacing(8)

        # ── Card 1: System ──────────────────────────────────────────────
        system_card = QGroupBox("SYSTEM")
        system_card.setObjectName("RightCard")
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(10, 6, 10, 10)
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

        self.realtime_monitor_btn = QPushButton("⚡ Realtime Monitor")
        self.realtime_monitor_btn.setEnabled(False)
        system_layout.addWidget(self.realtime_monitor_btn)

        cards_layout.addWidget(system_card)

        # ── Card 2: Routing & Recommendation ────────────────────────────
        routing_card = QGroupBox("ROUTING")
        routing_card.setObjectName("RightCard")
        routing_layout = QVBoxLayout(routing_card)
        routing_layout.setContentsMargins(10, 6, 10, 10)
        routing_layout.setSpacing(6)

        self.route_result_label = QLabel("Router: not yet computed")
        self.route_result_label.setWordWrap(True)
        routing_layout.addWidget(self.route_result_label)

        self.recommendation_label = QLabel("Recommendation: not yet calculated")
        self.recommendation_label.setWordWrap(True)
        routing_layout.addWidget(self.recommendation_label)

        cards_layout.addWidget(routing_card)

        # ── Card 3: Cost ────────────────────────────────────────────────
        cost_card = QGroupBox("COST")
        cost_card.setObjectName("RightCard")
        cost_layout = QVBoxLayout(cost_card)
        cost_layout.setContentsMargins(10, 6, 10, 10)
        cost_layout.setSpacing(6)

        self.live_estimate_label = QLabel("Estimated Request Cost: -")
        self.live_estimate_label.setWordWrap(True)
        cost_layout.addWidget(self.live_estimate_label)

        self.last_request_label = QLabel("Last Request Cost: €0.00")
        cost_layout.addWidget(self.last_request_label)

        cost_divider = QFrame()
        cost_divider.setFrameShape(QFrame.HLine)
        cost_divider.setObjectName("CardDivider")
        cost_layout.addWidget(cost_divider)

        self.session_cost_label = QLabel("Session Cost: €0.00")
        cost_layout.addWidget(self.session_cost_label)

        self.today_cost_label = QLabel("Cost Today: €0.00")
        cost_layout.addWidget(self.today_cost_label)

        self.request_count_label = QLabel("Requests Today: 0 | Session: 0")
        cost_layout.addWidget(self.request_count_label)

        cards_layout.addWidget(cost_card)

        # ── Card 4: Budget ──────────────────────────────────────────────
        budget_card = QGroupBox("BUDGET")
        budget_card.setObjectName("RightCard")
        budget_layout = QVBoxLayout(budget_card)
        budget_layout.setContentsMargins(10, 6, 10, 10)
        budget_layout.setSpacing(6)

        # Spend is "x of y" too, and the one figure worth seeing without reading.
        self.budget_meters = {
            "SESSION": Meter("SESSION", "Spent this session against the session cap"),
            "DAILY": Meter("DAILY", "Spent today against the daily cap"),
        }
        for meter in self.budget_meters.values():
            budget_layout.addWidget(meter)

        session_row = QHBoxLayout()
        session_row.setSpacing(8)
        session_lbl = QLabel("Session €")
        session_lbl.setMinimumWidth(70)
        session_row.addWidget(session_lbl)
        self.session_budget_input = QLineEdit(str(int(self.session_budget_eur)))
        self.session_budget_input.setPlaceholderText("1")
        self.session_budget_input.setAlignment(Qt.AlignRight)
        self.session_budget_input.setMaximumWidth(70)
        session_row.addWidget(self.session_budget_input)
        session_row.addStretch()
        budget_layout.addLayout(session_row)

        daily_row = QHBoxLayout()
        daily_row.setSpacing(8)
        daily_lbl = QLabel("Daily €")
        daily_lbl.setMinimumWidth(70)
        daily_row.addWidget(daily_lbl)
        self.daily_budget_input = QLineEdit(str(int(self.daily_budget_eur)))
        self.daily_budget_input.setPlaceholderText("5")
        self.daily_budget_input.setAlignment(Qt.AlignRight)
        self.daily_budget_input.setMaximumWidth(70)
        daily_row.addWidget(self.daily_budget_input)
        daily_row.addStretch()
        budget_layout.addLayout(daily_row)

        self.save_budget_btn = QPushButton("Save Limits")
        self.save_budget_btn.clicked.connect(self.save_budget_limits)
        budget_layout.addWidget(self.save_budget_btn)

        self.reset_session_budget_btn = QPushButton("Reset Session Spend")
        self.reset_session_budget_btn.clicked.connect(self.reset_session_spend)
        budget_layout.addWidget(self.reset_session_budget_btn)

        cards_layout.addWidget(budget_card)

        # ── Card 5: Quick Actions ───────────────────────────────────────
        actions_card = QGroupBox("ACTIONS")
        actions_card.setObjectName("RightCard")
        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(10, 6, 10, 10)
        actions_layout.setSpacing(6)

        self.cost_history_btn = QPushButton("📊  Cost History")
        self.cost_history_btn.clicked.connect(self.show_cost_history)
        actions_layout.addWidget(self.cost_history_btn)

        self.run_log_btn = QPushButton("📜  Run Log")
        self.run_log_btn.clicked.connect(self.show_run_log)
        actions_layout.addWidget(self.run_log_btn)

        self.settings_btn = QPushButton("⚙   Settings")
        self.settings_btn.clicked.connect(self.show_settings)
        actions_layout.addWidget(self.settings_btn)

        cards_layout.addWidget(actions_card)

        # ── Card 6: API Keys ────────────────────────────────────────────
        keys_card = QGroupBox("API KEYS")
        keys_card.setObjectName("RightCard")
        keys_layout = QVBoxLayout(keys_card)
        keys_layout.setContentsMargins(10, 6, 10, 10)
        keys_layout.setSpacing(4)

        self.openai_key_label = QLabel(f"OpenAI: {self.safe_key_status(OpenAIClientWrapper)}")
        keys_layout.addWidget(self.openai_key_label)

        self.deepseek_key_label = QLabel(f"DeepSeek: {self.safe_key_status(DeepSeekClientWrapper)}")
        keys_layout.addWidget(self.deepseek_key_label)

        self.kimi_key_label = QLabel(f"Kimi: {self.safe_key_status(KimiClientWrapper)}")
        keys_layout.addWidget(self.kimi_key_label)

        self.gemini_key_label = QLabel(f"Gemini: {self.safe_key_status(GeminiClientWrapper)}")
        keys_layout.addWidget(self.gemini_key_label)

        self.anthropic_key_label = QLabel(f"Anthropic: {self.safe_key_status(AnthropicClientWrapper)}")
        keys_layout.addWidget(self.anthropic_key_label)

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
            background-color: #0f0f0f;
        }
        QWidget#RightCardsContainer {
            background-color: transparent;
        }

        QGroupBox#RightCard {
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 10px;
            /* The title is drawn in this top margin. Card padding and each card
               layout's own top margin both apply *inside*, so they stack: keep
               their sum at a deliberate ~16px. It was ~30px (baggy) and briefly
               ~6px (cramped, title crowding the border). */
            margin-top: 16px;
            padding: 10px 12px 10px 12px;
        }
        QGroupBox#RightCard::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 4px;
            top: 0px;
            padding: 0 6px;
            background-color: transparent;
            color: #707070;
            font-size: 10px;
            font-weight: bold;
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

    def build_bug_bounty_panel(self):
        self.bug_bounty_panel = QWidget()
        self.bug_bounty_panel.setObjectName("BugBountyPanel")
        layout = QVBoxLayout(self.bug_bounty_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Target / program setup ───────────────────────────────────────────
        setup_group = QGroupBox("Target & Program")
        setup_group.setObjectName("BBSetupBox")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Target URL / IP:"), 0, 0)
        self.bb_target_input = QLineEdit()
        self.bb_target_input.setPlaceholderText("https://target.example.com  or  10.0.0.1")
        setup_layout.addWidget(self.bb_target_input, 0, 1, 1, 3)

        setup_layout.addWidget(QLabel("Program:"), 1, 0)
        self.bb_program_input = QLineEdit()
        self.bb_program_input.setPlaceholderText("HackerOne — Acme Corp  /  Bugcrowd — Example")
        setup_layout.addWidget(self.bb_program_input, 1, 1, 1, 3)

        setup_layout.addWidget(QLabel("Scope Type:"), 2, 0)
        self.bb_scope_box = QComboBox()
        self.bb_scope_box.addItems([
            "Web Application", "API / REST", "Mobile (Android)", "Mobile (iOS)",
            "Network / Infrastructure", "Source Code Review", "Cloud Config", "Other",
        ])
        setup_layout.addWidget(self.bb_scope_box, 2, 1)

        setup_layout.addWidget(QLabel("Severity Target:"), 2, 2)
        self.bb_severity_box = QComboBox()
        self.bb_severity_box.addItems(["Critical (P1)", "High (P2)", "Medium (P3)", "Low (P4)", "Informational"])
        setup_layout.addWidget(self.bb_severity_box, 2, 3)

        layout.addWidget(setup_group)

        # ── Nmap scan section ────────────────────────────────────────────────
        nmap_group = QGroupBox("Nmap Recon Scan")
        nmap_group.setObjectName("BBNmapBox")
        nmap_layout = QVBoxLayout(nmap_group)
        nmap_layout.setSpacing(4)

        nmap_cmd_row = QHBoxLayout()
        self.bb_nmap_cmd_input = QLineEdit()
        self.bb_nmap_cmd_input.setPlaceholderText("nmap -sV -sC -T4 --open <target>")
        nmap_cmd_row.addWidget(self.bb_nmap_cmd_input, 1)
        self.bb_nmap_run_btn = QPushButton("Run Nmap")
        self.bb_nmap_run_btn.setMinimumWidth(120)
        self.bb_nmap_run_btn.setObjectName("PrimaryAction")
        self.bb_nmap_run_btn.clicked.connect(self.bb_run_nmap)
        nmap_cmd_row.addWidget(self.bb_nmap_run_btn)
        self.bb_nmap_stop_btn = QPushButton("Kill")
        self.bb_nmap_stop_btn.setEnabled(False)
        self.bb_nmap_stop_btn.setObjectName("DangerAction")
        self.bb_nmap_stop_btn.clicked.connect(self.bb_kill_nmap)
        nmap_cmd_row.addWidget(self.bb_nmap_stop_btn)
        nmap_layout.addLayout(nmap_cmd_row)

        self.bb_nmap_output = QTextBrowser()
        self.bb_nmap_output.setOpenExternalLinks(False)
        self.bb_nmap_output.setFixedHeight(130)
        self.bb_nmap_output.setPlaceholderText("Nmap output will appear here…")
        nmap_layout.addWidget(self.bb_nmap_output)
        layout.addWidget(nmap_group)

        # ── Findings / Burp paste area ───────────────────────────────────────
        findings_group = QGroupBox("Findings / Burp Suite Output / Notes")
        findings_group.setObjectName("BBFindingsBox")
        findings_layout = QVBoxLayout(findings_group)
        self.bb_findings_input = QTextEdit()
        self.bb_findings_input.setPlaceholderText(
            "Paste HTTP request/response, Burp Suite output, manual observations, "
            "error messages, source code snippets — anything in scope."
        )
        self.bb_findings_input.setMinimumHeight(110)
        findings_layout.addWidget(self.bb_findings_input)
        layout.addWidget(findings_group)

        # ── Provider row ─────────────────────────────────────────────────────
        provider_row_container = QWidget()
        provider_row = FlowLayout(provider_row_container, spacing=6)
        provider_row.addWidget(QLabel("Provider:"))
        self.bb_provider_box = QComboBox()
        self.bb_provider_box.addItems(["ollama", "openai", "deepseek", "kimi", "gemini", "anthropic", "qwen"])
        self.bb_provider_box.setCurrentText("anthropic")
        provider_row.addWidget(self.bb_provider_box)
        provider_row.addWidget(QLabel("Model:"))
        self.bb_model_box = QComboBox()
        self.bb_model_box.setMinimumWidth(200)
        provider_row.addWidget(self.bb_model_box)

        self.bb_analyse_btn = QPushButton("Analyse")
        self.bb_analyse_btn.setMinimumWidth(130)
        self.bb_analyse_btn.setObjectName("PrimaryAction")
        self.bb_analyse_btn.clicked.connect(self.bb_analyse)
        provider_row.addWidget(self.bb_analyse_btn)

        self.bb_stop_btn = QPushButton("Stop")
        self.bb_stop_btn.setEnabled(False)
        self.bb_stop_btn.setObjectName("DangerAction")
        self.bb_stop_btn.clicked.connect(self.bb_stop)
        provider_row.addWidget(self.bb_stop_btn)
        layout.addWidget(provider_row_container)

        # ── Results: tabs + sidebar ───────────────────────────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.bb_tabs = QTabWidget()

        self.bb_report_box = QTextBrowser()
        self.bb_report_box.setOpenExternalLinks(False)
        self.bb_tabs.addTab(self.bb_report_box, "Full Report")

        self.bb_vuln_box = QTextBrowser()
        self.bb_tabs.addTab(self.bb_vuln_box, "Vulnerability")

        self.bb_poc_box = QTextBrowser()
        self.bb_tabs.addTab(self.bb_poc_box, "PoC Draft")

        self.bb_remediation_box = QTextBrowser()
        self.bb_tabs.addTab(self.bb_remediation_box, "Remediation")

        self.bb_submission_box = QTextBrowser()
        self.bb_tabs.addTab(self.bb_submission_box, "Submission")

        results_splitter.addWidget(self.bb_tabs)

        # Sidebar indicators
        indicators_widget = QWidget()
        ind_layout = QVBoxLayout(indicators_widget)
        ind_layout.setContentsMargins(8, 0, 0, 0)
        ind_layout.setSpacing(10)

        sev_group = QGroupBox("Severity")
        sev_group.setObjectName("BBSevBox")
        sev_inner = QVBoxLayout(sev_group)
        self.bb_severity_label = QLabel("—")
        self.bb_severity_label.setAlignment(Qt.AlignCenter)
        self.bb_severity_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ff5555;")
        sev_inner.addWidget(self.bb_severity_label)
        ind_layout.addWidget(sev_group)

        cvss_group = QGroupBox("CVSS Score")
        cvss_group.setObjectName("BBCvssBox")
        cvss_inner = QVBoxLayout(cvss_group)
        self.bb_cvss_label = QLabel("—")
        self.bb_cvss_label.setAlignment(Qt.AlignCenter)
        self.bb_cvss_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        cvss_inner.addWidget(self.bb_cvss_label)
        ind_layout.addWidget(cvss_group)

        bounty_group = QGroupBox("Bounty Estimate")
        bounty_group.setObjectName("BBBountyBox")
        bounty_inner = QVBoxLayout(bounty_group)
        self.bb_bounty_label = QLabel("—")
        self.bb_bounty_label.setAlignment(Qt.AlignCenter)
        self.bb_bounty_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #3cff88;")
        bounty_inner.addWidget(self.bb_bounty_label)
        ind_layout.addWidget(bounty_group)

        ind_layout.addStretch()

        self.bb_save_btn = QPushButton("Save Report")
        self.bb_save_btn.setEnabled(False)
        self.bb_save_btn.clicked.connect(self.bb_save)
        ind_layout.addWidget(self.bb_save_btn)

        self.bb_clear_btn = QPushButton("Clear")
        self.bb_clear_btn.clicked.connect(self.bb_clear)
        ind_layout.addWidget(self.bb_clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([700, 200])
        layout.addWidget(results_splitter, 1)

        self.bb_status_label = QLabel("")
        self.bb_status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.bb_status_label)

        self.bug_bounty_panel.hide()
        self._bb_nmap_process: Optional[QProcess] = None

        self.bb_provider_box.currentTextChanged.connect(self.bb_load_models)
        self.bb_load_models()

    # ── Bug Bounty handlers ───────────────────────────────────────────────────
    def bb_load_models(self):
        provider = self.bb_provider_box.currentText()
        self.bb_model_box.clear()
        self.bb_model_box.addItems(self.models_for_provider(provider))

    def bb_run_nmap(self):
        cmd_text = self.bb_nmap_cmd_input.text().strip()
        if not cmd_text:
            target = self.bb_target_input.text().strip()
            if not target:
                self.bb_nmap_output.setPlainText("[Error] Enter a target URL/IP or nmap command first.")
                return
            # strip protocol for nmap
            host = target.replace("https://", "").replace("http://", "").split("/")[0]
            cmd_text = f"nmap -sV -sC -T4 --open {host}"
            self.bb_nmap_cmd_input.setText(cmd_text)

        self.bb_nmap_output.setPlainText(f"[Running] {cmd_text}\n")
        self.bb_nmap_run_btn.setEnabled(False)
        self.bb_nmap_stop_btn.setEnabled(True)

        self._bb_nmap_process = QProcess(self)
        self._bb_nmap_process.setProcessChannelMode(QProcess.MergedChannels)
        self._bb_nmap_process.readyRead.connect(self._bb_nmap_read)
        self._bb_nmap_process.finished.connect(self._bb_nmap_finished)

        parts = cmd_text.split()
        self._bb_nmap_process.start(parts[0], parts[1:])

    def _bb_nmap_read(self):
        data = self._bb_nmap_process.readAll().data().decode("utf-8", errors="replace")
        self.bb_nmap_output.moveCursor(QTextCursor.End)
        self.bb_nmap_output.insertPlainText(data)
        self.bb_nmap_output.moveCursor(QTextCursor.End)

    def _bb_nmap_finished(self):
        self.bb_nmap_run_btn.setEnabled(True)
        self.bb_nmap_stop_btn.setEnabled(False)
        self.bb_nmap_output.moveCursor(QTextCursor.End)
        self.bb_nmap_output.insertPlainText("\n[Done]")

    def bb_kill_nmap(self):
        if self._bb_nmap_process is not None:
            self._bb_nmap_process.kill()
        self.bb_nmap_run_btn.setEnabled(True)
        self.bb_nmap_stop_btn.setEnabled(False)

    def bb_analyse(self):
        target = self.bb_target_input.text().strip()
        program = self.bb_program_input.text().strip()
        scope_type = self.bb_scope_box.currentText()
        findings = self.bb_findings_input.toPlainText().strip()
        nmap_output = self.bb_nmap_output.toPlainText().strip()

        if not target and not findings and not nmap_output:
            self.bb_status_label.setText("Enter a target, paste findings, or run a scan first.")
            return

        provider = self.bb_provider_box.currentText()
        model = self.bb_model_box.currentText()
        if not model:
            self.bb_status_label.setText("Select a model first.")
            return

        agent = self.agent_instances["bug_bounty"]
        messages = agent.build_messages(target, program, scope_type, findings, nmap_output)

        self._last_bb_response = ""
        self.bb_report_box.clear()
        self.bb_vuln_box.clear()
        self.bb_poc_box.clear()
        self.bb_remediation_box.clear()
        self.bb_submission_box.clear()
        self.bb_severity_label.setText("—")
        self.bb_cvss_label.setText("—")
        self.bb_bounty_label.setText("—")
        self.bb_save_btn.setEnabled(False)
        self.bb_status_label.setText("Analysing…")
        self.bb_analyse_btn.setEnabled(False)
        self.bb_stop_btn.setEnabled(True)
        self.bb_tabs.setCurrentIndex(0)

        if not self.authorize_request("bug_bounty", provider, model, target or "bug_bounty"):
            return
        self.bug_bounty_worker = ChatWorker(self.run_backend, provider, model, messages, target or "bug_bounty")
        self.bug_bounty_worker.token_signal.connect(self._bb_on_token)
        self.bug_bounty_worker.finished_signal.connect(self._bb_on_finished)
        self.bug_bounty_worker.usage_signal.connect(lambda u: self.note_request_usage("bug_bounty", u))
        self.bug_bounty_worker.error_signal.connect(self._bb_on_error)
        self.bug_bounty_worker.start()

    def _bb_on_token(self, token: str):
        self._last_bb_response += token
        self.bb_report_box.setPlainText(self._last_bb_response)
        self.bb_report_box.moveCursor(QTextCursor.End)

    def _bb_on_finished(self, full_response: str):
        self.record_request("bug_bounty", full_response)
        self._last_bb_response = full_response
        self._bb_populate_tabs(full_response)
        self._bb_update_indicators(full_response)
        self.bb_status_label.setText("Analysis complete.")
        self.bb_analyse_btn.setEnabled(True)
        self.bb_stop_btn.setEnabled(False)
        self.bb_save_btn.setEnabled(True)
        self.bb_tabs.setCurrentIndex(0)

    def _bb_on_error(self, error: str):
        self.abandon_request("bug_bounty")
        self.bb_report_box.setPlainText(f"[Error] {error}")
        self.bb_status_label.setText("Error.")
        self.bb_analyse_btn.setEnabled(True)
        self.bb_stop_btn.setEnabled(False)

    def bb_stop(self):
        if self.bug_bounty_worker is not None and self.bug_bounty_worker.isRunning():
            self.bug_bounty_worker.cancel()
        self.bb_status_label.setText("Stopped.")
        self.bb_analyse_btn.setEnabled(True)
        self.bb_stop_btn.setEnabled(False)

    def _bb_populate_tabs(self, text: str):
        import re as _re

        def extract(pattern):
            m = _re.search(pattern, text, _re.IGNORECASE | _re.DOTALL)
            return m.group(1).strip() if m else ""

        vuln = extract(r"(?:##\s*VULNERABILITY\s*REPORT|##\s*Vulnerability Details?)(.*?)(?=##|$)")
        poc = extract(r"(?:##\s*Proof of Concept|PoC\s*Draft?)(.*?)(?=##|$)")
        rem = extract(r"(?:##\s*Remediation)(.*?)(?=##|$)")
        sub = extract(r"(?:##\s*SUBMISSION\s*DRAFT|Submission\s*Draft?)(.*?)(?=##|$)")

        self.bb_vuln_box.setPlainText(vuln or text)
        self.bb_poc_box.setPlainText(poc)
        self.bb_remediation_box.setPlainText(rem)
        self.bb_submission_box.setPlainText(sub)

    def _bb_update_indicators(self, text: str):
        import re as _re

        sev_m = _re.search(r"\*\*Severity\*\*.*?(Critical|High|Medium|Low|Informational)", text, _re.IGNORECASE)
        if sev_m:
            sev = sev_m.group(1).capitalize()
            colors = {"Critical": "#ff3333", "High": "#ff7722", "Medium": "#f0c040",
                      "Low": "#3cff88", "Informational": "#4db8ff"}
            self.bb_severity_label.setText(sev)
            self.bb_severity_label.setStyleSheet(
                f"font-size: 20px; font-weight: bold; color: {colors.get(sev, '#ffffff')};"
            )

        cvss_m = _re.search(r"CVSS.*?(\d+\.\d+)", text, _re.IGNORECASE)
        if cvss_m:
            score = float(cvss_m.group(1))
            color = "#ff3333" if score >= 9 else "#ff7722" if score >= 7 else "#f0c040" if score >= 4 else "#3cff88"
            self.bb_cvss_label.setText(cvss_m.group(1))
            self.bb_cvss_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")

        bounty_m = _re.search(r"bounty.*?(\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?|\$[\d,]+\+?)", text, _re.IGNORECASE)
        if bounty_m:
            self.bb_bounty_label.setText(bounty_m.group(1))

    def bb_save(self):
        if not self._last_bb_response:
            return
        target = self.bb_target_input.text().strip().replace("/", "-").replace(":", "").replace(" ", "_") or "target"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = QFileDialog.getSaveFileName(
            self, "Save Bug Bounty Report",
            str(Path.home() / "Downloads" / f"bb_report_{target}_{ts}.md"),
            "Markdown (*.md);;Text (*.txt)",
        )[0]
        if path:
            Path(path).write_text(self._last_bb_response, encoding="utf-8")
            self.bb_status_label.setText(f"Saved: {path}")

    def bb_clear(self):
        self.bb_target_input.clear()
        self.bb_program_input.clear()
        self.bb_findings_input.clear()
        self.bb_nmap_output.clear()
        self.bb_nmap_cmd_input.clear()
        for box in (self.bb_report_box, self.bb_vuln_box, self.bb_poc_box,
                    self.bb_remediation_box, self.bb_submission_box):
            box.clear()
        self.bb_severity_label.setText("—")
        self.bb_severity_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ff5555;")
        self.bb_cvss_label.setText("—")
        self.bb_cvss_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.bb_bounty_label.setText("—")
        self.bb_status_label.setText("")
        self.bb_save_btn.setEnabled(False)
        self._last_bb_response = ""

    # ──────────────────────────────────────────────────────────────────
    # Manager Agent handlers
    # ──────────────────────────────────────────────────────────────────

    def manager_load_models(self):
        provider = self.manager_provider_box.currentText()
        self.manager_model_box.clear()
        models = self.models_for_provider(provider)
        if models:
            self.manager_model_box.addItems(models)
        else:
            self.manager_model_box.addItems(
                ["(no local models)" if provider == "ollama" else "(unavailable)"]
            )

    def manager_analyze_idea(self):
        idea = self.manager_idea_input.toPlainText().strip()
        if not idea:
            QMessageBox.warning(self, "No Idea", "Please describe your agent idea first.")
            return

        if self.manager_worker is not None and self.manager_worker.isRunning():
            QMessageBox.information(self, "Busy", "Analysis already running.")
            return

        provider = self.manager_provider_box.currentText()
        model = self.manager_model_box.currentText()

        messages = self.manager_agent.build_messages(idea)

        self.manager_spec_display.setPlainText("Analyzing...")
        self.manager_analyze_btn.setEnabled(False)
        self.manager_approve_btn.setEnabled(False)
        self.manager_reject_btn.setEnabled(False)
        self.pending_spec = None

        if not self.authorize_request("manager", provider, model, idea):
            return
        self.manager_worker = ChatWorker(self.run_backend, provider, model, messages, idea)
        self.manager_worker.finished_signal.connect(self._manager_on_finished)
        self.manager_worker.usage_signal.connect(lambda u: self.note_request_usage("manager", u))
        self.manager_worker.error_signal.connect(self._manager_on_error)
        self.manager_worker.start()

    def _manager_on_finished(self, response: str):
        self.record_request("manager", response)
        self.manager_analyze_btn.setEnabled(True)
        spec = self.manager_agent.parse_spec(response)
        if spec is None:
            self.manager_spec_display.setPlainText(
                "[Error] Could not parse a valid JSON spec from the response.\n\n"
                "Raw response:\n" + response
            )
            return

        import json as _json
        self.pending_spec = spec
        self.manager_spec_display.setPlainText(_json.dumps(spec, indent=2))
        self.manager_approve_btn.setEnabled(True)
        self.manager_reject_btn.setEnabled(True)
        self.manager_log.append("[Ready] Spec generated. Review and approve or reject.")

    def _manager_on_error(self, error: str):
        self.abandon_request("manager")
        self.manager_analyze_btn.setEnabled(True)
        self.manager_spec_display.setPlainText(f"[Error]\n{error}")
        self.manager_log.append(f"[Error] {error}")

    def manager_approve_spec(self):
        if not self.pending_spec:
            return

        name = self.pending_spec.get("name", "unknown")
        label = self.pending_spec.get("label", name)

        confirm = QMessageBox.question(
            self,
            "Confirm Agent Creation",
            f"Create agent '{label}' ({name})?\n\n"
            f"This will:\n"
            f"  • Write agents/{name}_agent.py\n"
            f"  • Add entry to config/registry.json\n"
            f"  • Add system prompt to config/tool_prompts.json\n\n"
            f"The app must be restarted to use the new agent.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if confirm != QMessageBox.Yes:
            return

        report = self.agent_factory.create_agent(self.pending_spec)

        if report["success"]:
            self.manager_log.append(f"\n[Created] Agent '{name}' created successfully.")
            for f in report["files_created"]:
                self.manager_log.append(f"  ✓ {f}")
            self.manager_log.append("\n[Info] Restart the app to activate the new agent.")
            self.manager_approve_btn.setEnabled(False)
            self.manager_reject_btn.setEnabled(False)
            self.pending_spec = None
            QMessageBox.information(
                self,
                "Agent Created",
                f"Agent '{label}' created successfully.\n\n"
                f"Restart the app to activate it.",
            )
        else:
            errors = "\n".join(report["errors"])
            self.manager_log.append(f"\n[Failed] Could not create agent:\n{errors}")
            QMessageBox.warning(self, "Creation Failed", errors)

    def manager_reject_spec(self):
        self.pending_spec = None
        self.manager_spec_display.setPlainText("")
        self.manager_approve_btn.setEnabled(False)
        self.manager_reject_btn.setEnabled(False)
        self.manager_log.append("[Rejected] Spec cleared. You can describe a new idea.")

    def manager_clear(self):
        self.manager_idea_input.clear()
        self.manager_spec_display.clear()
        self.pending_spec = None
        self.manager_approve_btn.setEnabled(False)
        self.manager_reject_btn.setEnabled(False)
        self.manager_log.append("[Cleared]")

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
            "chat": "CHAT", "osint": "TRACE", "osint_heavy": "BLOODHOUND",
            "wifi": "BEACON", "bug_bounty": "BUG SPRAY",
            "fiverr": "ATELIER",
            "author": "MANUSCRIPT", "manuscript": "PUBLISHER",
            "music": "MAESTRO", "webdesign": "SITE BUILDER", "audiobook": "NARRATOR",
            "manager": "FORGE", }
        agent_subtitles = {
            "chat":        "General-purpose conversation. Pick a tool, pick a model, talk.",
            "osint":       "Light open-source intelligence — structured research queries and summaries.",
            "osint_heavy": "Deep OSINT investigation with five-section dossier and curated tradecraft tools.",
            "wifi":        "Wireless reconnaissance, signal analysis, and Kali command generation.",
            "bug_bounty":  "Vulnerability triage with CWE classification and HackerOne-ready submission drafts.",
            "fiverr":      "Logo gigs end-to-end — DALL·E logo prompts, gig descriptions, and client delivery messages.",
            "author":      "Long-form fiction drafting — outlines, characters, scenes, dialogue, and world-building.",
            "manuscript":  "Sales metrics, platform distribution status, and publishing todo tracker.",
            "music":       "Spotify artist setup, release planning, distribution strategy, and income roadmap.",
            "webdesign":   "Modern HTML, CSS, and JavaScript generation with responsive layout and design advice.",
            "audiobook":   "Convert ebooks (PDF / EPUB / TXT / MOBI) into MP3 audiobooks via OpenAI TTS.",
            "manager":      "Describe a new agent in plain language — Forge writes the code and registers it.",
            }
        if hasattr(self, "agent_title_label"):
            self.agent_title_label.setText(agent_titles.get(agent_name, agent_name.upper()))
        if hasattr(self, "agent_subtitle_label"):
            self.agent_subtitle_label.setText(agent_subtitles.get(agent_name, ""))
        if hasattr(self, "agent_status_pill"):
            self.agent_status_pill.setText("●  READY")
            self.agent_status_pill.setStyleSheet("")

        is_audiobook = agent_name == "audiobook"
        is_manager = agent_name == "manager"
        is_author = agent_name == "author"
        is_manuscript = agent_name == "manuscript"
        is_music = agent_name == "music"
        is_osint = agent_name == "osint"
        is_osint_heavy = agent_name == "osint_heavy"
        is_wifi = agent_name == "wifi"
        is_fiverr = agent_name == "fiverr"
        is_webdesign = agent_name == "webdesign"
        is_bug_bounty = agent_name == "bug_bounty"
        is_custom = (is_audiobook or is_manager or is_author or is_manuscript
                     or is_music or is_osint or is_osint_heavy or is_wifi or is_fiverr
                     or is_webdesign or is_bug_bounty)

        self.normal_panel.setVisible(not is_custom)
        self.audiobook_panel.setVisible(is_audiobook)
        self.manager_panel.setVisible(is_manager)
        self.author_panel.setVisible(is_author)
        self.manuscript_panel.setVisible(is_manuscript)
        self.music_panel.setVisible(is_music)
        self.osint_panel.setVisible(is_osint)
        self.osint_heavy_panel.setVisible(is_osint_heavy)
        self.wifi_panel.setVisible(is_wifi)
        self.fiverr_panel.setVisible(is_fiverr)
        self.webdesign_panel.setVisible(is_webdesign)
        self.bug_bounty_panel.setVisible(is_bug_bounty)
        # Output area only relevant for standard (non-custom) agents like Chat.
        # Within those, auto-hide if there is no content yet — keeps the UI clean.
        standard_agent_with_output = not is_custom
        has_output_content = bool(self.output_box.toPlainText().strip())
        show_output = standard_agent_with_output and has_output_content
        self.output_label.setVisible(show_output)
        self.output_box.setVisible(show_output)

        if is_audiobook:
            self.output_label.setText("Output Log")
            self.output_box.setPlainText("[Ready] Click Start to begin.")
            self.refresh_audiobook_books()
        elif is_manager:
            self.output_label.setText("Forge Output")
            self.output_box.setPlainText("[Forge] Describe an idea above and click Analyze.")
        elif is_manuscript:
            from services.kdp_csv_parser import manuscript_seed_todos
            manuscript_seed_todos()
            self._load_manuscript_todos()
            self._refresh_next_step_tip()
        elif is_author:
            self._refresh_next_step_tip()
        elif is_music or is_osint or is_osint_heavy or is_wifi or is_fiverr or is_webdesign or is_bug_bounty:
            pass
        else:
            self.output_label.setText("Output")

    def get_audiobook_defaults(self):
        tool = self.tool_runner.tools["audiobook"]
        return {
            "input": tool["default_input"],
            "output": tool["default_output"],
            "voice": tool.get("default_voice", "alloy"),
            "chunk_tokens": tool.get("default_chunk_tokens", 1400),
        }

    def refresh_audiobook_books(self):
        defaults = self.get_audiobook_defaults()
        input_folder = Path(defaults["input"]).expanduser()
        output_folder = Path(defaults["output"]).expanduser()

        self.audiobook_input_path.setText(str(input_folder))
        self.audiobook_output_path.setText(str(output_folder))
        self.audiobook_voice_box.setCurrentText(defaults["voice"])
        self.audiobook_chunk_input.setText(str(defaults["chunk_tokens"]))
        self.audiobook_book_list.clear()
        self.tool_progress.setValue(0)

        if not input_folder.exists():
            self.output_box.setPlainText(f"[Error] Input folder does not exist:\n{input_folder}")
            self.show_empty_audiobook_folder_popup(input_folder)
            return

        books = sorted(f for f in input_folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EBOOKS)

        if not books:
            self.output_box.setPlainText(f"[Info] No supported ebooks found in:\n{input_folder}")
            self.show_empty_audiobook_folder_popup(input_folder)
            return

        for book in books:
            item = QListWidgetItem(f"📖 {book.name}")
            item.setData(Qt.UserRole, str(book))
            self.audiobook_book_list.addItem(item)

        if len(books) == 1:
            self.audiobook_book_list.setCurrentRow(0)

        self.output_box.setPlainText(f"[Ready] Found {len(books)} book(s). Select one and click Start.")
        self.audiobook_status_label.setText(f"[Ready] Found {len(books)} book(s).")
        self.estimate_audiobook_cost_from_selection()

    def show_empty_audiobook_folder_popup(self, folder_path: Path):
        msg = QMessageBox(self)
        msg.setWindowTitle("Audiobook Folder Empty")
        msg.setText(f"No supported ebooks found in:\n{folder_path}")
        open_btn = msg.addButton("Open Folder", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Ok)
        msg.exec()

        if msg.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))

    def open_audiobook_input_folder(self):
        folder = self.audiobook_input_path.text().strip()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def change_audiobook_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Audiobook Output Folder")
        if folder:
            self.audiobook_output_path.setText(folder)

    def estimate_audiobook_cost_from_selection(self):
        item = self.audiobook_book_list.currentItem()
        if not item:
            self.audiobook_cost_label.setText("Estimated cost: select a book first")
            return

        path = Path(item.data(Qt.UserRole))
        try:
            mb = max(0.1, path.stat().st_size / (1024 * 1024))
            rough = min(25.0, max(0.50, mb * 0.80))
            self.audiobook_cost_label.setText(f"Estimated cost: rough €{rough:.2f}–€{rough * 1.8:.2f} (file-size estimate)")
        except Exception:
            self.audiobook_cost_label.setText("Estimated cost: unavailable")

    def start_selected_audiobook_book(self):
        item = self.audiobook_book_list.currentItem()
        if not item:
            self.output_box.setPlainText("[Error] Please select a book first.")
            return

        book_path = item.data(Qt.UserRole)
        output_path = self.audiobook_output_path.text().strip()
        voice = self.audiobook_voice_box.currentText().strip()

        # Preflight: narrator needs an OpenAI key for TTS. Catch the most common
        # failure (missing key) before launching, so the user gets a clear message
        # instead of a process that silently exits.
        if not OpenAIClientWrapper.key_available():
            self.audiobook_status_label.setText("[Error] OPENAI_API_KEY not set.")
            QMessageBox.critical(
                self,
                "OpenAI API Key Required",
                "Audiobook conversion uses OpenAI's text-to-speech API, but "
                "OPENAI_API_KEY is not set.\n\n"
                "Add your key to the .env file in the project root:\n"
                "    OPENAI_API_KEY=sk-...\n\n"
                "then restart Sentinel and try again. "
                "Get a key at platform.openai.com/api-keys.",
            )
            return

        try:
            chunk_tokens = int(self.audiobook_chunk_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Value", "Chunk tokens must be a number.")
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Audiobook Conversion")
        msg.setText(
            f"Start audiobook conversion?\n\n"
            f"Book: {Path(book_path).name}\n"
            f"Voice: {voice}\n"
            f"Chunk tokens: {chunk_tokens}\n\n"
            f"This uses OpenAI TTS API and may cost real money."
        )
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if msg.exec() != QMessageBox.Yes:
            return

        config = {"input": book_path, "output": output_path, "voice": voice, "chunk_tokens": chunk_tokens}

        self.output_box.setPlainText(
            f"[Starting]\nBook: {Path(book_path).name}\nOutput: {output_path}\nVoice: {voice}\nChunk tokens: {chunk_tokens}\n\n"
        )
        self.audiobook_status_label.setText(f"[Running] {Path(book_path).name}")
        self.run_audiobook_live(config)

    def run_audiobook_live(self, config):
        self.tool_progress.setValue(0)
        self.stop_btn.setEnabled(True)
        self.audiobook_start_btn.setEnabled(False)
        self.audiobook_refresh_btn.setEnabled(False)

        tool = self.tool_runner.tools["audiobook"]
        project_root = str(Path(__file__).resolve().parent)
        self.audiobook_process = QProcess(self)
        self.audiobook_process.setProcessChannelMode(QProcess.MergedChannels)
        # Run from the project root so "-m services.narrator.converter" resolves,
        # using Sentinel's own interpreter (no separate venv -> PyInstaller-friendly).
        self.audiobook_process.setWorkingDirectory(project_root)

        program = sys.executable
        conv_args = [
            "--input", config["input"],
            "--output", config["output"],
            "--voice", config["voice"],
            "--chunk-tokens", str(config["chunk_tokens"]),
        ]
        if is_frozen():
            # Packaged app: re-invoke our own executable with the worker sentinel
            # (PyInstaller apps have no `python -m`).
            arguments = ["--narrator-worker"] + conv_args
        else:
            arguments = ["-u", "-m", tool.get("module", "services.narrator.converter")] + conv_args

        self.audiobook_process.readyReadStandardOutput.connect(self.handle_audiobook_stdout)
        self.audiobook_process.finished.connect(self.handle_audiobook_finished)
        self.audiobook_process.errorOccurred.connect(self.handle_audiobook_error)
        self.audiobook_process.start(program, arguments)

    def handle_audiobook_error(self, error):
        """Fired when the process fails to start/crashes at the QProcess level
        (e.g. interpreter not found) — distinct from a non-zero exit code."""
        # FailedToStart still emits finished() on some platforms; on others it
        # does not, so report here to guarantee the user sees something.
        reason = {
            QProcess.FailedToStart: "The converter process failed to start "
                                    "(interpreter or module not found).",
            QProcess.Crashed: "The converter process crashed.",
            QProcess.Timedout: "The converter process timed out.",
        }.get(error, "The converter process encountered an unknown error.")

        self.stop_btn.setEnabled(False)
        self.audiobook_start_btn.setEnabled(True)
        self.audiobook_refresh_btn.setEnabled(True)
        self.tool_progress.setValue(0)
        self.audiobook_status_label.setText("[Error] Converter could not run.")
        self.output_box.append(f"\n[Error] {reason}")
        QMessageBox.critical(self, "Audiobook Conversion Failed", reason)

    def handle_audiobook_stdout(self):
        data = self.audiobook_process.readAll().data().decode("utf-8", errors="replace")
        if not data:
            return

        self.output_box.moveCursor(QTextCursor.End)
        self.output_box.insertPlainText(data)
        self.output_box.ensureCursorVisible()

        matches = re.findall(r"(\d+(?:\.\d+)?)%\s+\((\d+)/(\d+)\)", data)
        if matches:
            percent = float(matches[-1][0])
            done = matches[-1][1]
            total = matches[-1][2]
            self.tool_progress.setValue(int(percent))
            self.audiobook_status_label.setText(f"[Running] {percent:.1f}% ({done}/{total})")

    def handle_audiobook_finished(self):
        self.stop_btn.setEnabled(False)
        self.audiobook_start_btn.setEnabled(True)
        self.audiobook_refresh_btn.setEnabled(True)

        exit_code = self.audiobook_process.exitCode() if self.audiobook_process else 0
        exit_status = self.audiobook_process.exitStatus() if self.audiobook_process else QProcess.NormalExit
        output_text = self.output_box.toPlainText()
        crashed = exit_status == QProcess.CrashExit

        success = "ALL BOOKS COMPLETED" in output_text or "🎉" in output_text
        quota_hit = any(k in output_text for k in (
            "insufficient_quota", "exceeded your current quota", "Billing hard limit"))
        paused = "Conversion paused" in output_text or "⏸️" in output_text

        if quota_hit:
            self.tool_progress.setValue(0)
            self.audiobook_status_label.setText("[Blocked] OpenAI quota exceeded — top up your account.")
            self.output_box.append(
                "\n[Blocked] Your OpenAI account has run out of quota.\n"
                "Top up your account at platform.openai.com/settings/billing,\n"
                "then click Start on the same book to resume automatically."
            )
            QMessageBox.warning(
                self, "OpenAI Quota Exceeded",
                "Your OpenAI account has run out of quota. Top up at "
                "platform.openai.com/settings/billing, then click Start to resume.",
            )

        elif paused and exit_code != 0:
            self.tool_progress.setValue(0)
            self.audiobook_status_label.setText("[Paused] Incomplete — click Start to resume.")
            self.output_box.append(
                "\n[Paused] Some chunks were not completed.\n"
                "Click Start on the same book to resume automatically."
            )

        elif crashed or exit_code != 0:
            reason = self._extract_audiobook_error(output_text)
            self.tool_progress.setValue(0)
            self.audiobook_status_label.setText("[Error] Conversion failed.")
            self.output_box.append(
                f"\n[Error] Conversion failed (exit code {exit_code}).\n{reason}"
            )
            QMessageBox.critical(
                self, "Audiobook Conversion Failed",
                f"The conversion did not complete.\n\n{reason}",
            )

        elif success:
            self.tool_progress.setValue(100)
            self.audiobook_status_label.setText("[Done] Audiobook created successfully.")
            self.output_box.append("\n[Done] Audiobook created successfully.")

        else:
            # Exit 0 but no success marker — don't fake success.
            reason = self._extract_audiobook_error(output_text)
            self.tool_progress.setValue(0)
            self.audiobook_status_label.setText("[Warning] Ended without confirming success.")
            self.output_box.append(
                "\n[Warning] The converter exited without reporting completion. "
                f"Nothing may have been produced.\n{reason}"
            )
            QMessageBox.warning(
                self, "Audiobook Conversion Incomplete",
                "The converter exited without confirming the audiobook was "
                f"created.\n\n{reason}",
            )

        self.refresh_audiobook_books()

    @staticmethod
    def _extract_audiobook_error(output_text: str) -> str:
        """Pull the most informative error line out of the converter's output so
        the user sees *why* it failed, not just that it did."""
        lines = [ln.strip() for ln in output_text.splitlines() if ln.strip()]
        # Prefer lines that name a concrete cause over generic failure notices.
        specific = ("not found", "not set", "Fatal error", "Traceback", "Exception",
                    "quota", "Authentication", "401", "Failed to read")
        for ln in reversed(lines):
            if any(m in ln for m in specific):
                return ln
        for ln in reversed(lines):
            if "❌" in ln or "Error" in ln:
                return ln
        return lines[-1] if lines else "No output was produced by the converter."

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

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt},
        ]

    def auto_route_agent(self):
        raw_text = self.input_box.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Warning", "Please enter text first.")
            return

        selected_agent = self.agent_box.currentText()
        selected_tool = self.tool_box.currentText() if hasattr(self, "tool_box") else "General Chat"
        backend, model = self.resolve_backend_model()
        self.route_result_label.setText(f"Router: {selected_agent} · {backend} · {model}")

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

        if selected_agent == "audiobook":
            self.start_selected_audiobook_book()
            return

        if selected_agent == "manager":
            self.manager_analyze_idea()
            return

        raw_text = self.input_box.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Warning", "Please enter text first.")
            return

        selected_tool = self.tool_box.currentText() if hasattr(self, "tool_box") else "General Chat"
        command_name, full_prompt = self.build_user_prompt(raw_text)
        final_backend, final_model = self.resolve_backend_model()

        estimated_cost, approx_tokens = self.estimate_chat_cost(final_backend, final_model, full_prompt)

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
                messages = agent.build_messages(full_prompt)
            else:
                messages = [{"role": "user", "content": full_prompt}]

            self.pending_agent = selected_agent
            self.pending_tool = selected_tool
            self.pending_backend = final_backend
            self.pending_model = final_model
            self.pending_command = command_name
            self.pending_messages = messages
            self.pending_prompt = full_prompt
            self.pending_usage = None

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
        /tmp/sentinelai_launch.log; when a widget is given, the reason is also
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

    def authorize_request(self, agent, provider, model, prompt, tool=None, label=None) -> bool:
        """Budget-check and confirm one request. False means: do not send it.

        `tool` is a registry tool name and is validated as one — pass it only
        when the request really runs a registered tool (the chat panel does).
        The agent panels pick their own mode ("Person", "Deep Scan", …), which
        is not a registry entry: pass that as `label` instead, so it still shows
        up in the run log and Saved Chats without failing the tool check.

        On success the context record_request() needs is stashed per agent, so a
        caller only has to pass the response back later.
        """
        estimated_cost, approx_tokens = self.estimate_chat_cost(provider, model, prompt)

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
        )
        if not validation.allowed:
            QMessageBox.warning(self, "Request Blocked", validation.reason)
            return False

        if not self.confirm_external_api_request(provider, model, estimated_cost, approx_tokens):
            return False

        descriptor = label or tool or "-"
        self._pending_requests[agent] = {
            "agent": agent,
            "tool": descriptor,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "usage": None,
            "run_id": self.run_logger.start(
                agent=agent,
                tool=descriptor,
                provider=provider,
                model=model,
                mode=self.execution_mode_box.currentText() if hasattr(self, "execution_mode_box") else "",
                prompt_summary=prompt,
            ),
        }
        return True

    def note_request_usage(self, agent, usage):
        """Real token counts from the worker, when it reports them."""
        context = self._pending_requests.get(agent)
        if context is not None:
            context["usage"] = usage

    def record_request(self, agent, response, messages=None):
        """Bill, save and close out a request authorised by authorize_request()."""
        context = self._pending_requests.pop(agent, None)
        if context is None:          # never authorised (or already recorded)
            return

        entry = self.usage_tracker.log_request(
            agent=context["agent"],
            backend=context["provider"],
            model=context["model"],
            prompt_text=context["prompt"],
            response_text=response,
            usage=context["usage"],
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

    def abandon_request(self, agent, reason="error"):
        """Drop a request that failed, so it is not billed and the log closes."""
        context = self._pending_requests.pop(agent, None)
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
        if self.chat_worker is not None and self.chat_worker.isRunning():
            self.stop_chat_worker()
            return

        if self.author_worker is not None and self.author_worker.isRunning():
            self.author_stop()
            return

        if self.author_pub_worker is not None and self.author_pub_worker.isRunning():
            self.author_pub_stop()
            return

        if self.author_mkt_worker is not None and self.author_mkt_worker.isRunning():
            self.author_mkt_stop()
            return

        if self.music_worker is not None and self.music_worker.isRunning():
            self.music_stop()
            return

        if self.osint_worker is not None and self.osint_worker.isRunning():
            self.osint_stop()
            return

        if self.osint_heavy_worker is not None and self.osint_heavy_worker.isRunning():
            self.osint_heavy_stop()
            return

        if self.webdesign_worker is not None and self.webdesign_worker.isRunning():
            self.webdesign_stop()
            return

        if self.wifi_worker is not None and self.wifi_worker.isRunning():
            self.wifi_stop()
            return

        if self.wifi_scan_worker is not None and self.wifi_scan_worker.isRunning():
            self.wifi_stop()
            return

        if self.fiverr_image_worker is not None and self.fiverr_image_worker.isRunning():
            self.fiverr_stop()
            return

        if self.fiverr_text_worker is not None and self.fiverr_text_worker.isRunning():
            self.fiverr_stop()
            return

        if self.bug_bounty_worker is not None and self.bug_bounty_worker.isRunning():
            self.bb_stop()
            return

        stopped = False
        if self.audiobook_process is not None:
            if self.audiobook_process.state() != QProcess.NotRunning:
                self.audiobook_process.kill()
                stopped = True

        self.stop_btn.setEnabled(False)
        self.audiobook_start_btn.setEnabled(True)
        self.audiobook_refresh_btn.setEnabled(True)

        if stopped:
            self.output_box.append("\n[Stopped] Current task stopped by user.")
            self.audiobook_status_label.setText("[Stopped]")
        else:
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

    def start_resource_timer(self):
        self.resource_timer = QTimer(self)
        self.resource_timer.timeout.connect(self.update_resource_label)
        self.resource_timer.start(1000)

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
        """Fill the Saved Chats list, honouring the search box and agent filter.

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

            for file, data in loaded:
                if wanted != ALL_AGENTS_FILTER and data.get("agent", "chat") != wanted:
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
            "fiverr": "fiverr",
            "author": "author", "music": "music",
            "webdesign": "webdesign", "audiobook": "audiobook",
            "manager": "manager", "manuscript": "manuscript",
        }
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
            "chat": "CHAT", "osint": "TRACE", "osint_heavy": "BLOODHOUND",
            "wifi": "BEACON", "bug_bounty": "BUG SPRAY",
            "fiverr": "ATELIER",
            "author": "MANUSCRIPT", "manuscript": "PUBLISHER",
            "music": "MAESTRO", "webdesign": "SITE BUILDER", "audiobook": "NARRATOR",
            "manager": "FORGE", }
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
            if self.audiobook_process is not None and self.audiobook_process.state() != QProcess.NotRunning:
                self.audiobook_process.kill()
            if self.chat_worker is not None and self.chat_worker.isRunning():
                self.chat_worker.cancel()
                self.chat_worker.terminate()
                self.chat_worker.wait(1000)
        except Exception as exc:
            self._note_failure("shutdown: stop background work", exc)
        event.accept()

SINGLE_INSTANCE_KEY = "sentinel-ai.single-instance"


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

