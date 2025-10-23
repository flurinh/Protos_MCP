#!/usr/bin/env python3
"""Minimal harness to invoke model_lambda_run via the MCP runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable, Tuple

from mcp.server.fastmcp import Context, FastMCP

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server


def _flatten_call_result(raw: Any) -> Tuple[Iterable[str], Any]:
    """FastMCP returns (messages, meta); normalize that into (texts, payload)."""

    if isinstance(raw, tuple) and len(raw) == 2:
        messages, payload = raw
    else:
        messages, payload = (), raw

    texts = []
    for msg in messages or ():
        text = getattr(msg, "text", None)
        if text:
            texts.append(text)

    return texts, payload


async def main() -> None:
    repo_root = Path(__file__).resolve().parent
    data_root = (repo_root / "protos" / "data").resolve()

    server: FastMCP = create_server(
        "Protos Lambda Tool Harness",
        config=ServerConfig(data_root=data_root),
    )

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)
        params = {
            "ctx": ctx,
            "protein_family": "gpcr_a",
            "sequence_dataset": "jumping_spider_rhodopsin_B1_mutant_screen",
        }
        raw = await server.call_tool("model_lambda_run", params)
        messages, payload = _flatten_call_result(raw)

        if messages:
            print("# tool messages")
            for line in messages:
                print(line)
            print()

        print("# tool payload")
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
