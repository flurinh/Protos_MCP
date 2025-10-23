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
                                  max_results: int = 100) -> Dict:
            """
            Search for similar ligands using Tanimoto similarity.
            
            Args:
                query_smiles: Query SMILES string
                similarity_threshold: Minimum similarity score (0-1)
                dataset: Optional dataset to search within
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
                
                # Get ligand processor
                processor = self.get_processor("molecule")

                if not hasattr(processor, "search_similar_ligands"):
                    return self.format_error(
                        "MoleculeProcessor does not expose similarity search",
                        "Port the legacy similarity utilities or provide a fingerprint backend."
                    )

                # Search for similar ligands
                results = processor.search_similar_ligands(
                    query_smiles,
                    similarity=similarity_threshold,
                    dataset=dataset
                )
                
                # Limit results
                if len(results) > max_results:
                    results = results[:max_results]
                
                # Format results
                similar_ligands = []
                for smiles, similarity in results:
                    similar_ligands.append({
                        "smiles": smiles,
                        "similarity": round(similarity, 3)
                    })
                
                return self.format_success({
                    "query_smiles": query_smiles,
                    "similarity_threshold": similarity_threshold,
                    "dataset": dataset,
                    "num_results": len(similar_ligands),
                    "similar_ligands": similar_ligands
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
                                          reload: bool = False) -> Dict:
            """
            Get bioactive ligands for a protein from ChEMBL.
            
            Args:
                protein_id: Protein identifier (UniProt ID, gene name, or ChEMBL target)
                activity_types: Filter by activity types (e.g., ['IC50', 'Ki'])
                min_pchembl: Minimum pChEMBL value (higher = more potent)
                reload: Force reload from ChEMBL (ignore cache)
                
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
                
                # Get ligand processor
                processor = self.get_processor("molecule")

                if not hasattr(processor, "get_protein_ligands"):
                    return self.format_error(
                        "ChemBL integration not available",
                        "The MoleculeProcessor transition removed direct ChEMBL loaders."
                    )

                # Get ligands from ChEMBL
                ligands = processor.get_protein_ligands(
                    protein_id,
                    reload=reload,
                    activity_types=activity_types,
                    min_pchembl=min_pchembl
                )
                
                # Format results
                formatted_ligands = []
                for ligand in ligands[:100]:  # Limit to first 100
                    formatted_ligands.append({
                        "chembl_id": ligand.get('chembl_id', ''),
                        "smiles": ligand.get('canonical_smiles', ''),
                        "activity_type": ligand.get('activity_type', ''),
                        "value": ligand.get('value', ''),
                        "units": ligand.get('units', ''),
                        "pchembl": ligand.get('pchembl_value', '')
                    })
                
                return self.format_success({
                    "protein_id": protein_id,
                    "activity_types": activity_types,
                    "min_pchembl": min_pchembl,
                    "num_ligands": len(ligands),
                    "ligands": formatted_ligands
                })
                
            except Exception as e:
                return self.handle_error(e)

        @server.tool()
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
        ) -> Dict:
            """Compute ligand-protein contacts for a structure."""

            if error := self.validate_required_params(
                {"structure_id": structure_id}, ["structure_id"],
            ):
                return error

            processor = self.get_processor("molecule")

            try:
                df = processor.compute_interactions(
                    structure_id,
                    ligands=ligand_names,
                    distance_cutoff=distance_cutoff,
                )
            except Exception as exc:  # noqa: BLE001
                return self.handle_error(exc)

            if df.empty:
                return self.format_success(
                    {
                        "structure_id": structure_id,
                        "ligand_names": list(ligand_names or []),
                        "distance_cutoff": distance_cutoff,
                        "interaction_count": 0,
                        "interactions": [],
                    },
                    message="No ligand-protein contacts detected",
                )

            records = df.to_dict(orient="records")
            unique_ligands = sorted(set(df["ligand_descriptor"].astype(str)))

            return self.format_success(
                {
                    "structure_id": structure_id,
                    "ligand_names": list(ligand_names or []),
                    "distance_cutoff": distance_cutoff,
                    "interaction_count": int(len(df)),
                    "unique_ligands": unique_ligands,
                    "columns": list(df.columns),
                    "interactions": records[: min(preview_rows, len(records))],
                    "truncated": len(records) > preview_rows,
                    "dataframe": records,
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
