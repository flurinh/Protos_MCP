"""
Ligand analysis tools leveraging Protos' MoleculeProcessor.

These tools provide comprehensive ligand analysis capabilities including
molecular property calculation, similarity search, drug-likeness filtering,
ChEMBL integration, and structure-ligand analysis.
"""

from typing import Dict, List, Optional, Any, Tuple, Sequence
import json
import logging

import pandas as pd

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, EntityNotFoundError

from protos.io.ingest.ligand_loader import LigandLoader
from protos.io.ingest.chembl_loader import (
    query_protein_ligands,
    search_similar_compounds_chembl,
    get_compound_by_chembl_id,
)
from protos.analysis.structure_ligand_analysis import (
    calculate_ligand_interactions,
)

logger = logging.getLogger(__name__)


class LigandAnalysisTools(BaseTool):
    """Tools for ligand analysis and processing."""
    
    def register(self, server):
        """Register ligand analysis tools with the server."""
        
        @server.tool()
        def ligand_calculate_molecular_properties(ctx, smiles: str) -> Dict:
            """
            Calculate molecular properties for a SMILES string.
            
            Uses RDKit to calculate properties including:
            - Molecular weight
            - LogP (lipophilicity)
            - HBA/HBD (hydrogen bond acceptors/donors)
            - TPSA (topological polar surface area)
            - Rotatable bonds
            - Lipinski rule of 5 compliance
            
            Args:
                smiles: SMILES string representing the molecule
                
            Returns:
                Dictionary with molecular properties
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"smiles": smiles}, 
                    ["smiles"]
                ):
                    return error
                
                # Get ligand processor
                processor = self.get_processor("molecule")
                
                # Calculate properties
                properties = processor.calculate_properties(smiles)
                
                if properties is None:
                    return self.format_error(
                        f"Failed to calculate properties for SMILES: {smiles}",
                        "Check if SMILES is valid and RDKit is installed"
                    )
                
                return self.format_success({
                    "smiles": smiles,
                    "properties": properties,
                    "drug_like": properties.get('lipinski_pass', False)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def search_similar_ligands(ctx, query_smiles: str,
                                  similarity_threshold: float = 0.7,
                                  dataset: Optional[str] = None,
                                  search_chembl: bool = False,
                                  max_results: int = 100) -> Dict:
            """
            Search for similar ligands using Tanimoto similarity.

            Args:
                query_smiles: Query SMILES string
                similarity_threshold: Minimum similarity score (0-1)
                dataset: Optional dataset to search within (if None, searches all registered ligands)
                search_chembl: Also search ChEMBL database for similar compounds
                max_results: Maximum number of results to return

            Returns:
                Dictionary with similar ligands and their similarity scores
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"query_smiles": query_smiles},
                    ["query_smiles"]
                ):
                    return error

                if not 0 <= similarity_threshold <= 1:
                    return self.format_error(
                        "Invalid similarity threshold",
                        "Threshold must be between 0 and 1"
                    )

                similar_ligands = []

                # Try RDKit for local similarity search
                try:
                    from rdkit import Chem
                    from rdkit.Chem import AllChem, DataStructs
                    has_rdkit = True
                except ImportError:
                    has_rdkit = False

                if has_rdkit:
                    # Generate query fingerprint
                    query_mol = Chem.MolFromSmiles(query_smiles)
                    if query_mol is None:
                        return self.format_error(
                            "Invalid query SMILES",
                            "Could not parse the provided SMILES string"
                        )

                    query_fp = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, nBits=2048)

                    # Get ligand processor to search local entities
                    processor = self.get_processor("molecule")
                    entities = processor.list_ligands() if hasattr(processor, 'list_ligands') else []

                    # If dataset specified, filter to that dataset
                    if dataset:
                        manager = getattr(processor, "dataset_manager", None)
                        if manager:
                            try:
                                ds = manager.load_dataset(dataset)
                                if hasattr(ds, 'content') and ds.content:
                                    entities = ds.content
                            except Exception:
                                pass

                    # Calculate Tanimoto similarity for each ligand
                    for entity_name in entities:
                        try:
                            entity_data = processor.load_entity(entity_name)
                            if entity_data and 'smiles' in entity_data:
                                target_smiles = entity_data['smiles']
                                target_mol = Chem.MolFromSmiles(target_smiles)

                                if target_mol:
                                    target_fp = AllChem.GetMorganFingerprintAsBitVect(target_mol, 2, nBits=2048)
                                    similarity = DataStructs.TanimotoSimilarity(query_fp, target_fp)

                                    if similarity >= similarity_threshold:
                                        similar_ligands.append({
                                            "entity": entity_name,
                                            "smiles": target_smiles,
                                            "similarity": round(similarity, 3),
                                            "source": "local"
                                        })
                        except Exception:
                            continue

                # Search ChEMBL if requested
                if search_chembl:
                    try:
                        chembl_results = search_similar_compounds_chembl(
                            query_smiles,
                            similarity=similarity_threshold,
                            limit=max_results
                        )
                        for result in chembl_results:
                            similar_ligands.append({
                                "chembl_id": result.get('chembl_id', ''),
                                "smiles": result.get('smiles', ''),
                                "similarity": round(result.get('similarity', 0), 3),
                                "source": "chembl"
                            })
                    except Exception as e:
                        logger.warning(f"ChEMBL search failed: {e}")

                # Sort by similarity (descending) and limit results
                similar_ligands.sort(key=lambda x: x['similarity'], reverse=True)

                # In LLM-safe mode, limit to 20 results
                safe_max = 20 if self.llm_safe_mode else max_results
                total_found = len(similar_ligands)
                if len(similar_ligands) > safe_max:
                    similar_ligands = similar_ligands[:safe_max]

                return self.format_success({
                    "query_smiles": query_smiles,
                    "similarity_threshold": similarity_threshold,
                    "dataset": dataset,
                    "search_chembl": search_chembl,
                    "rdkit_available": has_rdkit,
                    "total_found": total_found,
                    "num_results": len(similar_ligands),
                    "similar_ligands": similar_ligands,
                    "truncated": total_found > len(similar_ligands),
                })

            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def filter_drug_like_ligands(ctx, entity_names: List[str],
                                    strict: bool = False) -> Dict:
            """
            Filter ligands by drug-like properties (Lipinski's rule of 5).
            
            Args:
                entity_names: List of ligand entity names or SMILES
                strict: Apply stricter criteria (Veber's rules)
                
            Returns:
                Dictionary with drug-like and non-drug-like ligands
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity_names": entity_names}, 
                    ["entity_names"]
                ):
                    return error
                
                if not entity_names:
                    return self.format_error(
                        "No entities provided",
                        "Provide at least one ligand entity"
                    )
                
                # Get ligand processor
                processor = self.get_processor("molecule")
                
                # Filter drug-like ligands
                drug_like = processor.filter_drug_like(entity_names, strict=strict)
                non_drug_like = [e for e in entity_names if e not in drug_like]
                
                return self.format_success({
                    "total_ligands": len(entity_names),
                    "drug_like_count": len(drug_like),
                    "non_drug_like_count": len(non_drug_like),
                    "strict_mode": strict,
                    "drug_like": drug_like[:50],  # Limit to first 50
                    "non_drug_like": non_drug_like[:50]
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_protein_ligands_from_chembl(ctx, protein_id: str,
                                          activity_types: Optional[List[str]] = None,
                                          min_pchembl: float = 5.0,
                                          max_value_nm: float = 10000.0,
                                          limit: int = 100) -> Dict:
            """
            Get bioactive ligands for a protein from ChEMBL.

            Args:
                protein_id: Protein identifier (UniProt ID, gene name, or ChEMBL target)
                activity_types: Filter by activity types (e.g., ['IC50', 'Ki'])
                min_pchembl: Minimum pChEMBL value (higher = more potent, default 5.0)
                max_value_nm: Maximum activity value in nM (default 10000)
                limit: Maximum number of ligands to return (default 100)

            Returns:
                Dictionary with ligand bioactivity data
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"protein_id": protein_id},
                    ["protein_id"]
                ):
                    return error

                # Default activity types
                if activity_types is None:
                    activity_types = ['IC50', 'Ki', 'Kd', 'EC50']

                # Query ChEMBL directly using the loader
                ligands = query_protein_ligands(
                    protein_id,
                    activity_types=activity_types,
                    min_pchembl=min_pchembl,
                    max_value_nm=max_value_nm,
                    limit=limit
                )

                if not ligands:
                    return self.format_success({
                        "protein_id": protein_id,
                        "activity_types": activity_types,
                        "min_pchembl": min_pchembl,
                        "num_ligands": 0,
                        "ligands": [],
                        "message": f"No ligands found for {protein_id} matching criteria"
                    })

                # Format results
                formatted_ligands = []
                for ligand in ligands:
                    formatted_ligands.append({
                        "chembl_id": ligand.get('chembl_id', ''),
                        "smiles": ligand.get('smiles', ''),
                        "activity_type": ligand.get('activity_type', ''),
                        "value": ligand.get('value', ''),
                        "units": ligand.get('units', ''),
                        "value_nm": ligand.get('value_nm', ''),
                        "pchembl": ligand.get('pchembl_value', '')
                    })

                # In LLM-safe mode, limit to 20 ligands
                safe_max = 20 if self.llm_safe_mode else len(formatted_ligands)
                total_found = len(formatted_ligands)

                return self.format_success({
                    "protein_id": protein_id,
                    "activity_types": activity_types,
                    "min_pchembl": min_pchembl,
                    "total_found": total_found,
                    "num_ligands": min(safe_max, total_found),
                    "ligands": formatted_ligands[:safe_max],
                    "truncated": total_found > safe_max,
                })

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def list_ligand_entities(ctx, limit: Optional[int] = None, offset: int = 0) -> Dict:
            """List registered ligand entities with optional pagination."""

            try:
                processor = self.get_processor("molecule")
                entities = processor.list_ligands()
                total = len(entities)
                start = max(offset, 0)
                end = start + limit if limit else total
                sliced = entities[start:end]

                return self.format_success(
                    {
                        "total": total,
                        "offset": start,
                        "count": len(sliced),
                        "entities": sliced,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

        @server.tool()
        def load_ligand_entity(
            ctx,
            ligand_id: str,
            include_structure: bool = False,
        ) -> Dict:
            """Load a ligand entity and preview its metadata."""

            if error := self.validate_required_params(
                {"ligand_id": ligand_id}, ["ligand_id"]
            ):
                return error

            processor = self.get_processor("molecule")

            try:
                payload = processor.load_entity(ligand_id)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            if payload is None:
                return self.format_error(
                    f"Ligand '{ligand_id}' not found",
                    "Use ligand_register_smiles or other loaders to add ligands first.",
                )

            response: Dict[str, Any] = {
                "ligand_id": ligand_id,
                "kind": payload.get("kind"),
                "metadata": payload.get("metadata", {}),
            }

            if "smiles" in payload:
                response["smiles"] = payload["smiles"]

            if include_structure and "structure" in payload:
                response["structure"] = payload["structure"]

            return self.format_success(response)

        @server.tool()
        def load_ligand_dataset(
            ctx,
            dataset_name: str,
            include_entities: bool = False,
            preview_count: int = 25,
        ) -> Dict:
            """Summarize a ligand dataset and optionally preview member entities."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name}, ["dataset_name"],
            ):
                return error

            processor = self.get_processor("molecule")
            manager = getattr(processor, "dataset_manager", None)
            if manager is None or not manager.dataset_exists(dataset_name):
                return self.format_error(
                    f"Ligand dataset '{dataset_name}' not found",
                    "Use dataset.list_datasets to confirm available ligand datasets.",
                )

            info = manager.get_dataset_info(dataset_name) or {}
            entities = manager.get_dataset_entities(dataset_name)

            payload: Dict[str, Any] = {
                "dataset_name": dataset_name,
                "entity_count": len(entities),
                "metadata": info.get("metadata", {}),
                "entities": entities[: min(preview_count, len(entities))],
                "truncated": len(entities) > preview_count,
            }

            if include_entities and payload["entities"]:
                previews: List[Dict[str, Any]] = []
                for name in payload["entities"]:
                    ligand = processor.load_entity(name) or {}
                    previews.append(
                        {
                            "ligand_id": name,
                            "kind": ligand.get("kind"),
                            "smiles": ligand.get("smiles"),
                            "metadata": ligand.get("metadata", {}),
                        }
                    )
                payload["entity_previews"] = previews

            return self.format_success(payload)

        @server.tool()
        def ligand_dataset_stats(
            ctx,
            dataset_name: str,
            include_entities: bool = False,
        ) -> Dict:
            """Summarize a ligand dataset (entity count, metadata)."""

            result = load_ligand_dataset(
                ctx,
                dataset_name=dataset_name,
                include_entities=include_entities,
            )

            # load_ligand_dataset already returns a success/error dict.
            return result

        @server.tool()
        def ligand_register_smiles(
            ctx,
            smiles_map: Dict[str, str],
            dataset_name: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict:
            """Register SMILES records as ligand entities and persist a dataset."""

            if error := self.validate_required_params(
                {"smiles_map": smiles_map}, ["smiles_map"],
            ):
                return error

            if not smiles_map:
                return self.format_error(
                    "No SMILES records supplied",
                    "Provide a mapping of identifier -> SMILES string",
                )

            processor = self.get_processor("molecule")

            try:
                dataset_id, entity_names = processor.register_smiles_dataset(
                    smiles_map,
                    dataset_name=dataset_name,
                    metadata=metadata,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            return self.format_success(
                {
                    "dataset_name": dataset_id,
                    "entity_count": len(entity_names),
                    "entities": entity_names[: min(25, len(entity_names))],
                    "truncated": len(entity_names) > 25,
                },
                message="Ligand dataset registered",
            )

        @server.tool()
        def ligand_import_smiles_structures(
            ctx,
            smiles_map: Dict[str, str],
            dataset_name: Optional[str] = None,
            chain_id: str = "L",
            generate_3d: bool = True,
        ) -> Dict:
            """Create structure entities from SMILES strings via LigandLoader."""

            if error := self.validate_required_params(
                {"smiles_map": smiles_map}, ["smiles_map"],
            ):
                return error

            if not smiles_map:
                return self.format_error(
                    "No SMILES provided",
                    "Supply one or more identifier → SMILES mappings to import.",
                )

            structure_proc = self.get_processor("structure")
            molecule_proc = self.get_processor("molecule")
            loader = LigandLoader(
                structure_processor=structure_proc,
                ligand_processor=molecule_proc,
            )

            try:
                dataset_id, entities = loader.import_smiles(
                    smiles_map,
                    dataset_name=dataset_name,
                    chain_id=chain_id,
                    generate_3d=generate_3d,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            molecule_ds = f"{dataset_id}_molecules"
            structure_info = structure_proc.dataset_manager.get_dataset_info(dataset_id)
            molecule_info = molecule_proc.dataset_manager.get_dataset_info(molecule_ds)

            return self.format_success(
                {
                    "dataset_name": dataset_id,
                    "structure_entities": entities,
                    "structure_entity_count": len(entities),
                    "structure_metadata": structure_info.get("metadata", {}),
                    "molecule_dataset": molecule_ds,
                    "molecule_metadata": molecule_info.get("metadata", {}),
                },
                message="SMILES imported as structure entities",
            )
        
        @server.tool()
        def find_ligand_in_structures(ctx, ligand_code: str) -> Dict:
            """
            Find PDB structures containing a specific ligand.
            
            Args:
                ligand_code: Three-letter ligand code (e.g., 'ATP', 'NAD', 'HEM')
                
            Returns:
                Dictionary with PDB IDs containing the ligand
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"ligand_code": ligand_code}, 
                    ["ligand_code"]
                ):
                    return error
                
                # Validate ligand code format
                if len(ligand_code) != 3:
                    return self.format_error(
                        "Invalid ligand code",
                        "Ligand code must be exactly 3 characters (e.g., 'ATP')"
                    )
                
                ligand_code = ligand_code.upper()
                
                # Get ligand processor
                processor = self.get_processor("molecule")
                
                # Find structures with this ligand
                pdb_ids = processor.find_ligand_in_structures(ligand_code)
                
                return self.format_success({
                    "ligand_code": ligand_code,
                    "num_structures": len(pdb_ids),
                    "pdb_ids": pdb_ids[:100]  # Limit to first 100
                })

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def ligand_compute_interactions(
            ctx,
            structure_id: str,
            ligand_names: Optional[Sequence[str]] = None,
            distance_cutoff: float = 4.0,
            preview_rows: int = 25,
            save_to_table: Optional[str] = None,
        ) -> Dict:
            """Compute ligand-protein contacts for a structure.

            Args:
                structure_id: Structure to analyze.
                ligand_names: Filter to specific ligands (optional).
                distance_cutoff: Max distance for contacts.
                preview_rows: Max rows to return in preview.
                save_to_table: If provided, save results to this property table
                    instead of returning full data. Returns only a summary.
            """

            if error := self.validate_required_params(
                {"structure_id": structure_id}, ["structure_id"],
            ):
                return error

            struct_proc = self.get_processor("structure")

            try:
                frame = struct_proc.load_entity(structure_id)
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            if frame is None:
                return self.format_error(
                    f"Structure '{structure_id}' not found",
                    "Download the structure before computing interactions.",
                )

            structure_df = frame.reset_index()
            group_series = structure_df["group"].astype(str).str.upper()
            seq_ids = pd.to_numeric(structure_df["auth_seq_id"], errors="coerce")

            summary = struct_proc.summarize_ligands(structure_id)
            ligand_entries: List[Dict[str, Any]] = []

            def _resolve_seq_id(token: Any, payload: Dict[str, Any]) -> Optional[int]:
                seq_id = payload.get("seq_id")
                if seq_id is not None:
                    try:
                        return int(seq_id)
                    except (TypeError, ValueError):
                        return None
                for part in str(token).split("_"):
                    if part.isdigit():
                        return int(part)
                return None

            for chain_id, residues in summary.get("chains", {}).items():
                for res_id_token, payload in residues.items():
                    comp = (payload.get("comp_id") or "").upper()
                    seq_id = _resolve_seq_id(res_id_token, payload)
                    if not comp or seq_id is None:
                        continue
                    ligand_entries.append(
                        {
                            "name": comp,
                            "chain": chain_id,
                            "res_id": seq_id,
                        }
                    )

            if ligand_names:
                targets = {name.upper() for name in ligand_names}
                ligand_entries = [entry for entry in ligand_entries if entry["name"] in targets]

            if not ligand_entries:
                return self.format_error(
                    "No ligands matched the requested filters",
                    "Use extract_ligands_from_structure to inspect available ligands.",
                )

            processed_names = [entry["name"] for entry in ligand_entries]

            interaction_rows: List[Dict[str, Any]] = []
            ligand_summaries: Dict[str, Dict[str, Any]] = {}

            for entry in ligand_entries:
                mask = (
                    (group_series == "HETATM")
                    & (structure_df["auth_chain_id"] == entry["chain"])
                    & (seq_ids == entry["res_id"])
                )
                ligand_atoms = structure_df[mask]
                if ligand_atoms.empty:
                    continue

                try:
                    interactions = calculate_ligand_interactions(
                        struct_proc,
                        structure_id,
                        ligand_atoms,
                        detailed=True,
                        cutoff=distance_cutoff,
                    )
                except Exception as exc:  # noqa: BLE001
                    return self.handle_error(exc)

                descriptor = f"{structure_id}:{entry['name']}:{entry['chain']}:{entry['res_id']}"
                ligand_summaries[descriptor] = interactions.get("summary", {})

                for residue in interactions.get("binding_residues", []):
                    interaction_rows.append(
                        {
                            "structure_id": structure_id,
                            "ligand": entry["name"],
                            "ligand_descriptor": descriptor,
                            "chain_id": residue.get("chain_id"),
                            "res_id": residue.get("res_id"),
                            "res_name": residue.get("res_name"),
                            "min_distance": residue.get("min_distance"),
                            "num_contacts": residue.get("num_contacts"),
                            "contact_atoms": residue.get("contact_atoms"),
                        }
                    )

            if not interaction_rows:
                return self.format_success(
                    {
                        "structure_id": structure_id,
                        "ligand_names": list(ligand_names or []),
                        "distance_cutoff": distance_cutoff,
                        "interaction_count": 0,
                        "interactions": [],
                        "summaries": ligand_summaries,
                    },
                    message="No ligand-protein contacts detected",
                )

            df = pd.DataFrame(interaction_rows)
            df = df.dropna(subset=["res_id"])
            df["res_id"] = df["res_id"].astype(int)

            records = df.to_dict(orient="records")

            # If save_to_table specified, save and return summary only
            if save_to_table:
                try:
                    prop_proc = self.get_processor("property")
                    # Add scope column required by record_properties
                    for row in records:
                        row["scope"] = [{"format": "structure", "name": structure_id}]
                    prop_proc.record_properties(
                        save_to_table, records, allow_create=True
                    )
                    return self.format_success({
                        "saved": True,
                        "table": save_to_table,
                        "rows": len(records),
                        "structure_id": structure_id,
                        "ligands": processed_names,
                        "summaries": ligand_summaries,
                    })
                except Exception as exc:  # noqa: BLE001
                    return self.handle_error(exc)

            # Default: return data directly
            preview = records[: min(preview_rows, len(records))]
            return self.format_success(
                {
                    "structure_id": structure_id,
                    "ligand_names": processed_names,
                    "distance_cutoff": distance_cutoff,
                    "interaction_count": int(len(df)),
                    "unique_ligands": sorted(set(df["ligand_descriptor"].astype(str))),
                    "columns": list(df.columns),
                    "interactions": preview,
                    "truncated": len(records) > preview_rows,
                    "dataframe": records,
                    "summaries": ligand_summaries,
                }
            )
        
        @server.tool()
        def create_ligand_dataset_from_chembl(ctx, protein_id: str,
                                            dataset_name: str,
                                            activity_types: Optional[List[str]] = None,
                                            min_pchembl: float = 6.0,
                                            max_ligands: int = 1000) -> Dict:
            """
            Create a ligand dataset from ChEMBL bioactivity data.
            
            This tool downloads ligands for a protein target and creates
            a dataset with their properties and bioactivity data.
            
            Args:
                protein_id: Protein identifier (UniProt ID or gene name)
                dataset_name: Name for the new dataset
                activity_types: Activity types to include
                min_pchembl: Minimum pChEMBL value
                max_ligands: Maximum number of ligands to include
                
            Returns:
                Dictionary with dataset creation status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"protein_id": protein_id, "dataset_name": dataset_name}, 
                    ["protein_id", "dataset_name"]
                ):
                    return error
                
                # Get ligand processor
                processor = self.get_processor("molecule")
                
                # Get ligands from ChEMBL
                ligands = processor.get_protein_ligands(
                    protein_id,
                    activity_types=activity_types,
                    min_pchembl=min_pchembl
                )
                
                if not ligands:
                    return self.format_error(
                        f"No ligands found for {protein_id}",
                        "Check protein ID or adjust activity filters"
                    )
                
                # Limit number of ligands
                if len(ligands) > max_ligands:
                    ligands = ligands[:max_ligands]
                
                # Save ligands as entities
                saved_count = 0
                entity_names = []
                
                for ligand in ligands:
                    smiles = ligand.get('canonical_smiles', '')
                    if not smiles:
                        continue
                    
                    # Prepare ligand data
                    ligand_data = {
                        'smiles': smiles,
                        'chembl_id': ligand.get('chembl_id', ''),
                        'properties': {},
                        'activities': [{
                            'type': ligand.get('activity_type', ''),
                            'value': ligand.get('value', ''),
                            'units': ligand.get('units', ''),
                            'pchembl': ligand.get('pchembl_value', '')
                        }],
                        'targets': [protein_id]
                    }
                    
                    try:
                        processor.save_entity(smiles, ligand_data)
                        entity_names.append(smiles)
                        saved_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to save ligand {smiles}: {e}")
                
                # Create dataset
                if entity_names:
                    processor.create_dataset(
                        dataset_name,
                        entity_names,
                        metadata={
                            'protein_target': protein_id,
                            'activity_types': activity_types,
                            'min_pchembl': min_pchembl,
                            'source': 'ChEMBL'
                        }
                    )
                    
                    return self.format_success({
                        "dataset_name": dataset_name,
                        "protein_id": protein_id,
                        "total_ligands": len(ligands),
                        "saved_ligands": saved_count,
                        "dataset_created": True
                    })
                else:
                    return self.format_error(
                        "No valid ligands could be saved",
                        "Check ChEMBL data quality or connection"
                    )
                    
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def ligand_record_interactions(
            ctx,
            table_name: str,
            interactions: List[Dict[str, Any]],
            metadata: Optional[Dict[str, Any]] = None,
            allow_create: bool = True,
        ) -> Dict:
            """Record ligand interaction rows into a property table."""

            if error := self.validate_required_params(
                {"table_name": table_name, "interactions": interactions},
                ["table_name", "interactions"],
            ):
                return error

            if not interactions:
                return self.format_error(
                    "Empty interaction payload",
                    "Provide at least one interaction row from ligand_compute_interactions",
                )

            try:
                df = pd.DataFrame(interactions)
            except Exception as exc:  # noqa: BLE001
                return self.format_error(
                    "Failed to construct interaction table",
                    f"Ensure rows share consistent keys: {exc}",
                )

            processor = self.get_processor("molecule")

            try:
                recorded = processor.record_interactions(
                    table_name,
                    df,
                    metadata=metadata,
                    allow_create=allow_create,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            return self.format_success(
                {
                    "table_name": table_name,
                    "row_count": int(len(recorded)),
                    "columns": recorded.columns.tolist(),
                },
                message="Ligand interactions recorded",
            )

        @server.tool()
        def ligand_import_sdf(
            ctx,
            file_path: str,
            dataset_name: Optional[str] = None,
            chain_id: str = "L",
        ) -> Dict:
            """
            Import ligands from an SDF file and register them as entities.

            This tool imports molecules from an SDF file, creating:
            - Structure entities (with 3D coordinates from the SDF)
            - Molecule entities (with SMILES and metadata)
            - A dataset containing all imported entities

            Args:
                file_path: Path to the SDF file (absolute or relative to data root)
                dataset_name: Custom name for the created dataset (auto-generated if None)
                chain_id: Chain identifier for the ligand atoms (default 'L')

            Returns:
                Dictionary with dataset name and registered entity names
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"file_path": file_path},
                    ["file_path"]
                ):
                    return error

                from pathlib import Path as PathLib

                # Resolve file path
                input_path = PathLib(file_path)
                if not input_path.is_absolute():
                    # Try relative to data root input folder
                    data_root = PathLib(self.paths.data_root)
                    candidates = [
                        data_root / "input" / file_path,
                        data_root / file_path,
                        PathLib(file_path),
                    ]
                    for candidate in candidates:
                        if candidate.exists():
                            input_path = candidate
                            break

                if not input_path.exists():
                    return self.format_error(
                        f"SDF file not found: {file_path}",
                        "Provide the full path or place the file in data/input/"
                    )

                # Get processors
                structure_proc = self.get_processor("structure")
                molecule_proc = self.get_processor("molecule")

                # Create loader with both processors
                loader = LigandLoader(
                    structure_processor=structure_proc,
                    ligand_processor=molecule_proc,
                )

                # Import the SDF file
                dataset_id, entity_names = loader.import_sdf(
                    str(input_path),
                    dataset_name=dataset_name,
                    chain_id=chain_id,
                )

                # Get molecule dataset info
                molecule_dataset = f"{dataset_id}_molecules"

                return self.format_success({
                    "file_path": str(input_path),
                    "dataset_name": dataset_id,
                    "molecule_dataset": molecule_dataset,
                    "entity_count": len(entity_names),
                    "entities": entity_names[:25],  # Limit preview
                    "truncated": len(entity_names) > 25,
                }, message=f"Imported {len(entity_names)} molecule(s) from SDF")

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def ligand_smiles_to_inchi(ctx, smiles: str) -> Dict:
            """
            Convert SMILES to InChI and InChI Key.
            
            Args:
                smiles: SMILES string
                
            Returns:
                Dictionary with InChI representations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"smiles": smiles}, 
                    ["smiles"]
                ):
                    return error
                
                # Get ligand processor
                processor = self.get_processor("molecule")
                
                # Import utility function
                from protos.loaders.ligand_utils import smiles_to_inchi
                
                inchi, inchi_key = smiles_to_inchi(smiles)
                
                if inchi is None:
                    return self.format_error(
                        f"Failed to convert SMILES: {smiles}",
                        "Check if SMILES is valid and RDKit is installed"
                    )
                
                return self.format_success({
                    "smiles": smiles,
                    "inchi": inchi,
                    "inchi_key": inchi_key
                })

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def ligand_modify_smiles(
            ctx,
            smiles: str,
            atom_index: Optional[int] = None,
            old_element: str = "C",
            new_element: str = "N",
            in_ring_only: bool = True,
            occurrence: int = 1,
        ) -> Dict:
            """
            Modify a SMILES string by replacing an atom element.

            Can replace a specific atom by index, or find and replace occurrences
            of an element (optionally restricted to ring atoms).

            Args:
                smiles: Input SMILES string
                atom_index: Specific atom index to modify (0-based). If None, searches for element.
                old_element: Element to replace (default: "C" for carbon)
                new_element: New element (default: "N" for nitrogen)
                in_ring_only: Only replace atoms in rings (default: True)
                occurrence: Which occurrence to replace (1-based, default: 1 for first match)

            Returns:
                Dictionary with original and modified SMILES, plus atom info

            Example:
                # Replace first ring carbon with nitrogen
                ligand_modify_smiles(
                    smiles="c1ccccc1",  # benzene
                    old_element="C",
                    new_element="N",
                    in_ring_only=True
                )
                # Returns pyridine-like structure
            """
            try:
                if error := self.validate_required_params(
                    {"smiles": smiles}, ["smiles"]
                ):
                    return error

                try:
                    from rdkit import Chem
                    from rdkit.Chem import AllChem, Descriptors
                except ImportError:
                    return self.format_error(
                        "RDKit is required for SMILES modification",
                        "Install RDKit: pip install rdkit"
                    )

                # Parse the molecule
                mol = Chem.MolFromSmiles(smiles)
                if mol is None:
                    return self.format_error(
                        f"Invalid SMILES: {smiles}",
                        "Check SMILES syntax"
                    )

                # Make editable molecule
                rw_mol = Chem.RWMol(mol)

                # Get ring info
                ring_info = mol.GetRingInfo()
                ring_atoms = set()
                for ring in ring_info.AtomRings():
                    ring_atoms.update(ring)

                modified_idx = None
                old_element_upper = old_element.upper()
                new_element_upper = new_element.upper()

                if atom_index is not None:
                    # Modify specific atom
                    if atom_index < 0 or atom_index >= mol.GetNumAtoms():
                        return self.format_error(
                            f"Atom index {atom_index} out of range (0-{mol.GetNumAtoms()-1})",
                            "Use a valid atom index"
                        )
                    atom = rw_mol.GetAtomWithIdx(atom_index)
                    if in_ring_only and atom_index not in ring_atoms:
                        return self.format_error(
                            f"Atom {atom_index} is not in a ring",
                            "Set in_ring_only=False to modify non-ring atoms"
                        )
                    atom.SetAtomicNum(Chem.GetPeriodicTable().GetAtomicNumber(new_element_upper))
                    modified_idx = atom_index
                else:
                    # Find and replace by element
                    count = 0
                    for idx in range(mol.GetNumAtoms()):
                        atom = mol.GetAtomWithIdx(idx)
                        if atom.GetSymbol().upper() == old_element_upper:
                            if in_ring_only and idx not in ring_atoms:
                                continue
                            count += 1
                            if count == occurrence:
                                rw_atom = rw_mol.GetAtomWithIdx(idx)
                                rw_atom.SetAtomicNum(Chem.GetPeriodicTable().GetAtomicNumber(new_element_upper))
                                modified_idx = idx
                                break

                    if modified_idx is None:
                        return self.format_error(
                            f"No {old_element} atom found" + (" in rings" if in_ring_only else ""),
                            f"Check element or set in_ring_only=False"
                        )

                # Generate new SMILES
                try:
                    Chem.SanitizeMol(rw_mol)
                    new_smiles = Chem.MolToSmiles(rw_mol)
                except Exception as san_err:
                    return self.format_error(
                        f"Modified molecule is chemically invalid: {san_err}",
                        "The atom replacement created an invalid structure"
                    )

                # Calculate properties for comparison
                original_mol = Chem.MolFromSmiles(smiles)
                modified_mol = Chem.MolFromSmiles(new_smiles)

                return self.format_success({
                    "original_smiles": smiles,
                    "modified_smiles": new_smiles,
                    "modification": {
                        "atom_index": modified_idx,
                        "old_element": old_element_upper,
                        "new_element": new_element_upper,
                        "in_ring": modified_idx in ring_atoms if modified_idx is not None else None,
                    },
                    "original_formula": Chem.rdMolDescriptors.CalcMolFormula(original_mol),
                    "modified_formula": Chem.rdMolDescriptors.CalcMolFormula(modified_mol),
                    "original_mw": round(Descriptors.MolWt(original_mol), 2),
                    "modified_mw": round(Descriptors.MolWt(modified_mol), 2),
                }, message=f"Replaced {old_element_upper} with {new_element_upper} at atom {modified_idx}")

            except Exception as e:
                return self.handle_error(e)
