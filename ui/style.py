"""The application stylesheet.

Moved verbatim out of main.py (see docs/refactor_plan.md, phase 1). It is a
single Qt style sheet string with no application state in it.
"""

# ── VPN-Agent-inspired design system ─────────────────────────────
# Palette: #0d0f0e page · #151816 card · #151816 input · #262d29 border
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
            background-color: #0d0f0e;
            color: #e8ece9;
            font-size: 13px;
        }

        /* ── Inputs ────────────────────────────────────────────────── */
        QTextEdit, QTextBrowser, QListWidget {
            background-color: #151816;
            color: #e8ece9;
            border: 1px solid #262d29;
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: rgba(60, 255, 136, 0.25);
            selection-color: #ffffff;
        }
        QLineEdit, QComboBox {
            background-color: #151816;
            color: #e8ece9;
            border: 1px solid #262d29;
            border-radius: 8px;
            padding: 3px 9px;
            min-height: 20px;
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
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 6px;
            selection-background-color: rgba(60, 255, 136, 0.15);
            selection-color: #3cff88;
            outline: none;
            padding: 4px;
        }

        /* ── Buttons (default — neutral) ───────────────────────────── */
        QPushButton {
            background-color: #151816;
            color: #a8b3ad;
            border: 1px solid #2f3733;
            border-radius: 8px;
            padding: 7px 13px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #1b201d;
            border: 1px solid #3d4842;
            color: #ffffff;
        }
        QPushButton:pressed {
            background-color: #0d0f0e;
        }
        QPushButton:checked {
            background-color: rgba(60, 255, 136, 0.10);
            border: 1px solid #3cff88;
            color: #3cff88;
        }
        QPushButton:disabled {
            color: #4a5450;
            background-color: #151816;
            border: 1px solid #141715;
        }

        /* ── Group boxes (card style with label above) ─────────────── */
        QGroupBox {
            background-color: #151816;
            border: 1px solid #262d29;
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
            color: #5d6862;
            background-color: transparent;
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 2px;
        }

        /* ── Tabs ──────────────────────────────────────────────────── */
        QTabWidget::pane {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
            top: -1px;
        }
        QTabBar {
            background-color: transparent;
        }
        QTabBar::tab {
            background-color: transparent;
            color: #5d6862;
            padding: 7px 12px;
            border: none;
            border-bottom: 2px solid transparent;
            font-size: 13px;
            font-weight: 500;
        }
        QTabBar::tab:hover {
            color: #a8b3ad;
        }
        QTabBar::tab:selected {
            color: #3cff88;
            border-bottom: 2px solid #3cff88;
        }

        /* ── Checkboxes ────────────────────────────────────────────── */
        QCheckBox {
            color: #a8b3ad;
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
            border-radius: 6px;
            border: 1px solid #2f3733;
            background-color: #151816;
        }
        QCheckBox::indicator:hover {
            border: 1px solid #3d4842;
        }
        QCheckBox::indicator:checked {
            background-color: #3cff88;
            border: 1px solid #3cff88;
        }

        /* ── Progress bars ─────────────────────────────────────────── */
        QProgressBar {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 6px;
            text-align: center;
            color: #a8b3ad;
            height: 10px;
        }
        QProgressBar::chunk {
            background-color: #3cff88;
            border-radius: 6px;
        }

        /* ── Scrollbars ────────────────────────────────────────────── */
        QScrollBar:vertical {
            background-color: transparent;
            width: 8px;
            border: none;
            margin: 4px 2px;
        }
        QScrollBar::handle:vertical {
            background-color: #2f3733;
            border-radius: 6px;
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
            background-color: #2f3733;
            border-radius: 6px;
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
            color: #a8b3ad;
            background: transparent;
        }

        /* ── Tooltips ──────────────────────────────────────────────── */
        QToolTip {
            background-color: #151816;
            color: #e8ece9;
            border: 1px solid #3cff88;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 13px;
        }

        /* ── Sentinel agent title (big accent text) ───────────────── */
        QLabel#AgentTitle {
            color: #e8ece9;
            font-size: 24px;
            font-weight: 600;
            letter-spacing: -0.3px;
            background: transparent;
        }

        /* ── Agent subtitle (one-line function description) ─────── */
        QLabel#AgentSubtitle {
            color: #7d8983;
            font-size: 12px;
            font-weight: 400;
            background: transparent;
            padding: 0 0 4px 1px;
        }

        /* ── Status pill (top-right) ──────────────────────────────── */
        QLabel#StatusPill { /* pill */
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
            padding: 4px 12px;
            color: #3cff88;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1px;
        }

        /* ── Small "chip" buttons (Docs, Model Guide etc.) ────────── */
        QPushButton#ChipBtn {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
            padding: 4px 12px;
            color: #7d8983;
            font-size: 11px;
            font-weight: 500;
        }
        QPushButton#ChipBtn:hover {
            border: 1px solid #3cff88;
            color: #3cff88;
        }
        QLabel#DocsMatchLabel {
            color: #7d8983;
            font-size: 13px;
            min-width: 72px;
        }
        QScrollArea#AgentWorkspaceScroll {
            background-color: transparent;
            border: none;
        }

        /* ── Primary action (Send / Analyse / Generate) ──────────── */
        QPushButton#PrimaryAction {
            background-color: #3cff88;
            border: none;
            border-radius: 8px;
            padding: 9px 18px;
            color: #06301a;
            font-weight: 600;
            font-size: 13px;
            min-height: 18px;
            min-width: 110px;
        }
        QPushButton#PrimaryAction:hover {
            background-color: #5cffa0;
            color: #06301a;
        }
        QPushButton#PrimaryAction:pressed {
            background-color: rgba(60, 255, 136, 0.30);
        }
        QPushButton#PrimaryAction:disabled {
            color: #4a5450;
            border: none;
            background-color: #1f4a33;
        }

        QWidget[agentWorkspace="true"] { background-color: transparent; }
        QGroupBox[workspaceCard="true"] {
            background-color: #121614;
            border: 1px solid #232a26;
            border-radius: 10px;
            margin-top: 16px;
            padding: 14px 12px 11px 12px;
        }
        QGroupBox[workspaceCard="true"]::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 8px;
            top: 2px;
            padding: 0 6px;
            background-color: #0d0f0e;
            color: #7d8983;
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 1.5px;
        }
        QTabWidget[workspaceResults="true"]::pane {
            background-color: #121614;
            border: 1px solid #232a26;
            border-radius: 10px;
            padding: 6px;
        }
        QTextBrowser[workspaceOutput="true"], QTextEdit[workspaceOutput="true"] {
            background-color: #121614;
            border: 1px solid #232a26;
            border-radius: 10px;
            padding: 10px;
        }
        QWidget#ProgressiveSection {
            background-color: #101311;
            border: 1px solid #232a26;
            border-radius: 10px;
        }
        QPushButton#ProgressiveHeader {
            text-align: left;
            background-color: transparent;
            border: none;
            border-radius: 9px;
            padding: 8px 10px;
            color: #7d8983;
            font-size: 12px;
            font-weight: 500;
        }
        QPushButton#ProgressiveHeader:hover {
            color: #3cff88;
            background-color: rgba(60, 255, 136, 0.04);
        }
        QWidget#ProgressiveBody {
            background-color: transparent;
            border-top: 1px solid #232a26;
        }
        QWidget#WorkspaceState {
            background-color: transparent;
            min-height: 28px;
        }
        QLabel#WorkspaceStateDot, QLabel#WorkspaceStateText {
            color: #7d8983;
            font-size: 12px;
        }
        QWidget#WorkspaceState[state="running"] QLabel { color: #3cff88; }
        QWidget#WorkspaceState[state="success"] QLabel { color: #74d99f; }
        QWidget#WorkspaceState[state="error"] QLabel { color: #f85149; }
        QWidget[workspaceResultSurface="true"] {
            background-color: transparent;
        }

        /* ── Danger action (Stop / Disconnect) ────────────────────── */
        QPushButton#DangerAction {
            background-color: rgba(255, 85, 85, 0.10);
            border: 1px solid #f85149;
            border-radius: 8px;
            padding: 7px 14px;
            color: #f85149;
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
            color: #3d4842;
            border: 1px solid #2f3733;
            background-color: #151816;
        }

        /* ── Run bar ──────────────────────────────────────────────────── */
        QWidget#RunBar {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
        }
        QLabel#RunBarCost {
            font-size: 11px;
            color: #7d8983;
            padding: 0 4px;
        }
        QLabel#ModelSummary {
            color: #7d8983;
            font-size: 13px;
            padding: 0 8px;
            background: transparent;
        }
        QWidget#RunBarPopover {
            background-color: #151816;
        }
        QLabel#PopoverHeading {
            font-size: 10px;
            color: #5d6862;
            letter-spacing: 1px;
        }

        /* ── Status meters ────────────────────────────────────────────── */
        QLabel#MeterCaption {
            color: #7d8983;
            font-size: 12px;
            letter-spacing: 0.5px;
        }
        QLabel#MeterValue {
            color: #e8ece9;
            font-size: 13px;
            font-weight: 500;
        }

        /* ── Section renderer ─────────────────────────────────────────── */
        QFrame#SectionCard {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 8px;
        }
        QLabel#SectionTitle {
            font-size: 16px;
            font-weight: 500;
            color: #e8ece9;
        }
        QLabel#SectionBody {
            font-size: 13px;
            color: #a8b3ad;
        }
        QLabel#SectionMono {
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
            color: #a8b3ad;
        }
        QLabel#SectionEmpty {
            font-size: 13px;
            color: #5d6862;
            padding: 18px 2px;
        }
        QPushButton#SectionCopy, QPushButton#RawToggle {
            background: transparent;
            border: none;
            color: #7d8983;
            font-size: 12px;
            padding: 2px 6px;
            text-align: left;
        }
        QPushButton#SectionCopy:hover, QPushButton#RawToggle:hover {
            color: #3cff88;
        }

        QLabel#RailHeading {
            color: #5d6862;
            font-size: 10px;
            font-weight: 500;
            letter-spacing: 2px;
            padding: 10px 0 6px 16px;
            background: transparent;
        }

        QPushButton#RailFooterToggle {
            text-align: left;
            background: transparent;
            border: none;
            border-top: 1px solid #262d29;
            border-radius: 0;
            color: #5d6862;
            font-size: 11px;
            padding: 10px 16px 8px 16px;
        }
        QPushButton#RailFooterToggle:hover,
        QPushButton#RailFooterToggle:checked {
            background: transparent;
            border-left: none;
            border-right: none;
            border-bottom: none;
            border-top: 1px solid #262d29;
            color: #a8b3ad;
        }

        QComboBox#ToolChip {
            background-color: rgba(60, 255, 136, 0.10);
            border: none;
            border-radius: 6px;
            color: #3cff88;
            font-size: 13px;
            font-weight: 500;
            padding: 5px 10px;
        }
        QComboBox#ToolChip::drop-down { border: none; width: 0px; }
        QComboBox#MachinePick {
            background-color: transparent;
            border: none;
            color: #a8b3ad;
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
            padding: 4px 2px;
        }
        QLabel#RunBarDot {
            color: #5d6862;
            font-size: 13px;
            background: transparent;
        }
        QPushButton#RunAction {
            background-color: #3cff88;
            border: none;
            border-radius: 6px;
            color: #06301a;
            font-size: 13px;
            font-weight: 600;
            padding: 6px 18px;
        }
        QPushButton#RunAction:hover { background-color: #5cffa0; }
        QPushButton#RunAction:disabled { background-color: #1f4a33; color: #4a5450; }

        QLabel#SectionBadge {
            background-color: rgba(60, 255, 136, 0.12);
            border-radius: 5px;
            color: #3cff88;
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
            letter-spacing: 1px;
            padding: 3px 8px;
        }

        QTextEdit#PromptInput {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
            color: #e8ece9;
            font-size: 13px;
            padding: 12px;
        }
        QTextEdit#PromptInput:focus { border: 1px solid #3d4842; }

        QGroupBox#RightCard {
            background: transparent;
            border: none;
            border-top: 1px solid #262d29;
            margin-top: 16px;
            padding: 11px 1px 3px 1px;
        }
        QGroupBox#RightCard::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 0px;
            top: 2px;
            padding: 0 6px 0 0;
            background: transparent;
            color: #5d6862;
            font-size: 10px;
            font-weight: 500;
            letter-spacing: 2px;
        }

        QLabel#KVKey {
            color: #7d8983;
            font-size: 12px;
        }
        QLabel#KVValue {
            color: #e8ece9;
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
        }

        QPushButton#RailLink {
            background: transparent;
            border: none;
            color: #7d8983;
            font-size: 12px;
            padding: 8px 0 2px 0;
            text-align: left;
        }
        QPushButton#RailLink:hover { color: #3cff88; }

        QLabel#KVValueOn {
            color: #3cff88;
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
        }
        QLabel#KVValueOff {
            color: #5d6862;
            font-family: Menlo, Monaco, monospace;
            font-size: 12px;
        }

        QTextEdit#OutputBox {
            background-color: #151816;
            border: 1px solid #262d29;
            border-radius: 10px;
            color: #a8b3ad;
            font-size: 13px;
            padding: 12px;
        }
        QPushButton#OutputToggle {
            text-align: left;
            background-color: #121614;
            border: 1px solid #262d29;
            border-radius: 8px;
            color: #5d6862;
            font-size: 12px;
            padding: 8px 12px;
        }
        QPushButton#OutputToggle:hover,
        QPushButton#OutputToggle:checked {
            background-color: #151816;
            border: 1px solid #2f3733;
            color: #a8b3ad;
        }
        QPushButton#StopAction {
            background: transparent;
            border: 1px solid #2f3733;
            border-radius: 6px;
            color: #a8b3ad;
            font-size: 12px;
            padding: 6px 14px;
        }
        QPushButton#StopAction:disabled { color: #4a5450; border-color: #262d29; }
        QPushButton#StopAction:hover:enabled { border-color: #f85149; color: #f85149; }
"""
