"""
Property analysis tools for working with property tables.

These tools provide analysis capabilities for property tables where:
- Each row is an entity (indexed by entity_id)
- Each column is a property
- Each table is a dataset
"""

from typing import Dict, List, Optional, Any, Union, Callable
import pandas as pd
import numpy as np

from ..base import BaseTool
from ...core.exceptions import InvalidInputError, DatasetNotFoundError


class PropertyAnalysisTools(BaseTool):
    """Tools for property table analysis and manipulation."""
    
    def register(self, server):
        """Register property analysis tools with the server."""
        
        @server.tool()
        def create_property_table(ctx, dataset_name: str,
                                data: Union[Dict[str, Dict[str, Any]], List[Dict[str, Any]]],
                                metadata: Optional[Dict] = None) -> Dict:
            """
            Create a new property table from entity data.
            
            Args:
                dataset_name: Name for the property table/dataset
                data: Either:
                    - Dict of {entity_id: {property: value}}
                    - List of dicts with 'entity_id' key
                metadata: Optional metadata for the dataset
                
            Returns:
                Dictionary with creation status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "data": data},
                    ["dataset_name", "data"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Convert list format to dict format if needed
                if isinstance(data, list):
                    data_dict = {}
                    for item in data:
                        if 'entity_id' not in item:
                            return self.format_error(
                                "Missing entity_id in data items",
                                "Each item must have an 'entity_id' key"
                            )
                        entity_id = item.pop('entity_id')
                        data_dict[entity_id] = item
                    data = data_dict
                
                # Create property table
                df = processor.create_property_table(
                    dataset_name=dataset_name,
                    data=data,
                    metadata=metadata
                )
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "entities": len(df),
                    "properties": df.columns.tolist(),
                    "shape": list(df.shape)
                }, metadata={"created": True})
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def add_property_column(ctx, dataset_name: str,
                              property_name: str,
                              values: Union[Dict[str, Any], Any]) -> Dict:
            """
            Add a new property column to an existing property table.
            
            Args:
                dataset_name: Dataset to update
                property_name: Name of the new property
                values: Either:
                    - Dict mapping entity_id to value
                    - Single value to apply to all entities
                    
            Returns:
                Dictionary with update status
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "property_name": property_name, "values": values},
                    ["dataset_name", "property_name", "values"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Add property column
                processor.add_property_column(
                    dataset_name=dataset_name,
                    property_name=property_name,
                    values=values
                )
                
                # Get updated table info
                df = processor.get_property_table(dataset_name)
                
                return self.format_success({
                    "dataset_name": dataset_name,
                    "property_name": property_name,
                    "entities_updated": len(df),
                    "total_properties": len(df.columns)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_property_statistics(ctx, dataset_name: str,
                                  property_name: Optional[str] = None) -> Dict:
            """
            Get statistics for properties in a dataset.
            
            Args:
                dataset_name: Name of the property dataset
                property_name: Specific property to analyze (None for all)
                
            Returns:
                Dictionary with property statistics
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name},
                    ["dataset_name"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Load property table
                try:
                    df = processor.get_property_table(dataset_name)
                except Exception:
                    return self.format_error(
                        f"Dataset '{dataset_name}' not found",
                        "Use list_datasets to see available property datasets"
                    )
                
                if property_name:
                    # Stats for single property
                    if property_name not in df.columns:
                        return self.format_error(
                            f"Property '{property_name}' not found",
                            f"Available properties: {', '.join(df.columns)}"
                        )
                    
                    series = df[property_name]
                    stats = {
                        "property": property_name,
                        "count": len(series),
                        "non_null": series.notna().sum(),
                        "null_count": series.isna().sum(),
                        "dtype": str(series.dtype)
                    }
                    
                    # Additional stats for numeric types
                    if pd.api.types.is_numeric_dtype(series):
                        stats.update({
                            "mean": float(series.mean()) if series.notna().any() else None,
                            "std": float(series.std()) if series.notna().any() else None,
                            "min": float(series.min()) if series.notna().any() else None,
                            "max": float(series.max()) if series.notna().any() else None,
                            "median": float(series.median()) if series.notna().any() else None
                        })
                    
                    # Additional stats for categorical/string types
                    elif pd.api.types.is_string_dtype(series) or pd.api.types.is_categorical_dtype(series):
                        value_counts = series.value_counts()
                        stats.update({
                            "unique_values": len(value_counts),
                            "most_common": value_counts.head(5).to_dict()
                        })
                    
                    return self.format_success(stats)
                
                else:
                    # Stats for all properties
                    all_stats = {
                        "dataset": dataset_name,
                        "entities": len(df),
                        "properties": len(df.columns),
                        "property_stats": {}
                    }
                    
                    for col in df.columns:
                        series = df[col]
                        col_stats = {
                            "dtype": str(series.dtype),
                            "non_null": int(series.notna().sum()),
                            "null_pct": float(series.isna().sum() / len(series) * 100)
                        }
                        
                        if pd.api.types.is_numeric_dtype(series):
                            col_stats["type"] = "numeric"
                            if series.notna().any():
                                col_stats["mean"] = float(series.mean())
                                col_stats["std"] = float(series.std())
                        else:
                            col_stats["type"] = "categorical"
                            col_stats["unique"] = series.nunique()
                        
                        all_stats["property_stats"][col] = col_stats
                    
                    return self.format_success(all_stats)
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def filter_entities_by_property(ctx, dataset_name: str,
                                      property_name: str,
                                      operator: str,
                                      value: Any) -> Dict:
            """
            Filter entities based on property values.
            
            Args:
                dataset_name: Name of the property dataset
                property_name: Property to filter by
                operator: Comparison operator (=, !=, <, >, <=, >=, in, not_in, contains)
                value: Value to compare against
                
            Returns:
                Dictionary with filtered entity list
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "property_name": property_name, 
                     "operator": operator, "value": value},
                    ["dataset_name", "property_name", "operator", "value"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Define condition function based on operator
                if operator == "=":
                    condition = lambda x: x == value
                elif operator == "!=":
                    condition = lambda x: x != value
                elif operator == "<":
                    condition = lambda x: x < value if pd.notna(x) else False
                elif operator == ">":
                    condition = lambda x: x > value if pd.notna(x) else False
                elif operator == "<=":
                    condition = lambda x: x <= value if pd.notna(x) else False
                elif operator == ">=":
                    condition = lambda x: x >= value if pd.notna(x) else False
                elif operator == "in":
                    value_list = value if isinstance(value, list) else [value]
                    condition = lambda x: x in value_list
                elif operator == "not_in":
                    value_list = value if isinstance(value, list) else [value]
                    condition = lambda x: x not in value_list
                elif operator == "contains":
                    condition = lambda x: str(value) in str(x) if pd.notna(x) else False
                else:
                    return self.format_error(
                        f"Invalid operator: {operator}",
                        "Valid operators: =, !=, <, >, <=, >=, in, not_in, contains"
                    )
                
                # Apply filter
                try:
                    filtered_df = processor.filter_by_property(
                        dataset_name=dataset_name,
                        property_name=property_name,
                        condition=condition
                    )
                except ValueError as e:
                    return self.format_error(str(e))
                
                # Get filtered entities
                entities = filtered_df.index.tolist()
                
                return self.format_success({
                    "dataset": dataset_name,
                    "filter": {
                        "property": property_name,
                        "operator": operator,
                        "value": value
                    },
                    "matched_entities": len(entities),
                    "entities": entities[:100],  # First 100
                    "truncated": len(entities) > 100
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def merge_property_tables(ctx, dataset_names: List[str],
                                output_name: str,
                                how: str = "outer") -> Dict:
            """
            Merge multiple property tables into one.
            
            Args:
                dataset_names: List of datasets to merge
                output_name: Name for the merged dataset
                how: Merge method ('outer', 'inner', 'left', 'right')
                
            Returns:
                Dictionary with merge results
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_names": dataset_names, "output_name": output_name},
                    ["dataset_names", "output_name"]
                ):
                    return error
                
                if not dataset_names:
                    return self.format_error(
                        "No datasets provided",
                        "Provide at least one dataset to merge"
                    )
                
                if how not in ["outer", "inner", "left", "right"]:
                    return self.format_error(
                        f"Invalid merge method: {how}",
                        "Valid methods: outer, inner, left, right"
                    )
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Perform merge
                try:
                    merged_df = processor.merge_property_tables(
                        dataset_names=dataset_names,
                        output_name=output_name,
                        how=how
                    )
                except ValueError as e:
                    return self.format_error(str(e))
                
                return self.format_success({
                    "output_name": output_name,
                    "merged_from": dataset_names,
                    "merge_method": how,
                    "entities": len(merged_df),
                    "properties": merged_df.columns.tolist(),
                    "shape": list(merged_df.shape)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def get_entity_property_values(ctx, entity_id: str,
                                     dataset_name: Optional[str] = None) -> Dict:
            """
            Get all property values for a specific entity.
            
            Args:
                entity_id: Entity identifier
                dataset_name: Specific dataset (None to search all)
                
            Returns:
                Dictionary with entity's property values
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"entity_id": entity_id},
                    ["entity_id"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Get entity properties
                properties = processor.get_entity_properties(
                    entity_id=entity_id,
                    dataset_name=dataset_name
                )
                
                if not properties:
                    return self.format_error(
                        f"Entity '{entity_id}' not found",
                        "Entity may not exist in any property tables"
                    )
                
                return self.format_success({
                    "entity_id": entity_id,
                    "dataset": dataset_name or "all",
                    "properties": properties,
                    "property_count": len(properties)
                })
                
            except Exception as e:
                return self.handle_error(e)
        
        @server.tool()
        def export_property_table(ctx, dataset_name: str,
                                entities: Optional[List[str]] = None,
                                properties: Optional[List[str]] = None) -> Dict:
            """
            Export a property table or subset as CSV/JSON.
            
            Args:
                dataset_name: Dataset to export
                entities: List of entities to include (None for all)
                properties: List of properties to include (None for all)
                
            Returns:
                Dictionary with exported data
            """
            try:
                # Validate parameters
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name},
                    ["dataset_name"]
                ):
                    return error
                
                # Get property processor
                processor = self.get_processor("property")
                
                # Get property table
                try:
                    df = processor.get_property_table(dataset_name)
                except Exception:
                    return self.format_error(
                        f"Dataset '{dataset_name}' not found",
                        "Use list_datasets to see available property datasets"
                    )
                
                # Filter entities if specified
                if entities:
                    missing = [e for e in entities if e not in df.index]
                    if missing:
                        return self.format_error(
                            f"Some entities not found: {missing[:5]}",
                            f"Total missing: {len(missing)}"
                        )
                    df = df.loc[entities]
                
                # Filter properties if specified
                if properties:
                    missing = [p for p in properties if p not in df.columns]
                    if missing:
                        return self.format_error(
                            f"Properties not found: {missing}",
                            f"Available: {', '.join(df.columns)}"
                        )
                    df = df[properties]
                
                # Convert to dict format
                export_data = df.to_dict('index')
                
                return self.format_success({
                    "dataset": dataset_name,
                    "entities": len(df),
                    "properties": df.columns.tolist(),
                    "data": export_data
                })
                
            except Exception as e:
                return self.handle_error(e)