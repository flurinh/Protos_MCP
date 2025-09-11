"""
Dataset operation tools leveraging Protos' built-in dataset management.

These tools expose Protos processors' dataset functionality through MCP,
allowing users to create, list, load, and manage datasets without path management.
"""

from typing import Dict, List, Optional, Any
import json
from pathlib import Path
from datetime import datetime

from ..base import BaseTool
from ...core.exceptions import DatasetNotFoundError, InvalidInputError


class DatasetOperationTools(BaseTool):
    """Tools for dataset management using Protos processors."""
    
    def register(self, server):
        """Register dataset operation tools with the server."""
        
        @server.tool()
        def create_dataset(ctx, name: str, entities: List[str], 
                          processor_type: str, 
                          description: Optional[str] = None,
                          metadata: Optional[Dict] = None) -> Dict:
            """
            Create a new dataset using Protos' dataset management.
            
            Args:
                name: Dataset name/ID
                entities: List of entity names to include
                processor_type: Type of processor (structure, sequence, etc.)
                description: Optional dataset description
                metadata: Optional metadata dictionary
                
            Returns:
                Dictionary with creation status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "entities": entities, "processor_type": processor_type}, 
                    ["name", "entities", "processor_type"]
                ):
                    return error
                
                if not entities:
                    return self.format_error(
                        "No entities provided",
                        "Provide at least one entity for the dataset"
                    )
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Check which entities exist
                missing = []
                for entity in entities:
                    if hasattr(processor, 'entity_exists'):
                        if not processor.entity_exists(entity):
                            missing.append(entity)
                
                if missing:
                    return self.format_error(
                        f"Some entities not found: {missing}",
                        "Use download_entity or save_entity to add them first"
                    )
                
                # Create dataset using processor's method
                try:
                    # Use processor's create_standard_dataset method
                    dataset = processor.create_standard_dataset(
                        dataset_id=name,
                        name=description or name,
                        content=entities,
                        metadata=metadata
                    )
                    
                    return self.format_success({
                        "dataset_name": name,
                        "entity_count": len(entities),
                        "processor_type": processor_type,
                        "status": "created"
                    }, metadata={"entities": entities[:10]})  # Show first 10
                    
                except AttributeError:
                    # Fallback if processor doesn't have create_standard_dataset
                    return self.format_error(
                        f"Dataset creation not supported for {processor_type}",
                        "This processor may not support dataset operations"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def list_datasets(ctx, processor_type: str) -> Dict:
            """
            List all available datasets for a processor type.
            
            Uses Protos' built-in dataset listing functionality.
            
            Args:
                processor_type: Type of processor
                
            Returns:
                Dictionary with dataset list
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"processor_type": processor_type}, 
                    ["processor_type"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # List datasets using processor's method
                if hasattr(processor, 'list_datasets'):
                    datasets = processor.list_datasets()
                elif hasattr(processor, 'dataset_manager') and processor.dataset_manager:
                    # Use dataset manager if available
                    datasets = processor.dataset_manager.list_datasets()
                else:
                    # No dataset listing available for this processor
                    return self.format_error(
                        f"Dataset listing not supported for {processor_type}",
                        "This processor doesn't have dataset management methods"
                    )
                
                return self.format_success({
                    "processor_type": processor_type,
                    "count": len(datasets),
                    "datasets": datasets
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def load_dataset(ctx, name: str, processor_type: str,
                        summary_only: bool = False) -> Dict:
            """
            Load a dataset using Protos' dataset loading.
            
            Args:
                name: Dataset name/ID
                processor_type: Type of processor
                summary_only: If True, return only summary info
                
            Returns:
                Dictionary with dataset content or summary
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "processor_type": processor_type}, 
                    ["name", "processor_type"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Load dataset using processor's method
                try:
                    if hasattr(processor, 'load_dataset'):
                        # For structure/sequence processors
                        data = processor.load_dataset(name)
                        
                        if summary_only:
                            # Return summary for large datasets
                            if processor_type == "structure":
                                # For structure data (DataFrame)
                                if hasattr(data, 'shape'):
                                    summary = {
                                        "dataset_name": name,
                                        "processor_type": processor_type,
                                        "total_atoms": data.shape[0],
                                        "pdb_ids": list(data['pdb_id'].unique()) if 'pdb_id' in data.columns else [],
                                        "columns": list(data.columns)[:10]
                                    }
                                else:
                                    summary = {"dataset_name": name, "type": str(type(data))}
                            else:
                                # For other types
                                summary = {
                                    "dataset_name": name,
                                    "processor_type": processor_type,
                                    "entity_count": len(data) if hasattr(data, '__len__') else 1
                                }
                            
                            return self.format_success(summary)
                        else:
                            # Return full data
                            # Convert to serializable format
                            if hasattr(data, 'to_dict'):
                                serialized = data.to_dict('records')
                            elif isinstance(data, dict):
                                serialized = data
                            else:
                                serialized = {"data": str(data)}
                            
                            return self.format_success({
                                "dataset_name": name,
                                "processor_type": processor_type,
                                "data": serialized
                            })
                    else:
                        return self.format_error(
                            f"Dataset loading not supported for {processor_type}",
                            "This processor may not support dataset operations"
                        )
                        
                except FileNotFoundError as e:
                    return self.format_error(
                        f"Dataset '{name}' not found or contains missing entities",
                        f"Use list_datasets to see available datasets. If dataset exists, ensure all referenced entities are downloaded first. Error: {str(e)}"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def dataset_info(ctx, name: str, processor_type: str) -> Dict:
            """
            Get detailed information about a dataset.
            
            Args:
                name: Dataset name/ID
                processor_type: Type of processor
                
            Returns:
                Dictionary with dataset metadata and statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "processor_type": processor_type}, 
                    ["name", "processor_type"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Get dataset info
                if hasattr(processor, 'get_dataset_info'):
                    info = processor.get_dataset_info(name)
                    return self.format_success(info)
                else:
                    # No dataset info method available
                    return self.format_error(
                        f"Dataset info not supported for {processor_type}",
                        "This processor doesn't have get_dataset_info method"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def update_dataset(ctx, name: str, processor_type: str,
                          add_entities: Optional[List[str]] = None,
                          remove_entities: Optional[List[str]] = None,
                          update_metadata: Optional[Dict] = None) -> Dict:
            """
            Update an existing dataset.
            
            Args:
                name: Dataset name/ID
                processor_type: Type of processor
                add_entities: Entities to add
                remove_entities: Entities to remove
                update_metadata: Metadata to update
                
            Returns:
                Dictionary with update status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"name": name, "processor_type": processor_type}, 
                    ["name", "processor_type"]
                ):
                    return error
                
                if not any([add_entities, remove_entities, update_metadata]):
                    return self.format_error(
                        "No updates specified",
                        "Provide entities to add/remove or metadata to update"
                    )
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Load current dataset
                if hasattr(processor, 'dataset_manager') and processor.dataset_manager:
                    dataset_manager = processor.dataset_manager
                    
                    # Get current dataset
                    current = dataset_manager.load_dataset(name)
                    if not current:
                        return self.format_error(
                            f"Dataset '{name}' not found",
                            "Use list_datasets to see available datasets"
                        )
                    
                    # Update entities
                    entities = list(current.content)
                    if add_entities:
                        entities.extend(add_entities)
                    if remove_entities:
                        entities = [e for e in entities if e not in remove_entities]
                    
                    # Update metadata
                    metadata = current.metadata or {}
                    if update_metadata:
                        metadata.update(update_metadata)
                    
                    # Save updated dataset
                    dataset_manager.update_dataset(
                        name,
                        content=entities,
                        metadata=metadata
                    )
                    
                    return self.format_success({
                        "dataset_name": name,
                        "entities_added": len(add_entities) if add_entities else 0,
                        "entities_removed": len(remove_entities) if remove_entities else 0,
                        "metadata_updated": bool(update_metadata),
                        "total_entities": len(entities)
                    })
                else:
                    return self.format_error(
                        f"Dataset update not supported for {processor_type}",
                        "This processor may not support dataset operations"
                    )
                    
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def download_dataset_entities(ctx, dataset_name: str, 
                                     processor_type: str,
                                     source: str = "pdb",
                                     parallel: bool = True,
                                     max_workers: int = 5) -> Dict:
            """
            Download all entities referenced in an existing dataset.
            
            This tool loads a dataset and downloads all its entities from
            external sources (PDB, UniProt, etc.).
            
            Args:
                dataset_name: Name of the dataset to download entities for
                processor_type: Type of processor (structure, sequence, etc.)
                source: Source to download from (pdb, uniprot, alphafold)
                parallel: Whether to download in parallel (for large datasets)
                max_workers: Number of parallel download workers
                
            Returns:
                Dictionary with download status and results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "processor_type": processor_type}, 
                    ["dataset_name", "processor_type"]
                ):
                    return error
                
                # Validate processor type
                if error := self.validate_processor_type(processor_type):
                    return error
                
                # Get processor
                processor = self.get_processor(processor_type)
                
                # Load the dataset to get entity list
                if hasattr(processor, 'dataset_manager') and processor.dataset_manager:
                    dataset = processor.dataset_manager.load_dataset(dataset_name)
                    if not dataset:
                        return self.format_error(
                            f"Dataset '{dataset_name}' not found",
                            "Use list_datasets to see available datasets"
                        )
                    
                    entity_ids = list(dataset.content)
                else:
                    # Fallback: try to get dataset info
                    if hasattr(processor, 'get_dataset_info'):
                        info = processor.get_dataset_info(dataset_name)
                        # Extract entity names from the entity info list
                        entity_ids = [e['name'] for e in info.get('entities', [])]
                    else:
                        return self.format_error(
                            f"Cannot load dataset '{dataset_name}'",
                            "The processor doesn't support dataset operations"
                        )
                
                if not entity_ids:
                    return self.format_error(
                        f"Dataset '{dataset_name}' has no entities",
                        "The dataset is empty"
                    )
                
                # Download entities based on processor type
                if processor_type == "structure" and source == "pdb":
                    # Download PDB structures
                    if parallel and len(entity_ids) > 5:
                        # Use parallel download for large datasets
                        try:
                            from protos.cli.download_with_registration import bulk_download_structures
                            results = bulk_download_structures(
                                entity_ids, 
                                max_workers=max_workers
                            )
                            
                            # Extract success/failed from results
                            success = [eid for eid, status in results.items() if status == 'success']
                            failed = {eid: 'download failed' for eid, status in results.items() if status != 'success'}
                        except ImportError:
                            # Fallback to sequential download
                            from protos.loaders.download_structures import download_structures_with_processor
                            success, failed = download_structures_with_processor(
                                entity_ids, 
                                processor=processor
                            )
                    else:
                        # Sequential download for small datasets
                        from protos.loaders.download_structures import download_structures_with_processor
                        success, failed = download_structures_with_processor(
                            entity_ids, 
                            processor=processor
                        )
                        
                elif processor_type == "structure" and source == "alphafold":
                    # Download AlphaFold structures
                    try:
                        from protos.loaders.alphafold_utils import download_alphafold_structures
                        
                        success = []
                        failed = {}
                        
                        for entity_id in entity_ids:
                            if download_alphafold_structures([entity_id]):
                                success.append(entity_id)
                            else:
                                failed[entity_id] = "AlphaFold download failed"
                                
                    except ImportError:
                        return self.format_error(
                            "AlphaFold download not available",
                            "Ensure protos.loaders.alphafold_utils is installed"
                        )
                        
                elif processor_type == "sequence" and source == "uniprot":
                    # Download sequences from UniProt
                    try:
                        from protos.loaders.uniprot_loader import download_sequence
                        
                        success = []
                        failed = {}
                        
                        for entity_id in entity_ids:
                            sequence = download_sequence(entity_id)
                            if sequence:
                                # Save using processor
                                processor.save_entity(entity_id, sequence)
                                success.append(entity_id)
                            else:
                                failed[entity_id] = "UniProt download failed"
                                
                    except ImportError:
                        return self.format_error(
                            "UniProt download not available",
                            "Ensure protos.loaders.uniprot_loader is installed"
                        )
                else:
                    return self.format_error(
                        f"Download not implemented for {processor_type} from {source}",
                        "Supported combinations: structure+pdb, structure+alphafold, sequence+uniprot"
                    )
                
                # Update dataset metadata with download results
                if hasattr(processor.dataset_manager, 'update_dataset'):
                    try:
                        processor.dataset_manager.update_dataset(
                            dataset_name,
                            metadata={
                                'last_download': datetime.now().isoformat(),
                                'downloaded_count': len(success),
                                'failed_count': len(failed)
                            }
                        )
                    except:
                        pass  # Metadata update is optional
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "processor_type": processor_type,
                    "source": source,
                    "total_entities": len(entity_ids),
                    "downloaded": len(success),
                    "failed": len(failed),
                    "success_ids": success[:20],  # First 20
                    "failed_details": dict(list(failed.items())[:10]) if failed else {}
                })
                    
            except Exception as e:
                return self.handle_error(e)