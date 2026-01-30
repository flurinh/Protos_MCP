"""MCP Resources and Prompts for Protos server.

Resources provide cacheable reference data that clients can de-duplicate.
Prompts provide reusable workflow templates for common operations.

Based on MCP 2025-06-18 best practices:
- Resources are for cache invalidation and de-duplication
- Prompts guide AI interactions with step-by-step workflows
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
import yaml

from mcp.server.fastmcp import FastMCP

from .core.logging_config import get_logger

if TYPE_CHECKING:
    from .context import ServerContext

logger = get_logger("resources")


def register_resources(server: FastMCP, context: "ServerContext") -> None:
    """Register MCP resources for reference data.

    Resources enable client-side caching and de-duplication of frequently
    accessed data like tool documentation, GRN references, and dataset listings.

    Args:
        server: FastMCP server instance
        context: Server context with processor access
    """

    @server.resource("protos://guide/tool-usage")
    async def get_tool_usage_guide() -> Dict[str, Any]:
        """Tool usage documentation - cacheable by clients.

        Returns comprehensive tool documentation from tool_usage.yaml
        for client-side caching and reference.
        """
        try:
            import importlib.resources as pkg_resources
            # Try to load from package first
            try:
                yaml_content = pkg_resources.files("mcp_server").joinpath("tool_usage.yaml").read_text()
                return yaml.safe_load(yaml_content)
            except (FileNotFoundError, TypeError):
                # Fallback to direct file read
                from pathlib import Path
                yaml_path = Path(__file__).parent / "tool_usage.yaml"
                if yaml_path.exists():
                    with open(yaml_path) as f:
                        return yaml.safe_load(f)
                return {"error": "tool_usage.yaml not found"}
        except Exception as e:
            logger.error(f"Failed to load tool usage guide: {e}")
            return {"error": str(e)}

    @server.resource("protos://guide/topics")
    async def get_guide_topics() -> Dict[str, Any]:
        """Available guide topics for interactive help.

        Returns list of available topics that can be queried
        via the protos_guide tool.
        """
        return {
            "topics": [
                {
                    "name": "getting_started",
                    "description": "Introduction to Protos MCP and basic concepts",
                },
                {
                    "name": "entity_management",
                    "description": "Working with entities (download, register, query)",
                },
                {
                    "name": "dataset_operations",
                    "description": "Creating and managing datasets",
                },
                {
                    "name": "structure_analysis",
                    "description": "Protein structure analysis tools",
                },
                {
                    "name": "sequence_analysis",
                    "description": "Sequence analysis and alignment",
                },
                {
                    "name": "grn_annotation",
                    "description": "Generic Residue Numbering (GRN) workflows",
                },
                {
                    "name": "property_tables",
                    "description": "Working with property tables",
                },
                {
                    "name": "ligand_analysis",
                    "description": "Ligand and binding site analysis",
                },
                {
                    "name": "llm_safe_mode",
                    "description": "Understanding LLM-safe response patterns",
                },
            ]
        }

    @server.resource("protos://reference/grn/{family}")
    async def get_grn_reference(family: str) -> Dict[str, Any]:
        """GRN reference table for a protein family.

        Args:
            family: Protein family (e.g., 'gpcr_a', 'gpcr_b')

        Returns:
            Reference table metadata including position count and coverage.
        """
        try:
            processor = context.get_processor("grn")
            if processor is None:
                return {"error": "GRN processor not available"}

            # Load reference and return metadata (not full table)
            ref_name = f"{family}_ref" if not family.endswith("_ref") else family
            ref_data = processor.load_reference_table(ref_name)

            if ref_data is None:
                return {"error": f"Reference table '{ref_name}' not found"}

            # Return summary metadata
            return {
                "family": family,
                "reference_table": ref_name,
                "sequence_count": len(ref_data) if hasattr(ref_data, "__len__") else 0,
                "available_families": ["gpcr_a", "gpcr_b", "gpcr_c", "gpcr_f"],
            }
        except Exception as e:
            logger.error(f"Failed to load GRN reference: {e}")
            return {"error": str(e)}

    @server.resource("protos://datasets/{processor_type}")
    async def list_datasets_resource(processor_type: str) -> Dict[str, Any]:
        """List available datasets for a processor type.

        Args:
            processor_type: Type of processor (structure, sequence, grn, property, etc.)

        Returns:
            List of dataset names and metadata.
        """
        try:
            processor = context.get_processor(processor_type)
            if processor is None:
                return {"error": f"Processor '{processor_type}' not available"}

            manager = getattr(processor, "dataset_manager", None)
            if manager is None:
                return {"error": f"No dataset manager for '{processor_type}'"}

            datasets = manager.list_datasets()
            return {
                "processor_type": processor_type,
                "dataset_count": len(datasets),
                "datasets": datasets[:50] if len(datasets) > 50 else datasets,
                "truncated": len(datasets) > 50,
            }
        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            return {"error": str(e)}

    @server.resource("protos://entities/{processor_type}")
    async def list_entities_resource(processor_type: str) -> Dict[str, Any]:
        """List registered entities for a processor type.

        Args:
            processor_type: Type of processor (structure, sequence, etc.)

        Returns:
            Count and sample of registered entities.
        """
        try:
            registry = context.entity_registry
            if registry is None:
                return {"error": "Entity registry not available"}

            # Filter entities by processor type
            all_entities = registry.list_entities()
            filtered = [
                e for e in all_entities
                if e.get("format") == processor_type
            ]

            return {
                "processor_type": processor_type,
                "entity_count": len(filtered),
                "sample": filtered[:20] if len(filtered) > 20 else filtered,
                "truncated": len(filtered) > 20,
            }
        except Exception as e:
            logger.error(f"Failed to list entities: {e}")
            return {"error": str(e)}

    @server.resource("protos://server/info")
    async def get_server_info_resource() -> Dict[str, Any]:
        """Server information and status.

        Returns server configuration, available processors,
        and current state.
        """
        try:
            stats = context.get_stats() if hasattr(context, "get_stats") else {}
            return {
                "server": "protos-mcp",
                "version": "1.0.0",
                "data_root": str(context.config.data_root),
                "llm_safe_mode": context.config.llm_safe_mode,
                "available_processors": list(stats.get("processors", {}).keys()),
                "stats": stats,
            }
        except Exception as e:
            logger.error(f"Failed to get server info: {e}")
            return {"error": str(e)}

    logger.info("Registered MCP resources")


def register_prompts(server: FastMCP, context: "ServerContext") -> None:
    """Register MCP prompts for common workflows.

    Prompts provide reusable workflow templates that guide AI interactions
    with step-by-step instructions for common operations.

    Args:
        server: FastMCP server instance
        context: Server context (for future use)
    """

    @server.prompt("analyze-protein-structure")
    async def analyze_structure_prompt(pdb_id: str) -> str:
        """Comprehensive protein structure analysis workflow.

        Args:
            pdb_id: PDB identifier (e.g., '3sn6', '5d5a')
        """
        return f"""# Protein Structure Analysis: {pdb_id.upper()}

Perform a comprehensive analysis of protein structure {pdb_id.upper()}:

## Step 1: Download Structure
```
download_entity('{pdb_id}', processor_type='structure')
```

## Step 2: Explore Structure
```
structure_get_chains('{pdb_id}')
structure_get_all_sequences('{pdb_id}')
```

## Step 3: Find Ligands and Binding Sites
```
structure_extract_ligands('{pdb_id}')
structure_get_binding_sites('{pdb_id}')
```

## Step 4: Analyze Water Networks (if applicable)
```
structure_extract_water_molecules('{pdb_id}')
```

## Step 5: Report Findings
Summarize:
- Chain composition and lengths
- Ligands present and their interactions
- Key binding site residues
- Notable structural features

Use `protos_guide(topic='structure_analysis')` for detailed help.
"""

    @server.prompt("annotate-gpcr-sequences")
    async def gpcr_annotation_prompt(dataset_name: str) -> str:
        """GPCR sequence annotation with GRN workflow.

        Args:
            dataset_name: Name of sequence dataset to annotate
        """
        return f"""# GPCR GRN Annotation: {dataset_name}

Annotate GPCR sequences in dataset '{dataset_name}' with Generic Residue Numbers:

## Step 1: Verify Dataset
```
dataset_entities('{dataset_name}', processor_type='sequence')
```

## Step 2: Annotate with GRN
```
sequence_annotate_with_grn(
    dataset_name='{dataset_name}',
    reference_table='gpcrdb_ref',
    protein_family='gpcr_a',
    output_table='{dataset_name}_grn',
    allow_create=True
)
```

## Step 3: Query Results
```
# Check overall statistics
grn_query_position('{dataset_name}_grn', positions=['1x50', '3x50', '6x50', '7x50'])

# Query specific entity
grn_query_entity('{dataset_name}_grn', entity_id='<entity_name>')
```

## Step 4: Compare Conservation
```
grn_compare_conservation('{dataset_name}_grn', positions=['3x50', '6x50'])
```

Use `protos_guide(topic='grn_annotation')` for detailed help.
"""

    @server.prompt("ligand-binding-analysis")
    async def ligand_binding_prompt(pdb_id: str, ligand_id: Optional[str] = None) -> str:
        """Ligand binding site analysis workflow.

        Args:
            pdb_id: PDB identifier containing the ligand
            ligand_id: Optional specific ligand ID to analyze
        """
        ligand_clause = f"'{ligand_id}'" if ligand_id else "the primary ligand"
        return f"""# Ligand Binding Analysis: {pdb_id.upper()}

Analyze ligand binding in structure {pdb_id.upper()}:

## Step 1: Download and Identify Ligands
```
download_entity('{pdb_id}', processor_type='structure')
structure_extract_ligands('{pdb_id}')
```

## Step 2: Analyze Binding Site
```
structure_get_binding_sites(
    '{pdb_id}',
    ligand_id={f"'{ligand_id}'" if ligand_id else 'None'},
    distance_cutoff=5.0
)
```

## Step 3: Get Ligand Properties
```
# If SMILES available:
calculate_molecular_properties(smiles='<ligand_smiles>')
```

## Step 4: Search Similar Ligands (optional)
```
search_similar_ligands(smiles='<ligand_smiles>', threshold=0.7)
```

## Step 5: Report
Summarize:
- Ligand identification and properties
- Binding site residues (within 5A)
- Key interactions (H-bonds, hydrophobic, etc.)
- Drug-likeness assessment

Use `protos_guide(topic='ligand_analysis')` for detailed help.
"""

    @server.prompt("sequence-alignment-workflow")
    async def sequence_alignment_prompt(
        query_id: str,
        reference_id: str,
    ) -> str:
        """Pairwise sequence alignment workflow.

        Args:
            query_id: Query sequence entity ID
            reference_id: Reference sequence entity ID
        """
        return f"""# Sequence Alignment: {query_id} vs {reference_id}

Perform pairwise sequence alignment:

## Step 1: Ensure Sequences Available
```
load_entity('{query_id}', format='sequence')
load_entity('{reference_id}', format='sequence')
```

## Step 2: Perform Alignment
```
align_sequences(
    query='{query_id}',
    reference='{reference_id}',
    algorithm='needleman_wunsch'
)
```

## Step 3: Calculate Identity
```
calculate_sequence_identity(
    seq1='{query_id}',
    seq2='{reference_id}'
)
```

## Step 4: Detect Mutations
```
detect_mutations(
    query='{query_id}',
    reference='{reference_id}'
)
```

Use `protos_guide(topic='sequence_analysis')` for detailed help.
"""

    @server.prompt("create-property-table")
    async def property_table_prompt(table_name: str, entity_type: str) -> str:
        """Create and populate a property table workflow.

        Args:
            table_name: Name for the new property table
            entity_type: Type of entities (e.g., 'receptor', 'ligand')
        """
        return f"""# Create Property Table: {table_name}

Create a property table for {entity_type} entities:

## Step 1: Create Table with Initial Data
```
create_property_table(
    dataset_name='{table_name}',
    data={{
        'entity_1': {{'property1': 'value1', 'property2': 123}},
        'entity_2': {{'property1': 'value2', 'property2': 456}},
    }},
    metadata={{'entity_type': '{entity_type}'}}
)
```

## Step 2: Add More Properties
```
update_property_values(
    dataset_name='{table_name}',
    updates={{
        'entity_1': {{'new_property': 'new_value'}},
    }}
)
```

## Step 3: Query Properties
```
load_property_table('{table_name}')
get_property_statistics('{table_name}', property_name='property2')
```

## Step 4: Filter Entities
```
filter_entities_by_property(
    dataset_name='{table_name}',
    property_name='property2',
    operator='>',
    value=100
)
```

Use `protos_guide(topic='property_tables')` for detailed help.
"""

    @server.prompt("structure-comparison")
    async def structure_comparison_prompt(
        structure_ids: str,
        reference_id: Optional[str] = None,
    ) -> str:
        """Structure alignment and comparison workflow.

        Args:
            structure_ids: Comma-separated list of structure IDs
            reference_id: Optional reference structure for alignment
        """
        ids = [s.strip() for s in structure_ids.split(",")]
        ref = reference_id or ids[0]
        return f"""# Structure Comparison

Compare structures: {', '.join(ids)}

## Step 1: Download Structures
```
download_entities(
    identifiers={ids},
    processor_type='structure',
    dataset_name='comparison_structures'
)
```

## Step 2: Align to Reference
```
structure_align_to_reference(
    reference_id='{ref}',
    dataset_name='comparison_structures',
    output_dataset='aligned_structures',
    method='cealign'
)
```

## Step 3: Calculate RMSD Matrix
```
structure_rmsd_matrix(
    dataset_name='aligned_structures'
)
```

## Step 4: Compare Binding Sites (if applicable)
```
structure_compare_binding_sites(
    structures={ids},
    ligand_id=None  # or specific ligand
)
```

Use `protos_guide(topic='structure_analysis')` for detailed help.
"""

    logger.info("Registered MCP prompts")


def register_all(server: FastMCP, context: "ServerContext") -> None:
    """Register all MCP resources and prompts.

    Args:
        server: FastMCP server instance
        context: Server context
    """
    register_resources(server, context)
    register_prompts(server, context)
