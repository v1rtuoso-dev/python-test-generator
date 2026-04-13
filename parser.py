import os
from indexer import get_parser, load_index
from models import SpringComponent, Dependency, MethodInfo, MethodArg
from tree_sitter import Node

def extract_text(node: Node, content: bytes) -> str:
    if not node:
        return ""
    return content[node.start_byte:node.end_byte].decode('utf-8')

def parse_java_file(file_path: str, project_root: str) -> SpringComponent:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    raw_content = bytes(content, 'utf-8')
        
    parser = get_parser()
    tree = parser.parse(raw_content)
    index = load_index(project_root)
    
    package_name = ""
    component_name = ""
    stereotype = ""
    dependencies = []
    methods = []
    
    root = tree.root_node
    
    # 1. Package name
    for child in root.children:
        if child.type == 'package_declaration':
            for pkg_node in child.children:
                if pkg_node.type in ('scoped_identifier', 'identifier'):
                    package_name = extract_text(pkg_node, raw_content)
                    break
        elif child.type == 'class_declaration':
            # Extract Component Name
            name_node = child.child_by_field_name('name')
            if name_node:
                component_name = extract_text(name_node, raw_content)
                
            # Extract Annotations for Stereotype
            modifiers_node = None
            for c in child.children:
                if c.type == 'modifiers':
                    modifiers_node = c
                    break
            
            if modifiers_node:
                for mod in modifiers_node.children:
                    if mod.type in ('marker_annotation', 'annotation'):
                        name_child = mod.child_by_field_name('name')
                        if not name_child:
                            for c in mod.children:
                                if c.type == 'identifier':
                                    name_child = c
                                    break
                        if name_child:
                            anno_name = extract_text(name_child, raw_content)
                            if anno_name in ('Service', 'RestController', 'Controller', 'Component', 'Repository', 'RestClient'):
                                stereotype = anno_name
                                
            if not stereotype:
                stereotype = "Plain"
            
            # Extract Dependencies and Methods
            body_node = child.child_by_field_name('body')
            if body_node:
                for member in body_node.children:
                    if member.type == 'field_declaration':
                        # Find @Autowired or check if it's private final
                        # Very simplified for PoC
                        type_node = member.child_by_field_name('type')
                        decl_node = member.child_by_field_name('declarator')
                        if type_node and decl_node:
                            dep_type = extract_text(type_node, raw_content)
                            dep_name = extract_text(decl_node.child_by_field_name('name'), raw_content)
                            dependencies.append(Dependency(
                                name=dep_name, 
                                type=dep_type,
                                fqn=index.get(dep_type)
                            ))
                            
                    elif member.type == 'method_declaration':
                        mods = member.child_by_field_name('modifiers')
                        is_public = True
                        is_abstract = False
                        if mods:
                            mod_text = extract_text(mods, raw_content)
                            is_public = 'private' not in mod_text and 'protected' not in mod_text
                            is_abstract = 'abstract' in mod_text
                            
                        # T003 (skip private), T010 (skip abstract)
                        if is_public and not is_abstract:
                            name_node = member.child_by_field_name('name')
                            type_node = member.child_by_field_name('type')
                            params_node = member.child_by_field_name('parameters')
                            body_node = member.child_by_field_name('body')
                            
                            m_name = extract_text(name_node, raw_content) if name_node else ""
                            
                            # T006 - Skip main method
                            if m_name == "main" or m_name == "<init>":
                                continue
                                
                            # T010 - Skip interface methods lacking body implementation entirely
                            if not body_node:
                                continue
                                
                            # T021 - Empty method body. Block has { and }. If len <= 2, it's empty.
                            if len(body_node.children) <= 2:
                                continue
                                
                            # T001, T002 - Trivial getter / setter
                            # Heuristic: if it's named like a getter/setter and the body has only 1 statement
                            if m_name.startswith("get") or m_name.startswith("set") or m_name.startswith("is"):
                                if len(body_node.children) <= 3:
                                    continue # Skip trivial accessors
                                    
                            m_type = extract_text(type_node, raw_content) if type_node else "void"
                            m_args = []
                            
                            if params_node:
                                for param in params_node.children:
                                    if param.type == 'formal_parameter':
                                        p_type = extract_text(param.child_by_field_name('type'), raw_content)
                                        p_name = extract_text(param.child_by_field_name('name'), raw_content)
                                        m_args.append(MethodArg(name=p_name, type=p_type))
                                        
                            methods.append(MethodInfo(name=m_name, return_type=m_type, args=m_args))
                                
    return SpringComponent(
        name=component_name,
        package=package_name,
        stereotype=stereotype,
        dependencies=dependencies,
        methods=methods
    )
