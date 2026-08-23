from pathlib import Path  # used for file paths
from datetime import datetime  # used for timestamped filenames
from uuid import uuid4
from services.runtime_paths import user_data_base


class ReportExporter:
    def __init__(self, folder: str | Path | None = None):
        self.folder = Path(folder) if folder is not None else user_data_base() / "data" / "reports"
        self.folder.mkdir(parents=True, exist_ok=True)  # create folder if missing

    def export_text_report(self, title: str, content: str) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        safe_title = title.strip().replace(" ", "_").replace("/", "_")  # make filename safer
        filename = f"{timestamp}_{uuid4().hex}_{safe_title}.txt"
        filepath = self.folder / filename  # full path to report

        with open(filepath, "x", encoding="utf-8") as f:
            f.write(content)  # write the report content into the file

        return filepath  # return saved file path
