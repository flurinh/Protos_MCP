# Protos Architecture Status Report
**Date:** 2025-12-10
**Purpose:** Document current state for refactoring to modern architecture

---

## Executive Summary

Protos has **mostly migrated** to a modern architecture with per-entity storage and standardized `load_entity()`/`save_entity()` patterns. However, **legacy code remnants** in the analysis modules and deprecated files cause runtime failures when using modern processors.

### Critical Issue
The `structure_ligand_analysis.py` module directly accesses `processor.data` attribute which doesn't exist in modern processors, breaking ligand workflows.

---

## 1. Processor Status

| Processor | Status | Pattern | Notes |
|-----------|--------|---------|-------|
| **StructureProcessor** | ✅ MODERN | Per-entity PKL | Lazy stacking via `frames` dict |
| **SequenceProcessor** | ✅ MODERN | Per-entity FASTA | Dual single/multi-sequence support |
| **GRNProcessor** | ✅ MODERN | CSV table-based | Per-sequence rows with caching |
| **PropertyProcessor** | ✅ MODERN | CSV table-based | Scope-based relationships |
| **LigandProcessor** | ✅ MODERN | SDF/SMILES + cache | LigandRecord dataclass |
| **EmbeddingProcessor** | ✅ MODERN | PKL + metadata JSON | Model registry pattern |
| **GraphProcessor** | ✅ MODERN | PyTorch Geometric | Contact cutoff config |

### Modern Pattern (All Processors)
```python
# Load
data = processor.load_entity(name)

# Save
processor.save_entity(name, data, metadata={...})

# Dataset operations
processor.create_dataset(name, entities, metadata)
entities = processor.load_dataset(name)
```

---

## 2. Deprecated Code Identified

### 2.1 Files to DELETE (marked deprecated, unused)
```
protos/src/protos/processing/structure/structure_processor_deprecated.py
protos/src/protos/processing/grn/grn_processor_deprecated.py
protos/src/protos/processing/ligand/ligand_processor_deprecated.py
protos/src/protos/processing/structure/to_be_updated/  (entire directory)
```

### 2.2 Deprecated Methods (keep with warnings)
```python
# StructureProcessor - lines 2046-2055
def load_structure(self, identifier):  # → use load_entity()
def save_structure(self, name, data):   # → use save_entity()
```

### 2.3 Analysis Code Using Old Pattern (CRITICAL FIX)
```
protos/src/protos/analysis/structure_ligand_analysis.py
  - Line 133: processor.data[processor.data['pdb_id'] == pdb_id]
  - Line 169: processor.data[processor.data['pdb_id'] == pdb_id]
  - Line 249: processor.data[processor.data['pdb_id'] == pdb_id]
```

---

## 3. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP TOOLS LAYER                          │
│  (Thin wrappers - no business logic, no path manipulation)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PROCESSORS LAYER                           │
│  StructureProcessor │ SequenceProcessor │ LigandProcessor │ ... │
│                                                                 │
│  Interface:                                                     │
│    • load_entity(name) → data                                   │
│    • save_entity(name, data, metadata)                          │
│    • list_entities() → [names]                                  │
│    • create_dataset() / load_dataset()                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       ANALYSIS LAYER                            │
│  structure_ligand_analysis │ alignment_engine │ grn_assign │ ...│
│                                                                 │
│  Pattern: Receive processor, call processor.load_entity()       │
│  ❌ OLD: processor.data[...]  ← MUST ELIMINATE                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       LOADERS LAYER                             │
│  StructureLoader │ SequenceLoader │ LigandLoader │ ChEMBLLoader │
│                                                                 │
│  Pattern: Download/parse external → processor.save_entity()     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     IO CORE LAYER                               │
│  ProtosPaths │ EntityRegistry │ DatasetManager │ BaseProcessor  │
│                                                                 │
│  Single source of truth for paths, entities, datasets           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FILESYSTEM / DATA                            │
│  data/structure/  data/sequence/  data/grn/  data/ligand/  ...  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Anti-Patterns to Eliminate

### 4.1 Direct `.data` Access
```python
# ❌ OLD (breaks with modern processors)
structure_data = processor.data[processor.data['pdb_id'] == pdb_id]

# ✅ NEW (works with all processors)
structure_data = processor.load_entity(pdb_id)
if structure_data is not None:
    structure_data = structure_data.reset_index()
```

### 4.2 Direct Path Construction
```python
# ❌ OLD
path = Path(self.data_root) / "structure" / f"{name}.pkl"

# ✅ NEW
path = self.paths.get_entity_path("structure", name)
```

### 4.3 Monolithic DataFrame Storage
```python
# ❌ OLD
self.data = pd.concat([self.data, new_entity_df])  # Growing monolithic frame

# ✅ NEW
self.frames[entity_name] = new_entity_df  # Per-entity storage
# Or for tables:
self._append_row(entity_name, data)
```

---

## 5. Loader Status

| Loader | Status | Source |
|--------|--------|--------|
| StructureLoader | ✅ Modern | RCSB, AlphaFold, local |
| SequenceLoader | ✅ Modern | UniProt, FASTA |
| LigandLoader | ✅ Modern | ChEMBL, SMILES |
| CCDLoader | ✅ Modern | CCD |
| GPCRdbLoader | ✅ Modern | GPCRdb API |
| ChEMBLLoader | ✅ Modern | ChEMBL API |

All loaders follow pattern:
```python
loader = StructureLoader(processor=structure_processor)
entity_name = loader.download_and_register(identifier, name, source)
```

---

## 6. Test Coverage Gaps

### Workflows That May Fail
1. `test_ligand_workflow.py` - Uses `extract_ligands_from_structure()` which calls `.data`
2. Any workflow calling `structure_ligand_analysis.py` functions directly

### Workflows That Work
1. `sequence_workflow_via_tools.py` - Pure sequence operations
2. `sequence_alignment_via_tools.py` - MMseqs2 alignment
3. `grn_workflow_via_tools.py` - GRN annotation

---

## 7. Recommended Actions

### Phase 1: Critical Fixes (Immediate)
1. Fix `structure_ligand_analysis.py` - Replace all `.data` access with `load_entity()`
2. Run `test_ligand_workflow.py` to verify

### Phase 2: Cleanup (Short-term)
1. Delete `*_deprecated.py` files
2. Delete `to_be_updated/` directory
3. Audit all analysis modules for `.data` access

### Phase 3: Documentation (Medium-term)
1. Update CLAUDE.md with modern patterns
2. Add migration guide for any external code using old patterns
3. Add type hints to all processor interfaces

---

## 8. Files Changed in This Session

| File | Change |
|------|--------|
| `protos/src/protos/analysis/structure_ligand_analysis.py` | Added `_load_structure_frame()` helper, partial fix |
| `mcp_server/tools/analysis/sequence.py` | Fixed `max_chars` validation |
| `mcp_server/tools/loader/input.py` | New `input_scan`/`input_register` tools |
| `workflows/test_ligand_workflow.py` | Bypass MCP payload limit via direct processor |

---

## 9. Next Steps

See `PROTOS_REFACTORING_PLAN.md` for detailed step-by-step refactoring plan.
