"""Bug Spray — recon, triage and a submission draft for one bug-bounty target.

Third vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

The nmap half runs a local process, not a paid request: it goes nowhere near the
request guard, and `kill_nmap` is separate from `stop`, which cancels the LLM
analysis. Keeping the two apart is why `stop` does not touch the scan.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSplitter, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from ui.panels.base import AgentPanel
from ui.widgets import SectionView

SEVERITY_COLOURS = {
    "Critical": "#ff3333", "High": "#ff7722", "Medium": "#f0c040",
    "Low": "#3cff88", "Informational": "#4db8ff",
}


class BugBountyPanel(AgentPanel):
    """Triage findings into a severity, a CVSS score and a report to submit."""

    agent_key = "bug_bounty"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("BugBountyPanel")
        self._last_response = ""
        self._nmap_process: QProcess | None = None
        self._build()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Target / program setup ───────────────────────────────────────
        setup_group = QGroupBox("Target & Program")
        setup_group.setObjectName("BBSetupBox")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Target URL / IP:"), 0, 0)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("https://target.example.com  or  10.0.0.1")
        setup_layout.addWidget(self.target_input, 0, 1, 1, 3)

        setup_layout.addWidget(QLabel("Program:"), 1, 0)
        self.program_input = QLineEdit()
        self.program_input.setPlaceholderText("HackerOne — Acme Corp  /  Bugcrowd — Example")
        setup_layout.addWidget(self.program_input, 1, 1, 1, 3)

        setup_layout.addWidget(QLabel("Scope Type:"), 2, 0)
        self.scope_box = QComboBox()
        self.scope_box.addItems([
            "Web Application", "API / REST", "Mobile (Android)", "Mobile (iOS)",
            "Network / Infrastructure", "Source Code Review", "Cloud Config", "Other",
        ])
        setup_layout.addWidget(self.scope_box, 2, 1)

        setup_layout.addWidget(QLabel("Severity Target:"), 2, 2)
        self.severity_box = QComboBox()
        self.severity_box.addItems(
            ["Critical (P1)", "High (P2)", "Medium (P3)", "Low (P4)", "Informational"])
        setup_layout.addWidget(self.severity_box, 2, 3)

        layout.addWidget(setup_group)

        # ── Nmap scan section ────────────────────────────────────────────
        nmap_group = QGroupBox("Nmap Recon Scan")
        nmap_group.setObjectName("BBNmapBox")
        nmap_layout = QVBoxLayout(nmap_group)
        nmap_layout.setSpacing(4)

        nmap_cmd_row = QHBoxLayout()
        self.nmap_cmd_input = QLineEdit()
        self.nmap_cmd_input.setPlaceholderText("nmap -sV -sC -T4 --open <target>")
        nmap_cmd_row.addWidget(self.nmap_cmd_input, 1)
        self.nmap_run_btn = QPushButton("Run Nmap")
        self.nmap_run_btn.setMinimumWidth(120)
        self.nmap_run_btn.setObjectName("PrimaryAction")
        self.nmap_run_btn.clicked.connect(self.run_nmap)
        nmap_cmd_row.addWidget(self.nmap_run_btn)
        self.nmap_stop_btn = QPushButton("Kill")
        self.nmap_stop_btn.setEnabled(False)
        self.nmap_stop_btn.setObjectName("DangerAction")
        self.nmap_stop_btn.clicked.connect(self.kill_nmap)
        nmap_cmd_row.addWidget(self.nmap_stop_btn)
        nmap_layout.addLayout(nmap_cmd_row)

        self.nmap_output = QTextBrowser()
        self.nmap_output.setOpenExternalLinks(False)
        self.nmap_output.setFixedHeight(130)
        self.nmap_output.setPlaceholderText("Nmap output will appear here…")
        nmap_layout.addWidget(self.nmap_output)
        layout.addWidget(nmap_group)

        # ── Findings / Burp paste area ───────────────────────────────────
        findings_group = QGroupBox("Findings / Burp Suite Output / Notes")
        findings_group.setObjectName("BBFindingsBox")
        findings_layout = QVBoxLayout(findings_group)
        self.findings_input = QTextEdit()
        self.findings_input.setPlaceholderText(
            "Paste HTTP request/response, Burp Suite output, manual observations, "
            "error messages, source code snippets — anything in scope."
        )
        self.findings_input.setMinimumHeight(110)
        findings_layout.addWidget(self.findings_input)
        layout.addWidget(findings_group)

        # ── Provider row ─────────────────────────────────────────────────
        provider_row_container, provider_row = self.flow_row()
        self.build_provider_row(provider_row)

        self.analyse_btn = QPushButton("Analyse")
        self.analyse_btn.setMinimumWidth(130)
        self.analyse_btn.setObjectName("PrimaryAction")
        self.analyse_btn.clicked.connect(self.analyse)
        provider_row.addWidget(self.analyse_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        self.stop_btn.clicked.connect(self.stop)
        provider_row.addWidget(self.stop_btn)
        layout.addWidget(provider_row_container)

        # ── Results: structured report + sidebar ────────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)
        self.stream_box = QTextBrowser()
        self.stream_box.setOpenExternalLinks(False)
        self.stream_box.setVisible(False)
        result_layout.addWidget(self.stream_box, 1)
        self.sections = SectionView()
        result_layout.addWidget(self.sections, 1)

        results_splitter.addWidget(result_widget)

        # Sidebar indicators
        indicators_widget = QWidget()
        ind_layout = QVBoxLayout(indicators_widget)
        ind_layout.setContentsMargins(8, 0, 0, 0)
        ind_layout.setSpacing(10)

        sev_group = QGroupBox("Severity")
        sev_group.setObjectName("BBSevBox")
        sev_inner = QVBoxLayout(sev_group)
        self.severity_label = QLabel("—")
        self.severity_label.setAlignment(Qt.AlignCenter)
        self.severity_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #ff5555;")
        sev_inner.addWidget(self.severity_label)
        ind_layout.addWidget(sev_group)

        cvss_group = QGroupBox("CVSS Score")
        cvss_group.setObjectName("BBCvssBox")
        cvss_inner = QVBoxLayout(cvss_group)
        self.cvss_label = QLabel("—")
        self.cvss_label.setAlignment(Qt.AlignCenter)
        self.cvss_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        cvss_inner.addWidget(self.cvss_label)
        ind_layout.addWidget(cvss_group)

        bounty_group = QGroupBox("Bounty Estimate")
        bounty_group.setObjectName("BBBountyBox")
        bounty_inner = QVBoxLayout(bounty_group)
        self.bounty_label = QLabel("—")
        self.bounty_label.setAlignment(Qt.AlignCenter)
        self.bounty_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #3cff88;")
        bounty_inner.addWidget(self.bounty_label)
        ind_layout.addWidget(bounty_group)

        ind_layout.addStretch()

        self.save_btn = QPushButton("Save Report")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        ind_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        ind_layout.addWidget(self.clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([700, 200])
        layout.addWidget(results_splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

    # ── Recon (local, unpaid) ───────────────────────────────────────────
    def run_nmap(self) -> None:
        cmd_text = self.nmap_cmd_input.text().strip()
        if not cmd_text:
            target = self.target_input.text().strip()
            if not target:
                self.nmap_output.setPlainText(
                    "[Error] Enter a target URL/IP or nmap command first.")
                return
            # strip protocol for nmap
            host = target.replace("https://", "").replace("http://", "").split("/")[0]
            cmd_text = f"nmap -sV -sC -T4 --open {host}"
            self.nmap_cmd_input.setText(cmd_text)

        self.nmap_output.setPlainText(f"[Running] {cmd_text}\n")
        self.nmap_run_btn.setEnabled(False)
        self.nmap_stop_btn.setEnabled(True)

        self._nmap_process = QProcess(self)
        self._nmap_process.setProcessChannelMode(QProcess.MergedChannels)
        self._nmap_process.readyRead.connect(self._nmap_read)
        self._nmap_process.finished.connect(self._nmap_finished)

        parts = cmd_text.split()
        self._nmap_process.start(parts[0], parts[1:])

    def _nmap_read(self) -> None:
        data = self._nmap_process.readAll().data().decode("utf-8", errors="replace")
        self.nmap_output.moveCursor(QTextCursor.End)
        self.nmap_output.insertPlainText(data)
        self.nmap_output.moveCursor(QTextCursor.End)

    def _nmap_finished(self) -> None:
        self.nmap_run_btn.setEnabled(True)
        self.nmap_stop_btn.setEnabled(False)
        self.nmap_output.moveCursor(QTextCursor.End)
        self.nmap_output.insertPlainText("\n[Done]")

    def kill_nmap(self) -> None:
        if self._nmap_process is not None:
            self._nmap_process.kill()
        self.nmap_run_btn.setEnabled(True)
        self.nmap_stop_btn.setEnabled(False)

    # ── Analysis (paid) ─────────────────────────────────────────────────
    def analyse(self) -> None:
        target = self.target_input.text().strip()
        program = self.program_input.text().strip()
        scope_type = self.scope_box.currentText()
        findings = self.findings_input.toPlainText().strip()
        nmap_output = self.nmap_output.toPlainText().strip()

        if not target and not findings and not nmap_output:
            self.status_label.setText(
                "Enter a target, paste findings, or run a scan first.")
            return

        if not self.model:
            self.status_label.setText("Select a model first.")
            return

        messages = self.agent().build_messages(
            target, program, scope_type, findings, nmap_output)

        self._last_response = ""
        self.sections.clear()
        self.sections.setVisible(True)
        self.stream_box.clear()
        self.stream_box.setVisible(False)
        self.severity_label.setText("—")
        self.cvss_label.setText("—")
        self.bounty_label.setText("—")
        self.save_btn.setEnabled(False)
        self.status_label.setText("Analysing…")
        self.analyse_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        prompt = target or "bug_bounty"
        if not self.authorize(prompt):
            # The controls were already disabled above; a blocked request has to
            # put them back or the panel is stuck with a dead Analyse button.
            self.status_label.setText("Blocked before sending.")
            self.analyse_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        self.start_worker(
            messages, prompt,
            on_token=self._on_token,
            on_finished=self._on_finished,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        self._last_response += token
        self.sections.setVisible(False)
        self.stream_box.setVisible(True)
        self.stream_box.setPlainText(self._last_response)
        self.stream_box.moveCursor(QTextCursor.End)

    def _on_finished(self, full_response: str) -> None:
        self.record(full_response)
        self._last_response = full_response
        self.stream_box.setVisible(False)
        self.sections.setVisible(True)
        self._populate_sections(full_response)
        self._update_indicators(full_response)
        self.status_label.setText("Analysis complete.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(True)

    def _on_error(self, error: str) -> None:
        self.abandon()
        self.sections.setVisible(False)
        self.stream_box.setVisible(True)
        self.stream_box.setPlainText(f"[Error] {error}")
        self.status_label.setText("Error.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def stop(self) -> None:
        self.stop_worker()
        self.status_label.setText("Stopped.")
        self.analyse_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Report ──────────────────────────────────────────────────────────
    def _populate_sections(self, text: str) -> None:
        def extract(pattern):
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else ""

        vuln = extract(r"(?:##\s*VULNERABILITY\s*REPORT|##\s*Vulnerability Details?)(.*?)(?=##|$)")
        poc = extract(r"(?:##\s*Proof of Concept|PoC\s*Draft?)(.*?)(?=##|$)")
        rem = extract(r"(?:##\s*Remediation)(.*?)(?=##|$)")
        sub = extract(r"(?:##\s*SUBMISSION\s*DRAFT|Submission\s*Draft?)(.*?)(?=##|$)")

        self.sections.show_sections([
            ("Vulnerability Report", vuln or text),
            ("Proof of Concept", poc, True),
            ("Remediation", rem),
            ("Submission Draft", sub),
        ], raw=text)

    def _update_indicators(self, text: str) -> None:
        sev_m = re.search(
            r"\*\*Severity\*\*.*?(Critical|High|Medium|Low|Informational)",
            text, re.IGNORECASE)
        if sev_m:
            sev = sev_m.group(1).capitalize()
            self.severity_label.setText(sev)
            self.severity_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; "
                f"color: {SEVERITY_COLOURS.get(sev, '#ffffff')};"
            )

        cvss_m = re.search(r"CVSS.*?(\d+\.\d+)", text, re.IGNORECASE)
        if cvss_m:
            score = float(cvss_m.group(1))
            color = ("#ff3333" if score >= 9 else "#ff7722" if score >= 7
                     else "#f0c040" if score >= 4 else "#3cff88")
            self.cvss_label.setText(cvss_m.group(1))
            self.cvss_label.setStyleSheet(
                f"font-size: 22px; font-weight: bold; color: {color};")

        bounty_m = re.search(
            r"bounty.*?(\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?|\$[\d,]+\+?)",
            text, re.IGNORECASE)
        if bounty_m:
            self.bounty_label.setText(bounty_m.group(1))

    def save(self) -> None:
        if not self._last_response:
            return
        target = (self.target_input.text().strip()
                  .replace("/", "-").replace(":", "").replace(" ", "_")) or "target"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = QFileDialog.getSaveFileName(
            self, "Save Bug Bounty Report",
            str(Path.home() / "Downloads" / f"bb_report_{target}_{ts}.md"),
            "Markdown (*.md);;Text (*.txt)",
        )[0]
        if path:
            Path(path).write_text(self._last_response, encoding="utf-8")
            self.status_label.setText(f"Saved: {path}")

    def clear(self) -> None:
        self.target_input.clear()
        self.program_input.clear()
        self.findings_input.clear()
        self.nmap_output.clear()
        self.nmap_cmd_input.clear()
        self.sections.clear()
        self.sections.setVisible(True)
        self.stream_box.clear()
        self.stream_box.setVisible(False)
        self.severity_label.setText("—")
        self.severity_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #ff5555;")
        self.cvss_label.setText("—")
        self.cvss_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self.bounty_label.setText("—")
        self.status_label.setText("")
        self.save_btn.setEnabled(False)
        self._last_response = ""
