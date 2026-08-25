"""Tunnel — self-hosted VPN design, kill switch, and a deploy runbook.

Fifth vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

The panel has two halves that must not be confused: **Ask Advisor** is a paid
request and goes through the guard; **Build Config** renders WireGuard files
from the form with `build_configs` and never touches a provider.
"""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout,
)

from agents.vpn_agent import build_configs
from ui.panels.base import AgentPanel
from ui.widgets import MenuComboBox


class VpnPanel(AgentPanel):
    """Advise on, and generate, a self-hosted VPN."""

    agent_key = "vpn"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("VPNPanel")
        self._last_response = ""
        self._build()
        self.polish_workspace()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Deployment setup ─────────────────────────────────────────────
        setup_group = QGroupBox("Deployment")
        setup_group.setObjectName("VPNSetupGroup")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_box = MenuComboBox()
        self.mode_box.addItems(["Remote (VPS)", "Native (home LAN)"])
        self.mode_box.setToolTip(
            "Remote: traffic exits at a rented VPS — hides your IP, changes your "
            "apparent country.\nNative: runs on hardware you own — an encrypted way "
            "INTO your LAN, exit IP stays your home ISP."
        )
        setup_layout.addWidget(self.mode_box, 0, 1)

        setup_layout.addWidget(QLabel("Protocol:"), 0, 2)
        self.protocol_box = MenuComboBox()
        self.protocol_box.addItems(["WireGuard", "OpenVPN 443 fallback", "Both"])
        setup_layout.addWidget(self.protocol_box, 0, 3)

        setup_layout.addWidget(QLabel("Server host:"), 1, 0)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("VPS IP or DDNS hostname (Config Builder)")
        setup_layout.addWidget(self.host_input, 1, 1)

        setup_layout.addWidget(QLabel("SSH user:"), 1, 2)
        self.ssh_input = QLineEdit()
        self.ssh_input.setPlaceholderText("e.g. root")
        setup_layout.addWidget(self.ssh_input, 1, 3)

        setup_layout.addWidget(QLabel("LAN subnet:"), 2, 0)
        self.lan_input = QLineEdit()
        self.lan_input.setPlaceholderText("Native mode, e.g. 192.168.1.0/24")
        setup_layout.addWidget(self.lan_input, 2, 1)

        setup_layout.addWidget(QLabel("Egress iface:"), 2, 2)
        self.egress_input = QLineEdit()
        self.egress_input.setPlaceholderText("server NIC, e.g. eth0")
        setup_layout.addWidget(self.egress_input, 2, 3)

        layout.addWidget(setup_group)

        # Configuration generation is deterministic and offline; keep it apart
        # from the model-backed troubleshooting advisor below.
        builder_row = QHBoxLayout()
        self.builder_note = QLabel("Offline configuration — no model required")
        self.builder_note.setStyleSheet("color: #7f8d87; font-size: 12px;")
        builder_row.addWidget(self.builder_note)
        builder_row.addStretch()
        self.build_btn = QPushButton("Build Config")
        self.build_btn.setMinimumWidth(110)
        self.build_btn.setToolTip(
            "Render WireGuard configs and a deploy runbook locally — no LLM."
        )
        self.build_btn.clicked.connect(self.build_config)
        builder_row.addWidget(self.build_btn)
        layout.addLayout(builder_row)

        # ── Advisor question ─────────────────────────────────────────────
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText(
            "Ask the advisor — e.g. \"WireGuard won't connect on hotel wifi, what now?\""
        )
        self.question_input.returnPressed.connect(self.run)
        layout.addWidget(self.question_input)

        self.run_btn = QPushButton("Ask Advisor")
        self.run_btn.setMinimumWidth(120)
        self.run_btn.setObjectName("PrimaryAction")
        self.run_btn.clicked.connect(self.run)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        self.stop_btn.clicked.connect(self.stop)
        self.set_busy(self.run_btn, self.stop_btn, False)

        # ── Provider / action row ────────────────────────────────────────
        provider_row_container = self.build_run_bar(
            self.run_btn,
            stop=self.stop_btn,
            context="Advisor",
        )

        layout.addWidget(provider_row_container)

        # ── Results tabs ─────────────────────────────────────────────────
        self.tabs = QTabWidget()

        self.advisor_box = QTextBrowser()
        self.advisor_box.setOpenExternalLinks(False)
        self.tabs.addTab(self.advisor_box, "Advisor")

        self.config_box = QTextBrowser()
        self.config_box.setOpenExternalLinks(False)
        self.tabs.addTab(self.config_box, "Config && Commands")

        self.advisor_box.setPlaceholderText(
            "Troubleshooting advice will appear after you select Ask Advisor."
        )
        self.config_box.setPlaceholderText(
            "Generated VPN configuration and commands will appear after Build Config."
        )

        layout.addWidget(self.tabs, 1)

        # ── Bottom bar ───────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        bottom_row.addWidget(self.clear_btn)
        layout.addLayout(bottom_row)

    # ── The advisor (paid) ──────────────────────────────────────────────
    def context_prefix(self) -> str:
        """The deployment setup, phrased as context the advisor reasons from."""
        parts = [
            f"Deployment mode: {self.mode_box.currentText()}",
            f"Protocol focus: {self.protocol_box.currentText()}",
        ]
        if self.host_input.text().strip():
            parts.append(f"Server host: {self.host_input.text().strip()}")
        if self.lan_input.text().strip():
            parts.append(f"LAN subnet: {self.lan_input.text().strip()}")
        return "Context — " + "; ".join(parts) + ".\n\n"

    def run(self) -> None:
        question = self.question_input.text().strip()

        if not question:
            QMessageBox.warning(self, "Missing Input", "Enter a question for the advisor.")
            return
        if not self.model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        prompt = self.context_prefix() + question
        messages = self.agent().build_messages(prompt)

        if not self.authorize(prompt, label=self.mode_box.currentText()):
            return

        self._last_response = ""
        self.advisor_box.clear()
        self.tabs.setCurrentWidget(self.advisor_box)
        self.status_label.setText("Consulting advisor…")
        self.set_busy(self.run_btn, self.stop_btn, True)

        self.start_worker(
            messages, prompt,
            on_token=self._on_token,
            on_finished=self._on_finished,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        self._last_response += token
        self.advisor_box.setPlainText(self._last_response)
        self.advisor_box.moveCursor(QTextCursor.End)

    def _on_finished(self, full_response: str) -> None:
        self._last_response = full_response
        self.record(full_response)
        self.advisor_box.setPlainText(full_response)
        self.status_label.setText("Done.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    def _on_error(self, error: str) -> None:
        self.abandon()
        separator = "─" * 50
        self.advisor_box.setPlainText(f"⚠  ERROR\n{separator}\n{error}\n{separator}")
        self.status_label.setText("Error.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    def stop(self) -> None:
        self.stop_worker()
        self.status_label.setText("Stopped.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    # ── The config builder (offline) ────────────────────────────────────
    def build_config(self) -> None:
        """Render WireGuard configs + a deploy runbook. Deterministic, offline."""
        text = build_configs(
            mode=self.mode_box.currentText(),
            protocol=self.protocol_box.currentText(),
            server_host=self.host_input.text().strip(),
            ssh_user=self.ssh_input.text().strip(),
            lan_subnet=self.lan_input.text().strip(),
            egress_iface=self.egress_input.text().strip() or "eth0",
        )
        self.config_box.setPlainText(text)
        self.tabs.setCurrentWidget(self.config_box)
        self.status_label.setText("Config rendered.")

    def clear(self) -> None:
        self.advisor_box.clear()
        self.config_box.clear()
        self.question_input.clear()
        self.status_label.setText("Idle")
        self._last_response = ""
