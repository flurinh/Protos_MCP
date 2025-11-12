"""Quick script to inspect dataset entities via Protos processors.

Run with the development environment activated, e.g.:

    conda activate protos
    python scripts/debug_dataset_entities.py --processor sequence --dataset 3sn6_chain_A_mutants

It prints dataset metadata and the resolved entity list so we can verify the
server helpers populate counts correctly.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_server.config import ServerConfig
from mcp_server.context import ServerContext
from mcp_server.core.protos_manager import ProtosManager
from mcp_server.tools.dataset.operations import DatasetOperationTools


def ensure_iterable(obj: Any) -> Iterable[Any]:
    if obj is None:
        return []
    if isinstance(obj, (list, tuple, set)):
        return obj
    try:
        return list(obj)
    except TypeError:
        return [obj]


def main() -> None:
    parser = ArgumentParser(description="Inspect dataset entities for a processor")
    parser.add_argument(
        "--processor",
        default="sequence",
        help="Processor type to inspect (default: sequence)",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Dataset name to inspect. If omitted, the first dataset is used.",
    )
    parser.add_argument(
        "--data-root",
        default=Path(__file__).resolve().parents[1] / "protos" / "data",
        type=Path,
        help="Override Protos data root (defaults to repo protos/data)",
    )
    args = parser.parse_args()

    config = ServerConfig(data_root=args.data_root)
    context = ServerContext.initialize(config=config)
    context.ensure_protos_ready()

    manager = ProtosManager(context)
    processor = manager.get_processor(args.processor)
    dataset_manager = getattr(processor, "dataset_manager", None)
    if dataset_manager is None:
        raise SystemExit(f"Processor '{args.processor}' does not expose a dataset manager")

    dataset_names = dataset_manager.list_datasets()
    if not dataset_names:
        raise SystemExit(f"No datasets found for processor '{args.processor}'")

    dataset_name = args.dataset or dataset_names[0]
    if dataset_name not in dataset_names:
        raise SystemExit(
            f"Dataset '{dataset_name}' not found. Available: {', '.join(dataset_names[:10])}" +
            ("..." if len(dataset_names) > 10 else "")
        )

    info = dataset_manager.get_dataset_info(dataset_name)
    entities = dataset_manager.get_dataset_entities(dataset_name)

    dataset_tools = DatasetOperationTools(context)
    harvested = dataset_tools._harvest_entity_names(info)  # pylint: disable=protected-access
    handle = dataset_tools._record_dataset(  # pylint: disable=protected-access
        tool_name="debug_dataset_entities",
        processor_type=args.processor,
        dataset_name=dataset_name,
        info=dict(info),
    )
    recorded_summary = context.session.get_artifact(handle).summary

    print(f"Data root: {args.data_root}")
    print(f"Processor: {args.processor}")
    print(f"Dataset:   {dataset_name}")
    print("-" * 60)
    print("Metadata keys:", sorted((info.get("metadata") or {}).keys()))
    print("Entity count (info):", info.get("entity_count"))
    sequence_ids = (info.get("metadata") or {}).get("sequence_ids")
    if sequence_ids:
        print("Sequence IDs from metadata:", sequence_ids[:5], "..." if len(sequence_ids) > 5 else "")

    resolved_entities = [str(item) for item in ensure_iterable(entities)]
    print("Resolved entities (first 10):", resolved_entities[:10])
    print("Resolved entity count:", len(resolved_entities))
    print("Harvested entity names (fallback):", harvested[:10])
    print("Harvested count:", len(harvested))
    print("Recorded summary:", recorded_summary)


if __name__ == "__main__":
    main()
