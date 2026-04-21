from indexer import get_parser, load_index
from models import SpringComponent, Dependency, MethodInfo, MethodArg, CallSite
from tree_sitter import Node
from typing import List, Optional, Tuple, Dict

SPRING_STEREOTYPES = {
    "Service", "RestController", "Controller", "Component", "Repository", "RestClient",
}

LOMBOK_ANNOTATIONS = {
    "RequiredArgsConstructor", "AllArgsConstructor", "NoArgsConstructor",
    "Data", "Value", "Builder", "Getter", "Setter",
}

OBJECT_METHOD_DENYLIST = {
    "toString", "hashCode", "equals", "wait", "notify", "notifyAll",
    "getClass", "clone", "finalize",
}

HTTP_MAPPING_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": "REQUEST",
}


def _text(node: Optional[Node], raw: bytes) -> str:
    if not node:
        return ""
    return raw[node.start_byte:node.end_byte].decode("utf-8")


def _find_child(node: Node, type_name: str) -> Optional[Node]:
    for c in node.children:
        if c.type == type_name:
            return c
    return None


def _find_children(node: Node, type_name: str) -> List[Node]:
    return [c for c in node.children if c.type == type_name]


def _annotation_name(anno_node: Node, raw: bytes) -> str:
    """Extract bare annotation name from a marker_annotation / annotation node."""
    name_child = anno_node.child_by_field_name("name")
    if name_child:
        text = _text(name_child, raw)
        return text.split(".")[-1]
    for c in anno_node.children:
        if c.type in ("identifier", "scoped_identifier"):
            return _text(c, raw).split(".")[-1]
    return ""


def _annotation_string_argument(anno_node: Node, raw: bytes) -> Optional[str]:
    """For @GetMapping("/path") or @RequestMapping(value = "/x"), return the string literal value."""
    args_node = anno_node.child_by_field_name("arguments")
    if not args_node:
        for c in anno_node.children:
            if c.type == "annotation_argument_list":
                args_node = c
                break
    if not args_node:
        return None
    for c in args_node.children:
        if c.type == "string_literal":
            raw_txt = _text(c, raw)
            return raw_txt.strip('"')
        if c.type == "element_value_pair":
            key_node = c.child_by_field_name("key") or (c.children[0] if c.children else None)
            val_node = c.child_by_field_name("value") or (c.children[-1] if c.children else None)
            if key_node and _text(key_node, raw) in ("value", "path"):
                if val_node and val_node.type == "string_literal":
                    return _text(val_node, raw).strip('"')
    return None


def _collect_annotations(modifiers_node: Optional[Node], raw: bytes) -> List[Tuple[str, Node]]:
    out: List[Tuple[str, Node]] = []
    if not modifiers_node:
        return out
    for c in modifiers_node.children:
        if c.type in ("marker_annotation", "annotation"):
            name = _annotation_name(c, raw)
            if name:
                out.append((name, c))
    return out


def _has_modifier(modifiers_node: Optional[Node], raw: bytes, keyword: str) -> bool:
    if not modifiers_node:
        return False
    return keyword in _text(modifiers_node, raw).split()


def _collect_imports(root: Node, raw: bytes) -> Dict[str, str]:
    """Return simple-name -> FQN for top-level imports."""
    imports: Dict[str, str] = {}
    for child in root.children:
        if child.type == "import_declaration":
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    fqn = _text(c, raw)
                    if fqn.endswith(".*"):
                        continue
                    short = fqn.rsplit(".", 1)[-1]
                    imports[short] = fqn
    return imports


def _base_type_name(type_text: str) -> str:
    """`List<String>` -> `List`; `com.foo.Bar` -> `Bar`."""
    t = type_text.split("<", 1)[0].strip()
    return t.rsplit(".", 1)[-1]


def _resolve_fqn(type_text: str, index: Dict[str, str], local_imports: Dict[str, str]) -> Optional[str]:
    bare = _base_type_name(type_text)
    if not bare:
        return None
    if bare in local_imports:
        return local_imports[bare]
    return index.get(bare)


def _extract_throws(method_node: Node, raw: bytes) -> List[str]:
    out: List[str] = []
    for c in method_node.children:
        if c.type == "throws":
            for sub in c.children:
                if sub.type in ("type_identifier", "scoped_type_identifier", "identifier", "scoped_identifier"):
                    out.append(_text(sub, raw))
    return out


def _walk(node: Node):
    yield node
    for c in node.children:
        yield from _walk(c)


def _extract_thrown_types(body_node: Node, raw: bytes) -> List[str]:
    """Collect class names from `throw new X(...)` statements."""
    out: List[str] = []
    if not body_node:
        return out
    for n in _walk(body_node):
        if n.type == "throw_statement":
            for child in n.children:
                if child.type == "object_creation_expression":
                    t = child.child_by_field_name("type")
                    if t:
                        out.append(_text(t, raw))
    return out


def _extract_call_sites(body_node: Node, raw: bytes, dep_names: set) -> List[CallSite]:
    """Find method_invocation nodes `obj.method(args)` where obj is a known dependency."""
    out: List[CallSite] = []
    if not body_node:
        return out
    seen: set = set()
    for n in _walk(body_node):
        if n.type != "method_invocation":
            continue
        obj_node = n.child_by_field_name("object")
        name_node = n.child_by_field_name("name")
        args_node = n.child_by_field_name("arguments")
        if not obj_node or not name_node:
            continue
        obj_text = _text(obj_node, raw)
        if obj_text.startswith("this."):
            obj_text = obj_text[5:]
        if obj_text not in dep_names:
            continue
        method_name = _text(name_node, raw)
        arg_count = 0
        if args_node:
            arg_count = sum(
                1 for c in args_node.children
                if c.type not in ("(", ")", ",")
            )
        returns_value = False
        parent = n.parent
        if parent and parent.type in (
            "assignment_expression",
            "variable_declarator",
            "return_statement",
            "argument_list",
            "binary_expression",
            "ternary_expression",
            "cast_expression",
            "field_access",
            "method_invocation",
            "array_access",
        ):
            returns_value = True
        key = (obj_text, method_name, arg_count)
        if key in seen:
            continue
        seen.add(key)
        out.append(CallSite(
            dep_name=obj_text,
            method=method_name,
            arg_count=arg_count,
            returns_value=returns_value,
        ))
    return out


def _parse_parameters(params_node: Optional[Node], raw: bytes) -> List[MethodArg]:
    out: List[MethodArg] = []
    if not params_node:
        return out
    for param in params_node.children:
        if param.type != "formal_parameter":
            continue
        type_node = param.child_by_field_name("type")
        name_node = param.child_by_field_name("name")
        modifiers_node = _find_child(param, "modifiers")
        annos = [n for (n, _) in _collect_annotations(modifiers_node, raw)]
        if type_node and name_node:
            out.append(MethodArg(
                name=_text(name_node, raw),
                type=_text(type_node, raw),
                annotations=annos,
            ))
    return out


def _extract_class_request_mapping(annos: List[Tuple[str, Node]], raw: bytes) -> Optional[str]:
    for name, node in annos:
        if name == "RequestMapping":
            return _annotation_string_argument(node, raw) or ""
    return None


def _extract_http_mapping(annos: List[Tuple[str, Node]], raw: bytes) -> Tuple[Optional[str], Optional[str]]:
    for name, node in annos:
        if name in HTTP_MAPPING_ANNOTATIONS:
            return HTTP_MAPPING_ANNOTATIONS[name], _annotation_string_argument(node, raw) or "/"
    return None, None


def _extract_field_dep(member: Node, raw: bytes) -> Optional[Dependency]:
    type_node = member.child_by_field_name("type")
    decl_node = member.child_by_field_name("declarator")
    if not type_node or not decl_node:
        return None
    name_node = decl_node.child_by_field_name("name")
    if not name_node:
        return None
    modifiers_node = _find_child(member, "modifiers")
    annos = [n for (n, _) in _collect_annotations(modifiers_node, raw)]
    is_final = _has_modifier(modifiers_node, raw, "final")
    is_static = _has_modifier(modifiers_node, raw, "static")
    is_private = _has_modifier(modifiers_node, raw, "private")
    if is_static:
        return None
    is_injected = any(a in ("Autowired", "Inject", "Resource") for a in annos)
    # A `private final` field with no annotation is a strong Lombok/ctor-DI signal.
    looks_like_di_target = is_injected or (is_private and is_final)
    if not looks_like_di_target:
        return None
    return Dependency(
        name=_text(name_node, raw),
        type=_text(type_node, raw),
        source="field" if is_injected else "lombok",
    )


def _extract_ctor_deps(class_body: Node, raw: bytes, existing_names: set) -> List[Dependency]:
    """Find the largest public/accessible constructor and collect its parameters as deps."""
    best: Optional[Node] = None
    best_params = -1
    for member in class_body.children:
        if member.type != "constructor_declaration":
            continue
        modifiers_node = _find_child(member, "modifiers")
        if _has_modifier(modifiers_node, raw, "private"):
            continue
        params_node = member.child_by_field_name("parameters")
        count = 0
        if params_node:
            count = sum(1 for c in params_node.children if c.type == "formal_parameter")
        if count > best_params:
            best_params = count
            best = member
    out: List[Dependency] = []
    if not best or best_params <= 0:
        return out
    params_node = best.child_by_field_name("parameters")
    for param in params_node.children:
        if param.type != "formal_parameter":
            continue
        type_node = param.child_by_field_name("type")
        name_node = param.child_by_field_name("name")
        if not type_node or not name_node:
            continue
        dep_name = _text(name_node, raw)
        if dep_name in existing_names:
            continue
        out.append(Dependency(
            name=dep_name,
            type=_text(type_node, raw),
            source="constructor",
        ))
    return out


def parse_java_file(file_path: str, project_root: str) -> SpringComponent:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    raw = bytes(content, "utf-8")
    parser = get_parser()
    tree = parser.parse(raw)
    index = load_index(project_root)
    root = tree.root_node

    package_name = ""
    for child in root.children:
        if child.type == "package_declaration":
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    package_name = _text(c, raw)
                    break

    local_imports = _collect_imports(root, raw)

    # Find the primary class / record declaration.
    class_node: Optional[Node] = None
    is_record = False
    for child in root.children:
        if child.type == "class_declaration":
            class_node = child
            break
        if child.type == "record_declaration":
            class_node = child
            is_record = True
            break

    component = SpringComponent(
        name="",
        package=package_name,
        stereotype="",
        is_record=is_record,
        local_imports=local_imports,
    )
    if not class_node:
        return component

    name_node = class_node.child_by_field_name("name")
    if name_node:
        component.name = _text(name_node, raw)

    modifiers_node = _find_child(class_node, "modifiers")
    class_annos = _collect_annotations(modifiers_node, raw)
    for ann_name, _ in class_annos:
        if ann_name in SPRING_STEREOTYPES and not component.stereotype:
            component.stereotype = ann_name
        if ann_name in LOMBOK_ANNOTATIONS:
            component.lombok_annotations.append(ann_name)

    if is_record:
        component.stereotype = "Record"
    elif not component.stereotype:
        component.stereotype = "Plain"

    component.class_level_request_mapping = _extract_class_request_mapping(class_annos, raw)

    # superclass + interfaces
    super_node = class_node.child_by_field_name("superclass")
    if super_node:
        for c in super_node.children:
            if c.type in ("type_identifier", "scoped_type_identifier"):
                component.super_class = _text(c, raw)
    ifaces_node = class_node.child_by_field_name("interfaces")
    if ifaces_node:
        for n in _walk(ifaces_node):
            if n.type in ("type_identifier", "scoped_type_identifier"):
                component.interfaces.append(_text(n, raw))

    # Record components feed into the record flow.
    if is_record:
        params_node = class_node.child_by_field_name("parameters")
        if params_node:
            for p in params_node.children:
                if p.type == "formal_parameter":
                    t = p.child_by_field_name("type")
                    n = p.child_by_field_name("name")
                    if t and n:
                        component.record_components.append(MethodArg(
                            name=_text(n, raw),
                            type=_text(t, raw),
                        ))

    body_node = class_node.child_by_field_name("body")
    if body_node is None:
        return component

    # Pass 1: field-based dependencies
    for member in body_node.children:
        if member.type == "field_declaration":
            dep = _extract_field_dep(member, raw)
            if dep:
                dep.fqn = _resolve_fqn(dep.type, index, local_imports)
                component.dependencies.append(dep)

    existing_names = {d.name for d in component.dependencies}

    # Pass 2: constructor dependencies if needed
    has_lombok_required_ctor = any(
        a in component.lombok_annotations for a in ("RequiredArgsConstructor", "AllArgsConstructor")
    )
    needs_ctor_scan = not has_lombok_required_ctor or not component.dependencies
    if needs_ctor_scan:
        ctor_deps = _extract_ctor_deps(body_node, raw, existing_names)
        for dep in ctor_deps:
            dep.fqn = _resolve_fqn(dep.type, index, local_imports)
            component.dependencies.append(dep)

    dep_names = {d.name for d in component.dependencies}

    # Pass 3: methods
    for member in body_node.children:
        if member.type != "method_declaration":
            continue
        method_info = _maybe_parse_method(member, raw, dep_names)
        if method_info is not None:
            component.methods.append(method_info)

    return component


def _maybe_parse_method(member: Node, raw: bytes, dep_names: set) -> Optional[MethodInfo]:
    modifiers_node = _find_child(member, "modifiers")
    annos = _collect_annotations(modifiers_node, raw)
    is_abstract = _has_modifier(modifiers_node, raw, "abstract")
    is_private = _has_modifier(modifiers_node, raw, "private")
    is_protected = _has_modifier(modifiers_node, raw, "protected")
    is_public = not is_private and not is_protected

    if not is_public or is_abstract:
        return None

    name_node = member.child_by_field_name("name")
    type_node = member.child_by_field_name("type")
    params_node = member.child_by_field_name("parameters")
    body_node = member.child_by_field_name("body")

    m_name = _text(name_node, raw) if name_node else ""
    if not m_name:
        return None
    if m_name in ("main",):
        return None
    if m_name in OBJECT_METHOD_DENYLIST:
        return None
    if not body_node:
        return None
    # Empty-body: block { } has at least 2 children (braces).
    if len(body_node.children) <= 2:
        return None

    m_args = _parse_parameters(params_node, raw)
    m_type = _text(type_node, raw) if type_node else "void"

    http_mapping, http_path = _extract_http_mapping(annos, raw)

    # Trivial getter/setter/isser heuristic -- skip only when the method looks POJO-shaped:
    # no args, no HTTP mapping, and a tiny body. Otherwise a `@GetMapping("/x") getUser(id)` or
    # a stateful `getOrCompute(key)` would be missed.
    if http_mapping is None and not m_args:
        if (m_name.startswith("get") or m_name.startswith("set") or m_name.startswith("is")) \
                and len(body_node.children) <= 3:
            return None

    return MethodInfo(
        name=m_name,
        return_type=m_type,
        args=m_args,
        throws_declared=_extract_throws(member, raw),
        throws_thrown=_extract_thrown_types(body_node, raw),
        body_calls=_extract_call_sites(body_node, raw, dep_names),
        http_mapping=http_mapping,
        http_path=http_path,
    )
