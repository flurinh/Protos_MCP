# Protos-MCP Implementation TODO

## Executive Summary

The Protos-MCP implementation is now functionally complete for core data management operations. All critical path handling issues have been resolved, ensuring that MCP tools act as thin wrappers that delegate ALL file and data operations to Protos processors. The system now properly supports all data formats (structure, sequence, GRN, property, ligand) with full CRUD operations and dataset management.

### ✅ What Works
- Entity operations (download, load, save, delete) for all formats
- Dataset management (create, list, load, update) 
- Proper path delegation - MCP never touches files directly
- API accepts JSON objects (not just strings)
- Enhanced error messages with actionable suggestions

### ⚠️ Known Issues
- BaseProcessor has a bug accessing dataset['entities'] instead of dataset.content
- Datasets may reference entities that haven't been downloaded (user workflow issue)

### 🚧 Next Steps
- Implement remaining analysis tools (GRN assignment, sequence analysis, etc.)
- Create high-level workflow tools
- Add embedding analysis tools

## Overview
This document outlines the implementation plan for serving Protos' data management capabilities through MCP servers. The goal is to provide a seamless, path-management-free experience for users while enabling full recreation of example workflows through AI assistants.

## 🎉 Progress Update (2025-07-23)

### Completed Tasks ✅
1. **Core Infrastructure Setup**
   - Created clean modular server architecture
   - Implemented ServerContext with ProtosPaths integration
   - Fixed processor initialization with correct parameters
   - Set up proper error handling with LLM-friendly messages

2. **Entity Management Tools**
   - Implemented entity discovery (list_entities, search_entities, entity_info)
   - Implemented entity operations (download_entity, load_entity, save_entity, delete_entity)
   - Fixed processor-specific method calls
   - Fixed sequence loading to handle both single and multi-sequence files
   - Added proper save_entity support for all processor types (structure, sequence, GRN, property, ligand)

3. **Path Management Fixes** 🔴 CRITICAL
   - Removed ALL direct path manipulation from MCP tools
   - Fixed file path construction in save_entity - now delegates to Protos
   - Fixed AlphaFold download to use default Protos paths
   - Removed direct filesystem access in dataset operations
   - Ensured ALL path operations go through ProtosPaths

4. **Dataset Operations**
   - Implemented dataset CRUD using Protos DatasetManager
   - Fixed dataset listing to use processor methods only
   - Improved error messages for missing entities vs missing datasets
   - All dataset operations properly delegate to Protos
   - Added `download_dataset_entities` tool to download all entities in a dataset
   - Supports parallel downloads for large datasets
   - Works with structure (PDB/AlphaFold) and sequence (UniProt) sources

5. **API Improvements**
   - save_entity now accepts JSON objects directly (not just strings)
   - Better handling of different data formats in load_entity
   - Enhanced error messages with actionable suggestions
   - Added processor type validation to all tools using ProcessorFactory registry

### Key Learnings
- ProtosPaths only accepts `data_root` parameter (not the multiple params in old docs)
- Different processors have different constructor signatures
- Entity registry is managed through processors, not accessed directly
- Data must be downloaded first before listing/loading operations work
- StructureProcessor uses `load_structures()` not `load_entity()`
- Each processor has different save method names (see Critical section below)
- MCP tools must NEVER handle paths - only Protos does path management

### Current Status
- ✅ Server starts successfully with Claude Desktop
- ✅ ProtosPaths initialization works
- ✅ Processor factory creates processors correctly
- ✅ Download functionality works through Protos loaders
- ✅ Entity discovery and operations implemented
- ✅ Dataset management tools completed
- ✅ All path operations delegated to Protos
- ✅ Processor type validation implemented
- ✅ Analysis capabilities (Property ✅, Structure ✅, Ligand ✅, GRN ✅, Sequence ✅)
- ⏳ Workflow recreation

## 🏗️ Proposed Server Architecture

### Directory Structure
```
mcp_server/
├── __init__.py
├── server.py                    # Main server with lifespan management
├── config.py                    # Configuration management
├── context.py                   # Server context and state management
│
├── core/                        # Core infrastructure
│   ├── __init__.py
│   ├── protos_manager.py       # ProtosPaths and processor management
│   ├── processor_factory.py    # Processor creation and caching
│   └── exceptions.py           # Custom exceptions
│
├── tools/                       # MCP tool implementations
│   ├── __init__.py
│   ├── base.py                 # Base tool class with common functionality
│   │
│   ├── entity/                 # Entity management tools
│   │   ├── __init__.py
│   │   ├── discovery.py        # list_entities, search_entities, entity_info
│   │   └── operations.py       # download_entity, save_entity, load_entity, delete_entity
│   │
│   ├── dataset/                # Dataset management tools
│   │   ├── __init__.py
│   │   └── operations.py       # create_dataset, list_datasets, load_dataset, etc.
│   │
│   ├── analysis/               # Analysis tools by domain
│   │   ├── __init__.py
│   │   ├── structure.py        # Structure analysis tools
│   │   ├── grn.py             # GRN assignment tools
│   │   ├── sequence.py        # Sequence analysis tools
│   │   ├── property.py        # Property management tools
│   │   ├── embedding.py       # Embedding generation tools
│   │   └── ligand.py          # Ligand analysis tools
│   │
│   └── workflow/              # High-level workflow tools
│       ├── __init__.py
│       ├── grn_workflow.py    # Complete GRN assignment workflow
│       └── ligand_workflow.py # Complete ligand analysis workflow
│
├── utils/                     # Utility functions
│   ├── __init__.py
│   ├── serialization.py      # Data serialization for MCP
│   ├── validation.py         # Input validation
│   └── formatting.py         # Output formatting
│
└── tests/                    # Test suite
    ├── __init__.py
    ├── test_core/
    ├── test_tools/
    └── test_integration/
```

### Architecture Principles

1. **Separation of Concerns**
   - Core infrastructure separate from tools
   - Domain-specific tools in dedicated modules
   - Shared utilities and base classes

2. **Single Responsibility**
   - Each tool handles one specific operation
   - Complex workflows composed from simple tools
   - Clear input/output contracts

3. **Dependency Injection**
   - Tools receive context/dependencies via constructor
   - No global state or imports
   - Testable and mockable

4. **Progressive Implementation**
   - Start with core data management
   - Add format-specific processing
   - Finally implement complex workflows

## 🔴 CRITICAL: Protos Data Management Principles

### Absolute Rules for MCP Implementation

1. **Protos Handles ALL Data Management**
   - MCP tools are ONLY a thin interface layer
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

### Processor-Specific Save Methods

**CRITICAL**: Each processor has different save method names and signatures. MCP tools MUST use the correct method for each processor type:

#### StructureProcessor
```python
# Primary save methods:
processor.save_structure(name: str, structure_df: pd.DataFrame, format: str = 'pkl')
processor.save_entity(name: str, data: pd.DataFrame)  # Saves to cache

# For CIF format:
processor.save_cif(df, output_path)  # Protos handles path

# For sequences extracted from structures:
processor.save_chain_dict_to_fasta()  # Saves all chains
```

#### SequenceProcessor  
```python
# Primary save methods:
processor.save_entity(name: str, data: Union[str, Dict[str, str]])
processor.save_sequences(sequences: Dict[str, str], output_file: str)

# For alignments:
processor.save_alignment(alignment_data: Dict, output_file: str)
```

#### GRNProcessor
```python
# Primary save methods:
processor.save_grn_table(dataset_id: str, normalize_formats: bool = True)
processor.save_entity(name: str, data: pd.Series)  # Adds row to table
processor.save_data(name: str, data: Any, file_format: str = 'csv')
```

#### PropertyProcessor
```python
# Primary save method:
processor.save_property_table(dataset_name: str, metadata: Optional[Dict] = None)

# Note: save_entity() logs warning - use assign_property() instead:
processor.assign_property(entity: str, property_name: str, value: Any)
```

#### LigandProcessor
```python
# Primary save method:
processor.save_entity(name: str, data: Dict, metadata: Optional[Dict] = None)
# Saves both JSON metadata and SDF structure file
```

### MCP Implementation Pattern

```python
# ❌ WRONG - MCP tool handling paths
def save_entity_wrong(name, data, format):
    file_path = f"/data/{format}/{name}.ext"  # NEVER DO THIS
    with open(file_path, 'w') as f:
        f.write(data)

# ✅ CORRECT - Let Protos handle everything
def save_entity_correct(name, data, format):
    processor = get_processor(format)
    
    if format == "structure":
        processor.save_structure(name, data)
    elif format == "sequence":
        processor.save_entity(name, data)
    elif format == "grn":
        processor.save_grn_table(name)
    elif format == "property":
        processor.save_property_table(name)
    elif format == "ligand":
        processor.save_entity(name, data)
```

### Data Flow Architecture

```
LLM Request → MCP Tool → Protos Processor → ProtosPaths → File System
                ↓                  ↓              ↓
              Simple          Core Logic    Path Resolution
              Interface       & Validation   & Management
```

MCP tools should be extremely thin wrappers that:
1. Parse incoming requests
2. Call appropriate Protos methods
3. Format responses for LLMs

ALL complexity lives in Protos, NOT in MCP tools.

## 🎯 Implementation Phases

### Phase 1: Core Infrastructure Setup ✅ (COMPLETED)

#### 1.1 Server Core Components

**File: `mcp_server/context.py`**
```python
@dataclass
class ServerContext:
    """Central server state management"""
    paths: ProtosPaths
    entity_registry: EntityRegistry
    processors: Dict[str, BaseProcessor]
    config: ServerConfig
    
    @classmethod
    def initialize(cls, config: ServerConfig) -> 'ServerContext':
        """Initialize all core components"""
        paths = ProtosPaths(base_path=config.data_root)
        return cls(
            paths=paths,
            entity_registry=EntityRegistry(paths),
            processors={},
            config=config
        )
```

**File: `mcp_server/core/protos_manager.py`**
```python
class ProtosManager:
    """Manages ProtosPaths and processor lifecycle"""
    def __init__(self, context: ServerContext):
        self.context = context
        self._processor_cache = {}
    
    def get_processor(self, processor_type: str) -> BaseProcessor:
        """Get or create processor instance"""
        if processor_type not in self._processor_cache:
            self._processor_cache[processor_type] = self._create_processor(processor_type)
        return self._processor_cache[processor_type]
```

**File: `mcp_server/core/processor_factory.py`**
```python
class ProcessorFactory:
    """Factory for creating processor instances"""
    _registry = {
        "structure": StructureProcessor,
        "sequence": SequenceProcessor,
        "grn": GRNProcessor,
        "property": PropertyProcessor,
        "embedding": EmbeddingProcessor,
        "ligand": LigandProcessor,
        "graph": GraphProcessor
    }
    
    @classmethod
    def create(cls, processor_type: str, paths: ProtosPaths) -> BaseProcessor:
        """Create processor with injected paths"""
        if processor_type not in cls._registry:
            raise ValueError(f"Unknown processor type: {processor_type}")
        return cls._registry[processor_type](paths=paths)
```

#### 1.2 Configuration Management

**File: `mcp_server/config.py`**
```python
class ServerConfig:
    """Server configuration with smart defaults"""
    def __init__(self, config_path: Optional[Path] = None):
        self.data_root = self._resolve_data_root()
        self.cache_enabled = True
        self.max_memory_mb = 4096
        self.processor_defaults = {}
        
        if config_path and config_path.exists():
            self._load_from_file(config_path)
    
    def _resolve_data_root(self) -> Path:
        """Resolve data directory with fallback chain"""
        # 1. Environment variable
        if env_root := os.environ.get("PROTOS_DATA_ROOT"):
            return Path(env_root)
        
        # 2. Current directory
        if (cwd_data := Path.cwd() / "data").exists():
            return cwd_data
        
        # 3. User home
        user_data = Path.home() / "protos_data"
        user_data.mkdir(exist_ok=True)
        return user_data
```

#### 1.3 Tool Base Infrastructure

**File: `mcp_server/tools/base.py`**
```python
class BaseTool:
    """Base class for all MCP tools"""
    def __init__(self, context: ServerContext):
        self.context = context
        self.paths = context.paths
        self.registry = context.entity_registry
    
    def get_processor(self, processor_type: str) -> BaseProcessor:
        """Get processor instance from context"""
        return self.context.processors.get(processor_type) or \
               self._create_processor(processor_type)
    
    def format_success(self, data: Any, metadata: Optional[Dict] = None) -> Dict:
        """Standard success response"""
        return {
            "success": True,
            "data": data,
            "metadata": metadata or {}
        }
    
    def format_error(self, error: str, suggestion: Optional[str] = None) -> Dict:
        """Standard error response"""
        return {
            "success": False,
            "error": error,
            "suggestion": suggestion
        }
```

### Phase 2: Entity Management Tools ✅ (COMPLETED)

#### 2.1 Implementation Structure

**File: `mcp_server/tools/entity/discovery.py`**
```python
class EntityDiscoveryTools(BaseTool):
    """Tools for discovering and searching entities"""
    
    @mcp_tool()
    def list_entities(self, processor_type: str, 
                     filter_metadata: Optional[Dict] = None) -> Dict:
        """List all entities for a processor type"""
        try:
            processor = self.get_processor(processor_type)
            entities = processor.list_entities()
            
            if filter_metadata:
                # Apply metadata filtering
                entities = self._filter_by_metadata(entities, filter_metadata)
            
            return self.format_success({
                "processor_type": processor_type,
                "count": len(entities),
                "entities": entities
            })
        except Exception as e:
            return self.format_error(str(e))
    
    @mcp_tool()
    def search_entities(self, query: str, 
                       processor_types: Optional[List[str]] = None) -> Dict:
        """Search entities across processor types"""
        # Implementation details...
    
    @mcp_tool()
    def entity_info(self, entity_name: str) -> Dict:
        """Get comprehensive entity information"""
        # Implementation details...
```

**File: `mcp_server/tools/entity/operations.py`**
```python
class EntityOperationTools(BaseTool):
    """Tools for entity CRUD operations"""
    
    @mcp_tool()
    def download_entity(self, entity_id: str, source: str = "pdb",
                       processor_type: str = "structure") -> Dict:
        """Download and register entity"""
        try:
            processor = self.get_processor(processor_type)
            
            # Download based on source
            if source == "pdb":
                from protos.loaders.download_structures import download_structures_with_processor
                success, failed = download_structures_with_processor(
                    [entity_id], processor
                )
                
            return self.format_success({
                "entity_id": entity_id,
                "downloaded": success,
                "source": source
            })
        except Exception as e:
            return self.format_error(str(e))
    
    @mcp_tool()
    def save_entity(self, name: str, data: str, 
                   format: str, metadata: Optional[Dict] = None) -> Dict:
        """Save entity with automatic registration"""
        # Implementation details...
    
    @mcp_tool()
    def load_entity(self, name: str, format: str) -> Dict:
        """Load entity data in standardized format"""
        # Implementation details...
    
    @mcp_tool()
    def delete_entity(self, name: str, formats: List[str]) -> Dict:
        """Delete entity from specified formats"""
        # Implementation details...
```

### Phase 3: Dataset Management Tools 🚧 (Current Focus)

#### 3.1 Implementation Structure

**File: `mcp_server/tools/dataset/operations.py`**
```python
class DatasetOperationTools(BaseTool):
    """Tools for dataset management"""
    
    @mcp_tool()
    def create_dataset(self, name: str, entities: List[str], 
                      processor_type: str, metadata: Optional[Dict] = None) -> Dict:
        """Create a new dataset"""
        try:
            processor = self.get_processor(processor_type)
            
            # Validate entities exist
            missing = [e for e in entities if not processor.entity_exists(e)]
            if missing:
                return self.format_error(
                    f"Entities not found: {missing}",
                    "Use download_entity or save_entity first"
                )
            
            # Create dataset
            processor.create_dataset(name, entities, metadata)
            
            return self.format_success({
                "dataset_name": name,
                "entity_count": len(entities),
                "processor_type": processor_type
            })
        except Exception as e:
            return self.format_error(str(e))
    
    @mcp_tool()
    def list_datasets(self, processor_type: str) -> Dict:
        """List available datasets"""
        # Implementation details...
    
    @mcp_tool()
    def load_dataset(self, name: str, processor_type: str,
                    format: str = "default") -> Dict:
        """Load dataset with appropriate formatting"""
        try:
            processor = self.get_processor(processor_type)
            data = processor.load_dataset(name)
            
            # Format based on processor type
            if processor_type in ["structure", "sequence"]:
                # Return as dict of entities
                formatted = {entity: self._serialize_data(d) 
                           for entity, d in data.items()}
            elif processor_type in ["grn", "property"]:
                # Return as table
                formatted = self._serialize_dataframe(data)
            
            return self.format_success({
                "dataset_name": name,
                "processor_type": processor_type,
                "data": formatted
            })
        except Exception as e:
            return self.format_error(str(e))
```

### Phase 4: Analysis Capabilities

#### 4.1 Domain-Specific Analysis Tools

**File: `mcp_server/tools/analysis/structure.py`**
```python
class StructureAnalysisTools(BaseTool):
    """Structure-specific analysis tools"""
    
    @mcp_tool()
    def extract_sequence(self, pdb_id: str, chain: str = "A",
                        save_to_sequence: bool = True) -> Dict:
        """Extract sequence from structure"""
        try:
            struct_proc = self.get_processor("structure")
            struct_proc.load_structures([pdb_id])
            
            # Extract sequence
            sequence = struct_proc.get_sequence(pdb_id, chain)
            
            if save_to_sequence:
                # Auto-save to sequence processor
                seq_proc = self.get_processor("sequence")
                seq_proc.save_sequence(f"{pdb_id}_{chain}", sequence)
            
            return self.format_success({
                "pdb_id": pdb_id,
                "chain": chain,
                "sequence": sequence,
                "length": len(sequence),
                "saved": save_to_sequence
            })
        except Exception as e:
            return self.format_error(str(e))
    
    @mcp_tool()
    def calculate_rmsd(self, structures: List[str], 
                      alignment_type: str = "backbone") -> Dict:
        """Calculate RMSD between structures"""
        # Implementation using FoldMason or similar
    
    @mcp_tool()
    def extract_ligands(self, pdb_id: str) -> Dict:
        """Extract ligand information from structure"""
        try:
            lig_proc = self.get_processor("ligand")
            ligands = lig_proc.extract_ligands(pdb_id)
            
            return self.format_success({
                "pdb_id": pdb_id,
                "ligand_count": len(ligands),
                "ligands": [{
                    "name": lig.name,
                    "chain": lig.chain,
                    "atoms": len(lig.atoms)
                } for lig in ligands]
            })
        except Exception as e:
            return self.format_error(str(e))
```

**File: `mcp_server/tools/analysis/grn.py`**
```python
class GRNAnalysisTools(BaseTool):
    """GRN assignment and analysis tools"""
    
    @mcp_tool()
    def assign_grn(self, sequences: Dict[str, str], 
                   reference: str = "gpcrdb_ref",
                   family: str = "gpcr_a") -> Dict:
        """Perform GRN assignment on sequences"""
        try:
            grn_proc = self.get_processor("grn")
            
            # Load reference
            grn_proc.load_reference_table(reference)
            
            # Get config
            config = grn_proc.get_grn_config(family)
            
            # Perform assignment
            grn_table = grn_proc.assign_grn_batch(sequences, config)
            
            return self.format_success({
                "sequence_count": len(sequences),
                "reference": reference,
                "family": family,
                "grn_table": self._serialize_dataframe(grn_table)
            })
        except Exception as e:
            return self.format_error(str(e))
```

**File: `mcp_server/tools/analysis/property.py`**
```python
class PropertyAnalysisTools(BaseTool):
    """Property management tools"""
    
    @mcp_tool()
    def assign_property(self, entity: str, property_name: str,
                       value: Any, dataset: Optional[str] = None) -> Dict:
        """Assign property to entity"""
        try:
            prop_proc = self.get_processor("property")
            prop_proc.assign_property(entity, property_name, value, dataset)
            
            return self.format_success({
                "entity": entity,
                "property": property_name,
                "value": value,
                "dataset": dataset
            })
        except Exception as e:
            return self.format_error(str(e))
```

### Phase 5: Workflow Recreation

#### 5.1 High-Level Workflow Implementation

**File: `mcp_server/tools/workflow/grn_workflow.py`**
```python
class GRNWorkflowTools(BaseTool):
    """Complete GRN assignment workflow"""
    
    @mcp_tool()
    def run_grn_workflow(self, dataset_name: str, 
                        reference: str = "gpcrdb_ref",
                        family: str = "gpcr_a",
                        save_results: bool = True) -> Dict:
        """Execute complete GRN assignment workflow"""
        try:
            # Step 1: Load structures
            struct_proc = self.get_processor("structure")
            struct_proc.load_dataset(dataset_name)
            
            # Step 2: Extract sequences
            sequences = struct_proc.get_seq_dict()
            
            # Step 3: Perform alignment
            grn_proc = self.get_processor("grn")
            alignment_df = grn_proc.align_to_reference(sequences, reference)
            
            # Step 4: Filter by identity
            filtered = alignment_df[alignment_df['sequence_identity'] > 0.25]
            
            # Step 5: Assign GRN
            grn_table = grn_proc.assign_grn_from_alignment(filtered, family)
            
            # Step 6: Save results
            if save_results:
                grn_proc.save_grn_table(f"{dataset_name}_grn", grn_table)
            
            return self.format_success({
                "dataset": dataset_name,
                "sequence_count": len(sequences),
                "aligned_count": len(filtered),
                "grn_assignments": len(grn_table),
                "saved": save_results
            })
        except Exception as e:
            return self.format_error(str(e))
```

**File: `mcp_server/tools/workflow/ligand_workflow.py`**
```python
class LigandWorkflowTools(BaseTool):
    """Complete ligand analysis workflow"""
    
    @mcp_tool()
    def run_ligand_workflow(self, pdb_id: str,
                           analyze_pockets: bool = True,
                           fetch_bioactivity: bool = True) -> Dict:
        """Execute complete ligand analysis workflow"""
        # Implementation matching test_ligand_workflow.py
```

## 🔧 Technical Implementation Details

### Tool Design Principles

1. **Stateless Operations**
   ```python
   @mcp_tool
   def load_structure(params: Dict) -> Dict:
       # Get context from server
       context = get_server_context()
       processor = context.get_processor("structure")
       
       # Perform operation
       result = processor.load_structure(params["pdb_id"])
       
       # Return standardized output
       return {
           "success": True,
           "data": result.to_dict(),
           "metadata": {...}
       }
   ```

2. **Error Handling**
   ```python
   try:
       result = operation()
   except FileNotFoundError:
       return {
           "success": False,
           "error": "Entity not found",
           "suggestion": "Use download_entity first"
       }
   ```

3. **Batch Operations**
   ```python
   @mcp_tool
   def batch_operation(params: Dict) -> Dict:
       results = []
       errors = []
       
       for item in params["items"]:
           try:
               result = process_item(item)
               results.append(result)
           except Exception as e:
               errors.append({"item": item, "error": str(e)})
       
       return {
           "success": len(errors) == 0,
           "results": results,
           "errors": errors
       }
   ```

### Data Format Standards

1. **Structure Data**
   ```json
   {
     "pdb_id": "1ubq",
     "chains": ["A"],
     "atoms": [...],
     "metadata": {
       "resolution": 1.8,
       "method": "X-RAY"
     }
   }
   ```

2. **Sequence Data**
   ```json
   {
     "entity_name": "EGFR_HUMAN",
     "sequence": "MKVLG...",
     "length": 1210,
     "metadata": {
       "organism": "Homo sapiens",
       "uniprot_id": "P00533"
     }
   }
   ```

3. **GRN Data**
   ```json
   {
     "entity": "BACR_HALSA",
     "positions": {
       "1.50": "A",
       "2.50": "L",
       "3.50": "V"
     }
   }
   ```

### Memory Management

1. **Streaming Large Datasets**
   - Return data in chunks
   - Support pagination
   - Implement iterators

2. **Cache Management**
   - LRU cache for processors
   - Configurable cache size
   - Clear cache commands

3. **Resource Limits**
   - Maximum dataset size
   - Memory usage monitoring
   - Graceful degradation

## 📅 Timeline

### Week 1-2: Phase 1 (Core Infrastructure)
- Server context implementation
- ProtosPaths integration
- Basic processor management

### Week 3-4: Phase 2 (Entity Management)
- Entity discovery tools
- CRUD operations
- Cross-format tracking

### Week 5-6: Phase 3 (Dataset Management)
- Dataset operations
- Batch processing
- Metadata handling

### Week 7-8: Phase 4 (Analysis Tools)
- Structure analysis
- GRN assignment
- Property management

### Week 9-10: Phase 5 (Workflow Recreation)
- Example workflow implementation
- Pipeline system
- Testing and refinement

## 🧪 Testing Strategy

### Unit Tests
- Test each MCP tool individually
- Mock processor operations
- Verify error handling

### Integration Tests
- Test complete workflows
- Verify data persistence
- Check cross-tool compatibility

### Performance Tests
- Large dataset handling
- Memory usage profiling
- Response time benchmarks

### LLM Compatibility Tests
- Test with Claude
- Test with Ollama
- Verify error message clarity

## 📋 Success Criteria

1. **Zero Path Management**: Users never specify file paths
2. **Workflow Parity**: Can recreate all example workflows
3. **Error Clarity**: LLMs can understand and relay errors
4. **Performance**: <1s response for most operations
5. **Reliability**: 99%+ success rate for standard operations

## 🚀 Implementation Strategy - Leveraging Protos

### Core Principle: Protos Does the Work
**We are NOT reimplementing functionality - we are exposing Protos' existing capabilities through MCP tools**

### Phase 2.5: Multi-Format Entity Operations ✅ COMPLETED

1. **Structure Format** ✅
   - [x] download_entity (via download_structures_with_processor)
   - [x] list_entities (via processor.list_entities)
   - [x] load_entity (via processor.load_structures)
   - [x] save_entity (via processor.save_structure or save_entity)

2. **Sequence Format** ✅
   - [x] download_entity (from UniProt via Protos loaders)
   - [x] save_entity (via processor.save_entity or save_sequence)
   - [x] load_entity (handles both single and multi-sequence files)
   - [x] list_entities (via processor.list_entities)

3. **GRN Format** ✅
   - [x] save_entity (converts dict to pd.Series, uses processor.save_entity)
   - [x] load_entity (via processor.load or load_entity)
   - [x] list_entities (via processor.list_entities)

4. **Property Format** ✅
   - [x] save_entity (uses processor.assign_property for each property)
   - [x] load_entity (via processor.get_entity_properties)
   - [x] list_entities (via processor.list_entities)

5. **Ligand Format** ✅
   - [x] save_entity (via processor.save_entity with metadata)
   - [x] load_entity (via processor.load_entity)
   - [x] list_entities (via processor.list_entities)

### Phase 3: Dataset Management ✅ COMPLETED
**Key insight: Processors already have dataset methods - we just expose them!**

1. **Core Dataset Operations**
   - [x] create_dataset - Uses processor.create_standard_dataset()
   - [x] list_datasets - Uses processor.list_datasets() or dataset_manager
   - [x] load_dataset - Uses processor.load_dataset()
   - [x] dataset_info - Uses processor.get_dataset_info()
   - [x] update_dataset - Uses dataset_manager methods

2. **Implementation Approach**
   ```python
   # NOT this:
   def create_dataset_custom_logic()  # ❌
   
   # But this:
   processor.create_standard_dataset()  # ✅ Let Protos handle it
   ```

### Completed Metrics ✅
- [x] Server starts with ProtosPaths initialized
- [x] Can list entities without specifying paths
- [x] Clean separation between infrastructure and tools
- [x] Basic error handling works
- [x] Download functionality operational
- [x] Entity operations functional for ALL formats
- [x] Dataset operations fully implemented
- [x] ALL path operations delegated to Protos
- [x] API accepts JSON objects directly
- [x] Enhanced error messages with actionable suggestions

### Design Decisions Made
1. **Data Serialization Format** ✅
   - JSON for metadata and simple data
   - Base64 for binary data (structures) 
   - DataFrame.to_dict() for tabular data
   - Summary format for large datasets

2. **Processor Initialization** ✅
   - Each processor has different constructor parameters
   - Most take (name, paths), EmbeddingProcessor takes only name
   - Factory pattern handles differences

3. **Error Handling Strategy** ✅
   - ProtosMCPError base class with suggestions
   - LLM-friendly error messages
   - Fallback methods for processor operations

### Lessons Learned
1. **Protos Architecture**
   - Entity registry is part of processors, not standalone
   - Must download data before listing/loading works
   - Different processors have different method names (load_structures vs load_entity)
   - Processors already have full dataset management built in!
   - Dataset objects have .content attribute, not ['entities'] key
   - Each processor has specific save methods (see documentation)

2. **MCP Integration**
   - Context access varies by MCP version
   - Windows requires explicit Python executable path
   - Environment variables needed for PYTHONPATH and PROTOS_DATA_ROOT
   - MCP tools must be thin wrappers - NO path handling

3. **Path Management** 🔴 CRITICAL
   - ProtosPaths constructor only takes data_root parameter
   - Processors handle their own subdirectories
   - No manual path construction needed
   - MCP tools NEVER touch paths - only call processor methods
   - ALL file operations must go through Protos processors

### Key Protos Methods to Leverage

1. **BaseProcessor Dataset Methods** (inherited by all processors)
   ```python
   # Dataset operations
   processor.create_standard_dataset(dataset_id, name, content)
   processor.load_dataset(dataset_id)
   processor.save_dataset(dataset_id, data)
   processor.list_datasets()
   processor.get_dataset_info(dataset_id)
   
   # Entity operations
   processor.list_entities()
   processor.entity_exists(name)
   ```

2. **Format-Specific Methods**
   ```python
   # StructureProcessor
   processor.load_structures(pdb_ids)
   processor.download_structure(pdb_id)
   
   # SequenceProcessor  
   processor.load_sequence(name)
   processor.save_sequence(name, sequence)
   
   # GRNProcessor
   processor.load_grn_table(name)
   processor.save_grn_table(name, df)
   
   # PropertyProcessor
   processor.assign_property(entity, property, value)
   processor.get_entity_properties(entity)
   
   # LigandProcessor
   processor.extract_ligands(pdb_id)
   processor.save_ligand(name, ligand_data)
   ```

---

## 📋 Remaining Tasks

### High Priority
1. **Fix BaseProcessor Bug** ✅ COMPLETED
   - BaseProcessor.load_dataset tries to access dataset['entities']
   - Should use dataset.content instead
   - Fixed in protos/src/protos/core/base_processor.py line 237

2. **Add Processor Type Validation** ✅ COMPLETED
   - Validate processor_type parameter against available processors
   - Use ProcessorFactory registry for validation
   - Added validate_processor_type() method to BaseTool
   - All MCP tools now validate processor types before use

### Medium Priority
1. **Fix Embedding Processor**
   - Update initialization to match new constructor signature
   - Ensure it works with ProtosPaths properly

### Low Priority
1. **Implement Analysis Tools**
   - Structure analysis (RMSD, alignment, etc.)
   - GRN assignment workflows
   - Property analysis and aggregation
   - Ligand interaction analysis

2. **Implement Workflow Tools**
   - Complete GRN assignment workflow
   - Ligand analysis workflow
   - Cross-format analysis pipelines

## 🐛 Known Issues

1. **Dataset Loading Error**
   - When dataset references entities that haven't been downloaded
   - Error message now clarifies this is a missing entity issue
   - Solution: Download all entities before loading dataset

2. **BaseProcessor.load_dataset Bug** ✅ FIXED
   - Was trying to access dataset['entities'] but should use dataset.content
   - Fixed in BaseProcessor to properly check for content attribute

*Last updated: 2025-07-23 - Phase 1, 2, 2.5, and 3 completed*