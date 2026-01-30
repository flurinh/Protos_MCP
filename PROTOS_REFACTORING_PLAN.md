# Protos Refactoring Plan
**Date:** 2025-12-10
**Goal:** Complete migration to modern architecture, eliminate deprecated code

---

## Overview

We will refactor in **small, testable steps**, validating each change with real workflow tests before proceeding.

---

## Phase 1: Fix Critical Analysis Module (structure_ligand_analysis.py)

### Step 1.1: Fix `extract_all_ligands()`
**File:** `protos/src/protos/analysis/structure_ligand_analysis.py`
**Issue:** Uses `processor.data[...]` directly
**Fix:** Use existing `_load_structure_frame()` helper

```python
# BEFORE (line ~75)
structure_data = cif_processor.data[cif_processor.data['pdb_id'] == pdb_id].copy()

# AFTER
structure_data = _load_structure_frame(cif_processor, pdb_id)
```

**Test:** `python workflows/test_ligand_workflow.py`

### Step 1.2: Fix `get_ligand_by_id()`
**Issue:** Same `.data` access pattern
**Fix:** Use helper

### Step 1.3: Fix `analyze_ligand_binding()`
**Issue:** Same `.data` access pattern
**Fix:** Use helper

### Step 1.4: Fix any remaining `.data` accesses
**Command to find:** `grep -n "\.data\[" protos/src/protos/analysis/`

**Validation Workflow:**
```bash
conda run -n protos python workflows/test_ligand_workflow.py
```

---

## Phase 2: Audit All Analysis Modules

### Step 2.1: Search for `.data` access patterns
```bash
grep -rn "processor\.data\|cif_processor\.data\|\.data\[" protos/src/protos/analysis/
```

### Step 2.2: Fix each occurrence
For each file found:
1. Identify the function
2. Determine if it receives a processor
3. Replace `.data` access with `processor.load_entity()` or helper

### Expected Files to Check:
- `analysis/structure/` - alignment, comparison, geometry
- `analysis/sequence/` - alignment utilities
- `analysis/grn/` - GRN assignment

**Validation Workflows:**
```bash
conda run -n protos python workflows/structure_alignment_via_tools.py
conda run -n protos python workflows/grn_workflow_via_tools.py
conda run -n protos python workflows/sequence_alignment_via_tools.py
```

---

## Phase 3: Delete Deprecated Files

### Step 3.1: Archive deprecated processors
```bash
# Create archive directory
mkdir -p protos/src/protos/archive/deprecated_2024

# Move deprecated files
mv protos/src/protos/processing/structure/structure_processor_deprecated.py \
   protos/src/protos/archive/deprecated_2024/

mv protos/src/protos/processing/grn/grn_processor_deprecated.py \
   protos/src/protos/archive/deprecated_2024/

mv protos/src/protos/processing/ligand/ligand_processor_deprecated.py \
   protos/src/protos/archive/deprecated_2024/
```

### Step 3.2: Delete to_be_updated directory
```bash
rm -rf protos/src/protos/processing/structure/to_be_updated/
```

### Step 3.3: Clean up imports
Search for any imports of deprecated modules and remove them.

**Validation:**
```bash
conda run -n protos python -c "import protos; print('Import OK')"
```

---

## Phase 4: Update MCP Tools (if needed)

### Step 4.1: Verify all MCP tools use processors correctly
```bash
grep -rn "\.data\[" mcp_server/tools/
```

### Step 4.2: Ensure payload limits don't break workflows
For large data operations (structures), consider:
- `output_format="summary"` for LLM-facing tools
- Direct processor access for programmatic workflows

**Validation:**
```bash
conda run -n protos python workflows/structure_grn_annotation_via_tools.py
```

---

## Phase 5: Comprehensive Testing

### Run All Workflows
```bash
# Sequence workflows
conda run -n protos python workflows/sequence_workflow_via_tools.py
conda run -n protos python workflows/sequence_alignment_via_tools.py

# GRN workflows
conda run -n protos python workflows/grn_workflow_via_tools.py

# Structure workflows
conda run -n protos python workflows/structure_alignment_via_tools.py
conda run -n protos python workflows/structure_grn_annotation_via_tools.py
conda run -n protos python workflows/structure_water_network_via_tools.py

# Ligand workflows
conda run -n protos python workflows/test_ligand_workflow.py

# Property workflows
conda run -n protos python workflows/property_workflow_via_tools.py

# Model workflows (if applicable)
conda run -n protos python workflows/model_lambda_via_tools.py
```

---

## Phase 6: Documentation Update

### Step 6.1: Update CLAUDE.md
- Remove references to deprecated patterns
- Add modern pattern examples
- Update processor-specific sections

### Step 6.2: Add Deprecation Notes
For any code that still uses old patterns for backward compatibility, add clear warnings:

```python
import warnings

def load_structure(self, identifier):
    """DEPRECATED: Use load_entity() instead."""
    warnings.warn(
        "load_structure() is deprecated, use load_entity()",
        DeprecationWarning,
        stacklevel=2
    )
    return self.load_entity(identifier)
```

---

## Execution Checklist

| Step | Description | Status | Test |
|------|-------------|--------|------|
| 1.1 | Fix `extract_all_ligands()` | ⬜ | `test_ligand_workflow.py` |
| 1.2 | Fix `get_ligand_by_id()` | ⬜ | `test_ligand_workflow.py` |
| 1.3 | Fix `analyze_ligand_binding()` | ⬜ | `test_ligand_workflow.py` |
| 1.4 | Audit remaining `.data` in file | ⬜ | grep check |
| 2.1 | Search all analysis modules | ⬜ | grep results |
| 2.2 | Fix each occurrence | ⬜ | workflow tests |
| 3.1 | Archive deprecated processors | ⬜ | import test |
| 3.2 | Delete to_be_updated | ⬜ | import test |
| 3.3 | Clean imports | ⬜ | import test |
| 4.1 | Verify MCP tools | ⬜ | grep check |
| 4.2 | Fix payload issues | ⬜ | workflow tests |
| 5.0 | Run all workflows | ⬜ | all pass |
| 6.1 | Update CLAUDE.md | ⬜ | review |
| 6.2 | Add deprecation warnings | ⬜ | grep check |

---

## Risk Mitigation

1. **Backup before deleting:** Archive instead of delete
2. **Test after each step:** Don't batch changes
3. **Keep deprecated methods:** Add warnings but don't remove yet
4. **Document breaking changes:** For any external users

---

## Success Criteria

1. All workflows pass without `.data` access errors
2. No grep hits for `processor.data[` in analysis modules
3. Deprecated files archived/deleted
4. CLAUDE.md updated with modern patterns only
5. Import test passes: `python -c "import protos"`

---

## Ready to Start?

Begin with **Step 1.1** - fixing `extract_all_ligands()` in `structure_ligand_analysis.py`.
