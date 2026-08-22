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


class OsintPanel(AgentPanel):
    """Structure a target into search queries, dorks and public sources."""

    agent_key = "osint"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("OSINTPanel")
        self._last_response = ""
        self._build()
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

        setup_layout.addWidget(provider_row_container, 2, 0, 1, 4)
        layout.addWidget(setup_group)

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
        self.status_label.setText("Structuring query…")
        self.analyse_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

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
        self.status_label.setText("Done.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_error(self, error: str) -> None:
        self.abandon()
        separator = "─" * 50
        self.stream_box.setVisible(True)
        self.sections.setVisible(False)
        self.stream_box.setPlainText(
            f"⚠  ERROR\n{separator}\n{error}\n{separator}"
        )
        self.status_label.setText("Error.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def stop(self) -> None:
        self.stop_worker()
        self.status_label.setText("Stopped.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Output ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        self._clear_output()
        self.target_input.clear()
        self.status_label.setText("Idle")
        self._last_response = ""

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
