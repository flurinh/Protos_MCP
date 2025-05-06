from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Union, Tuple
import requests
from pathlib import Path
import tempfile
import shutil
import json


# Define context types for type safety
@dataclass
class ProtosContext:
    """Typed context for our protos application"""
    processors: Dict[str, Any]  # Store processor instances
    initialized: bool
    base_path: Optional[str]
    data: Dict[str, pd.DataFrame]  # Store data frames
    sequences: Dict[str, Dict[str, str]]  # Store sequences
    datasets: Dict[str, List[str]]  # Store datasets

# Lifespan management for our MCP server
@asynccontextmanager
async def protos_lifespan(server: FastMCP) -> AsyncIterator[ProtosContext]:
    """Manage protos lifecycle with persistent state"""
    # Initialize on startup
    print("Initializing protos context", file=sys.stderr)
    context = ProtosContext(
        processors={},
        initialized=False,
        base_path=None,
        data={},
        sequences={},
        datasets={}
    )

    try:
        yield context
    finally:
        # Cleanup on shutdown
        print("Cleaning up protos resources", file=sys.stderr)
        # Perform any necessary cleanup here

# Create our MCP server with the lifespan context
mcp = FastMCP("ProtosServer", lifespan=protos_lifespan)

@mcp.tool()
def say_hello() -> str:
    return "Hey there"

@mcp.tool()
def import_protos(ctx: Context) -> str:
    """Import the protos library and verify it works"""
    try:
        import protos
        return f"Successfully imported protos library. Version: {protos.__version__ if hasattr(protos, '__version__') else 'unknown'}"
    except ImportError as e:
        return f"Failed to import protos: {str(e)}"


@mcp.tool()
def initialize_folders(ctx: Context, base_path: Optional[str] = None) -> str:
    """Initialize the folder structure required by protos"""
    protos_ctx = ctx.request_context.lifespan_context

    try:
        # Import protos
        import protos

        if base_path is None:
            base_path = Path(__file__).parent / "data"
        else:
            base_path = Path(base_path)

        # Set the context base path
        protos_ctx.base_path = base_path

        # Create main directory structure
        os.makedirs(protos_ctx.base_path, exist_ok=True)

        # Create subdirectories based on the test files
        subdirs = [
            "structure/mmcif",
            "structure/alphafold_structures",
            "structure/structure_dataset",
            "sequence/fasta",
            "sequence/metadata"
        ]

        # Create each subdirectory
        for subdir in subdirs:
            os.makedirs(os.path.join(protos_ctx.base_path, subdir), exist_ok=True)

        protos_ctx.initialized = True
        return f"Folder structure initialized at: {protos_ctx.base_path}"
    except Exception as e:
        return f"Failed to initialize folder structure: {str(e)}"


@mcp.tool()
def download_pdb_structure(ctx: Context, pdb_id: str, target_folder: Optional[str] = None) -> str:
    """Download a protein structure from PDB in mmCIF format"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Determine target folder
        if target_folder is None:
            target_folder = os.path.join(protos_ctx.base_path, "structure/mmcif")

        # Ensure target folder exists
        os.makedirs(target_folder, exist_ok=True)

        # Normalize PDB ID to lowercase
        pdb_id = pdb_id.lower()

        # Define target file path
        file_path = os.path.join(target_folder, f"{pdb_id}.cif")

        # Download from PDB
        url = f"https://files.rcsb.org/download/{pdb_id}.cif"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Save the file
        with open(file_path, 'wb') as f:
            f.write(response.content)

        return f"Successfully downloaded {pdb_id} to {file_path}"
    except Exception as e:
        return f"Failed to download PDB structure {pdb_id}: {str(e)}"


@mcp.tool()
def download_alphafold_structure(ctx: Context, uniprot_id: str, model_version: int = 1) -> str:
    """Download an AlphaFold predicted structure for a UniProt ID"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Determine target folder
        target_folder = os.path.join(protos_ctx.base_path, "structure/alphafold_structures")

        # Ensure target folder exists
        os.makedirs(target_folder, exist_ok=True)

        # Define target file path
        file_path = os.path.join(target_folder, f"AF-{uniprot_id}-F1-model_v{model_version}.cif")

        # Download from AlphaFold DB
        url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v{model_version}.cif"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Save the file
        with open(file_path, 'wb') as f:
            f.write(response.content)

        return f"Successfully downloaded AlphaFold structure for {uniprot_id} (model version {model_version}) to {file_path}"
    except Exception as e:
        return f"Failed to download AlphaFold structure for {uniprot_id}: {str(e)}"


@mcp.tool()
def map_uniprot_to_pdb(ctx: Context, uniprot_ids: List[str]) -> str:
    """Map UniProt IDs to PDB IDs using the UniProt API"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Define the mapping results
        mapping_results = []

        # Process each UniProt ID
        for uid in uniprot_ids:
            # Query the UniProt API for PDB mappings
            url = f"https://rest.uniprot.org/uniprotkb/{uid}.json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Extract PDB IDs from response
            pdb_ids = []
            if "dbReferences" in data:
                for ref in data["dbReferences"]:
                    if ref.get("type") == "PDB":
                        pdb_ids.append(ref.get("id", "").lower())

            # Add to results
            if pdb_ids:
                for pdb_id in pdb_ids:
                    mapping_results.append({"uid": uid, "pdb_id": pdb_id})

        # Convert results to DataFrame
        if mapping_results:
            df = pd.DataFrame(mapping_results)

            # Store the mapping in context
            protos_ctx.data["uniprot_pdb_mapping"] = df

            # Return a summary
            return f"Found {len(df)} PDB mappings for {len(uniprot_ids)} UniProt IDs.\n" + \
                f"Mapping summary:\n{df.to_string(index=False)}"
        else:
            return f"No PDB mappings found for the provided UniProt IDs"
    except Exception as e:
        return f"Failed to map UniProt IDs to PDB IDs: {str(e)}"


@mcp.tool()
def download_uniprot_sequence(ctx: Context, uniprot_id: str) -> str:
    """Download a protein sequence from UniProt"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Determine target folder
        fasta_dir = os.path.join(protos_ctx.base_path, "sequence/fasta")

        # Ensure target folder exists
        os.makedirs(fasta_dir, exist_ok=True)

        # Define target file path
        file_path = os.path.join(fasta_dir, f"{uniprot_id}.fasta")

        # Download from UniProt
        url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.fasta"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Save the file
        with open(file_path, 'w') as f:
            f.write(response.text)

        # Parse the FASTA file and store in context
        if uniprot_id not in protos_ctx.sequences:
            protos_ctx.sequences[uniprot_id] = {}

        lines = response.text.strip().split('\n')
        header = lines[0]
        sequence = ''.join(lines[1:])

        protos_ctx.sequences[uniprot_id] = {
            "header": header,
            "sequence": sequence
        }

        return f"Successfully downloaded sequence for {uniprot_id} to {file_path}"
    except Exception as e:
        return f"Failed to download UniProt sequence {uniprot_id}: {str(e)}"


@mcp.tool()
def read_fasta(ctx: Context, file_path: str) -> str:
    """Read and parse a FASTA file"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if file exists
        if not os.path.exists(file_path):
            # Try to resolve relative path
            absolute_path = os.path.join(protos_ctx.base_path, "sequence/fasta", file_path)
            if not os.path.exists(absolute_path):
                return f"Error: FASTA file not found at {file_path} or {absolute_path}"
            file_path = absolute_path

        # Read the file
        with open(file_path, 'r') as f:
            content = f.read()

        # Parse FASTA
        sequences = {}
        current_id = None
        current_seq = []

        for line in content.strip().split('\n'):
            if line.startswith('>'):
                if current_id is not None:
                    sequences[current_id] = ''.join(current_seq)
                current_id = line[1:].strip()
                current_seq = []
            else:
                current_seq.append(line.strip())

        if current_id is not None:
            sequences[current_id] = ''.join(current_seq)

        # Store in context
        fasta_name = os.path.basename(file_path)
        protos_ctx.sequences[fasta_name] = sequences

        # Return summary
        return f"Read {len(sequences)} sequences from {file_path}:\n" + \
            "\n".join([f"{id}: {seq[:50]}..." if len(seq) > 50 else f"{id}: {seq}"
                       for id, seq in sequences.items()])
    except Exception as e:
        return f"Failed to read FASTA file: {str(e)}"


@mcp.tool()
def write_fasta(ctx: Context, file_path: str, sequences: Dict[str, str]) -> str:
    """Write sequences to a FASTA file"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Determine target directory
        directory = os.path.dirname(file_path)
        if not directory:
            # If no directory specified, use the default
            file_path = os.path.join(protos_ctx.base_path, "sequence/fasta", file_path)
            directory = os.path.dirname(file_path)

        # Ensure directory exists
        os.makedirs(directory, exist_ok=True)

        # Write FASTA file
        with open(file_path, 'w') as f:
            for seq_id, sequence in sequences.items():
                f.write(f">{seq_id}\n")
                # Write sequence in chunks of 60 characters
                for i in range(0, len(sequence), 60):
                    f.write(f"{sequence[i:i + 60]}\n")

        return f"Successfully wrote {len(sequences)} sequences to {file_path}"
    except Exception as e:
        return f"Failed to write FASTA file: {str(e)}"


@mcp.tool()
def clean_sequence(ctx: Context, sequence: str) -> str:
    """Clean a protein sequence by removing whitespace and invalid characters"""
    try:
        # Remove whitespace
        cleaned = ''.join(sequence.split())

        # Convert to uppercase
        cleaned = cleaned.upper()

        # Keep only valid amino acid characters
        valid_chars = set("ACDEFGHIKLMNPQRSTVWYX")
        cleaned = ''.join(char for char in cleaned if char in valid_chars)

        return f"Original length: {len(sequence)}\nCleaned length: {len(cleaned)}\nCleaned sequence: {cleaned}"
    except Exception as e:
        return f"Failed to clean sequence: {str(e)}"


@mcp.tool()
def load_cif_structure(ctx: Context, pdb_id: str) -> str:
    """Load a CIF structure file and convert to DataFrame"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        import protos.io.cif_handler as cif_handler

        # Normalize PDB ID
        pdb_id = pdb_id.lower()

        # Determine file path
        file_path = os.path.join(protos_ctx.base_path, "structure/mmcif", f"{pdb_id}.cif")

        # Check if file exists
        if not os.path.exists(file_path):
            # Try to download it
            return f"Error: CIF file for {pdb_id} not found at {file_path}. Please download it first using download_pdb_structure."

        # Parse the CIF file using Bio.PDB
        from Bio.PDB import MMCIFParser, MMCIF2Dict

        # First try to parse as dictionary
        cif_dict = MMCIF2Dict.MMCIF2Dict(file_path)

        # Extract atom data
        atom_site = {}
        for key in cif_dict:
            if key.startswith('_atom_site.'):
                field = key.replace('_atom_site.', '')
                atom_site[field] = cif_dict[key]

        # Convert to DataFrame
        df = pd.DataFrame(atom_site)

        # Add pdb_id column
        df['pdb_id'] = pdb_id

        # Add converted columns for compatibility
        if 'auth_seq_id' not in df.columns and 'label_seq_id' in df.columns:
            df['auth_seq_id'] = df['label_seq_id']

        if 'res_name3l' not in df.columns and 'label_comp_id' in df.columns:
            df['res_name3l'] = df['label_comp_id']

        if 'auth_chain_id' not in df.columns and 'auth_asym_id' in df.columns:
            df['auth_chain_id'] = df['auth_asym_id']

        # Parse coordinates
        if 'Cartn_x' in df.columns:
            df['x'] = pd.to_numeric(df['Cartn_x'], errors='coerce')
        if 'Cartn_y' in df.columns:
            df['y'] = pd.to_numeric(df['Cartn_y'], errors='coerce')
        if 'Cartn_z' in df.columns:
            df['z'] = pd.to_numeric(df['Cartn_z'], errors='coerce')

        # Store in context
        protos_ctx.data[pdb_id] = df

        # Return summary
        return f"Loaded {len(df)} atoms from {pdb_id}.\n" + \
            f"Chains: {', '.join(sorted(df['auth_chain_id'].unique()))}\n" + \
            f"Sample data:\n{df.head().to_string()}"
    except Exception as e:
        return f"Failed to load CIF structure: {str(e)}"


@mcp.tool()
def get_chains(ctx: Context, pdb_id: str) -> str:
    """Get chains available in a PDB structure"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if structure is loaded
        if pdb_id not in protos_ctx.data:
            return f"Error: Structure {pdb_id} not loaded. Please load it first using load_cif_structure."

        # Get chains
        df = protos_ctx.data[pdb_id]
        chains = sorted(df['auth_chain_id'].unique())

        # Return summary
        return f"Found {len(chains)} chains in {pdb_id}: {', '.join(chains)}"
    except Exception as e:
        return f"Failed to get chains: {str(e)}"


@mcp.tool()
def get_sequence_from_structure(ctx: Context, pdb_id: str, chain_id: str) -> str:
    """Extract amino acid sequence from a protein structure"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if structure is loaded
        if pdb_id not in protos_ctx.data:
            return f"Error: Structure {pdb_id} not loaded. Please load it first using load_cif_structure."

        # Get data for this chain
        df = protos_ctx.data[pdb_id]
        chain_data = df[df['auth_chain_id'] == chain_id]

        if chain_data.empty:
            return f"Error: Chain {chain_id} not found in structure {pdb_id}"

        # Filter to CA atoms to get one record per residue
        ca_atoms = chain_data[chain_data['label_atom_id'] == 'CA']

        if ca_atoms.empty:
            # Try with atom_name instead
            ca_atoms = chain_data[chain_data['atom_name'] == 'CA']

        if ca_atoms.empty:
            return f"Error: No CA atoms found in chain {chain_id}"

        # Sort by residue number
        ca_atoms = ca_atoms.sort_values('auth_seq_id')

        # Extract the sequence using 3-letter codes
        res_name_col = 'res_name3l' if 'res_name3l' in ca_atoms.columns else 'label_comp_id'
        residues = ca_atoms[res_name_col].tolist()

        # Convert 3-letter codes to 1-letter codes
        aa_map = {
            'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F',
            'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L',
            'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R',
            'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y'
        }

        sequence = ''.join([aa_map.get(res, 'X') for res in residues])

        # Store in context
        key = f"{pdb_id}_{chain_id}"
        if key not in protos_ctx.sequences:
            protos_ctx.sequences[key] = {}

        protos_ctx.sequences[key] = {
            "sequence": sequence,
            "source": f"{pdb_id} chain {chain_id}"
        }

        return f"Extracted sequence from {pdb_id} chain {chain_id} ({len(sequence)} residues):\n{sequence}"
    except Exception as e:
        return f"Failed to extract sequence: {str(e)}"


@mcp.tool()
def get_ca_coordinates(ctx: Context, pdb_id: str, chain_id: str) -> str:
    """Extract CA atom coordinates from a protein structure"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if structure is loaded
        if pdb_id not in protos_ctx.data:
            return f"Error: Structure {pdb_id} not loaded. Please load it first using load_cif_structure."

        # Get data for this chain
        df = protos_ctx.data[pdb_id]
        chain_data = df[df['auth_chain_id'] == chain_id]

        if chain_data.empty:
            return f"Error: Chain {chain_id} not found in structure {pdb_id}"

        # Filter to CA atoms
        ca_atoms = chain_data[chain_data['label_atom_id'] == 'CA']

        if ca_atoms.empty:
            # Try with atom_name instead
            ca_atoms = chain_data[chain_data['atom_name'] == 'CA']

        if ca_atoms.empty:
            return f"Error: No CA atoms found in chain {chain_id}"

        # Sort by residue number
        ca_atoms = ca_atoms.sort_values('auth_seq_id')

        # Extract coordinates
        coords = ca_atoms[['x', 'y', 'z']].values

        # Format coordinates as string
        coord_str = "\n".join([f"Residue {idx + 1}: ({x:.3f}, {y:.3f}, {z:.3f})"
                               for idx, (x, y, z) in enumerate(coords)])

        return f"Extracted {len(coords)} CA coordinates from {pdb_id} chain {chain_id}:\n{coord_str}"
    except Exception as e:
        return f"Failed to extract coordinates: {str(e)}"


@mcp.tool()
def create_dataset(ctx: Context, dataset_id: str, name: str, description: str, content: List[str]) -> str:
    """Create a dataset of protein structures"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Store dataset in context
        protos_ctx.datasets[dataset_id] = {
            "id": dataset_id,
            "name": name,
            "description": description,
            "content": content
        }

        # Write dataset file
        dataset_dir = os.path.join(protos_ctx.base_path, "structure/structure_dataset")
        os.makedirs(dataset_dir, exist_ok=True)

        file_path = os.path.join(dataset_dir, f"{dataset_id}.json")

        with open(file_path, 'w') as f:
            json.dump(protos_ctx.datasets[dataset_id], f, indent=2)

        return f"Created dataset {dataset_id} with {len(content)} entries and saved to {file_path}"
    except Exception as e:
        return f"Failed to create dataset: {str(e)}"


@mcp.tool()
def list_datasets(ctx: Context) -> str:
    """List available datasets"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check datasets in context
        if not protos_ctx.datasets:
            # Try to load from files
            dataset_dir = os.path.join(protos_ctx.base_path, "structure/structure_dataset")

            if not os.path.exists(dataset_dir):
                return "No datasets found"

            # List JSON files
            dataset_files = [f for f in os.listdir(dataset_dir) if f.endswith('.json')]

            if not dataset_files:
                return "No dataset files found"

            # Load each dataset
            for file_name in dataset_files:
                file_path = os.path.join(dataset_dir, file_name)

                with open(file_path, 'r') as f:
                    dataset = json.load(f)

                dataset_id = dataset.get("id", os.path.splitext(file_name)[0])
                protos_ctx.datasets[dataset_id] = dataset

        # Format dataset info
        if not protos_ctx.datasets:
            return "No datasets found"

        dataset_info = []
        for dataset_id, dataset in protos_ctx.datasets.items():
            name = dataset.get("name", dataset_id)
            description = dataset.get("description", "No description")
            content = dataset.get("content", [])

            dataset_info.append(f"ID: {dataset_id}")
            dataset_info.append(f"Name: {name}")
            dataset_info.append(f"Description: {description}")
            dataset_info.append(f"Entries: {len(content)}")
            dataset_info.append("")

        return "\n".join(dataset_info)
    except Exception as e:
        return f"Failed to list datasets: {str(e)}"


@mcp.tool()
def load_dataset(ctx: Context, dataset_id: str) -> str:
    """Load structures from a dataset"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if dataset exists
        if dataset_id not in protos_ctx.datasets:
            # Try to load from file
            dataset_dir = os.path.join(protos_ctx.base_path, "structure/structure_dataset")
            file_path = os.path.join(dataset_dir, f"{dataset_id}.json")

            if not os.path.exists(file_path):
                return f"Error: Dataset {dataset_id} not found"

            # Load dataset
            with open(file_path, 'r') as f:
                dataset = json.load(f)

            protos_ctx.datasets[dataset_id] = dataset

        # Get structure list
        dataset = protos_ctx.datasets[dataset_id]
        structures = dataset.get("content", [])

        if not structures:
            return f"Error: Dataset {dataset_id} has no structures"

        # Load each structure
        loaded = []
        failed = []

        for pdb_id in structures:
            try:
                # Check if already loaded
                if pdb_id in protos_ctx.data:
                    loaded.append(pdb_id)
                    continue

                # Try to load
                file_path = os.path.join(protos_ctx.base_path, "structure/mmcif", f"{pdb_id}.cif")

                if not os.path.exists(file_path):
                    failed.append(f"{pdb_id} (file not found)")
                    continue

                # Load with load_cif_structure
                result = load_cif_structure(ctx, pdb_id)

                if "Error" in result:
                    failed.append(f"{pdb_id} (parsing error)")
                else:
                    loaded.append(pdb_id)
            except Exception as e:
                failed.append(f"{pdb_id} ({str(e)})")

        # Return summary
        return f"Loaded {len(loaded)} structures from dataset {dataset_id}.\n" + \
            f"Successfully loaded: {', '.join(loaded)}\n" + \
            (f"Failed to load: {', '.join(failed)}" if failed else "All structures loaded successfully.")
    except Exception as e:
        return f"Failed to load dataset: {str(e)}"


@mcp.tool()
def find_binding_pocket(ctx: Context, pdb_id: str, chain_id: str, distance_cutoff: float = 10.0) -> str:
    """Find binding pocket residues in a protein structure"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Check if structure is loaded
        if pdb_id not in protos_ctx.data:
            return f"Error: Structure {pdb_id} not loaded. Please load it first using load_cif_structure."

        # Get data for this structure
        df = protos_ctx.data[pdb_id]

        # Check if chain exists
        if chain_id not in df['auth_chain_id'].unique():
            return f"Error: Chain {chain_id} not found in structure {pdb_id}"

        # Get chain atoms
        chain_atoms = df[df['auth_chain_id'] == chain_id]

        # Get non-chain atoms (potential ligands)
        non_chain_atoms = df[df['auth_chain_id'] != chain_id]

        if non_chain_atoms.empty:
            return f"No potential ligands found in structure {pdb_id}"

        # Find binding pocket residues
        binding_residues = set()

        # For each chain atom, check distance to non-chain atoms
        for _, chain_atom in chain_atoms.iterrows():
            chain_coords = np.array([chain_atom['x'], chain_atom['y'], chain_atom['z']])

            for _, non_chain_atom in non_chain_atoms.iterrows():
                non_chain_coords = np.array([non_chain_atom['x'], non_chain_atom['y'], non_chain_atom['z']])

                # Calculate distance
                dist = np.linalg.norm(chain_coords - non_chain_coords)

                # If within cutoff, add to binding residues
                if dist <= distance_cutoff:
                    binding_residues.add(int(chain_atom['auth_seq_id']))

        if not binding_residues:
            return f"No binding pocket residues found within {distance_cutoff} Å"

        # Sort residues
        binding_residues = sorted(binding_residues)

        # Get residue types
        residue_types = {}
        for res_id in binding_residues:
            res_atoms = chain_atoms[chain_atoms['auth_seq_id'].astype(int) == res_id]
            if 'res_name3l' in res_atoms.columns:
                residue_types[res_id] = res_atoms['res_name3l'].iloc[0]
            elif 'label_comp_id' in res_atoms.columns:
                residue_types[res_id] = res_atoms['label_comp_id'].iloc[0]

        # Format results
        results = []
        for res_id in binding_residues:
            res_type = residue_types.get(res_id, "UNK")
            results.append(f"Residue {res_id} ({res_type})")

        return f"Found {len(binding_residues)} binding pocket residues in {pdb_id} chain {chain_id}:\n" + \
            "\n".join(results)
    except Exception as e:
        return f"Failed to find binding pocket: {str(e)}"


@mcp.tool()
def list_files(ctx: Context, directory: Optional[str] = None) -> str:
    """List files in a directory"""
    protos_ctx = ctx.request_context.lifespan_context

    if not protos_ctx.initialized:
        return "Error: You must initialize the folder structure first using initialize_folders"

    try:
        # Determine which directory to list
        if directory is None:
            directory = protos_ctx.base_path
        else:
            # If relative path, make it absolute
            if not os.path.isabs(directory):
                directory = os.path.join(protos_ctx.base_path, directory)

        # Check if directory exists
        if not os.path.exists(directory):
            return f"Error: Directory {directory} does not exist"

        if not os.path.isdir(directory):
            return f"Error: {directory} is not a directory"

        # List files and directories
        files = []
        subdirs = []

        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                subdirs.append(item)
            else:
                files.append(item)

        # Format results
        results = [f"Contents of {directory}:"]

        if subdirs:
            results.append("\nDirectories:")
            for subdir in sorted(subdirs):
                results.append(f"- {subdir}/")

        if files:
            results.append("\nFiles:")
            for file in sorted(files):
                results.append(f"- {file}")

        if not subdirs and not files:
            results.append("\nDirectory is empty")

        return "\n".join(results)
    except Exception as e:
        return f"Failed to list files: {str(e)}"


@mcp.tool()
def sequence_statistics(ctx: Context, sequence: str) -> str:
    """Calculate statistics for a protein sequence"""
    try:
        # Basic validation
        if not sequence:
            return "Error: Empty sequence provided"

        # Clean sequence
        sequence = ''.join(sequence.split()).upper()

        # Amino acid groups
        aa_groups = {
            'Hydrophobic': ['A', 'I', 'L', 'M', 'F', 'W', 'Y', 'V'],
            'Polar': ['N', 'C', 'Q', 'S', 'T'],
            'Acidic': ['D', 'E'],
            'Basic': ['R', 'H', 'K'],
            'Special': ['G', 'P']
        }

        # Calculate AA composition
        aa_counts = {}
        for aa in "ACDEFGHIKLMNPQRSTVWY":
            aa_counts[aa] = sequence.count(aa)

        total_count = sum(aa_counts.values())

        # Calculate group percentages
        group_percentages = {}
        for group, aas in aa_groups.items():
            group_count = sum(aa_counts.get(aa, 0) for aa in aas)
            group_percentages[group] = (group_count / total_count) * 100 if total_count > 0 else 0

        # Format results
        results = [f"Sequence length: {len(sequence)}"]

        results.append("\nAmino acid composition:")
        for aa, count in aa_counts.items():
            if count > 0:
                percentage = (count / total_count) * 100
                results.append(f"{aa}: {count} ({percentage:.1f}%)")

        results.append("\nAmino acid group percentages:")
        for group, percentage in group_percentages.items():
            results.append(f"{group}: {percentage:.1f}%")

        return "\n".join(results)
    except Exception as e:
        return f"Failed to calculate sequence statistics: {str(e)}"


@mcp.tool()
def compare_sequences(ctx: Context, seq1: str, seq2: str) -> str:
    """Compare two protein sequences"""
    try:
        # Basic validation
        if not seq1 or not seq2:
            return "Error: Empty sequence provided"

        # Clean sequences
        seq1 = ''.join(seq1.split()).upper()
        seq2 = ''.join(seq2.split()).upper()

        # Calculate identity and similarity
        min_len = min(len(seq1), len(seq2))
        max_len = max(len(seq1), len(seq2))

        # Trim or pad sequences to same length
        if len(seq1) > len(seq2):
            seq2 = seq2 + '-' * (len(seq1) - len(seq2))
        elif len(seq2) > len(seq1):
            seq1 = seq1 + '-' * (len(seq2) - len(seq1))

        # Calculate identity
        identical = sum(1 for a, b in zip(seq1, seq2) if a == b)
        identity_percentage = (identical / max_len) * 100 if max_len > 0 else 0

        # Calculate similarity
        # Define similar amino acids
        similar_groups = [
            set(['S', 'T', 'P', 'A', 'G']),  # Small
            set(['N', 'D', 'E', 'Q']),  # Acidic and amides
            set(['H', 'R', 'K']),  # Basic
            set(['M', 'I', 'L', 'V']),  # Hydrophobic
            set(['F', 'Y', 'W'])  # Aromatic
        ]

        similar = 0
        for a, b in zip(seq1, seq2):
            if a == b:
                similar += 1
            else:
                for group in similar_groups:
                    if a in group and b in group:
                        similar += 1
                        break

        similarity_percentage = (similar / max_len) * 100 if max_len > 0 else 0

        # Format alignment
        alignment = []
        for i in range(0, len(seq1), 60):
            seq1_chunk = seq1[i:i + 60]
            seq2_chunk = seq2[i:i + 60]

            matches = ''.join('|' if a == b else ' ' for a, b in zip(seq1_chunk, seq2_chunk))

            alignment.append(f"Seq1: {seq1_chunk}")
            alignment.append(f"      {matches}")
            alignment.append(f"Seq2: {seq2_chunk}")
            alignment.append("")

        # Format results
        results = [
            f"Sequence lengths: {len(seq1.replace('-', ''))} and {len(seq2.replace('-', ''))} residues",
            f"Identity: {identical}/{max_len} ({identity_percentage:.1f}%)",
            f"Similarity: {similar}/{max_len} ({similarity_percentage:.1f}%)",
            "",
            "Alignment:"
        ]

        results.extend(alignment)

        return "\n".join(results)
    except Exception as e:
        return f"Failed to compare sequences: {str(e)}"


# Run the server
if __name__ == "__main__":
    mcp.run()