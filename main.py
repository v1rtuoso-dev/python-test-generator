import json
import os
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich import print

load_dotenv()

app = typer.Typer(help="Spring Boot Unit Test Generator (Python)")

from indexer import build_index
from parser import parse_java_file
from generator import generate_static_test, fill_ai_logic
from config import load_config, should_include
from merger import merge_into_existing
from manifest import load_manifest, save_manifest, has_changed, update_entry
from coverage import parse_jacoco, is_method_uncovered
from analyzer import analyze_project


def _detect_project_root(source_file: str) -> str:
    parts = list(Path(source_file).parts)
    if "src" in parts:
        src_idx = parts.index("src")
        return str(Path(*parts[:src_idx]))
    return os.getcwd()


def _write_test(component, project_root: str, output_dir: str, final_code: str, merge_mode: str) -> Path:
    pkg_path = component.package.replace(".", "/")
    out_dir_full = Path(project_root) / output_dir / pkg_path
    os.makedirs(out_dir_full, exist_ok=True)
    out_file = out_dir_full / f"{component.name}Test.java"
    if out_file.exists() and merge_mode == "append":
        merged = merge_into_existing(out_file, final_code)
        out_file.write_text(merged, encoding="utf-8")
    else:
        out_file.write_text(final_code, encoding="utf-8")
    return out_file


def _filter_methods_by_coverage(component, uncovered_set, fqn_override: Optional[str] = None):
    if not uncovered_set:
        return
    fqn = fqn_override or f"{component.package}.{component.name}"
    component.methods = [m for m in component.methods if is_method_uncovered(uncovered_set, fqn, m.name)]


@app.command()
def scan(project_root: str = typer.Argument(..., help="Path to the root of the Spring Boot project")):
    """Scans the Java project to build a local type and symbol index."""
    print(f"[bold green]Scanning project at {project_root}...[/bold green]")
    index = build_index(project_root)
    print(f"[bold blue]Indexing complete. Indexed {len(index)} canonical class names.[/bold blue]")


@app.command()
def analyze(
    project_root: str = typer.Argument(..., help="Path to the root of the Spring Boot project"),
    output: Optional[str] = typer.Option(None, help="Optional path to write the JSON report to"),
):
    """Classify every class in the project and emit a JSON summary."""
    print(f"[bold green]Analyzing project at {project_root}...[/bold green]")
    build_index(project_root)
    report = analyze_project(project_root)
    text = json.dumps(report, indent=2)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        print(f"[bold blue]Report written to {output}[/bold blue]")
    else:
        print(text)
    print(
        f"[bold cyan]Summary: {report.get('total_classes', 0)} classes, "
        f"{report.get('testable_methods', 0)} testable methods, "
        f"{len(report.get('missing_tests', []))} classes missing tests.[/bold cyan]"
    )


@app.command()
def generate(
    source_file: str = typer.Argument(..., help="Path to the .java file to generate tests for"),
    project_root: Optional[str] = typer.Option(None, help="Root of your Spring Boot project (auto-detected if empty)"),
    output_dir: str = typer.Option("src/test/java", help="Output directory for generated tests"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip the AI polish pass"),
):
    """Generates a unit test for the given Spring Boot Java class."""
    print(f"[bold green]Generating test for {source_file}...[/bold green]")
    if not project_root:
        project_root = _detect_project_root(source_file)
    print(f"[dim]Anchoring test output to project root: {project_root}[/dim]")

    cfg = load_config(project_root)
    build_index(project_root)
    component = parse_java_file(source_file, project_root)
    if not component.name:
        print("[red]Could not extract class name from file.[/red]")
        raise typer.Exit(1)

    print(
        f"[cyan]Extracted component: {component.name} ({component.stereotype}) "
        f"with {len(component.dependencies)} deps and {len(component.methods)} methods.[/cyan]"
    )

    scaffold_code = generate_static_test(component, cfg)

    final_code = scaffold_code
    if not no_ai:
        original_source = Path(source_file).read_text(encoding="utf-8")
        final_code = fill_ai_logic(scaffold_code, original_source, component, Path(project_root))

    out_file = _write_test(component, project_root, output_dir, final_code, cfg.get("merge_mode", "append"))
    print(f"[bold blue]Test generated successfully at {out_file}[/bold blue]")


@app.command("generate-all")
def generate_all(
    project_root: str = typer.Argument(..., help="Path to the root of the Spring Boot project"),
    output_dir: str = typer.Option("src/test/java", help="Output directory for generated tests"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip the AI polish pass"),
    changed_only: bool = typer.Option(False, "--changed-only", help="Only regenerate for sources whose SHA256 changed"),
    uncovered_only: Optional[str] = typer.Option(
        None, "--uncovered-only",
        help="Path to a JaCoCo jacoco.xml; only generate for methods with coverage below --threshold",
    ),
    threshold: float = typer.Option(50.0, help="Line-coverage threshold percent when using --uncovered-only"),
):
    """Generates unit tests for all Spring Boot components in the project."""
    print(f"[bold green]Scanning for Spring Boot components in {project_root}...[/bold green]")
    src_dir = Path(project_root) / "src" / "main" / "java"
    if not src_dir.exists():
        print(f"[red]Could not find src/main/java in {project_root}[/red]")
        raise typer.Exit(1)

    cfg = load_config(project_root)
    build_index(project_root)

    uncovered_set = parse_jacoco(uncovered_only, threshold) if uncovered_only else set()
    if uncovered_only:
        print(f"[cyan]Coverage filter active: {len(uncovered_set)} uncovered methods below {threshold}%.[/cyan]")

    manifest = load_manifest(project_root) if changed_only else {}
    merge_mode = cfg.get("merge_mode", "append")
    generated_count = 0
    skipped_count = 0

    for file_path in src_dir.rglob("*.java"):
        fpath = str(file_path)
        if not should_include(fpath, cfg):
            skipped_count += 1
            continue
        if changed_only and not has_changed(project_root, fpath, manifest):
            skipped_count += 1
            continue
        try:
            component = parse_java_file(fpath, project_root)
            if not component.name or not component.methods:
                continue

            if uncovered_set:
                _filter_methods_by_coverage(component, uncovered_set)
                if not component.methods:
                    continue

            print(f"[cyan]Found: {component.name} ({component.stereotype}) - Scaffolding...[/cyan]")
            scaffold_code = generate_static_test(component, cfg)
            final_code = scaffold_code
            if not no_ai:
                original_source = Path(fpath).read_text(encoding="utf-8")
                final_code = fill_ai_logic(scaffold_code, original_source, component, Path(project_root))

            _write_test(component, project_root, output_dir, final_code, merge_mode)
            generated_count += 1
            if changed_only:
                update_entry(project_root, fpath, manifest)
        except Exception as e:
            print(f"[yellow]Skipping {file_path.name} due to an error: {e}[/yellow]")

    if changed_only:
        save_manifest(project_root, manifest)

    print(
        f"[bold blue]Generated {generated_count} test file(s). "
        f"Skipped {skipped_count} (filtered/unchanged).[/bold blue]"
    )


if __name__ == "__main__":
    app()
