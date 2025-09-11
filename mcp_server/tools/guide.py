"""
Protos workflow guide and helper tools.

These tools provide interactive guidance for using Protos, explaining core concepts,
data management principles, and providing workflow examples.
"""

from typing import Dict, List, Optional, Any
import json

from .base import BaseTool


class ProtoGuideTools(BaseTool):
    """Interactive guide and helper tools for Protos workflows."""
    
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
                "best_practices": self._get_best_practices_guide()
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
        
        @server.tool()
        def workflow_example(ctx, workflow_type: str) -> Dict:
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
        
        @server.tool()
        def explain_concept(ctx, concept: str) -> Dict:
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
            "description": "Processors are specialized modules that handle different biological data types",
            "available_processors": {
                "structure": {
                    "handles": "3D protein structures (PDB/mmCIF files)",
                    "key_methods": ["load_structures", "save_structure", "get_sequence"],
                    "use_for": "Structure analysis, coordinate extraction, chain information"
                },
                "sequence": {
                    "handles": "Protein/DNA/RNA sequences (FASTA format)",
                    "key_methods": ["load_sequence", "save_entity", "align_sequences"],
                    "use_for": "Sequence alignment, conservation analysis, mutation detection"
                },
                "grn": {
                    "handles": "Generic Residue Numbering tables",
                    "key_methods": ["load_reference_table", "assign_grn", "save_grn_table"],
                    "use_for": "Consistent residue numbering across protein families"
                },
                "property": {
                    "handles": "Experimental properties and metadata",
                    "key_methods": ["assign_property", "save_property_table"],
                    "use_for": "Binding affinity, expression levels, experimental conditions"
                },
                "ligand": {
                    "handles": "Small molecule ligands",
                    "key_methods": ["extract_ligands", "calculate_properties", "save_entity"],
                    "use_for": "Drug discovery, binding site analysis, molecular properties"
                },
                "embedding": {
                    "handles": "Machine learning embeddings",
                    "key_methods": ["generate_embeddings", "save_embeddings"],
                    "use_for": "ML-based analysis, similarity searches, clustering"
                }
            },
            "key_principle": "Each processor inherits from BaseProcessor and provides standardized methods for its data type"
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
            }
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
                "list_entities": "See all entities for a processor type",
                "search_entities": "Find entities across all processors",
                "entity_info": "Get comprehensive information about an entity"
            }
        }
    
    def _get_workflows_guide(self) -> Dict:
        """Get workflows guide content."""
        return {
            "title": "Common Analysis Workflows",
            "workflow_types": {
                "structure_based": {
                    "description": "Workflows starting from 3D structures",
                    "examples": [
                        "Structure → Sequence extraction → Alignment",
                        "Structure → Ligand extraction → Property calculation",
                        "Multiple structures → Structural alignment → RMSD analysis"
                    ]
                },
                "sequence_based": {
                    "description": "Workflows starting from sequences",
                    "examples": [
                        "Sequences → Alignment → Conservation analysis",
                        "Sequences → GRN assignment → Family analysis",
                        "Sequences → Clustering → Phylogeny"
                    ]
                },
                "integrated": {
                    "description": "Workflows combining multiple data types",
                    "examples": [
                        "Structure + Sequence → GRN → Property mapping",
                        "Structure + Ligand → Binding analysis → Drug design",
                        "Multiple formats → Integrated dataset → ML analysis"
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
                "Verify entities exist with list_entities",
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
                    "example": "download_dataset_entities('my_dataset', max_parallel=5)"
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
                "command": "list_entities(processor_type='structure')"
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
                "tool": "get_binding_site_residues",
                "params": {"pdb_id": "4djh", "ligand_name": "0KE", "cutoff": 5.0}
            },
            {
                "step": 4,
                "description": "Calculate molecular properties",
                "tool": "calculate_molecular_properties",
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
                "tool": "find_conserved_regions",
                "params": {"dataset_name": "kinase_sequences", "threshold": 0.9}
            },
            {
                "step": 5,
                "description": "Detect mutations",
                "tool": "detect_mutations",
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
                "data_access": "Use processor-specific methods like load_structures(), save_entity()",
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