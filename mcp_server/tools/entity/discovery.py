"""
Entity discovery tools for finding and searching entities in Protos.

These tools allow users to discover what data is available without
needing to know file paths or internal structure.
"""

from typing import Dict, List, Optional, Any
import re

from ..base import BaseTool
from ...core.exceptions import InvalidInputError


class EntityDiscoveryTools(BaseTool):
    """Tools for discovering and searching entities."""
    
    def register(self, server):
        """Register entity discovery tools with the server."""
        
        @server.tool()
        def list_entities(ctx, processor_type: str, 
                         limit: Optional[int] = None,
                         offset: Optional[int] = None) -> Dict:
            """
            List all entities available for a specific processor type.
            
            Args:
                processor_type: Type of processor (structure, sequence, grn, etc.)
                limit: Maximum number of entities to return
                offset: Number of entities to skip
                
            Returns:
                Dictionary with entity list and metadata
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
                
                # Get all entities
                try:
                    if hasattr(processor, 'list_entities'):
                        entities = processor.list_entities()
                    elif hasattr(processor, 'list_structures') and processor_type == "structure":
                        # Fallback for structure processor
                        entities = processor.list_structures()
                    elif hasattr(processor, 'get_available_pdb_files') and processor_type == "structure":
                        # Another fallback for structure processor
                        entities = processor.get_available_pdb_files()
                    else:
                        # If no list method available, return empty list
                        entities = []
                except Exception as e:
                    # If listing fails, might be because no entities exist yet
                    print(f"Warning: Failed to list entities for {processor_type}: {e}", file=sys.stderr)
                    entities = []
                
                # Apply pagination
                total = len(entities)
                if offset:
                    entities = entities[offset:]
                if limit:
                    entities = entities[:limit]
                
                return self.format_success({
                    "processor_type": processor_type,
                    "total": total,
                    "count": len(entities),
                    "offset": offset or 0,
                    "entities": entities
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def search_entities(ctx, query: str,
                          processor_types: Optional[List[str]] = None,
                          regex: bool = False,
                          case_sensitive: bool = False) -> Dict:
            """
            Search for entities across one or more processor types.
            
            Args:
                query: Search query (substring or regex)
                processor_types: List of processor types to search (None = all)
                regex: Whether to treat query as regex pattern
                case_sensitive: Whether search is case sensitive
                
            Returns:
                Dictionary with search results grouped by processor type
            """
            try:
                # Validate parameters
                if error := self.validate_required_params({"query": query}, ["query"]):
                    return error
                
                # Default to all processors if none specified
                if not processor_types:
                    from ...core.processor_factory import ProcessorFactory
                    processor_types = ProcessorFactory.get_available_processors()
                
                # Prepare search pattern
                if regex:
                    try:
                        pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
                    except re.error as e:
                        return self.format_error(
                            f"Invalid regex pattern: {e}",
                            "Please provide a valid regular expression"
                        )
                else:
                    # Convert to simple regex for substring matching
                    escaped_query = re.escape(query)
                    pattern = re.compile(escaped_query, 0 if case_sensitive else re.IGNORECASE)
                
                # Search across processor types
                results = {}
                total_matches = 0
                
                for proc_type in processor_types:
                    try:
                        # Validate processor type
                        if error := self.validate_processor_type(proc_type):
                            results[proc_type] = {"error": "invalid processor type"}
                            continue
                        
                        processor = self.get_processor(proc_type)
                        entities = processor.list_entities()
                        
                        # Filter by pattern
                        matches = [e for e in entities if pattern.search(e)]
                        
                        if matches:
                            results[proc_type] = matches
                            total_matches += len(matches)
                            
                    except Exception as e:
                        # Log error but continue with other processors
                        results[proc_type] = {"error": str(e)}
                
                return self.format_success({
                    "query": query,
                    "total_matches": total_matches,
                    "results": results
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def entity_info(ctx, entity_name: str) -> Dict:
            """
            Get comprehensive information about an entity.
            
            Shows all formats where the entity exists and associated metadata.
            
            Args:
                entity_name: Name of the entity to look up
                
            Returns:
                Dictionary with entity information across all formats
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity_name": entity_name}, 
                    ["entity_name"]
                ):
                    return error
                
                # Check all processor types
                entity_info = {
                    "entity_name": entity_name,
                    "formats": {}
                }
                
                for proc_type in self.manager.get_available_processors():
                    try:
                        processor = self.get_processor(proc_type)
                        
                        # Check if entity exists
                        if hasattr(processor, 'entity_exists'):
                            exists = processor.entity_exists(entity_name)
                        else:
                            # Fallback: check if in entity list
                            entities = processor.list_entities()
                            exists = entity_name in entities
                        
                        if exists:
                            format_info = {
                                "exists": True,
                                "processor_type": proc_type
                            }
                            
                            # Try to get additional metadata
                            if hasattr(processor, 'get_entity_metadata'):
                                format_info["metadata"] = processor.get_entity_metadata(entity_name)
                            
                            entity_info["formats"][proc_type] = format_info
                            
                    except Exception as e:
                        # Log error but continue
                        entity_info["formats"][proc_type] = {
                            "error": str(e)
                        }
                
                # Add registry information if available
                if hasattr(self.registry, 'find_entity'):
                    registry_info = self.registry.find_entity(entity_name)
                    if registry_info:
                        entity_info["registry"] = {
                            "aliases": getattr(registry_info, 'aliases', []),
                            "created": getattr(registry_info, 'created', None),
                            "modified": getattr(registry_info, 'modified', None)
                        }
                
                return self.format_success(entity_info)
                
            except Exception as e:
                return self.handle_error(e)