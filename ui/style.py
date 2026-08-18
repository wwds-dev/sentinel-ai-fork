"""The application stylesheet.

Moved verbatim out of main.py (see docs/refactor_plan.md, phase 1). It is a
single Qt style sheet string with no application state in it.
"""

# ── VPN-Agent-inspired design system ─────────────────────────────
# Palette: #0f0f0f page · #181818 card · #161616 input · #262626 border
# Accent: #3cff88 (Sentinel green) for active/focused/title states
# Semantic: green (success) / red (danger) for primary actions

GLOBAL_STYLESHEET = """
/* Type scale — four steps, two weights. 10/11/12/13px were four sizes that
   read as one, which is why nothing looked more important than anything else.
     display 22px/500   agent title
     title   15px/500   card and section headings (used by the section renderer)
     body    13px/400   controls, labels, prose
     caption 11px/400   eyebrow labels, units, metadata
   Do not add a fifth size. */
        QWidget {
            background-color: #0f0f0f;
            color: #d8d8d8;
            font-size: 13px;
        }

        /* ── Inputs ────────────────────────────────────────────────── */
        QTextEdit, QTextBrowser, QListWidget {
            background-color: #161616;
            color: #e8e8e8;
            border: 1px solid #262626;
            border-radius: 8px;
            padding: 8px 10px;
            selection-background-color: rgba(60, 255, 136, 0.25);
            selection-color: #ffffff;
        }
        QLineEdit, QComboBox {
            background-color: #161616;
            color: #e8e8e8;
            border: 1px solid #262626;
            border-radius: 8px;
            padding: 4px 10px;
            min-height: 22px;
            selection-background-color: rgba(60, 255, 136, 0.25);
            selection-color: #ffffff;
        }
        QTextEdit:focus, QTextBrowser:focus, QLineEdit:focus, QComboBox:focus {
            border: 1px solid #3cff88;
        }
        QComboBox::drop-down {
            border: none;
            width: 22px;
        }
        QComboBox QAbstractItemView {
            background-color: #181818;
            border: 1px solid #262626;
            border-radius: 6px;
            selection-background-color: rgba(60, 255, 136, 0.15);
            selection-color: #3cff88;
            outline: none;
            padding: 4px;
        }

        /* ── Buttons (default — neutral) ───────────────────────────── */
        QPushButton {
            background-color: #1a1a1a;
            color: #d0d0d0;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
            padding: 9px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #232323;
            border: 1px solid #3a3a3a;
            color: #ffffff;
        }
        QPushButton:pressed {
            background-color: #0f0f0f;
        }
        QPushButton:checked {
            background-color: rgba(60, 255, 136, 0.10);
            border: 1px solid #3cff88;
            color: #3cff88;
        }
        QPushButton:disabled {
            color: #555555;
            background-color: #161616;
            border: 1px solid #1f1f1f;
        }

        /* ── Group boxes (card style with label above) ─────────────── */
        QGroupBox {
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 10px;
            margin-top: 18px;
            padding: 14px 12px 10px 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 4px;
            top: 0px;
            padding: 0 6px;
            color: #707070;
            background-color: transparent;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 2px;
        }

        /* ── Tabs ──────────────────────────────────────────────────── */
        QTabWidget::pane {
            background-color: #161616;
            border: 1px solid #242424;
            border-radius: 8px;
            top: -1px;
        }
        QTabBar {
            background-color: transparent;
        }
        QTabBar::tab {
            background-color: transparent;
            color: #707070;
            padding: 7px 12px;
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
            font-weight: 500;
        }
        QTabBar::tab:hover {
            color: #cccccc;
        }
        QTabBar::tab:selected {
            color: #3cff88;
            border-bottom: 2px solid #3cff88;
        }

        /* ── Checkboxes ────────────────────────────────────────────── */
        QCheckBox {
            color: #c0c0c0;
            spacing: 8px;        /* indicator → its own label */
            /* Trailing room so a checkbox's label never butts straight into the
               next widget (another checkbox's indicator, or a button). Must be
               padding, not margin: Qt ignores margin here, and the macOS style
               eats ~11px of any layout spacing we'd set instead. Global, so
               every agent tab gets it. */
            padding-right: 14px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid #2a2a2a;
            background-color: #161616;
        }
        QCheckBox::indicator:hover {
            border: 1px solid #4a4a4a;
        }
        QCheckBox::indicator:checked {
            background-color: #3cff88;
            border: 1px solid #3cff88;
        }

        /* ── Progress bars ─────────────────────────────────────────── */
        QProgressBar {
            background-color: #161616;
            border: 1px solid #262626;
            border-radius: 6px;
            text-align: center;
            color: #cccccc;
            height: 10px;
        }
        QProgressBar::chunk {
            background-color: #3cff88;
            border-radius: 4px;
        }

        /* ── Scrollbars ────────────────────────────────────────────── */
        QScrollBar:vertical {
            background-color: transparent;
            width: 8px;
            border: none;
            margin: 4px 2px;
        }
        QScrollBar::handle:vertical {
            background-color: #2a2a2a;
            border-radius: 4px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #444;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar:horizontal {
            background-color: transparent;
            height: 8px;
            border: none;
            margin: 2px 4px;
        }
        QScrollBar::handle:horizontal {
            background-color: #2a2a2a;
            border-radius: 4px;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #444;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0;
        }

        /* ── Labels ────────────────────────────────────────────────── */
        QLabel {
            color: #c8c8c8;
            background: transparent;
        }

        /* ── Tooltips ──────────────────────────────────────────────── */
        QToolTip {
            background-color: #161616;
            color: #e8e8e8;
            border: 1px solid #3cff88;
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 13px;
        }

        /* ── Sentinel agent title (big accent text) ───────────────── */
        QLabel#AgentTitle {
            color: #3cff88;
            font-size: 22px;
            font-weight: 500;
            letter-spacing: 3px;
            background: transparent;
        }

        /* ── Agent subtitle (one-line function description) ─────── */
        QLabel#AgentSubtitle {
            color: #888888;
            font-size: 13px;
            font-weight: 400;
            background: transparent;
            padding: 0 0 4px 1px;
        }

        /* ── Status pill (top-right) ──────────────────────────────── */
        QLabel#StatusPill {
            background-color: #161616;
            border: 1px solid #262626;
            border-radius: 12px;
            padding: 4px 12px;
            color: #3cff88;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1px;
        }

        /* ── Small "chip" buttons (Docs, Model Guide etc.) ────────── */
        QPushButton#ChipBtn {
            background-color: #161616;
            border: 1px solid #262626;
            border-radius: 12px;
            padding: 4px 12px;
            color: #aaaaaa;
            font-size: 11px;
            font-weight: 500;
        }
        QPushButton#ChipBtn:hover {
            border: 1px solid #3cff88;
            color: #3cff88;
        }

        /* ── Primary action (Send / Analyse / Generate) ──────────── */
        QPushButton#PrimaryAction {
            background-color: rgba(60, 255, 136, 0.10);
            border: 1px solid #3cff88;
            border-radius: 8px;
            padding: 7px 14px;
            color: #3cff88;
            font-weight: 500;
            font-size: 13px;
            min-height: 18px;
            min-width: 110px;
        }
        QPushButton#PrimaryAction:hover {
            background-color: rgba(60, 255, 136, 0.18);
            color: #ffffff;
        }
        QPushButton#PrimaryAction:pressed {
            background-color: rgba(60, 255, 136, 0.30);
        }
        QPushButton#PrimaryAction:disabled {
            color: #4a4a4a;
            border: 1px solid #2a2a2a;
            background-color: #161616;
        }

        /* ── Danger action (Stop / Disconnect) ────────────────────── */
        QPushButton#DangerAction {
            background-color: rgba(255, 85, 85, 0.10);
            border: 1px solid #ff5555;
            border-radius: 8px;
            padding: 7px 14px;
            color: #ff7070;
            font-weight: 500;
            font-size: 13px;
            min-height: 18px;
            min-width: 80px;
        }
        QPushButton#DangerAction:hover {
            background-color: rgba(255, 85, 85, 0.18);
            color: #ffffff;
        }
        QPushButton#DangerAction:disabled {
            color: #4a4a4a;
            border: 1px solid #2a2a2a;
            background-color: #161616;
        }
"""
