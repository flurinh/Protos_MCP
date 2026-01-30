#!/usr/bin/env python3
"""
Input Molecule Workflow - Complete Ligand Analysis, Structure Merge, and Boltz Submission

This workflow demonstrates a full structural biology pipeline:

1. MOLECULE IMPORT & ANALYSIS:
   - Load a molecule from an SDF file
   - Register it as structure and molecule entities
   - Calculate molecular properties (MW, LogP, TPSA, etc.)
   - Assess drug-likeness (Lipinski's Rule of 5)
   - Search for similar ligands

2. STRUCTURE PREPARATION:
   - Download a target protein structure from RCSB
   - Remove existing ligands (keeping waters and ions)
   - Merge our ligand into the target structure
   - Export as proper Protos entities with relationships

3. SMILES MODIFICATION & BOLTZ SUBMISSION:
   - Modify the ligand SMILES (C→N in ring)
   - Extract protein sequence from structure
   - Collect ions and waters from structure
   - Generate Boltz configuration with:
     * Protein sequence
     * Modified ligand (SMILES)
     * Crystallographic waters (CCD: HOH)
     * Ions (CCD codes)

Usage:
    python workflows/input_molecule_workflow.py
    python workflows/input_molecule_workflow.py --file path/to/molecule.sdf
    python workflows/input_molecule_workflow.py --target 1xlx
"""

from __future__ import annotations

import asyncio
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "protos" / "src"
for path in (REPO_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import protos

from mcp.server.fastmcp import Context

from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server

# Use shared workflow utilities
from workflow_utils import normalize_response, extract_summary


# Default input file (Uni-Dock docking result)
DEFAULT_INPUT_FILE = "lig_003071_conf0_rank004.sdf"
DATASET_NAME = "input_molecule_analysis"

# Target protein for docking
DEFAULT_TARGET_STRUCTURE = "1xlx"  # Adenosine A2A receptor with antagonist
DOCKED_COMPLEX_NAME = "docked_complex"


async def run_workflow(
    input_file: Optional[str] = None,
    target_structure: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the input molecule loading, analysis, and docking workflow.

    Args:
        input_file: Path to SDF file (defaults to data/input/*.sdf)
        target_structure: PDB ID for target protein (defaults to 1xlx)

    Returns:
        Workflow result dictionary
    """
    target_pdb = (target_structure or DEFAULT_TARGET_STRUCTURE).lower()
    data_root_path = (REPO_ROOT / "data").resolve()
    protos.set_data_path(str(data_root_path))

    # Resolve input file
    if input_file:
        sdf_path = Path(input_file)
        if not sdf_path.is_absolute():
            sdf_path = data_root_path / "input" / input_file
    else:
        sdf_path = data_root_path / "input" / DEFAULT_INPUT_FILE

    if not sdf_path.exists():
        raise FileNotFoundError(f"Input SDF file not found: {sdf_path}")

    print(f"Input file: {sdf_path}")

    server = create_server(
        "Protos Input Molecule Workflow",
        config=ServerConfig(data_root=data_root_path),
    )

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, *, raise_on_error: bool = False, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            payload = normalize_response(response)
            success = payload.get("success", True)
            if raise_on_error and not success:
                error_msg = payload.get("error") or payload.get("data", {}).get("error", "unknown error")
                raise RuntimeError(f"{tool} failed: {error_msg}")
            return payload

        # Initialize Protos data environment
        print("\n1. Initializing Protos data environment...")
        await call("config_get_data_root", raise_on_error=True)

        # Step 1: Import the SDF file
        print("\n2. Importing SDF file...")
        import_result = await call(
            "ligand_import_sdf",
            file_path=str(sdf_path),
            dataset_name=DATASET_NAME,
            chain_id="L",
            raise_on_error=True,
        )
        import_data = import_result.get("data", import_result)
        dataset_name = import_data.get("dataset_name", DATASET_NAME)
        molecule_dataset = import_data.get("molecule_dataset")
        entities = import_data.get("entities", [])

        print(f"   Dataset: {dataset_name}")
        print(f"   Molecule dataset: {molecule_dataset}")
        print(f"   Entities imported: {len(entities)}")

        if not entities:
            raise RuntimeError("No molecules were imported from the SDF file")

        # Step 2: Load the first entity to get its SMILES
        print("\n3. Loading molecule entity...")
        entity_name = entities[0]
        load_result = await call(
            "load_ligand_entity",
            ligand_id=entity_name,
            include_structure=False,
            raise_on_error=True,
        )
        load_data = load_result.get("data", load_result)
        smiles = load_data.get("smiles")
        metadata = load_data.get("metadata", {})

        print(f"   Entity: {entity_name}")
        print(f"   SMILES: {smiles}")
        if metadata:
            print(f"   Source: {metadata.get('source_file', 'unknown')}")

        # Step 3: Calculate molecular properties
        print("\n4. Calculating molecular properties...")
        properties_result = {}
        if smiles:
            props_response = await call(
                "ligand_calculate_molecular_properties",
                smiles=smiles,
            )
            if props_response.get("success", True):
                properties_result = props_response.get("data", {}).get("properties", {})
                drug_like = props_response.get("data", {}).get("drug_like", False)

                print(f"   Molecular Weight: {properties_result.get('mw', 'N/A'):.2f}")
                print(f"   LogP: {properties_result.get('logp', 'N/A'):.2f}")
                print(f"   TPSA: {properties_result.get('tpsa', 'N/A'):.2f}")
                print(f"   HBD: {properties_result.get('hbd', 'N/A')}")
                print(f"   HBA: {properties_result.get('hba', 'N/A')}")
                print(f"   Rotatable Bonds: {properties_result.get('rotatable_bonds', 'N/A')}")
                print(f"   Drug-like (Lipinski): {drug_like}")

        # Step 4: Check drug-likeness
        print("\n5. Assessing drug-likeness (Lipinski's Rule of 5)...")
        drug_like_result = await call(
            "filter_drug_like_ligands",
            entity_names=entities,
            strict=False,
        )
        drug_like_data = drug_like_result.get("data", drug_like_result)
        drug_like_count = drug_like_data.get("drug_like_count", 0)
        drug_like_entities = drug_like_data.get("drug_like", [])

        print(f"   Drug-like molecules: {drug_like_count}/{len(entities)}")

        # Step 5: Search for similar ligands (if we have SMILES)
        print("\n6. Searching for similar ligands...")
        similarity_result = {}
        if smiles:
            sim_response = await call(
                "search_similar_ligands",
                query_smiles=smiles,
                similarity_threshold=0.5,
                search_chembl=False,  # Set to True for external search
                max_results=10,
            )
            similarity_result = sim_response.get("data", {})
            num_similar = similarity_result.get("num_results", 0)
            similar_ligands = similarity_result.get("similar_ligands", [])
            # Handle case where single-element list was unwrapped to dict by convert_payload
            if isinstance(similar_ligands, dict):
                similar_ligands = [similar_ligands]

            print(f"   Similar ligands found: {num_similar}")
            if similar_ligands:
                for lig in similar_ligands[:3]:
                    print(f"     - {lig.get('entity', lig.get('chembl_id', 'unknown'))}: {lig.get('similarity', 0):.3f}")

        # Step 6: List all registered ligand entities
        print("\n7. Listing registered ligand entities...")
        list_result = await call(
            "list_ligand_entities",
            limit=10,
        )
        list_data = list_result.get("data", list_result)
        total_ligands = list_data.get("total", 0)

        print(f"   Total registered ligands: {total_ligands}")

        # ============================================================
        # DOCKING PREPARATION STEPS
        # ============================================================
        docking_result = {}

        # Step 7: Download target structure
        print(f"\n8. Downloading target structure ({target_pdb.upper()})...")
        receptor_resp = await call(
            "download_entity",
            entity_id=target_pdb.upper(),
            processor_type="structure",
            allow_cached=True,
        )
        receptor_data = receptor_resp.get("data", receptor_resp)
        receptor_name = receptor_data.get("context", {}).get("registered") or target_pdb.upper()
        print(f"   Downloaded: {receptor_name}")

        # Step 8: Extract ligands from target to identify what to remove
        print(f"\n9. Extracting ligands from {receptor_name}...")
        extract_result = await call(
            "extract_ligands_from_structure",
            pdb_id=receptor_name,
            exclude_common=True,
            min_atoms=5,
        )
        extract_data = extract_result.get("data", extract_result)
        target_ligands = extract_data.get("ligands", [])

        if target_ligands:
            print(f"   Found {len(target_ligands)} ligand(s):")
            for lig in target_ligands:
                print(f"     - {lig.get('res_name', 'UNK')} in chain {lig.get('chain_id', '?')} ({lig.get('num_atoms', 0)} atoms)")

            # Get ligand residue names to remove
            ligand_names_to_remove = list({lig.get("res_name", lig.get("res_name3l", "")) for lig in target_ligands})
            ligand_names_to_remove = [n for n in ligand_names_to_remove if n]  # Filter empty

            # Step 9: Remove ligand while keeping waters and ions
            print(f"\n10. Removing ligand(s) from receptor (keeping waters & ions)...")
            stripped_receptor_id = f"{receptor_name}_stripped"
            remove_result = await call(
                "structure_remove_specific_ligand",
                structure_id=receptor_name,
                ligand_residue_names=ligand_names_to_remove,
                keep_waters=True,
                keep_ions=True,
                new_id=stripped_receptor_id,
                save=True,
            )
            remove_data = remove_result.get("data", remove_result)
            print(f"   Original atoms: {remove_data.get('original_atoms', 0)}")
            print(f"   Removed ligand atoms: {remove_data.get('removed_ligands', {}).get('atom_count', 0)}")
            print(f"   Remaining atoms: {remove_data.get('remaining_atoms', 0)}")
            print(f"   Remaining HETATM (waters/ions): {remove_data.get('remaining_hetatm', 0)}")
        else:
            print("   No ligands found to remove")
            stripped_receptor_id = receptor_name
            ligand_names_to_remove = []

        # Step 10: Merge ligand into receptor structure
        print(f"\n11. Merging ligand into receptor structure...")
        complex_id = f"{stripped_receptor_id}_with_{entity_name}"

        merge_result = await call(
            "structure_merge",
            structure_ids=[stripped_receptor_id, entity_name],
            new_id=complex_id,
            chain_mapping={f"{entity_name}:L": "L"},  # Assign ligand to chain L
            save=True,
            record_relationships=True,
            relationship_metadata={
                "workflow": "input_molecule_workflow",
                "target_structure": target_pdb.upper(),
                "ligand_source": str(sdf_path.name),
            },
        )
        merge_data = merge_result.get("data", merge_result)
        print(f"   Merged structure ID: {complex_id}")
        print(f"   Total atoms: {merge_data.get('total_atoms', 'N/A')}")
        print(f"   Chains: {', '.join(merge_data.get('chains', []))}")
        print(f"   Entity path: {merge_data.get('entity_path', 'N/A')}")

        # Record relationships
        relationships = merge_data.get("relationships_recorded", [])
        if relationships:
            print(f"   Relationships recorded: {len(relationships)}")
            for rel in relationships:
                print(f"     - {rel.get('source')} -> {rel.get('target')} ({rel.get('type')})")

        # Step 11: Export merged complex as CIF (to Protos-managed location)
        print(f"\n12. Exporting merged complex as CIF...")
        complex_export = await call(
            "structure_export_entity",
            structure_id=complex_id,
            format="cif",
            overwrite=True,
        )
        complex_export_data = complex_export.get("data", {})
        complex_cif_path = complex_export_data.get("relative_path", complex_export_data.get("export_path"))
        print(f"   CIF exported: {complex_cif_path}")

        # Also export as PDB (to Protos-managed location)
        pdb_export = await call(
            "structure_export_entity",
            structure_id=complex_id,
            format="pdb",
            overwrite=True,
        )
        pdb_export_data = pdb_export.get("data", {})
        complex_pdb_path = pdb_export_data.get("relative_path", pdb_export_data.get("export_path"))
        print(f"   PDB exported: {complex_pdb_path}")

        docking_result = {
            "target_structure": target_pdb.upper(),
            "receptor_id": stripped_receptor_id,
            "removed_ligands": ligand_names_to_remove,
            "complex_id": complex_id,
            "entity_path": merge_data.get("entity_path"),
            "complex_cif": complex_cif_path,
            "complex_pdb": complex_pdb_path,
            "total_atoms": merge_data.get("total_atoms"),
            "chains": merge_data.get("chains", []),
            "relationships": relationships,
        }

        # ============================================================
        # SMILES MODIFICATION & BOLTZ SUBMISSION
        # ============================================================
        boltz_result = {}

        if smiles:
            # Step 13: Modify SMILES (C→N in ring)
            print(f"\n13. Modifying ligand SMILES (C→N in ring)...")
            modify_result = await call(
                "ligand_modify_smiles",
                smiles=smiles,
                old_element="C",
                new_element="N",
                in_ring_only=True,
                occurrence=1,
            )
            modify_data = modify_result.get("data", modify_result)

            if modify_data.get("modified_smiles"):
                modified_smiles = modify_data["modified_smiles"]
                print(f"   Original: {smiles}")
                print(f"   Modified: {modified_smiles}")
                print(f"   Formula:  {modify_data.get('original_formula')} → {modify_data.get('modified_formula')}")
                print(f"   MW:       {modify_data.get('original_mw')} → {modify_data.get('modified_mw')}")
            else:
                print(f"   Could not modify SMILES, using original")
                modified_smiles = smiles

            # Step 14: Extract protein sequence from structure
            print(f"\n14. Extracting protein sequence from {receptor_name}...")
            seq_result = await call(
                "extract_sequence_from_structure",
                pdb_id=receptor_name,
                chain_id="A",  # Main chain
            )
            seq_data = seq_result.get("data", seq_result)
            protein_sequence = seq_data.get("sequence", "")
            print(f"   Chain A sequence length: {len(protein_sequence)}")

            # Step 15: Get ions and waters from structure
            print(f"\n15. Extracting ions and waters from {receptor_name}...")

            # Extract water molecules
            waters_result = await call(
                "structure_extract_water_molecules",
                pdb_id=receptor_name,
                min_atoms=1,
            )
            waters_data = waters_result.get("data", waters_result)
            water_count = waters_data.get("water_count", 0)
            print(f"   Waters found: {water_count}")

            # Extract ligands (which will include ions)
            ions_result = await call(
                "extract_ligands_from_structure",
                pdb_id=receptor_name,
                exclude_common=False,  # Include ions
                min_atoms=1,
            )
            ions_data = ions_result.get("data", ions_result)
            all_hetero = ions_data.get("ligands", [])

            # Filter for common ions
            ion_names = {'NA', 'CL', 'K', 'CA', 'MG', 'ZN', 'FE', 'CU', 'MN'}
            ions_found = [lig for lig in all_hetero if lig.get("res_name", "").upper() in ion_names]
            print(f"   Ions found: {len(ions_found)}")
            for ion in ions_found[:5]:
                print(f"     - {ion.get('res_name')} chain {ion.get('chain_id')}")

            # Step 16: Prepare Boltz configuration
            print(f"\n16. Preparing Boltz configuration...")

            # Build extra_sequences for ions and waters
            extra_sequences = []

            # Add a few waters (limit to 5 for demo)
            waters_list = waters_data.get("waters", [])[:5]
            for i, water in enumerate(waters_list):
                extra_sequences.append({
                    "ligand": {
                        "id": [f"W{i+1}"],
                        "ccd": "HOH",
                    }
                })

            # Add ions
            for i, ion in enumerate(ions_found[:5]):
                ion_ccd = ion.get("res_name", "").upper()
                extra_sequences.append({
                    "ligand": {
                        "id": [f"I{i+1}"],
                        "ccd": ion_ccd,
                    }
                })

            # Prepare Boltz job
            boltz_config = {
                "ligand": {
                    "id": "LIG",
                    "smiles": modified_smiles,
                },
                "extra_sequences": extra_sequences,
                "properties": [
                    {"affinity": {"binder": "LIG"}}
                ],
            }

            # Register the sequence for Boltz
            register_result = await call(
                "sequence_register_records",
                records=[{"name": f"{receptor_name}_chain_A", "sequence": protein_sequence}],
                dataset_name=f"boltz_{receptor_name}",
                overwrite=True,
                materialize_entities=True,
            )

            # Prepare Boltz mutation job
            boltz_job_result = await call(
                "model_prepare_boltz_mutations",
                dataset_name=f"boltz_{receptor_name}",
                mutation_entries=[
                    {
                        "entity": f"{receptor_name}_chain_A",
                        "config": {
                            "output_name": f"{receptor_name}_with_modified_ligand",
                            **boltz_config,
                        },
                    }
                ],
                model_name="boltz2",
                base_config={
                    "recycling": 4,
                    "num_samples": 1,
                },
            )
            boltz_job_data = boltz_job_result.get("data", boltz_job_result)
            jobs = boltz_job_data.get("jobs", [])
            # Handle case where single-element list was unwrapped to dict by convert_payload
            if isinstance(jobs, dict):
                jobs = [jobs]

            if jobs:
                job = jobs[0]
                print(f"   Boltz config ID: {job.get('config_id', 'N/A')}")
                print(f"   Config path: {job.get('config_path', 'N/A')}")
                print(f"   FASTA path: {job.get('fasta_path', 'N/A')}")
                if job.get("command"):
                    print(f"   Command: {' '.join(job['command'][:5])}...")

            boltz_result = {
                "original_smiles": smiles,
                "modified_smiles": modified_smiles,
                "modification": modify_data.get("modification"),
                "protein_sequence_length": len(protein_sequence),
                "waters_included": len(waters_list),
                "ions_included": [ion.get("res_name") for ion in ions_found[:5]],
                "boltz_jobs": jobs,
            }

        # Build final result
        result = {
            "input_file": str(sdf_path),
            "dataset_name": dataset_name,
            "molecule_dataset": molecule_dataset,
            "entities": entities,
            "primary_entity": {
                "name": entity_name,
                "smiles": smiles,
                "metadata": metadata,
            },
            "properties": properties_result,
            "drug_likeness": {
                "total": len(entities),
                "drug_like": drug_like_count,
                "entities": drug_like_entities,
            },
            "similarity_search": extract_summary({"data": similarity_result}),
            "total_registered_ligands": total_ligands,
            "docking": docking_result,
            "boltz": boltz_result,
        }

        return result


def summarize(result: Dict[str, Any]) -> None:
    """Print a summary of the workflow results."""
    print("\n" + "=" * 60)
    print("INPUT MOLECULE WORKFLOW SUMMARY")
    print("=" * 60)

    print(f"\nInput File: {result.get('input_file')}")
    print(f"Dataset Created: {result.get('dataset_name')}")
    print(f"Molecule Dataset: {result.get('molecule_dataset')}")
    print(f"Entities Imported: {len(result.get('entities', []))}")

    primary = result.get("primary_entity", {})
    if primary:
        print(f"\nPrimary Molecule:")
        print(f"  Name: {primary.get('name')}")
        print(f"  SMILES: {primary.get('smiles')}")

    props = result.get("properties", {})
    if props:
        print(f"\nMolecular Properties:")
        print(f"  MW: {props.get('mw', 'N/A')}")
        print(f"  LogP: {props.get('logp', 'N/A')}")
        print(f"  TPSA: {props.get('tpsa', 'N/A')}")
        print(f"  HBD/HBA: {props.get('hbd', 'N/A')}/{props.get('hba', 'N/A')}")
        print(f"  Rotatable Bonds: {props.get('rotatable_bonds', 'N/A')}")
        print(f"  Lipinski Pass: {props.get('lipinski_pass', 'N/A')}")

    drug = result.get("drug_likeness", {})
    if drug:
        print(f"\nDrug-likeness Assessment:")
        print(f"  Drug-like: {drug.get('drug_like', 0)}/{drug.get('total', 0)}")

    sim = result.get("similarity_search", {})
    if sim:
        print(f"\nSimilarity Search:")
        print(f"  Results: {sim.get('num_results', sim.get('count', 0))}")

    print(f"\nTotal Registered Ligands: {result.get('total_registered_ligands', 0)}")

    # Complex structure information
    docking = result.get("docking", {})
    if docking:
        print(f"\nStructure Preparation:")
        print(f"  Target Structure: {docking.get('target_structure', 'N/A')}")
        print(f"  Receptor ID: {docking.get('receptor_id', 'N/A')}")
        print(f"  Removed Ligands: {', '.join(docking.get('removed_ligands', [])) or 'None'}")

        print(f"\nMerged Complex (Protos Entity):")
        print(f"  Complex ID: {docking.get('complex_id', 'N/A')}")
        print(f"  Entity Path: {docking.get('entity_path', 'N/A')}")
        print(f"  Total Atoms: {docking.get('total_atoms', 'N/A')}")
        print(f"  Chains: {', '.join(docking.get('chains', []))}")

        print(f"\nExported Files:")
        print(f"  CIF: {docking.get('complex_cif', 'N/A')}")
        print(f"  PDB: {docking.get('complex_pdb', 'N/A')}")

        relationships = docking.get("relationships", [])
        if relationships:
            print(f"\nEntity Relationships:")
            for rel in relationships:
                print(f"  {rel.get('source')} --[{rel.get('type')}]--> {rel.get('target')}")

    # Boltz submission information
    boltz = result.get("boltz", {})
    if boltz:
        print(f"\nSMILES Modification:")
        print(f"  Original: {boltz.get('original_smiles', 'N/A')[:50]}...")
        print(f"  Modified: {boltz.get('modified_smiles', 'N/A')[:50]}...")
        mod = boltz.get("modification", {})
        if mod:
            print(f"  Change: {mod.get('old_element')} → {mod.get('new_element')} at atom {mod.get('atom_index')}")

        print(f"\nBoltz Submission:")
        print(f"  Protein sequence length: {boltz.get('protein_sequence_length', 'N/A')}")
        print(f"  Waters included: {boltz.get('waters_included', 0)}")
        print(f"  Ions included: {', '.join(boltz.get('ions_included', [])) or 'None'}")

        jobs = boltz.get("boltz_jobs", [])
        if jobs:
            job = jobs[0]
            print(f"\n  Boltz Job:")
            print(f"    Config ID: {job.get('config_id', 'N/A')}")
            print(f"    Config: {job.get('config_path', 'N/A')}")
            print(f"    FASTA: {job.get('fasta_path', 'N/A')}")

    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load and analyze molecules from SDF files, then prepare docking"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to SDF file (default: data/input/lig_003071_conf0_rank004.sdf)"
    )
    parser.add_argument(
        "--target", "-t",
        type=str,
        default=None,
        help="PDB ID of target structure for docking (default: 1xlx)"
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(run_workflow(args.file, args.target))
        summarize(result)
    except Exception as e:
        print(f"\nWorkflow failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
