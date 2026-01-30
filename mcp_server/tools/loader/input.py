"""Input folder scanning and registration tools for MCP.

Provides sparse-output tools for discovering and registering files
from the Protos input folder without overwhelming LLM context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..base import BaseTool


class InputLoaderTools(BaseTool):
    """Tools for scanning and registering files from the input folder."""

    @property
    def catalog_group(self) -> str:
        return "input.loader"

    def _get_input_dir(self) -> Path:
        """Get the input directory path."""
        return Path(self.paths.data_root) / "input"

    def _scan_input_folder(self) -> Dict[str, List[Path]]:
        """
        Scan input folder and group files by processor type.

        Returns:
            Dict mapping processor type to list of file paths
        """
        input_dir = self._get_input_dir()

        if not input_dir.exists():
            input_dir.mkdir(parents=True, exist_ok=True)
            return {}

        # File extension to processor type mapping
        extension_map = {
            # Structures
            '.cif': 'structure',
            '.pdb': 'structure',
            '.mmcif': 'structure',
            # Sequences
            '.fasta': 'sequence',
            '.fa': 'sequence',
            '.faa': 'sequence',
            # Molecules/Ligands
            '.sdf': 'molecule',
            '.mol': 'molecule',
            '.mol2': 'molecule',
            # Properties (ambiguous - user may need to specify)
            '.csv': 'property',
            '.tsv': 'property',
        }

        files_by_type: Dict[str, List[Path]] = {}

        for file_path in input_dir.iterdir():
            # Skip directories, hidden files, and README
            if (file_path.is_dir() or
                file_path.name.startswith('.') or
                file_path.name.upper() in ('README.TXT', 'README.MD')):
                continue

            # Get file extension (handle .gz files)
            suffix = file_path.suffix.lower()
            if suffix == '.gz':
                # Check the extension before .gz
                stem_suffix = Path(file_path.stem).suffix.lower()
                if stem_suffix:
                    suffix = stem_suffix

            processor_type = extension_map.get(suffix)
            if processor_type:
                if processor_type not in files_by_type:
                    files_by_type[processor_type] = []
                files_by_type[processor_type].append(file_path)

        return files_by_type

    def register(self, server):
        @server.tool()
        def input_scan(ctx) -> Dict[str, Any]:
            """
            Scan the input folder and return a sparse summary of available files.

            Returns file type counts and registration hints without listing
            all filenames to keep LLM context minimal.
            """
            try:
                input_dir = self._get_input_dir()

                if not input_dir.exists():
                    return self.format_success({
                        "input_folder": str(input_dir),
                        "exists": False,
                        "hint": "Input folder does not exist. It will be created on first use."
                    })

                files_by_type = self._scan_input_folder()

                if not files_by_type:
                    return self.format_success({
                        "input_folder": str(input_dir),
                        "exists": True,
                        "total_files": 0,
                        "types": {},
                        "hint": "No recognizable files found. Place .cif/.pdb (structures), .fasta (sequences), or .sdf (molecules) files here."
                    })

                # Build sparse summary - counts only, not filenames
                type_summary = {}
                total = 0

                for proc_type, files in files_by_type.items():
                    count = len(files)
                    total += count

                    # Provide registration hint based on count
                    if count == 1:
                        hint = "Will register as single entity"
                    else:
                        hint = f"Will create dataset with {count} entities"

                    type_summary[proc_type] = {
                        "count": count,
                        "hint": hint
                    }

                return self.format_success({
                    "input_folder": str(input_dir),
                    "total_files": total,
                    "types": type_summary,
                    "next_step": "Use input_register() to register files, optionally specifying processor_type and dataset_name"
                })

            except Exception as exc:
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=input_scan,
            name="input_scan",
            description="Scan input folder and return sparse summary of available files by type.",
            parameters=[],
            returns={"fields": ["total_files", "types", "next_step"]},
            tags=["input", "scan", "loader"],
        )

        @server.tool()
        def input_register(
            ctx,
            processor_type: Optional[str] = None,
            dataset_name: Optional[str] = None,
            overwrite: bool = False,
        ) -> Dict[str, Any]:
            """
            Register files from the input folder.

            - For multiple files of the same type: creates a dataset
            - For single files: registers as individual entity

            Args:
                processor_type: Filter to specific type (structure, sequence, molecule).
                                If None, processes all types.
                dataset_name: Custom dataset name. If None, auto-generates based on type.
                overwrite: Whether to overwrite existing entities.
            """
            try:
                files_by_type = self._scan_input_folder()

                if not files_by_type:
                    return self.format_error(
                        "No files found in input folder",
                        "Place files in the input folder first, then run input_scan to verify."
                    )

                # Filter by processor type if specified
                if processor_type:
                    if error := self.validate_processor_type(processor_type):
                        return error

                    if processor_type not in files_by_type:
                        available = list(files_by_type.keys())
                        return self.format_error(
                            f"No {processor_type} files found in input folder",
                            f"Available types: {', '.join(available)}"
                        )

                    files_by_type = {processor_type: files_by_type[processor_type]}

                results: Dict[str, Any] = {
                    "registered": [],
                    "datasets_created": [],
                    "failed": [],
                    "skipped": [],
                }

                for proc_type, files in files_by_type.items():
                    try:
                        reg_result = self._register_files_for_type(
                            proc_type,
                            files,
                            dataset_name=dataset_name if processor_type else None,
                            overwrite=overwrite
                        )

                        results["registered"].extend(reg_result.get("registered", []))
                        if reg_result.get("dataset"):
                            results["datasets_created"].append({
                                "name": reg_result["dataset"],
                                "type": proc_type,
                                "entity_count": len(reg_result.get("registered", []))
                            })
                        results["failed"].extend(reg_result.get("failed", []))
                        results["skipped"].extend(reg_result.get("skipped", []))

                    except Exception as exc:
                        results["failed"].append({
                            "type": proc_type,
                            "error": str(exc)
                        })

                # Build summary
                summary = {
                    "registered_count": len(results["registered"]),
                    "datasets_created": len(results["datasets_created"]),
                    "failed_count": len(results["failed"]),
                }

                if results["datasets_created"]:
                    summary["datasets"] = results["datasets_created"]

                if results["failed"]:
                    summary["failures"] = results["failed"]

                if results["skipped"]:
                    summary["skipped_count"] = len(results["skipped"])

                message = f"Registered {summary['registered_count']} entities"
                if summary["datasets_created"]:
                    message += f", created {summary['datasets_created']} dataset(s)"

                return self.format_success(summary, message=message)

            except Exception as exc:
                return self.handle_error(exc)

        self.register_tool_metadata(
            function=input_register,
            name="input_register",
            description="Register files from input folder. Creates datasets for multiple files, individual entities for singles.",
            parameters=[
                {"name": "processor_type", "type": "str", "optional": True},
                {"name": "dataset_name", "type": "str", "optional": True},
                {"name": "overwrite", "type": "bool", "default": False},
            ],
            returns={"fields": ["registered_count", "datasets_created", "failed_count"]},
            tags=["input", "register", "loader", "dataset"],
        )

    def _register_files_for_type(
        self,
        processor_type: str,
        files: List[Path],
        dataset_name: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Register files for a specific processor type.

        Args:
            processor_type: The processor type (structure, sequence, molecule)
            files: List of file paths to register
            dataset_name: Optional custom dataset name
            overwrite: Whether to overwrite existing entities

        Returns:
            Dict with registered entities, dataset name (if created), and failures
        """
        result: Dict[str, Any] = {
            "registered": [],
            "failed": [],
            "skipped": [],
            "dataset": None,
        }

        # Get the appropriate loader
        if processor_type == "structure":
            from protos.io.ingest.structure_loader import StructureLoader
            processor = self.get_processor("structure")
            loader = StructureLoader(processor=processor)
        elif processor_type == "sequence":
            from protos.io.ingest.sequence_loader import SequenceLoader
            processor = self.get_processor("sequence")
            loader = SequenceLoader(processor=processor)
        elif processor_type == "molecule":
            from protos.io.ingest.ligand_loader import LigandLoader
            processor = self.get_processor("molecule")
            loader = LigandLoader(processor=processor)
        else:
            # For other types, try generic approach
            processor = self.get_processor(processor_type)
            loader = None

        # Process each file
        for file_path in files:
            entity_name = file_path.stem

            # Check if entity already exists
            if not overwrite and hasattr(processor, 'entity_exists') and processor.entity_exists(entity_name):
                result["skipped"].append(entity_name)
                continue

            try:
                if loader:
                    # Use loader's download_and_register with local source
                    registered = loader.download_and_register(
                        identifier=str(file_path),
                        name=entity_name,
                        source='local'
                    )

                    if registered:
                        result["registered"].append(registered)
                        # Remove file from input folder after successful registration
                        try:
                            file_path.unlink()
                        except Exception:
                            pass  # Don't fail if we can't delete
                    else:
                        result["failed"].append({"file": file_path.name, "error": "Registration returned None"})
                else:
                    result["failed"].append({"file": file_path.name, "error": f"No loader for {processor_type}"})

            except Exception as exc:
                result["failed"].append({"file": file_path.name, "error": str(exc)})

        # Create dataset if we have multiple registered entities
        if len(result["registered"]) > 1:
            ds_name = dataset_name or f"{processor_type}_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            try:
                manager = processor.dataset_manager
                manager.create_dataset(
                    name=ds_name,
                    entities=result["registered"],
                    metadata={
                        "source": "input_folder",
                        "import_date": datetime.now().isoformat(),
                        "processor_type": processor_type,
                    }
                )
                result["dataset"] = ds_name
            except Exception as exc:
                result["failed"].append({"dataset": ds_name, "error": str(exc)})

        return result
