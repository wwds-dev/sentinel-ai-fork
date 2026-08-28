import json  # used for saving history as JSON
from pathlib import Path  # makes folder paths easier
from datetime import datetime  # used to generate timestamped filenames
from uuid import uuid4
from services.runtime_paths import user_data_base


class HistoryStore:
    def __init__(self, folder: str | Path | None = None):
        self.folder = Path(folder) if folder is not None else user_data_base() / "data" / "chats"
        self.folder.mkdir(parents=True, exist_ok=True)  # create the folder if needed

    def save_chat(self, agent: str, backend: str, model: str, command: str,
                  messages: list, response: str, project: str | None = None):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        filepath = self.folder / f"{timestamp}_{uuid4().hex}.json"

        payload = {
            "timestamp": timestamp,
            "agent": agent,
            "backend": backend,
            "model": model,
            "command": command,
            "messages": messages,
            "response": response
        }
        if project:
            payload["project"] = project

        # Exclusive creation prevents an accidental overwrite even if clocks
        # are frozen or UUID generation is replaced in a test.
        with open(filepath, "x", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)  # save nicely formatted JSON

        return filepath

    def list_chats(self):
        return sorted(self.folder.glob("*.json"), reverse=True)  # newest first

    def load_chat(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)  # read a saved chat back into Python
