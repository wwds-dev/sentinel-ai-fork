"""Bloodhound — deep investigation, dossier, and image OSINT.

Fourth vertical moved out of `main.py` (phase 4, `docs/refactor_plan.md`).

The EXIF helpers moved as module-level functions rather than methods: they read
a file and return text, touch no widget and no host, and as functions they can
be tested against a real JPEG without building a panel at all.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from services.runtime_paths import user_data_base
from ui.panels.base import AgentPanel
from ui.widgets import MenuComboBox, SectionView


# ── EXIF, as plain functions ────────────────────────────────────────────────

def extract_exif(path: str) -> dict:
    """Every EXIF tag we can read, or {} — a stripped image is not an error."""
    try:
        from PIL import Image as PILImage
        from PIL.ExifTags import TAGS, GPSTAGS
        img = PILImage.open(path)
        raw = img._getexif()
        if not raw:
            return {}
        result = {}
        for tag_id, value in raw.items():
            tag = TAGS.get(tag_id, str(tag_id))
            if tag == "GPSInfo" and isinstance(value, dict):
                result["GPSInfo"] = {GPSTAGS.get(k, k): v for k, v in value.items()}
            elif isinstance(value, (str, int, float, bytes)):
                result[tag] = value
        return result
    except Exception:
        return {}


def gps_to_decimal(dms, ref: str) -> float:
    """Degrees/minutes/seconds → signed decimal degrees. 0.0 when unreadable."""
    try:
        d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
        decimal = d + m / 60 + s / 3600
        return round(-decimal if ref in ("S", "W") else decimal, 6)
    except Exception:
        return 0.0


def exif_summary(path: str) -> str:
    """One line for the panel: date, device, software, coordinates."""
    exif = extract_exif(path)
    if not exif:
        return "No EXIF data found in this image."
    parts = []
    for key in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
        if key in exif:
            parts.append(f"Date: {exif[key]}")
            break
    device = (str(exif.get("Make", "")) + " " + str(exif.get("Model", ""))).strip()
    if device:
        parts.append(f"Device: {device}")
    if exif.get("Software"):
        parts.append(f"Software: {str(exif['Software'])[:40]}")
    gps = exif.get("GPSInfo", {})
    if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
        lat = gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
        lon = gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        parts.append(f"GPS: {lat}°, {lon}°")
    return "  ·  ".join(parts) if parts else "EXIF present but no key fields extracted."


def exif_for_prompt(path: str) -> str:
    """The same metadata, written for the model rather than the status line."""
    exif = extract_exif(path)
    if not exif:
        return "No EXIF metadata could be extracted (data may have been stripped)."
    lines = [f"Image file: {Path(path).name}"]
    for key in ("DateTimeOriginal", "DateTime", "Make", "Model", "Software",
                "LensMake", "LensModel", "ImageWidth", "ImageLength",
                "Orientation", "Flash", "FocalLength"):
        if key in exif:
            lines.append(f"  {key}: {exif[key]}")
    gps = exif.get("GPSInfo", {})
    if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
        lat = gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
        lon = gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        lines.append(f"  GPS Coordinates: {lat}, {lon}")
        lines.append(f"  Google Maps link: https://maps.google.com/?q={lat},{lon}")
        if gps.get("GPSAltitude"):
            lines.append(f"  GPS Altitude: {gps['GPSAltitude']} m")
        if gps.get("GPSImgDirection"):
            lines.append(f"  Camera direction: {gps['GPSImgDirection']} degrees")
    return "\n".join(lines)


class OsintHeavyPanel(AgentPanel):
    """Investigate one target in depth and produce a dossier."""

    agent_key = "osint_heavy"

    def __init__(self, host, parent=None):
        super().__init__(host, parent)
        self.setObjectName("OSINTHeavyPanel")
        self._last_response = ""
        self._image_path = ""
        self._image_osint = ""
        self._build()
        self.polish_workspace()
        self.hide()

    # ── Construction ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ── Investigation Brief ──────────────────────────────────────────
        brief_group = QGroupBox("Investigation Brief")
        brief_group.setObjectName("OSINTHeavyBriefBox")
        brief_layout = QGridLayout(brief_group)
        brief_layout.setSpacing(6)

        brief_layout.addWidget(QLabel("Target:"), 0, 0)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText(
            "Name, username, email, domain, IP, phone number, or organisation…"
        )
        brief_layout.addWidget(self.target_input, 0, 1, 1, 3)

        brief_layout.addWidget(QLabel("Target Type:"), 1, 0)
        self.type_box = MenuComboBox()
        self.type_box.addItems([
            "Person", "Username", "Email Address", "Domain / IP",
            "Organisation", "Phone Number", "Auto-detect",
        ])
        brief_layout.addWidget(self.type_box, 1, 1)

        brief_layout.addWidget(QLabel("Scope:"), 1, 2)
        self.scope_box = MenuComboBox()
        self.scope_box.addItems(["Quick Scan", "Standard Investigation", "Deep Dive"])
        self.scope_box.setCurrentText("Standard Investigation")
        brief_layout.addWidget(self.scope_box, 1, 3)

        brief_layout.addWidget(QLabel("Objective:"), 2, 0)
        self.objective_input = QTextEdit()
        self.objective_input.setPlaceholderText(
            "What are you trying to establish? e.g. verify identity, map infrastructure, "
            "check breach exposure, assess threat level…"
        )
        self.objective_input.setMinimumHeight(70)
        self.objective_input.setMaximumHeight(120)
        brief_layout.addWidget(self.objective_input, 2, 1, 1, 3)

        self.investigate_btn = QPushButton("Investigate")
        self.investigate_btn.setMinimumWidth(140)
        self.investigate_btn.setObjectName("PrimaryAction")
        self.investigate_btn.clicked.connect(self.investigate)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setObjectName("DangerAction")
        self.stop_btn.clicked.connect(self.stop)
        self.set_busy(self.investigate_btn, self.stop_btn, False)

        provider_row_container = self.build_run_bar(
            self.investigate_btn,
            stop=self.stop_btn,
            context="Investigation",
        )

        brief_layout.addWidget(provider_row_container, 3, 0, 1, 4)
        layout.addWidget(brief_group)

        # ── Target Image (optional) ──────────────────────────────────────
        image_group = QGroupBox(
            "Target Image  —  optional, enables EXIF analysis && face search links")
        image_group.setObjectName("OSINTHeavyImageBox")
        image_outer = QVBoxLayout(image_group)
        image_outer.setSpacing(4)
        image_outer.setContentsMargins(6, 4, 6, 4)
        image_top_row = QHBoxLayout()
        self.image_label = QLabel("No image selected")
        self.image_label.setStyleSheet("color: #666; font-style: italic;")
        self.image_label.setMinimumWidth(200)
        image_top_row.addWidget(self.image_label, 1)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setMinimumWidth(100)
        self.browse_btn.setMaximumWidth(120)
        self.browse_btn.clicked.connect(self.browse_image)
        image_top_row.addWidget(self.browse_btn)
        self.clear_image_btn = QPushButton("Clear Image")
        self.clear_image_btn.setMinimumWidth(110)
        self.clear_image_btn.setMaximumWidth(130)
        self.clear_image_btn.clicked.connect(self.clear_image)
        image_top_row.addWidget(self.clear_image_btn)
        image_outer.addLayout(image_top_row)
        self.exif_display = QTextEdit()
        self.exif_display.setReadOnly(True)
        self.exif_display.setMinimumHeight(56)
        self.exif_display.setMaximumHeight(90)
        self.exif_display.setPlaceholderText(
            "EXIF metadata will appear here after selecting an image…"
        )
        self.exif_display.setStyleSheet(
            "font-family: monospace; font-size: 11px; color: #aaa;"
        )
        image_outer.addWidget(self.exif_display)
        layout.addWidget(image_group)

        # ── Results splitter: tabs left, indicators right ────────────────
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

        # ── Indicators sidebar ───────────────────────────────────────────
        indicators_widget = QWidget()
        indicators_layout = QVBoxLayout(indicators_widget)
        indicators_layout.setContentsMargins(8, 0, 0, 0)
        indicators_layout.setSpacing(10)

        threat_group = QGroupBox("Threat Level")
        threat_group.setObjectName("OSINTHeavyThreatBox")
        threat_layout = QVBoxLayout(threat_group)
        self.threat_bar = QProgressBar()
        self.threat_bar.setRange(0, 10)
        self.threat_bar.setValue(0)
        self.threat_bar.setTextVisible(False)
        self.threat_bar.setFixedHeight(16)
        self.threat_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: #cc2200; }"
        )
        threat_layout.addWidget(self.threat_bar)
        self.threat_label = QLabel("—")
        self.threat_label.setAlignment(Qt.AlignCenter)
        threat_layout.addWidget(self.threat_label)
        indicators_layout.addWidget(threat_group)

        conf_group = QGroupBox("Confidence")
        conf_group.setObjectName("OSINTHeavyConfBox")
        conf_layout = QVBoxLayout(conf_group)
        self.conf_label = QLabel("—")
        self.conf_label.setAlignment(Qt.AlignCenter)
        self.conf_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #dd88ff;")
        conf_layout.addWidget(self.conf_label)
        indicators_layout.addWidget(conf_group)

        sources_group = QGroupBox("Sources")
        sources_group.setObjectName("OSINTHeavySourcesBox")
        sources_layout = QVBoxLayout(sources_group)
        self.sources_label = QLabel("—")
        self.sources_label.setAlignment(Qt.AlignCenter)
        self.sources_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #4db8ff;")
        sources_layout.addWidget(self.sources_label)
        indicators_layout.addWidget(sources_group)

        depth_group = QGroupBox("Depth")
        depth_group.setObjectName("OSINTHeavyDepthBox")
        depth_layout = QVBoxLayout(depth_group)
        self.depth_label = QLabel("—")
        self.depth_label.setAlignment(Qt.AlignCenter)
        self.depth_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #aaaaff;")
        depth_layout.addWidget(self.depth_label)
        indicators_layout.addWidget(depth_group)

        indicators_layout.addStretch()

        self.save_btn = QPushButton("Save Report")
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

    # ── Running ─────────────────────────────────────────────────────────
    def investigate(self) -> None:
        target = self.target_input.text().strip()
        target_type = self.type_box.currentText()
        scope = self.scope_box.currentText()
        objective = self.objective_input.toPlainText().strip()

        if not target:
            QMessageBox.warning(self, "Missing Input", "Please enter a target identifier.")
            return
        if not self.model:
            QMessageBox.warning(self, "No Model", "Please select a model.")
            return

        image_metadata = ""
        if self._image_path:
            image_metadata = exif_for_prompt(self._image_path)

        messages = self.agent().build_messages(
            target, target_type, scope, objective, image_metadata)

        self._clear_displays()
        self._last_response = ""
        self.depth_label.setText(scope)
        self.status_label.setText("Investigating…")
        self.set_busy(self.investigate_btn, self.stop_btn, True)
        self.save_btn.setEnabled(False)

        if not self.authorize(target):
            # Investigate was disabled above; put it back or a refused request
            # leaves the panel dead.
            self.status_label.setText("Blocked before sending.")
            self.set_busy(self.investigate_btn, self.stop_btn, False)
            return

        self.start_worker(
            messages, target,
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
        self.status_label.setText("Investigation complete.")
        self.set_busy(self.investigate_btn, self.stop_btn, False)
        self.save_btn.setEnabled(True)

    def _on_error(self, error: str) -> None:
        self.abandon()
        self.sections.setVisible(False)
        self.stream_box.setVisible(True)
        self.stream_box.setPlainText(f"[Error] {error}")
        self.status_label.setText("Error.")
        self.set_busy(self.investigate_btn, self.stop_btn, False)

    def stop(self) -> None:
        self.stop_worker()
        self.status_label.setText("Stopped.")
        self.set_busy(self.investigate_btn, self.stop_btn, False)

    # ── The dossier ─────────────────────────────────────────────────────
    def save(self) -> None:
        if not self._last_response:
            return
        target = (self.target_input.text().strip()
                  .replace(" ", "_").replace("/", "-")) or "target"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"osint_dossier_{target}_{ts}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save OSINT Dossier",
            str(user_data_base() / "data" / default_name),
            "Text files (*.txt);;All files (*)",
        )
        if path:
            Path(path).write_text(self._last_response, encoding="utf-8")
            self.status_label.setText(f"Saved to {Path(path).name}")

    def clear(self) -> None:
        self._clear_displays()
        self.target_input.clear()
        self.objective_input.clear()
        self.status_label.setText("")
        self._last_response = ""
        self.clear_image()

    def _clear_displays(self) -> None:
        self.sections.clear()
        self.stream_box.clear()
        self.stream_box.setVisible(False)
        self.sections.setVisible(True)
        if self._image_osint:
            self._populate_sections("")
        self.threat_bar.setValue(0)
        self.threat_label.setText("—")
        self.conf_label.setText("—")
        self.sources_label.setText("—")
        self.depth_label.setText("—")
        self.save_btn.setEnabled(False)

    def _populate_sections(self, text: str) -> None:
        sections = self.parse_sections(text)
        cards = [
            ("Overview", sections.get("overview", "")),
            ("Digital footprint", sections.get("footprint", "")),
            ("Infrastructure / social profile", sections.get("infra", "")),
            ("Risk and red flags", sections.get("risk", "")),
            ("Methodology and tools", sections.get("methodology", "")),
        ]
        if self._image_osint:
            cards.append(("Image OSINT", self._image_osint))
        self.sections.show_sections(cards, raw=text)

    @staticmethod
    def parse_sections(text: str) -> dict:
        """Split the dossier on its five numbered headings."""
        patterns = {
            "overview":    r"##\s*1\.\s*OVERVIEW(.*?)(?=##\s*2\.|$)",
            "footprint":   r"##\s*2\.\s*DIGITAL FOOTPRINT(.*?)(?=##\s*3\.|$)",
            "infra":       r"##\s*3\.\s*INFRASTRUCTURE.*?(.*?)(?=##\s*4\.|$)",
            "risk":        r"##\s*4\.\s*RISK.*?(.*?)(?=##\s*5\.|$)",
            "methodology": r"##\s*5\.\s*METHODOLOGY.*?(.*?)$",
        }
        result = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            result[key] = m.group(1).strip() if m else ""
        return result

    def _update_indicators(self, text: str) -> None:
        threat_m = re.search(r"THREAT LEVEL[:\s]+(\d+)\s*/\s*10", text, re.IGNORECASE)
        if threat_m:
            level = int(threat_m.group(1))
            self.threat_bar.setValue(min(level, 10))
            self.threat_label.setText(f"{level}/10")

        conf_m = re.search(r"CONFIDENCE[:\s]+(\d+)\s*%", text, re.IGNORECASE)
        if conf_m:
            self.conf_label.setText(f"{conf_m.group(1)}%")

        sources_m = re.search(r"SOURCES REFERENCED[:\s]+(\d+)", text, re.IGNORECASE)
        if sources_m:
            self.sources_label.setText(sources_m.group(1))

    # ── Image OSINT ─────────────────────────────────────────────────────
    def browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Target Image", str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp *.heic);;All files (*)"
        )
        if not path:
            return
        self.set_image(path)

    def set_image(self, path: str) -> None:
        """Attach an image: its EXIF joins the prompt and fills the Image tab."""
        self._image_path = path
        self.image_label.setText(Path(path).name)
        self.image_label.setStyleSheet("color: #dd88ff; font-style: normal;")
        self.exif_display.setPlainText(exif_summary(path))
        self._populate_image_tab(path)

    def clear_image(self) -> None:
        self._image_path = ""
        self.image_label.setText("No image selected")
        self.image_label.setStyleSheet("color: #666; font-style: italic;")
        self.exif_display.clear()
        self.image_tab.clear()

    def _populate_image_tab(self, path: str) -> None:
        exif = extract_exif(path)
        fname = Path(path).name
        gps_block = ""
        gps = exif.get("GPSInfo", {})
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = gps_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
            lon = gps_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
            gps_block = (
                f'<h3 style="color:#f0c040;">GPS Coordinates Extracted</h3>'
                f"<p><b>Coordinates:</b> {lat}, {lon}</p>"
                f'<p><a href="https://maps.google.com/?q={lat},{lon}">Google Maps</a>'
                f' &nbsp;|&nbsp; <a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15">OpenStreetMap</a>'
                f' &nbsp;|&nbsp; <a href="https://suncalc.org/#/{lat},{lon},14/">SunCalc</a></p>'
            )
        exif_rows = ""
        for key in ("DateTimeOriginal", "DateTime", "DateTimeDigitized",
                    "Make", "Model", "Software", "LensMake", "LensModel",
                    "ImageWidth", "ImageLength", "Orientation", "Flash", "FocalLength"):
            if key in exif:
                exif_rows += (f"<tr><td style='color:#888;padding-right:14px;'>{key}</td>"
                              f"<td>{exif[key]}</td></tr>")
        no_exif = (
            "<p style='color:#ff8888;'>No EXIF data found — the image may have been stripped "
            "(common with screenshots, social media downloads, and edited files). "
            "This itself can be a signal.</p>"
            if not exif else ""
        )
        html = (
            "<html><body style='font-family:monospace;font-size:12px;color:#ccc;background:#1a1a1a;padding:8px;'>"
            f"<h2 style='color:#dd88ff;'>Image OSINT &mdash; {fname}</h2>"
            f"{no_exif}{gps_block}"
            "<h3 style='color:#4db8ff;'>Reverse Image Search</h3>"
            "<p style='color:#aaa;'>Upload the image at each service to search for matches:</p><ul>"
            "<li><a href='https://tineye.com'>TinEye</a> &mdash; reverse image search with date history</li>"
            "<li><a href='https://images.google.com'>Google Images</a> &mdash; click the camera icon to upload</li>"
            "<li><a href='https://yandex.com/images'>Yandex Images</a> &mdash; strong face/person matching</li>"
            "<li><a href='https://www.bing.com/visualsearch'>Bing Visual Search</a> &mdash; Microsoft image search</li>"
            "</ul>"
            "<h3 style='color:#ff88aa;'>Face Recognition Services</h3>"
            "<p style='color:#aaa;'>Upload the image to search for the person across the public web:</p><ul>"
            "<li><a href='https://pimeyes.com'>PimEyes</a> &mdash; facial recognition across billions of public images</li>"
            "<li><a href='https://facecheck.id'>FaceCheck.ID</a> &mdash; face search across social media profiles</li>"
            "<li><a href='https://lenso.ai'>Lenso.ai</a> &mdash; AI-powered reverse image and face search</li>"
            "</ul>"
            "<h3 style='color:#3cff88;'>Extracted EXIF Metadata</h3>"
            + ("<table>" + exif_rows + "</table>" if exif_rows
               else "<p style='color:#888;'>No key EXIF fields found.</p>")
            + "<br><p style='color:#555;font-size:11px;'>For authorised investigative use only.</p>"
            "</body></html>"
        )
        self.image_tab.setHtml(html)
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.image_tab))
