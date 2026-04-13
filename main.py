import typer
from rich import print
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

app = typer.Typer(help="Spring Boot Unit Test Generator (Python)")

from indexer import build_index

@app.command()
def scan(project_root: str = typer.Argument(..., help="Path to the root of the Spring Boot project")):
    """
    Scans the Java project to build a local type and symbol index.
    """
    print(f"[bold green]Scanning project at {project_root}...[/bold green]")
    index = build_index(project_root)
    print(f"[bold blue]Indexing complete. Indexed {len(index)} canonical class names.[/bold blue]")

from parser import parse_java_file
from generator import generate_static_test, fill_ai_logic
from pathlib import Path
import os

@app.command()
def generate(
    source_file: str = typer.Argument(..., help="Path to the .java file to generate tests for"),
    project_root: str = typer.Option(None, help="Root of your Spring Boot project (Auto-detected if left empty)"),
    output_dir: str = typer.Option("src/test/java", help="Output directory for generated tests")
):
    """
    Generates a unit test for the given Spring Boot Java class.
    """
    print(f"[bold green]Generating test for {source_file}...[/bold green]")
    
    # Auto-detect Spring Boot project root from the source file path
    if not project_root:
        parts = list(Path(source_file).parts)
        if "src" in parts:
            src_idx = parts.index("src")
            project_root = str(Path(*parts[:src_idx]))
        if not project_root:
            project_root = os.getcwd()
            
    print(f"[dim]Anchoring test output to project root: {project_root}[/dim]")
    
    # 1. Parse AST
    component = parse_java_file(source_file, project_root)
    if not component.name:
        print("[red]Could not extract class name from file.[/red]")
        raise typer.Exit(1)
        
    print(f"[cyan]Extracted component: {component.name} ({component.stereotype}) with {len(component.dependencies)} deps and {len(component.methods)} methods.[/cyan]")
    
    # 2. Static Scaffolding
    scaffold_code = generate_static_test(component)
    
    # 3. AI Pass
    with open(source_file, "r", encoding="utf-8") as f:
        original_source = f.read()
    final_code = fill_ai_logic(scaffold_code, original_source)
    
    # 4. Save
    pkg_path = component.package.replace(".", "/")
    out_dir_full = Path(project_root) / output_dir / pkg_path
    os.makedirs(out_dir_full, exist_ok=True)
    
    out_file = out_dir_full / f"{component.name}Test.java"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(final_code)
        
    print(f"[bold blue]Test generated successfully at {out_file}[/bold blue]")

@app.command()
def generate_all(
    project_root: str = typer.Argument(..., help="Path to the root of the Spring Boot project"),
    output_dir: str = typer.Option("src/test/java", help="Output directory for generated tests")
):
    """
    Generates unit tests for all Spring Boot components (@Service, @RestController) found in the project.
    """
    print(f"[bold green]Scanning for Spring Boot components in {project_root}...[/bold green]")
    src_dir = Path(project_root) / "src" / "main" / "java"
    
    if not src_dir.exists():
        print(f"[red]Could not find src/main/java in {project_root}[/red]")
        raise typer.Exit(1)
        
    generated_count = 0
    for file_path in src_dir.rglob("*.java"):
        try:
            # print(f"[dim]Checking: {file_path.name}...[/dim]") # Removed verbose output
            component = parse_java_file(str(file_path), project_root)
            # Only generate tests for classes that actually have testable methods extracted
            if component.name and len(component.methods) > 0:
                print(f"[cyan]Found: {component.name} ({component.stereotype}) - Scaffolding...[/cyan]")
                
                scaffold_code = generate_static_test(component)
                with open(str(file_path), "r", encoding="utf-8") as f:
                    original_source = f.read()
                final_code = fill_ai_logic(scaffold_code, original_source)
                
                pkg_path = component.package.replace(".", "/")
                out_dir_full = Path(project_root) / output_dir / pkg_path
                os.makedirs(out_dir_full, exist_ok=True)
                
                out_file = out_dir_full / f"{component.name}Test.java"
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(final_code)
                generated_count += 1
        except Exception as e:
            print(f"[yellow]Skipping {file_path.name} due to an error: {e}[/yellow]")
            
    print(f"[bold blue]Successfully generated {generated_count} test files.[/bold blue]")

if __name__ == "__main__":
    app()
