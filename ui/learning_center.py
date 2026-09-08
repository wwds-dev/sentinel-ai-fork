"""Searchable, file-backed Learning Centre for Sentinel Fork."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import markdown
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from services.runtime_paths import resource_base


@dataclass(frozen=True)
class LearningTopic:
    title: str
    filename: str
    summary: str


LEARNING_TOPICS = (
    LearningTopic("Start here", "quick_start.md", "A guided first run through Sentinel."),
    LearningTopic("Workspace tour", "workspace.md", "Navigation, work area, history and Inspector."),
    LearningTopic("Controls & settings", "controls_settings.md", "Every shared control and setting."),
    LearningTopic("Portable USB mode", "portable.md", "Build, use, update and safely eject a portable copy."),
    LearningTopic("Chat essentials", "chat.md", "Conversation, routing, privacy and costs."),
    LearningTopic("Trace", "trace.md", "Public-source identity research and live sources."),
    LearningTopic("Bloodhound", "bloodhound.md", "Dossiers, images, and file discovery."),
    LearningTopic("Beacon", "beacon.md", "Authorised Wi-Fi diagnostics and lab workflows."),
    LearningTopic("Bug Spray", "bug_spray.md", "Authorised website assessment and reporting."),
    LearningTopic("Tunnel", "tunnel.md", "Personal VPN design and troubleshooting."),
    LearningTopic("Forge", "forge.md", "Create and review agent scaffolds."),
    LearningTopic("Agent workflows", "workflows.md", "Combine agents to complete larger goals."),
    LearningTopic("Privacy & cost", "privacy_cost.md", "Choose routes and protect sensitive data."),
    LearningTopic("Troubleshooting", "troubleshooting.md", "Resolve common setup and run problems."),
    LearningTopic("Advanced tools", "advanced_tools.md", "Safe next steps and the v3 Kali roadmap."),
)


def load_learning_topic(resource_root: Path, topic: LearningTopic) -> str:
    """Return topic Markdown, with a useful message when resources are missing."""
    path = resource_root / "docs" / "training" / topic.filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return (
            f"# {topic.title}\n\n"
            "This lesson is not available in the current installation. "
            "Update or reinstall Sentinel Fork to restore its training files."
        )


def build_learning_center(app) -> QDialog:
    resource_root = resource_base()
    dialog = QDialog(app)
    dialog.setWindowTitle("Sentinel Learning Centre")
    dialog.resize(1120, 760)

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(16, 16, 16, 16)
    outer.setSpacing(10)

    title = QLabel("Learning Centre")
    title.setObjectName("AgentTitle")
    outer.addWidget(title)
    outer.addWidget(QLabel("Short, practical lessons for using Sentinel safely and effectively."))

    search_row = QHBoxLayout()
    search_box = QLineEdit()
    search_box.setPlaceholderText("Search the current lesson…")
    search_box.setClearButtonEnabled(True)
    search_row.addWidget(search_box, 1)
    previous_btn = QPushButton("Previous")
    previous_btn.setObjectName("ChipBtn")
    next_btn = QPushButton("Next")
    next_btn.setObjectName("ChipBtn")
    match_label = QLabel("")
    match_label.setObjectName("DocsMatchLabel")
    search_row.addWidget(previous_btn)
    search_row.addWidget(next_btn)
    search_row.addWidget(match_label)
    outer.addLayout(search_row)

    body = QHBoxLayout()
    topic_list = QListWidget()
    topic_list.setObjectName("LearningTopicList")
    topic_list.setFixedWidth(245)
    for topic in LEARNING_TOPICS:
        item = QListWidgetItem(topic.title)
        item.setToolTip(topic.summary)
        topic_list.addItem(item)
    body.addWidget(topic_list)

    browser = QTextBrowser()
    browser.setObjectName("LearningBrowser")
    browser.setOpenExternalLinks(True)
    browser.setSearchPaths([str(resource_root / "docs" / "training")])
    browser.document().setBaseUrl(QUrl.fromLocalFile(str(resource_root) + "/"))
    browser.setStyleSheet(
        "QTextBrowser { background: #111111; color: #d5ddd8; border: 1px solid #242424; "
        "border-radius: 8px; font-size: 15px; padding: 14px; }"
    )
    body.addWidget(browser, 1)
    outer.addLayout(body, 1)

    def render_topic(row: int) -> None:
        if row < 0:
            return
        source = load_learning_topic(resource_root, LEARNING_TOPICS[row])
        browser.setHtml(markdown.markdown(source, extensions=["tables", "fenced_code"]))
        browser.moveCursor(QTextCursor.Start)
        search_box.clear()

    topic_list.currentRowChanged.connect(render_topic)
    app._wire_document_search(
        search_box, previous_btn, next_btn, match_label, browser
    )

    close_btn = QPushButton("Close")
    close_btn.setObjectName("ChipBtn")
    close_btn.clicked.connect(dialog.accept)
    close_btn.setFixedWidth(100)
    outer.addWidget(close_btn, 0, Qt.AlignRight)

    topic_list.setCurrentRow(0)
    return dialog


def show_learning_center(app) -> None:
    build_learning_center(app).exec()
