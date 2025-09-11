"""
Ligand analysis tools leveraging Protos' LigandProcessor.

These tools provide comprehensive ligand analysis capabilities including
molecular property calculation, similarity search, drug-likeness filtering,
ChEMBL integration, and structure-ligand analysis.
"""

from typing import Dict, List, Optional, Any, Tuple
import json
import logging

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, EntityNotFoundError

logger = logging.getLogger(__name__)


class LigandAnalysisTools(BaseTool):
    """Tools for ligand analysis and processing."""
    
    def register(self, server):
        """Register ligand analysis tools with the server."""
        
        @server.tool()
        def calculate_molecular_properties(ctx, smiles: str) -> Dict:
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
                processor = self.get_processor("ligand")
                
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
                processor = self.get_processor("ligand")
                
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
                processor = self.get_processor("ligand")
                
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
                processor = self.get_processor("ligand")
                
                # Check if ChEMBL loader is available
                if not hasattr(processor, 'chembl_loader') or processor.chembl_loader is None:
                    return self.format_error(
                        "ChEMBL integration not available",
                        "Ensure ChEMBL loader is installed and configured"
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
                processor = self.get_processor("ligand")
                
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
                processor = self.get_processor("ligand")
                
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
        def smiles_to_inchi(ctx, smiles: str) -> Dict:
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
                processor = self.get_processor("ligand")
                
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