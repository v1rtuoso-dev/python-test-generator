"""Rule-based filler: turns the rich SpringComponent model into concrete Java
fragments (arg init, stubs, verifies, assertions, extra tests) that the Jinja
templates can drop straight into the scaffold.

This is a port of the core ideas from:
- testme-idea `MockitoMockBuilder.shouldStub/shouldVerify`
- Squaretest's dataflow-based stub/verify generation
- spring-test-generator's `AssertionGenerator` / `ExceptionTestGenerator`
- junit-test-generator's throws loop

The goal is that the scaffold already compiles and is meaningful BEFORE the
optional Gemini polish pass -- so AI-off still yields a usable test.
"""

from typing import List, Dict, Optional
from models import SpringComponent, MethodInfo, MethodArg, Dependency, CallSite
from typecatalog import default_for, matcher_for, _base_name


VALIDATION_ANNOTATIONS = {
    "NotNull", "NotBlank", "NotEmpty", "Valid", "Size", "Min", "Max",
    "Positive", "PositiveOrZero", "Negative", "NegativeOrZero", "Pattern",
    "Email", "Past", "Future",
}


def _indent(block: str, spaces: int = 8) -> str:
    if not block:
        return ""
    pad = " " * spaces
    return "\n".join(pad + ln if ln else ln for ln in block.splitlines())


def _find_dep(component: SpringComponent, dep_name: str) -> Optional[Dependency]:
    for d in component.dependencies:
        if d.name == dep_name:
            return d
    return None


def _render_args_init(method: MethodInfo) -> str:
    lines: List[str] = []
    for arg in method.args:
        literal = default_for(arg.type)
        arg.default = literal  # persist so the template can use arg.default if needed
        lines.append(f"{arg.type} {arg.name} = {literal};")
    return "\n".join(lines)


def _render_stubs(method: MethodInfo, component: SpringComponent) -> str:
    """Emit `when(dep.m(matchers...)).thenReturn(default);` per returning call site."""
    lines: List[str] = []
    seen: set = set()
    for call in method.body_calls:
        if not call.returns_value:
            continue
        key = (call.dep_name, call.method, call.arg_count)
        if key in seen:
            continue
        seen.add(key)
        dep = _find_dep(component, call.dep_name)
        matchers = ", ".join(["any()"] * call.arg_count)
        # Heuristic default for thenReturn: we don't know the exact return type
        # from source-level analysis, so a safe null plus a TODO pointer helps
        # the AI pass refine without breaking the scaffold for primitives.
        stub_value = "null"
        lines.append(
            f"org.mockito.Mockito.when({call.dep_name}.{call.method}({matchers})).thenReturn({stub_value});"
        )
    return "\n".join(lines)


def _render_verifies(method: MethodInfo, component: SpringComponent) -> str:
    lines: List[str] = []
    seen: set = set()
    for call in method.body_calls:
        if call.returns_value:
            continue
        key = (call.dep_name, call.method, call.arg_count)
        if key in seen:
            continue
        seen.add(key)
        matchers = ", ".join(["any()"] * call.arg_count)
        lines.append(f"org.mockito.Mockito.verify({call.dep_name}).{call.method}({matchers});")
    return "\n".join(lines)


def _render_assertion(method: MethodInfo) -> str:
    rtype = (method.return_type or "").strip()
    if rtype in ("", "void"):
        return ""
    bare = _base_name(rtype)
    if bare in ("boolean", "Boolean"):
        return "org.junit.jupiter.api.Assertions.assertNotNull(result);"
    if bare == "Optional":
        return "org.assertj.core.api.Assertions.assertThat(result).isNotNull();"
    if bare in ("List", "Set", "Collection", "Iterable", "Map", "Stream"):
        return "org.assertj.core.api.Assertions.assertThat(result).isNotNull();"
    return "org.assertj.core.api.Assertions.assertThat(result).isNotNull();"


def _invocation_args(method: MethodInfo) -> str:
    return ", ".join(arg.name for arg in method.args)


def _result_decl(method: MethodInfo, call_expr: str) -> str:
    rtype = (method.return_type or "").strip()
    if rtype in ("", "void"):
        return f"{call_expr};"
    return f"{rtype} result = {call_expr};"


def _first_mockable_dep(component: SpringComponent) -> Optional[Dependency]:
    for d in component.dependencies:
        return d
    return None


def _render_exception_tests(method: MethodInfo, component: SpringComponent, sut_name: str) -> List[str]:
    """For each declared checked exception, emit a negative-path test using doThrow on a dep."""
    out: List[str] = []
    throws = list(dict.fromkeys(method.throws_declared))
    if not throws:
        return out
    dep = _first_mockable_dep(component)
    if not dep or not method.body_calls:
        return out
    # Pick the first call site on that dep as the throw target.
    target_call: Optional[CallSite] = None
    for call in method.body_calls:
        if call.dep_name == dep.name:
            target_call = call
            break
    if target_call is None:
        return out
    matchers = ", ".join(["any()"] * target_call.arg_count)
    call_expr = f"{sut_name}.{method.name}({_invocation_args(method)})"
    for ex in throws:
        bare = _base_name(ex)
        # Arg initializers repeat so the test is independent.
        args_init = _render_args_init(method)
        test = (
            f"@org.junit.jupiter.api.Test\n"
            f"void {method.name}_throws{bare}() {{\n"
            f"    // Arrange\n"
            f"{_indent(args_init, 4)}\n"
            f"    org.mockito.Mockito.doThrow(new {bare}(\"boom\"))\n"
            f"        .when({target_call.dep_name}).{target_call.method}({matchers});\n"
            f"    // Act & Assert\n"
            f"    org.junit.jupiter.api.Assertions.assertThrows({bare}.class, () -> {call_expr});\n"
            f"}}"
        )
        out.append(test)
    return out


def _render_validation_tests(method: MethodInfo, sut_name: str) -> List[str]:
    out: List[str] = []
    null_targets: List[MethodArg] = []
    for arg in method.args:
        if any(a in VALIDATION_ANNOTATIONS for a in arg.annotations):
            null_targets.append(arg)
    if not null_targets:
        return out
    for arg in null_targets:
        other_args: List[str] = []
        for a in method.args:
            if a.name == arg.name:
                other_args.append("null")
            else:
                other_args.append(default_for(a.type))
        call_expr = f"{sut_name}.{method.name}({', '.join(other_args)})"
        test = (
            f"@org.junit.jupiter.api.Test\n"
            f"void {method.name}_rejectsNull_{arg.name}() {{\n"
            f"    org.junit.jupiter.api.Assertions.assertThrows(\n"
            f"        RuntimeException.class,\n"
            f"        () -> {call_expr}\n"
            f"    );\n"
            f"}}"
        )
        out.append(test)
    return out


def fill_component(component: SpringComponent, sut_var: str) -> None:
    """Populate the per-method rendered blocks in-place on the component."""
    for method in component.methods:
        method.args_init_block = _render_args_init(method)
        method.stubs_block = _render_stubs(method, component)
        method.verify_block = _render_verifies(method, component)
        method.assert_line = _render_assertion(method)
        extras = _render_exception_tests(method, component, sut_var)
        extras += _render_validation_tests(method, sut_var)
        method.extra_tests = extras


def sut_var_name(component: SpringComponent) -> str:
    name = component.name
    if not name:
        return "sut"
    return name[0].lower() + name[1:]
