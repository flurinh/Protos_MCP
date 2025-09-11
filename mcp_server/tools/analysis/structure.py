"""
Structure analysis tools for analyzing protein structures.

These tools provide analysis capabilities for structural data including
sequence extraction, chain analysis, coordinate extraction, and ligand analysis.
"""

from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime
import pandas as pd
import numpy as np

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, EntityNotFoundError


class StructureAnalysisTools(BaseTool):
    """Tools for structure analysis and manipulation."""
    
    def register(self, server):
        """Register structure analysis tools with the server."""
        
        @server.tool()
        def extract_sequence_from_structure(ctx, pdb_id: str,
                                          chain_id: str = "A",
                                          save_to_sequence: bool = False) -> Dict:
            """
            Extract amino acid sequence from a protein structure.
            
            Args:
                pdb_id: PDB identifier of the structure
                chain_id: Chain ID to extract sequence from
                save_to_sequence: If True, save to sequence processor
                
            Returns:
                Dictionary with extracted sequence
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Extract sequence
                try:
                    sequence = processor.get_sequence(pdb_id, chain_id)
                except ValueError as e:
                    return self.format_error(
                        str(e),
                        f"Make sure structure {pdb_id} is loaded and chain {chain_id} exists"
                    )
                
                if not sequence:
                    return self.format_error(
                        f"No sequence found for {pdb_id} chain {chain_id}",
                        "Check if the chain exists in the structure"
                    )
                
                result = {
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "sequence": sequence,
                    "length": len(sequence)
                }
                
                # Save to sequence processor if requested
                if save_to_sequence:
                    try:
                        seq_processor = self.get_processor("sequence")
                        seq_processor.save_entity(
                            name=f"{pdb_id}_{chain_id}",
                            data=sequence,
                            metadata={"source": "structure", "pdb_id": pdb_id, "chain": chain_id}
                        )
                        result["saved_to_sequence"] = True
                    except Exception as e:
                        result["save_error"] = str(e)
                        result["saved_to_sequence"] = False
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_all_sequences_from_structure(ctx, pdb_id: str,
                                           save_to_sequence: bool = False) -> Dict:
            """
            Extract sequences from all chains in a structure.
            
            Args:
                pdb_id: PDB identifier
                save_to_sequence: If True, save all to sequence processor
                
            Returns:
                Dictionary with sequences for all chains
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Get all sequences
                try:
                    sequences = processor.get_all_sequences()
                except Exception as e:
                    return self.format_error(
                        f"Failed to extract sequences: {str(e)}",
                        f"Make sure structure {pdb_id} is loaded"
                    )
                
                # Filter to this PDB ID
                pdb_sequences = {
                    chain_id: seq 
                    for chain_id, seq in sequences.items() 
                    if chain_id.startswith(f"{pdb_id}_")
                }
                
                if not pdb_sequences:
                    return self.format_error(
                        f"No sequences found for {pdb_id}",
                        "Structure may not be loaded or has no chains"
                    )
                
                result = {
                    "pdb_id": pdb_id,
                    "chains": len(pdb_sequences),
                    "sequences": pdb_sequences
                }
                
                # Save to sequence processor if requested
                if save_to_sequence:
                    saved = []
                    errors = []
                    try:
                        seq_processor = self.get_processor("sequence")
                        for chain_id, sequence in pdb_sequences.items():
                            try:
                                seq_processor.save_entity(
                                    name=chain_id,
                                    data=sequence,
                                    metadata={"source": "structure", "pdb_id": pdb_id}
                                )
                                saved.append(chain_id)
                            except Exception as e:
                                errors.append({"chain": chain_id, "error": str(e)})
                        
                        result["saved_sequences"] = saved
                        if errors:
                            result["save_errors"] = errors
                    except Exception as e:
                        result["save_error"] = str(e)
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_structure_chains(ctx, pdb_id: str) -> Dict:
            """
            Get list of chains in a structure.
            
            Args:
                pdb_id: PDB identifier
                
            Returns:
                Dictionary with chain information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Get chains
                chains = processor.get_chains(pdb_id)
                
                if not chains:
                    return self.format_error(
                        f"No chains found for {pdb_id}",
                        "Structure may not be loaded"
                    )
                
                # Get additional info for each chain
                chain_info = []
                for chain in chains:
                    try:
                        seq = processor.get_sequence(pdb_id, chain)
                        chain_info.append({
                            "chain_id": chain,
                            "length": len(seq) if seq else 0
                        })
                    except:
                        chain_info.append({
                            "chain_id": chain,
                            "length": 0
                        })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "chain_count": len(chains),
                    "chains": chain_info
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_ca_coordinates(ctx, pdb_id: str, chain_id: str = "A") -> Dict:
            """
            Get C-alpha atom coordinates for a chain.
            
            Args:
                pdb_id: PDB identifier
                chain_id: Chain ID
                
            Returns:
                Dictionary with coordinate array
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Get coordinates
                try:
                    coords = processor.get_ca_coordinates(pdb_id, chain_id)
                except ValueError as e:
                    return self.format_error(
                        str(e),
                        f"Make sure {pdb_id} chain {chain_id} exists"
                    )
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "num_residues": len(coords),
                    "coordinates": coords.tolist(),  # Convert numpy array to list
                    "shape": list(coords.shape)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def extract_ligands_from_structure(ctx, pdb_id: str,
                                         exclude_common: bool = True,
                                         min_atoms: int = 3) -> Dict:
            """
            Extract all ligands from a protein structure.
            
            Args:
                pdb_id: PDB identifier
                exclude_common: Exclude water, ions, common molecules
                min_atoms: Minimum atoms for a ligand
                
            Returns:
                Dictionary with ligand information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Import analysis function
                try:
                    from protos.analysis.structure_ligand_analysis import extract_all_ligands
                except ImportError:
                    return self.format_error(
                        "Ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Extract ligands
                ligands = extract_all_ligands(
                    processor, 
                    pdb_id,
                    exclude_common=exclude_common,
                    min_atoms=min_atoms
                )
                
                # Format results
                ligand_summary = []
                for ligand in ligands:
                    ligand_summary.append({
                        "ligand_id": ligand['ligand_id'],
                        "res_name": ligand['res_name3l'],
                        "chain_id": ligand['chain_id'],
                        "res_id": ligand['res_id'],
                        "num_atoms": ligand['num_atoms'],
                        "centroid": ligand['centroid'].tolist()
                    })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "num_ligands": len(ligands),
                    "ligands": ligand_summary,
                    "excluded_common": exclude_common,
                    "min_atoms": min_atoms
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_binding_site_residues(ctx, pdb_id: str,
                                    ligand_name: str,
                                    chain_id: Optional[str] = None,
                                    cutoff: float = 5.0) -> Dict:
            """
            Get residues in the binding site of a ligand.
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code
                chain_id: Optional chain specification
                cutoff: Distance cutoff in Angstroms
                
            Returns:
                Dictionary with binding site residues
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Import analysis functions
                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_ligand_by_id, get_binding_site
                    )
                except ImportError:
                    return self.format_error(
                        "Ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Get ligand atoms
                ligand_atoms = get_ligand_by_id(
                    processor, pdb_id, ligand_name, chain_id
                )
                
                if ligand_atoms is None or ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}",
                        "Check ligand name and chain ID"
                    )
                
                # Get binding site
                binding_site = get_binding_site(
                    processor, pdb_id, ligand_atoms, cutoff
                )
                
                # Format results
                residues = binding_site['residues']
                unique_residues = residues[['auth_chain_id', 'res_name3l', 'auth_seq_id']].drop_duplicates()
                
                residue_list = []
                for _, res in unique_residues.iterrows():
                    residue_list.append({
                        "chain": res['auth_chain_id'],
                        "res_name": res['res_name3l'],
                        "res_id": int(res['auth_seq_id'])
                    })
                
                return self.format_success({
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "cutoff": cutoff,
                    "num_residues": len(unique_residues),
                    "binding_site_residues": residue_list,
                    "total_atoms": len(binding_site['atoms'])
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def analyze_ligand_interactions(ctx, pdb_id: str,
                                       ligand_name: str,
                                       chain_id: Optional[str] = None,
                                       detailed: bool = True) -> Dict:
            """
            Analyze detailed protein-ligand interactions including multiple interaction types.
            
            This tool provides comprehensive interaction analysis beyond simple distance cutoffs,
            including hydrogen bonds, hydrophobic contacts, pi-stacking, salt bridges, and
            water-mediated interactions.
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code (e.g., 'ATP', 'HEM')
                chain_id: Optional chain specification for the ligand
                detailed: If True, return detailed interaction lists; if False, only summary
                
            Returns:
                Dictionary with comprehensive interaction analysis including:
                - Hydrogen bonds with donor/acceptor information
                - Hydrophobic contacts
                - Water-mediated bridges
                - Pi-stacking interactions
                - Salt bridges
                - Binding site residue summary
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Import analysis function
                try:
                    from protos.analysis.structure_ligand_analysis import calculate_ligand_interactions
                except ImportError:
                    return self.format_error(
                        "Advanced ligand analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Get ligand atoms
                structure_data = processor.data[processor.data['pdb_id'] == pdb_id]
                ligand_filter = (structure_data['group'] == 'HETATM') & (structure_data['res_name3l'] == ligand_name)
                if chain_id:
                    ligand_filter &= (structure_data['auth_chain_id'] == chain_id)
                
                ligand_atoms = structure_data[ligand_filter]
                
                if ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}" + 
                        (f" chain {chain_id}" if chain_id else ""),
                        "Check ligand name and chain ID. Use extract_ligands_from_structure to list available ligands"
                    )
                
                # Calculate interactions
                interactions = calculate_ligand_interactions(
                    processor, pdb_id, ligand_atoms, detailed=detailed
                )
                
                # Format the response
                result = {
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "num_ligand_atoms": len(ligand_atoms)
                }
                
                if detailed:
                    # Include full interaction details
                    result.update({
                        "summary": interactions.get('summary', {}),
                        "binding_site": interactions.get('binding_site', {}),
                        "hydrogen_bonds": interactions.get('hydrogen_bonds', []),
                        "hydrophobic_contacts": interactions.get('hydrophobic', []),
                        "water_mediated": interactions.get('water_mediated', []),
                        "pi_stacking": interactions.get('pi_stacking', []),
                        "salt_bridges": interactions.get('salt_bridges', [])
                    })
                else:
                    # Only include summary
                    result["summary"] = interactions
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def analyze_binding_pocket(ctx, pdb_id: str,
                                 ligand_name: str,
                                 chain_id: Optional[str] = None,
                                 cutoff: float = 8.0,
                                 include_volume: bool = True) -> Dict:
            """
            Analyze the binding pocket around a ligand including volume estimation.
            
            This tool provides comprehensive binding pocket analysis including:
            - Binding site residue identification
            - Pocket volume estimation using convex hull
            - Residue conservation potential
            - Pocket properties (hydrophobicity, charge distribution)
            
            Args:
                pdb_id: PDB identifier
                ligand_name: Three-letter ligand code
                chain_id: Optional chain specification for the ligand
                cutoff: Distance cutoff for binding site definition (Angstroms)
                include_volume: Whether to calculate pocket volume
                
            Returns:
                Dictionary with binding pocket analysis
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id, "ligand_name": ligand_name},
                    ["pdb_id", "ligand_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Import analysis functions
                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_binding_site, estimate_binding_site_volume
                    )
                except ImportError:
                    return self.format_error(
                        "Binding pocket analysis module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Get ligand atoms
                structure_data = processor.data[processor.data['pdb_id'] == pdb_id]
                ligand_filter = (structure_data['group'] == 'HETATM') & (structure_data['res_name3l'] == ligand_name)
                if chain_id:
                    ligand_filter &= (structure_data['auth_chain_id'] == chain_id)
                
                ligand_atoms = structure_data[ligand_filter]
                
                if ligand_atoms.empty:
                    return self.format_error(
                        f"Ligand {ligand_name} not found in {pdb_id}",
                        "Use extract_ligands_from_structure to list available ligands"
                    )
                
                # Get binding site
                binding_site = get_binding_site(processor, pdb_id, ligand_atoms, cutoff)
                
                if binding_site['residues'].empty:
                    return self.format_error(
                        "No binding site residues found",
                        f"Try increasing cutoff beyond {cutoff} Angstroms"
                    )
                
                # Analyze pocket composition
                residues_df = binding_site['residues']
                
                # Categorize residues
                hydrophobic = ['ALA', 'VAL', 'LEU', 'ILE', 'MET', 'PHE', 'TRP', 'PRO']
                aromatic = ['PHE', 'TYR', 'TRP']
                charged = ['ARG', 'LYS', 'ASP', 'GLU', 'HIS']
                polar = ['SER', 'THR', 'CYS', 'ASN', 'GLN', 'TYR']
                
                residue_counts = residues_df['res_name'].value_counts().to_dict()
                
                pocket_properties = {
                    "hydrophobic_residues": sum(residues_df['res_name'].isin(hydrophobic)),
                    "aromatic_residues": sum(residues_df['res_name'].isin(aromatic)),
                    "charged_residues": sum(residues_df['res_name'].isin(charged)),
                    "polar_residues": sum(residues_df['res_name'].isin(polar))
                }
                
                # Format residue list
                residue_list = []
                for _, res in residues_df.iterrows():
                    residue_list.append({
                        "residue": f"{res['res_name']}{res['res_id']}",
                        "chain": res['chain_id'],
                        "distance": round(res['min_distance'], 2),
                        "num_atoms": res['num_atoms']
                    })
                
                result = {
                    "pdb_id": pdb_id,
                    "ligand": ligand_name,
                    "chain_id": chain_id,
                    "cutoff": cutoff,
                    "num_residues": len(residues_df),
                    "num_atoms": len(binding_site['atoms']),
                    "residue_composition": residue_counts,
                    "pocket_properties": pocket_properties,
                    "binding_residues": residue_list
                }
                
                # Calculate pocket volume if requested
                if include_volume:
                    try:
                        volume = estimate_binding_site_volume(binding_site['atoms'])
                        result["pocket_volume"] = {
                            "volume_cubic_angstroms": round(volume, 2),
                            "estimated_method": "convex_hull"
                        }
                    except Exception as e:
                        result["pocket_volume"] = {
                            "error": f"Could not calculate volume: {str(e)}"
                        }
                
                # Identify key interaction residues (closest to ligand)
                closest_residues = residues_df.nsmallest(5, 'min_distance')
                result["key_residues"] = [
                    f"{row['res_name']}{row['res_id']}" 
                    for _, row in closest_residues.iterrows()
                ]
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_structure_properties(ctx, pdb_id: str,
                                         chain_id: Optional[str] = None) -> Dict:
            """
            Calculate basic structural properties.
            
            Args:
                pdb_id: PDB identifier
                chain_id: Optional specific chain
                
            Returns:
                Dictionary with structural properties
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id},
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if needed
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                
                # Get structure data
                structure_data = processor.data[processor.data['pdb_id'] == pdb_id]
                if chain_id:
                    structure_data = structure_data[structure_data['auth_chain_id'] == chain_id]
                
                if structure_data.empty:
                    return self.format_error(
                        f"No data found for {pdb_id}" + (f" chain {chain_id}" if chain_id else ""),
                        "Check PDB ID and chain specification"
                    )
                
                # Calculate properties
                properties = {
                    "pdb_id": pdb_id,
                    "chain_id": chain_id,
                    "total_atoms": len(structure_data),
                    "protein_atoms": len(structure_data[structure_data['group'] == 'ATOM']),
                    "hetero_atoms": len(structure_data[structure_data['group'] == 'HETATM']),
                    "num_residues": structure_data[structure_data['group'] == 'ATOM']['auth_seq_id'].nunique(),
                    "chains": structure_data['auth_chain_id'].unique().tolist(),
                    "resolution": structure_data['resolution'].iloc[0] if 'resolution' in structure_data.columns else None
                }
                
                # Bounding box
                coords = structure_data[['x', 'y', 'z']].values
                properties["bounding_box"] = {
                    "min": coords.min(axis=0).tolist(),
                    "max": coords.max(axis=0).tolist(),
                    "center": coords.mean(axis=0).tolist()
                }
                
                return self.format_success(properties)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def align_protein_structures(ctx, reference_pdb: str, mobile_pdb: str,
                                   atom_selection: str = "CA",
                                   chain_selection: Optional[str] = None,
                                   window_size: int = 8,
                                   max_gap: int = 30) -> Dict:
            """
            Align two protein structures using CEalign algorithm.
            
            This tool performs structural alignment of two proteins and returns
            the transformation matrix and RMSD. The alignment is performed on
            selected atoms (default: CA atoms).
            
            Args:
                reference_pdb: PDB ID of the reference structure
                mobile_pdb: PDB ID of the structure to align
                atom_selection: Atom type to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align (e.g., "A"), or None for all
                window_size: Window size for CEalign algorithm
                max_gap: Maximum gap size for CEalign algorithm
                
            Returns:
                Dictionary with alignment results including RMSD and transformation
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_pdb": reference_pdb, "mobile_pdb": mobile_pdb}, 
                    ["reference_pdb", "mobile_pdb"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structures if not already loaded
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([reference_pdb, mobile_pdb])
                
                # Get structure data
                ref_data = processor.data[processor.data['pdb_id'] == reference_pdb].copy()
                mob_data = processor.data[processor.data['pdb_id'] == mobile_pdb].copy()
                
                if ref_data.empty:
                    return self.format_error(
                        f"Reference structure {reference_pdb} not found",
                        "Ensure the structure is loaded"
                    )
                
                if mob_data.empty:
                    return self.format_error(
                        f"Mobile structure {mobile_pdb} not found",
                        "Ensure the structure is loaded"
                    )
                
                # Apply chain selection if specified
                if chain_selection:
                    ref_data = ref_data[ref_data['auth_chain_id'] == chain_selection]
                    mob_data = mob_data[mob_data['auth_chain_id'] == chain_selection]
                    
                    if ref_data.empty or mob_data.empty:
                        return self.format_error(
                            f"Chain {chain_selection} not found in one or both structures",
                            "Check available chains with get_structure_chains"
                        )
                
                # Apply atom selection
                if atom_selection == "CA":
                    ref_coords = ref_data[ref_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    mob_coords = mob_data[mob_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                elif atom_selection == "backbone":
                    backbone_atoms = ['N', 'CA', 'C', 'O']
                    ref_coords = ref_data[ref_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    mob_coords = mob_data[mob_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                else:  # all atoms
                    ref_coords = ref_data[['x', 'y', 'z']].copy()
                    mob_coords = mob_data[['x', 'y', 'z']].copy()
                
                # Ensure numeric types
                for coord in ['x', 'y', 'z']:
                    ref_coords[coord] = pd.to_numeric(ref_coords[coord], errors='coerce')
                    mob_coords[coord] = pd.to_numeric(mob_coords[coord], errors='coerce')
                
                # Drop NaN values
                ref_coords = ref_coords.dropna()
                mob_coords = mob_coords.dropna()
                
                if ref_coords.empty or mob_coords.empty:
                    return self.format_error(
                        "No valid coordinates found after filtering",
                        "Check atom selection and data quality"
                    )
                
                # Perform alignment using struct_alignment
                from protos.processing.structure.struct_alignment import align_structures
                
                try:
                    aligned_coords, rotation, translation, alignment_path, rmsd = align_structures(
                        ref_coords, mob_coords, 
                        window_size=window_size, 
                        max_gap=max_gap
                    )
                    
                    # Format results
                    return self.format_success({
                        "reference_pdb": reference_pdb,
                        "mobile_pdb": mobile_pdb,
                        "rmsd": round(float(rmsd), 3),
                        "num_aligned_atoms": len(alignment_path[0]) if alignment_path else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection,
                        "rotation_matrix": rotation.tolist() if hasattr(rotation, 'tolist') else rotation,
                        "translation_vector": translation.tolist() if hasattr(translation, 'tolist') else translation,
                        "window_size": window_size,
                        "max_gap": max_gap
                    })
                    
                except Exception as e:
                    return self.format_error(
                        f"Alignment failed: {str(e)}",
                        "Check if structures have compatible atom sets"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_structure_rmsd_matrix(ctx, pdb_ids: List[str],
                                          atom_selection: str = "CA",
                                          chain_selection: Optional[str] = None,
                                          mode: str = "all_vs_all") -> Dict:
            """
            Calculate RMSD matrix between multiple structures.
            
            This tool performs pairwise structural alignments between multiple
            proteins and returns an RMSD matrix. Can operate in all-vs-all mode
            or one-vs-all mode.
            
            Args:
                pdb_ids: List of PDB IDs to compare
                atom_selection: Atom type to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align, or None for all
                mode: Comparison mode ("all_vs_all" or "one_vs_all")
                
            Returns:
                Dictionary with RMSD matrix and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_ids": pdb_ids}, 
                    ["pdb_ids"]
                ):
                    return error
                
                if len(pdb_ids) < 2:
                    return self.format_error(
                        "Need at least 2 structures",
                        "Provide multiple PDB IDs to compare"
                    )
                
                if mode not in ["all_vs_all", "one_vs_all"]:
                    return self.format_error(
                        f"Invalid mode: {mode}",
                        "Use 'all_vs_all' or 'one_vs_all'"
                    )
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load all structures
                processor.load_structures(pdb_ids)
                
                # Prepare structure data
                processed_structures = {}
                
                for pdb_id in pdb_ids:
                    pdb_data = processor.data[processor.data['pdb_id'] == pdb_id].copy()
                    
                    if pdb_data.empty:
                        continue
                    
                    # Apply chain selection
                    if chain_selection:
                        pdb_data = pdb_data[pdb_data['auth_chain_id'] == chain_selection]
                    
                    # Apply atom selection
                    if atom_selection == "CA":
                        coords = pdb_data[pdb_data['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    elif atom_selection == "backbone":
                        backbone_atoms = ['N', 'CA', 'C', 'O']
                        coords = pdb_data[pdb_data['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    else:
                        coords = pdb_data[['x', 'y', 'z']].copy()
                    
                    # Ensure numeric types
                    for coord in ['x', 'y', 'z']:
                        coords[coord] = pd.to_numeric(coords[coord], errors='coerce')
                    
                    coords = coords.dropna()
                    
                    if not coords.empty:
                        processed_structures[pdb_id] = {'df_norm': coords}
                
                if len(processed_structures) < 2:
                    return self.format_error(
                        "Not enough valid structures after filtering",
                        "Check atom selection and chain availability"
                    )
                
                # Calculate RMSD matrix
                from protos.processing.structure.struct_alignment import (
                    structure_comparison_ava, structure_comparison_1va
                )
                
                if mode == "all_vs_all":
                    rmsd_matrix, structure_ids = structure_comparison_ava(processed_structures)
                    
                    # Convert to dictionary format
                    rmsd_dict = {}
                    for i, id1 in enumerate(structure_ids):
                        rmsd_dict[id1] = {}
                        for j, id2 in enumerate(structure_ids):
                            rmsd_dict[id1][id2] = round(float(rmsd_matrix[i, j]), 3)
                    
                    # Calculate statistics
                    rmsd_values = []
                    for i in range(len(structure_ids)):
                        for j in range(i + 1, len(structure_ids)):
                            rmsd_values.append(rmsd_matrix[i, j])
                    
                    return self.format_success({
                        "mode": "all_vs_all",
                        "num_structures": len(structure_ids),
                        "structure_ids": structure_ids,
                        "rmsd_matrix": rmsd_dict,
                        "min_rmsd": round(float(min(rmsd_values)), 3) if rmsd_values else 0,
                        "max_rmsd": round(float(max(rmsd_values)), 3) if rmsd_values else 0,
                        "mean_rmsd": round(float(sum(rmsd_values) / len(rmsd_values)), 3) if rmsd_values else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection
                    })
                    
                else:  # one_vs_all
                    rmsd_list, compared_ids = structure_comparison_1va(processed_structures)
                    reference_id = list(processed_structures.keys())[0]
                    
                    # Create dictionary format
                    rmsd_dict = {reference_id: {}}
                    for i, comp_id in enumerate(compared_ids):
                        rmsd_dict[reference_id][comp_id] = round(float(rmsd_list[i]), 3)
                    
                    return self.format_success({
                        "mode": "one_vs_all",
                        "reference_structure": reference_id,
                        "compared_structures": compared_ids,
                        "rmsd_values": rmsd_dict,
                        "min_rmsd": round(float(min(rmsd_list)), 3) if rmsd_list else 0,
                        "max_rmsd": round(float(max(rmsd_list)), 3) if rmsd_list else 0,
                        "mean_rmsd": round(float(sum(rmsd_list) / len(rmsd_list)), 3) if rmsd_list else 0,
                        "atom_selection": atom_selection,
                        "chain_selection": chain_selection
                    })
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def superimpose_structures(ctx, reference_pdb: str, mobile_pdb: str,
                                 output_name: str,
                                 atom_selection: str = "CA",
                                 chain_selection: Optional[str] = None) -> Dict:
            """
            Superimpose one structure onto another and save the result.
            
            This tool aligns a mobile structure onto a reference structure and
            saves the transformed coordinates as a new entity.
            
            Args:
                reference_pdb: PDB ID of the reference structure
                mobile_pdb: PDB ID of the structure to superimpose
                output_name: Name for the superimposed structure entity
                atom_selection: Atoms to use for alignment ("CA", "backbone", "all")
                chain_selection: Specific chain to align, or None for all
                
            Returns:
                Dictionary with superposition results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_pdb": reference_pdb, "mobile_pdb": mobile_pdb, "output_name": output_name}, 
                    ["reference_pdb", "mobile_pdb", "output_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structures
                processor.load_structures([reference_pdb, mobile_pdb])
                
                # Get full structure data
                ref_data = processor.data[processor.data['pdb_id'] == reference_pdb].copy()
                mob_data = processor.data[processor.data['pdb_id'] == mobile_pdb].copy()
                
                if ref_data.empty or mob_data.empty:
                    return self.format_error(
                        "One or both structures not found",
                        "Ensure both structures are loaded"
                    )
                
                # Get alignment coordinates based on selection
                if chain_selection:
                    ref_align = ref_data[ref_data['auth_chain_id'] == chain_selection].copy()
                    mob_align = mob_data[mob_data['auth_chain_id'] == chain_selection].copy()
                else:
                    ref_align = ref_data.copy()
                    mob_align = mob_data.copy()
                
                if atom_selection == "CA":
                    ref_coords = ref_align[ref_align['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                    mob_coords = mob_align[mob_align['atom_name'] == 'CA'][['x', 'y', 'z']].copy()
                elif atom_selection == "backbone":
                    backbone_atoms = ['N', 'CA', 'C', 'O']
                    ref_coords = ref_align[ref_align['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                    mob_coords = mob_align[mob_align['atom_name'].isin(backbone_atoms)][['x', 'y', 'z']].copy()
                else:
                    ref_coords = ref_align[['x', 'y', 'z']].copy()
                    mob_coords = mob_align[['x', 'y', 'z']].copy()
                
                # Ensure numeric types
                for coord in ['x', 'y', 'z']:
                    ref_coords[coord] = pd.to_numeric(ref_coords[coord], errors='coerce')
                    mob_coords[coord] = pd.to_numeric(mob_coords[coord], errors='coerce')
                
                ref_coords = ref_coords.dropna()
                mob_coords = mob_coords.dropna()
                
                # Perform alignment
                from protos.processing.structure.struct_alignment import align_structures
                
                aligned_coords, rotation, translation, alignment_path, rmsd = align_structures(
                    ref_coords, mob_coords
                )
                
                # Apply transformation to ALL atoms of mobile structure
                import numpy as np
                
                # Get all mobile structure coordinates
                all_mob_coords = mob_data[['x', 'y', 'z']].copy()
                for coord in ['x', 'y', 'z']:
                    all_mob_coords[coord] = pd.to_numeric(all_mob_coords[coord], errors='coerce')
                
                # Apply rotation and translation
                coords_array = all_mob_coords.values
                transformed_coords = np.dot(coords_array, rotation) + translation
                
                # Update mobile structure data with transformed coordinates
                transformed_data = mob_data.copy()
                transformed_data[['x', 'y', 'z']] = transformed_coords
                transformed_data['pdb_id'] = output_name  # Update PDB ID
                
                # Save transformed structure
                processor.save_entity(output_name, transformed_data)
                
                return self.format_success({
                    "reference_pdb": reference_pdb,
                    "mobile_pdb": mobile_pdb,
                    "output_name": output_name,
                    "rmsd": round(float(rmsd), 3),
                    "num_aligned_atoms": len(alignment_path[0]) if alignment_path else 0,
                    "total_atoms_transformed": len(transformed_data),
                    "atom_selection": atom_selection,
                    "chain_selection": chain_selection,
                    "saved": True
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def compare_ligand_binding_sites(ctx, structures: List[Dict[str, str]],
                                       cutoff: float = 5.0,
                                       similarity_threshold: float = 0.5) -> Dict:
            """
            Compare binding sites across multiple protein-ligand complexes.
            
            This tool analyzes binding site conservation across structures, useful for:
            - Understanding binding mode conservation
            - Identifying key interaction residues
            - Comparing different ligands in the same pocket
            - Analyzing conformational changes upon ligand binding
            
            Args:
                structures: List of dicts with 'pdb_id', 'ligand_name', and optional 'chain_id'
                cutoff: Distance cutoff for binding site definition (Angstroms)
                similarity_threshold: Jaccard similarity threshold for grouping similar sites
                
            Returns:
                Dictionary with binding site comparison results including:
                - Pairwise binding site similarities
                - Conserved residues across all structures
                - Binding site clustering
                - Key differences between sites
            """
            try:
                # Validate parameters
                if not structures or len(structures) < 2:
                    return self.format_error(
                        "Need at least 2 structures to compare",
                        "Provide multiple structure-ligand pairs"
                    )
                
                for i, struct in enumerate(structures):
                    if 'pdb_id' not in struct or 'ligand_name' not in struct:
                        return self.format_error(
                            f"Structure {i} missing required fields",
                            "Each structure needs 'pdb_id' and 'ligand_name'"
                        )
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load all structures
                pdb_ids = [s['pdb_id'] for s in structures]
                processor.load_structures(pdb_ids)
                
                # Import analysis functions
                try:
                    from protos.analysis.structure_ligand_analysis import (
                        get_ligand_by_id, get_binding_site, 
                        compare_ligand_binding_sites as compare_sites
                    )
                except ImportError:
                    return self.format_error(
                        "Binding site comparison module not available",
                        "Ensure protos.analysis is installed"
                    )
                
                # Collect binding sites for each structure
                binding_sites = {}
                site_residues = {}
                
                for struct in structures:
                    pdb_id = struct['pdb_id']
                    ligand_name = struct['ligand_name']
                    chain_id = struct.get('chain_id')
                    
                    # Get ligand atoms
                    ligand_atoms = get_ligand_by_id(
                        processor, pdb_id, ligand_name, chain_id
                    )
                    
                    if ligand_atoms is None or ligand_atoms.empty:
                        return self.format_error(
                            f"Ligand {ligand_name} not found in {pdb_id}",
                            "Check ligand names and chain IDs"
                        )
                    
                    # Get binding site
                    binding_site = get_binding_site(
                        processor, pdb_id, ligand_atoms, cutoff
                    )
                    
                    key = f"{pdb_id}_{ligand_name}"
                    if chain_id:
                        key += f"_{chain_id}"
                    
                    binding_sites[key] = binding_site
                    
                    # Extract residue identifiers for comparison
                    if not binding_site['residues'].empty:
                        residues = binding_site['residues']
                        site_residues[key] = set(
                            f"{row['res_name']}{row['res_id']}" 
                            for _, row in residues.iterrows()
                        )
                    else:
                        site_residues[key] = set()
                
                # Perform pairwise comparisons
                comparisons = []
                site_keys = list(site_residues.keys())
                
                for i in range(len(site_keys)):
                    for j in range(i + 1, len(site_keys)):
                        key1, key2 = site_keys[i], site_keys[j]
                        
                        # Calculate Jaccard similarity
                        residues1 = site_residues[key1]
                        residues2 = site_residues[key2]
                        
                        if residues1 or residues2:
                            intersection = residues1 & residues2
                            union = residues1 | residues2
                            similarity = len(intersection) / len(union) if union else 0
                            
                            comparisons.append({
                                "site1": key1,
                                "site2": key2,
                                "similarity": round(similarity, 3),
                                "shared_residues": list(intersection),
                                "unique_to_site1": list(residues1 - residues2),
                                "unique_to_site2": list(residues2 - residues1)
                            })
                
                # Find conserved residues across all sites
                all_residues = list(site_residues.values())
                if all_residues:
                    conserved_residues = set.intersection(*all_residues) if all_residues else set()
                    variable_residues = set.union(*all_residues) - conserved_residues
                else:
                    conserved_residues = set()
                    variable_residues = set()
                
                # Group similar binding sites
                site_groups = []
                grouped = set()
                
                for i, key in enumerate(site_keys):
                    if key in grouped:
                        continue
                    
                    group = [key]
                    grouped.add(key)
                    
                    # Find all sites similar to this one
                    for comp in comparisons:
                        if comp['similarity'] >= similarity_threshold:
                            if comp['site1'] == key and comp['site2'] not in grouped:
                                group.append(comp['site2'])
                                grouped.add(comp['site2'])
                            elif comp['site2'] == key and comp['site1'] not in grouped:
                                group.append(comp['site1'])
                                grouped.add(comp['site1'])
                    
                    if len(group) > 1:
                        site_groups.append(group)
                
                # Calculate binding site statistics
                site_stats = {}
                for key, residues in site_residues.items():
                    site_stats[key] = {
                        "num_residues": len(residues),
                        "residue_list": sorted(list(residues))
                    }
                
                result = {
                    "num_structures": len(structures),
                    "cutoff": cutoff,
                    "site_statistics": site_stats,
                    "conserved_residues": sorted(list(conserved_residues)),
                    "variable_residues": sorted(list(variable_residues)),
                    "conservation_ratio": round(
                        len(conserved_residues) / len(conserved_residues | variable_residues), 3
                    ) if conserved_residues or variable_residues else 0,
                    "pairwise_comparisons": comparisons,
                    "similar_site_groups": site_groups,
                    "similarity_threshold": similarity_threshold
                }
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def extract_sequences_from_structure(ctx, pdb_id: str,
                                           chain_ids: Optional[List[str]] = None,
                                           save_as_fasta: Optional[str] = None) -> Dict:
            """
            Extract amino acid sequences from protein chains in a structure.
            
            This tool extracts sequences from specified chains (or all chains) in a 
            protein structure and optionally saves them as a FASTA file using the 
            sequence processor.
            
            Args:
                pdb_id: PDB ID of the structure
                chain_ids: List of chain IDs to extract (None for all chains)
                save_as_fasta: Name to save sequences as FASTA file (without extension)
                
            Returns:
                Dictionary with extracted sequences and metadata
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_id": pdb_id}, 
                    ["pdb_id"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load structure if not already loaded
                if not hasattr(processor, 'data') or processor.data is None:
                    processor.load_structures([pdb_id])
                elif pdb_id not in processor.data['pdb_id'].unique():
                    processor.load_structures([pdb_id])
                
                # Get structure data
                structure_data = processor.data[processor.data['pdb_id'] == pdb_id]
                
                if structure_data.empty:
                    return self.format_error(
                        f"Structure {pdb_id} not found",
                        "Ensure the structure is loaded"
                    )
                
                # Get available chains
                available_chains = structure_data['auth_chain_id'].unique().tolist()
                
                # Use specified chains or all chains
                if chain_ids:
                    chains_to_extract = [c for c in chain_ids if c in available_chains]
                    if not chains_to_extract:
                        return self.format_error(
                            f"None of the specified chains {chain_ids} found in structure",
                            f"Available chains: {available_chains}"
                        )
                else:
                    chains_to_extract = available_chains
                
                # Extract sequences using processor's get_seq_dict method
                processor.pdb_ids = [pdb_id]  # Set current PDB ID
                seq_dict = processor.get_seq_dict()
                
                # Filter to requested chains
                sequences = {}
                for key, seq in seq_dict.items():
                    pdb, chain = key.split('_')
                    if pdb == pdb_id and chain in chains_to_extract:
                        sequences[key] = seq
                
                result = {
                    "pdb_id": pdb_id,
                    "chains_extracted": list(set(k.split('_')[1] for k in sequences.keys())),
                    "sequences": sequences,
                    "sequence_count": len(sequences)
                }
                
                # Save as FASTA if requested
                if save_as_fasta and sequences:
                    try:
                        # Get sequence processor
                        seq_processor = self.get_processor("sequence")
                        
                        # Save sequences using sequence processor
                        seq_processor.save_sequences(sequences, save_as_fasta)
                        
                        result["saved_as"] = f"{save_as_fasta}.fasta"
                        result["message"] = f"Sequences saved to {save_as_fasta}.fasta"
                    except Exception as e:
                        result["save_error"] = str(e)
                        result["message"] = "Sequences extracted but failed to save as FASTA"
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def extract_all_chains_from_dataset(ctx, dataset_name: str,
                                          save_as_fasta: Optional[str] = None,
                                          chain_filter: Optional[List[str]] = None) -> Dict:
            """
            Extract sequences from all structures in a dataset.
            
            This tool processes an entire structure dataset, extracting sequences
            from all chains (or filtered chains) and optionally saving them as
            a FASTA file.
            
            Args:
                dataset_name: Name of the structure dataset
                save_as_fasta: Name to save all sequences as FASTA file
                chain_filter: List of chain IDs to include (e.g., ['A', 'B'])
                
            Returns:
                Dictionary with extraction results and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get structure processor
                processor = self.get_processor("structure")
                
                # Load dataset
                dataset = processor.load_dataset(dataset_name)
                if dataset is None:
                    return self.format_error(
                        f"Dataset '{dataset_name}' not found",
                        "Check dataset name and ensure it exists"
                    )
                
                # Get structure list from dataset
                structures = dataset.content if hasattr(dataset, 'content') else dataset.get('content', [])
                
                if not structures:
                    return self.format_error(
                        f"Dataset '{dataset_name}' is empty",
                        "Dataset contains no structures"
                    )
                
                # Extract sequences from all structures
                all_sequences = {}
                failed_structures = []
                chain_stats = {}
                
                for pdb_id in structures:
                    try:
                        # Load structure
                        structure = processor.load_structure(pdb_id)
                        if structure is None:
                            raise ValueError(f"Could not load structure {pdb_id}")
                            
                        # Set data temporarily for get_seq_dict
                        old_data = processor.data
                        processor.data = structure
                        processor.pdb_ids = [pdb_id]
                        
                        # Get sequences for this structure
                        seq_dict = processor.get_seq_dict()
                        
                        # Restore original data
                        processor.data = old_data
                        
                        # Filter chains if requested
                        for key, seq in seq_dict.items():
                            pdb, chain = key.split('_')
                            if chain_filter is None or chain in chain_filter:
                                all_sequences[key] = seq
                                
                                # Track statistics
                                if chain not in chain_stats:
                                    chain_stats[chain] = 0
                                chain_stats[chain] += 1
                                
                    except Exception as e:
                        failed_structures.append({
                            "pdb_id": pdb_id,
                            "error": str(e)
                        })
                
                result = {
                    "dataset_name": dataset_name,
                    "total_structures": len(structures),
                    "successful_structures": len(structures) - len(failed_structures),
                    "total_sequences": len(all_sequences),
                    "chain_statistics": chain_stats,
                    "failed_structures": failed_structures
                }
                
                # Save as FASTA if requested
                if save_as_fasta and all_sequences:
                    try:
                        # Get sequence processor
                        seq_processor = self.get_processor("sequence")
                        
                        # Save all sequences
                        seq_processor.save_sequences(all_sequences, save_as_fasta)
                        
                        # Also create a sequence dataset
                        seq_processor.create_dataset(
                            save_as_fasta,
                            list(all_sequences.keys()),
                            {
                                "source": f"structure_dataset:{dataset_name}",
                                "chain_filter": chain_filter,
                                "extraction_date": datetime.now().isoformat()
                            }
                        )
                        
                        result["saved_as"] = f"{save_as_fasta}.fasta"
                        result["sequence_dataset"] = save_as_fasta
                        result["message"] = f"Sequences saved to {save_as_fasta}.fasta and dataset created"
                    except Exception as e:
                        result["save_error"] = str(e)
                        result["message"] = "Sequences extracted but failed to save"
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        @server.tool()
        def get_sequences_and_save_fasta(ctx, pdb_ids: List[str],
                                        fasta_name: str,
                                        use_chain_dict: bool = True) -> Dict:
            """
            Extract sequences from structures using get_seq_dict/get_chain_dict and save as FASTA.
            
            This is a simple tool that loads structures, calls get_seq_dict() or get_chain_dict()
            on the structure processor, and saves the results as a FASTA file using the 
            sequence processor.
            
            Args:
                pdb_ids: List of PDB IDs to process
                fasta_name: Name for the output FASTA file (without extension)
                use_chain_dict: If True, use get_chain_dict(); if False, use get_seq_dict()
                
            Returns:
                Dictionary with extraction results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"pdb_ids": pdb_ids, "fasta_name": fasta_name}, 
                    ["pdb_ids", "fasta_name"]
                ):
                    return error
                
                if not pdb_ids:
                    return self.format_error(
                        "No PDB IDs provided",
                        "Provide at least one PDB ID"
                    )
                
                # Get structure processor
                struct_processor = self.get_processor("structure")
                
                # Load all structures
                struct_processor.load_structures(pdb_ids)
                
                # Set the PDB IDs for processing
                struct_processor.pdb_ids = pdb_ids
                
                # Get sequences using the appropriate method
                if use_chain_dict:
                    sequences = struct_processor.get_chain_dict()
                else:
                    sequences = struct_processor.get_seq_dict()
                
                if not sequences:
                    return self.format_error(
                        "No sequences extracted",
                        "Check that structures contain protein chains"
                    )
                
                # Get sequence processor and save as FASTA
                seq_processor = self.get_processor("sequence")
                seq_processor.save_sequences(sequences, fasta_name)
                
                # Create a sequence dataset
                seq_processor.create_dataset(
                    fasta_name,
                    list(sequences.keys()),
                    {
                        "source_structures": pdb_ids,
                        "extraction_method": "get_chain_dict" if use_chain_dict else "get_seq_dict",
                        "total_sequences": len(sequences)
                    }
                )
                
                result = {
                    "pdb_ids_processed": pdb_ids,
                    "total_sequences": len(sequences),
                    "fasta_file": f"{fasta_name}.fasta",
                    "sequence_dataset": fasta_name,
                    "method_used": "get_chain_dict" if use_chain_dict else "get_seq_dict",
                    "sequences_extracted": list(sequences.keys())[:10] + (["..."] if len(sequences) > 10 else [])
                }
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
