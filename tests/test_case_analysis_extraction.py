#!/usr/bin/env python3
"""AST smoke tests for case-analysis extraction and cross-image wiring."""

import ast
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CASE_SERVICE_DIR = ROOT / "python_service/httpserver/services/case_analysis"
CASE_PARTS_DIR = CASE_SERVICE_DIR / "case_analysis_parts"
ROUTES_DIR = ROOT / "python_service/httpserver/routes"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class(tree: ast.AST, name: str) -> ast.ClassDef:
    node = next(
        (item for item in ast.walk(tree) if isinstance(item, ast.ClassDef) and item.name == name),
        None,
    )
    assert node is not None, f"{name} class not found"
    return node


def _function(nodes: Iterable[ast.AST], name: str) -> ast.AST:
    node = next(
        (
            item
            for item in nodes
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
        ),
        None,
    )
    assert node is not None, f"{name} method/function not found"
    return node


def _calls_attribute(node: ast.AST, attribute: str) -> bool:
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == attribute
        for item in ast.walk(node)
    )


def _has_route(node: ast.AST, method: str, path: str) -> bool:
    for item in ast.walk(node):
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in item.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr != method or not decorator.args:
                continue
            first_arg = decorator.args[0]
            if isinstance(first_arg, ast.Constant) and first_arg.value == path:
                return True
    return False


def test_case_analysis_service_composes_refactored_mixins():
    tree = _parse(CASE_SERVICE_DIR / "case_analysis_service.py")
    service_class = _class(tree, "CaseAnalysisService")

    bases = {base.id for base in service_class.bases if isinstance(base, ast.Name)}
    assert bases == {
        "CaseAnalysisCoreMixin",
        "CaseAnalysisWindowsMixin",
        "CaseAnalysisPipelinesMixin",
    }

    init = _function(service_class.body, "__init__")
    initialized_attributes = {
        target.attr
        for item in ast.walk(init)
        if isinstance(item, ast.Assign)
        for target in item.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    assert "_cpp_backend" in initialized_attributes


def test_extraction_is_owned_by_windows_mixin():
    tree = _parse(CASE_PARTS_DIR / "_windows.py")
    mixin = _class(tree, "CaseAnalysisWindowsMixin")
    extraction = _function(mixin.body, "extract_filtered_files")

    assert isinstance(extraction, ast.AsyncFunctionDef)
    assert _calls_attribute(extraction, "extract_files")
    assert _calls_attribute(extraction, "get_extraction_status")


def test_core_mixin_owns_dependency_and_report_operations():
    tree = _parse(CASE_PARTS_DIR / "_core.py")
    mixin = _class(tree, "CaseAnalysisCoreMixin")

    set_backend = _function(mixin.body, "set_cpp_backend")
    descriptions = _function(mixin.body, "generate_file_descriptions")
    report = _function(mixin.body, "generate_case_report")
    cross_report = _function(mixin.body, "get_cross_image_report")

    assert any(
        isinstance(item, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "_cpp_backend" for target in item.targets)
        for item in ast.walk(set_backend)
    )
    assert isinstance(descriptions, ast.AsyncFunctionDef)
    assert isinstance(report, ast.AsyncFunctionDef)
    assert _calls_attribute(report, "generate_final_report")
    assert _calls_attribute(cross_report, "get_cross_image_report")


def test_pipeline_mixin_owns_single_and_cross_image_orchestration():
    tree = _parse(CASE_PARTS_DIR / "_pipelines.py")
    mixin = _class(tree, "CaseAnalysisPipelinesMixin")

    full_analysis = _function(mixin.body, "run_full_analysis")
    multi_analysis = _function(mixin.body, "run_multi_image_analysis")

    assert isinstance(full_analysis, ast.AsyncFunctionDef)
    assert _calls_attribute(full_analysis, "extract_filtered_files")
    assert isinstance(multi_analysis, ast.AsyncFunctionDef)
    assert _calls_attribute(multi_analysis, "filter_files_multi")
    assert _calls_attribute(multi_analysis, "run_full_analysis")
    assert _calls_attribute(multi_analysis, "generate_case_report")
    assert any(
        isinstance(item, ast.keyword)
        and item.arg == "is_cross_image_report"
        and isinstance(item.value, ast.Constant)
        and item.value.value is True
        for item in ast.walk(multi_analysis)
    )


def test_cpp_backend_service_exposes_extraction_api():
    tree = _parse(ROOT / "python_service/httpserver/services/cpp_backend.py")
    service_class = _class(tree, "CppBackendService")

    assert isinstance(_function(service_class.body, "extract_files"), ast.AsyncFunctionDef)
    assert isinstance(_function(service_class.body, "get_extraction_status"), ast.AsyncFunctionDef)


def test_refactored_routes_expose_cross_image_entry_points():
    aggregator = _parse(ROUTES_DIR / "case_analysis.py")
    included_modules = {
        arg.id
        for item in ast.walk(aggregator)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "include_router"
        and item.args
        for arg in [item.args[0].value]
        if isinstance(item.args[0], ast.Attribute)
        and item.args[0].attr == "router"
        and isinstance(arg, ast.Name)
    }
    assert {"_case", "_windows"}.issubset(included_modules)

    case_routes = _parse(ROUTES_DIR / "case_analysis_endpoints/_case.py")
    assert _has_route(case_routes, "get", "/case-report-by-case/{case_id}")
    cross_report_route = _function(case_routes.body, "get_case_report_by_case")
    assert _calls_attribute(cross_report_route, "get_cross_image_report")

    multi_routes = _parse(ROUTES_DIR / "multi_analysis.py")
    assert _has_route(multi_routes, "post", "/api/llm/multi-image-analysis")
    start_route = _function(multi_routes.body, "start_multi_image_analysis")
    assert _calls_attribute(start_route, "run_multi_image_analysis")


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    try:
        for test in tests:
            test()
            print(f"PASS {test.__name__}")
    except Exception as exc:
        print(f"FAIL {test.__name__}: {exc}")
        return 1

    print(f"All {len(tests)} structural smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
