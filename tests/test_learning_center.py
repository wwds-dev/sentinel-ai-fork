from pathlib import Path
import re

from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser, QWidget

from ui.learning_center import (
    LEARNING_TOPICS,
    build_learning_center,
    load_learning_topic,
)


def test_every_learning_topic_exists_in_project_resources():
    root = Path(__file__).resolve().parents[1]
    for topic in LEARNING_TOPICS:
        text = load_learning_topic(root, topic)
        assert text.startswith("# ")
        assert "not available in the current installation" not in text
        assert len(text.split()) >= 100


def test_learning_topic_missing_resource_has_readable_fallback(tmp_path):
    text = load_learning_topic(tmp_path, LEARNING_TOPICS[0])
    assert LEARNING_TOPICS[0].title in text
    assert "not available" in text


def test_learning_topics_have_unique_titles_and_files():
    assert len({topic.title for topic in LEARNING_TOPICS}) == len(LEARNING_TOPICS)
    assert len({topic.filename for topic in LEARNING_TOPICS}) == len(LEARNING_TOPICS)


def test_release_bundle_includes_training_resources():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "Sentinel.spec").read_text(encoding="utf-8")
    assert '("docs/training", "docs/training")' in spec


def test_every_training_screenshot_reference_exists():
    root = Path(__file__).resolve().parents[1]
    training = root / "docs" / "training"
    references = []
    for source in training.glob("*.md"):
        references.extend(re.findall(r"!\[[^]]*]\(([^)]+)\)", source.read_text()))
    assert len(references) >= 8
    for reference in references:
        assert (root / reference).is_file(), reference


def test_learning_center_opens_with_first_lesson(monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    class Host(QWidget):
        @staticmethod
        def _wire_document_search(search, previous, next_button, label, browser):
            search.textChanged.connect(lambda text: label.setText(text))

    host = Host()
    dialog = build_learning_center(host)
    assert dialog.windowTitle() == "Sentinel Learning Centre"
    browser = dialog.findChild(QTextBrowser, "LearningBrowser")
    assert browser is not None
    assert "complete a safe first request" in browser.toPlainText()
