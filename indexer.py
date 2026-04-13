import os
import json
from pathlib import Path
from rich import print
import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

JAVA_LANGUAGE = Language(tsjava.language())

def get_parser() -> Parser:
    parser = Parser()
    parser.language = JAVA_LANGUAGE
    return parser

def build_index(project_root: str, output_file: str = ".spring_test_gen_index.json") -> dict:
    """
    Scans the given project root for .java files and builds an index mapping
    ClassNames to their fully qualified package path (e.g., UserService -> com.example.service.UserService).
    """
    index = {}
    parser = get_parser()
    
    # We only care about src/main/java for type indexing
    src_dir = Path(project_root) / "src" / "main" / "java"
    if not src_dir.exists():
        print(f"[yellow]Warning: Could not find src/main/java in {project_root}[/yellow]")
        src_dir = Path(project_root) # Fallback to scan everything if standard structure missing
        
    for path in src_dir.rglob("*.java"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                
            tree = parser.parse(bytes(content, "utf-8"))
            root_node = tree.root_node
            
            package_name = ""
            class_names = []
            
            # Simple traversal to find package and class/interface/enum names
            for child in root_node.children:
                if child.type == 'package_declaration':
                    # Find the scoped_identifier or identifier inside package
                    for pkg_child in child.children:
                        if pkg_child.type in ('scoped_identifier', 'identifier'):
                            package_name = content[pkg_child.start_byte:pkg_child.end_byte]
                            
                elif child.type in ('class_declaration', 'interface_declaration', 'enum_declaration', 'record_declaration'):
                    for class_child in child.children:
                        if class_child.type == 'identifier':
                            class_names.append(content[class_child.start_byte:class_child.end_byte])
                            
            for class_name in class_names:
                fqn = f"{package_name}.{class_name}" if package_name else class_name
                index[class_name] = fqn
                
        except Exception as e:
            print(f"[red]Error parsing {path}: {e}[/red]")
            
    # Save the index
    output_path = Path(project_root) / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=4)
        
    return index

def load_index(project_root: str, index_file: str = ".spring_test_gen_index.json") -> dict:
    output_path = Path(project_root) / index_file
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
