"""Forge — describe an agent in prose, review the generated spec, create it.

Second vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

Two things differ from the other panels and are deliberate:

- Forge owns its `ManagerAgent` rather than taking it from
  `host.agent_instances`. It was never registered there, and registering it now
  would put it in the chat panel's `build_messages` path, which is a behaviour
  change and not part of a move.
- Writing the agent files is the host's job (`agent_factory`): it touches
  `agents/` and `config/` for the whole application, not for this panel.
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
)

from agents.manager_agent import ManagerAgent
from ui.panels.base import AgentPanel


class ManagerPanel(AgentPanel):
    """Turn an idea into a reviewed agent spec, then write the agent."""

    agent_key = "manager"
    default_provider = "deepseek"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("ManagerPanel")
        self.manager_agent = ManagerAgent()
        self.pending_spec: dict | None = None
        self._build()
        self.polish_workspace()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Idea input ───────────────────────────────────────────────────
        idea_group = QGroupBox("Describe Your Agent Idea")
        idea_group.setObjectName("ManagerIdeaBox")
        idea_layout = QVBoxLayout(idea_group)

        self.idea_input = QTextEdit()
        self.idea_input.setPlaceholderText(
            "Example: A cybersecurity agent that helps analyse logs, detect anomalies, "
            "and suggest mitigations. Should prefer local models for privacy."
        )
        self.idea_input.setMinimumHeight(100)
        self.idea_input.setMaximumHeight(160)
        idea_layout.addWidget(self.idea_input)

        idea_btn_row = QHBoxLayout()
        self.build_provider_row(idea_btn_row, empty_placeholder=True)
        idea_btn_row.addStretch()

        self.analyze_btn = QPushButton("Analyze Idea")
        self.analyze_btn.setMinimumWidth(140)
        self.analyze_btn.setObjectName("PrimaryAction")
        self.analyze_btn.clicked.connect(self.analyze_idea)
        idea_btn_row.addWidget(self.analyze_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        idea_btn_row.addWidget(self.clear_btn)

        idea_layout.addLayout(idea_btn_row)
        layout.addWidget(idea_group)

        # ── Generated spec ───────────────────────────────────────────────
        spec_group = QGroupBox("Generated Spec (review before approving)")
        spec_group.setObjectName("ManagerSpecBox")
        spec_layout = QVBoxLayout(spec_group)

        self.spec_display = QTextEdit()
        self.spec_display.setReadOnly(True)
        self.spec_display.setMinimumHeight(180)
        self.spec_display.setPlaceholderText("Spec will appear here after analysis...")
        self.spec_display.setStyleSheet("font-family: monospace; font-size: 12px;")
        spec_layout.addWidget(self.spec_display)

        approve_row = QHBoxLayout()

        self.approve_btn = QPushButton("Approve && Create Agent")
        self.approve_btn.setEnabled(False)
        self.approve_btn.setMinimumWidth(200)
        self.approve_btn.setObjectName("PrimaryAction")
        self.approve_btn.clicked.connect(self.approve_spec)
        approve_row.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("Reject / Clear Spec")
        self.reject_btn.setEnabled(False)
        self.reject_btn.clicked.connect(self.reject_spec)
        approve_row.addWidget(self.reject_btn)

        approve_row.addStretch()
        spec_layout.addLayout(approve_row)
        layout.addWidget(spec_group)

        # ── Creation log ─────────────────────────────────────────────────
        log_group = QGroupBox("Creation Log")
        log_group.setObjectName("ManagerLogBox")
        log_layout = QVBoxLayout(log_group)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(100)
        self.log.setPlaceholderText("Agent creation and validation events will appear here.")
        self.log.setStyleSheet("font-family: monospace; font-size: 12px;")
        log_layout.addWidget(self.log)
        layout.addWidget(log_group)

    # ── Running ─────────────────────────────────────────────────────────
    def analyze_idea(self) -> None:
        idea = self.idea_input.toPlainText().strip()
        if not idea:
            QMessageBox.warning(self, "No Idea", "Please describe your agent idea first.")
            return

        if self.is_running():
            QMessageBox.information(self, "Busy", "Analysis already running.")
            return

        messages = self.manager_agent.build_messages(idea)

        self.spec_display.setPlainText("Analyzing...")
        self.analyze_btn.setEnabled(False)
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.pending_spec = None

        if not self.authorize(idea):
            # Analyze was disabled above; a blocked request has to put it back
            # or the panel is stuck with a dead button and "Analyzing..." on
            # screen for a request that was never sent.
            self.spec_display.setPlainText("[Blocked] The request was not sent.")
            self.analyze_btn.setEnabled(True)
            return

        self.start_worker(
            messages, idea,
            on_finished=self._on_finished,
            on_error=self._on_error,
        )

    def _on_finished(self, response: str) -> None:
        self.record(response)
        self.analyze_btn.setEnabled(True)
        spec = self.manager_agent.parse_spec(response)
        if spec is None:
            self.spec_display.setPlainText(
                "[Error] Could not parse a valid JSON spec from the response.\n\n"
                "Raw response:\n" + response
            )
            return

        self.pending_spec = spec
        self.spec_display.setPlainText(json.dumps(spec, indent=2))
        self.approve_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)
        self.log.append("[Ready] Spec generated. Review and approve or reject.")

    def _on_error(self, error: str) -> None:
        self.abandon()
        self.analyze_btn.setEnabled(True)
        self.spec_display.setPlainText(f"[Error]\n{error}")
        self.log.append(f"[Error] {error}")

    def stop(self) -> None:
        """The window's Stop button. Forge has no Stop of its own.

        Before the move it was not reachable from `stop_current_task` at all, so
        an analysis could only be waited out; leaving Analyze disabled after a
        cancel would strand the panel.
        """
        if self.stop_worker():
            self.log.append("[Stopped] Analysis cancelled.")
        self.analyze_btn.setEnabled(True)

    # ── The spec ────────────────────────────────────────────────────────
    def approve_spec(self) -> None:
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

        report = self.host.agent_factory.create_agent(self.pending_spec)

        if report["success"]:
            self.log.append(f"\n[Created] Agent '{name}' created successfully.")
            for f in report["files_created"]:
                self.log.append(f"  ✓ {f}")
            self.log.append("\n[Info] Restart the app to activate the new agent.")
            self.approve_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.pending_spec = None
            QMessageBox.information(
                self,
                "Agent Created",
                f"Agent '{label}' created successfully.\n\n"
                f"Restart the app to activate it.",
            )
        else:
            errors = "\n".join(report["errors"])
            self.log.append(f"\n[Failed] Could not create agent:\n{errors}")
            QMessageBox.warning(self, "Creation Failed", errors)

    def reject_spec(self) -> None:
        self.pending_spec = None
        self.spec_display.setPlainText("")
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.log.append("[Rejected] Spec cleared. You can describe a new idea.")

    def clear(self) -> None:
        self.idea_input.clear()
        self.spec_display.clear()
        self.pending_spec = None
        self.approve_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.log.append("[Cleared]")
