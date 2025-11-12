"""Run MCP workflows and summarise context handle coverage."""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class WorkflowReport:
    name: str
    success: bool
    context_handles: List[str]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def discover_workflow_scripts(workflow_dir: Path) -> List[Path]:
    return sorted(path for path in workflow_dir.glob("*_via_tools.py") if path.is_file())


def _extract_handles(payload: Any) -> List[str]:
    handles: List[str] = []

    def _scan(value: Any) -> None:
        if isinstance(value, dict):
            for key, val in value.items():
                if key == "context_handle" and isinstance(val, str):
                    handles.append(val)
                else:
                    _scan(val)
        elif isinstance(value, list):
            for item in value:
                _scan(item)
        elif isinstance(value, str) and value.count(".") >= 2:
            prefix = value.split(".", 1)[0]
            if prefix in {"dataset", "entity", "result"}:
                handles.append(value)

    _scan(payload)
    return sorted(set(handles))


async def _run_module(path: Path) -> WorkflowReport:
    module_name = f"workflow_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return WorkflowReport(name=path.name, success=False, context_handles=[], error="Failed to import module")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[assignment]

    run_callable = getattr(module, "run_workflow", None)
    if run_callable is None:
        return WorkflowReport(
            name=path.name,
            success=False,
            context_handles=[],
            error="run_workflow() not defined",
        )

    try:
        result = await run_callable() if asyncio.iscoroutinefunction(run_callable) else run_callable()
        handles = _extract_handles(result)
        return WorkflowReport(
            name=path.name,
            success=True,
            context_handles=handles,
            result=result if isinstance(result, dict) else None,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback
        return WorkflowReport(
            name=path.name,
            success=False,
            context_handles=[],
            error=str(exc),
            result={"traceback": traceback.format_exc()},
        )


async def run_workflows(
    *,
    workflow_dir: Path,
    names: Optional[Iterable[str]] = None,
) -> List[WorkflowReport]:
    scripts = discover_workflow_scripts(workflow_dir)
    if names:
        wanted = {Path(name).stem for name in names}
        scripts = [script for script in scripts if script.stem in wanted or script.name in wanted]

    reports: List[WorkflowReport] = []
    for script in scripts:
        reports.append(await _run_module(script))
    return reports


def summarise_reports(reports: Iterable[WorkflowReport]) -> Dict[str, Any]:
    summary = {
        "total": 0,
        "success": 0,
        "failure": 0,
        "workflows": [],
    }
    for report in reports:
        summary["total"] += 1
        summary_key = "success" if report.success else "failure"
        summary[summary_key] += 1
        summary["workflows"].append(
            {
                "name": report.name,
                "success": report.success,
                "context_handles": report.context_handles,
                "error": report.error,
            }
        )
    return summary


async def main(names: Optional[List[str]] = None) -> None:
    workflow_dir = Path(__file__).resolve().parent.parent / "workflows"
    reports = await run_workflows(workflow_dir=workflow_dir, names=names)
    summary = summarise_reports(reports)
    for item in summary["workflows"]:
        status = "OK" if item["success"] else "FAIL"
        handles = ", ".join(item["context_handles"]) or "<none>"
        print(f"[{status}] {item['name']} :: context={handles}")
        if item.get("error"):
            print(f"    error: {item['error']}")
    print(f"Totals: {summary['success']} passed / {summary['failure']} failed")


if __name__ == "__main__":
    asyncio.run(main())
