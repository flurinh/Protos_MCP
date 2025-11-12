# Protos MCP reliability & context roadmap (draft)

## Objectives
- Stabilize MCP tool usage so LLM agents consistently pick the right operations without dumping raw data back through the model.
- Provide a session-aware context store that records what data has been loaded or generated, and makes those handles reusable across tool invocations.
- Present clear, consistently named tool surfaces plus inline help so agents understand the available capabilities per processor and analysis domain.
- Ensure workflows mirror the `protos/test_*.py` scripts end-to-end via MCP tools and succeed deterministically.

## Proposed pillars

1. **Session context state**
   - Add a `SessionState` object to `ServerContext` that tracks active datasets/entities per processor and stores light-weight payload summaries keyed by handles.
   - Extend `BaseTool` with helper methods (`record_dataset_usage`, `record_entity_usage`, `store_result_payload`) so each tool can update the session state without duplicating logic.
   - Implement new `ContextTools` (`context_status`, `context_list`, `context_get`, `context_clear`, `context_set_active`) to introspect and manipulate session state. Include summaries of what each processor currently "owns".

2. **Tool instrumentation**
   - Update core loader/dataset/analysis tools (starting with sequence + structure) to call the session helpers whenever they download/register/load data. Returned payloads should reference session handles instead of forcing the LLM to echo records.
   - Add optional `store_in_context` / `context_label` parameters to analysis outputs (alignments, conservation, linkage, embeddings) so results can be saved and referenced atomically.
   - Ensure tools that already have `store_result` flags still interact with the session when materialized artifacts are produced (datasets, tables, property IDs).

3. **Naming & capability catalog**
   - Normalize cross-processor helpers with explicit prefixes (e.g., `entity_download`, `dataset_list`, `dataset_merge`). Keep legacy names as shims that delegate to the new atomic functions until clients migrate.
   - Produce a machine-readable tool catalog (JSON/YAML) that groups tool names by domain (`sequence.load`, `sequence.analyze`, `structure.export`, etc.) with parameter hints. Expose it via a new `help_tools` endpoint so agents can discover the correct surface programmatically.
   - Update `ProtoGuideTools` to pull from the catalog instead of hard-coded lists, and add quick-start examples that emphasise using context handles instead of raw payloads.

4. **Status & diagnostics**
   - Expand the existing `config_get_data_root`/`get_server_info` answers with current session highlights (active datasets, last tool run, cached processors).
   - Introduce `context_history` (recent tool invocations + key artifacts) to help debug agent missteps.
   - Provide guard-rail messaging when a tool shouldn't be reused for a given dataset (e.g., single-sequence vs dataset operations) to deter the LLM from hopping to similar-but-wrong tools.

5. **Validation loop**
   - Add an MCP workflow test runner that replays the scripts under `workflows/` against the live FastMCP server and asserts deterministic success.
   - Gate new context features with unit-style tests (e.g., storing datasets, clearing handles, alias resolution) under `mcp_server/tests`.
   - Track coverage in `STATUS_TODO.md` (new section) so future contributors can see which workflows are validated through MCP.

## Next implementation slices

1. Build `SessionState` + `ContextTools`, wire into `ServerContext` and `BaseTool`.
2. Instrument sequence & structure loader/dataset tools with context recording, add consistent tool aliases.
3. Publish the tool catalog + enhanced guide/help surfaces.
4. Roll the context-aware changes across analysis/model tools, adding `store_in_context` support.
5. Implement MCP workflow regression runner and document status in the tracker.

Each slice should culminate in running representative workflow scripts (sequence + structure first) to confirm context handles remove the need for inline data payloads.

