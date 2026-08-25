"""Beacon — Wi-Fi reconnaissance, adapter detection and a Kali command builder.

Sixth and last vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

Three kinds of work share one panel, and only one of them costs money:

- the scans run a local subprocess (`airport`, `ping`, `networksetup`) —
  unpaid, cancelled by the scan worker;
- the Kali builder renders command strings from `build_kali_commands` — unpaid,
  no network at all;
- the optional AI pass over either result is a paid request through the guard.

`stop` therefore cancels *both* workers: a scan can still be running when the AI
pass has not started, or the reverse.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSplitter, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from agents.wifi_agent import AIRPORT, build_kali_commands, detect_usb_adapters
from services.runtime_paths import user_data_base
from ui.workers import SubprocessWorker
from ui.panels.base import AgentPanel
from ui.widgets import MenuComboBox

# Static facts about the adapters the Kali builder knows how to target.
KALI_ADAPTERS = {
    "TL-WN722N (AR9271)": {
        "name": "TL-WN722N", "chipset": "AR9271", "monitor": True, "inject": True,
        "kali_iface": "wlan0", "driver_note": "ath9k_htc — works out of the box on Kali.",
    },
    "AWUS036ACH (RTL8812AU)": {
        "name": "AWUS036ACH", "chipset": "RTL8812AU", "monitor": True, "inject": True,
        "kali_iface": "wlan0",
        "driver_note": "Install driver in Kali: sudo apt install realtek-rtl88xxau-dkms",
    },
    "TL-WN725N V3 (RTL8188EU)": {
        "name": "TL-WN725N V3", "chipset": "RTL8188EU", "monitor": True, "inject": False,
        "kali_iface": "wlan0",
        "driver_note": "Limited injection support — passive monitoring only.",
    },
}


class WifiPanel(AgentPanel):
    """Wireless recon with an optional AI read of the results."""

    agent_key = "wifi"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("WiFiPanel")
        self._last_response = ""
        self._detected_adapter: dict = {}
        self.scan_worker: SubprocessWorker | None = None
        self._build()
        self.polish_workspace()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Quick Setup ──────────────────────────────────────────────────
        setup_group = QGroupBox("Quick Setup")
        setup_group.setObjectName("WiFiSetupGroup")
        setup_layout = QGridLayout(setup_group)
        setup_layout.setSpacing(6)

        setup_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_box = MenuComboBox()
        self.mode_box.addItems([
            "Interface Info", "Scan Networks", "Signal Monitor",
            "Ping Test", "Kali Command Builder",
        ])
        self.mode_box.currentTextChanged.connect(self._on_mode_changed)
        setup_layout.addWidget(self.mode_box, 0, 1)

        setup_layout.addWidget(QLabel("Interface:"), 0, 2)
        self.interface_box = MenuComboBox()
        self.interface_box.addItems(["en0", "en1", "en2", "en3"])
        setup_layout.addWidget(self.interface_box, 0, 3)

        setup_layout.addWidget(QLabel("Target Host:"), 1, 0)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("e.g. 192.168.1.1  (used for Ping Test)")
        setup_layout.addWidget(self.target_input, 1, 1, 1, 3)

        layout.addWidget(setup_group)

        # ── Kali sub-form ────────────────────────────────────────────────
        self.kali_group = QGroupBox("Kali Command Builder")
        self.kali_group.setObjectName("WiFiKaliGroup")
        kali_layout = QGridLayout(self.kali_group)
        kali_layout.setSpacing(6)

        kali_layout.addWidget(QLabel("Operation:"), 0, 0)
        self.kali_op_box = MenuComboBox()
        self.kali_op_box.addItems([
            "Handshake Capture", "Deauth Attack", "WPS Audit", "PMKID Attack",
        ])
        kali_layout.addWidget(self.kali_op_box, 0, 1)

        kali_layout.addWidget(QLabel("Adapter:"), 0, 2)
        self.kali_adapter_box = MenuComboBox()
        self.kali_adapter_box.addItems(list(KALI_ADAPTERS.keys()))
        kali_layout.addWidget(self.kali_adapter_box, 0, 3)

        kali_layout.addWidget(QLabel("BSSID:"), 1, 0)
        self.kali_bssid_input = QLineEdit()
        self.kali_bssid_input.setPlaceholderText("e.g. AA:BB:CC:DD:EE:FF")
        kali_layout.addWidget(self.kali_bssid_input, 1, 1)

        kali_layout.addWidget(QLabel("Channel:"), 1, 2)
        self.kali_channel_input = QLineEdit()
        self.kali_channel_input.setPlaceholderText("e.g. 6")
        kali_layout.addWidget(self.kali_channel_input, 1, 3)

        kali_layout.addWidget(QLabel("Network (ESSID):"), 2, 0)
        self.kali_essid_input = QLineEdit()
        self.kali_essid_input.setPlaceholderText("e.g. MyHomeNetwork")
        kali_layout.addWidget(self.kali_essid_input, 2, 1, 1, 3)

        layout.addWidget(self.kali_group)
        self.kali_group.hide()

        self.run_btn = QPushButton("Run")
        self.run_btn.setMinimumWidth(110)
        self.run_btn.setObjectName("PrimaryAction")
        self.run_btn.clicked.connect(self.run)

        self.detect_btn = QPushButton("Detect Adapters")
        self.detect_btn.setToolTip("Scan USB bus for connected Wi-Fi adapters")
        self.detect_btn.clicked.connect(self.detect_adapters)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        self.stop_btn.clicked.connect(self.stop)
        self.set_busy(self.run_btn, self.stop_btn, False)

        # ── Provider / action row ────────────────────────────────────────
        provider_row_container = self.build_run_bar(
            self.run_btn,
            stop=self.stop_btn,
            secondary=(self.detect_btn,),
            context="Wireless",
        )

        layout.addWidget(provider_row_container)

        ai_row = QHBoxLayout()
        self.ai_checkbox = QCheckBox("AI Analysis — feed results to LLM for interpretation")
        self.ai_checkbox.setChecked(True)
        ai_row.addWidget(self.ai_checkbox)
        ai_row.addStretch()
        layout.addLayout(ai_row)

        # ── Results splitter ─────────────────────────────────────────────
        results_splitter = QSplitter(Qt.Horizontal)

        self.tabs = QTabWidget()

        self.raw_box = QTextBrowser()
        self.raw_box.setOpenExternalLinks(False)
        self.tabs.addTab(self.raw_box, "Raw Output")

        self.analysis_box = QTextBrowser()
        self.tabs.addTab(self.analysis_box, "AI Analysis")

        self.kali_cmd_box = QTextBrowser()
        self.tabs.addTab(self.kali_cmd_box, "Kali Commands")

        self.raw_box.setPlaceholderText("Wireless scan or interface output will appear here.")
        self.analysis_box.setPlaceholderText(
            "Optional AI interpretation will appear here when AI Analysis is enabled."
        )
        self.kali_cmd_box.setPlaceholderText(
            "Generated authorised-testing commands will appear here."
        )

        results_splitter.addWidget(self.tabs)

        # ── Sidebar indicators ───────────────────────────────────────────
        indicators_widget = QWidget()
        indicators_layout = QVBoxLayout(indicators_widget)
        indicators_layout.setContentsMargins(6, 6, 6, 6)
        indicators_layout.setSpacing(8)

        adapter_group = QGroupBox("Adapter")
        adapter_group.setObjectName("WiFiAdapterGroup")
        adapter_layout = QVBoxLayout(adapter_group)
        self.adapter_label = QLabel("Not detected")
        self.adapter_label.setAlignment(Qt.AlignCenter)
        self.adapter_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #4db8ff;")
        self.adapter_label.setWordWrap(True)
        adapter_layout.addWidget(self.adapter_label)
        indicators_layout.addWidget(adapter_group)

        chipset_group = QGroupBox("Chipset")
        chipset_group.setObjectName("WiFiChipsetGroup")
        chipset_layout = QVBoxLayout(chipset_group)
        self.chipset_label = QLabel("—")
        self.chipset_label.setAlignment(Qt.AlignCenter)
        self.chipset_label.setStyleSheet("font-size: 12px; color: #aaa;")
        chipset_layout.addWidget(self.chipset_label)
        indicators_layout.addWidget(chipset_group)

        caps_group = QGroupBox("Capabilities")
        caps_group.setObjectName("WiFiCapsGroup")
        caps_layout = QVBoxLayout(caps_group)
        self.monitor_label = QLabel("Monitor  —")
        self.inject_label = QLabel("Injection  —")
        self.monitor_label.setStyleSheet("font-size: 12px;")
        self.inject_label.setStyleSheet("font-size: 12px;")
        caps_layout.addWidget(self.monitor_label)
        caps_layout.addWidget(self.inject_label)
        indicators_layout.addWidget(caps_group)

        signal_group = QGroupBox("Signal (RSSI)")
        signal_group.setObjectName("WiFiSignalGroup")
        signal_layout = QVBoxLayout(signal_group)
        self.signal_bar = QProgressBar()
        self.signal_bar.setMinimum(0)
        self.signal_bar.setMaximum(100)
        self.signal_bar.setValue(0)
        self.signal_bar.setTextVisible(True)
        signal_layout.addWidget(self.signal_bar)
        self.signal_val_label = QLabel("—")
        self.signal_val_label.setAlignment(Qt.AlignCenter)
        self.signal_val_label.setStyleSheet("font-size: 11px; color: #aaa;")
        signal_layout.addWidget(self.signal_val_label)
        indicators_layout.addWidget(signal_group)

        sec_group = QGroupBox("Security")
        sec_group.setObjectName("WiFiSecGroup")
        sec_layout = QVBoxLayout(sec_group)
        self.security_label = QLabel("—")
        self.security_label.setAlignment(Qt.AlignCenter)
        self.security_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        sec_layout.addWidget(self.security_label)
        indicators_layout.addWidget(sec_group)

        indicators_layout.addStretch()

        self.save_btn = QPushButton("Save Output")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        indicators_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        indicators_layout.addWidget(self.clear_btn)

        results_splitter.addWidget(indicators_widget)
        results_splitter.setSizes([680, 220])
        layout.addWidget(results_splitter, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

    # ── Mode / adapters ─────────────────────────────────────────────────
    def _on_mode_changed(self, mode: str) -> None:
        is_kali = mode == "Kali Command Builder"
        self.kali_group.setVisible(is_kali)
        self.ai_checkbox.setEnabled(not is_kali)
        if is_kali:
            self.tabs.setCurrentIndex(2)

    def detect_adapters(self) -> None:
        self.status_label.setText("Scanning USB bus...")
        self.detect_btn.setEnabled(False)
        adapters = detect_usb_adapters()
        self.detect_btn.setEnabled(True)

        if not adapters or "error" in adapters[0]:
            err = (adapters[0].get("error", "Unknown error")
                   if adapters else "No adapters found")
            self.adapter_label.setText("None found")
            self.chipset_label.setText("—")
            self.monitor_label.setText("Monitor  —")
            self.inject_label.setText("Injection  —")
            self.raw_box.setPlainText(
                "[Adapter Detection]\nNo known Wi-Fi adapters detected on USB bus.\n" + err)
            self.status_label.setText("No known adapters detected.")
            self._detected_adapter = {}
            return

        adapter = adapters[0]
        self._detected_adapter = adapter
        self.adapter_label.setText(adapter.get("name", "Unknown"))
        self.chipset_label.setText(adapter.get("chipset", "—"))

        mon_ok = adapter.get("monitor", False)
        inj_ok = adapter.get("inject", False)
        self.monitor_label.setText(f"Monitor  {'✅' if mon_ok else '❌'}")
        self.inject_label.setText(f"Injection  {'✅' if inj_ok else '❌'}")
        self.monitor_label.setStyleSheet(
            f"font-size: 12px; color: {'#3cff88' if mon_ok else '#ff5555'};")
        self.inject_label.setStyleSheet(
            f"font-size: 12px; color: {'#3cff88' if inj_ok else '#ff5555'};")

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
        self.raw_box.setPlainText(report)
        self.tabs.setCurrentIndex(0)
        self.status_label.setText(
            f"Detected: {adapter.get('name')} ({adapter.get('chipset')})")

    # ── Running ─────────────────────────────────────────────────────────
    def run(self) -> None:
        mode = self.mode_box.currentText()

        if mode == "Kali Command Builder":
            self._run_kali_builder()
            return

        self._clear_displays()
        self._last_response = ""
        self.set_busy(self.run_btn, self.stop_btn, True)
        self.save_btn.setEnabled(False)
        self.status_label.setText(f"Running: {mode}…")
        self.tabs.setCurrentIndex(0)

        if mode == "Interface Info":
            cmd = ["networksetup", "-listallhardwareports"]
        elif mode == "Scan Networks":
            cmd = [AIRPORT, "-s"]
        elif mode == "Signal Monitor":
            cmd = [AIRPORT, "-I"]
        elif mode == "Ping Test":
            target = self.target_input.text().strip()
            if not target:
                QMessageBox.warning(
                    self, "Missing Target", "Enter a target host or IP for Ping Test.")
                self.set_busy(self.run_btn, self.stop_btn, False)
                return
            cmd = ["ping", "-c", "8", target]
        else:
            cmd = [AIRPORT, "-I"]

        self.scan_worker = SubprocessWorker(cmd)
        self.scan_worker.finished_signal.connect(self._scan_finished)
        self.scan_worker.error_signal.connect(self._scan_error)
        self.scan_worker.start()

    def _run_kali_builder(self) -> None:
        op = self.kali_op_box.currentText()
        adapter_name = self.kali_adapter_box.currentText()
        bssid = self.kali_bssid_input.text().strip()
        channel = self.kali_channel_input.text().strip()
        essid = self.kali_essid_input.text().strip()

        adapter = KALI_ADAPTERS.get(adapter_name, next(iter(KALI_ADAPTERS.values())))
        cmds = build_kali_commands(op, adapter, bssid, channel, essid)

        self.kali_cmd_box.setPlainText(cmds)
        self.tabs.setCurrentIndex(2)
        self._last_response = cmds
        self.save_btn.setEnabled(True)
        self.status_label.setText(f"Kali commands generated: {op}")

        if self.ai_checkbox.isEnabled() and self.ai_checkbox.isChecked() and self.model:
            prompt = (
                "Explain the following Kali Linux Wi-Fi attack command sequence for an "
                "authorised penetration test. Break down what each step does and what to "
                f"watch for:\n\n{cmds}"
            )
            self._start_ai_pass(prompt)

    def _scan_finished(self, raw: str) -> None:
        self.raw_box.setPlainText(raw)
        self.status_label.setText("Scan complete.")
        self._update_indicators(raw)

        if self.ai_checkbox.isChecked() and self.model:
            mode = self.mode_box.currentText()
            prompt = f"Mode: {mode}\n\nRaw output:\n{raw}\n\nAnalyse this Wi-Fi scan result."
            self._start_ai_pass(prompt)
            self.status_label.setText("Running AI analysis…")
        else:
            self._last_response = raw
            self.set_busy(self.run_btn, self.stop_btn, False)
            self.save_btn.setEnabled(True)

    def _start_ai_pass(self, prompt: str) -> None:
        """The paid half. `run`/scan already put the panel in the running state."""
        messages = self.agent().build_messages(prompt)
        if not self.authorize(prompt):
            self.set_busy(self.run_btn, self.stop_btn, False)
            return
        self.start_worker(
            messages, prompt,
            on_token=self._on_token,
            on_finished=self._on_finished,
            on_error=self._on_error,
        )
        self.tabs.setCurrentIndex(1)

    def _scan_error(self, error: str) -> None:
        self.raw_box.setPlainText(f"[Error]\n{error}")
        self.status_label.setText("Error running scan.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    def _on_token(self, token: str) -> None:
        self._last_response += token
        self.analysis_box.setPlainText(self._last_response)
        self.analysis_box.moveCursor(QTextCursor.End)

    def _on_finished(self, full_response: str) -> None:
        self.record(full_response)
        self._last_response = full_response
        self.analysis_box.setPlainText(full_response)
        self.status_label.setText("Analysis complete.")
        self.set_busy(self.run_btn, self.stop_btn, False)
        self.save_btn.setEnabled(True)

    def _on_error(self, error: str) -> None:
        self.abandon()
        self.analysis_box.setPlainText(f"[Error] {error}")
        self.status_label.setText("Error.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    def stop(self) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.cancel()
        self.stop_worker()
        self.status_label.setText("Stopped.")
        self.set_busy(self.run_btn, self.stop_btn, False)

    def is_running(self) -> bool:
        scan = self.scan_worker is not None and self.scan_worker.isRunning()
        return scan or super().is_running()

    # ── Output ──────────────────────────────────────────────────────────
    def save(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        if not self._last_response:
            return
        mode = self.mode_box.currentText().lower().replace(" ", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"wifi_{mode}_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Wi-Fi Output",
            str(user_data_base() / "data" / default_name),
            "Text files (*.txt);;All files (*)",
        )
        if path:
            Path(path).write_text(self._last_response, encoding="utf-8")
            self.status_label.setText(f"Saved to {Path(path).name}")

    def clear(self) -> None:
        self._clear_displays()
        self.target_input.clear()
        self.kali_bssid_input.clear()
        self.kali_channel_input.clear()
        self.kali_essid_input.clear()
        self.status_label.setText("")
        self._last_response = ""

    def _clear_displays(self) -> None:
        self.raw_box.clear()
        self.analysis_box.clear()
        self.kali_cmd_box.clear()
        self.signal_bar.setValue(0)
        self.signal_val_label.setText("—")
        self.security_label.setText("—")
        self.save_btn.setEnabled(False)

    def _update_indicators(self, raw: str) -> None:
        rssi_m = re.search(r"agrCtlRSSI:\s*(-\d+)", raw)
        if rssi_m:
            rssi = int(rssi_m.group(1))
            quality = max(0, min(100, 2 * (rssi + 100)))
            self.signal_bar.setValue(quality)
            self.signal_val_label.setText(f"{rssi} dBm")
            bar_color = ("#3cff88" if quality >= 60 else "#f0c040"
                         if quality >= 30 else "#ff5555")
            self.signal_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 3px; }}"
            )

        sec_m = re.search(r"link auth:\s*(\S+)", raw, re.IGNORECASE)
        if sec_m:
            self.security_label.setText(sec_m.group(1).upper())
        elif "WPA3" in raw:
            self.security_label.setText("WPA3")
        elif "WPA2" in raw:
            self.security_label.setText("WPA2")
        elif "WPA" in raw:
            self.security_label.setText("WPA")
        elif "WEP" in raw:
            self.security_label.setText("WEP")
            self.security_label.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #ff5555;")
