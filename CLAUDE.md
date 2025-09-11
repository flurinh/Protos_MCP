# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Protos-MCP is a structural biology framework that integrates with LLMs through the Model Context Protocol. It provides zero-configuration data management for protein structures, sequences, annotations, properties, and ML embeddings.

## 🎉 Latest Updates (2025-07-23)

### Critical Fixes Completed
- **ALL path operations now go through Protos** - removed all direct path manipulation from MCP tools
- **Entity operations fixed for all formats** - structure, sequence, GRN, property, and ligand
- **Dataset operations fully implemented** - using Protos DatasetManager exclusively
- **API now accepts JSON objects directly** - not just JSON strings
- **Enhanced error messages** - provide actionable suggestions for common issues
- **Processor type validation** - all tools validate processor types using ProcessorFactory registry
- **BaseProcessor.load_dataset bug fixed** - now properly uses dataset.content attribute

### Remaining Known Issues
- **Missing entity errors**: When datasets reference entities that haven't been downloaded yet (user workflow issue)

## 🔴 CRITICAL: Protos Data Management Principles

**These are ABSOLUTE RULES that override all other considerations:**

1. **Protos Handles ALL Data Management**
   - MCP tools are ONLY a thin interface layer to Protos
   - NEVER construct file paths in MCP tools
   - NEVER directly read/write files in MCP tools
   - ALWAYS use Protos processor methods for ALL operations

2. **ProtosPaths is the ONLY Path System**
   - Protos internally manages all paths through ProtosPaths
   - MCP tools NEVER need to know about file locations
   - Entity names are the only identifiers MCP tools use

3. **Entity Registry Ensures Consistency**
   - Protos tracks all entities through its registry
   - MCP tools work with human-readable entity names
   - Hash IDs are internal to Protos only

4. **Processors are the Data Interface**
   - Each processor has specific methods for its data type
   - MCP tools must use the correct processor methods
   - All complexity lives in Protos, NOT in MCP tools

## Processor-Specific Save Methods

**CRITICAL**: Each processor uses different save method names. MCP tools MUST use the correct method:

### StructureProcessor
```python
processor.save_structure(name: str, structure_df: pd.DataFrame, format: str = 'pkl')
processor.save_entity(name: str, data: pd.DataFrame)  # Saves to cache
processor.save_cif(df, output_path)  # For CIF format
```

### SequenceProcessor
```python
processor.save_entity(name: str, data: Union[str, Dict[str, str]])
processor.save_sequences(sequences: Dict[str, str], output_file: str)
processor.save_alignment(alignment_data: Dict, output_file: str)
```

### GRNProcessor
```python
processor.save_grn_table(dataset_id: str, normalize_formats: bool = True)
processor.save_entity(name: str, data: pd.Series)  # Adds row to table
processor.save_data(name: str, data: Any, file_format: str = 'csv')
```

### PropertyProcessor
```python
processor.save_property_table(dataset_name: str, metadata: Optional[Dict] = None)
processor.assign_property(entity: str, property_name: str, value: Any)  # Use instead of save_entity
```

### LigandProcessor
```python
processor.save_entity(name: str, data: Dict, metadata: Optional[Dict] = None)
```

## MCP Implementation Status

### ✅ Completed
- Phase 1: Core Infrastructure
- Phase 2: Entity Management Tools  
- Phase 2.5: Multi-Format Entity Operations
- Phase 3: Dataset Management
- Critical path management fixes
- Dataset entity download tool
- Processor type validation (using ProcessorFactory)
- BaseProcessor dataset loading bug fix
- Interactive guide tools for workflow assistance

### 🚧 In Progress
- Phase 4: Analysis Capabilities (mostly complete)
  - ✅ Property analysis tools (table operations, statistics, filtering)
  - ✅ Structure analysis tools (sequence extraction, ligand analysis, alignment)
  - ✅ GRN analysis tools (reference loading, alignment, assignment)
  - ✅ Sequence analysis tools (alignment, conservation, clustering)
  - ✅ Ligand analysis tools (properties, similarity, ChEMBL integration)
- Phase 5: Workflow Recreation

### New Tools Added
- **download_dataset_entities**: Downloads all entities referenced in a dataset
  - Supports parallel downloads for performance
  - Works with PDB, AlphaFold, and UniProt sources
  - Updates dataset metadata with download results

- **Property Analysis Tools**:
  - `create_property_table`: Create property tables from entity data
  - `add_property_column`: Add new properties to existing tables
  - `get_property_statistics`: Calculate statistics for properties
  - `filter_entities_by_property`: Filter entities based on property values
  - `merge_property_tables`: Combine multiple property tables
  - `get_entity_property_values`: Query properties for specific entities

- **Structure Analysis Tools**:
  - `extract_sequence_from_structure`: Extract amino acid sequences from structures
  - `get_all_sequences_from_structure`: Extract sequences from all chains
  - `get_structure_chains`: List chains in a structure
  - `get_ca_coordinates`: Get C-alpha coordinates for analysis
  - `extract_ligands_from_structure`: Find all ligands in a structure
  - `get_binding_site_residues`: Identify residues near ligands
  - `calculate_structure_properties`: Basic structural statistics
  - `align_protein_structures`: Align two structures using CEalign algorithm
  - `calculate_structure_rmsd_matrix`: Calculate RMSD matrix for multiple structures
  - `superimpose_structures`: Superimpose and save aligned structures

- **Ligand Analysis Tools**:
  - `calculate_molecular_properties`: Calculate molecular properties from SMILES
  - `search_similar_ligands`: Find similar molecules using Tanimoto similarity
  - `filter_drug_like_ligands`: Filter by Lipinski's rule of 5
  - `get_protein_ligands_from_chembl`: Download bioactive ligands from ChEMBL
  - `find_ligand_in_structures`: Find PDB structures containing a ligand
  - `create_ligand_dataset_from_chembl`: Create dataset from ChEMBL data
  - `smiles_to_inchi`: Convert SMILES to InChI representations

- **GRN Analysis Tools**:
  - `load_grn_reference_table`: Load reference GRN tables (e.g., GPCRdb)
  - `extract_sequences_from_structures`: Extract sequences from structure datasets
  - `align_sequences_to_reference`: Align sequences to GRN reference database
  - `assign_grn_to_sequences`: Assign GRN positions to aligned sequences
  - `create_grn_table`: Create and save GRN annotation tables
  - `get_grn_coverage_stats`: Calculate GRN coverage statistics
  - `get_grn_config`: Get GRN configuration for protein families

- **Sequence Analysis Tools**:
  - `align_sequences`: Perform pairwise sequence alignment
  - `calculate_sequence_identity`: Calculate pairwise sequence identities
  - `find_conserved_regions`: Find conserved regions across sequences
  - `detect_mutations`: Detect mutations between sequences
  - `translate_sequence`: Translate DNA/RNA to protein
  - `cluster_sequences`: Cluster sequences by similarity

- **Interactive Guide Tools**:
  - `protos_guide`: Get interactive guidance on Protos concepts and usage
  - `workflow_example`: Get step-by-step workflow examples with MCP tool calls
  - `explain_concept`: Get detailed explanations of Protos concepts

### Key Architecture Decisions
1. **MCP tools are thin wrappers** - they ONLY parse requests and format responses
2. **Protos handles ALL data operations** - MCP never touches files or paths
3. **Entity names are the interface** - users work with human-readable names only
4. **Processors do the work** - each has specific methods that MCP tools call

## Essential Commands

```bash
# Installation
cd protos && pip install -e .              # Install in development mode
cd protos && pip install -e ".[dev]"       # With dev tools
cd protos && pip install -e ".[all]"       # All features including GPU

# Testing
cd protos && python -m pytest tests/       # Run all tests
pytest -m "not integration"                # Skip integration tests
pytest -m "not slow"                       # Skip slow tests
pytest tests/test_core/ -v --tb=short      # Run specific test directory

# Code Quality (run from protos directory)
black src/                                 # Format code
isort src/                                 # Sort imports
black --check src/                         # Check formatting
flake8 src/                               # Lint code
mypy src/ --ignore-missing-imports         # Type checking

# MCP Server Integration
python claude_server.py                    # For Claude integration
python ollama_server.py                    # For Ollama integration
```

## ProtosPaths System

ProtosPaths handles path management throughout the Protos framework:

```python
# Key classes in protos.io.paths
from protos.io.paths.path_config import ProtosPaths, DataSource

# Initialization
paths = ProtosPaths(
    data_root=None  # Uses env var PROTOS_DATA_ROOT or defaults to ~/protos_data
)

# Core functions
structure_path = paths.get_processor_path("structure")
abs_path = paths.resolve_path("dataset.json", source=DataSource.USER)
exists, source = paths.exists("structure/1abc.cif")

# Global helpers (from protos.io.paths)
structure_file = get_structure_path("1abc")
dataset_file = get_dataset_path("my_dataset", processor_type="structure")
```

## DatasetManager

DatasetManager provides standardized dataset operations:

```python
# In protos.core.dataset_manager
manager = DatasetManager(
    processor_type="structure",  # Processor type
    paths=paths                  # Path resolver instance
)

# Dataset operations
dataset = manager.create_dataset(
    dataset_id="my_dataset",
    name="My Structure Dataset",
    description="A collection of structure IDs",
    content=["1abc", "2xyz", "3def"],
    metadata={"source": "PDB"}
)

dataset = manager.load_dataset("my_dataset")
structures = dataset.content
manager.save_dataset(dataset)
datasets = manager.list_datasets()
manager.delete_dataset("my_dataset")
```

## BaseProcessor

BaseProcessor is the foundation for all processor types:

```python
# In protos.core.base_processor
class StructureProcessor(BaseProcessor):
    def __init__(self, name, data_root=None, config=None):
        super().__init__(
            name=name,
            data_root=data_root,
            processor_data_dir="structure", # Directory name
            config=config
        )

# Initialization pattern for processors
processor = StructureProcessor(
    name="my_processor",     # Identifier
    data_root="~/data",      # Custom data location (optional)
    config={"param": "val"}  # Configuration values
)

# Common methods
data = processor.load_data("dataset_id", file_format="csv")
processor.save_data("results", data=processed_data, file_format="json")
dataset = processor.create_standard_dataset(
    dataset_id="std_dataset",
    name="Standard Dataset",
    content=["item1", "item2"]
)
```

## Integration Flow

1. BaseProcessor creates ProtosPaths instance during initialization
2. BaseProcessor initializes DatasetManager with paths and processor type
3. When loading/saving:
   - ProtosPaths resolves file paths
   - DatasetManager handles dataset operations
   - BaseProcessor manages format conversion and error handling

## High-Level Architecture

### Data Flow
1. **Entity Registry** (`data/entity_registry.json`): Universal tracking system that maps entities across different data formats
2. **ProtosPaths**: Automatically resolves all file paths - never hardcode paths
3. **BaseProcessor**: All processors inherit from this, providing standardized load/save operations
4. **DatasetManager**: Handles dataset CRUD operations for all processor types

### Directory Structure
```
protos/                    # Core library
├── src/protos/           # Main source code
│   ├── core/            # BaseProcessor, DatasetManager, EntityRegistry
│   ├── io/              # ProtosPaths and file handling
│   └── processors/      # Specialized processors (structure, sequence, etc.)
├── tests/               # Pytest test suite
└── data/               # Auto-managed data directory

mcp_server/              # MCP integration
├── tools/              # MCP tool implementations
└── server.py           # Server base class

data/                   # User data (auto-created)
├── entity_registry.json
├── structure/          # PDB/mmCIF files
├── sequence/           # FASTA files
├── grn/               # Generic Residue Numbering
├── property/          # Experimental properties
├── embedding/         # ML embeddings
├── ligand/            # Ligand data
└── graph/             # Network data
```

### Key Architectural Principles
1. **Zero Configuration**: Everything works with sensible defaults
2. **Entity-Centric**: Same biological entity tracked across all data types
3. **Processor Pattern**: Each data type has a specialized processor inheriting from BaseProcessor
4. **Standardized I/O**: All processors use consistent load/save patterns
5. **MCP Integration**: Stateless functions expose Protos functionality to LLMs

### Common Development Patterns

```python
# Always use ProtosPaths for file operations
from protos.io.paths import get_structure_path, get_dataset_path
structure_file = get_structure_path("1abc")  # Not "data/structure/1abc.cif"

# Processor initialization pattern
from protos.processors import StructureProcessor
processor = StructureProcessor(name="my_processor")  # Auto-handles paths

# Dataset operations pattern
dataset = processor.create_standard_dataset(
    dataset_id="my_dataset",
    name="My Dataset",
    content=["id1", "id2", "id3"]
)
results = processor.process_dataset(dataset)

# MCP tool processor validation pattern
from mcp_server.core.processor_factory import ProcessorFactory
valid_types = ProcessorFactory.get_available_processors()
if processor_type not in valid_types:
    raise ValueError(f"Invalid processor type. Valid types: {valid_types}")
```

### MCP Tool Development
When adding new MCP tools:
1. Add tool definition to `mcp_server/tools/`
2. Follow stateless function pattern with clear input/output
3. Use standardized error messages for LLM consumption
4. Update server.py to register the new tool
5. Always validate processor types using ProcessorFactory

### Testing Strategy
- Unit tests for individual components
- Integration tests for processor workflows
- Markers for conditional testing (gpu, network, slow)
- Always test with `pytest -m "not integration"` for quick feedback