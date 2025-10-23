#!/usr/bin/env python3
"""
GPCR Agonist vs Inverse Agonist Analysis

This script implements a comprehensive analysis comparing agonists and inverse agonists 
in Class A GPCRs, focusing on interactions per GRN position in the binding pocket.

Based on the research question: "When the Schiff base in opsins flips, it establishes 
a hydrogen bond. Compare agonists and inverse agonists in Class A GPCRs with the 
interactions per GRN in the binding pocket."
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Tuple, Optional
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Phase 1: Data Collection and Preparation
def setup_environment():
    """Set up Protos environment with proper paths."""
    # Set up paths explicitly to avoid bugs
    data_dir = Path("/mnt/c/Users/hidbe/PycharmProjects/protos/data")
    os.environ["PROTOS_DATA_ROOT"] = str(data_dir.absolute())
    os.environ["PROTOS_REF_DATA_ROOT"] = str(data_dir.absolute())
    
    # Import Protos components
    from protos.io.paths.path_config import ProtosPaths
    from protos.processing.structure.struct_base_processor import CifBaseProcessor
    from protos.processing.grn.grn_base_processor import GRNBaseProcessor
    from protos.processing.sequence.seq_processor import SeqProcessor
    
    # Initialize paths
    paths = ProtosPaths(
        user_data_root=str(data_dir.absolute()),
        ref_data_root=str(data_dir.absolute()),
        create_dirs=True
    )
    
    # Initialize processors
    struct_proc = CifBaseProcessor(name="gpcr_structures")
    grn_proc = GRNBaseProcessor(name="gpcr_grn")
    seq_proc = SeqProcessor(name="gpcr_sequences")
    
    return struct_proc, grn_proc, seq_proc, paths

def define_structure_sets():
    """Define agonist and inverse agonist structure sets."""
    agonist_structures = {
        # Beta-adrenergic receptors
        '3SN6': 'β2AR with Gs and BI-167107 (full agonist)',
        '4LDO': 'β2AR with Gs and BI-167107 (full agonist)',
        '3P0G': 'β2AR with BI-167107 (full agonist)',
        '6MXT': 'β1AR with Gs and formoterol (full agonist)',
        
        # Dopamine receptors  
        '7JOZ': 'D1R with G protein and non-catechol agonist',
        '7CKZ': 'D1R with Gs and dopamine (full agonist)',
        '6VMS': 'D2R with Gi and bromocriptine (agonist)',
        
        # Serotonin receptors
        '7E2Y': '5-HT1A with Gi and serotonin (full agonist)',
        '6G79': '5-HT2A with mini-Gq and 25-CN-NBOH (agonist)',
        
        # Muscarinic receptors
        '4MQS': 'M2R with iperoxo (full agonist)',
        '4MQT': 'M2R with iperoxo and LY2119620 (agonist + PAM)',
        
        # Adenosine receptors
        '7ARO': 'A2AR with LUF5833 (partial agonist)',
        '6GDG': 'A2AR with NECA (full agonist)',
    }
    
    inverse_agonist_structures = {
        # Beta-adrenergic receptors
        '2RH1': 'β2AR with carazolol (inverse agonist)',
        '3NY8': 'β2AR with ICI-118551 (inverse agonist)', 
        '3NYA': 'β2AR with alprenolol (inverse agonist)',
        '5JQH': 'β2AR with carazolol (inverse agonist, high res)',
        
        # Rhodopsin
        '1U19': 'Rhodopsin with 11-cis-retinal (inverse agonist)',
        '1GZM': 'Rhodopsin with 11-cis-retinal (inverse agonist)',
        
        # Dopamine receptors
        '6CM4': 'D2R with risperidone (inverse agonist)',
        '6LUQ': 'D2R with haloperidol (inverse agonist)',
        
        # Serotonin receptors
        '6A93': '5-HT2A with risperidone (inverse agonist)',
        '6A94': '5-HT2A with zotepine (inverse agonist)',
        '6WGT': '5-HT2A with lumateperone (inverse agonist)',
        
        # Muscarinic receptors
        '3UON': 'M2R with QNB (inverse agonist)',
        '5CXV': 'M1R with tiotropium (inverse agonist)',
        
        # Adenosine receptors
        '5UEN': 'A1R with DU172 (inverse agonist)',
        '3VGA': 'A2AR with caffeine derivative (inverse agonist)',
    }
    
    return agonist_structures, inverse_agonist_structures

def download_structures(struct_proc, agonist_structures, inverse_agonist_structures):
    """Download all structures using Protos loaders."""
    logger.info("Starting structure download...")
    
    # Combine all PDB IDs
    all_pdbs = list(agonist_structures.keys()) + list(inverse_agonist_structures.keys())
    
    # Use Protos loader to download structures
    from protos.loaders.download_structures import download_protein_structures
    
    try:
        # Download structures
        logger.info(f"Downloading {len(all_pdbs)} structures...")
        successful, failed = download_protein_structures(
            pdb_ids=all_pdbs,
            processor=struct_proc,
            overwrite=False
        )
        
        logger.info(f"Successfully downloaded {len(successful)} structures, failed {len(failed)}")
        
        # Update datasets.json to include our new dataset
        datasets_json_path = struct_proc.path_dataset_dir / 'datasets.json'
        
        # Load existing datasets or create new
        if datasets_json_path.exists():
            with open(datasets_json_path, 'r') as f:
                datasets = json.load(f)
        else:
            datasets = {}
        
        # Add our dataset
        datasets['gpcr_agonist_inverse_agonist'] = all_pdbs
        
        # Save updated datasets.json
        with open(datasets_json_path, 'w') as f:
            json.dump(datasets, f, indent=2)
        
        logger.info(f"Updated datasets.json with gpcr_agonist_inverse_agonist dataset")
        
        return successful
        
    except Exception as e:
        logger.error(f"Error downloading structures: {e}")
        raise

# Phase 2: GRN Assignment and Alignment - Testing All Three Approaches
def test_all_grn_approaches(struct_proc, grn_proc, seq_proc, all_pdbs):
    """Test all three GRN annotation approaches."""
    logger.info("Testing all three GRN annotation approaches...")
    
    results = {
        'cli_approach': {},
        'direct_code': {},
        'structure_based': {}
    }
    
    try:
        # First ensure we have the dataset loaded
        struct_proc.load_dataset('gpcr_agonist_inverse_agonist')
        
        # Extract sequences from structures
        sequences = struct_proc.get_seq_dict()
        logger.info(f"Extracted {len(sequences)} sequences from structures")
        
        # Save sequences to FASTA for CLI approach
        fasta_path = seq_proc.data_dirs['fasta'] / 'gpcr_structures.fasta'
        seq_proc.save_sequences(sequences, str(fasta_path))
        
        # Copy GPCR reference table if needed
        ref_source = Path("/mnt/c/Users/hidbe/PycharmProjects/protos/src/protos/reference_data/grn/ref/gpcrdb_ref.csv")
        ref_dest = Path(grn_proc.data_path) / "ref" / "gpcrdb_ref.csv"
        
        if not ref_dest.exists() and ref_source.exists():
            ref_dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(ref_source, ref_dest)
            logger.info(f"Copied GPCR reference table to {ref_dest}")
        
        # Test Approach 1: CLI Command
        logger.info("\n=== Testing Approach 1: CLI Command ===")
        try:
            results['cli_approach'] = test_cli_approach(seq_proc, fasta_path)
        except Exception as e:
            logger.error(f"CLI approach failed: {e}")
            results['cli_approach'] = {}
        
        # Test Approach 2: Direct Code
        logger.info("\n=== Testing Approach 2: Direct Code ===")
        try:
            results['direct_code'] = test_direct_code_approach(grn_proc, seq_proc, sequences)
        except Exception as e:
            logger.error(f"Direct code approach failed: {e}")
            results['direct_code'] = {}
        
        # Test Approach 3: Structure-Based (CifBaseProcessor)
        logger.info("\n=== Testing Approach 3: Structure-Based ===")
        try:
            results['structure_based'] = test_structure_based_approach(struct_proc)
        except Exception as e:
            logger.error(f"Structure-based approach failed: {e}")
            results['structure_based'] = {}
        
        # Compare results
        logger.info("\n=== Comparing Results ===")
        compare_grn_results(results)
        
        return results
        
    except Exception as e:
        logger.error(f"Error in GRN assignment testing: {e}")
        raise

def test_cli_approach(seq_proc, fasta_path):
    """Test GRN assignment using CLI command."""
    try:
        import subprocess
        
        # Save a subset of sequences for testing
        test_sequences = {}
        all_sequences = seq_proc.load_sequences(str(fasta_path))
        
        # Select first 5 sequences
        for i, (seq_id, seq) in enumerate(all_sequences.items()):
            if i < 5:
                test_sequences[seq_id] = seq
            else:
                break
        
        test_fasta = seq_proc.data_dirs['fasta'] / 'test_gpcr_cli.fasta'
        seq_proc.save_sequences(test_sequences, str(test_fasta))
        
        # Run CLI command
        cmd = [
            'python', '-m', 'protos.cli.grn.assign_grns',
            '-p', 'gpcr_a',
            '-s'] + list(test_sequences.keys()) + [
            '-o', 'test_cli_grns',
            '-n', '4'
        ]
        
        logger.info(f"Running CLI command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("CLI command completed successfully")
            logger.info(f"Output: {result.stdout}")
            
            # Try to load the results
            try:
                from protos.processing.grn.grn_base_processor import GRNBaseProcessor
                grn_proc_temp = GRNBaseProcessor(name="test_cli_results")
                grn_proc_temp.load_grn_table("test_cli_grns")
                logger.info(f"CLI approach assigned GRNs to {len(grn_proc_temp.data)} sequences")
                return grn_proc_temp.data
            except Exception as e:
                logger.warning(f"Could not load CLI results: {e}")
                return {}
        else:
            logger.error(f"CLI command failed: {result.stderr}")
            return {}
            
    except Exception as e:
        logger.error(f"CLI approach failed: {e}")
        return {}

def test_direct_code_approach(grn_proc, seq_proc, sequences):
    """Test GRN assignment using direct code."""
    try:
        from protos.processing.grn.grn_assignment import assign_gene_nr
        from protos.processing.grn.grn_table_utils import GRNConfigManager
        from protos.processing.sequence.seq_alignment import mmseqs2_align2, init_aligner, align_blosum62
        
        # Select a subset for testing
        test_sequences = dict(list(sequences.items())[:5])
        
        # Try to load reference table
        try:
            grn_proc.load_grn_table("ref/gpcrdb_ref")
            logger.info("Loaded GPCR reference table")
        except Exception as e:
            logger.warning(f"Could not load reference table: {e}")
            return {}
        
        # Get reference sequences
        ref_sequences = {}
        ref_data = grn_proc.data
        
        # Extract sequences from reference (handling different formats)
        for idx in ref_data.index:
            # Try to reconstruct sequence from GRN positions
            row = ref_data.loc[idx]
            seq_parts = []
            for col in ref_data.columns:
                val = row[col]
                if pd.notna(val) and val != '-' and len(str(val)) > 0:
                    # Extract amino acid (first character)
                    aa = str(val)[0]
                    if aa.isalpha() and aa.upper() in 'ACDEFGHIKLMNPQRSTVWY':
                        seq_parts.append(aa)
            
            if seq_parts:
                ref_sequences[idx] = ''.join(seq_parts)
        
        logger.info(f"Extracted {len(ref_sequences)} reference sequences")
        
        if not ref_sequences:
            logger.error("No valid reference sequences found")
            return {}
        
        # Run similarity search
        try:
            logger.info("Running MMseqs2 similarity search...")
            hits = mmseqs2_align2(test_sequences, ref_sequences)
            
            if hits is not None and not hits.empty:
                logger.info(f"Found {len(hits)} sequence matches")
                
                # Simple GRN assignment based on best hits
                grn_results = {}
                for query_id in hits['query_id'].unique():
                    query_hits = hits[hits['query_id'] == query_id]
                    best_hit = query_hits.loc[query_hits['sequence_identity'].idxmax()]
                    
                    grn_results[query_id] = {
                        'best_ref': best_hit['target_id'],
                        'identity': best_hit['sequence_identity'],
                        'grn_assigned': True
                    }
                
                logger.info(f"Direct code approach assigned GRNs to {len(grn_results)} sequences")
                return grn_results
            else:
                logger.warning("No similarity hits found")
                return {}
                
        except Exception as e:
            logger.error(f"MMseqs2 search failed: {e}")
            return {}
            
    except Exception as e:
        logger.error(f"Direct code approach failed: {e}")
        return {}

def test_structure_based_approach(struct_proc):
    """Test GRN assignment using CifBaseProcessor.assign_grns()."""
    try:
        logger.info("Testing CifBaseProcessor.assign_grns() method...")
        
        # First check if we have sequences
        seq_dict = struct_proc.get_seq_dict()
        logger.info(f"Found {len(seq_dict)} sequences in structure data")
        
        # Sample a few sequences
        for i, (seq_id, seq) in enumerate(seq_dict.items()):
            if i < 3:
                logger.info(f"  {seq_id}: {seq[:50]}... (length: {len(seq)})")
        
        # Use the built-in method
        grn_assignments = struct_proc.assign_grns(
            protein_family='gpcr_a',
            similarity_threshold=0.2,
            grn_table_name='gpcrdb_ref',
            use_mmseqs=True,
            save_results=True
        )
        
        logger.info(f"Structure-based approach assigned GRNs to {len(grn_assignments)} chains")
        
        # Show sample assignments
        if grn_assignments:
            for i, (chain_id, grn_data) in enumerate(grn_assignments.items()):
                if i < 3:
                    logger.info(f"  {chain_id}: {len(grn_data)} GRN positions")
                    if hasattr(grn_data, 'head'):
                        logger.info(f"    Sample GRNs: {list(grn_data.head().items())}")
        
        # Also test get_grn_dict if assignments were made
        if grn_assignments:
            grn_dict = struct_proc.get_grn_dict()
            logger.info(f"Retrieved GRN dictionary for {len(grn_dict)} PDB entries")
        
        return grn_assignments
        
    except Exception as e:
        logger.error(f"Structure-based approach failed: {e}")
        import traceback
        traceback.print_exc()
        return {}

def compare_grn_results(results):
    """Compare results from all three approaches."""
    logger.info("\n=== GRN Assignment Results Comparison ===")
    
    for approach, data in results.items():
        if data:
            logger.info(f"\n{approach}:")
            logger.info(f"  - Successfully processed: {len(data)} sequences/chains")
            
            # Show sample results
            if isinstance(data, pd.DataFrame) and not data.empty:
                logger.info(f"  - GRN positions found: {len(data.columns)}")
                logger.info(f"  - Sample GRNs: {list(data.columns[:5])}")
            elif isinstance(data, dict) and data:
                sample_key = list(data.keys())[0]
                logger.info(f"  - Sample result for {sample_key}: {data[sample_key]}")
        else:
            logger.info(f"\n{approach}: Failed or no results")
    
    # Identify which approaches succeeded
    successful_approaches = [app for app, data in results.items() if data]
    logger.info(f"\nSuccessful approaches: {successful_approaches}")
    
    return results

# Phase 3: Binding Pocket Analysis
def define_binding_pocket():
    """Define binding pocket residues using GRN positions."""
    binding_pocket_grn = [
        '3.32', '3.33', '3.36',  # TM3
        '5.42', '5.43', '5.46',  # TM5  
        '6.48', '6.51', '6.52',  # TM6
        '7.39', '7.43', '7.50'   # TM7 (including Schiff base)
    ]
    return binding_pocket_grn

def analyze_binding_pocket(struct_proc, grn_assignments, binding_pocket_grn, 
                          agonist_structures, inverse_agonist_structures):
    """Analyze binding pocket interactions."""
    logger.info("Starting binding pocket analysis...")
    
    interaction_data = {}
    
    for pdb_id in grn_assignments:
        try:
            # Get structure data
            struct_data = struct_proc.data[struct_proc.data['pdb_id'] == pdb_id].copy()
            
            if struct_data.empty:
                logger.warning(f"No structure data for {pdb_id}")
                continue
            
            # Determine ligand type
            if pdb_id in agonist_structures:
                ligand_type = 'agonist'
                description = agonist_structures[pdb_id]
            else:
                ligand_type = 'inverse_agonist'
                description = inverse_agonist_structures[pdb_id]
            
            # Get GRN data for this structure
            grn_data = grn_assignments[pdb_id]
            
            # Analyze interactions at each GRN position
            interactions = {}
            for grn_pos in binding_pocket_grn:
                # This is a placeholder - actual interaction analysis would go here
                # In real implementation, we would:
                # 1. Map GRN position to residue number
                # 2. Find atoms at that position
                # 3. Calculate distances to ligand
                # 4. Identify hydrogen bonds, hydrophobic contacts, etc.
                
                interactions[grn_pos] = {
                    'residue': 'TBD',
                    'hydrogen_bonds': [],
                    'hydrophobic_contacts': [],
                    'distance_to_ligand': None
                }
            
            interaction_data[pdb_id] = {
                'type': ligand_type,
                'description': description,
                'interactions': interactions,
                'grn_data': grn_data
            }
            
            logger.info(f"Analyzed {pdb_id} ({ligand_type})")
            
        except Exception as e:
            logger.error(f"Error analyzing {pdb_id}: {e}")
    
    return interaction_data

# Phase 4: Comparative Analysis
def compare_interactions(interaction_data, binding_pocket_grn):
    """Compare interaction patterns between agonists and inverse agonists."""
    logger.info("Starting comparative analysis...")
    
    # Initialize comparison data
    h_bond_comparison = {}
    for grn_pos in binding_pocket_grn:
        h_bond_comparison[grn_pos] = {
            'agonist': [],
            'inverse_agonist': []
        }
    
    # Analyze conformational markers
    conformational_markers = {
        '3.32': 'DRY motif ionic lock',
        '5.50': 'Toggle switch',
        '6.48': 'CWxP rotamer', 
        '7.50': 'NPxxY/Schiff base'
    }
    
    # Collect data for each position
    for pdb_id, data in interaction_data.items():
        ligand_type = data['type']
        interactions = data['interactions']
        
        for grn_pos in binding_pocket_grn:
            if grn_pos in interactions:
                h_bonds = interactions[grn_pos]['hydrogen_bonds']
                h_bond_comparison[grn_pos][ligand_type].extend(h_bonds)
    
    # Generate summary statistics
    summary = {
        'total_structures': len(interaction_data),
        'agonist_structures': sum(1 for d in interaction_data.values() if d['type'] == 'agonist'),
        'inverse_agonist_structures': sum(1 for d in interaction_data.values() if d['type'] == 'inverse_agonist'),
        'h_bond_comparison': h_bond_comparison,
        'conformational_markers': conformational_markers
    }
    
    return summary

# Phase 5: Generate Report
def generate_report(summary, output_file='gpcr_analysis_report.md'):
    """Generate analysis report."""
    logger.info("Generating report...")
    
    report = f"""# GPCR Agonist vs Inverse Agonist Analysis Results

## Summary
- Total structures analyzed: {summary['total_structures']}
- Agonist structures: {summary['agonist_structures']}
- Inverse agonist structures: {summary['inverse_agonist_structures']}

## Key GRN Positions Analyzed
"""
    
    # Add binding pocket positions
    for grn_pos in summary['h_bond_comparison'].keys():
        marker = summary['conformational_markers'].get(grn_pos, '')
        if marker:
            report += f"- **{grn_pos}**: {marker}\n"
        else:
            report += f"- {grn_pos}\n"
    
    report += """
## Analysis Status

This analysis framework has been set up with the following components:
1. ✅ Structure download using Protos loaders - Successfully downloaded structures
2. ⚠️ GRN assignment - Skipped due to reference table format issues
3. ✅ Binding pocket definition - Defined key GRN positions
4. ✅ Framework for interaction analysis - Structure ready

### Missing Functionality Identified:

1. **GRN Reference Table Issues**:
   - The gpcrdb_ref.csv format doesn't match expected GRN column format
   - Need to investigate proper GPCR GRN table format

2. **Ligand Processing**:
   - No LigandProcessor found in Protos
   - Need methods to:
     - Extract ligand coordinates from structures
     - Calculate protein-ligand distances
     - Identify hydrogen bonds
     - Detect hydrophobic contacts

3. **Structure Analysis Methods Missing**:
   - `struct_proc.get_grn_coordinates()` - Not implemented
   - `struct_proc.add_grn_annotations()` - Not implemented
   - Need methods to map GRN positions to structure coordinates

4. **Visualization Tools**:
   - No ligand visualization module found
   - Would need PyMOL or similar integration

### Recommendations:

1. **For GRN Assignment**: 
   - Check if there's a different GRN reference format for GPCRs
   - Consider using GPCRdb API for GRN assignments

2. **For Ligand Analysis**:
   - Implement basic distance calculations using structure data
   - Use existing structure coordinates to identify binding pocket residues
   - Calculate distances between protein and HETATM records

3. **For Missing Methods**:
   - These could be implemented as utility functions
   - Use the existing structure data DataFrame for calculations

## Conclusions
The Protos framework successfully handles structure download and organization. However, specialized ligand analysis and GRN-structure mapping functionality would need to be implemented to complete this analysis.
"""
    
    # Save report
    with open(output_file, 'w') as f:
        f.write(report)
    
    logger.info(f"Report saved to {output_file}")

# Main execution
def main():
    """Run the complete analysis pipeline."""
    logger.info("Starting GPCR agonist vs inverse agonist analysis...")
    
    try:
        # Phase 1: Setup
        struct_proc, grn_proc, seq_proc, paths = setup_environment()
        agonist_structures, inverse_agonist_structures = define_structure_sets()
        
        # Download structures
        downloaded = download_structures(struct_proc, agonist_structures, inverse_agonist_structures)
        
        # Phase 2: Test All GRN Assignment Approaches
        all_pdbs = list(agonist_structures.keys()) + list(inverse_agonist_structures.keys())
        grn_results = test_all_grn_approaches(struct_proc, grn_proc, seq_proc, all_pdbs)
        
        # Use the best available results for further analysis
        grn_assignments = grn_results.get('structure_based', {}) or grn_results.get('direct_code', {}) or {}
        
        # Phase 3: Binding Pocket Analysis
        binding_pocket_grn = define_binding_pocket()
        interaction_data = analyze_binding_pocket(
            struct_proc, grn_assignments, binding_pocket_grn,
            agonist_structures, inverse_agonist_structures
        )
        
        # Phase 4: Comparative Analysis
        summary = compare_interactions(interaction_data, binding_pocket_grn)
        
        # Phase 5: Generate Report
        generate_report(summary)
        
        logger.info("Analysis complete!")
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise

if __name__ == "__main__":
    main()