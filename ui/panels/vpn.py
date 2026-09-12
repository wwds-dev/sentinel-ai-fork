"""Tunnel — self-hosted VPN design, kill switch, and a deploy runbook.

Fifth vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

The panel keeps four paths visibly separate: **Connection Check** is read-only,
**Action Preview** cannot execute, **Ask Advisor** is a paid request that goes
through the guard, and **Build Config** renders WireGuard files locally.
"""

from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QTextBrowser,
    QVBoxLayout,
)

from agents.vpn_agent.sentinel_chat_agent import build_configs
from services.vpn_diagnostics import (
    VpnDiagnosticsReport,
    build_vpn_action_preview,
    inspect_wireguard_config,
    load_vpn_profile_catalog,
)
from ui.panels.base import AgentPanel
from ui.widgets import MenuComboBox, SectionView
from ui.workers import VpnDiagnosticsWorker


class VpnPanel(AgentPanel):
    """Advise on, and generate, a self-hosted VPN."""

    agent_key = "vpn"
    diagnostics_worker_class = VpnDiagnosticsWorker

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("VPNPanel")
        self._last_response = ""
        self._last_diagnostics_report = None
        self._diagnostics_worker = None
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

        # ── Read-only connection check ─────────────────────────────────
        diagnostics_group = QGroupBox("Connection Check")
        diagnostics_group.setObjectName("VPNDiagnosticsGroup")
        diagnostics_layout = QVBoxLayout(diagnostics_group)

        diagnostics_note = QLabel(
            "Inspect installed VPN tools, active tunnels, the default route, and "
            "configured DNS. This check never connects, disconnects, or changes settings."
        )
        diagnostics_note.setWordWrap(True)
        diagnostics_layout.addWidget(diagnostics_note)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Compare profile:"))
        self.profile_box = MenuComboBox()
        self.profile_box.setMinimumWidth(180)
        self.profile_box.setToolTip(
            "Compare the local connection snapshot with a VPN Agent profile. "
            "Choosing a profile here does not activate or modify it."
        )
        profile_row.addWidget(self.profile_box, 1)
        self.profile_refresh_btn = QPushButton("Reload")
        self.profile_refresh_btn.setToolTip("Reload the VPN Agent profile list from disk.")
        self.profile_refresh_btn.clicked.connect(self.reload_profiles)
        profile_row.addWidget(self.profile_refresh_btn)
        self.inspect_config_btn = QPushButton("Inspect config…")
        self.inspect_config_btn.setToolTip(
            "Choose one WireGuard file. Private and pre-shared keys are discarded "
            "before Tunnel builds its local summary."
        )
        self.inspect_config_btn.clicked.connect(self.inspect_config)
        profile_row.addWidget(self.inspect_config_btn)
        diagnostics_layout.addLayout(profile_row)

        diagnostics_row = QHBoxLayout()
        self.external_checks_box = QCheckBox("Include public IP and latency")
        self.external_checks_box.setToolTip(
            "Optional: contacts api.ipify.org and tests connectivity to 1.1.1.1. "
            "Tunnel asks again before starting."
        )
        diagnostics_row.addWidget(self.external_checks_box)
        diagnostics_row.addStretch()

        self.diagnostics_stop_btn = QPushButton("Stop Check")
        self.diagnostics_stop_btn.setObjectName("DangerAction")
        self.diagnostics_stop_btn.setVisible(False)
        self.diagnostics_stop_btn.setEnabled(False)
        self.diagnostics_stop_btn.clicked.connect(self.stop_diagnostics)
        diagnostics_row.addWidget(self.diagnostics_stop_btn)

        self.diagnostics_btn = QPushButton("Check Connection")
        self.diagnostics_btn.clicked.connect(self.run_diagnostics)
        diagnostics_row.addWidget(self.diagnostics_btn)
        diagnostics_layout.addLayout(diagnostics_row)
        layout.addWidget(diagnostics_group)

        preview_group = QGroupBox("Safe Action Preview")
        preview_layout = QHBoxLayout(preview_group)
        preview_note = QLabel("Shows what would happen; never runs the command.")
        preview_note.setWordWrap(True)
        preview_layout.addWidget(preview_note, 1)
        self.action_box = MenuComboBox()
        self.action_box.addItems(["Connect", "Disconnect", "Restart"])
        self.action_box.setToolTip("Choose the change you want to inspect.")
        preview_layout.addWidget(self.action_box)
        self.preview_action_btn = QPushButton("Preview")
        self.preview_action_btn.clicked.connect(self.preview_action)
        preview_layout.addWidget(self.preview_action_btn)
        layout.addWidget(preview_group)

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

        self.diagnostics_view = SectionView()
        self.tabs.addTab(self.diagnostics_view, "Diagnostics")

        self.advisor_box = QTextBrowser()
        self.advisor_box.setOpenExternalLinks(False)
        self.tabs.addTab(self.advisor_box, "Advisor")

        self.config_box = QTextBrowser()
        self.config_box.setOpenExternalLinks(False)
        self.tabs.addTab(self.config_box, "Config && Commands")

        self.action_view = SectionView()
        self.tabs.addTab(self.action_view, "Action Preview")

        self.config_inspection_view = SectionView()
        self.tabs.addTab(self.config_inspection_view, "Config Inspection")

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

        self.reload_profiles()

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

        if self._diagnostics_running():
            QMessageBox.information(
                self, "Connection Check Running", "Stop the connection check before asking the advisor."
            )
            return
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
        stopped = False
        if super().is_running():
            self.worker.cancel()
            stopped = True
        if self._diagnostics_running():
            self.stop_diagnostics()
            stopped = True
        if stopped:
            self.status_label.setText("Stopped.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    # ── Read-only diagnostics ───────────────────────────────────────────
    def _diagnostics_running(self) -> bool:
        return (
            self._diagnostics_worker is not None
            and self._diagnostics_worker.isRunning()
        )

    def is_running(self) -> bool:
        return super().is_running() or self._diagnostics_running()

    def reload_profiles(self) -> None:
        """Refresh the profile picker without changing VPN Agent state."""
        catalog = load_vpn_profile_catalog()
        previous = self.profile_box.currentText()
        self.profile_box.clear()
        self.profile_box.addItem("No profile comparison", None)
        for profile in catalog.profiles:
            name = str(profile.get("name") or "Unnamed")
            self.profile_box.addItem(name, dict(profile))

        preferred = previous if self.profile_box.findText(previous) >= 0 else catalog.active_profile
        if preferred and self.profile_box.findText(preferred) >= 0:
            self.profile_box.setCurrentText(preferred)
        if catalog.error:
            self.profile_box.setToolTip(
                f"VPN profiles could not be loaded from {catalog.source}: {catalog.error}"
            )

    def selected_profile(self) -> dict | None:
        profile = self.profile_box.currentData()
        return dict(profile) if isinstance(profile, dict) else None

    def run_diagnostics(self) -> None:
        if super().is_running():
            QMessageBox.information(
                self, "Advisor Running", "Stop the advisor before checking the connection."
            )
            return
        if self._diagnostics_running():
            return

        include_external = self.external_checks_box.isChecked()
        if include_external:
            answer = QMessageBox.question(
                self,
                "Allow External Connectivity Checks?",
                "This optional check contacts api.ipify.org to read your public IP "
                "and tests latency to 1.1.1.1. No AI provider is used. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.diagnostics_view.clear()
        self.tabs.setCurrentWidget(self.diagnostics_view)
        self.status_label.setText(
            "Checking locally and externally…" if include_external else "Checking locally…"
        )
        self.diagnostics_btn.setVisible(False)
        self.diagnostics_btn.setEnabled(False)
        self.diagnostics_stop_btn.setVisible(True)
        self.diagnostics_stop_btn.setEnabled(True)

        worker = self.diagnostics_worker_class(
            include_external=include_external,
            selected_profile=self.selected_profile(),
        )
        self._diagnostics_worker = worker
        worker.finished_signal.connect(self._on_diagnostics_finished)
        worker.error_signal.connect(self._on_diagnostics_error)
        worker.start()

    def _finish_diagnostics_ui(self) -> None:
        self.diagnostics_btn.setVisible(True)
        self.diagnostics_btn.setEnabled(True)
        self.diagnostics_stop_btn.setVisible(False)
        self.diagnostics_stop_btn.setEnabled(False)

    def _on_diagnostics_finished(self, report: VpnDiagnosticsReport) -> None:
        self._finish_diagnostics_ui()
        self._last_diagnostics_report = report
        self.diagnostics_view.show_sections(report.sections(), raw=report.as_text())
        self.tabs.setCurrentWidget(self.diagnostics_view)
        self.status_label.setText("Connection check stopped." if report.cancelled else "Connection check complete.")

    def _on_diagnostics_error(self, error: str) -> None:
        self._finish_diagnostics_ui()
        self.diagnostics_view.show_sections(
            [("Connection check could not finish", error, False)], raw=error
        )
        self.tabs.setCurrentWidget(self.diagnostics_view)
        self.status_label.setText("Connection check error.")

    def stop_diagnostics(self) -> None:
        if self._diagnostics_running():
            self._diagnostics_worker.cancel()
            self.status_label.setText("Stopping connection check…")
            self.diagnostics_stop_btn.setEnabled(False)

    def inspect_config(self) -> None:
        """Summarise one selected WireGuard file without retaining its secrets."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Inspect WireGuard Configuration",
            "",
            "WireGuard configurations (*.conf);;All files (*)",
        )
        if not path:
            return
        try:
            inspection = inspect_wireguard_config(path, self._last_diagnostics_report)
        except ValueError as exc:
            QMessageBox.warning(self, "Configuration Could Not Be Inspected", str(exc))
            return
        self.config_inspection_view.show_sections(
            inspection.sections(), raw=inspection.as_text()
        )
        self.tabs.setCurrentWidget(self.config_inspection_view)
        self.status_label.setText(
            "Configuration inspected locally — key material discarded."
        )

    def shutdown(self, timeout_ms: int = 2000) -> None:
        """Cancel and join Tunnel workers before their widgets are destroyed."""
        workers = [self.worker, self._diagnostics_worker]
        for worker in workers:
            if worker is not None and worker.isRunning():
                worker.cancel()
        for worker in workers:
            if worker is None or not worker.isRunning() or not hasattr(worker, "wait"):
                continue
            if not worker.wait(timeout_ms) and hasattr(worker, "terminate"):
                # Every diagnostic command is bounded, but application shutdown
                # must not destroy a live QThread if an OS call ignores cancellation.
                worker.terminate()
                worker.wait(500)

    # ── Deliberately non-executing action preview ─────────────────────
    def preview_action(self) -> None:
        preview = build_vpn_action_preview(
            self.action_box.currentText(),
            self.selected_profile(),
            self._last_diagnostics_report,
        )
        self.action_view.show_sections(preview.sections(), raw=preview.as_text())
        self.tabs.setCurrentWidget(self.action_view)
        self.status_label.setText(
            "Action preview ready — nothing executed."
            if preview.valid else "Action preview unavailable."
        )

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
        self.diagnostics_view.clear()
        self.advisor_box.clear()
        self.config_box.clear()
        self.action_view.clear()
        self.config_inspection_view.clear()
        self.question_input.clear()
        self.status_label.setText("Idle")
        self._last_response = ""
        self._last_diagnostics_report = None
