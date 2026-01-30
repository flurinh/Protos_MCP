"""
Protos workflow guide and helper tools.

These tools provide interactive guidance for using Protos, explaining core concepts,
data management principles, and providing workflow examples.
"""

from typing import Dict, List, Optional, Any
import json
from pathlib import Path

import yaml

from .base import BaseTool


class ProtoGuideTools(BaseTool):
    """Interactive guide and helper tools for Protos workflows."""

    def __init__(self, context):
        super().__init__(context)
        self._tool_usage_cache: Optional[Dict[str, Any]] = None

    @property
    def catalog_group(self) -> str:  # noqa: D401 - inherited docs adequate
        return "guide"

    def register(self, server):
        """Register guide tools with the server."""

        @server.tool()
        def protos_guide(ctx, topic: Optional[str] = None) -> Dict:
            """
            Get interactive guidance on using Protos.
            
            Topics available:
            - overview: General introduction to Protos
            - processors: Understanding the processor system
            - data_management: Core data management principles
            - entity_registry: How entities are tracked
            - workflows: Common analysis workflows
            - best_practices: Best practices and tips
            
            Args:
                topic: Specific topic to get help on (optional)
                
            Returns:
                Guidance information and examples
            """
            guides = {
                "overview": self._get_overview_guide(),
                "processors": self._get_processors_guide(),
                "data_management": self._get_data_management_guide(),
                "entity_registry": self._get_entity_registry_guide(),
                "workflows": self._get_workflows_guide(),
                "best_practices": self._get_best_practices_guide(),
                "tools": self._get_tool_catalog_guide(),
                "grn_annotation": self._get_grn_annotation_guide(),
                "llm_safe_mode": self._get_llm_safe_mode_guide(),
            }

            if topic and topic in guides:
                return self.format_success({
                    "topic": topic,
                    "content": guides[topic],
                    "related_topics": [t for t in guides.keys() if t != topic]
                })

            # Return topic list if no specific topic requested
            return self.format_success({
                "available_topics": list(guides.keys()),
                "description": "Use protos_guide with a specific topic for detailed information",
                "quick_start": self._get_quick_start()
            })
        self.register_tool_metadata(
            function=protos_guide,
            name="protos_guide",
            description="Interactive guidance on Protos processors, data management, and workflows.",
            parameters=[{"name": "topic", "type": "str", "optional": True}],
            returns={"fields": ["available_topics", "content"]},
            tags=["guide"],
        )
        
        @server.tool()
        def guide_workflow_example(ctx, workflow_type: str) -> Dict:
            """
            Get step-by-step examples of common Protos workflows.
            
            Workflow types:
            - structure_analysis: Basic structure loading and analysis
            - grn_assignment: GRN assignment for protein families
            - ligand_analysis: Ligand extraction and analysis
            - sequence_alignment: Sequence alignment workflows
            - property_integration: Adding experimental properties
            - cross_format: Working across multiple data formats
            
            Args:
                workflow_type: Type of workflow example to retrieve
                
            Returns:
                Step-by-step workflow with MCP tool calls
            """
            workflows = {
                "structure_analysis": self._get_structure_workflow(),
                "grn_assignment": self._get_grn_workflow(),
                "ligand_analysis": self._get_ligand_workflow(),
                "sequence_alignment": self._get_sequence_workflow(),
                "property_integration": self._get_property_workflow(),
                "cross_format": self._get_cross_format_workflow()
            }
            
            if workflow_type not in workflows:
                return self.format_error(
                    f"Unknown workflow type: {workflow_type}",
                    f"Available workflows: {', '.join(workflows.keys())}"
                )
            
            return self.format_success({
                "workflow_type": workflow_type,
                "steps": workflows[workflow_type],
                "tips": self._get_workflow_tips(workflow_type)
            })
        self.register_tool_metadata(
            function=guide_workflow_example,
            name="guide_workflow_example",
            description="Retrieve MCP-tool equivalents for canonical Protos workflows.",
            parameters=[{"name": "workflow_type", "type": "str"}],
            returns={"fields": ["steps"]},
            tags=["guide", "workflow"],
        )
        
        @server.tool()
        def guide_explain_concept(ctx, concept: str) -> Dict:
            """
            Get detailed explanation of Protos concepts.
            
            Concepts:
            - entity: What is an entity in Protos?
            - processor: What are processors and how do they work?
            - dataset: Understanding datasets vs entities
            - grn: Generic Residue Numbering system
            - paths: How Protos manages file paths
            - formats: Supported data formats
            
            Args:
                concept: Concept to explain
                
            Returns:
                Detailed explanation with examples
            """
            concepts = {
                "entity": self._explain_entity(),
                "processor": self._explain_processor(),
                "dataset": self._explain_dataset(),
                "grn": self._explain_grn(),
                "paths": self._explain_paths(),
                "formats": self._explain_formats()
            }
            
            if concept not in concepts:
                return self.format_error(
                    f"Unknown concept: {concept}",
                    f"Available concepts: {', '.join(concepts.keys())}"
                )
            
            return self.format_success({
                "concept": concept,
                "explanation": concepts[concept]
            })
        self.register_tool_metadata(
            function=guide_explain_concept,
            name="guide_explain_concept",
            description="Explain a Protos concept (entity, processor, dataset, etc.).",
            parameters=[{"name": "concept", "type": "str"}],
            returns={"fields": ["explanation"]},
            tags=["guide", "concept"],
        )

        @server.tool()
        def guide_tool_help(ctx, tool_name: Optional[str] = None) -> Dict:
            """Return usage guidance for registered MCP tools."""

            catalog_dict = self.tool_catalog.to_dict()
            tools = {entry["name"]: entry for entry in catalog_dict.get("tools", [])}

            if not tool_name:
                return self.format_success({
                    "tools": sorted(tools.keys()),
                    "catalog_path": str(self.context.config.tool_catalog_path),
                })

            normalized = tool_name.lower()
            entry = self.tool_catalog.resolve(tool_name)
            if entry is None:
                matches = [name for name in tools if normalized in name.lower()]
                suggestion = (
                    f"Available tools: {', '.join(sorted(tools))}"
                    if not matches
                    else f"Did you mean: {', '.join(matches)}?"
                )
                return self.format_error(
                    f"Unknown tool '{tool_name}'",
                    suggestion,
                )

            payload = entry.to_dict()
            payload["catalog_path"] = str(self.context.config.tool_catalog_path)

            usage_notes = self._load_tool_usage()
            extras = usage_notes.get(entry.name)
            if extras:
                payload["usage_notes"] = extras

            return self.format_success(payload)

        self.register_tool_metadata(
            function=guide_tool_help,
            name="guide_tool_help",
            description="Surface catalog metadata (and optional usage notes) for any registered tool.",
            parameters=[{"name": "tool_name", "type": "str", "optional": True}],
            returns={"fields": ["description", "parameters", "catalog_path"]},
            tags=["guide", "tools"],
        )

    def _load_tool_usage(self) -> Dict[str, Any]:
        if self._tool_usage_cache is not None:
            return self._tool_usage_cache

        usage_path = Path(__file__).resolve().parents[1] / "tool_usage.yaml"
        if not usage_path.exists():
            self._tool_usage_cache = {}
            return self._tool_usage_cache

        try:
            data = yaml.safe_load(usage_path.read_text()) or {}
        except yaml.YAMLError:
            data = {}

        if not isinstance(data, dict):
            data = {}

        self._tool_usage_cache = {str(key): value for key, value in data.items() if isinstance(key, str)}
        return self._tool_usage_cache

    def _get_overview_guide(self) -> Dict:
        """Get overview guide content."""
        return {
            "title": "Protos Overview",
            "description": "Protos is a comprehensive structural biology framework for managing and analyzing protein data",
            "key_features": [
                "Zero-configuration data management",
                "Unified entity tracking across formats",
                "Modular processor architecture",
                "Seamless format interoperability"
            ],
            "core_principles": [
                "Entities are tracked by human-readable names (e.g., '1ubq', 'EGFR_HUMAN')",
                "Processors handle all data operations - never manipulate files directly",
                "Datasets organize collections of entities for batch processing",
                "All paths are managed internally - you only work with entity names"
            ],
            "quick_example": {
                "description": "Download and analyze a protein structure",
                "steps": [
                    "download_entity('1ubq', source='pdb', processor_type='structure')",
                    "load_entity('1ubq', format='structure')",
                    "extract_sequence_from_structure('1ubq', chain_id='A')"
                ]
            }
        }
    
    def _get_processors_guide(self) -> Dict:
        """Get processors guide content."""
        return {
            "title": "Understanding Processors",
            "description": "Each processor owns the zero-config load/list/save APIs for its data type. Loaders pull data in; list/load tools inspect what you already have; analysis helpers mirror the test workflows.",
            "processors": {
                "structure": {
                    "handles": "3D structures (PDB/mmCIF)",
                    "list_load": [
                        "list_structure_entities",
                        "load_structure",
                        "load_structure_dataset",
                        "structure_dataset_stats",
                        "structure_filter_dataset",
                    ],
                    "analysis": [
                        "structure_collect_chain_sequences",
                        "structure_align_to_reference",
                        "structure_extract_water_molecules",
                        "structure_compute_water_networks",
                        "structure_apply_grn_annotations",
                        "structure_graph_generate_from_dataset",
                        "structure_graph_load_entity",
                    ],
                    "binding_site": [
                        "structure_get_binding_site_residues",
                        "structure_analyze_binding_pocket",
                        "structure_analyze_ligand_interactions",
                        "structure_compare_ligand_binding_sites",
                    ],
                    "export": [
                        "structure_export_entity",
                        "structure_export_dataset",
                    ],
                    "loaders": ["download_entity", "download_entities", "download_sources"],
                    "note": "Structure DataFrames never exposed; use analysis/binding_site tools for specific queries.",
                },
                "sequence": {
                    "handles": "Protein / DNA / RNA sequences",
                    "list_load": [
                        "list_sequence_entities",
                        "load_sequence",
                        "load_sequence_dataset",
                        "sequence_dataset_stats",
                    ],
                    "analysis": [
                        "sequence_align_to_reference",
                        "sequence_align_mmseqs",
                        "sequence_compute_conservation",
                        "sequence_create_mutant_library",
                        "sequence_annotate_with_grn",
                    ],
                    "export": [
                        "sequence_save_sequences",
                        "sequence_export_dataset",
                        "sequence_export_entity",
                    ],
                    "loaders": [
                        "download_entity",
                        "download_entities",
                        "download_sources",
                        "sequence_download",
                        "sequence_register_records",
                    ],
                },
                "molecule": {
                    "handles": "Small-molecule ligands",
                    "list_load": [
                        "list_ligand_entities",
                        "load_ligand_entity",
                        "load_ligand_dataset",
                    ],
                    "analysis": [
                        "ligand_compute_interactions",
                        "structure_analyze_ligand_interactions",
                        "ligand_calculate_molecular_properties",
                        "search_similar_ligands",
                        "filter_drug_like_ligands",
                    ],
                    "export": [
                        "ligand_register_smiles",
                        "ligand_record_interactions",
                        "ligand_import_smiles_structures",
                        "ligand_import_sdf",
                    ],
                    "loaders": [
                        "extract_ligands_from_structure",
                        "get_protein_ligands_from_chembl",
                        "import_sdf_to_protos",
                    ],
                    "note": "Small molecule data (SMILES, properties) is always returned in full - compact format.",
                },
                "embedding": {
                    "handles": "Sequence embeddings (ESM, ANKH, etc.)",
                    "list_load": [
                        "embedding_list_models",
                        "embedding_load_dataset",
                    ],
                    "analysis": [
                        "embedding_cosine_similarity",
                    ],
                    "export": [
                        "embedding_generate",
                    ],
                    "loaders": [],
                },
                "grn": {
                    "handles": "Generic Residue Numbering tables",
                    "list_load": [
                        "list_grn_tables",
                        "load_grn_reference_table",
                        "load_grn_table",
                    ],
                    "analysis": [
                        "grn_annotate_sequences",
                        "assign_grn_to_dataset",
                        "get_grn_table_stats",
                        "grn_compare_conservation",
                    ],
                    "query": [
                        "grn_query_entity",
                        "grn_query_position",
                    ],
                    "export": [
                        "record_grn_table",
                    ],
                    "loaders": [],
                    "note": "Use query tools to inspect specific entities or positions without loading full tables.",
                },
                "property": {
                    "handles": "Tabular properties / annotations",
                    "list_load": [
                        "list_property_tables",
                        "load_property_table",
                        "load_property_rows",
                    ],
                    "analysis": [
                        "get_property_statistics",
                        "filter_entities_by_property",
                    ],
                    "export": [
                        "create_property_table",
                        "record_property_rows",
                        "export_property_table",
                    ],
                    "loaders": [],
                },
            },
            "key_principle": "Use loader tools to download new data, then switch to list/load helpers for inspection and processor-native analysis tools for transformations."
        }
    
    def _get_data_management_guide(self) -> Dict:
        """Get data management guide content."""
        return {
            "title": "Data Management in Protos",
            "core_rules": [
                {
                    "rule": "Never specify file paths",
                    "explanation": "Protos manages all paths internally through ProtosPaths",
                    "example": "Use 'load_entity(\"1ubq\")' not 'load_file(\"/path/to/1ubq.cif\")'"
                },
                {
                    "rule": "Entities are the primary interface",
                    "explanation": "All data is accessed through entity names, not files",
                    "example": "Entity '1ubq' might have structure, sequence, and property data"
                },
                {
                    "rule": "Processors handle format conversion",
                    "explanation": "Each processor knows how to save/load its data format",
                    "example": "StructureProcessor handles PDB/mmCIF, SequenceProcessor handles FASTA"
                },
                {
                    "rule": "Datasets organize entities",
                    "explanation": "Datasets are collections of entity names for batch processing",
                    "example": "Create a dataset of GPCRs for comparative analysis"
                }
            ],
            "data_flow": {
                "download": "External source → Processor → Entity Registry → Local storage",
                "load": "Entity name → Processor → ProtosPaths → File data → Parsed object",
                "save": "Data object → Processor → ProtosPaths → File storage → Registry update"
            },
            "packaged_datasets": {
                "sequence": "register_gpcr_sequence_dataset",
                "structure": "register_rhodopsin_structure_dataset",
                "molecule": "register_chembl_ligand_dataset",
                "property": "register_gpcr_property_dataset",
                "graph": "register_rhodopsin_graph_dataset",
                "description": "These helpers copy the embedded reference datasets into the current data root and register them with the appropriate processor."
            }
        }

    def _get_tool_catalog_guide(self) -> Dict[str, Any]:
        """Summarise tools registered in the shared catalog."""

        catalog = self.tool_catalog
        groups = catalog.list_groups()
        counts = {group: len(names) for group, names in groups.items()}
        highlight = {
            group: names[:6] for group, names in groups.items()
        }
        return {
            "title": "Tool Catalog",
            "description": "Automatically generated map of MCP tools grouped by their domain.",
            "group_counts": counts,
            "sample_tools": highlight,
            "usage": "Use context_status and context_list to inspect artifacts after each tool call; combine loaders with dataset operations for reproducible workflows.",
        }
    
    def _get_entity_registry_guide(self) -> Dict:
        """Get entity registry guide content."""
        return {
            "title": "Entity Registry System",
            "description": "The entity registry tracks all biological objects across different data formats",
            "key_concepts": [
                {
                    "concept": "Universal tracking",
                    "description": "One entity can have multiple data formats",
                    "example": "Entity '1ubq' might have structure, sequence, and embedding data"
                },
                {
                    "concept": "Human-readable names",
                    "description": "Entities use meaningful identifiers",
                    "examples": ["PDB IDs: '1ubq', '7tm1'", "UniProt IDs: 'EGFR_HUMAN', 'P00533'"]
                },
                {
                    "concept": "Automatic registration",
                    "description": "Entities are registered when downloaded or saved",
                    "note": "No manual registration needed"
                }
            ],
            "operations": {
                "entity_list_entities": "See all entities for a processor type",
                "entity_search_entities": "Find entities across all processors",
                "entity_info": "Get comprehensive information about an entity"
            }
        }

    def _get_grn_annotation_guide(self) -> Dict[str, Any]:
        """Provide a focused guide on sequence/structure GRN annotation."""

        return {
            "title": "GRN Annotation Workflow",
            "description": "How to extract chains, align them to references, annotate with GRN, and project results back onto structures.",
            "atomic_steps": [
                "structure_register_chain_sequences_from_dataset",
                "align_sequences_by_id (or sequence_find_best_match)",
                "sequence_annotate_with_grn",
                "structure_apply_grn_annotations",
            ],
            "composite_tool": "structure_prepare_grn_annotations",
            "usage": {
                "structure_prepare_grn_annotations": {
                    "purpose": "Runs the entire chain extraction → filtering → GRN annotation → structure mapping pipeline in one call.",
                    "arguments": {
                        "structure_ids": "List of PDB IDs already registered in the structure processor.",
                        "reference_table": "GRN reference (e.g., 'gpcrdb_ref').",
                        "protein_family": "Family configuration (e.g., 'gpcr_a').",
                        "reference_sequence_entity": "Optional chain name such as '5d5a_chain_A'; defaults to the first extracted chain.",
                        "alignment_threshold": "Normalized alignment score (0-1) for keeping chains in the GPCR subset.",
                    },
                    "produces": [
                        "Filtered sequence dataset name",
                        "GRN table registered under data/grn/tables",
                        "Annotation counts per structure/chain",
                    ],
                    "follow_up": "Use grn_query_entity and grn_query_position to inspect results without loading full tables.",
                }
            },
            "query_tools": {
                "grn_query_entity": {
                    "purpose": "Get GRN annotations for a single entity (e.g., 'ADRB2_HUMAN').",
                    "use_case": "Inspect what residues are assigned to each GRN position for one sequence.",
                    "example": "grn_query_entity(grn_table='gpcr_grn', entity_id='ADRB2_HUMAN', positions=['1.50', '3.50'])",
                },
                "grn_query_position": {
                    "purpose": "Get amino acid distribution at specific GRN positions across all entities.",
                    "use_case": "Conservation analysis - which AAs appear at functionally important positions.",
                    "example": "grn_query_position(grn_table='gpcr_grn', positions=['1.50', '2.50', '3.50', '7.50'])",
                },
            },
            "tips": [
                "Ensure structures are downloaded via download_entities before running GRN steps.",
                "Lower alignment_threshold (e.g., 0.6) if no chains pass the similarity filter.",
                "When orchestrating manually, keep the chain entity names (e.g., '3sn6_chain_A') consistent so they match GRN table rows.",
                "Use grn_query_entity to inspect individual sequences; use grn_query_position for conservation analysis.",
                "sequence_annotate_with_grn returns statistics only; use query tools for detailed inspection.",
            ],
        }

    def _get_llm_safe_mode_guide(self) -> Dict[str, Any]:
        """Guide for understanding LLM-safe mode data output patterns."""

        return {
            "title": "LLM-Safe Mode - Data Output Patterns",
            "description": "Tools operate in LLM-safe mode by default, returning summaries and statistics instead of raw data to prevent context flooding.",
            "core_principle": "Defaults are safe; explicit requests are honored.",
            "what_is_restricted": {
                "structure_dataframes": "Never exposed directly - use statistics and atom previews instead",
                "full_sequences": "Return length and preview; use include_sequence=True when needed",
                "raw_embeddings": "Never returned - use similarity tools for analysis",
                "large_grn_tables": "Return statistics; use grn_query_* tools for inspection",
                "alignment_text": "Return scores; use include_alignment=True when needed",
            },
            "what_is_unrestricted": {
                "binding_pocket_analysis": "Full residue data returned - essential for reasoning",
                "ligand_interactions": "Full contact data returned - needed for drug design",
                "small_molecule_data": "SMILES, properties always included - compact format",
                "statistics_and_counts": "Always included in responses",
                "error_messages": "Always detailed with suggestions",
            },
            "how_to_get_full_data": {
                "sequences": "load_sequence(id, include_sequence=True)",
                "alignments": "align_sequences_by_id(e1, e2, include_alignment=True)",
                "datasets": "load_sequence_dataset(name, include_sequences=True)",
                "grn_details": "Use grn_query_entity() or grn_query_position()",
            },
            "query_tool_pattern": {
                "description": "Instead of loading entire tables, use targeted query tools",
                "examples": [
                    "grn_query_entity(table, entity_id) - Get one entity's GRN annotations",
                    "grn_query_position(table, positions) - Get AA distribution at specific GRNs",
                    "get_entity_property_values(table, entity) - Get properties for one entity",
                ],
            },
            "tips": [
                "Statistics and metadata are always returned - use them to decide if you need full data",
                "Structure DataFrames are never exposed - use analysis tools instead",
                "When you need specific data, request it explicitly with include_* flags",
                "For GRN tables, use query tools rather than loading entire tables",
                "Binding pocket and ligand interaction data is always detailed (needed for reasoning)",
            ],
        }

    def _get_workflows_guide(self) -> Dict:
        """Get workflows guide content."""
        return {
            "title": "Common Analysis Workflows",
            "workflow_types": {
                "structure_based": {
                    "description": "Workflows starting from 3D structures",
                    "examples": [
                        "download_entities → structure_prepare_grn_annotations → load_grn_table",
                        "structure_prepare_grn_annotations → structure_export_entity → model_prepare_job",
                        "extract_ligands_from_structure → ligand_compute_interactions → record_property_rows",
                    ]
                },
                "sequence_based": {
                    "description": "Workflows starting from sequences",
                    "examples": [
                        "sequence_register_records → load_sequence_dataset → align_sequences_by_id",
                        "sequence_annotate_with_grn → record_property_rows → load_property_rows",
                        "sequence_download → sequence_align_mmseqs → sequence_export_dataset",
                    ]
                },
                "integrated": {
                    "description": "Workflows combining multiple data types",
                    "examples": [
                        "structure_prepare_grn_annotations → ligand_compute_interactions → model_prepare_job",
                        "ligand_register_smiles → ligand_import_smiles_structures → model_prepare_job",
                        "download_entities → sequence_register_records → record_property_rows",
                    ]
                }
            },
            "tips": [
                "Start with data download/preparation",
                "Use datasets for batch processing",
                "Chain processor outputs as inputs",
                "Save intermediate results for reproducibility"
            ]
        }
    
    def _get_best_practices_guide(self) -> Dict:
        """Get best practices guide content."""
        return {
            "title": "Best Practices for Protos",
            "data_preparation": [
                "Download all required entities before analysis",
                "Verify entities exist with entity_list_entities",
                "Create datasets for related entities",
                "Use consistent naming conventions"
            ],
            "processing": [
                "Load data once and reuse processor instances",
                "Use appropriate processors for each data type",
                "Handle missing data gracefully",
                "Save intermediate results"
            ],
            "common_patterns": {
                "batch_download": {
                    "description": "Download multiple structures efficiently",
                    "example": "download_entities(['3sn6', '5d5a'], processor_type='structure', dataset_name='gpcr_structures')"
                },
                "cross_format": {
                    "description": "Link data across formats",
                    "example": "Extract sequences from structures, then perform GRN assignment"
                },
                "property_integration": {
                    "description": "Combine structure with experimental data",
                    "example": "Map binding affinity to structural features"
                }
            },
            "troubleshooting": [
                "Entity not found: Check if downloaded first",
                "Format errors: Verify processor type matches data",
                "Memory issues: Process large datasets in batches",
                "Path errors: Never specify paths, use entity names"
            ]
        }
    
    def _get_quick_start(self) -> List[Dict]:
        """Get quick start steps."""
        return [
            {
                "step": 1,
                "action": "Check available entities",
                "command": "entity_list_entities(processor_type='structure')"
            },
            {
                "step": 2,
                "action": "Download a protein structure",
                "command": "download_entity('1ubq', source='pdb')"
            },
            {
                "step": 3,
                "action": "Load and analyze",
                "command": "load_entity('1ubq', format='structure')"
            },
            {
                "step": 4,
                "action": "Extract information",
                "command": "extract_sequence_from_structure('1ubq')"
            }
        ]
    
    # Workflow examples
    def _get_structure_workflow(self) -> List[Dict]:
        """Get structure analysis workflow."""
        return [
            {
                "step": 1,
                "description": "Initialize the data root and refresh reference assets",
                "tool": "config_initialize_data",
                "params": {"reinstall_reference": True, "refresh_registry": True}
            },
            {
                "step": 2,
                "description": "Download receptor structures into a dataset",
                "tool": "download_entities",
                "params": {
                    "identifiers": ["5d5a", "6b73"],
                    "processor_type": "structure",
                    "dataset_name": "gpcr_structures",
                    "create_dataset": True
                }
            },
            {
                "step": 3,
                "description": "Extract chains, align to GPCR references, and save GRN tables in one call",
                "tool": "structure_prepare_grn_annotations",
                "params": {
                    "structure_ids": ["5d5a", "6b73"],
                    "reference_table": "gpcrdb_ref",
                    "protein_family": "gpcr_a",
                    "alignment_threshold": 0.8
                }
            },
            {
                "step": 4,
                "description": "Inspect the resulting datasets/table",
                "tool": "load_grn_table",
                "params": {"table_name": "gpcr_grn_demo"},
                "note": "Pairs nicely with structure_apply_grn_annotations if you need to refresh existing entities."
            },
            {
                "step": 5,
                "description": "Export a GRN-labelled structure for modeling",
                "tool": "structure_export_entity",
                "params": {
                    "structure_id": "5d5a",
                    "format": "pdb",
                    "include_metadata": True,
                    "overwrite": True
                }
            }
        ]
    
    def _get_grn_workflow(self) -> List[Dict]:
        """Get GRN assignment workflow."""
        return [
            {
                "step": 1,
                "description": "Download the target structures",
                "tool": "download_entities",
                "params": {
                    "identifiers": ["3sn6", "5d5a", "6b73"],
                    "processor_type": "structure",
                    "dataset_name": "gpcr_structures",
                    "create_dataset": True
                }
            },
            {
                "step": 2,
                "description": "Run the combined chain extraction, alignment, and annotation workflow",
                "tool": "structure_prepare_grn_annotations",
                "params": {
                    "structure_ids": ["3sn6", "5d5a", "6b73"],
                    "reference_table": "gpcrdb_ref",
                    "protein_family": "gpcr_a",
                    "alignment_threshold": 0.75,
                    "filtered_sequence_dataset": "gpcr_chain_filtered"
                }
            },
            {
                "step": 3,
                "description": "Inspect alignment/coverage summaries",
                "tool": "load_sequence_dataset",
                "params": {"dataset_name": "gpcr_chain_filtered", "include_sequences": False}
            },
            {
                "step": 4,
                "description": "Load the stored GRN table for downstream reporting",
                "tool": "load_grn_table",
                "params": {"table_name": "gpcr_chain_filtered_grn"}
            },
            {
                "step": 5,
                "description": "Map GRN labels back onto structures (for visualization/export)",
                "tool": "structure_apply_grn_annotations",
                "params": {
                    "grn_table": "gpcr_chain_filtered_grn",
                    "structures": ["3sn6", "5d5a", "6b73"],
                    "column_name": "grn",
                    "save_entities": True
                }
            }
        ]
    
    def _get_ligand_workflow(self) -> List[Dict]:
        """Get ligand analysis workflow."""
        return [
            {
                "step": 1,
                "description": "Download the receptor structure (or dataset)",
                "tool": "download_entities",
                "params": {
                    "identifiers": ["5d5a"],
                    "processor_type": "structure",
                    "dataset_name": "ligand_workflow_structures"
                }
            },
            {
                "step": 2,
                "description": "Register chain sequences and annotate with GRNs",
                "tool": "structure_prepare_grn_annotations",
                "params": {
                    "structure_ids": ["5d5a"],
                    "reference_table": "gpcrdb_ref",
                    "protein_family": "gpcr_a",
                    "chain_dataset_prefix": "ligand_workflow_chains"
                }
            },
            {
                "step": 3,
                "description": "List ligands and inspect their metadata",
                "tool": "extract_ligands_from_structure",
                "params": {"pdb_id": "5d5a", "exclude_common": True, "min_atoms": 4}
            },
            {
                "step": 4,
                "description": "Compute residue-level interactions for the selected ligand",
                "tool": "ligand_compute_interactions",
                "params": {
                    "structure_id": "5d5a",
                    "ligand_names": ["CAU"],
                    "distance_cutoff": 4.0
                },
                "note": "Returns a dataframe plus per-ligand summaries ready for property logging."
            },
            {
                "step": 5,
                "description": "Persist binding contacts as a property table",
                "tool": "record_property_rows",
                "params": {
                    "dataset_name": "5d5a_ligand_contacts",
                    "rows": "{from_step_4}",
                    "allow_create": True
                }
            },
            {
                "step": 6,
                "description": "Register the ligand SMILES as a molecule entity",
                "tool": "save_entity",
                "params": {
                    "name": "5d5a_CAU_A",
                    "format": "molecule",
                    "data": {"smiles": "CC(C)NC1=NC(=O)N(C=C1)C2=CN=C(N)N=C2N", "kind": "smiles_record"},
                    "metadata": {"source_structure": "5d5a"}
                }
            },
            {
                "step": 7,
                "description": "Prepare a Boltz docking submission referencing the receptor dataset and ligand",
                "tool": "model_prepare_job",
                "params": {
                    "model_name": "boltz2",
                    "inputs": {"sequence_dataset": "ligand_workflow_chains_5d5a", "entity": "5d5a_chain_A"},
                    "config": {
                        "output_name": "5d5a_A_CAU_dock",
                        "ligand": {"id": "CAU", "smiles": "CC(C)NC1=NC(=O)N(C=C1)C2=CN=C(N)N=C2N"},
                        "default_sequence_type": "protein"
                    }
                }
            }
        ]
    
    def _get_sequence_workflow(self) -> List[Dict]:
        """Get sequence analysis workflow."""
        return [
            {
                "step": 1,
                "description": "Load sequences",
                "tool": "load_entity",
                "params": {"name": "kinase_sequences", "format": "sequence"}
            },
            {
                "step": 2,
                "description": "Perform pairwise alignment",
                "tool": "align_sequences",
                "params": {"seq1_name": "EGFR_HUMAN", "seq2_name": "ERBB2_HUMAN", "algorithm": "blosum62"}
            },
            {
                "step": 3,
                "description": "Calculate sequence identity",
                "tool": "calculate_sequence_identity",
                "params": {"dataset_name": "kinase_sequences", "method": "pairwise"}
            },
            {
                "step": 4,
                "description": "Find conserved regions",
                "tool": "sequence_find_conserved_regions",
                "params": {"dataset_name": "kinase_sequences", "threshold": 0.9}
            },
            {
                "step": 5,
                "description": "Detect mutations",
                "tool": "sequence_detect_mutations",
                "params": {"reference": "EGFR_HUMAN", "variant": "EGFR_L858R"}
            },
            {
                "step": 6,
                "description": "Cluster by similarity",
                "tool": "cluster_sequences",
                "params": {"dataset_name": "kinase_sequences", "threshold": 0.8}
            }
        ]
    
    def _get_property_workflow(self) -> List[Dict]:
        """Get property integration workflow."""
        return [
            {
                "step": 1,
                "description": "Download structures that will anchor the analysis",
                "tool": "download_entities",
                "params": {
                    "identifiers": ["3sn6", "5d5a", "6b73"],
                    "processor_type": "structure",
                    "dataset_name": "gpcr_structures"
                }
            },
            {
                "step": 2,
                "description": "Register custom reference sequences (e.g., curated chains)",
                "tool": "sequence_register_records",
                "params": {
                    "records": [
                        {"name": "5d5a_chain_A", "sequence": "{paste_sequence}"},
                        {"name": "6b73_chain_A", "sequence": "{paste_sequence}"}
                    ],
                    "dataset_name": "gpcr_sequences",
                    "overwrite": True,
                    "metadata": {"source": "property_workflow"}
                }
            },
            {
                "step": 3,
                "description": "Load the registered sequences (and optionally preview them)",
                "tool": "load_sequence_dataset",
                "params": {"dataset_name": "gpcr_sequences", "include_sequences": True}
            },
            {
                "step": 4,
                "description": "Align each chain to a reference to obtain scores",
                "tool": "align_sequences_by_id",
                "params": {
                    "entity1": "5d5a_chain_A",
                    "entity2": "reference_chain",
                    "alignment_method": "blosum62"
                },
                "note": "Repeat for every chain and capture the normalized scores for reporting."
            },
            {
                "step": 5,
                "description": "Record the per-chain metrics into a property table",
                "tool": "record_property_rows",
                "params": {
                    "dataset_name": "gpcr_sequence_alignment",
                    "rows": "[{entity_name: '5d5a_chain_A', 'scope': [{'format': 'sequence', 'name': '5d5a_chain_A'}], 'score': 0.82}]",
                    "allow_create": True
                }
            },
            {
                "step": 6,
                "description": "Query the property table for reporting or filtering",
                "tool": "load_property_rows",
                "params": {
                    "dataset_name": "gpcr_sequence_alignment",
                    "entity_name": "5d5a_chain_A",
                    "scope_format": "sequence"
                }
            }
        ]
    
    def _get_cross_format_workflow(self) -> List[Dict]:
        """Get cross-format workflow."""
        return [
            {
                "step": 1,
                "description": "Generate ligand structures from SMILES",
                "tool": "ligand_import_smiles_structures",
                "params": {
                    "smiles_map": {"DOPAMINE": "CNCCC1=CC(=C(C=C1)O)O"},
                    "dataset_name": "ligand_smiles_demo",
                    "generate_3d": True
                }
            },
            {
                "step": 2,
                "description": "Download/export the receptor structure for docking",
                "tool": "structure_export_entity",
                "params": {
                    "structure_id": "5d5a",
                    "format": "pdb",
                    "output_path": "${DATA_ROOT}/exports/5d5a.pdb",
                    "overwrite": True
                }
            },
            {
                "step": 3,
                "description": "Export the generated ligand to SDF",
                "tool": "structure_export_entity",
                "params": {
                    "structure_id": "ligand_smiles_demo_DOPAMINE",
                    "format": "sdf",
                    "output_path": "${DATA_ROOT}/exports/dopamine.sdf",
                    "overwrite": True
                }
            },
            {
                "step": 4,
                "description": "Prepare a Uni-Dock (or Boltz) job that references both files",
                "tool": "model_prepare_job",
                "params": {
                    "model_name": "unidock",
                    "inputs": {
                        "receptor_pdb": "${DATA_ROOT}/exports/5d5a.pdb",
                        "ligand_file": "${DATA_ROOT}/exports/dopamine.sdf"
                    },
                    "config": {"search_mode": "fast", "num_modes": 5}
                }
            },
            {
                "step": 5,
                "description": "Record docking metadata back into the property processor",
                "tool": "record_property_rows",
                "params": {
                    "dataset_name": "smiles_docking_runs",
                    "rows": "[{entity_name: '5d5a', 'scope': [{'format': 'structure', 'name': '5d5a'}], 'ligand': 'DOPAMINE', 'job_id': 'unidock_001'}]",
                    "allow_create": True
                }
            }
        ]
    
    def _get_workflow_tips(self, workflow_type: str) -> List[str]:
        """Get workflow-specific tips."""
        tips = {
            "structure_analysis": [
                "Run config_initialize_data once per session so shared reference tables remain available",
                "Use structure_prepare_grn_annotations instead of hand-written loops whenever you need numbered chains",
                "Export annotated entities only after structure_apply_grn_annotations has written the GRN column",
                "Keep track of dataset names returned by structure_prepare_grn_annotations for later reuse"
            ],
            "grn_assignment": [
                "Alignment thresholds are normalized—start around 0.75 and adjust as needed",
                "Always inspect the filtered dataset and GRN table before mapping back to structures",
                "structure_apply_grn_annotations can remap existing entities without rerunning the full pipeline",
                "Persist table names (e.g., gpcr_chain_filtered_grn) so subsequent workflows can load them directly"
            ],
            "ligand_analysis": [
                "Call extract_ligands_from_structure first to confirm the ligand IDs you plan to analyze",
                "ligand_compute_interactions now returns a dataframe—pipe it straight into record_property_rows",
                "Register SMILES (save_entity or ligand_register_smiles) before invoking model_prepare_job",
                "Reuse the sequence_dataset/entity returned by structure_prepare_grn_annotations when preparing Boltz jobs"
            ],
            "sequence_alignment": [
                "Choose appropriate substitution matrix for your sequences",
                "Consider sequence length when setting gap penalties",
                "Use conservation threshold based on your analysis needs",
                "Save alignments for visual inspection"
            ],
            "property_integration": [
                "Record derived metrics with record_property_rows and scope definitions so they can be filtered later",
                "Keep alignment or scoring metadata alongside experimental properties",
                "Use load_property_rows to spot-check entries immediately after recording",
                "Export tables only after validating units/metadata"
            ],
            "cross_format": [
                "Plan the artifacts you need (structure exports, ligand SDFs, property rows) before invoking model_prepare_job",
                "Use consistent naming when moving between structure, sequence, molecule, and property processors",
                "Record session artifacts with context_status to track generated files",
                "Prefer dataset-scoped analyses (e.g., ligand_smiles_demo) for reproducibility"
            ]
        }
        return tips.get(workflow_type, ["No specific tips available"])
    
    # Concept explanations
    def _explain_entity(self) -> Dict:
        """Explain entity concept."""
        return {
            "definition": "An entity is any biological object tracked in Protos",
            "examples": {
                "proteins": ["1ubq (ubiquitin structure)", "EGFR_HUMAN (EGFR sequence)"],
                "complexes": ["1atp (ATP synthase complex)", "4djh (GPCR-ligand complex)"],
                "ligands": ["ATP", "NADH", "drug molecules"]
            },
            "key_points": [
                "Entities use human-readable identifiers",
                "One entity can have multiple data formats",
                "Entities are automatically registered when created",
                "Entity names are the primary way to access data"
            ],
            "naming_conventions": {
                "structures": "PDB IDs (4 characters, e.g., '1ubq')",
                "sequences": "UniProt IDs (e.g., 'EGFR_HUMAN') or custom names",
                "ligands": "3-letter codes or ChEMBL IDs"
            }
        }
    
    def _explain_processor(self) -> Dict:
        """Explain processor concept."""
        return {
            "definition": "Processors are specialized modules that handle specific biological data types",
            "architecture": "All processors inherit from BaseProcessor and implement standard methods",
            "key_responsibilities": [
                "Data loading and parsing",
                "Format conversion",
                "Data validation",
                "File path management",
                "Entity registration"
            ],
            "usage_pattern": {
                "initialization": "Processors are created automatically by MCP tools",
                "data_access": "Use processor-specific methods like load_structure(), save_entity()",
                "no_direct_creation": "Never create processors directly in MCP tools"
            },
            "interoperability": "Processors can exchange data through the entity registry"
        }
    
    def _explain_dataset(self) -> Dict:
        """Explain dataset concept."""
        return {
            "definition": "A dataset is a named collection of entities for batch processing",
            "structure": {
                "name": "Unique identifier for the dataset",
                "entities": "List of entity names included",
                "metadata": "Optional information about the dataset",
                "processor_type": "Which processor manages this dataset"
            },
            "vs_entities": {
                "entities": "Individual biological objects",
                "datasets": "Collections of related entities"
            },
            "use_cases": [
                "Analyzing protein families",
                "Comparing multiple structures",
                "Batch property assignment",
                "Training ML models"
            ],
            "example": {
                "name": "kinase_structures",
                "entities": ["1atp", "1atq", "2src", "4anu"],
                "metadata": {"family": "protein kinase", "species": "human"}
            }
        }
    
    def _explain_grn(self) -> Dict:
        """Explain GRN concept."""
        return {
            "definition": "Generic Residue Numbering provides consistent residue identification across protein families",
            "problem_solved": "Different proteins have different sequence lengths and insertions/deletions, making comparison difficult",
            "solution": "GRN assigns universal position numbers based on structural/functional importance",
            "example": {
                "description": "GPCR family positions",
                "positions": {
                    "3.50": "Most conserved residue in helix 3 (DRY motif)",
                    "7.50": "NPxxY motif in helix 7",
                    "1.50": "Most conserved position in helix 1"
                }
            },
            "benefits": [
                "Compare equivalent positions across proteins",
                "Identify conserved motifs",
                "Map mutations to functional regions",
                "Transfer annotations between homologs"
            ],
            "usage": "Assign GRN after sequence alignment to reference"
        }
    
    def _explain_paths(self) -> Dict:
        """Explain path management."""
        return {
            "core_principle": "You NEVER specify file paths - Protos handles all path management",
            "why": {
                "portability": "Code works on any system",
                "organization": "Consistent data structure",
                "safety": "No accidental file overwrites",
                "simplicity": "Focus on science, not file management"
            },
            "how_it_works": {
                "ProtosPaths": "Central path resolver",
                "data_root": "Base directory for all data",
                "processor_dirs": "Each processor has its subdirectory",
                "automatic": "Paths resolved based on entity names and formats"
            },
            "user_perspective": {
                "wrong": "load_file('/home/user/data/structures/1ubq.cif')",
                "correct": "load_entity('1ubq', format='structure')"
            }
        }
    
    def _explain_formats(self) -> Dict:
        """Explain supported formats."""
        return {
            "structure_formats": {
                "mmCIF": "Preferred format for structures",
                "PDB": "Legacy format, automatically converted",
                "pickle": "Fast loading for processed structures"
            },
            "sequence_formats": {
                "FASTA": "Standard sequence format",
                "clustal": "Multiple sequence alignments",
                "stockholm": "Alignments with annotations"
            },
            "table_formats": {
                "CSV": "Property and GRN tables",
                "TSV": "Tab-separated values",
                "JSON": "Structured data with metadata",
                "parquet": "Efficient columnar storage"
            },
            "ligand_formats": {
                "SDF": "Structure data file with 3D coordinates",
                "SMILES": "Linear molecular notation",
                "InChI": "International Chemical Identifier"
            },
            "embedding_formats": {
                "npy": "NumPy arrays",
                "h5": "HDF5 for large embeddings",
                "pt": "PyTorch tensors"
            }
        }
