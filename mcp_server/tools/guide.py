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
            """Return usage guidance for a specific MCP tool from tool_usage.yaml."""

            usage = self._load_tool_usage()
            if not usage:
                return self.format_error(
                    "No tool usage metadata available",
                    "Populate mcp_server/tool_usage.yaml to enable this helper.",
                )

            if not tool_name:
                return self.format_success({"tools": sorted(usage.keys())})

            lookup = tool_name.lower()
            key = next((name for name in usage if name.lower() == lookup), None)

            if key is None:
                matches = [name for name in usage if lookup in name.lower()]
                suggestion = (
                    f"Available tools: {', '.join(sorted(usage.keys()))}"
                    if not matches
                    else f"Did you mean: {', '.join(matches)}?"
                )
                return self.format_error(
                    f"Unknown tool '{tool_name}'",
                    suggestion,
                )

            entry = usage.get(key, {})
            payload = {"tool": key, **entry}
            return self.format_success(payload)

        self.register_tool_metadata(
            function=guide_tool_help,
            name="guide_tool_help",
            description="Surface enriched usage notes for a tool (parsed from tool_usage.yaml).",
            parameters=[{"name": "tool_name", "type": "str", "optional": True}],
            returns={"fields": ["summary", "workflows"]},
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
                    "export": [
                        "structure_export_entity",
                        "structure_export_dataset",
                    ],
                    "loaders": ["download_entity", "download_entities", "download_sources"],
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
                        "analyze_structure_ligand_environment",
                        "ligand_calculate_molecular_properties",
                    ],
                    "export": [
                        "ligand_register_smiles",
                        "ligand_record_interactions",
                    ],
                    "loaders": ["extract_ligands_from_structure", "get_protein_ligands_from_chembl"],
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
                    ],
                    "export": [
                        "record_grn_table",
                    ],
                    "loaders": [],
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
                    "follow_up": "Call load_grn_table for previews or structure_apply_grn_annotations if you need to re-map without rerunning the full workflow.",
                }
            },
            "tips": [
                "Ensure structures are downloaded via download_entities before running GRN steps.",
                "Lower alignment_threshold (e.g., 0.6) if no chains pass the similarity filter.",
                "When orchestrating manually, keep the chain entity names (e.g., '3sn6_chain_A') consistent so they match GRN table rows.",
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
                        "download_entities → load_structure_dataset → structure_filter_dataset → structure_collect_chain_sequences",
                        "structure_align_to_reference → structure_apply_grn_annotations → structure_export_dataset",
                        "extract_ligands_from_structure → ligand_compute_interactions → ligand_record_interactions",
                    ]
                },
                "sequence_based": {
                    "description": "Workflows starting from sequences",
                    "examples": [
                        "sequence_download → load_sequence_dataset → sequence_align_to_reference",
                        "sequence_align_mmseqs → sequence_compute_conservation → sequence_export_dataset",
                        "sequence_annotate_with_grn → load_grn_table → structure_apply_grn_annotations",
                    ]
                },
                "integrated": {
                    "description": "Workflows combining multiple data types",
                    "examples": [
                        "structure_collect_chain_sequences → sequence_save_sequences → embedding_generate → embedding_cosine_similarity",
                        "structure_graph_generate_from_dataset → structure_graph_load_entity → property_record_table",
                        "ligand_register_smiles → load_ligand_dataset → analyze_ligand_binding_site",
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
                "description": "Download structures of interest",
                "tool": "download_entity",
                "params": {"entity_id": "1ubq", "source": "pdb", "processor_type": "structure"},
                "note": "Can also use AlphaFold with source='alphafold'"
            },
            {
                "step": 2,
                "description": "Create a dataset for analysis",
                "tool": "create_dataset",
                "params": {"name": "my_structures", "entities": ["1ubq", "2ubq"], "processor_type": "structure"}
            },
            {
                "step": 3,
                "description": "Load the dataset",
                "tool": "load_dataset",
                "params": {"name": "my_structures", "processor_type": "structure"}
            },
            {
                "step": 4,
                "description": "Extract sequences from all chains",
                "tool": "get_all_sequences_from_structure",
                "params": {"pdb_id": "1ubq", "save_to_sequence": True}
            },
            {
                "step": 5,
                "description": "Calculate structural properties",
                "tool": "calculate_structure_properties",
                "params": {"pdb_id": "1ubq"}
            },
            {
                "step": 6,
                "description": "Align structures if multiple",
                "tool": "align_protein_structures",
                "params": {"reference_pdb": "1ubq", "mobile_pdb": "2ubq"}
            }
        ]
    
    def _get_grn_workflow(self) -> List[Dict]:
        """Get GRN assignment workflow."""
        return [
            {
                "step": 1,
                "description": "Download GPCR structures",
                "tool": "download_entity",
                "params": {"entity_id": "5uen", "source": "pdb", "processor_type": "structure"},
                "note": "Repeat for multiple GPCRs"
            },
            {
                "step": 2,
                "description": "Create structure dataset",
                "tool": "create_dataset",
                "params": {"name": "gpcr_structures", "entities": ["5uen", "6ps0", "7wy5"], "processor_type": "structure"}
            },
            {
                "step": 3,
                "description": "Extract sequences from structures",
                "tool": "extract_sequences_from_structures",
                "params": {"dataset_name": "gpcr_structures"}
            },
            {
                "step": 4,
                "description": "Load GRN reference table",
                "tool": "load_grn_reference_table",
                "params": {"reference_name": "gpcrdb_ref"}
            },
            {
                "step": 5,
                "description": "Align sequences to reference",
                "tool": "align_sequences_to_reference",
                "params": {"sequences": "{from_step_3}", "reference_name": "gpcrdb_ref"}
            },
            {
                "step": 6,
                "description": "Assign GRN positions",
                "tool": "assign_grn_to_sequences",
                "params": {"alignment_results": "{from_step_5}", "family": "gpcr_a"}
            },
            {
                "step": 7,
                "description": "Create and save GRN table",
                "tool": "create_grn_table",
                "params": {"dataset_name": "gpcr_grn_analysis", "grn_data": "{from_step_6}"}
            }
        ]
    
    def _get_ligand_workflow(self) -> List[Dict]:
        """Get ligand analysis workflow."""
        return [
            {
                "step": 1,
                "description": "Download protein-ligand complex",
                "tool": "download_entity",
                "params": {"entity_id": "4djh", "source": "pdb", "processor_type": "structure"}
            },
            {
                "step": 2,
                "description": "Extract all ligands",
                "tool": "extract_ligands_from_structure",
                "params": {"pdb_id": "4djh", "exclude_common": True}
            },
            {
                "step": 3,
                "description": "Get binding site residues",
                "tool": "structure_get_binding_site_residues",
                "params": {"pdb_id": "4djh", "ligand_name": "0KE", "cutoff": 5.0}
            },
            {
                "step": 4,
                "description": "Calculate molecular properties",
                "tool": "ligand_calculate_molecular_properties",
                "params": {"smiles": "CC1=CC=C(C=C1)C2=CC(=NN2C3=CC=C(C=C3)S(=O)(=O)N)C(F)(F)F"}
            },
            {
                "step": 5,
                "description": "Search for similar ligands",
                "tool": "search_similar_ligands",
                "params": {"query_smiles": "{from_step_4}", "dataset_name": "chembl_drugs", "threshold": 0.7}
            },
            {
                "step": 6,
                "description": "Get bioactivity from ChEMBL",
                "tool": "get_protein_ligands_from_chembl",
                "params": {"target_id": "CHEMBL203", "min_pchembl": 6.0}
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
                "description": "Create property table from entities",
                "tool": "create_property_table",
                "params": {"dataset_name": "kinase_props", "entities": ["EGFR", "ERBB2", "BRAF"]}
            },
            {
                "step": 2,
                "description": "Add experimental properties",
                "tool": "add_property_column",
                "params": {
                    "dataset_name": "kinase_props",
                    "property_name": "IC50_nM",
                    "values": {"EGFR": 2.5, "ERBB2": 15.3, "BRAF": 0.8}
                }
            },
            {
                "step": 3,
                "description": "Add calculated properties",
                "tool": "add_property_column",
                "params": {
                    "dataset_name": "kinase_props",
                    "property_name": "mutation_count",
                    "values": {"EGFR": 5, "ERBB2": 3, "BRAF": 8}
                }
            },
            {
                "step": 4,
                "description": "Calculate statistics",
                "tool": "get_property_statistics",
                "params": {"dataset_name": "kinase_props", "property_name": "IC50_nM"}
            },
            {
                "step": 5,
                "description": "Filter by property",
                "tool": "filter_entities_by_property",
                "params": {"dataset_name": "kinase_props", "property_name": "IC50_nM", "operator": "<", "value": 10}
            },
            {
                "step": 6,
                "description": "Export results",
                "tool": "export_property_table",
                "params": {"dataset_name": "kinase_props", "format": "csv"}
            }
        ]
    
    def _get_cross_format_workflow(self) -> List[Dict]:
        """Get cross-format workflow."""
        return [
            {
                "step": 1,
                "description": "Start with structures",
                "tool": "download_entity",
                "params": {"entity_id": "1atp", "source": "pdb", "processor_type": "structure"}
            },
            {
                "step": 2,
                "description": "Extract sequences",
                "tool": "extract_sequence_from_structure",
                "params": {"pdb_id": "1atp", "chain_id": "E", "save_to_sequence": True}
            },
            {
                "step": 3,
                "description": "Extract ligands",
                "tool": "extract_ligands_from_structure",
                "params": {"pdb_id": "1atp"}
            },
            {
                "step": 4,
                "description": "Assign GRN if applicable",
                "tool": "assign_grn_to_sequences",
                "params": {"sequences": {"1atp_E": "{from_step_2}"}, "family": "kinase"}
            },
            {
                "step": 5,
                "description": "Create integrated property table",
                "tool": "create_property_table",
                "params": {"dataset_name": "integrated_analysis", "entities": ["1atp"]}
            },
            {
                "step": 6,
                "description": "Add multi-format properties",
                "tool": "add_property_column",
                "params": {
                    "dataset_name": "integrated_analysis",
                    "property_name": "has_atp",
                    "values": {"1atp": True}
                }
            }
        ]
    
    def _get_workflow_tips(self, workflow_type: str) -> List[str]:
        """Get workflow-specific tips."""
        tips = {
            "structure_analysis": [
                "Always check if structures are downloaded before loading",
                "Use chain_id parameter to focus on specific chains",
                "Save sequences to sequence processor for further analysis",
                "Consider resolution when comparing structures"
            ],
            "grn_assignment": [
                "Ensure sequence identity > 25% for reliable GRN assignment",
                "Use appropriate reference table for your protein family",
                "Check coverage statistics to assess assignment quality",
                "Save GRN tables for reproducibility"
            ],
            "ligand_analysis": [
                "Exclude common molecules (water, ions) for meaningful results",
                "Use appropriate cutoff distances for binding site analysis",
                "Verify SMILES strings before property calculation",
                "Consider stereochemistry in similarity searches"
            ],
            "sequence_alignment": [
                "Choose appropriate substitution matrix for your sequences",
                "Consider sequence length when setting gap penalties",
                "Use conservation threshold based on your analysis needs",
                "Save alignments for visual inspection"
            ],
            "property_integration": [
                "Ensure all entities exist before creating property tables",
                "Use consistent units for numerical properties",
                "Document property sources in metadata",
                "Export tables for use in other tools"
            ],
            "cross_format": [
                "Plan data flow between processors",
                "Save intermediate results at each step",
                "Use entity names consistently across formats",
                "Create datasets to organize related analyses"
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
