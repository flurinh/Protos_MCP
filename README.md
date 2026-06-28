<h1 align="center">ProtOS-MCP</h1>

<p align="center">
  <b>Let LLM agents drive a structural-biology toolkit, end to end.</b><br>
  Model Context Protocol servers that wrap <a href="https://github.com/flurinh/protos">ProtOS</a> as clean, stateless JSON tools — for Claude, Ollama, or any MCP client.
</p>

<p align="center"><img src="docs/architecture.jpg" alt="Sequence diagram: Scientist to AI to MCP to ProtOS and back" width="760"></p>

<p align="center">
  <a href="https://flurinh.github.io">◆ Portfolio</a> &nbsp;·&nbsp;
  <b>The build:</b>
  <a href="https://github.com/flurinh/LM-DTA">LM-DTA</a> →
  <a href="https://github.com/flurinh/mt">Master thesis</a> →
  <a href="https://github.com/flurinh/protos">ProtOS</a> →
  <a href="https://github.com/flurinh/MOGRN">MOGRN</a> →
  <a href="https://github.com/flurinh/lambda">Lambda</a> →
  <b>ProtOS-MCP</b>
</p>

---

## What it is

ProtOS-MCP couples the ProtOS structural-biology toolkit with **Model Context Protocol**
servers, so an agent can run structure-centric workflows from a single natural-language
request. ProtOS supplies zero-configuration processors (structures, sequences, GRNs,
ligands, properties, embeddings, graphs); the MCP layer wraps them behind **stateless JSON
tools**, and adds a **workflow recipe engine** and an **agentic-task benchmark suite**.

## ▶ See it run

**[Watch a live four-turn session](https://flurinh.github.io/#protos-mcp)** on the portfolio:
the agent orients itself, ingests a sequence, predicts its λmax with
**[Lambda](https://github.com/flurinh/lambda)**, then engineers a redshift — redesigning the
Rhodozyme enzyme one mutation at a time.

## Getting started

```bash
pip install -e protos                 # the ProtOS library
pip install -r requirements-mcp.txt   # MCP-facing dependencies
python claude_server.py               # or: python ollama_server.py
```

Run the tests:

```bash
python -m pytest protos/tests -m "not integration"
python -m pytest mcp_server/tests -q
```

## Layout

- `mcp_server/core` — shared MCP runtime (contexts, processor factory, error types)
- `mcp_server/tools` — tool implementations grouped by analysis domain
- `claude_server.py` / `ollama_server.py` — runnable entry points
- `WORKFLOWS.md` — zero-config data flow, processor workflows, and the full tool catalog

---

<p align="center">
◀ <b>Previously:</b> <a href="https://github.com/flurinh/lambda">Lambda — predicting opsin colour</a>
&nbsp;·&nbsp;
<b>Next:</b> <a href="https://flurinh.github.io/#rhodozyme">Rhodozyme & Cauldron — what it builds</a> ▶
</p>
