"""Property table data and analysis tools backed by PropertyProcessor."""

from typing import Dict, List, Optional, Any, Union, Callable
import json
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

            # Return metadata + limited preview only - full data stays in Protos context
            max_preview = min(limit or 10, 10)  # Cap at 10 rows max
            payload = {
                "table_name": table_name,
                "row_count": int(len(table)),
                "columns": table.columns.tolist(),
                "preview": table.head(max_preview).to_dict(orient="records"),
                "note": "Full table available in Protos context. Use property operations for analysis.",
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
                
                # Convert data to property rows format with auto-generated scope
                # This allows the model to create simple knowledge tables without
                # worrying about the scope format
                rows = []
                if isinstance(data, dict):
                    for entity_id, props in data.items():
                        row = {
                            "entity_name": entity_id,
                            "scope": [{"format": "property", "name": entity_id}],
                            **props,
                        }
                        rows.append(row)
                elif isinstance(data, list):
                    for item in data:
                        entity_id = item.get('entity_id') or item.get('entity_name')
                        if not entity_id:
                            return self.format_error(
                                "Missing entity_id/entity_name in data items",
                                "Each item must have an 'entity_id' or 'entity_name' key"
                            )
                        row = {
                            "entity_name": entity_id,
                            "scope": item.get("scope", [{"format": "property", "name": entity_id}]),
                        }
                        # Add all other properties
                        for k, v in item.items():
                            if k not in ("entity_id", "entity_name", "scope"):
                                row[k] = v
                        rows.append(row)

                # Create property table using record_properties
                # Note: PropertyProcessor uses table_name, MCP uses dataset_name for consistency
                df = processor.record_properties(
                    table_name=dataset_name,
                    rows=rows,
                    metadata=metadata,
                    allow_create=True,
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

            # Return metadata + preview only - full data stays in Protos context
            return self.format_success(
                {
                    "dataset_name": dataset_name,
                    "row_count": int(len(table)),
                    "columns": table.columns.tolist(),
                    "preview": table.head(10).to_dict(orient="records"),
                    "note": "Full data available in Protos context.",
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
        def update_property_values(
            ctx,
            dataset_name: str,
            updates: Dict[str, Dict[str, Any]],
        ) -> Dict:
            """
            Update specific values in a property table.

            Allows the model to modify individual cells or multiple properties
            for specific entities without replacing the entire table.

            Args:
                dataset_name: Name of the property table
                updates: Dict mapping entity_id to {property: new_value}
                        Example: {"ADRB2": {"receptor_family": "Adrenergic (β)", "affinity": 5.2}}

            Returns:
                Dictionary with update status
            """
            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "updates": updates},
                    ["dataset_name", "updates"]
                ):
                    return error

                processor = self.get_processor("property")

                # Load existing table
                try:
                    df = processor.load_table(dataset_name)
                except Exception:
                    return self.format_error(
                        f"Property table '{dataset_name}' not found",
                        "Create the table first with create_property_table or record_property_rows"
                    )

                # Property tables use entity_name column, not index
                existing_entities = set(df["entity_name"].dropna().tolist()) if "entity_name" in df.columns else set()

                # Apply updates
                updated_entities = []
                added_entities = []
                new_columns = set()

                for entity_id, props in updates.items():
                    if entity_id in existing_entities:
                        # Update existing entity's properties
                        mask = df["entity_name"] == entity_id
                        for prop, value in props.items():
                            if prop not in df.columns:
                                df[prop] = None
                                new_columns.add(prop)
                            df.loc[mask, prop] = value
                        updated_entities.append(entity_id)
                    else:
                        # Add new entity row
                        new_row = {
                            "entity_name": entity_id,
                            "scope": [{"format": "property", "name": entity_id}],
                        }
                        for prop, value in props.items():
                            if prop not in df.columns:
                                df[prop] = None
                                new_columns.add(prop)
                            new_row[prop] = value
                        # Convert scope to JSON string for CSV storage
                        new_row["scope"] = json.dumps(new_row["scope"])
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        added_entities.append(entity_id)

                # Save the updated table
                processor._write_table(dataset_name, df)

                return self.format_success({
                    "dataset_name": dataset_name,
                    "updated_entities": updated_entities,
                    "added_entities": added_entities,
                    "new_columns": list(new_columns),
                    "total_entities": len(df),
                    "total_properties": len(df.columns),
                })

            except Exception as e:
                return self.handle_error(e)

        @server.tool()
        def delete_property_rows(
            ctx,
            dataset_name: str,
            entity_ids: List[str],
        ) -> Dict:
            """
            Delete specific rows (entities) from a property table.

            Args:
                dataset_name: Name of the property table
                entity_ids: List of entity IDs to delete

            Returns:
                Dictionary with deletion status
            """
            try:
                if error := self.validate_required_params(
                    {"dataset_name": dataset_name, "entity_ids": entity_ids},
                    ["dataset_name", "entity_ids"]
                ):
                    return error

                processor = self.get_processor("property")

                # Load existing table
                try:
                    df = processor.load_table(dataset_name)
                except Exception:
                    return self.format_error(
                        f"Property table '{dataset_name}' not found",
                        "Check table name with list_property_tables"
                    )

                # Track what was deleted
                deleted = []
                not_found = []

                for entity_id in entity_ids:
                    if entity_id in df.index:
                        df = df.drop(entity_id)
                        deleted.append(entity_id)
                    else:
                        not_found.append(entity_id)

                # Save the updated table
                processor._write_table(dataset_name, df)

                return self.format_success({
                    "dataset_name": dataset_name,
                    "deleted": deleted,
                    "not_found": not_found,
                    "remaining_entities": len(df),
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
                
                # In LLM-safe mode, limit the entity list further
                max_entities = 20 if self.llm_safe_mode else 100

                return self.format_success({
                    "dataset": dataset_name,
                    "filter": {
                        "property": property_name,
                        "operator": operator,
                        "value": value
                    },
                    "matched_entities": len(entities),
                    "entities": entities[:max_entities],
                    "truncated": len(entities) > max_entities
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
                
                # In LLM-safe mode, return preview only
                if self.llm_safe_mode:
                    max_preview = min(10, len(df))
                    preview_df = df.head(max_preview)
                    return self.format_success({
                        "dataset": dataset_name,
                        "total_entities": len(df),
                        "properties": df.columns.tolist(),
                        "preview_entities": max_preview,
                        "preview_data": preview_df.to_dict('index'),
                        "note": "Showing preview only (LLM-safe mode). Full data saved to disk.",
                    })
                else:
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
