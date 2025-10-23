"""Property table data and analysis tools backed by PropertyProcessor."""

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
        def list_property_tables(ctx) -> Dict:
            """List all property tables registered with Protos."""

            processor = self.get_processor("property")
            tables = processor.list_tables()
            return self.format_success({
                "tables": tables,
                "count": len(tables),
            })

        @server.tool()
        def load_property_table(ctx, table_name: str, limit: Optional[int] = None) -> Dict:
            """Load a property table as JSON for inspection."""

            if error := self.validate_required_params(
                {"table_name": table_name}, ["table_name"],
            ):
                return error

            processor = self.get_processor("property")
            try:
                table = processor.load_table(table_name)
            except FileNotFoundError:
                return self.format_error(
                    f"Property table '{table_name}' not found",
                    "Use list_property_tables to see available tables.",
                )

            payload = {
                "table_name": table_name,
                "row_count": int(len(table)),
                "columns": table.columns.tolist(),
                "data": table.head(limit).to_dict(orient="records") if limit else table.to_dict(orient="records"),
                "truncated": bool(limit and len(table) > limit),
            }
            return self.format_success(payload)

        @server.tool()
        def save_property_table(
            ctx,
            table_name: str,
            metadata: Optional[Dict[str, Any]] = None,
        ) -> Dict:
            """Persist property table metadata and ensure dataset registration is updated."""

            if error := self.validate_required_params(
                {"table_name": table_name}, ["table_name"],
            ):
                return error

            processor = self.get_processor("property")
            try:
                processor.save_property_table(table_name, metadata=metadata)
            except FileNotFoundError:
                return self.format_error(
                    f"Property table '{table_name}' not found",
                    "Create the table first before attempting to save metadata.",
                )

            info = processor.dataset_manager.get_dataset_info(table_name)
            return self.format_success(info, message="Property table saved")

        @server.tool()
        def create_property_table(
            ctx,
            dataset_name: str,
            data: Union[Dict[str, Dict[str, Any]], List[Dict[str, Any]]],
            metadata: Optional[Dict] = None,
        ) -> Dict:
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
        def record_property_rows(
            ctx,
            dataset_name: str,
            rows: Union[List[Dict[str, Any]], Dict[str, Any]],
            metadata: Optional[Dict[str, Any]] = None,
            allow_create: bool = False,
        ) -> Dict:
            """Append rows to a property table using `record_properties`."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name, "rows": rows}, ["dataset_name", "rows"],
            ):
                return error

            processor = self.get_processor("property")

            if isinstance(rows, dict):
                row_payload = [rows]
            else:
                row_payload = rows

            updated = processor.record_properties(
                dataset_name,
                row_payload,
                metadata=metadata,
                allow_create=allow_create,
            )

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "row_count": int(len(updated)),
                    "columns": updated.columns.tolist(),
                },
                message="Property rows recorded",
            )

        @server.tool()
        def load_property_rows(
            ctx,
            dataset_name: str,
            entity_name: Optional[str] = None,
            scope_format: Optional[str] = None,
        ) -> Dict:
            """Load property rows, optionally filtered by entity scope."""

            if error := self.validate_required_params(
                {"dataset_name": dataset_name}, ["dataset_name"],
            ):
                return error

            processor = self.get_processor("property")
            table = processor.load_dataset_rows(
                table_name=dataset_name,
                entity_name=entity_name,
                format_type=scope_format,
            )

            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "row_count": int(len(table)),
                    "columns": table.columns.tolist(),
                    "data": table.to_dict(orient="records"),
                }
            )

        @server.tool()
        def add_property_column(
            ctx,
            dataset_name: str,
            property_name: str,
            values: Union[Dict[str, Any], Any],
        ) -> Dict:
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
        def merge_property_tables(
            ctx,
            dataset_names: List[str],
            output_name: str,
            how: str = "outer",
        ) -> Dict:
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
                
                processor = self.get_processor("property")

                tables: List[pd.DataFrame] = []
                for name in dataset_names:
                    try:
                        tables.append(processor.load_table(name))
                    except FileNotFoundError:
                        return self.format_error(
                            f"Property table '{name}' not found",
                            "Ensure all source tables exist before merging.",
                        )

                if not tables:
                    return self.format_error(
                        "No property tables loaded",
                        "Verify dataset names are correct.",
                    )

                merged_df = tables[0]
                for table in tables[1:]:
                    merged_df = merged_df.merge(
                        table,
                        left_index=True,
                        right_index=True,
                        how=how,
                        suffixes=("", "_dup"),
                    )

                # Remove duplicate suffix columns if any
                duplicate_cols = [col for col in merged_df.columns if col.endswith("_dup")]
                if duplicate_cols:
                    merged_df = merged_df.drop(columns=duplicate_cols)

                processor.create_property_table(
                    table_name=output_name,
                    data=merged_df,
                    metadata={"merged_from": dataset_names, "merge_method": how},
                    allow_create=True,
                )

                return self.format_success(
                    {
                        "output_name": output_name,
                        "merged_from": dataset_names,
                        "merge_method": how,
                        "entities": int(len(merged_df)),
                        "properties": merged_df.columns.tolist(),
                        "shape": list(merged_df.shape),
                    }
                )
                
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
