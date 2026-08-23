"""Trace — the light OSINT panel.

First vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`). The
bodies are the ones that ran in `GodAI`; what changed is where the widgets live
and how the panel reaches the application:

- widgets are the panel's own attributes, so the `osint_` prefix that kept them
  apart in a shared namespace is gone;
- the request guard, the worker and the model list go through `AgentPanel`,
  which is the whole reason the base exists.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextBrowser, QVBoxLayout,
)

from ui.widgets import SectionView
from ui.panels.base import AgentPanel
from services.deepseek_client import is_insufficient_balance_error


class OsintPanel(AgentPanel):
    """Structure a target into search queries, dorks and public sources."""

    agent_key = "osint"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("OSINTPanel")
        self._last_response = ""
        self._activity_entries: list[str] = []
        self._received_first_token = False
        self._build()
        self.polish_workspace()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Target form ──────────────────────────────────────────────────
        setup_group = QGroupBox("Target")
        setup_group.setObjectName("OSINTSetupBox")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Target:"), 0, 0)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText(
            "Enter name, username, email, domain, company, phone, or IP…"
        )
        setup_layout.addWidget(self.target_input, 0, 1, 1, 3)

        setup_layout.addWidget(QLabel("Query Type:"), 1, 0)
        self.type_box = QComboBox()
        self.type_box.addItems([
            "Auto-detect", "Person", "Username", "Email",
            "Domain", "Company", "Phone", "IP Address",
        ])
        setup_layout.addWidget(self.type_box, 1, 1)

        provider_row_container, provider_row = self.flow_row()
        self.build_provider_row(provider_row)

        self.analyse_btn = QPushButton("Structure Query")
        self.analyse_btn.setMinimumWidth(150)
        self.analyse_btn.setObjectName("PrimaryAction")
        self.analyse_btn.clicked.connect(self.analyse)
        provider_row.addWidget(self.analyse_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        self.stop_btn.clicked.connect(self.stop)
        provider_row.addWidget(self.stop_btn)
        self.set_busy(self.analyse_btn, self.stop_btn, False)

        setup_layout.addWidget(provider_row_container, 2, 0, 1, 4)
        layout.addWidget(setup_group)

        # ── Persistent activity trail ───────────────────────────────────
        activity_group = QGroupBox("Activity")
        activity_group.setObjectName("OSINTActivityBox")
        activity_layout = QVBoxLayout(activity_group)
        self.activity_box = QTextBrowser()
        self.activity_box.setObjectName("OSINTActivityLog")
        self.activity_box.setOpenExternalLinks(False)
        self.activity_box.setMinimumHeight(116)
        self.activity_box.setMaximumHeight(180)
        activity_layout.addWidget(self.activity_box)
        layout.addWidget(activity_group)
        self._reset_activity()

        # ── Output ───────────────────────────────────────────────────────
        # The answer is already parsed into four sections; render it as those
        # sections rather than pouring each into its own tabbed text box. Copy
        # lives per card, so the dorks are still one click from the clipboard.
        self.stream_box = QTextBrowser()
        self.stream_box.setOpenExternalLinks(False)
        self.stream_box.setVisible(False)
        layout.addWidget(self.stream_box, 1)

        self.sections = SectionView()
        layout.addWidget(self.sections, 1)

        # ── Bottom bar ───────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        self.status_label = QLabel("Idle")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        bottom_row.addWidget(clear_btn)
        layout.addLayout(bottom_row)

    # ── Running ─────────────────────────────────────────────────────────
    def analyse(self) -> None:
        target = self.target_input.text().strip()
        query_type = self.type_box.currentText()

        if not target:
            QMessageBox.warning(self, "Missing Input", "Please enter a target.")
            return
        if not self.model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        messages = self.agent().build_messages(target, query_type)

        if not self.authorize(target, label=query_type):
            return

        self._clear_output()
        self._last_response = ""
        self._received_first_token = False
        self._reset_activity()
        self._append_activity(f"Target accepted: {target} ({query_type}).")
        if self.provider == "ollama":
            self._append_activity(
                f"Running locally with Ollama · {self.model}; the target stays on this Mac."
            )
        else:
            self._append_activity(
                f"Using {self.provider} · {self.model} after the provider permission check."
            )
        self._append_activity(
            "Scope confirmed: planning queries only. No websites or public databases "
            "are contacted by Trace in this mode."
        )
        self._append_activity(
            "Building target components, search variations, Google dorks, and a "
            "recommended public-source checklist…"
        )
        notice = getattr(self, "_route_notice", "")
        self.status_label.setText(
            f"{notice} Structuring query…" if notice else "Structuring query…"
        )
        self._route_notice = ""
        self.set_busy(self.analyse_btn, self.stop_btn, True)

        self.start_worker(
            messages, target,
            on_token=self._on_token,
            on_finished=self._on_finished,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        # While tokens arrive there are no sections to show yet, so the raw
        # stream is the view; the cards replace it once the answer is whole.
        self._last_response += token
        if not self._received_first_token:
            self._received_first_token = True
            self._append_activity("Model response received; assembling the four result sections…")
        self.sections.setVisible(False)
        self.stream_box.setVisible(True)
        self.stream_box.setPlainText(self._last_response)
        self.stream_box.moveCursor(QTextCursor.End)

    def _on_finished(self, full_response: str) -> None:
        self._last_response = full_response
        self.record(full_response)
        self.stream_box.setVisible(False)
        self.sections.setVisible(True)
        self._populate_sections(full_response)
        self._append_activity(
            "Completed. External sources queried: none. The displayed sources are "
            "recommendations for the user to check, not verified findings."
        )
        self.status_label.setText("Done.")
        self.set_busy(self.analyse_btn, self.stop_btn, False)

    def _on_error(self, error: str) -> None:
        self.abandon()
        balance_error = is_insufficient_balance_error(error)
        if balance_error:
            error = self._prepare_balance_recovery()
        self._append_activity(f"Run ended before completion: {error}")
        separator = "─" * 50
        self.stream_box.setVisible(True)
        self.sections.setVisible(False)
        self.stream_box.setPlainText(
            f"⚠  ERROR\n{separator}\n{error}\n{separator}"
        )
        if balance_error:
            self.status_label.setText(
                "Ready to retry locally."
                if self.provider == "ollama" else "Action needed."
            )
        else:
            self.status_label.setText("Error.")
        self.set_busy(self.analyse_btn, self.stop_btn, False)

    def _prepare_balance_recovery(self) -> str:
        """Select, but never automatically run, a local retry after a 402."""
        previous_provider = self.provider
        self.provider_box.setCurrentText("ollama")
        local_model = self.model
        unavailable = not local_model or local_model.startswith("(")
        if unavailable:
            self.provider_box.setCurrentText(previous_provider)
            return (
                "The DeepSeek cloud account has no API credit, so this request "
                "could not finish. "
                "No local model is currently available. Add DeepSeek credit or "
                "choose another provider. Trace will ask before sending the target "
                "to a different cloud service."
            )
        self._prefer_local_retry_once = True
        return (
            "The DeepSeek cloud account has no API credit, so this request could "
            "not finish. Local DeepSeek through Ollama is free. "
            f"Trace selected the local model {local_model} for a safe retry, but "
            "did not resend the target. Click Structure Query to retry on this Mac. "
            "To use another cloud provider, choose it yourself; Trace will ask "
            "before sending the target."
        )

    def stop(self) -> None:
        self.stop_worker()
        self._append_activity("Stopped by the user. No further processing was performed.")
        self.status_label.setText("Stopped.")
        self.set_busy(self.analyse_btn, self.stop_btn, False)

    # ── Output ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        self._clear_output()
        self.target_input.clear()
        self._reset_activity()
        self.status_label.setText("Idle")
        self._last_response = ""

    def _reset_activity(self) -> None:
        self._activity_entries = [
            "Ready. Trace will show each processing stage here and will explicitly "
            "state whether any external source was queried."
        ]
        self._render_activity()

    def _append_activity(self, message: str) -> None:
        self._activity_entries.append(message)
        self._render_activity()

    def _render_activity(self) -> None:
        if not hasattr(self, "activity_box"):
            return
        lines = [
            f"{'✓' if index < len(self._activity_entries) - 1 else '•'} {message}"
            for index, message in enumerate(self._activity_entries)
        ]
        self.activity_box.setPlainText("\n".join(lines))
        self.activity_box.moveCursor(QTextCursor.End)

    def _clear_output(self) -> None:
        self.sections.clear()
        self.stream_box.clear()
        self.stream_box.setVisible(False)
        self.sections.setVisible(True)

    def _populate_sections(self, text: str) -> None:
        sections = self.parse_sections(text)
        self.sections.show_sections(
            [
                ("Query structure", sections.get("structure", "")),
                ("Google dorks", sections.get("dorks", ""), True),
                ("Public sources", sections.get("sources", "")),
                ("Summary and next steps", sections.get("summary", "")),
            ],
            raw=text,
        )

    @staticmethod
    def parse_sections(text: str) -> dict:
        """Split the answer on its four `## HEADING`s. Missing ones come back empty."""
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
