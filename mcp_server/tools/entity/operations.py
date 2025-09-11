"""
Entity operation tools for CRUD operations on Protos entities.

These tools handle downloading, saving, loading, and deleting entities
with automatic path management and registration.
"""

from typing import Dict, List, Optional, Any
import json
import base64
from pathlib import Path

from ..base import BaseTool
from ...core.exceptions import EntityNotFoundError, InvalidInputError


class EntityOperationTools(BaseTool):
    """Tools for entity CRUD operations."""
    
    def register(self, server):
        """Register entity operation tools with the server."""
        
        @server.tool()
        def download_entity(ctx, entity_id: str,
                          source: str = "pdb",
                          processor_type: str = "structure",
                          overwrite: bool = False) -> Dict:
            """
            Download an entity from an external source.
            
            Args:
                entity_id: ID of entity to download (e.g., PDB ID)
                source: Source to download from (pdb, uniprot, etc.)
                processor_type: Type of processor to use
                overwrite: Whether to overwrite existing entity
                
            Returns:
                Dictionary with download status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity_id": entity_id}, 
                    ["entity_id"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Check if already exists
                if not overwrite and hasattr(processor, 'entity_exists'):
                    if processor.entity_exists(entity_id):
                        return self.format_error(
                            f"Entity '{entity_id}' already exists",
                            "Use overwrite=true to replace existing entity"
                        )
                
                # Download based on processor type and source
                if processor_type == "structure" and source == "pdb":
                    # Import download function
                    try:
                        from protos.loaders.download_structures import download_structures_with_processor
                        success, failed = download_structures_with_processor(
                            [entity_id], 
                            processor=processor,
                            overwrite=overwrite
                        )
                        
                        if entity_id in failed:
                            return self.format_error(
                                f"Failed to download {entity_id}: {failed[entity_id]}",
                                "Check that the ID is valid and the source is accessible"
                            )
                        
                        return self.format_success({
                            "entity_id": entity_id,
                            "source": source,
                            "processor_type": processor_type,
                            "status": "downloaded"
                        })
                        
                    except ImportError:
                        return self.format_error(
                            "Download functionality not available",
                            "Ensure protos.loaders module is installed"
                        )
                        
                elif processor_type == "sequence" and source == "uniprot":
                    # Download from UniProt
                    try:
                        from protos.loaders.uniprot_loader import download_sequence
                        
                        # Download sequence
                        sequence = download_sequence(entity_id)
                        if sequence:
                            # Save using processor
                            processor.save_sequence(entity_id, sequence)
                            
                            return self.format_success({
                                "entity_id": entity_id,
                                "source": source,
                                "processor_type": processor_type,
                                "status": "downloaded",
                                "sequence_length": len(sequence)
                            })
                        else:
                            return self.format_error(
                                f"Failed to download sequence {entity_id}",
                                "Check that the UniProt ID is valid"
                            )
                    except ImportError:
                        return self.format_error(
                            "UniProt download functionality not available",
                            "Ensure protos.loaders.uniprot_loader is available"
                        )
                        
                elif processor_type == "structure" and source == "alphafold":
                    # Download from AlphaFold
                    try:
                        from protos.loaders.alphafold_utils import download_alphafold_structures
                        
                        # Let Protos handle the download and path management internally
                        success = download_alphafold_structures(
                            [entity_id],
                            output_dir=None  # Let the function use default Protos paths
                        )
                        
                        if success:
                            return self.format_success({
                                "entity_id": entity_id,
                                "source": source,
                                "processor_type": processor_type,
                                "status": "downloaded"
                            })
                        else:
                            return self.format_error(
                                f"Failed to download from AlphaFold: {entity_id}",
                                "Check that the UniProt ID has an AlphaFold structure"
                            )
                    except ImportError:
                        return self.format_error(
                            "AlphaFold download functionality not available",
                            "Ensure protos.loaders.alphafold_utils is available"
                        )
                        
                else:
                    return self.format_error(
                        f"Download not implemented for {processor_type} from {source}",
                        "Supported: structure from pdb/alphafold, sequence from uniprot"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def load_entity(ctx, name: str, format: str,
                       output_format: str = "json") -> Dict:
            """
            Load an entity's data.
            
            Args:
                name: Entity name
                format: Processor type (structure, sequence, etc.)
                output_format: How to return data (json, base64, summary)
                
            Returns:
                Dictionary with entity data
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "format": format}, 
                    ["name", "format"]
                ):
                    return error
                
                # Validate processor type (format parameter is processor type)
                if error := self.validate_processor_type(format):
                    return error
                
                # Get processor
                processor = self.get_processor(format)
                
                # Load entity based on processor type
                try:
                    if format == "structure":
                        # For structure processor, load single structure
                        processor.load_structures([name])
                        if hasattr(processor, 'data') and processor.data is not None:
                            # Filter to just this structure
                            data = processor.data[processor.data['pdb_id'] == name]
                        else:
                            return self.format_error(
                                f"Failed to load structure {name}",
                                "Structure may not exist. Try downloading it first."
                            )
                    elif format == "property":
                        # For properties, get all properties for the entity
                        if hasattr(processor, 'get_entity_properties'):
                            data = processor.get_entity_properties(name)
                        else:
                            return self.format_error(
                                "Property loading not available",
                                "PropertyProcessor doesn't have get_entity_properties method"
                            )
                    elif hasattr(processor, 'load_entity'):
                        data = processor.load_entity(name)
                    elif hasattr(processor, 'load_sequence') and format == "sequence":
                        data = processor.load_sequence(name)
                    elif hasattr(processor, 'load') and format == "grn":
                        data = processor.load(name)
                    else:
                        return self.format_error(
                            f"Load not implemented for {format} processor",
                            "This processor may not support entity loading"
                        )
                except FileNotFoundError:
                    return self.format_error(
                        f"Entity '{name}' not found",
                        f"Use download_entity to fetch it first"
                    )
                
                # Format output based on requested format
                if output_format == "summary":
                    # Return summary information
                    if hasattr(data, '__len__'):
                        summary = {
                            "name": name,
                            "format": format,
                            "size": len(data)
                        }
                        
                        # Add type-specific summary
                        if format == "structure" and hasattr(data, 'shape'):
                            summary["atoms"] = data.shape[0] if len(data.shape) > 0 else 0
                            if hasattr(data, 'columns'):
                                summary["columns"] = list(data.columns)[:10]  # First 10 columns
                        elif format == "sequence":
                            if isinstance(data, str):
                                # Single sequence
                                summary["length"] = len(data)
                                summary["preview"] = data[:50] + "..." if len(data) > 50 else data
                            elif isinstance(data, dict):
                                # Multi-sequence file
                                summary["sequence_count"] = len(data)
                                summary["sequence_ids"] = list(data.keys())[:10]  # First 10 IDs
                                # Get length of first sequence as example
                                if data:
                                    first_seq = list(data.values())[0]
                                    summary["first_sequence_length"] = len(first_seq)
                            
                        return self.format_success(summary)
                        
                elif output_format == "base64":
                    # Encode as base64 for binary data
                    if hasattr(data, 'to_json'):
                        json_str = data.to_json()
                        encoded = base64.b64encode(json_str.encode()).decode()
                    else:
                        json_str = json.dumps(data)
                        encoded = base64.b64encode(json_str.encode()).decode()
                        
                    return self.format_success({
                        "name": name,
                        "format": format,
                        "encoding": "base64",
                        "data": encoded
                    })
                    
                else:  # json
                    # Return as JSON
                    if hasattr(data, 'to_dict'):
                        json_data = data.to_dict()
                    elif hasattr(data, 'to_json'):
                        json_data = json.loads(data.to_json())
                    elif isinstance(data, str):
                        json_data = {"sequence": data}
                    else:
                        json_data = data
                        
                    return self.format_success({
                        "name": name,
                        "format": format,
                        "data": json_data
                    })
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def save_entity(ctx, name: str, data: Any, format: str,
                       metadata: Optional[Dict] = None,
                       data_encoding: str = "json") -> Dict:
            """
            Save a new entity or update existing one.
            
            Args:
                name: Entity name
                data: Entity data (JSON object, JSON string, or base64 encoded string)
                format: Processor type
                metadata: Optional metadata to store
                data_encoding: How data is encoded (json or base64)
                
            Returns:
                Dictionary with save status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "data": data, "format": format}, 
                    ["name", "data", "format"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(format):
                    return error
                
                # Get processor
                processor = self.get_processor(format)
                
                # Decode data
                if data_encoding == "base64":
                    try:
                        decoded = base64.b64decode(data).decode()
                        data = decoded
                    except Exception as e:
                        return self.format_error(
                            f"Failed to decode base64 data: {e}",
                            "Ensure data is properly base64 encoded"
                        )
                
                # Parse data based on format
                if format == "sequence":
                    # For sequences, data might be string, dict, or JSON string
                    if isinstance(data, str):
                        # Check if it's a JSON string
                        if data.startswith("{"):
                            parsed = json.loads(data)
                            sequence_data = parsed.get("sequence", parsed)
                        else:
                            # It's a plain sequence string
                            sequence_data = data
                    elif isinstance(data, dict):
                        # Direct dictionary input
                        sequence_data = data.get("sequence", data)
                    else:
                        sequence_data = data
                        
                    # Use the processor's save_entity method - it handles ALL path management
                    if hasattr(processor, 'save_entity'):
                        processor.save_entity(name, sequence_data, metadata)
                    elif hasattr(processor, 'save_sequence'):
                        # Fallback to save_sequence if available
                        processor.save_sequence(name, sequence_data)
                        # Note: The processor internally handles entity registration
                    else:
                        return self.format_error(
                            "Save not implemented for sequence processor",
                            "The processor must implement save_entity or save_sequence"
                        )
                        
                elif format == "structure":
                    # For structures, parse the data and use processor's save methods
                    try:
                        import pandas as pd
                        
                        # Parse structure data
                        parsed_data = json.loads(data)
                        
                        # Convert to DataFrame if it's a dict/list
                        if isinstance(parsed_data, dict):
                            if 'data' in parsed_data:
                                df = pd.DataFrame(parsed_data['data'])
                            else:
                                df = pd.DataFrame([parsed_data])
                        elif isinstance(parsed_data, list):
                            df = pd.DataFrame(parsed_data)
                        else:
                            return self.format_error(
                                "Invalid structure data format",
                                "Provide structure data as JSON object or array"
                            )
                        
                        # Use processor's save_structure method - it handles ALL path management
                        if hasattr(processor, 'save_structure'):
                            processor.save_structure(name, df, format='pkl')
                        elif hasattr(processor, 'save_entity'):
                            processor.save_entity(name, df, metadata)
                        else:
                            return self.format_error(
                                "Save not implemented for structure processor",
                                "The processor must implement save_structure or save_entity"
                            )
                    except json.JSONDecodeError as e:
                        return self.format_error(
                            f"Invalid JSON data: {e}",
                            "Ensure data is valid JSON format"
                        )
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save structure: {e}",
                            "Check data format and try again"
                        )
                    
                elif format == "grn":
                    # For GRN, save as a table
                    try:
                        parsed_data = json.loads(data) if isinstance(data, str) else data
                        
                        # GRN processor expects a DataFrame or Series
                        if isinstance(parsed_data, dict):
                            # Convert dict to Series for single entity
                            import pandas as pd
                            grn_series = pd.Series(parsed_data)
                            processor.save_entity(name, grn_series)
                        else:
                            processor.save_entity(name, parsed_data)
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save GRN data: {e}",
                            "Ensure data is a valid GRN mapping (dict of position -> residue)"
                        )
                        
                elif format == "property":
                    # For properties, use assign_property instead of save_entity
                    try:
                        parsed_data = json.loads(data) if isinstance(data, str) else data
                        
                        if isinstance(parsed_data, dict):
                            # Assign each property
                            for prop_name, prop_value in parsed_data.items():
                                processor.assign_property(name, prop_name, prop_value)
                        else:
                            return self.format_error(
                                "Property data must be a dictionary",
                                "Provide properties as {property_name: value}"
                            )
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save properties: {e}",
                            "Check property format and try again"
                        )
                        
                elif format == "ligand":
                    # For ligands, expect ligand-specific data
                    try:
                        parsed_data = json.loads(data) if isinstance(data, str) else data
                        processor.save_entity(name, parsed_data, metadata)
                    except Exception as e:
                        return self.format_error(
                            f"Failed to save ligand data: {e}",
                            "Ensure data is valid ligand information"
                        )
                    
                else:
                    # Generic save for other formats
                    if hasattr(processor, 'save_entity'):
                        processor.save_entity(name, data, metadata)
                    else:
                        return self.format_error(
                            f"Save not implemented for {format} processor"
                        )
                
                return self.format_success({
                    "name": name,
                    "format": format,
                    "status": "saved"
                }, metadata=metadata)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def delete_entity(ctx, name: str, formats: List[str]) -> Dict:
            """
            Delete an entity from specified formats.
            
            Args:
                name: Entity name
                formats: List of formats to delete from
                
            Returns:
                Dictionary with deletion status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "formats": formats}, 
                    ["name", "formats"]
                ):
                    return error
                
                if not formats:
                    return self.format_error(
                        "No formats specified",
                        "Provide a list of formats to delete from"
                    )
                
                # Track results
                results = {}
                
                for format in formats:
                    try:
                        # Validate processor type
                        if error := self.validate_processor_type(format):
                            results[format] = f"invalid_processor_type"
                            continue
                        
                        processor = self.get_processor(format)
                        
                        if hasattr(processor, 'delete_entity'):
                            processor.delete_entity(name)
                            results[format] = "deleted"
                        else:
                            results[format] = "not_implemented"
                            
                    except Exception as e:
                        results[format] = f"error: {str(e)}"
                
                # Determine overall success
                deleted = [f for f, r in results.items() if r == "deleted"]
                failed = [f for f, r in results.items() if r.startswith("error")]
                
                if deleted and not failed:
                    return self.format_success({
                        "name": name,
                        "deleted_from": deleted,
                        "results": results
                    })
                else:
                    return self.format_error(
                        f"Deletion partially failed",
                        f"Check results for details",
                        error_type="PartialFailure"
                    )
                    
            except Exception as e:
                return self.handle_error(e)