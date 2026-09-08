# Forge — create reviewed agent scaffolds

**Goal:** turn an agent idea into a safe, reviewable specification. **Time:** 15 minutes.

![Forge workspace](docs/training/images/forge.png)

Forge is different from Chat: Chat helps think and answer; Forge creates a
concrete agent specification and, only after approval, a source-code scaffold.

## Describe the idea

State the agent's purpose, intended users, inputs, outputs, allowed providers,
allowed tools, budget needs and actions that require approval. Keep one agent
focused on one responsibility. **Analyze Idea** asks the selected model for a
structured JSON specification.

## Review before creation

Check the internal name, label, description, system prompt, providers, tools,
budget and approval flag. Reject vague permissions, open-ended execution,
unnecessary cloud access or a prompt that claims capabilities the code will not
have. **Reject / Clear Spec** discards the draft.

**Approve & Create Agent** writes a Python scaffold and inactive registry/tool
entries. It does not make the agent a built-in sidebar item or dynamically load
it. A developer must inspect the files, add a suitable panel, test permissions
and deliberately integrate it. Restarting alone is not a safety review.

## Best practices

- Prefer narrow tools with explicit inputs and structured outputs.
- Require approval for external writes, spending and security-sensitive work.
- Keep secrets out of system prompts and generated files.
- Test failure, cancellation and disabled-permission paths.
- Do not approve a spec you cannot explain.

## Exercise

Draft a read-only log-summary agent that uses Ollama by default. Confirm that
its spec has no file-write or network capability before rejecting the practice draft.

