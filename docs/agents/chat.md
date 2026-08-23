# CHAT — General-purpose conversation

`key: chat` · class: `agents/chat_agent.py → ChatAgent` · panel: standard `normal_panel` (no custom panel) · handler: `send_prompt()`

## What it does
The default agent. Plain text in, plain text out, with full multi-turn conversation history. It has no domain framing of its own — instead it wears whichever **Tool** you pick (General Chat, Writing, Coding, Summarize, Rewrite), each supplying a different system prompt. Use it for anything without a dedicated specialist agent.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Tool | System prompt frame prepended to every message. |
| Command | Optional pre-built prompt scaffold from `config/commands.json`. |
| Provider / Model | Which LLM runs the request. |
| Model settings (gear) | Optional execution-mode, provider/model, and API-permission overrides. The recommended route is used by default. |
| Prompt box | Your message. Run, or Stop to cancel while a request is active. |

## Outputs
Streaming text into the **Output** box (auto-hidden until there's content). Each turn is appended to `current_messages`, so follow-ups keep context. Conversations auto-save to `data/chats/` and appear in **Saved Chats**.

## How it works
`ChatAgent.build_messages()` returns `[system(tool prompt), user]`. On later turns the prior assistant reply is included so the model sees the whole thread. Token-by-token streaming for streaming backends, word-by-word emulation otherwise.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/chat_agent.py` | `ChatAgent` — message builder. |
| `main.py: send_prompt()` | Builds request, spawns `ChatWorker`, streams tokens. |
| `main.py: ChatWorker` (QThread) | Runs the backend call off the UI thread. |
| DB `tools` table / `config/tool_prompts.json` | The actual system prompts per Tool. |
| `services/history_store.py` | Saves/loads chats in `data/chats/`. |

## Extend it
- **Add a Tool**: insert a row in the `tools` table (or `config/tool_prompts.json`) with a new system prompt — it shows up in the Tool combo automatically.
- **Add command scaffolds**: extend `config/commands.json`.
- **Attachments / RAG**: `send_prompt()` is the hook — enrich the user message before it reaches `ChatWorker`.

## Requirements
Any compatible text/reasoning provider. Ollama is free/local; cloud providers need an API key (app `.env`). Image-only and speech-only models are excluded from text-task recommendations.
