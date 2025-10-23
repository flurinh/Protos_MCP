# Status & TODO

Use this tracker to monitor processor migration work, model-platform refactors, research questions, and MCP naming clean-up tasks.

## Processor & Workflow Migration

### Structure Processor
- [x] Alignment engine wraps CEalign/Kabsch/simple with in-place transforms.
- [x] Loader/exporter share a single processor instance; no ad-hoc helpers remain.
- [x] CIF IO relies exclusively on `ProtosPaths` and round-trips cleanly.
- [x] Workflow scripts (`test_structure_*`) operate on dataset abstractions.
- [x] DataFrame utilities keep canonical schema while adding filters and residue/ligand helpers.
- [x] Chain extraction stays opt-in and registers sequences only when requested.
- [x] Registry bridge emits `derived_from` metadata for chain registrations.
- [x] Relationship lookup helpers expose linked sequences when loading structures or datasets.

### Sequence Processor
- [x] Paths split between `fasta/entities` and `fasta/datasets` via `ProtosPaths`.
- [x] Loader ingests local FASTA or UniProt IDs with lazy registration.
- [x] Alignment logic lives under `analysis.sequence` (Biopython + MMseqs).
- [x] Exporter filters by sequence IDs and drives dataset demonstrations.
- [x] Relationship helpers mirror structure-side lookups.
- [x] Mutant library workflow plus conservation/linkage analytics available.
- [x] GRN‑aware mutational generation API (`SequenceProcessor.generate_mutants_for_sequence`).
- [x] Zero‑config mutational study workflow added (`protos/test_mutational_study.py`).
- [ ] Ship reference workflow that classifies chains after registration and feeds annotations back to source structures.

### Graph Processor
- [ ] Implement `GraphProcessor` (PyG optional) that registers graphs under `graph/` with provenance metadata.
- [ ] Provide structure→graph translation utilities with configurable neighbour rules.
- [ ] Record `derived_from` relationships and add dataset bulk-generation helpers plus metrics.
- [ ] Author a guarded workflow script that demonstrates dataset → graph generation → summary statistics.

### Ligand Processor
- [ ] Finalise RDKit integration (descriptors, fingerprints, SDF round-tripping).
- [ ] Classify ligands (cofactors, ions) during extraction; allow residue filters.
- [ ] Extend interaction analysis beyond distance cut-offs and store results via `PropertyProcessor`.
- [ ] Let `StructureProcessor` request ligand extraction inside annotation workflows.
- [ ] Add curated loaders (QM9, ChEMBL, Enamine) with provenance metadata.
- [ ] Plan QSAR integration that links ligand-derived properties back to structures and sequences.

### Cross-Cutting Open Tasks
- [ ] Reproduce each legacy `protos/test_*.py` workflow via MCP tools to confirm atomic tool coverage.
1. Introduce registry-mediated exchange so processors discover related entities lazily rather than through tight coupling.
2. Standardise alignment artefact formats (`.msa`, `.alm`) and integrate them into exporters.
3. Expand cross-processor tests (structure ↔ sequence roundtrip, GRN classification annotations) once the above infrastructure lands.

## Model Platform Refactor
- Adopt enriched `ModelCard` metadata (input/output `ArtifactSpec`, `ExecutionSpec`) to describe model IO explicitly.
- Provide shared helpers to assemble artefact bundles from processors before adapters run.
- Split adapters into `ExternalJobAdapter` (config builders) and `RuntimeAdapter` (direct model invocation) to clarify execution mode.
- Register output ingestion helpers keyed by artefact kind (`register_structure`, `register_property_table`, etc.).
- Return a uniform `ModelInvocation` payload containing assembled artefacts, job metadata, and predictions for both execution modes.
- Roadmap: implement spec infrastructure → refactor ModelManager → migrate Boltz & Lambda adapters → extend cards for new models.

Progress (2025‑10‑10)
- [x] Embedding runtime callable and cards registered (`embedding_esm2_t12_35m`, `embedding_ankh_large`, `embedding_esm2_t33_650m`).
- [x] Lambda adapter migrated: `embedding_dataset` optional; computes via embedding card when absent.
- [x] Lambda uses packaged configs (binding_domain2.json, final_mapping7.csv) and passes explicit paths into Predictor; writes a job‑local config snapshot.
- [x] ModelManager + Lambda logging added for diagnosability; workflows refactored to use protos/data only.

Next
- [ ] Add remaining embedding cards (e.g., ProtT5‑XL) and device/precision knobs.
- [ ] Unify GraphscoreDTA staging to data_root (no repo writes) and extend ingestion for LigandMPNN/Pocket2Mol.
- [ ] Expose MCP tools for embedding prepare+ingest and Lambda prepare/run summaries.

## Embedding via ModelManager (Migration Plan)

Rationale
- Today `EmbeddingProcessor` both computes embeddings and manages datasets. We want all model execution (including embeddings) centralized in `ModelManager` to: unify resource handling (GPU/remote), standardize staging and artifact paths, reduce duplicated init logic (HF weights/device), and expose embeddings cleanly via MCP tools.

Goals
- Move embedding computation into `ModelManager` adapters; keep `EmbeddingProcessor` focused on ingestion, dataset metadata, and convenience load/save.
- Provide first‑class embedding ModelCards (ESM2, Ankh, ProtTrans, etc.) with consistent IO.
- Standardize dataset naming/metadata (model, type, artifact_path) and storage layout.
- Preserve backward compatibility with a deprecation period.

API & Cards
- Input spec: `sequence_dataset` (provider: `sequence_dataset`, format: fasta) + optional `selector`/`filters`.
- Config: `model_name` (implicit from card), `embedding_type` (`per_residue`|`per_protein`), `batch_size`, `device`, `precision`, `truncate/pad`, `layers/pool`.
- Output spec: `embedding_dataset` (provider: `embedding_dataset`, format: npz or dir) with metadata {model_name, embedding_type, artifact_path, shapes_preview}.
- ModelCards (initial set):
  - `embedding_esm2_t12_35m` (runtime)
  - `embedding_ankh_large` (runtime)
  - `embedding_esm2_t33_650m` (runtime, GPU preferred)
  - Future: `embedding_prott5_xl`, `embedding_electra`, etc.

Adapters
- `EmbeddingRuntimeAdapter` loads the HF model/tokenizer, streams batches, and returns `RuntimeResult` with:
  - `artifacts`: the persisted dataset bundle (npz/dir)
  - `metadata`: model, type, counts, shapes preview, timing
- External mode (optional): `EmbeddingExternalAdapter` for remote/API execution (builds config + input fasta and assembles returned artifact on completion).

Artifact layout & paths
- Staging under `data/models/embedding/<card>/job_<ts>/` (inputs/, outputs/).
- Persist datasets under `data/embedding/embeddings/{dataset_name}`; store `artifact_path` relative to ProtosPaths.
- Cache HF weights under `data/models/embedding/<card>/cache` (override via env if needed).

EmbeddingProcessor changes (compat layer)
- Phase 0: Add shim so `EmbeddingProcessor.embed_sequences(...)` calls `ModelManager.prepare(<embedding_card>, ...)` under the hood, then ingests results. Log a deprecation warning.
- Retain `get_dataset_info`, `load_embeddings`, and dataset registration methods. Remove direct HF/model init once migration completes.

MCP tooling
- New tools under `mcp_server/tools/model/`:
  - `model_embedding_prepare_inputs(sequence_dataset, model_card, embedding_type, ...)` → returns summary + defaults
  - `model_embedding_run(sequence_dataset, model_card, embedding_type, batch_size, device, ...)` → runs adapter and returns dataset name + preview
- Update `list_models`/`describe_model` to include embedding cards.

Testing & migration plan
- Phase 1 (Introduce):
  - Implement embedding ModelCards + `EmbeddingRuntimeAdapter` (ESM2-t12, Ankh-large).
  - Add unit tests mirroring current embedding tests but via ModelManager (no network by default; use tiny local fixtures or skip with marks).
  - Wire `EmbeddingProcessor.embed_sequences` to call ModelManager.
- Phase 2 (Adopt):
  - Update repository tests to prefer ModelManager path (leave legacy tests marked or skipped).
  - Update MCP recipes to use `model_embedding_*` tools.
- Phase 3 (Deprecate):
  - Remove direct compute from `EmbeddingProcessor`; keep ingestion/dataset access only.
  - Finalize docs and examples.

Schema & naming
- Canonical dataset name: `<sequence_dataset>__<model_name>__<embedding_type>` (already in use) — enforce in adapter and store in metadata.
- Metadata keys standardized: `model_name`, `embedding_type`, `artifact_path`, `entity_count`, `shapes_preview`.

Operational considerations
- Device selection: allow `device=auto|cpu|cuda:N` in config with fallbacks.
- Precision: fp32 default; allow bf16/fp16 where supported.
- Chunking: configurable `batch_size` and max tokens with truncation strategy logged in metadata.
- Offline mode: adapter detects absence of network and requires local weights; emit clear error or skip (tests to mark accordingly).

Risks & mitigations
- HF dependency variance → pin minimal versions in extras; lazy import inside adapter.
- GPU unavailability → device fallback; performance warning.
- Large memory → stream tokens and layers; support pooling to per-protein when needed.

Acceptance criteria
- Embedding datasets prepared via ModelManager match legacy datasets in schema and content for a reference set.
- All embedding-facing MCP tools use ModelManager; no tests depend on direct `EmbeddingProcessor` compute.
- Backward-compat shim logs deprecation and forwards to ModelManager without behavior changes.

Progress (2025‑10‑10)
- [x] Implemented `protos.models.embedding_runtime:run_embedding` (runtime path), with NPZ artifact + sidecar metadata.
- [x] Registered initial embedding cards; standardized dataset naming and metadata.
- [x] Added ingestion helpers in `EmbeddingProcessor`: `ingest_from_artifact`, `ingest_from_invocation`.
- [x] Updated `protos/test_embedding_workflow.py` to use ModelManager + ingestion; skips gracefully on missing deps.

Open items
- [ ] Register additional models; add pooling/layer selection in config.
- [ ] Migrate remaining workflows away from direct `EmbeddingProcessor.embed_sequences`.
- [ ] Document artifact schema and metadata guarantees in WORKFLOWS.md.

## Workflow Refactor Notes
- Legacy examples under `protos/examples` relied on manual path management; the refactor plan replaces them with zero-config workflows that register datasets and rely on loader helpers.
- Dataset helper roadmap: register packaged GPCR sequences, rhodopsin structures, ChEMBL ligands, GPCR property tables, and rhodopsin graphs entirely through loaders + `DatasetManager`.
- Capability enhancements still pending include GRN visualisation helpers, property export APIs, ligand loader parity, registry diagnostics, and workflow-driven status reports.
- July 24, 2025 capability testing (Protos MCP Server v0.1.0) validated core entity/dataset operations; follow-up focuses on the open enhancer list above.

## Protein–Ligand Interactions
- Modernize analyzer pathing and inputs:
  - Consume canonical per-entity DataFrames via `StructureProcessor.load_entity(structure_id)`; remove `pdb_id`/`CifBaseProcessor` assumptions.
  - Add a selector util to slice a single ligand’s atoms by `res_id` (preferred) or the tuple (`auth_chain_id`, `auth_seq_id`, `auth_comp_id`, `insertion`).
  - Export ligands using `StructureExporter` (format `sdf`) with ProtosPaths-derived targets; no manual paths.
- Persist and summarize results:
  - Save tidy interaction tables with `PropertyProcessor` (columns: structure_id, res_id, chain_id, comp_id, interaction_type, partner residues/atoms, distance, details).
  - Provide dataset-level aggregators and compact summaries (counts per interaction type, top residues).
- MCP tool surface:
  - `structure_list_ligands` (thin over `summarize_ligands`).
  - `structure_analyze_ligand_interactions` (cutoffs/filters; returns summary + optional saved table id).
  - `structure_export_ligand_sdf` (filters: include_res_ids/comp_ids/chains; grouping controls).
- Quality and extensibility:
  - Improve H-bond detection (donor/acceptor typing, angle criteria) leveraging RDKit.
  - Add pi-stacking and salt-bridge heuristics; align water-mediated contacts with water-network analysis.
- Ensure zero-config: no hardcoded filepaths or examples; all exports routed through ProtosPaths.

## Ligand Design (LigandMPNN) & GraphProcessor Roadmap

Outline

1) ModelManager Integration (LigandMPNN)
- Define ModelCard 'ligand_mpnn':
  - input_spec: pocket_graph (graph, pickle/pyg, required), pocket_metadata (json, optional), constraints (json, optional)
  - output_spec: ligand_candidates (table csv/parquet), ligand_sdf (sdf, optional)
  - execution: mode runtime/external, entrypoint protos.models.ligand_mpnn.adapter:run, environment GPU tags
- Adapter responsibilities:
  - assemble_inputs: validate pocket graph + metadata/constraints
  - run: invoke LigandMPNN; return SMILES + scores
  - ingest_outputs: import candidates via LigandLoader (structure + molecule datasets), export SDF via StructureExporter (SDF), record property table
- MCP Tools:
  - list_models / describe_model
  - model_ligandmpnn_prepare_inputs(graph_entity, constraints?)
  - model_ligandmpnn_run(graph_entity, constraints?)

2) GraphProcessor Enhancements
- Pocket graph generation:
  - generate_pocket_graph(structure_id, res_ids, cutoff, include_ligand=True, level='atom'|'residue', schema='ligandmpnn_pocket_v1')
  - Identify binding pocket residues via KD-tree around ligand atoms; filter structure to pocket + ligand
  - Persist with provenance (structure_id, res_ids, cutoff, schema, level)
- Graph schema registry:
  - GraphSchema interface: node_features(), edge_policy(), metadata (schema_name, version)
  - Built-ins:
    - basic_atom_cutoff_v1: current atomic-number + cutoff edges
    - ligandmpnn_pocket_v1: richer atom features (element one-hot, formal charge, aromatic flag, residue type one-hot, distance to ligand centroid), cutoff edges
    - residue_contact_v1: residue-level features and contact edges
- Options:
  - include_waters, include_sidechains_only, include_chains, include_res_ids filters

3) End-to-End Workflow (Pocket → LigandMPNN)
- Select ligand (summarize_ligands) or explicit res_id
- GraphProcessor.generate_pocket_graph(..., schema='ligandmpnn_pocket_v1')
- ModelManager: assemble_inputs('ligand_mpnn', request={pocket_graph, metadata, constraints})
- Run adapter; candidates → register via LigandLoader.import_smiles; export SDF; record property table

4) Storage & Artifacts (ProtosPaths only)
- Graphs: graph/graphs/{entity}.pkl with registry metadata; datasets under graph/datasets
- Candidates SDF: structure/sdf/{dataset_or_structure}__ligandmpnn_candidates.sdf
- Property tables: property/tables/{table}.csv

5) Quality & Extensibility
- Improve H-bond detection (donor/acceptor typing, angle); add pi-stacking and salt-bridge heuristics
- Align water-mediated contacts with water-network analysis
- Keep zero-config: no hardcoded paths; all exports derived from ProtosPaths

6) Optional CLI/MCP Enhancers
- structure_list_ligands(structure_id)
- structure_generate_pocket_graph(structure_id, res_ids, cutoff, schema,...)
- model_ligandmpnn_prepare_inputs/run
- structure_export_ligand_sdf with include_res_ids/comp_ids/chains

## Research Threads
- **Deborah** – quantify retinal binding-site rigidity vs flexibility, correlate quantum yield with energy barriers, and compute inactive/active energy gaps.
- **Gebhard** – rank water-network positions using beta factors by deforming backbones, refining waters, and reading resulting densities.
- **Lea** – compare GRN positions across OPN5, cone, and bistable opsins in active vs inactive conformations.
- **Valerie** – contrast agonist vs inverse-agonist GRN interactions in Class A GPCRs, focusing on hydrogen-bond patterns around the Schiff base and other key positions.

## MCP Tool Naming
The MCP surface now follows the `domain_action` (or `action_domain`) convention (`structure_extract_water_molecules`, `config_set_data_root`, `grn_align_dataset_to_reference`, etc.). Keep this prefixing pattern for any new tools so wildcard discovery stays predictable for agents.

## Next Steps
- Prioritise GRN workflow consolidation and follow-on tooling once the registry-driven helpers land.
- Decide whether to standardise on aliasing (preferred) or hard renames when future regressions are spotted.
- Coordinate model-platform refactor milestones with Lambda analysis needs so datasets, embeddings, and property outputs remain compatible.


### Ligand & Graph Integration
- [ ] Unify ligand structural handling: parse SMILES/SDF through a shared molecule-frame builder that mirrors the mmCIF → DataFrame pipeline.
- [ ] Extend StructureLoader (or new LigandLoader) to ingest SDF/SMILES, persist canonical frames via StructureProcessor, and tag ligand metadata.
- [ ] Build MoleculeProcessor surface for SMILES/InChI metadata while StructureProcessor owns coordinate storage; expose lazy SMILES generation for extracted ligands.
- [ ] Expose MCP tools for bidirectional conversion (structure_export_ligands, ligand_generate_structure, graph generation for ligands).
- [ ] Ensure graph generation consumes canonical frames for both proteins and ligands; update documentation/workflows accordingly.
