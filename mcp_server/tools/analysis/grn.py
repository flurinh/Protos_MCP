"""
GRN (Generic Residue Numbering) analysis tools leveraging Protos' GRNProcessor.

These tools provide GRN assignment capabilities including reference table loading,
sequence alignment, GRN assignment to new sequences, and coverage analysis.
"""

from typing import Dict, List, Optional, Any, Tuple
import json
import logging

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, EntityNotFoundError

logger = logging.getLogger(__name__)


class GRNAnalysisTools(BaseTool):
    """Tools for GRN analysis and assignment."""
    
    def register(self, server):
        """Register GRN analysis tools with the server."""
        
        @server.tool()
        def load_grn_reference_table(ctx, reference_name: str) -> Dict:
            """
            Load a GRN reference table for sequence annotation.
            
            Available reference tables include:
            - gpcrdb_ref: GPCR reference numbering from GPCRdb
            - Additional reference tables can be added to the reference data
            
            Args:
                reference_name: Name of the reference table (without .csv extension)
                
            Returns:
                Dictionary with reference table information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_name": reference_name}, 
                    ["reference_name"]
                ):
                    return error
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Load reference table
                ref_data = processor.load_reference_table(reference_name)
                
                if ref_data is None or ref_data.empty:
                    return self.format_error(
                        f"Reference table '{reference_name}' not found",
                        "Check available reference tables in the reference data directory"
                    )
                
                # Get some statistics
                num_sequences = len(ref_data)
                num_positions = len(ref_data.columns)
                
                # Sample positions (first 10 GRN positions)
                sample_positions = list(ref_data.columns[:10])
                
                return self.format_success({
                    "reference_name": reference_name,
                    "num_sequences": num_sequences,
                    "num_positions": num_positions,
                    "sample_positions": sample_positions,
                    "sequence_ids": ref_data.index.tolist()[:20]  # First 20 IDs
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def load_grn_table(ctx, table_name: str) -> Dict:
            """
            Load any GRN table (not just reference tables).
            
            This loads user-created GRN tables from the tables/ directory.
            
            Args:
                table_name: Name of the GRN table (without .csv extension)
                
            Returns:
                Dictionary with table information and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"table_name": table_name},
                    ["table_name"]
                ):
                    return error

                # Get GRN processor
                processor = self.get_processor("grn")

                # Load GRN table using the correct method
                try:
                    table_df = processor.load_table(table_name)
                except Exception as e:
                    return self.format_error(
                        f"Failed to load GRN table '{table_name}': {str(e)}",
                        "Check that the table exists. Use list_grn_tables to see available tables"
                    )

                if table_df is None or table_df.empty:
                    return self.format_error(
                        f"GRN table '{table_name}' is empty or not found",
                        "The table may not exist. Use list_grn_tables to see available tables"
                    )

                # Get statistics from the loaded DataFrame
                num_sequences = len(table_df)
                num_positions = len(table_df.columns)

                # Get coverage statistics (limit to first 10 for memory efficiency)
                coverage_stats = {}
                for seq_id in table_df.index[:10]:
                    row = table_df.loc[seq_id]
                    assigned = (row != '-').sum()
                    coverage_stats[seq_id] = round(assigned / num_positions, 3) if num_positions > 0 else 0.0
                
                # Sample positions (memory-efficient: only first 20)
                sample_positions = list(table_df.columns[:20])

                # Calculate average coverage efficiently
                avg_coverage = 0.0
                if num_sequences > 0 and num_positions > 0:
                    total_assigned = (table_df != '-').sum().sum()
                    avg_coverage = round(total_assigned / (num_sequences * num_positions), 3)

                return self.format_success({
                    "table_name": table_name,
                    "num_sequences": num_sequences,
                    "num_positions": num_positions,
                    "sequence_ids": list(table_df.index[:20]),
                    "sample_positions": sample_positions,
                    "sample_coverage": coverage_stats,
                    "avg_coverage": avg_coverage
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def list_grn_tables(ctx) -> Dict:
            """
            List all available GRN tables.
            
            Returns both reference tables and user-created tables.
            
            Returns:
                Dictionary with lists of available tables
            """
            try:
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # List all datasets (which are tables for GRN)
                all_tables = processor.list_datasets()
                
                # Try to identify reference tables
                reference_tables = []
                user_tables = []
                
                # Check for common reference table patterns
                for table in all_tables:
                    if table.endswith('_ref') or table in ['gpcrdb_ref', 'mo_ref']:
                        reference_tables.append(table)
                    else:
                        user_tables.append(table)
                
                return self.format_success({
                    "total_tables": len(all_tables),
                    "reference_tables": reference_tables,
                    "user_tables": user_tables,
                    "all_tables": all_tables
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def apply_grn_interval(ctx, table_name: str, 
                             grn_positions: List[str],
                             save_as: Optional[str] = None) -> Dict:
            """
            Filter a GRN table to include only specific GRN positions.
            
            This is useful for focusing on specific regions (e.g., only TM helices).
            
            Args:
                table_name: Name of the GRN table to filter
                grn_positions: List of GRN positions to keep (e.g., ["1.50", "2.50", "3.50"])
                save_as: Optional name to save filtered table
                
            Returns:
                Dictionary with filtered table information
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"table_name": table_name, "grn_positions": grn_positions}, 
                    ["table_name", "grn_positions"]
                ):
                    return error
                
                if not grn_positions:
                    return self.format_error(
                        "No GRN positions provided",
                        "Provide at least one GRN position to filter"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")

                # Load table using correct method
                table_df = processor.load_table(table_name)
                if table_df is None or table_df.empty:
                    return self.format_error(
                        f"GRN table '{table_name}' not found or empty",
                        "Check that the table exists using list_grn_tables"
                    )

                original_positions = len(table_df.columns)

                # Filter to keep only specified GRN positions
                valid_positions = [pos for pos in grn_positions if pos in table_df.columns]
                if not valid_positions:
                    return self.format_error(
                        "None of the specified GRN positions exist in the table",
                        f"Available positions: {list(table_df.columns[:20])}..."
                    )

                filtered_df = table_df[valid_positions]
                filtered_positions = len(filtered_df.columns)

                # Save if requested
                if save_as:
                    processor.record_table(save_as, filtered_df)

                # Get coverage after filtering (limit to first 10 for efficiency)
                coverage_stats = {}
                for seq_id in filtered_df.index[:10]:
                    row = filtered_df.loc[seq_id]
                    assigned = (row != '-').sum()
                    coverage_stats[seq_id] = round(assigned / filtered_positions, 3) if filtered_positions > 0 else 0

                result = {
                    "original_table": table_name,
                    "original_positions": original_positions,
                    "filtered_positions": filtered_positions,
                    "positions_kept": list(filtered_df.columns[:50]),  # Limit output
                    "positions_removed": original_positions - filtered_positions,
                    "sample_coverage": coverage_stats
                }

                if save_as:
                    result["saved_as"] = save_as

                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_grn_table_stats(ctx, table_name: str) -> Dict:
            """
            Get detailed statistics about a GRN table.
            
            Analyzes coverage, conservation, and missing data patterns.
            
            Args:
                table_name: Name of the GRN table to analyze
                
            Returns:
                Dictionary with comprehensive table statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"table_name": table_name}, 
                    ["table_name"]
                ):
                    return error
                
                # Get GRN processor
                processor = self.get_processor("grn")

                # Load table using correct method
                table_df = processor.load_table(table_name)

                if table_df is None or table_df.empty:
                    return self.format_error(
                        f"GRN table '{table_name}' is empty or not found",
                        "Cannot calculate statistics for empty table"
                    )

                # Basic stats
                num_sequences = len(table_df)
                num_positions = len(table_df.columns)

                # Coverage by sequence
                sequence_coverage = table_df.apply(
                    lambda row: (row != '-').sum() / len(row) if len(row) > 0 else 0, axis=1
                )

                # Coverage by position
                position_coverage = table_df.apply(
                    lambda col: (col != '-').sum() / len(col) if len(col) > 0 else 0, axis=0
                )
                
                # Conservation analysis (limit to prevent memory bloat)
                import numpy as np
                highly_conserved = []
                variable_positions = []
                missing_positions = []

                for pos in table_df.columns:
                    col = table_df[pos]
                    non_gap = col[col != '-']

                    if len(non_gap) == 0:
                        missing_positions.append(pos)
                    else:
                        # Calculate conservation
                        value_counts = non_gap.value_counts()
                        most_common = value_counts.iloc[0]
                        conservation = most_common / len(non_gap)

                        if conservation >= 0.9 and len(highly_conserved) < 50:
                            highly_conserved.append({
                                "position": pos,
                                "residue": value_counts.index[0],
                                "conservation": round(conservation, 3)
                            })
                        elif conservation <= 0.5 and len(variable_positions) < 50:
                            variable_positions.append({
                                "position": pos,
                                "entropy": round(-sum(
                                    (count/len(non_gap)) * np.log2(count/len(non_gap))
                                    for count in value_counts
                                ), 3)
                            })
                
                return self.format_success({
                    "table_name": table_name,
                    "num_sequences": num_sequences,
                    "num_positions": num_positions,
                    "coverage_stats": {
                        "mean_sequence_coverage": round(sequence_coverage.mean(), 3),
                        "min_sequence_coverage": round(sequence_coverage.min(), 3),
                        "max_sequence_coverage": round(sequence_coverage.max(), 3),
                        "mean_position_coverage": round(position_coverage.mean(), 3),
                        "fully_covered_positions": int((position_coverage == 1.0).sum()),
                        "empty_positions": len(missing_positions)
                    },
                    "conservation_stats": {
                        "highly_conserved_count": len(highly_conserved),
                        "highly_conserved_positions": highly_conserved[:10],  # Top 10
                        "variable_positions_count": len(variable_positions),
                        "variable_positions": variable_positions[:10]  # Top 10
                    },
                    "best_covered_sequences": sequence_coverage.nlargest(10).to_dict(),
                    "worst_covered_sequences": sequence_coverage.nsmallest(10).to_dict()
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def add_grn_annotation(ctx, table_name: str,
                             sequence_id: str,
                             grn_positions: Dict[str, str]) -> Dict:
            """
            Add or update GRN annotation for a single sequence.
            
            Args:
                table_name: Name of the GRN table
                sequence_id: ID of the sequence to annotate
                grn_positions: Dictionary mapping GRN positions to residues
                              e.g., {"1.50": "R", "2.50": "L", "3.50": "D"}
                
            Returns:
                Dictionary with update status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"table_name": table_name, "sequence_id": sequence_id, "grn_positions": grn_positions}, 
                    ["table_name", "sequence_id", "grn_positions"]
                ):
                    return error
                
                if not grn_positions:
                    return self.format_error(
                        "No GRN positions provided",
                        "Provide at least one GRN position-residue mapping"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")

                # Load table using correct method
                import pandas as pd
                table_df = processor.load_table(table_name)
                if table_df is None:
                    table_df = pd.DataFrame()

                # Track whether this is a new or updated entry
                is_update = sequence_id in table_df.index

                # If sequence exists, get current data
                if is_update:
                    current_row = table_df.loc[sequence_id].to_dict()
                else:
                    # Initialize with gaps for all columns
                    current_row = {col: '-' for col in table_df.columns}

                # Update with new positions
                positions_updated = 0
                new_positions = []

                for grn_pos, residue in grn_positions.items():
                    if grn_pos in table_df.columns:
                        current_row[grn_pos] = residue
                        positions_updated += 1
                    else:
                        new_positions.append(grn_pos)

                # Convert to Series and update the table
                row_data = pd.Series(current_row, name=sequence_id)
                table_df.loc[sequence_id] = row_data

                # Save the updated table using record_table
                processor.record_table(table_name, table_df)

                result = {
                    "table_name": table_name,
                    "sequence_id": sequence_id,
                    "positions_updated": positions_updated,
                    "total_positions": len(grn_positions),
                    "status": "updated" if is_update else "created"
                }
                
                if new_positions:
                    result["new_positions_not_in_table"] = new_positions
                    result["suggestion"] = "Use apply_grn_interval to add new positions to the table structure"
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_extract_sequences_from_dataset(ctx, dataset_name: str,
                                         processor_type: str = "structure",
                                         chain_selection: Optional[str] = None) -> Dict:
            """
            Extract sequences from all entities in a dataset.
            
            This tool loads entities from storage rather than requiring sequences
            as input. Works with both structure and sequence datasets.
            
            Args:
                dataset_name: Name of the dataset
                processor_type: Type of processor containing the dataset
                chain_selection: For structures, which chain to extract (e.g., "A")
                
            Returns:
                Dictionary with entity IDs and their sequences
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get appropriate processor
                processor = self.get_processor(processor_type)
                
                # Load dataset
                try:
                    dataset = processor.load_dataset(dataset_name)
                    entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset: {str(e)}",
                        f"Ensure dataset exists in {processor_type} processor"
                    )
                
                extracted_sequences = {}
                failed_extractions = []
                
                if processor_type == "structure":
                    # Extract from structures
                    for entity in entities:
                        try:
                            processor.load_structures([entity])
                            
                            if chain_selection:
                                seq = processor.get_sequence(entity, chain_selection)
                                if seq:
                                    extracted_sequences[f"{entity}_{chain_selection}"] = seq
                            else:
                                # Get all chains
                                all_seqs = processor.get_all_sequences()
                                for chain_id, seq in all_seqs.items():
                                    if chain_id.startswith(f"{entity}_"):
                                        extracted_sequences[chain_id] = seq
                                        
                        except Exception as e:
                            failed_extractions.append({"entity": entity, "error": str(e)})
                            
                elif processor_type == "sequence":
                    # Load from sequence processor
                    for entity in entities:
                        try:
                            seq_data = processor.load_entity(entity)
                            if isinstance(seq_data, dict):
                                # Multi-sequence file
                                for seq_id, seq in seq_data.items():
                                    extracted_sequences[seq_id] = seq
                            else:
                                extracted_sequences[entity] = str(seq_data)
                        except Exception as e:
                            failed_extractions.append({"entity": entity, "error": str(e)})
                
                result = {
                    "dataset": dataset_name,
                    "processor_type": processor_type,
                    "num_entities": len(entities),
                    "num_sequences": len(extracted_sequences),
                    "sequence_ids": list(extracted_sequences.keys())
                }
                
                if chain_selection:
                    result["chain_selection"] = chain_selection
                
                if failed_extractions:
                    result["failed_extractions"] = failed_extractions
                
                # Store sequences temporarily for next steps
                self._temp_sequences = extracted_sequences
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_align_dataset_to_reference(ctx, dataset_name: str,
                                     reference_name: str,
                                     min_identity: float = 0.25,
                                     alignment_method: str = "mmseqs2") -> Dict:
            """
            Align all sequences in a dataset to a GRN reference table.
            
            This tool uses dataset and reference names rather than requiring
            sequences to be passed as parameters.
            
            Args:
                dataset_name: Name of dataset containing query sequences
                reference_name: Name of GRN reference table
                min_identity: Minimum sequence identity threshold
                alignment_method: Method to use (mmseqs2 or blosum62)
                
            Returns:
                Dictionary with alignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "reference_name": reference_name}, 
                    ["dataset_name", "reference_name"]
                ):
                    return error
                
                # Get processors
                grn_processor = self.get_processor("grn")
                seq_processor = self.get_processor("sequence")
                
                # Load reference table
                grn_processor.load_reference_table(reference_name)
                ref_sequences = grn_processor.get_seq_dict()
                
                if not ref_sequences:
                    return self.format_error(
                        f"No sequences found in reference '{reference_name}'",
                        "Check if reference table loaded correctly"
                    )
                
                # Load query sequences from dataset
                query_sequences = {}
                
                # First check if we have sequences from previous extraction
                if hasattr(self, '_temp_sequences') and self._temp_sequences:
                    query_sequences = self._temp_sequences
                else:
                    # Load from dataset
                    try:
                        dataset = seq_processor.load_dataset(dataset_name)
                        entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                        
                        for entity in entities:
                            seq_data = seq_processor.load_entity(entity)
                            if isinstance(seq_data, dict):
                                query_sequences.update(seq_data)
                            else:
                                query_sequences[entity] = str(seq_data)
                    except:
                        # Try structure processor
                        struct_processor = self.get_processor("structure")
                        dataset = struct_processor.load_dataset(dataset_name)
                        entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                        
                        for entity in entities:
                            struct_processor.load_structures([entity])
                            all_seqs = struct_processor.get_all_sequences()
                            query_sequences.update(all_seqs)
                
                if not query_sequences:
                    return self.format_error(
                        "No sequences found in dataset",
                        "Ensure dataset contains valid sequence data"
                    )
                
                # Perform alignment
                if alignment_method == "mmseqs2":
                    try:
                        from protos.processing.sequence.seq_alignment import mmseqs2_align2
                        alignment_df = mmseqs2_align2(query_sequences, ref_sequences)
                        
                        # Filter by identity
                        filtered_alignments = alignment_df[alignment_df['sequence_identity'] >= min_identity]
                        alignment_results = filtered_alignments.to_dict('records')
                        
                    except ImportError:
                        return self.format_error(
                            "MMseqs2 not available",
                            "Install MMseqs2 or use 'blosum62' alignment method"
                        )
                else:
                    # Use pairwise BLOSUM62 alignment
                    alignment_results = []
                    from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62
                    
                    aligner = init_aligner()
                    for query_id, query_seq in query_sequences.items():
                        best_match = None
                        best_identity = 0
                        
                        for ref_id, ref_seq in ref_sequences.items():
                            alignment = align_blosum62(query_seq, ref_seq, aligner)
                            # Calculate identity
                            matches = sum(1 for a, b in zip(alignment.seqA, alignment.seqB) if a == b and a != '-')
                            identity = matches / len([a for a in alignment.seqA if a != '-']) if alignment.seqA else 0
                            
                            if identity >= min_identity and identity > best_identity:
                                best_match = {
                                    'query_id': query_id,
                                    'target_id': ref_id,
                                    'sequence_identity': identity,
                                    'alignment_length': len(alignment.seqA),
                                    'score': alignment.score
                                }
                                best_identity = identity
                        
                        if best_match:
                            alignment_results.append(best_match)
                
                # Format results
                best_matches = {}
                for result in alignment_results:
                    query_id = result['query_id']
                    if query_id not in best_matches or result['sequence_identity'] > best_matches[query_id]['sequence_identity']:
                        best_matches[query_id] = result
                
                # Store alignments for next step
                self._temp_alignments = best_matches
                
                return self.format_success({
                    "dataset": dataset_name,
                    "reference": reference_name,
                    "num_queries": len(query_sequences),
                    "num_aligned": len(best_matches),
                    "alignment_method": alignment_method,
                    "min_identity": min_identity,
                    "aligned_sequences": list(best_matches.keys()),
                    "avg_identity": round(
                        sum(m['sequence_identity'] for m in best_matches.values()) / len(best_matches), 3
                    ) if best_matches else 0
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def assign_grn_to_dataset(ctx, dataset_name: str,
                                reference_name: str,
                                protein_family: str = "gpcr_a",
                                output_name: Optional[str] = None) -> Dict:
            """
            Assign GRN positions to all sequences in a dataset.
            
            This combines alignment and GRN assignment in one step, using
            dataset names rather than requiring sequence data.
            
            Args:
                dataset_name: Dataset containing sequences to annotate
                reference_name: GRN reference table to use
                protein_family: Protein family for GRN configuration
                output_name: Name for output GRN table (defaults to dataset_name + "_grn")
                
            Returns:
                Dictionary with GRN assignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "reference_name": reference_name}, 
                    ["dataset_name", "reference_name"]
                ):
                    return error
                
                # Use stored alignments if available, otherwise align first
                if hasattr(self, '_temp_alignments') and self._temp_alignments:
                    best_matches = self._temp_alignments
                else:
                    # Perform alignment
                    align_result = grn_align_dataset_to_reference(
                        ctx, dataset_name, reference_name, 
                        min_identity=0.25, alignment_method="mmseqs2"
                    )
                    
                    if not align_result["success"]:
                        return align_result
                    
                    # Extract alignments from previous step
                    best_matches = self._temp_alignments
                
                if not best_matches:
                    return self.format_error(
                        "No sequences could be aligned",
                        "Check sequence identity threshold and reference table"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Load reference table
                processor.load_reference_table(reference_name)
                
                # Get GRN configuration
                from protos.processing.grn.grn_utils import GRNConfigManager
                config_manager = GRNConfigManager(paths=processor.paths)
                grn_config = config_manager.get_config(protein_family=protein_family, strict=False)
                
                # Process each alignment
                grn_data = {}
                metadata = {}
                
                for query_id, alignment_info in best_matches.items():
                    ref_id = alignment_info['target_id']
                    
                    # Get reference GRN annotation
                    ref_row = processor.data.loc[ref_id]
                    
                    # Create GRN assignment
                    # Note: This is simplified - full implementation would properly map through alignment
                    grn_positions = {}
                    for grn_pos, residue in ref_row.items():
                        if residue != '-':
                            grn_positions[grn_pos] = residue
                    
                    grn_data[query_id] = grn_positions
                    metadata[query_id] = {
                        'reference_id': ref_id,
                        'sequence_identity': alignment_info['sequence_identity']
                    }
                
                # Create DataFrame
                import pandas as pd
                grn_df = pd.DataFrame.from_dict(grn_data, orient='index')
                grn_df = grn_df.fillna('-')
                
                # Sort columns by GRN position
                sorted_cols = sorted(grn_df.columns, key=lambda x: (
                    float(x.split('.')[0]), 
                    float(x.split('.')[1]) if '.' in x else 0
                ))
                grn_df = grn_df[sorted_cols]
                
                # Save GRN table
                output_name = output_name or f"{dataset_name}_grn"
                processor.save_grn_table(output_name)
                
                # Calculate coverage statistics
                coverage_stats = {}
                for seq_id in grn_df.index:
                    assigned = (grn_df.loc[seq_id] != '-').sum()
                    total = len(grn_df.columns)
                    coverage_stats[seq_id] = round(assigned / total, 3)
                
                return self.format_success({
                    "dataset": dataset_name,
                    "reference": reference_name,
                    "protein_family": protein_family,
                    "output_table": output_name,
                    "num_sequences": len(grn_df),
                    "num_positions": len(grn_df.columns),
                    "sequences_annotated": list(grn_df.index),
                    "avg_coverage": round(sum(coverage_stats.values()) / len(coverage_stats), 3),
                    "coverage_by_sequence": coverage_stats
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_grn_for_entities(ctx, entity_list: List[str],
                               grn_table: str,
                               positions: Optional[List[str]] = None) -> Dict:
            """
            Get GRN annotations for specific entities from a GRN table.
            
            Args:
                entity_list: List of entity IDs to query
                grn_table: Name of the GRN table to query
                positions: Optional list of specific GRN positions to retrieve
                
            Returns:
                Dictionary with GRN annotations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity_list": entity_list, "grn_table": grn_table}, 
                    ["entity_list", "grn_table"]
                ):
                    return error
                
                if not entity_list:
                    return self.format_error(
                        "Empty entity list",
                        "Provide at least one entity to query"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")

                # Load GRN table using correct method
                try:
                    table_df = processor.load_table(grn_table)
                    if table_df is None or table_df.empty:
                        return self.format_error(
                            f"GRN table '{grn_table}' not found or empty",
                            "Check that the GRN table exists"
                        )
                except Exception as e:
                    return self.format_error(
                        f"Failed to load GRN table: {str(e)}",
                        "Check that the GRN table exists"
                    )

                # Count found/missing entities - don't return full annotation data
                found_entities = []
                missing_entities = []
                coverage_summary = {}

                for entity in entity_list:
                    if entity in table_df.index:
                        found_entities.append(entity)
                        # Calculate coverage for this entity
                        row = table_df.loc[entity]
                        assigned = (row != '-').sum()
                        total = len(row)
                        coverage_summary[entity] = round(assigned / total, 3) if total > 0 else 0
                    else:
                        missing_entities.append(entity)

                result = {
                    "grn_table": grn_table,
                    "num_queried": len(entity_list),
                    "num_found": len(found_entities),
                    "found_entities": found_entities[:20],  # Limit list
                    "coverage_summary": coverage_summary,
                    "note": "GRN annotations available in Protos context. Use processor methods for full data.",
                }

                if positions:
                    result["positions_requested"] = positions[:20]

                if missing_entities:
                    result["missing_entities"] = missing_entities[:20]

                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_compare_conservation(ctx, grn_table: str,
                                   entity_group1: List[str],
                                   entity_group2: List[str],
                                   min_conservation: float = 0.8) -> Dict:
            """
            Compare GRN conservation between two groups of entities.
            
            Args:
                grn_table: Name of the GRN table
                entity_group1: First group of entity IDs
                entity_group2: Second group of entity IDs
                min_conservation: Minimum conservation threshold
                
            Returns:
                Dictionary with conservation comparison
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"grn_table": grn_table, "entity_group1": entity_group1, "entity_group2": entity_group2}, 
                    ["grn_table", "entity_group1", "entity_group2"]
                ):
                    return error
                
                if not entity_group1 or not entity_group2:
                    return self.format_error(
                        "Empty entity group",
                        "Both groups must contain at least one entity"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Load GRN table
                processor.load_grn_table(grn_table)
                
                # Get GRN data for both groups
                group1_data = processor.data.loc[processor.data.index.intersection(entity_group1)]
                group2_data = processor.data.loc[processor.data.index.intersection(entity_group2)]
                
                if group1_data.empty or group2_data.empty:
                    return self.format_error(
                        "One or both groups have no data in GRN table",
                        "Check entity names match those in the table"
                    )
                
                # Calculate conservation for each position
                position_conservation = {}
                conserved_in_group1 = []
                conserved_in_group2 = []
                conserved_in_both = []
                different_between_groups = []
                
                for pos in processor.data.columns:
                    # Group 1 conservation
                    group1_residues = group1_data[pos].value_counts()
                    group1_residues = group1_residues[group1_residues.index != '-']
                    if not group1_residues.empty:
                        group1_cons = group1_residues.iloc[0] / len(group1_data)
                        group1_consensus = group1_residues.index[0]
                    else:
                        group1_cons = 0
                        group1_consensus = '-'
                    
                    # Group 2 conservation
                    group2_residues = group2_data[pos].value_counts()
                    group2_residues = group2_residues[group2_residues.index != '-']
                    if not group2_residues.empty:
                        group2_cons = group2_residues.iloc[0] / len(group2_data)
                        group2_consensus = group2_residues.index[0]
                    else:
                        group2_cons = 0
                        group2_consensus = '-'
                    
                    position_conservation[pos] = {
                        'group1_conservation': round(group1_cons, 3),
                        'group1_consensus': group1_consensus,
                        'group2_conservation': round(group2_cons, 3),
                        'group2_consensus': group2_consensus
                    }
                    
                    # Categorize positions
                    if group1_cons >= min_conservation:
                        conserved_in_group1.append(pos)
                    if group2_cons >= min_conservation:
                        conserved_in_group2.append(pos)
                    if group1_cons >= min_conservation and group2_cons >= min_conservation:
                        if group1_consensus == group2_consensus:
                            conserved_in_both.append(pos)
                        else:
                            different_between_groups.append(pos)
                
                return self.format_success({
                    "grn_table": grn_table,
                    "group1_size": len(group1_data),
                    "group2_size": len(group2_data),
                    "conservation_threshold": min_conservation,
                    "conserved_in_group1": len(conserved_in_group1),
                    "conserved_in_group2": len(conserved_in_group2),
                    "conserved_in_both": len(conserved_in_both),
                    "different_between_groups": len(different_between_groups),
                    "key_differences": different_between_groups[:10],  # Top 10
                    "position_details": position_conservation
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_extract_sequences_from_structures(ctx, dataset_name: str,
                                            chain_selection: Optional[str] = "all") -> Dict:
            """
            Extract amino acid sequences from a structure dataset (deprecated).
            
            Note: Use grn_extract_sequences_from_dataset for improved functionality.
            
            Args:
                dataset_name: Name of the structure dataset
                chain_selection: Which chains to extract ("all", "A", "B", etc.)
                
            Returns:
                Dictionary with extracted sequences
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get structure processor
                struct_processor = self.get_processor("structure")
                
                # Load dataset
                struct_processor.load_dataset(dataset_name)
                
                # Extract sequences
                if hasattr(struct_processor, 'get_seq_dict'):
                    sequences = struct_processor.get_seq_dict()
                else:
                    # Fallback method
                    sequences = {}
                    for pdb_id in struct_processor.pdb_ids:
                        seq = struct_processor.get_sequence(pdb_id, chain_selection)
                        if seq:
                            sequences[f"{pdb_id}_{chain_selection}"] = seq
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "num_sequences": len(sequences),
                    "chain_selection": chain_selection,
                    "sequences": dict(list(sequences.items())[:10])  # First 10
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_align_sequences_to_reference(ctx, query_sequences: Dict[str, str],
                                       reference_name: str,
                                       min_identity: float = 0.25,
                                       alignment_method: str = "mmseqs2") -> Dict:
            """
            Align query sequences to a GRN reference database using raw sequences.
            
            Note: For dataset-based alignment, use grn_align_dataset_to_reference instead.
            
            Args:
                query_sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                reference_name: Name of the reference table to align against
                min_identity: Minimum sequence identity threshold (0-1)
                alignment_method: Alignment method ("mmseqs2" or "blosum62")
                
            Returns:
                Dictionary with alignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"query_sequences": query_sequences, "reference_name": reference_name}, 
                    ["query_sequences", "reference_name"]
                ):
                    return error
                
                if not query_sequences:
                    return self.format_error(
                        "No sequences provided",
                        "Provide at least one sequence to align"
                    )
                
                # Get processors
                grn_processor = self.get_processor("grn")
                seq_processor = self.get_processor("sequence")
                
                # Load reference table
                grn_processor.load_reference_table(reference_name)
                ref_sequences = grn_processor.get_seq_dict()
                
                if not ref_sequences:
                    return self.format_error(
                        f"No sequences found in reference '{reference_name}'",
                        "Check if reference table loaded correctly"
                    )
                
                # Perform alignment
                if alignment_method == "mmseqs2":
                    try:
                        from protos.processing.sequence.seq_alignment import mmseqs2_align2
                        alignment_df = mmseqs2_align2(query_sequences, ref_sequences)
                    except ImportError:
                        return self.format_error(
                            "MMseqs2 not available",
                            "Install MMseqs2 or use 'blosum62' alignment method"
                        )
                else:
                    # Use pairwise BLOSUM62 alignment
                    alignment_results = []
                    from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62
                    
                    aligner = init_aligner()
                    for query_id, query_seq in query_sequences.items():
                        for ref_id, ref_seq in ref_sequences.items():
                            alignment = align_blosum62(query_seq, ref_seq, aligner)
                            # Calculate identity
                            matches = sum(1 for a, b in zip(alignment.seqA, alignment.seqB) if a == b)
                            identity = matches / len(alignment.seqA) if alignment.seqA else 0
                            
                            if identity >= min_identity:
                                alignment_results.append({
                                    'query_id': query_id,
                                    'target_id': ref_id,
                                    'sequence_identity': identity,
                                    'alignment_length': len(alignment.seqA),
                                    'score': alignment.score
                                })
                
                # Filter by identity threshold
                if alignment_method == "mmseqs2":
                    filtered_alignments = alignment_df[alignment_df['sequence_identity'] >= min_identity]
                    alignment_results = filtered_alignments.to_dict('records')
                
                # Get best match for each query
                best_matches = {}
                for result in alignment_results:
                    query_id = result['query_id']
                    if query_id not in best_matches or result['sequence_identity'] > best_matches[query_id]['sequence_identity']:
                        best_matches[query_id] = result
                
                result = {
                    "num_queries": len(query_sequences),
                    "num_alignments": len(alignment_results),
                    "num_filtered": len([r for r in alignment_results if r['sequence_identity'] >= min_identity]),
                    "alignment_method": alignment_method,
                    "min_identity": min_identity,
                }

                # In LLM-safe mode, limit the number of best matches returned
                if self.llm_safe_mode:
                    max_matches = min(10, len(best_matches))
                    limited_matches = dict(list(best_matches.items())[:max_matches])
                    result["best_matches"] = limited_matches
                    if len(best_matches) > max_matches:
                        result["matches_note"] = f"Showing {max_matches} of {len(best_matches)} best matches"
                else:
                    result["best_matches"] = best_matches

                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def assign_grn_to_sequences(ctx, sequence_alignments: Dict[str, Dict],
                                   reference_name: str,
                                   protein_family: str = "gpcr_a",
                                   expand_annotation: bool = True) -> Dict:
            """
            Assign GRN positions to aligned sequences.
            
            Args:
                sequence_alignments: Alignment results from grn_align_sequences_to_reference
                reference_name: Name of the reference table used
                protein_family: Protein family for GRN configuration
                expand_annotation: Whether to expand annotations to fill gaps
                
            Returns:
                Dictionary with GRN assignments
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequence_alignments": sequence_alignments, "reference_name": reference_name}, 
                    ["sequence_alignments", "reference_name"]
                ):
                    return error
                
                if not sequence_alignments:
                    return self.format_error(
                        "No alignments provided",
                        "First run grn_align_sequences_to_reference"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Load reference table if not already loaded
                processor.load_reference_table(reference_name)
                
                # Get GRN configuration
                from protos.processing.grn.grn_utils import GRNConfigManager
                config_manager = GRNConfigManager(paths=processor.paths)
                grn_config = config_manager.get_config(protein_family=protein_family, strict=False)
                
                # Process each alignment
                grn_assignments = {}
                
                for query_id, alignment_info in sequence_alignments.items():
                    if 'target_id' not in alignment_info:
                        continue
                    
                    ref_id = alignment_info['target_id']
                    
                    # Get reference GRN annotation
                    ref_row = processor.data.loc[ref_id]
                    
                    # Create GRN assignment for query
                    # This is a simplified version - full implementation would use
                    # init_row_from_alignment and expand_annotation
                    grn_assignment = {}
                    for grn_pos, residue in ref_row.items():
                        if residue != '-':
                            grn_assignment[grn_pos] = residue  # Simplified - would map through alignment
                    
                    grn_assignments[query_id] = {
                        'reference_id': ref_id,
                        'sequence_identity': alignment_info.get('sequence_identity', 0),
                        'num_positions': len(grn_assignment),
                        'grn_positions': grn_assignment
                    }
                
                return self.format_success({
                    "num_sequences": len(grn_assignments),
                    "protein_family": protein_family,
                    "reference_name": reference_name,
                    "grn_assignments": grn_assignments
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_create_table(ctx, grn_assignments: Dict[str, Dict],
                           dataset_name: str,
                           normalize_formats: bool = True) -> Dict:
            """
            Create and save a GRN table from assignments.
            
            Args:
                grn_assignments: GRN assignments from assign_grn_to_sequences
                dataset_name: Name for the GRN dataset
                normalize_formats: Whether to normalize GRN position formats
                
            Returns:
                Dictionary with table creation status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"grn_assignments": grn_assignments, "dataset_name": dataset_name}, 
                    ["grn_assignments", "dataset_name"]
                ):
                    return error
                
                if not grn_assignments:
                    return self.format_error(
                        "No GRN assignments provided",
                        "First run assign_grn_to_sequences"
                    )
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Create DataFrame from assignments
                import pandas as pd
                
                # Extract GRN data
                grn_data = {}
                for seq_id, assignment in grn_assignments.items():
                    if 'grn_positions' in assignment:
                        grn_data[seq_id] = assignment['grn_positions']
                
                # Create DataFrame
                grn_df = pd.DataFrame.from_dict(grn_data, orient='index')
                grn_df = grn_df.fillna('-')
                
                # Sort columns by GRN position
                from protos.processing.grn.grn_utils import sort_grns_str
                cols = grn_df.columns.tolist()
                sorted_cols = sort_grns_str(cols)
                grn_df = grn_df[sorted_cols]
                
                # Save the table
                processor.data = grn_df
                processor.save_grn_table(dataset_name, normalize_formats=normalize_formats)
                
                # Calculate coverage statistics
                total_positions = len(grn_df.columns)
                total_cells = len(grn_df) * total_positions
                filled_cells = (grn_df != '-').sum().sum()
                coverage = filled_cells / total_cells if total_cells > 0 else 0
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "num_sequences": len(grn_df),
                    "num_positions": total_positions,
                    "coverage": round(coverage, 3),
                    "table_saved": True
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_get_coverage_stats(ctx, dataset_name: str) -> Dict:
            """
            Calculate coverage statistics for a GRN table.
            
            Args:
                dataset_name: Name of the GRN dataset
                
            Returns:
                Dictionary with coverage statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Load GRN table
                grn_table = processor.load_grn_table(dataset_name)
                
                if grn_table is None or grn_table.empty:
                    return self.format_error(
                        f"GRN table '{dataset_name}' not found",
                        "Check available GRN datasets"
                    )
                
                # Calculate statistics
                total_positions = len(grn_table.columns)
                total_sequences = len(grn_table)
                total_cells = total_positions * total_sequences
                
                # Coverage by position
                position_coverage = (grn_table != '-').sum()
                avg_position_coverage = position_coverage.mean()
                
                # Coverage by sequence
                sequence_coverage = (grn_table != '-').sum(axis=1)
                avg_sequence_coverage = sequence_coverage.mean()
                
                # Overall coverage
                filled_cells = (grn_table != '-').sum().sum()
                overall_coverage = filled_cells / total_cells if total_cells > 0 else 0
                
                # Most/least covered positions
                most_covered = position_coverage.nlargest(10)
                least_covered = position_coverage[position_coverage > 0].nsmallest(10)
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "num_sequences": total_sequences,
                    "num_positions": total_positions,
                    "overall_coverage": round(overall_coverage, 3),
                    "avg_position_coverage": round(avg_position_coverage, 1),
                    "avg_sequence_coverage": round(avg_sequence_coverage, 1),
                    "most_covered_positions": most_covered.to_dict(),
                    "least_covered_positions": least_covered.to_dict(),
                    "fully_covered_positions": int((position_coverage == total_sequences).sum()),
                    "empty_positions": int((position_coverage == 0).sum())
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def grn_get_config(ctx, protein_family: str = "gpcr_a",
                          strict: bool = False) -> Dict:
            """
            Get GRN configuration for a protein family.
            
            Args:
                protein_family: Protein family name (e.g., "gpcr_a", "kinase")
                strict: Whether to use strict configuration
                
            Returns:
                Dictionary with GRN configuration regions
            """
            try:
                # Get GRN processor
                processor = self.get_processor("grn")
                
                # Get configuration
                from protos.processing.grn.grn_utils import GRNConfigManager
                config_manager = GRNConfigManager(paths=processor.paths)
                config = config_manager.get_config(protein_family=protein_family, strict=strict)
                
                if not config:
                    return self.format_error(
                        f"No configuration found for protein family '{protein_family}'",
                        "Check available protein families in GRN config"
                    )
                
                # Format configuration
                formatted_config = {}
                for region_name, (start_grn, end_grn) in config.items():
                    formatted_config[region_name] = {
                        "start": start_grn,
                        "end": end_grn
                    }
                
                return self.format_success({
                    "protein_family": protein_family,
                    "strict": strict,
                    "regions": formatted_config,
                    "num_regions": len(formatted_config)
                })

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def grn_query_entity(ctx, grn_table: str,
                           entity_id: str,
                           positions: Optional[List[str]] = None) -> Dict:
            """
            Get GRN annotations for a specific entity from a GRN table.

            Use this tool to inspect the GRN annotation of a single entity/sequence.
            Optionally filter to specific GRN positions of interest.

            Args:
                grn_table: Name of the GRN table
                entity_id: ID of the entity to query
                positions: Optional list of specific GRN positions to retrieve
                          (e.g., ["1.50", "2.50", "3.50"])

            Returns:
                Dictionary with entity's GRN annotations
            """
            try:
                if error := self.validate_required_params(
                    {"grn_table": grn_table, "entity_id": entity_id},
                    ["grn_table", "entity_id"]
                ):
                    return error

                processor = self.get_processor("grn")

                try:
                    table_df = processor.load_table(grn_table)
                    if table_df is None or table_df.empty:
                        return self.format_error(
                            f"GRN table '{grn_table}' not found or empty",
                            "Check available tables using list_grn_tables"
                        )
                except Exception as e:
                    return self.format_error(
                        f"Failed to load GRN table: {str(e)}",
                        "Check that the table exists"
                    )

                if entity_id not in table_df.index:
                    # Try partial match
                    matches = [idx for idx in table_df.index if entity_id.lower() in idx.lower()]
                    if matches:
                        return self.format_error(
                            f"Entity '{entity_id}' not found in table",
                            f"Did you mean one of: {matches[:5]}"
                        )
                    return self.format_error(
                        f"Entity '{entity_id}' not found in table",
                        f"Available entities: {list(table_df.index[:10])}..."
                    )

                row = table_df.loc[entity_id]

                # Filter to specific positions if requested
                if positions:
                    valid_positions = [p for p in positions if p in row.index]
                    invalid_positions = [p for p in positions if p not in row.index]
                    row = row[valid_positions]
                else:
                    valid_positions = list(row.index)
                    invalid_positions = []

                # Convert to dict, filtering out gaps for cleaner output
                annotations = {}
                gap_count = 0
                for pos, residue in row.items():
                    if residue != '-' and residue != '' and residue is not None:
                        annotations[pos] = residue
                    else:
                        gap_count += 1

                result = {
                    "grn_table": grn_table,
                    "entity_id": entity_id,
                    "total_positions": len(valid_positions),
                    "assigned_positions": len(annotations),
                    "gap_positions": gap_count,
                    "coverage": round(len(annotations) / len(valid_positions), 3) if valid_positions else 0,
                    "annotations": annotations,
                }

                if invalid_positions:
                    result["invalid_positions"] = invalid_positions

                return self.format_success(result)

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def grn_query_position(ctx, grn_table: str,
                             positions: List[str],
                             include_entity_details: bool = False) -> Dict:
            """
            Get amino acid distribution at specific GRN positions.

            Use this tool to analyze conservation or variation at specific GRN positions
            across all entities in a GRN table.

            Args:
                grn_table: Name of the GRN table
                positions: List of GRN positions to analyze (e.g., ["1.50", "2.50"])
                include_entity_details: If True, include per-entity residues (limited)

            Returns:
                Dictionary with AA distribution for each position
            """
            try:
                if error := self.validate_required_params(
                    {"grn_table": grn_table, "positions": positions},
                    ["grn_table", "positions"]
                ):
                    return error

                if not positions:
                    return self.format_error(
                        "No positions provided",
                        "Provide at least one GRN position to query"
                    )

                processor = self.get_processor("grn")

                try:
                    table_df = processor.load_table(grn_table)
                    if table_df is None or table_df.empty:
                        return self.format_error(
                            f"GRN table '{grn_table}' not found or empty",
                            "Check available tables using list_grn_tables"
                        )
                except Exception as e:
                    return self.format_error(
                        f"Failed to load GRN table: {str(e)}",
                        "Check that the table exists"
                    )

                position_stats: Dict[str, Any] = {}
                invalid_positions = []

                for pos in positions:
                    if pos not in table_df.columns:
                        invalid_positions.append(pos)
                        continue

                    col = table_df[pos]

                    # Count amino acids (excluding gaps)
                    aa_counts = col.value_counts()
                    non_gap_counts = aa_counts[~aa_counts.index.isin(['-', '', None])]
                    gap_count = aa_counts.get('-', 0) + aa_counts.get('', 0)

                    total_entities = len(col)
                    assigned_count = total_entities - gap_count

                    # Calculate conservation
                    if len(non_gap_counts) > 0:
                        most_common_aa = non_gap_counts.index[0]
                        most_common_count = non_gap_counts.iloc[0]
                        conservation = most_common_count / assigned_count if assigned_count > 0 else 0
                    else:
                        most_common_aa = None
                        conservation = 0

                    pos_data = {
                        "total_entities": total_entities,
                        "assigned_count": int(assigned_count),
                        "gap_count": int(gap_count),
                        "coverage": round(assigned_count / total_entities, 3) if total_entities > 0 else 0,
                        "most_common_aa": most_common_aa,
                        "conservation": round(conservation, 3),
                        "aa_distribution": non_gap_counts.to_dict(),
                    }

                    # Optionally include per-entity details (limited)
                    if include_entity_details:
                        # Only include first 20 entities with non-gap residues
                        entity_residues = {}
                        count = 0
                        for entity_id, residue in col.items():
                            if residue != '-' and residue != '' and residue is not None:
                                entity_residues[entity_id] = residue
                                count += 1
                                if count >= 20:
                                    break
                        pos_data["entity_residues"] = entity_residues
                        if assigned_count > 20:
                            pos_data["entity_residues_note"] = f"Showing 20 of {int(assigned_count)} entities"

                    position_stats[pos] = pos_data

                result = {
                    "grn_table": grn_table,
                    "positions_queried": len(positions),
                    "positions_found": len(position_stats),
                    "position_stats": position_stats,
                }

                if invalid_positions:
                    result["invalid_positions"] = invalid_positions
                    # Suggest similar positions
                    available = list(table_df.columns[:20])
                    result["available_positions_sample"] = available

                return self.format_success(result)

            except Exception as e:
                return self.handle_error(e)

