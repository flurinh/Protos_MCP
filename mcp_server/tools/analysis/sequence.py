"""
Sequence analysis tools leveraging Protos' SequenceProcessor.

These tools provide sequence analysis capabilities including alignment,
identity calculation, conservation analysis, and mutation detection.
"""

from typing import Dict, List, Optional, Any, Tuple, Union
import json
import logging

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, EntityNotFoundError

logger = logging.getLogger(__name__)


class SequenceAnalysisTools(BaseTool):
    """Tools for sequence analysis and processing."""
    
    def register(self, server):
        """Register sequence analysis tools with the server."""
        
        @server.tool()
        def align_sequences(ctx, sequence1: str, sequence2: str,
                          alignment_method: str = "blosum62",
                          gap_open: int = -10,
                          gap_extend: int = -1) -> Dict:
            """
            Perform pairwise sequence alignment using raw sequences.
            
            Note: For entity-based alignment, use align_sequences_by_id instead.
            
            Args:
                sequence1: First sequence (raw string)
                sequence2: Second sequence (raw string)
                alignment_method: Alignment method ("blosum62", "pam250", etc.)
                gap_open: Gap opening penalty
                gap_extend: Gap extension penalty
                
            Returns:
                Dictionary with alignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequence1": sequence1, "sequence2": sequence2}, 
                    ["sequence1", "sequence2"]
                ):
                    return error
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Perform alignment
                from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62, format_alignment
                
                aligner = init_aligner()
                
                if alignment_method == "blosum62":
                    alignment = align_blosum62(sequence1, sequence2, aligner, 
                                             gap_open=gap_open, gap_extend=gap_extend)
                else:
                    # Use generic alignment
                    alignment = aligner.align(sequence1, sequence2, 
                                            gap_open=gap_open, gap_extend=gap_extend)[0][0]
                
                # Format alignment
                formatted = format_alignment(alignment)
                
                # Calculate statistics
                aligned_seq1 = str(alignment.seqA)
                aligned_seq2 = str(alignment.seqB)
                
                matches = sum(1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != '-')
                length = len([a for a, b in zip(aligned_seq1, aligned_seq2) if a != '-' or b != '-'])
                identity = matches / length if length > 0 else 0
                
                # Count gaps
                gaps_seq1 = aligned_seq1.count('-')
                gaps_seq2 = aligned_seq2.count('-')
                
                return self.format_success({
                    "alignment": formatted,
                    "score": float(alignment.score),
                    "identity": round(identity, 3),
                    "matches": matches,
                    "length": length,
                    "gaps_seq1": gaps_seq1,
                    "gaps_seq2": gaps_seq2,
                    "method": alignment_method
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def align_sequences_by_id(ctx, entity1: str, entity2: str,
                                alignment_method: str = "blosum62",
                                gap_open: int = -10,
                                gap_extend: int = -1) -> Dict:
            """
            Perform pairwise sequence alignment using entity identifiers.
            
            This tool loads sequences from Protos storage rather than requiring
            the full sequence strings as input.
            
            Args:
                entity1: Entity identifier for first sequence
                entity2: Entity identifier for second sequence
                alignment_method: Alignment method ("blosum62", "pam250", etc.)
                gap_open: Gap opening penalty
                gap_extend: Gap extension penalty
                
            Returns:
                Dictionary with alignment results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity1": entity1, "entity2": entity2}, 
                    ["entity1", "entity2"]
                ):
                    return error
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Load sequences from storage
                try:
                    seq1_data = processor.load_entity(entity1)
                    seq2_data = processor.load_entity(entity2)
                except Exception as e:
                    return self.format_error(
                        f"Failed to load sequences: {str(e)}",
                        "Ensure both entities exist in sequence processor"
                    )
                
                # Extract sequence strings
                if isinstance(seq1_data, dict):
                    # Handle multi-sequence files
                    seq1 = list(seq1_data.values())[0] if seq1_data else ""
                else:
                    seq1 = str(seq1_data)
                    
                if isinstance(seq2_data, dict):
                    seq2 = list(seq2_data.values())[0] if seq2_data else ""
                else:
                    seq2 = str(seq2_data)
                
                if not seq1 or not seq2:
                    return self.format_error(
                        "Empty sequences found",
                        "Check that entities contain valid sequence data"
                    )
                
                # Perform alignment
                from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62, format_alignment
                
                aligner = init_aligner()
                
                if alignment_method == "blosum62":
                    alignment = align_blosum62(seq1, seq2, aligner, 
                                             gap_open=gap_open, gap_extend=gap_extend)
                else:
                    alignment = aligner.align(seq1, seq2, 
                                            gap_open=gap_open, gap_extend=gap_extend)[0][0]
                
                # Format alignment
                formatted = format_alignment(alignment)
                
                # Calculate statistics
                aligned_seq1 = str(alignment.seqA)
                aligned_seq2 = str(alignment.seqB)
                
                matches = sum(1 for a, b in zip(aligned_seq1, aligned_seq2) if a == b and a != '-')
                length = len([a for a, b in zip(aligned_seq1, aligned_seq2) if a != '-' or b != '-'])
                identity = matches / length if length > 0 else 0
                
                return self.format_success({
                    "entity1": entity1,
                    "entity2": entity2,
                    "alignment": formatted,
                    "score": float(alignment.score),
                    "identity": round(identity, 3),
                    "matches": matches,
                    "length": length,
                    "gaps_seq1": aligned_seq1.count('-'),
                    "gaps_seq2": aligned_seq2.count('-'),
                    "method": alignment_method
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_sequence_identity(ctx, sequences: Dict[str, str],
                                      reference_sequence: Optional[str] = None) -> Dict:
            """
            Calculate pairwise sequence identities using raw sequences.
            
            Note: For entity-based identity calculation, use calculate_identity_from_dataset instead.
            
            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                reference_sequence: Optional reference sequence to compare all against
                
            Returns:
                Dictionary with identity matrix
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, 
                    ["sequences"]
                ):
                    return error
                
                if len(sequences) < 2 and not reference_sequence:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences or a reference sequence"
                    )
                
                # Calculate identities
                identities = {}
                
                if reference_sequence:
                    # Compare all to reference
                    for seq_id, seq in sequences.items():
                        # Simple identity calculation
                        min_len = min(len(seq), len(reference_sequence))
                        matches = sum(1 for i in range(min_len) if seq[i] == reference_sequence[i])
                        identity = matches / max(len(seq), len(reference_sequence))
                        identities[seq_id] = round(identity, 3)
                else:
                    # All vs all comparison
                    seq_ids = list(sequences.keys())
                    for i, id1 in enumerate(seq_ids):
                        identities[id1] = {}
                        for j, id2 in enumerate(seq_ids):
                            if i == j:
                                identities[id1][id2] = 1.0
                            else:
                                seq1 = sequences[id1]
                                seq2 = sequences[id2]
                                min_len = min(len(seq1), len(seq2))
                                matches = sum(1 for k in range(min_len) if seq1[k] == seq2[k])
                                identity = matches / max(len(seq1), len(seq2))
                                identities[id1][id2] = round(identity, 3)
                
                # Calculate statistics
                if reference_sequence:
                    avg_identity = sum(identities.values()) / len(identities)
                    min_identity = min(identities.values())
                    max_identity = max(identities.values())
                else:
                    all_values = []
                    for id1 in identities:
                        for id2 in identities[id1]:
                            if id1 != id2:
                                all_values.append(identities[id1][id2])
                    avg_identity = sum(all_values) / len(all_values) if all_values else 0
                    min_identity = min(all_values) if all_values else 0
                    max_identity = max(all_values) if all_values else 0
                
                return self.format_success({
                    "num_sequences": len(sequences),
                    "reference_used": bool(reference_sequence),
                    "identities": identities,
                    "avg_identity": round(avg_identity, 3),
                    "min_identity": round(min_identity, 3),
                    "max_identity": round(max_identity, 3)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def calculate_identity_from_dataset(ctx, dataset_name: str,
                                          reference_entity: Optional[str] = None) -> Dict:
            """
            Calculate pairwise sequence identities for all sequences in a dataset.
            
            Args:
                dataset_name: Name of the sequence dataset
                reference_entity: Optional reference entity for one-vs-all comparison
                
            Returns:
                Dictionary with identity matrix or list
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Load dataset
                try:
                    dataset = processor.load_dataset(dataset_name)
                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset: {str(e)}",
                        "Check dataset exists in sequence processor"
                    )
                
                # Get entity list from dataset
                if hasattr(dataset, 'content'):
                    entities = dataset.content
                elif hasattr(dataset, 'entities'):
                    entities = dataset.entities
                else:
                    return self.format_error(
                        "Cannot determine dataset entities",
                        "Dataset structure not recognized"
                    )
                
                # Load all sequences
                sequences = {}
                for entity in entities:
                    try:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)
                    except Exception as e:
                        logger.warning(f"Failed to load {entity}: {e}")
                
                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for identity calculation",
                        "Ensure dataset contains multiple valid sequences"
                    )
                
                # Calculate identities
                from protos.processing.sequence.seq_alignment import calculate_identity
                
                if reference_entity:
                    # One-vs-all mode
                    if reference_entity not in sequences:
                        return self.format_error(
                            f"Reference entity '{reference_entity}' not in dataset",
                            "Choose a reference from the dataset entities"
                        )
                    
                    ref_seq = sequences[reference_entity]
                    identities = {}
                    
                    for entity, seq in sequences.items():
                        if entity != reference_entity:
                            identity = calculate_identity(ref_seq, seq)
                            identities[entity] = round(identity, 3)
                    
                    return self.format_success({
                        "mode": "one_vs_all",
                        "reference": reference_entity,
                        "dataset": dataset_name,
                        "num_comparisons": len(identities),
                        "identities": identities,
                        "avg_identity": round(sum(identities.values()) / len(identities), 3),
                        "min_identity": round(min(identities.values()), 3),
                        "max_identity": round(max(identities.values()), 3)
                    })
                else:
                    # All-vs-all mode
                    identity_matrix = {}
                    
                    for entity1 in sequences:
                        identity_matrix[entity1] = {}
                        for entity2 in sequences:
                            if entity1 == entity2:
                                identity_matrix[entity1][entity2] = 1.0
                            else:
                                identity = calculate_identity(sequences[entity1], sequences[entity2])
                                identity_matrix[entity1][entity2] = round(identity, 3)
                    
                    # Calculate statistics
                    all_identities = []
                    for e1 in sequences:
                        for e2 in sequences:
                            if e1 != e2:
                                all_identities.append(identity_matrix[e1][e2])
                    
                    return self.format_success({
                        "mode": "all_vs_all",
                        "dataset": dataset_name,
                        "num_sequences": len(sequences),
                        "identity_matrix": identity_matrix,
                        "avg_identity": round(sum(all_identities) / len(all_identities), 3) if all_identities else 0,
                        "min_identity": round(min(all_identities), 3) if all_identities else 0,
                        "max_identity": round(max(all_identities), 3) if all_identities else 0
                    })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def find_conserved_regions(ctx, sequences: Dict[str, str],
                                 min_conservation: float = 0.8,
                                 min_length: int = 5) -> Dict:
            """
            Find conserved regions across multiple sequences using raw sequences.
            
            Note: For dataset-based conservation analysis, use find_conserved_regions_in_dataset instead.
            
            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                min_conservation: Minimum conservation threshold (0-1)
                min_length: Minimum length of conserved region
                
            Returns:
                Dictionary with conserved regions
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, 
                    ["sequences"]
                ):
                    return error
                
                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences to find conservation"
                    )
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Find the shortest sequence length
                min_seq_length = min(len(seq) for seq in sequences.values())
                
                # Calculate conservation at each position
                conservation_scores = []
                for pos in range(min_seq_length):
                    residues = [seq[pos] for seq in sequences.values() if pos < len(seq)]
                    # Calculate frequency of most common residue
                    if residues:
                        most_common = max(set(residues), key=residues.count)
                        conservation = residues.count(most_common) / len(residues)
                        conservation_scores.append({
                            'position': pos,
                            'conservation': conservation,
                            'consensus': most_common,
                            'residues': ''.join(sorted(set(residues)))
                        })
                
                # Find conserved regions
                conserved_regions = []
                current_region = None
                
                for score in conservation_scores:
                    if score['conservation'] >= min_conservation:
                        if current_region is None:
                            current_region = {
                                'start': score['position'],
                                'end': score['position'],
                                'conservation': [score['conservation']],
                                'consensus': score['consensus']
                            }
                        else:
                            current_region['end'] = score['position']
                            current_region['conservation'].append(score['conservation'])
                            current_region['consensus'] += score['consensus']
                    else:
                        if current_region and (current_region['end'] - current_region['start'] + 1) >= min_length:
                            current_region['avg_conservation'] = sum(current_region['conservation']) / len(current_region['conservation'])
                            conserved_regions.append(current_region)
                        current_region = None
                
                # Check last region
                if current_region and (current_region['end'] - current_region['start'] + 1) >= min_length:
                    current_region['avg_conservation'] = sum(current_region['conservation']) / len(current_region['conservation'])
                    conserved_regions.append(current_region)
                
                # Clean up regions
                for region in conserved_regions:
                    region.pop('conservation', None)
                    region['length'] = region['end'] - region['start'] + 1
                
                return self.format_success({
                    "num_sequences": len(sequences),
                    "sequence_length": min_seq_length,
                    "min_conservation": min_conservation,
                    "min_length": min_length,
                    "num_conserved_regions": len(conserved_regions),
                    "conserved_regions": conserved_regions[:20],  # First 20
                    "total_conserved_positions": sum(r['length'] for r in conserved_regions)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def find_conserved_regions_in_dataset(ctx, dataset_name: str,
                                            min_conservation: float = 0.8,
                                            min_length: int = 5) -> Dict:
            """
            Find conserved regions across all sequences in a dataset.
            
            Args:
                dataset_name: Name of the sequence dataset
                min_conservation: Minimum conservation threshold (0-1)
                min_length: Minimum length for conserved regions
                
            Returns:
                Dictionary with conserved regions
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                if not 0 <= min_conservation <= 1:
                    return self.format_error(
                        "min_conservation must be between 0 and 1",
                        "Use 0.8 for 80% conservation"
                    )
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Load dataset and sequences
                try:
                    dataset = processor.load_dataset(dataset_name)
                    entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                    
                    sequences = {}
                    for entity in entities:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)
                            
                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset sequences: {str(e)}",
                        "Ensure dataset exists and contains valid sequences"
                    )
                
                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for conservation analysis",
                        "Add more sequences to the dataset"
                    )
                
                # Find conserved regions
                from protos.processing.sequence.seq_conservation import find_conserved_regions
                
                conserved_regions = find_conserved_regions(
                    list(sequences.values()),
                    threshold=min_conservation,
                    min_length=min_length
                )
                
                # Format results
                formatted_regions = []
                for region in conserved_regions:
                    formatted_regions.append({
                        "start": region["start"],
                        "end": region["end"],
                        "length": region["end"] - region["start"] + 1,
                        "consensus": region["consensus"],
                        "avg_conservation": round(region["conservation"], 3)
                    })
                
                # Sort by position
                formatted_regions.sort(key=lambda x: x["start"])
                
                total_conserved = sum(r["length"] for r in formatted_regions)
                avg_seq_length = sum(len(s) for s in sequences.values()) / len(sequences)
                
                return self.format_success({
                    "dataset": dataset_name,
                    "num_sequences": len(sequences),
                    "conservation_threshold": min_conservation,
                    "num_conserved_regions": len(formatted_regions),
                    "conserved_regions": formatted_regions,
                    "total_conserved_positions": total_conserved,
                    "conservation_coverage": round(total_conserved / avg_seq_length, 3) if avg_seq_length > 0 else 0
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def detect_mutations(ctx, wild_type: str, variant: str,
                           numbering_start: int = 1) -> Dict:
            """
            Detect mutations between wild-type and variant sequences using raw sequences.
            
            Note: For entity-based mutation detection, use detect_mutations_between_entities instead.
            
            Args:
                wild_type: Wild-type sequence (raw string)
                variant: Variant sequence (raw string)
                numbering_start: Position numbering start (default 1)
                
            Returns:
                Dictionary with detected mutations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"wild_type": wild_type, "variant": variant}, 
                    ["wild_type", "variant"]
                ):
                    return error
                
                # Detect mutations
                mutations = []
                insertions = []
                deletions = []
                
                # Simple mutation detection (without alignment)
                if len(wild_type) == len(variant):
                    # Same length - check substitutions
                    for i, (wt_res, var_res) in enumerate(zip(wild_type, variant)):
                        if wt_res != var_res:
                            mutations.append({
                                'position': i + numbering_start,
                                'wild_type': wt_res,
                                'variant': var_res,
                                'type': 'substitution',
                                'notation': f"{wt_res}{i + numbering_start}{var_res}"
                            })
                else:
                    # Different lengths - need alignment
                    from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62
                    
                    aligner = init_aligner()
                    alignment = align_blosum62(wild_type, variant, aligner)
                    
                    wt_aligned = str(alignment.seqA)
                    var_aligned = str(alignment.seqB)
                    
                    wt_pos = numbering_start - 1
                    var_pos = 0
                    
                    for wt_res, var_res in zip(wt_aligned, var_aligned):
                        if wt_res != '-':
                            wt_pos += 1
                        
                        if wt_res == '-' and var_res != '-':
                            # Insertion
                            insertions.append({
                                'position': wt_pos,
                                'inserted': var_res,
                                'type': 'insertion',
                                'notation': f"ins{wt_pos}{var_res}"
                            })
                        elif wt_res != '-' and var_res == '-':
                            # Deletion
                            deletions.append({
                                'position': wt_pos,
                                'deleted': wt_res,
                                'type': 'deletion',
                                'notation': f"del{wt_pos}{wt_res}"
                            })
                        elif wt_res != '-' and var_res != '-' and wt_res != var_res:
                            # Substitution
                            mutations.append({
                                'position': wt_pos,
                                'wild_type': wt_res,
                                'variant': var_res,
                                'type': 'substitution',
                                'notation': f"{wt_res}{wt_pos}{var_res}"
                            })
                
                # Combine all mutations
                all_mutations = mutations + insertions + deletions
                all_mutations.sort(key=lambda x: x['position'])
                
                # Calculate statistics
                num_substitutions = len(mutations)
                num_insertions = len(insertions)
                num_deletions = len(deletions)
                total_mutations = len(all_mutations)
                
                # Calculate similarity
                matches = sum(1 for wt, var in zip(wild_type, variant) if wt == var)
                similarity = matches / max(len(wild_type), len(variant)) if max(len(wild_type), len(variant)) > 0 else 0
                
                return self.format_success({
                    "wild_type_length": len(wild_type),
                    "variant_length": len(variant),
                    "total_mutations": total_mutations,
                    "substitutions": num_substitutions,
                    "insertions": num_insertions,
                    "deletions": num_deletions,
                    "similarity": round(similarity, 3),
                    "mutations": all_mutations[:50],  # First 50
                    "mutation_rate": round(total_mutations / len(wild_type), 3) if len(wild_type) > 0 else 0
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def detect_mutations_between_entities(ctx, reference_entity: str, 
                                            variant_entity: str,
                                            include_positions: bool = True) -> Dict:
            """
            Detect mutations between two sequence entities.
            
            Args:
                reference_entity: Reference sequence entity ID
                variant_entity: Variant sequence entity ID
                include_positions: Include detailed position information
                
            Returns:
                Dictionary with detected mutations
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"reference_entity": reference_entity, "variant_entity": variant_entity}, 
                    ["reference_entity", "variant_entity"]
                ):
                    return error
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Load sequences
                try:
                    ref_data = processor.load_entity(reference_entity)
                    var_data = processor.load_entity(variant_entity)
                    
                    # Extract sequences
                    ref_seq = list(ref_data.values())[0] if isinstance(ref_data, dict) else str(ref_data)
                    var_seq = list(var_data.values())[0] if isinstance(var_data, dict) else str(var_data)
                    
                except Exception as e:
                    return self.format_error(
                        f"Failed to load sequences: {str(e)}",
                        "Ensure both entities exist in sequence processor"
                    )
                
                # Align sequences first
                from protos.processing.sequence.seq_alignment import init_aligner, align_blosum62
                
                aligner = init_aligner()
                alignment = align_blosum62(ref_seq, var_seq, aligner)
                
                aligned_ref = str(alignment.seqA)
                aligned_var = str(alignment.seqB)
                
                # Detect mutations
                mutations = []
                ref_pos = 0
                var_pos = 0
                
                for i, (ref_aa, var_aa) in enumerate(zip(aligned_ref, aligned_var)):
                    if ref_aa != '-':
                        ref_pos += 1
                    if var_aa != '-':
                        var_pos += 1
                        
                    if ref_aa != var_aa:
                        if ref_aa == '-':
                            # Insertion
                            mutations.append({
                                "type": "insertion",
                                "position": ref_pos,
                                "reference": "-",
                                "variant": var_aa,
                                "notation": f"ins{ref_pos}{var_aa}"
                            })
                        elif var_aa == '-':
                            # Deletion
                            mutations.append({
                                "type": "deletion",
                                "position": ref_pos,
                                "reference": ref_aa,
                                "variant": "-",
                                "notation": f"{ref_aa}{ref_pos}del"
                            })
                        else:
                            # Substitution
                            mutations.append({
                                "type": "substitution",
                                "position": ref_pos,
                                "reference": ref_aa,
                                "variant": var_aa,
                                "notation": f"{ref_aa}{ref_pos}{var_aa}"
                            })
                
                # Summary statistics
                mut_types = {"substitution": 0, "insertion": 0, "deletion": 0}
                for mut in mutations:
                    mut_types[mut["type"]] += 1
                
                result = {
                    "reference_entity": reference_entity,
                    "variant_entity": variant_entity,
                    "total_mutations": len(mutations),
                    "mutation_types": mut_types,
                    "alignment_score": float(alignment.score),
                    "sequence_identity": round(
                        sum(1 for a, b in zip(aligned_ref, aligned_var) if a == b and a != '-') / 
                        len([a for a in aligned_ref if a != '-']), 3
                    )
                }
                
                if include_positions:
                    result["mutations"] = mutations
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def translate_sequence(ctx, dna_sequence: str,
                             genetic_code: int = 1,
                             to_stop: bool = True) -> Dict:
            """
            Translate DNA/RNA sequence to protein.
            
            Args:
                dna_sequence: DNA or RNA sequence
                genetic_code: NCBI genetic code table (1=standard)
                to_stop: Stop translation at first stop codon
                
            Returns:
                Dictionary with translation results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dna_sequence": dna_sequence}, 
                    ["dna_sequence"]
                ):
                    return error
                
                # Clean sequence
                dna_sequence = dna_sequence.upper().replace('U', 'T')
                
                # Standard genetic code
                codon_table = {
                    'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L',
                    'TCT': 'S', 'TCC': 'S', 'TCA': 'S', 'TCG': 'S',
                    'TAT': 'Y', 'TAC': 'Y', 'TAA': '*', 'TAG': '*',
                    'TGT': 'C', 'TGC': 'C', 'TGA': '*', 'TGG': 'W',
                    'CTT': 'L', 'CTC': 'L', 'CTA': 'L', 'CTG': 'L',
                    'CCT': 'P', 'CCC': 'P', 'CCA': 'P', 'CCG': 'P',
                    'CAT': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q',
                    'CGT': 'R', 'CGC': 'R', 'CGA': 'R', 'CGG': 'R',
                    'ATT': 'I', 'ATC': 'I', 'ATA': 'I', 'ATG': 'M',
                    'ACT': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T',
                    'AAT': 'N', 'AAC': 'N', 'AAA': 'K', 'AAG': 'K',
                    'AGT': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R',
                    'GTT': 'V', 'GTC': 'V', 'GTA': 'V', 'GTG': 'V',
                    'GCT': 'A', 'GCC': 'A', 'GCA': 'A', 'GCG': 'A',
                    'GAT': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E',
                    'GGT': 'G', 'GGC': 'G', 'GGA': 'G', 'GGG': 'G'
                }
                
                # Translate in all three frames
                translations = {}
                
                for frame in range(3):
                    protein = []
                    for i in range(frame, len(dna_sequence) - 2, 3):
                        codon = dna_sequence[i:i+3]
                        if len(codon) == 3:
                            aa = codon_table.get(codon, 'X')
                            if to_stop and aa == '*':
                                break
                            protein.append(aa)
                    translations[f"frame_{frame+1}"] = ''.join(protein)
                
                # Find ORFs (Open Reading Frames)
                orfs = []
                for frame_name, protein in translations.items():
                    # Find sequences between M and *
                    import re
                    for match in re.finditer(r'M[^*]*\*', protein):
                        if len(match.group()) >= 10:  # At least 10 amino acids
                            orfs.append({
                                'frame': frame_name,
                                'start': match.start(),
                                'end': match.end(),
                                'length': len(match.group()) - 1,  # Exclude stop
                                'sequence': match.group()[:-1]  # Remove stop
                            })
                
                # Sort ORFs by length
                orfs.sort(key=lambda x: x['length'], reverse=True)
                
                return self.format_success({
                    "dna_length": len(dna_sequence),
                    "translations": translations,
                    "num_orfs": len(orfs),
                    "longest_orf": orfs[0] if orfs else None,
                    "orfs": orfs[:10]  # Top 10 ORFs
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def cluster_sequences(ctx, sequences: Dict[str, str],
                            identity_threshold: float = 0.9,
                            method: str = "single") -> Dict:
            """
            Cluster sequences by similarity using raw sequences.
            
            Note: For dataset-based clustering, use cluster_dataset_sequences instead.
            
            Args:
                sequences: Dictionary mapping sequence IDs to sequences (raw strings)
                identity_threshold: Identity threshold for clustering (0-1)
                method: Clustering method ("single", "complete", "average")
                
            Returns:
                Dictionary with cluster assignments
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"sequences": sequences}, 
                    ["sequences"]
                ):
                    return error
                
                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences",
                        "Provide multiple sequences to cluster"
                    )
                
                # Calculate pairwise identities
                seq_ids = list(sequences.keys())
                n = len(seq_ids)
                identity_matrix = [[1.0] * n for _ in range(n)]
                
                for i in range(n):
                    for j in range(i + 1, n):
                        seq1 = sequences[seq_ids[i]]
                        seq2 = sequences[seq_ids[j]]
                        
                        # Simple identity calculation
                        min_len = min(len(seq1), len(seq2))
                        matches = sum(1 for k in range(min_len) if seq1[k] == seq2[k])
                        identity = matches / max(len(seq1), len(seq2))
                        
                        identity_matrix[i][j] = identity
                        identity_matrix[j][i] = identity
                
                # Simple clustering based on threshold
                clusters = {}
                assigned = set()
                cluster_id = 0
                
                for i, seq_id in enumerate(seq_ids):
                    if seq_id in assigned:
                        continue
                    
                    # Start new cluster
                    cluster_id += 1
                    cluster_members = [seq_id]
                    assigned.add(seq_id)
                    
                    # Find similar sequences
                    for j, other_id in enumerate(seq_ids):
                        if other_id not in assigned and identity_matrix[i][j] >= identity_threshold:
                            cluster_members.append(other_id)
                            assigned.add(other_id)
                    
                    clusters[f"cluster_{cluster_id}"] = {
                        'members': cluster_members,
                        'size': len(cluster_members),
                        'representative': seq_id
                    }
                
                # Calculate cluster statistics
                cluster_sizes = [c['size'] for c in clusters.values()]
                
                return self.format_success({
                    "num_sequences": len(sequences),
                    "num_clusters": len(clusters),
                    "identity_threshold": identity_threshold,
                    "clustering_method": method,
                    "clusters": clusters,
                    "largest_cluster": max(cluster_sizes) if cluster_sizes else 0,
                    "singleton_clusters": sum(1 for s in cluster_sizes if s == 1)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def cluster_dataset_sequences(ctx, dataset_name: str,
                                    similarity_threshold: float = 0.8,
                                    method: str = "single") -> Dict:
            """
            Cluster sequences in a dataset by similarity.
            
            Args:
                dataset_name: Name of the sequence dataset
                similarity_threshold: Similarity threshold for clustering (0-1)
                method: Clustering method (single, complete, average)
                
            Returns:
                Dictionary with cluster assignments
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name}, 
                    ["dataset_name"]
                ):
                    return error
                
                if not 0 <= similarity_threshold <= 1:
                    return self.format_error(
                        "similarity_threshold must be between 0 and 1",
                        "Use 0.8 for 80% similarity clustering"
                    )
                
                # Get sequence processor
                processor = self.get_processor("sequence")
                
                # Load dataset
                try:
                    dataset = processor.load_dataset(dataset_name)
                    entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                    
                    sequences = {}
                    for entity in entities:
                        seq_data = processor.load_entity(entity)
                        if isinstance(seq_data, dict):
                            sequences[entity] = list(seq_data.values())[0]
                        else:
                            sequences[entity] = str(seq_data)
                            
                except Exception as e:
                    return self.format_error(
                        f"Failed to load dataset: {str(e)}",
                        "Ensure dataset exists in sequence processor"
                    )
                
                if len(sequences) < 2:
                    return self.format_error(
                        "Need at least 2 sequences for clustering",
                        "Add more sequences to the dataset"
                    )
                
                # Calculate pairwise distances
                from protos.processing.sequence.seq_alignment import calculate_identity
                import numpy as np
                
                entities_list = list(sequences.keys())
                n = len(entities_list)
                distance_matrix = np.zeros((n, n))
                
                for i in range(n):
                    for j in range(i + 1, n):
                        identity = calculate_identity(
                            sequences[entities_list[i]], 
                            sequences[entities_list[j]]
                        )
                        distance = 1 - identity  # Convert identity to distance
                        distance_matrix[i, j] = distance
                        distance_matrix[j, i] = distance
                
                # Perform hierarchical clustering
                from scipy.cluster.hierarchy import linkage, fcluster
                
                # Convert to condensed distance matrix
                condensed_dist = []
                for i in range(n):
                    for j in range(i + 1, n):
                        condensed_dist.append(distance_matrix[i, j])
                
                # Cluster
                linkage_matrix = linkage(condensed_dist, method=method)
                clusters = fcluster(linkage_matrix, 1 - similarity_threshold, criterion='distance')
                
                # Format results
                cluster_dict = {}
                for entity, cluster_id in zip(entities_list, clusters):
                    cluster_key = f"cluster_{cluster_id}"
                    if cluster_key not in cluster_dict:
                        cluster_dict[cluster_key] = []
                    cluster_dict[cluster_key].append(entity)
                
                # Calculate cluster statistics
                cluster_stats = {}
                for cluster_key, members in cluster_dict.items():
                    if len(members) > 1:
                        # Calculate average within-cluster identity
                        identities = []
                        for i, e1 in enumerate(members):
                            for e2 in members[i + 1:]:
                                identity = calculate_identity(sequences[e1], sequences[e2])
                                identities.append(identity)
                        avg_identity = sum(identities) / len(identities) if identities else 1.0
                    else:
                        avg_identity = 1.0
                    
                    cluster_stats[cluster_key] = {
                        "size": len(members),
                        "avg_identity": round(avg_identity, 3)
                    }
                
                return self.format_success({
                    "dataset": dataset_name,
                    "num_sequences": len(sequences),
                    "similarity_threshold": similarity_threshold,
                    "clustering_method": method,
                    "num_clusters": len(cluster_dict),
                    "clusters": cluster_dict,
                    "cluster_statistics": cluster_stats,
                    "singletons": sum(1 for c in cluster_dict.values() if len(c) == 1)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def extract_sequence_from_structure_batch(ctx, dataset_name: str,
                                                chain_selection: Optional[str] = None,
                                                save_as_dataset: Optional[str] = None) -> Dict:
            """
            Extract sequences from all structures in a dataset.
            
            This is a batch operation that processes multiple structures and
            extracts their sequences, optionally saving them as a new sequence dataset.
            
            Args:
                dataset_name: Name of the structure dataset
                chain_selection: Chain to extract (e.g., "A"), or None for all chains
                save_as_dataset: Optional name for saving extracted sequences
                
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
                
                # Get processors
                struct_processor = self.get_processor("structure")
                seq_processor = self.get_processor("sequence")
                
                # Load structure dataset
                try:
                    dataset = struct_processor.load_dataset(dataset_name)
                    entities = dataset.content if hasattr(dataset, 'content') else dataset.entities
                except Exception as e:
                    return self.format_error(
                        f"Failed to load structure dataset: {str(e)}",
                        "Ensure dataset exists in structure processor"
                    )
                
                # Extract sequences from each structure
                extracted_sequences = {}
                failed_extractions = []
                
                for entity in entities:
                    try:
                        # Load structure
                        struct_processor.load_structures([entity])
                        
                        if chain_selection:
                            # Extract specific chain
                            seq = struct_processor.get_sequence(entity, chain_selection)
                            if seq:
                                seq_id = f"{entity}_{chain_selection}"
                                extracted_sequences[seq_id] = seq
                        else:
                            # Extract all chains
                            all_seqs = struct_processor.get_all_sequences()
                            for chain_id, seq in all_seqs.items():
                                if chain_id.startswith(f"{entity}_"):
                                    extracted_sequences[chain_id] = seq
                                    
                    except Exception as e:
                        failed_extractions.append({
                            "entity": entity,
                            "error": str(e)
                        })
                
                if not extracted_sequences:
                    return self.format_error(
                        "No sequences could be extracted",
                        "Check structure dataset and chain selection"
                    )
                
                # Save as dataset if requested
                saved_entities = []
                if save_as_dataset:
                    try:
                        # Save each sequence
                        for seq_id, sequence in extracted_sequences.items():
                            seq_processor.save_entity(seq_id, sequence)
                            saved_entities.append(seq_id)
                        
                        # Create sequence dataset
                        import pandas as pd
                        seq_dataset = seq_processor.create_standard_dataset(
                            dataset_id=save_as_dataset,
                            name=f"Sequences from {dataset_name}",
                            content=list(extracted_sequences.keys()),
                            metadata={
                                "source_dataset": dataset_name,
                                "chain_selection": chain_selection,
                                "extraction_date": str(pd.Timestamp.now())
                            }
                        )
                        seq_processor.save_dataset(seq_dataset)
                        
                    except Exception as e:
                        logger.warning(f"Failed to save sequences: {e}")
                
                result = {
                    "source_dataset": dataset_name,
                    "num_structures": len(entities),
                    "num_sequences_extracted": len(extracted_sequences),
                    "chain_selection": chain_selection or "all",
                    "sequence_ids": list(extracted_sequences.keys())
                }
                
                if save_as_dataset:
                    result["saved_as_dataset"] = save_as_dataset
                    result["saved_entities"] = saved_entities
                
                if failed_extractions:
                    result["failed_extractions"] = failed_extractions
                
                return self.format_success(result)
                
            except Exception as e:
                return self.handle_error(e)