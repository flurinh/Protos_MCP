# Workflows & Tooling Guide

This reference explains how the Protos processors, datasets, and MCP tools fit together. Use it to design new workflows, keep tool naming consistent, and understand how the ModelManager orchestrates cross-processor tasks.

## Zero-Config Data Flow
- `ProtosPaths` is the single entry point for filesystem access: it materialises `./data/` (or a custom root) and creates processor-specific subdirectories on demand.
- `EntityRegistry` stores UUID-backed metadata while exposing only human-readable names; all processors call `register_entity` so the same biological object can appear as structure, sequence, GRN table, ligand, property, embedding, or graph.
- Processors never manually compose paths: loaders ingest files, datasets are JSON descriptors in `data/<processor>/datasets/`, and tables live under their processor (e.g., `data/grn/tables/`).
- Typer CLIs (`protos init`, `protos clear`) reset the environment without touching user code; the MCP runtime mirrors that behaviour by sharing a `ServerContext` with ready-made processors.

## Entity & Dataset Lifecycle
- Base processors expose a uniform API (`load_entity`, `save_entity`, `create_dataset`, `load_dataset`, `record_properties`, etc.) that always resolves names through the registry.
- Relationships are captured when processors derive new entities (e.g., sequence extracted from a structure, ligand interactions stored as properties) so MCP agents can enumerate related resources without guessing paths.
- Dataset metadata should include provenance (`source`, `created_by`, `parameters`) because tools like `dataset_info` surface those fields verbatim to clients.

## GRN Annotation Pipeline
1. **Reference Discovery** – load reference tables (`load_grn_reference_table`) and retrieve GRN configuration for the target protein family.
2. **Sequence Extraction** – pull sequences from entity or structure datasets (`grn_extract_sequences_from_dataset` or `grn_extract_sequences_from_structures`).
3. **Alignment** – match query sequences to the reference via MMseqs2 or BLOSUM62 (`grn_align_dataset_to_reference` or `grn_align_sequences_to_reference`).
4. **Annotation & Expansion** – assign GRN positions (`assign_grn_to_dataset`/`assign_grn_to_sequences`) and expand coverage (loop handling, gap filling).
5. **Recording & QA** – persist GRN tables (`record_grn_table`/`grn_create_table`), then compute coverage or conservation statistics (`grn_get_coverage_stats`, `grn_compare_conservation`).

## Model Integration Workflows
- `ModelManager` mediates between processors and external/in-process models using declarative model cards (input/output specs plus execution metadata).
- **External config adapters** (e.g., Boltz-2) package datasets into YAML/FASTA bundles and hand back a `PreparedJob` for schedulers.
- **Runtime adapters** hydrated processors directly, but after the remote rework Lambda now follows the external-job path: ModelManager packages artifacts and produces a submission script even for Lambda runs.
- MCP tools surface helper stages: `model_lambda_prepare_resources` copies packaged configs, while `model_lambda_run` handles dataset registration, GRN annotation, embedding fallback, and finally returns either inline predictions or (the default) a prepared job payload.
- Example drivers under `workflows/` showcase these flows: `model_lambda_via_tools.py` for Lambda submissions, `boltz_sequence_prediction_via_tools.py` for Boltz jobs, and `smiles_docking_via_tools.py` for SMILES‑driven docking prep.

### Lambda (Adapter‑Centric, Zero‑Config)
- Embeddings now run via embedding model cards (`embedding_ankh_large`, `embedding_esm2_t12_35m`, etc.). The Lambda adapter treats `embedding_dataset` as optional and computes embeddings on‑the‑fly when absent.
- Packaged configs only: the adapter resolves `binding_domain2.json` and `final_mapping7.csv` from `protos/src/protos/models/lambda/lmda/configs/` and passes explicit paths into Predictor at construction. A job‑local snapshot (`lambda_run_config.json`) is written under `data/models/lambda/run_<ts>/outputs/`.
- Job-first submissions: by default `ModelManager.prepare('lambda')` now yields a `PreparedJob` with packaged inputs, command, and working directory. When optional on-box dependencies are present the runtime path still works, but MCP tooling (`model_lambda_run`) always reports the `mode` (`runtime` vs `job`) so callers can branch accordingly.
- Outputs: when the runtime executes locally, property tables are registered via `PropertyProcessor` (under `data/property/tables/`); in the submission-only path the packaged job metadata contains the snapshot locations agents must upload to remote accelerators.
- Logging: ModelManager and the adapter emit INFO logs summarizing inputs, resource resolution, embedding source, alignment counts, and snapshot paths.

Next: update the MCP tools and server routes to reflect these changes (embedding cards, Lambda adapter flow, GRN‑aware mutation helpers, and the new SMILES‑to‑docking workflow) so agent workflows can leverage the zero‑config paths and staging.

### Embeddings via ModelManager
- Use `ModelManager.prepare('embedding_<model>')` with inputs `{'sequence_dataset': <name>}` and config `{'embedding_type': 'per_residue'|'mean'|'sum'}`.
- The runtime writes a compact NPZ artifact plus sidecar JSON and returns a `RuntimeResult`; ingest via `EmbeddingProcessor.ingest_from_invocation(invocation, dataset_name=...)` to create a formal dataset.

## Tool Categories & Naming Patterns
- Loader tools (`download_entity`, `download_entities`, `sequence_download`, etc.) move data into the registry; they live under `mcp_server/tools/loader/`.
- Data IO tools cover dataset CRUD and entity management (`create_dataset`, `entity_list_entities`, `load_entity`). They ensure everything flows through `DatasetManager` and the registry.
- Analysis tools wrap processor logic for structures, sequences, GRNs, ligands, properties, and embeddings. The convention is **verb-first names that include the domain**, e.g., `list_structure_entities`, `calculate_sequence_identity`.
- Cross-processor workflows (model manager) expose the Lambda prediction chain and model discovery helpers under `model/manager.py`.
- A handful of existing tools do not include their domain token (see `STATUS_TODO.md` for the clean-up list); new tools should follow the `verb_domain` pattern to stay searchable and unambiguous.

## Standalone Analysis Helpers
- `analysis/embedding.py` defines `_tensor_to_array` (convert torch tensors to `np.ndarray`) and `_flatten_to_numpy` (normalize nested predictions) for reuse across embedding tools. Document any additional module-level helpers here when adding them.

## Mutational Study (GRN‑Aware)
- Flow: sequence dataset → GRN annotation → GRN→sequence position map → sequence‑position mutational study.
- API:
  - `SequenceProcessor.annotate_with_grn(dataset_name=..., reference_table='gpcrdb_ref', protein_family='gpcr_a', output_table=...)` produces the GRN table.
  - `GRNProcessor.build_grn_to_seq_index(grn_table, sequence_id=...)` maps GRN labels to 1‑based sequence indices for a given sequence.
  - `SequenceProcessor.generate_mutants_for_sequence(seq_name, sequence, seq_positions={...}, grn_positions={...}, grn_table=..., protein_family='gpcr_a')` returns `{mutant_name: sequence}` with tags like `T3L`.
  - Persist with `SequenceProcessor.save_sequences` to register a mutant dataset (optionally include WT).
- Example workflow: see `protos/test_mutational_study.py` (single‑sequence and multi‑sequence GRN mutation demos). All paths are derived from ProtosPaths; no hardcoded locations.

## MCP Tool Catalog
The following tables enumerate every MCP tool currently registered. Grouping matches the loader / data IO / analysis / workflow categories described above. Update this catalog when adding, removing, or renaming tools so agent capabilities stay discoverable.

## Analysis
### Embedding Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `embedding_cosine_similarity` | Compute cosine similarities between embeddings in a dataset. | `analysis/embedding.py` |
| `embedding_generate` | Generate embeddings for a dataset or explicit sequence mapping. | `analysis/embedding.py` |
| `embedding_list_models` | List available embedding models with dimensions/descriptions. | `analysis/embedding.py` |
| `embedding_load_dataset` | Summarise an embedding dataset and optionally return selected embeddings. | `analysis/embedding.py` |

### GRN Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `add_grn_annotation` | Add or update GRN annotation for a single sequence. Args: table_name: Name of the GRN table sequence_id: ID of the sequence to annotate grn_positions: Dictionary mapping GRN positions to residues e.g., {"1.50": "R", "2.50": "L", "3.50": "D"} Returns: Dictionary with update status | `analysis/grn.py` |
| `grn_align_dataset_to_reference` | Align all sequences in a dataset to a GRN reference table. This tool uses dataset and reference names rather than requiring sequences to be passed as parameters. Args: dataset_name: Name of dataset containing query sequences reference_name: Name of GRN reference table min_identity: Minimum sequence identity threshold alignment_method: Method to use (mmseqs2 or blosum62) Returns: Dictionary with alignment results | `analysis/grn.py` |
| `grn_align_sequences_to_reference` | Align query sequences to a GRN reference database using raw sequences. Note: For dataset-based alignment, use align_dataset_to_reference instead. Args: query_sequences: Dictionary mapping sequence IDs to sequences (raw strings) reference_name: Name of the reference table to align against min_identity: Minimum sequence identity threshold (0-1) alignment_method: Alignment method ("mmseqs2" or "blosum62") Returns: Dictionary with alignment results | `analysis/grn.py` |
| `apply_grn_interval` | Filter a GRN table to include only specific GRN positions. This is useful for focusing on specific regions (e.g., only TM helices). Args: table_name: Name of the GRN table to filter grn_positions: List of GRN positions to keep (e.g., ["1.50", "2.50", "3.50"]) save_as: Optional name to save filtered table Returns: Dictionary with filtered table information | `analysis/grn.py` |
| `assign_grn_to_dataset` | Assign GRN positions to all sequences in a dataset. This combines alignment and GRN assignment in one step, using dataset names rather than requiring sequence data. Args: dataset_name: Dataset containing sequences to annotate reference_name: GRN reference table to use protein_family: Protein family for GRN configuration output_name: Name for output GRN table (defaults to dataset_name + "_grn") Returns: Dictionary with GRN assignment results | `analysis/grn.py` |
| `assign_grn_to_sequences` | Assign GRN positions to aligned sequences. Args: sequence_alignments: Alignment results from align_sequences_to_reference reference_name: Name of the reference table used protein_family: Protein family for GRN configuration expand_annotation: Whether to expand annotations to fill gaps Returns: Dictionary with GRN assignments | `analysis/grn.py` |
| `grn_compare_conservation` | Compare GRN conservation between two groups of entities. Args: grn_table: Name of the GRN table entity_group1: First group of entity IDs entity_group2: Second group of entity IDs min_conservation: Minimum conservation threshold Returns: Dictionary with conservation comparison | `analysis/grn.py` |
| `grn_create_table` | Create and save a GRN table from assignments. Args: grn_assignments: GRN assignments from assign_grn_to_sequences dataset_name: Name for the GRN dataset normalize_formats: Whether to normalize GRN position formats Returns: Dictionary with table creation status | `analysis/grn.py` |
| `grn_extract_sequences_from_dataset` | Extract sequences from all entities in a dataset. This tool loads entities from storage rather than requiring sequences as input. Works with both structure and sequence datasets. Args: dataset_name: Name of the dataset processor_type: Type of processor containing the dataset chain_selection: For structures, which chain to extract (e.g., "A") Returns: Dictionary with entity IDs and their sequences | `analysis/grn.py` |
| `grn_extract_sequences_from_structures` | Extract amino acid sequences from a structure dataset (deprecated). Note: Use extract_sequences_from_dataset for improved functionality. Args: dataset_name: Name of the structure dataset chain_selection: Which chains to extract ("all", "A", "B", etc.) Returns: Dictionary with extracted sequences | `analysis/grn.py` |
| `grn_get_config` | Get GRN configuration for a protein family. Args: protein_family: Protein family name (e.g., "gpcr_a", "kinase") strict: Whether to use strict configuration Returns: Dictionary with GRN configuration regions | `analysis/grn.py` |
| `grn_get_coverage_stats` | Calculate coverage statistics for a GRN table. Args: dataset_name: Name of the GRN dataset Returns: Dictionary with coverage statistics | `analysis/grn.py` |
| `get_grn_for_entities` | Get GRN annotations for specific entities from a GRN table. Args: entity_list: List of entity IDs to query grn_table: Name of the GRN table to query positions: Optional list of specific GRN positions to retrieve Returns: Dictionary with GRN annotations | `analysis/grn.py` |
| `get_grn_table_stats` | Get detailed statistics about a GRN table. Analyzes coverage, conservation, and missing data patterns. Args: table_name: Name of the GRN table to analyze Returns: Dictionary with comprehensive table statistics | `analysis/grn.py` |
| `grn_annotate_sequences` | Annotate sequences with GRN positions using `SequenceProcessor.annotate_with_grn`. | `analysis/grn.py` |
| `list_grn_tables` | List all available GRN tables. Returns both reference tables and user-created tables. Returns: Dictionary with lists of available tables | `analysis/grn.py` |
| `load_grn_reference_table` | Load a GRN reference table for sequence annotation. Available reference tables include: - gpcrdb_ref: GPCR reference numbering from GPCRdb - Additional reference tables can be added to the reference data Args: reference_name: Name of the reference table (without .csv extension) Returns: Dictionary with reference table information | `analysis/grn.py` |
| `load_grn_table` | Load any GRN table (not just reference tables). This loads user-created GRN tables from the tables/ directory. Args: table_name: Name of the GRN table (without .csv extension) Returns: Dictionary with table information and statistics | `analysis/grn.py` |
| `record_grn_table` | Create or update a GRN table via `GRNProcessor.record_table`. | `analysis/grn.py` |

### Ligand Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `ligand_calculate_molecular_properties` | Calculate molecular properties for a SMILES string. Uses RDKit to calculate properties including: - Molecular weight - LogP (lipophilicity) - HBA/HBD (hydrogen bond acceptors/donors) - TPSA (topological polar surface area) - Rotatable bonds - Lipinski rule of 5 compliance Args: smiles: SMILES string representing the molecule Returns: Dictionary with molecular properties | `analysis/ligand.py` |
| `create_ligand_dataset_from_chembl` | Create a ligand dataset from ChEMBL bioactivity data. This tool downloads ligands for a protein target and creates a dataset with their properties and bioactivity data. Args: protein_id: Protein identifier (UniProt ID or gene name) dataset_name: Name for the new dataset activity_types: Activity types to include min_pchembl: Minimum pChEMBL value max_ligands: Maximum number of ligands to include Returns: Dictionary with dataset creation status | `analysis/ligand.py` |
| `filter_drug_like_ligands` | Filter ligands by drug-like properties (Lipinski's rule of 5). Args: entity_names: List of ligand entity names or SMILES strict: Apply stricter criteria (Veber's rules) Returns: Dictionary with drug-like and non-drug-like ligands | `analysis/ligand.py` |
| `find_ligand_in_structures` | Find PDB structures containing a specific ligand. Args: ligand_code: Three-letter ligand code (e.g., 'ATP', 'NAD', 'HEM') Returns: Dictionary with PDB IDs containing the ligand | `analysis/ligand.py` |
| `get_protein_ligands_from_chembl` | Get bioactive ligands for a protein from ChEMBL. Args: protein_id: Protein identifier (UniProt ID, gene name, or ChEMBL target) activity_types: Filter by activity types (e.g., ['IC50', 'Ki']) min_pchembl: Minimum pChEMBL value (higher = more potent) reload: Force reload from ChEMBL (ignore cache) Returns: Dictionary with ligand bioactivity data | `analysis/ligand.py` |
| `ligand_compute_interactions` | Compute ligand-protein contacts for a structure. | `analysis/ligand.py` |
| `ligand_dataset_stats` | Summarize a ligand dataset (entity count, metadata). | `analysis/ligand.py` |
| `ligand_record_interactions` | Record ligand interaction rows into a property table. | `analysis/ligand.py` |
| `ligand_register_smiles` | Register SMILES records as ligand entities and persist a dataset. | `analysis/ligand.py` |
| `ligand_import_smiles_structures` | Ingest SMILES strings as structure entities (plus molecule datasets) via `LigandLoader`, optionally building 3D coordinates for downstream docking. | `analysis/ligand.py` |
| `list_ligand_entities` | List registered ligand entities with optional pagination. | `analysis/ligand.py` |
| `load_ligand_dataset` | Summarize a ligand dataset and optionally preview member entities. | `analysis/ligand.py` |
| `load_ligand_entity` | Load a ligand entity and preview its metadata. | `analysis/ligand.py` |
| `search_similar_ligands` | Search for similar ligands using Tanimoto similarity. Args: query_smiles: Query SMILES string similarity_threshold: Minimum similarity score (0-1) dataset: Optional dataset to search within max_results: Maximum number of results to return Returns: Dictionary with similar ligands and their similarity scores | `analysis/ligand.py` |
| `ligand_smiles_to_inchi` | Convert SMILES to InChI and InChI Key. Args: smiles: SMILES string Returns: Dictionary with InChI representations | `analysis/ligand.py` |

### Property Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `add_property_column` | Add a new property column to an existing property table. Args: dataset_name: Dataset to update property_name: Name of the new property values: Either: - Dict mapping entity_id to value - Single value to apply to all entities Returns: Dictionary with update status | `analysis/property.py` |
| `create_property_table` | Create a new property table from entity data. Args: dataset_name: Name for the property table/dataset data: Either: - Dict of {entity_id: {property: value}} - List of dicts with 'entity_id' key metadata: Optional metadata for the dataset Returns: Dictionary with creation status | `analysis/property.py` |
| `export_property_table` | Export a property table or subset as CSV/JSON. Args: dataset_name: Dataset to export entities: List of entities to include (None for all) properties: List of properties to include (None for all) Returns: Dictionary with exported data | `analysis/property.py` |
| `filter_entities_by_property` | Filter entities based on property values. Args: dataset_name: Name of the property dataset property_name: Property to filter by operator: Comparison operator (=, !=, <, >, <=, >=, in, not_in, contains) value: Value to compare against Returns: Dictionary with filtered entity list | `analysis/property.py` |
| `get_entity_property_values` | Get all property values for a specific entity. Args: entity_id: Entity identifier dataset_name: Specific dataset (None to search all) Returns: Dictionary with entity's property values | `analysis/property.py` |
| `get_property_statistics` | Get statistics for properties in a dataset. Args: dataset_name: Name of the property dataset property_name: Specific property to analyze (None for all) Returns: Dictionary with property statistics | `analysis/property.py` |
| `list_property_tables` | List all property tables registered with Protos. | `analysis/property.py` |
| `load_property_rows` | Load property rows, optionally filtered by entity scope. | `analysis/property.py` |
| `load_property_table` | Load a property table as JSON for inspection. | `analysis/property.py` |
| `merge_property_tables` | Merge multiple property tables into one. Args: dataset_names: List of datasets to merge output_name: Name for the merged dataset how: Merge method ('outer', 'inner', 'left', 'right') Returns: Dictionary with merge results | `analysis/property.py` |
| `record_property_rows` | Append rows to a property table using `record_properties`. | `analysis/property.py` |
| `save_property_table` | Persist property table metadata and ensure dataset registration is updated. | `analysis/property.py` |

### Sequence Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `align_sequences` | Perform pairwise sequence alignment using raw sequences. Note: For entity-based alignment, use align_sequences_by_id instead. Args: sequence1: First sequence (raw string) sequence2: Second sequence (raw string) alignment_method: Alignment method ("blosum62", "pam250", etc.) gap_open: Gap opening penalty gap_extend: Gap extension penalty Returns: Dictionary with alignment results | `analysis/sequence.py` |
| `align_sequences_by_id` | Perform pairwise sequence alignment using entity identifiers. This tool loads sequences from Protos storage rather than requiring the full sequence strings as input. Args: entity1: Entity identifier for first sequence entity2: Entity identifier for second sequence alignment_method: Alignment method ("blosum62", "pam250", etc.) gap_open: Gap opening penalty gap_extend: Gap extension penalty Returns: Dictionary with alignment results | `analysis/sequence.py` |
| `sequence_calculate_identity_from_dataset` | Calculate pairwise sequence identities for all sequences in a dataset. Args: dataset_name: Name of the sequence dataset reference_entity: Optional reference entity for one-vs-all comparison Returns: Dictionary with identity matrix or list | `analysis/sequence.py` |
| `calculate_sequence_identity` | Calculate pairwise sequence identities using raw sequences. Note: For entity-based identity calculation, use sequence_calculate_identity_from_dataset instead. Args: sequences: Dictionary mapping sequence IDs to sequences (raw strings) reference_sequence: Optional reference sequence to compare all against Returns: Dictionary with identity matrix | `analysis/sequence.py` |
| `cluster_dataset_sequences` | Cluster sequences in a dataset by similarity. Args: dataset_name: Name of the sequence dataset similarity_threshold: Similarity threshold for clustering (0-1) method: Clustering method (single, complete, average) Returns: Dictionary with cluster assignments | `analysis/sequence.py` |
| `cluster_sequences` | Cluster sequences by similarity using raw sequences. Note: For dataset-based clustering, use cluster_dataset_sequences instead. Args: sequences: Dictionary mapping sequence IDs to sequences (raw strings) identity_threshold: Identity threshold for clustering (0-1) method: Clustering method ("single", "complete", "average") Returns: Dictionary with cluster assignments | `analysis/sequence.py` |
| `sequence_detect_mutations` | Detect mutations between wild-type and variant sequences using raw sequences. Note: For entity-based mutation detection, use sequence_detect_mutations_between_entities instead. Args: wild_type: Wild-type sequence (raw string) variant: Variant sequence (raw string) numbering_start: Position numbering start (default 1) Returns: Dictionary with detected mutations | `analysis/sequence.py` |
| `sequence_detect_mutations_between_entities` | Detect mutations between two sequence entities. Args: reference_entity: Reference sequence entity ID variant_entity: Variant sequence entity ID include_positions: Include detailed position information Returns: Dictionary with detected mutations | `analysis/sequence.py` |
| `extract_sequence_from_structure_batch` | Extract sequences from all structures in a dataset. This is a batch operation that processes multiple structures and extracts their sequences, optionally saving them as a new sequence dataset. Args: dataset_name: Name of the structure dataset chain_selection: Chain to extract (e.g., "A"), or None for all chains save_as_dataset: Optional name for saving extracted sequences Returns: Dictionary with extracted sequences | `analysis/sequence.py` |
| `sequence_find_conserved_regions` | Find conserved regions across multiple sequences using raw sequences. Note: For dataset-based conservation analysis, use sequence_find_conserved_regions_in_dataset instead. Args: sequences: Dictionary mapping sequence IDs to sequences (raw strings) min_conservation: Minimum conservation threshold (0-1) min_length: Minimum length of conserved region Returns: Dictionary with conserved regions | `analysis/sequence.py` |
| `sequence_find_conserved_regions_in_dataset` | Find conserved regions across all sequences in a dataset. Args: dataset_name: Name of the sequence dataset min_conservation: Minimum conservation threshold (0-1) min_length: Minimum length for conserved regions Returns: Dictionary with conserved regions | `analysis/sequence.py` |
| `list_sequence_entities` | List registered sequence entities with optional pagination. | `analysis/sequence.py` |
| `load_sequence` | Load a sequence entity and return summary details. | `analysis/sequence.py` |
| `load_sequence_dataset` | Load a sequence dataset and summarize its members. | `analysis/sequence.py` |
| `sequence_align_mmseqs` | Run MMseqs pairwise alignment over a collection of sequences. | `analysis/sequence.py` |
| `sequence_align_to_reference` | Align multiple sequences against a reference using SequenceProcessor helpers. | `analysis/sequence.py` |
| `sequence_annotate_with_grn` | Annotate sequences with GRN positions using bundled references. | `analysis/sequence.py` |
| `sequence_compute_conservation` | Compute per-position conservation across aligned sequences. | `analysis/sequence.py` |
| `sequence_compute_linkage` | Compute residue linkage using mutual information. | `analysis/sequence.py` |
| `sequence_create_mutant_library` | Generate a mutant library and optionally persist it. | `analysis/sequence.py` |
| `sequence_dataset_stats` | Summarize a sequence dataset (entity counts, length stats). | `analysis/sequence.py` |
| `sequence_export_dataset` | Materialize a dataset FASTA inside the managed Protos data root (no custom paths). | `analysis/sequence.py` |
| `sequence_export_entity` | Export a single sequence entity to FASTA. | `analysis/sequence.py` |
| `sequence_find_best_match` | Find the best-matching reference sequence for a query. | `analysis/sequence.py` |
| `sequence_save_sequences` | Persist multiple sequences via SequenceProcessor.save_sequences. | `analysis/sequence.py` |
| `translate_sequence` | Translate DNA/RNA sequence to protein. Args: dna_sequence: DNA or RNA sequence genetic_code: NCBI genetic code table (1=standard) to_stop: Stop translation at first stop codon Returns: Dictionary with translation results | `analysis/sequence.py` |

### Structure Analysis
| Tool | Description | Module |
| --- | --- | --- |
| `align_protein_structures` | Align two protein structures using CEalign algorithm. This tool performs structural alignment of two proteins and returns the transformation matrix and RMSD. The alignment is performed on selected atoms (default: CA atoms). Args: reference_pdb: PDB ID of the reference structure mobile_pdb: PDB ID of the structure to align atom_selection: Atom type to use for alignment ("CA", "backbone", "all") chain_selection: Specific chain to align (e.g., "A"), or None for all window_size: Window size for CEalign algorithm max_gap: Maximum gap size for CEalign algorithm Returns: Dictionary with alignment results including RMSD and transformation | `analysis/structure.py` |
| `structure_analyze_binding_pocket` | Analyze the binding pocket around a ligand including volume estimation. This tool provides comprehensive binding pocket analysis including: - Binding site residue identification - Pocket volume estimation using convex hull - Residue conservation potential - Pocket properties (hydrophobicity, charge distribution) Args: pdb_id: PDB identifier ligand_name: Three-letter ligand code chain_id: Optional chain specification for the ligand cutoff: Distance cutoff for binding site definition (Angstroms) include_volume: Whether to calculate pocket volume Returns: Dictionary with binding pocket analysis | `analysis/structure.py` |
| `structure_analyze_ligand_interactions` | Analyze detailed protein-ligand interactions including multiple interaction types. This tool provides comprehensive interaction analysis beyond simple distance cutoffs, including hydrogen bonds, hydrophobic contacts, pi-stacking, salt bridges, and water-mediated interactions. Args: pdb_id: PDB identifier ligand_name: Three-letter ligand code (e.g., 'ATP', 'HEM') chain_id: Optional chain specification for the ligand detailed: If True, return detailed interaction lists; if False, only summary Returns: Dictionary with comprehensive interaction analysis including: - Hydrogen bonds with donor/acceptor information - Hydrophobic contacts - Water-mediated bridges - Pi-stacking interactions - Salt bridges - Binding site residue summary | `analysis/structure.py` |
| `calculate_structure_properties` | Calculate basic structural properties. Args: pdb_id: PDB identifier chain_id: Optional specific chain Returns: Dictionary with structural properties | `analysis/structure.py` |
| `calculate_structure_rmsd_matrix` | Calculate RMSD matrix between multiple structures. This tool performs pairwise structural alignments between multiple proteins and returns an RMSD matrix. Can operate in all-vs-all mode or one-vs-all mode. Args: pdb_ids: List of PDB IDs to compare atom_selection: Atom type to use for alignment ("CA", "backbone", "all") chain_selection: Specific chain to align, or None for all mode: Comparison mode ("all_vs_all" or "one_vs_all") Returns: Dictionary with RMSD matrix and statistics | `analysis/structure.py` |
| `structure_compare_ligand_binding_sites` | Compare binding sites across multiple protein-ligand complexes. This tool analyzes binding site conservation across structures, useful for: - Understanding binding mode conservation - Identifying key interaction residues - Comparing different ligands in the same pocket - Analyzing conformational changes upon ligand binding Args: structures: List of dicts with 'pdb_id', 'ligand_name', and optional 'chain_id' cutoff: Distance cutoff for binding site definition (Angstroms) similarity_threshold: Jaccard similarity threshold for grouping similar sites Returns: Dictionary with binding site comparison results including: - Pairwise binding site similarities - Conserved residues across all structures - Binding site clustering - Key differences between sites | `analysis/structure.py` |
| `structure_extract_all_chains_from_dataset` | Extract sequences from all structures in a dataset. This tool processes an entire structure dataset, extracting sequences from all chains (or filtered chains) and optionally saving them as a FASTA file. Args: dataset_name: Name of the structure dataset save_as_fasta: Name to save all sequences as FASTA file chain_filter: List of chain IDs to include (e.g., ['A', 'B']) Returns: Dictionary with extraction results and statistics | `analysis/structure.py` |
| `extract_ligands_from_structure` | Extract all ligands from a protein structure. Args: pdb_id: PDB identifier exclude_common: Exclude water, ions, common molecules min_atoms: Minimum atoms for a ligand Returns: Dictionary with ligand information | `analysis/structure.py` |
| `extract_sequence_from_structure` | Extract amino acid sequence from a protein structure. Args: pdb_id: PDB identifier of the structure chain_id: Chain ID to extract sequence from save_to_sequence: If True, save to sequence processor Returns: Dictionary with extracted sequence | `analysis/structure.py` |
| `extract_sequences_from_structure` | Extract amino acid sequences from protein chains in a structure. This tool extracts sequences from specified chains (or all chains) in a protein structure and optionally saves them as a FASTA file using the sequence processor. Args: pdb_id: PDB ID of the structure chain_ids: List of chain IDs to extract (None for all chains) save_as_fasta: Name to save sequences as FASTA file (without extension) Returns: Dictionary with extracted sequences and metadata | `analysis/structure.py` |
| `structure_extract_water_molecules` | List water molecules treated as ligand-like records. | `analysis/structure.py` |
| `get_all_sequences_from_structure` | Extract sequences from all chains in a structure. Args: pdb_id: PDB identifier save_to_sequence: If True, save all to sequence processor Returns: Dictionary with sequences for all chains | `analysis/structure.py` |
| `structure_get_binding_site_residues` | Get residues in the binding site of a ligand. Args: pdb_id: PDB identifier ligand_name: Three-letter ligand code chain_id: Optional chain specification cutoff: Distance cutoff in Angstroms Returns: Dictionary with binding site residues | `analysis/structure.py` |
| `structure_get_ca_coordinates` | Get C-alpha atom coordinates for a chain. Args: pdb_id: PDB identifier chain_id: Chain ID Returns: Dictionary with coordinate array | `analysis/structure.py` |
| `structure_get_sequences_and_save_fasta` | Extract sequences from structures using get_seq_dict/get_chain_dict and save as FASTA. This helper collects chain sequences for the provided structures and saves them as a FASTA file using the sequence processor. The `use_chain_dict` flag is kept for backward compatibility but no longer changes behaviour (chain extraction always uses the unified `collect_chain_sequences`). Args: pdb_ids: List of PDB IDs to process fasta_name: Name for the output FASTA file (without extension) use_chain_dict: Deprecated; retained for backwards compatibility Returns: Dictionary with extraction results | `analysis/structure.py` |
| `get_structure_chains` | Get list of chains in a structure. Args: pdb_id: PDB identifier Returns: Dictionary with chain information | `analysis/structure.py` |
| `structure_graph_generate_from_dataset` | Generate graphs for each structure in a dataset using GraphProcessor. | `analysis/structure.py` |
| `structure_graph_load_entity` | Load a graph entity and summarize its contents. | `analysis/structure.py` |
| `list_structure_entities` | List registered structure entities with optional pagination. | `analysis/structure.py` |
| `load_structure` | Load a structure entity and return summary details. | `analysis/structure.py` |
| `load_structure_dataset` | Load a structure dataset and summarize its members. | `analysis/structure.py` |
| `structure_register_chain_sequences_from_dataset` | Register per-chain sequences for all structures in a dataset. | `analysis/structure.py` |
| `structure_align_to_reference` | Align structures via `StructureProcessor.align_and_record` and surface registry artifacts. | `analysis/structure.py` |
| `structure_annotate_entities` | Apply chain-level and optional structure-level annotations. | `analysis/structure.py` |
| `structure_apply_grn_annotations` | Map GRN annotations from a table onto structure residues. | `analysis/structure.py` |
| `structure_prepare_grn_annotations` | Extract chains, filter/align them, annotate with GRN, and project annotations back onto the provided structures in one call. | `analysis/structure.py` |
| `structure_collect_chain_sequences` | Collect per-chain sequences for one or more structures. | `analysis/structure.py` |
| `structure_compute_embedding_similarity` | Compute per-residue embedding similarity relative to a reference chain. | `analysis/structure.py` |
| `structure_compute_water_networks` | Analyze water-mediated residue networks for the given structures. | `analysis/structure.py` |
| `structure_dataset_stats` | Summarize a structure dataset (entity counts, metadata). | `analysis/structure.py` |
| `structure_export_dataset` | Export all structures in a dataset. | `analysis/structure.py` |
| `structure_export_entity` | Export a single structure entity. | `analysis/structure.py` |
| `structure_filter_dataset` | Filter structures in a dataset by column values and optionally register the results. | `analysis/structure.py` |
| `structure_list_dataset_sequences` | List sequences related to each structure in a dataset. | `analysis/structure.py` |
| `superimpose_structures` | Superimpose one structure onto another and save the result. This tool aligns a mobile structure onto a reference structure and saves the transformed coordinates as a new entity. Args: reference_pdb: PDB ID of the reference structure mobile_pdb: PDB ID of the structure to superimpose output_name: Name for the superimposed structure entity atom_selection: Atoms to use for alignment ("CA", "backbone", "all") chain_selection: Specific chain to align, or None for all Returns: Dictionary with superposition results | `analysis/structure.py` |

## Cross-Processor Workflows
### Model Manager
| Tool | Description | Module |
| --- | --- | --- |
| `describe_model` | Return full model card metadata for a specific model. | `model/manager.py` |
| `model_lambda_prepare_resources` | Copy and normalize Lambda model resources into the active data root. | `model/manager.py` |
| `model_lambda_run` | Register sequences (if provided), annotate GRN, and execute Lambda prediction in one call. | `model/manager.py` |
| `list_models` | List registered model cards available through ModelManager. | `model/manager.py` |

## Data IO
### Dataset Operations
| Tool | Description | Module |
| --- | --- | --- |
| `copy_dataset` | Copy a dataset to a new name using `DatasetManager.copy_dataset`. | `dataset/operations.py` |
| `create_dataset` | Create a dataset from registered entity names. | `dataset/operations.py` |
| `dataset_entities` | Return the entity names associated with a dataset. | `dataset/operations.py` |
| `dataset_info` | Return metadata and current entity coverage for a dataset. | `dataset/operations.py` |
| `delete_dataset` | Delete a dataset definition. | `dataset/operations.py` |
| `export_dataset` | Export a dataset using the processor's `export_dataset` helper. | `dataset/operations.py` |
| `list_datasets` | List datasets known to a processor. | `dataset/operations.py` |
| `load_dataset` | Load dataset members via the processor for quick inspection. | `dataset/operations.py` |
| `merge_datasets` | Merge multiple datasets into a single dataset using `DatasetManager.merge_datasets`. | `dataset/operations.py` |
| `refresh_all_datasets` | Refresh entity names for all datasets of a processor. | `dataset/operations.py` |
| `refresh_dataset_entities` | Refresh entity names in a dataset using `DatasetManager.refresh_dataset_entities`. | `dataset/operations.py` |
| `register_chembl_ligand_dataset` | Install the packaged ChEMBL ligand reference dataset. | `dataset/operations.py` |
| `register_gpcr_property_dataset` | Install the packaged GPCR ligand-binding property dataset. | `dataset/operations.py` |
| `register_gpcr_sequence_dataset` | Install the packaged GPCR agonist/antagonist sequence dataset. | `dataset/operations.py` |
| `register_rhodopsin_graph_dataset` | Install the packaged rhodopsin residue graph dataset. | `dataset/operations.py` |
| `register_rhodopsin_structure_dataset` | Install the packaged rhodopsin state structure dataset. | `dataset/operations.py` |
| `update_dataset` | Add/remove entities and/or merge metadata into an existing dataset. | `dataset/operations.py` |

### Entity Discovery
| Tool | Description | Module |
| --- | --- | --- |
| `entity_info` | Get comprehensive information about an entity. Shows all formats where the entity exists and associated metadata. Args: entity_name: Name of the entity to look up Returns: Dictionary with entity information across all formats | `entity/discovery.py` |
| `entity_list_entities` | List all entities available for a specific processor type. Args: processor_type: Type of processor (structure, sequence, grn, etc.) limit: Maximum number of entities to return offset: Number of entities to skip Returns: Dictionary with entity list and metadata | `entity/discovery.py` |
| `entity_search_entities` | Search for entities across one or more processor types. Args: query: Search query (substring or regex) processor_types: List of processor types to search (None = all) regex: Whether to treat query as regex pattern case_sensitive: Whether search is case sensitive Returns: Dictionary with search results grouped by processor type | `entity/discovery.py` |

### Entity Operations
| Tool | Description | Module |
| --- | --- | --- |
| `delete_entity` | Delete an entity from specified formats. Args: name: Entity name formats: List of formats to delete from Returns: Dictionary with deletion status | `entity/operations.py` |
| `download_entity` | Download an entity from an external source. Args: entity_id: ID of entity to download (e.g., PDB ID) processor_type: Type of processor to use overwrite: Whether to overwrite existing entity Returns: Dictionary with download status | `entity/operations.py` |
| `load_entity` | Load an entity's data. Args: name: Entity name format: Processor type (structure, sequence, etc.) output_format: How to return data (json, base64, summary) Returns: Dictionary with entity data | `entity/operations.py` |
| `save_entity` | Save a new entity or update existing one. Args: name: Entity name data: Entity data (JSON object, JSON string, or base64 encoded string) format: Processor type metadata: Optional metadata to store data_encoding: How data is encoded (json or base64) Returns: Dictionary with save status | `entity/operations.py` |

## Guidance
### Interactive Guide
| Tool | Description | Module |
| --- | --- | --- |
| `guide_explain_concept` | Get detailed explanation of Protos concepts. Concepts: - entity: What is an entity in Protos? - processor: What are processors and how do they work? - dataset: Understanding datasets vs entities - grn: Generic Residue Numbering system - paths: How Protos manages file paths - formats: Supported data formats Args: concept: Concept to explain Returns: Detailed explanation with examples | `guide.py` |
| `protos_guide` | Get interactive guidance on using Protos. Topics available: - overview: General introduction to Protos - processors: Understanding the processor system - data_management: Core data management principles - entity_registry: How entities are tracked - workflows: Common analysis workflows - best_practices: Best practices and tips Args: topic: Specific topic to get help on (optional) Returns: Guidance information and examples | `guide.py` |
| `guide_workflow_example` | Get step-by-step examples of common Protos workflows. Workflow types: - structure_analysis: Basic structure loading and analysis - grn_assignment: GRN assignment for protein families - ligand_analysis: Ligand extraction and analysis - sequence_alignment: Sequence alignment workflows - property_integration: Adding experimental properties - cross_format: Working across multiple data formats Args: workflow_type: Type of workflow example to retrieve Returns: Step-by-step workflow with MCP tool calls | `guide.py` |
| `guide_tool_help` | Query `tool_usage.yaml` for enriched descriptions, arguments, and workflow context for a specific tool (or list all entries). | `guide.py` |

## Loader Tools
### Sequence Loader
| Tool | Description | Module |
| --- | --- | --- |
| `sequence_download` | Download a FASTA source (local path or UniProt) and register it. | `loader/sequence.py` |
| `sequence_inspect_identifier` | Parse an identifier using SequenceLoader without downloading. | `loader/sequence.py` |
| `sequence_register_records` | Register sequences provided inline (e.g., from another tool). | `loader/sequence.py` |

### Entity Download
| Tool | Description | Module |
| --- | --- | --- |
| `download_entity` | Download a single entity (structure or sequence) and register it with the corresponding processor. | `entity/operations.py` |
| `download_entities` | Download multiple entities and optionally create/update a dataset. | `entity/operations.py` |
| `download_sources` | List available download sources/aliases for the requested processor type. | `entity/operations.py` |

## Runtime Config
### Config Helpers
| Tool | Description | Module |
| --- | --- | --- |
| `config_reset_data` | Reset the shared data directory and registry state. | `config.py` |
| `config_get_data_root` | Report the currently configured Protos data root. | `config.py` |
| `config_initialize_data` | Ensure the configured data root exists with the expected layout. | `config.py` |
| `config_set_data_root` | Update the Protos data root before any processors are used. | `config.py` |
