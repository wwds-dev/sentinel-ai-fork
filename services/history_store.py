import json  # used for saving history as JSON
from pathlib import Path  # makes folder paths easier
from datetime import datetime  # used to generate timestamped filenames


class HistoryStore:
    def __init__(self, folder: str = "data/chats"):
        self.folder = Path(folder)  # store the history folder path
        self.folder.mkdir(parents=True, exist_ok=True)  # create the folder if needed

    def save_chat(self, agent: str, backend: str, model: str, command: str,
                  messages: list, response: str, project: str | None = None):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # make a timestamp
        filepath = self.folder / f"{timestamp}.json"  # create filename from timestamp

        payload = {
            "timestamp": timestamp,
            "agent": agent,
            "backend": backend,
            "model": model,
            "command": command,
            "messages": messages,
            "response": response,
            "project": project,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)  # save nicely formatted JSON

    def list_chats(self):
        return sorted(self.folder.glob("*.json"), reverse=True)  # newest first

    def load_chat(self, filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)  # read a saved chat back into Python

    def assign_project(self, filepath: str, project: str | None) -> None:
        data = self.load_chat(filepath)
        if project:
            data["project"] = project
        else:
            data.pop("project", None)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
