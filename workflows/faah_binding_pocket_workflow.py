#!/usr/bin/env python3
"""
FAAH binding pocket analysis workflow using MCP tools.

This workflow demonstrates:
- Downloading multiple structures for a protein target
- Analyzing binding pockets with save_to_table for memory efficiency
- Comparing binding sites across structures
- Using property tables to accumulate results

FAAH (Fatty Acid Amide Hydrolase) is a drug target with many crystal structures.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import Context
from mcp_server.config import ServerConfig
from mcp_server.runtime import create_server

# FAAH structures with known inhibitors
FAAH_STRUCTURES = [
    "1MT5",  # Human FAAH with MAP inhibitor
    "2VYA",  # Human FAAH with JP104
    "3LJ6",  # Human FAAH with URB597
    "3PPM",  # Humanized rat FAAH with carprofen
]

DATASET_NAME = "faah_structures"
BINDING_POCKET_TABLE = "faah_binding_pockets"
BINDING_SITE_TABLE = "faah_binding_sites"
SITE_COMPARISON_TABLE = "faah_site_comparison"
CUTOFF = 6.0  # Distance cutoff for binding site


def _convert_payload(value: Any) -> Any:
    """Extract JSON from MCP response objects."""
    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str) and text_attr:
        try:
            return json.loads(text_attr)
        except Exception:
            return text_attr

    if isinstance(value, list):
        converted = [_convert_payload(item) for item in value]
        if len(converted) == 1 and isinstance(converted[0], dict):
            return converted[0]
        return converted

    if isinstance(value, tuple):
        return tuple(_convert_payload(item) for item in value)

    if isinstance(value, dict):
        return {key: _convert_payload(val) for key, val in value.items()}

    return value


def _normalize_response(raw: Any) -> Dict[str, Any]:
    """Normalize MCP tool response to consistent dict format."""
    if isinstance(raw, tuple) and len(raw) == 2:
        messages, meta = raw
    else:
        messages = []
        meta = raw

    text_messages: List[str] = []
    for msg in messages or []:
        text = getattr(msg, "text", None)
        if text:
            text_messages.append(text)

    meta_converted = _convert_payload(meta)

    if isinstance(meta_converted, dict):
        candidate = meta_converted.get("result", meta_converted)
        if isinstance(candidate, dict):
            payload = candidate
        else:
            payload = {"result": candidate}
    else:
        payload = {"result": meta_converted}

    if text_messages:
        payload = {**payload, "messages": text_messages}
    return payload


async def run_workflow() -> Dict[str, Any]:
    """Run the FAAH binding pocket analysis workflow."""
    data_root_path = (REPO_ROOT / "data").resolve()
    server = create_server(
        "FAAH Binding Pocket Workflow",
        config=ServerConfig(data_root=data_root_path),
    )

    async with server.settings.lifespan(server):
        ctx = Context(fastmcp=server)

        async def call(tool: str, **kwargs: Any) -> Dict[str, Any]:
            kwargs.setdefault("ctx", ctx)
            response = await server.call_tool(tool, kwargs)
            return _normalize_response(response)

        results: Dict[str, Any] = {
            "structures": [],
            "ligands": {},
            "binding_pockets": {},
            "site_comparisons": [],
        }

        # Step 1: Download FAAH structures
        print(f"Downloading {len(FAAH_STRUCTURES)} FAAH structures...")
        download_resp = await call(
            "download_entities",
            identifiers=FAAH_STRUCTURES,
            processor_type="structure",
            dataset_name=DATASET_NAME,
            create_dataset=True,
            overwrite=True,
        )
        download_data = download_resp.get("data", download_resp)
        downloaded = download_data.get("downloaded", [])
        failed = download_data.get("failed", [])
        print(f"  Downloaded: {downloaded}")
        if failed:
            print(f"  Failed: {failed}")
        results["structures"] = downloaded

        if not downloaded:
            print("No structures downloaded. Exiting.")
            return results

        # Step 2: Extract ligands from each structure
        print("\nExtracting ligands from structures...")
        structure_ligand_pairs: List[Dict[str, str]] = []

        for pdb_id in downloaded:
            ligand_resp = await call(
                "extract_ligands_from_structure",
                pdb_id=pdb_id,
            )
            ligand_data = ligand_resp.get("data", ligand_resp)
            ligands = ligand_data.get("ligands", [])

            # Filter out common solvents/ions
            excluded = {"HOH", "WAT", "SO4", "PO4", "GOL", "PEG", "EDO", "ACT", "CL", "NA"}
            valid_ligands = [
                lig for lig in ligands
                if lig.get("res_name", "").upper() not in excluded
                and lig.get("num_atoms", 0) > 5
            ]

            results["ligands"][pdb_id] = valid_ligands
            print(f"  {pdb_id}: {len(valid_ligands)} ligands")

            # Take the largest ligand for analysis
            if valid_ligands:
                best = max(valid_ligands, key=lambda x: x.get("num_atoms", 0))
                structure_ligand_pairs.append({
                    "pdb_id": pdb_id,
                    "ligand_name": best["res_name"],
                    "chain_id": best.get("chain_id"),
                })
                print(f"    Selected: {best['res_name']} ({best.get('num_atoms', 0)} atoms)")

        # Step 3: Analyze binding pockets with save_to_table
        print(f"\nAnalyzing binding pockets (saving to {BINDING_POCKET_TABLE})...")
        for pair in structure_ligand_pairs:
            pocket_resp = await call(
                "structure_analyze_binding_pocket",
                pdb_id=pair["pdb_id"],
                ligand_name=pair["ligand_name"],
                chain_id=pair.get("chain_id"),
                cutoff=CUTOFF,
                save_to_table=BINDING_POCKET_TABLE,
            )
            pocket_data = pocket_resp.get("data", pocket_resp)

            if pocket_data.get("saved"):
                results["binding_pockets"][pair["pdb_id"]] = {
                    "ligand": pair["ligand_name"],
                    "rows_saved": pocket_data.get("rows", 0),
                    "key_residues": pocket_data.get("key_residues", []),
                    "pocket_properties": pocket_data.get("pocket_properties", {}),
                }
                print(f"  {pair['pdb_id']}: {pocket_data.get('rows', 0)} residues saved")
                print(f"    Key residues: {pocket_data.get('key_residues', [])[:5]}")
            else:
                print(f"  {pair['pdb_id']}: Error - {pocket_data.get('error', 'unknown')}")

        # Step 4: Compare binding sites across structures
        if len(structure_ligand_pairs) >= 2:
            print(f"\nComparing binding sites (saving to {SITE_COMPARISON_TABLE})...")
            comparison_resp = await call(
                "structure_compare_ligand_binding_sites",
                structures=structure_ligand_pairs,
                cutoff=CUTOFF,
                similarity_threshold=0.3,
                save_to_table=SITE_COMPARISON_TABLE,
            )
            comparison_data = comparison_resp.get("data", comparison_resp)

            if comparison_data.get("saved"):
                results["site_comparisons"] = {
                    "rows_saved": comparison_data.get("rows", 0),
                    "conserved_residues": comparison_data.get("conserved_residues", []),
                    "conservation_ratio": comparison_data.get("conservation_ratio", 0),
                }
                print(f"  Comparisons saved: {comparison_data.get('rows', 0)}")
                print(f"  Conserved residues: {comparison_data.get('conserved_residues', [])[:10]}")
                print(f"  Conservation ratio: {comparison_data.get('conservation_ratio', 0):.2%}")
            else:
                # Full response mode
                results["site_comparisons"] = {
                    "conserved_residues": comparison_data.get("conserved_residues", []),
                    "conservation_ratio": comparison_data.get("conservation_ratio", 0),
                    "num_comparisons": len(comparison_data.get("pairwise_comparisons", [])),
                }

        # Step 5: Load property table to verify
        print(f"\nVerifying property table {BINDING_POCKET_TABLE}...")
        table_resp = await call(
            "load_property_table",
            table_name=BINDING_POCKET_TABLE,
        )
        table_data = table_resp.get("data", table_resp)
        print(f"  Total rows: {table_data.get('row_count', 0)}")
        print(f"  Columns: {table_data.get('columns', [])}")

        return results


def summarize(result: Dict[str, Any]) -> None:
    """Print a summary of the workflow results."""
    print("\n" + "=" * 50)
    print("FAAH Binding Pocket Analysis Summary")
    print("=" * 50)

    structures = result.get("structures", [])
    print(f"\nStructures analyzed: {len(structures)}")
    for pdb_id in structures:
        ligands = result.get("ligands", {}).get(pdb_id, [])
        pocket = result.get("binding_pockets", {}).get(pdb_id, {})
        print(f"  {pdb_id}:")
        print(f"    Ligands found: {len(ligands)}")
        if pocket:
            print(f"    Selected ligand: {pocket.get('ligand')}")
            print(f"    Binding residues: {pocket.get('rows_saved', 0)}")
            print(f"    Key residues: {pocket.get('key_residues', [])[:3]}")
            props = pocket.get("pocket_properties", {})
            if props:
                print(f"    Pocket: {props.get('hydrophobic_residues', 0)} hydrophobic, "
                      f"{props.get('aromatic_residues', 0)} aromatic, "
                      f"{props.get('charged_residues', 0)} charged")

    comparisons = result.get("site_comparisons", {})
    if comparisons:
        print(f"\nBinding site conservation:")
        print(f"  Conservation ratio: {comparisons.get('conservation_ratio', 0):.1%}")
        conserved = comparisons.get("conserved_residues", [])
        if conserved:
            print(f"  Conserved residues ({len(conserved)}): {conserved[:10]}")


def main() -> None:
    result = asyncio.run(run_workflow())
    summarize(result)


if __name__ == "__main__":
    main()
