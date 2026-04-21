import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict
from jinja2 import Environment, FileSystemLoader
from rich import print

from models import SpringComponent, MethodInfo
from filler import fill_component, sut_var_name
from typecatalog import default_for


def get_template_env() -> Environment:
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    return Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _pick_template(component: SpringComponent) -> str:
    if component.stereotype in ("RestController", "Controller"):
        return "controller.jinja"
    if component.stereotype == "Repository":
        return "repository.jinja"
    if component.stereotype in ("Plain", "Record"):
        return "plain.jinja"
    return "service.jinja"


def _full_path_for_method(method: MethodInfo, class_mapping: Optional[str]) -> str:
    base = (class_mapping or "").rstrip("/") if class_mapping else ""
    route = method.http_path or ""
    if route and not route.startswith("/"):
        route = "/" + route
    result = f"{base}{route}" or "/"
    return result


def _ctor_fallback_block(component: SpringComponent, sut_var: str) -> str:
    """If the component has a constructor that mocked fields cannot satisfy via @InjectMocks
    (e.g. final fields without matching @Mock types), emit an explicit `new` call in setUp.

    This is conservative: we only emit when every dep has `source=constructor` AND there is at
    least one dep. @InjectMocks already handles `source=field` + `source=lombok` cases.
    """
    if not component.dependencies:
        return ""
    if not all(d.source == "constructor" for d in component.dependencies):
        return ""
    args = ", ".join(d.name for d in component.dependencies)
    return f"{sut_var} = new {component.name}({args});"


def generate_static_test(component: SpringComponent, config: Optional[Dict] = None) -> str:
    """Render the scaffold with all blocks pre-filled by the rule-based filler."""
    cfg = config or {}
    env = get_template_env()
    sut_var = sut_var_name(component)
    fill_component(component, sut_var)

    template = env.get_template(_pick_template(component))

    imports = set()
    for dep in component.dependencies:
        if dep.fqn:
            imports.add(dep.fqn)

    ctor_block = ""
    if component.stereotype not in ("Record", "Plain"):
        ctor_block = _ctor_fallback_block(component, sut_var)

    return template.render(
        component=component,
        imports=sorted(imports),
        sut_var=sut_var,
        use_assertj=cfg.get("use_assertj", True),
        use_testcontainers=cfg.get("use_testcontainers", False),
        ctor_fallback_block=ctor_block,
        full_path=lambda m: _full_path_for_method(m, component.class_level_request_mapping),
    )


# ---------- AI layer ----------

SYSTEM_PROMPT = (
    "You are an expert Spring Boot / JUnit 5 / Mockito / AssertJ developer. "
    "You will receive a fully structured Java test scaffold that already compiles. "
    "Your ONLY job is to replace placeholder literals with realistic values and strengthen assertions. "
    "STRICT RULES: "
    "1. Do NOT add, remove or rename imports, fields, @Mock/@MockBean declarations, @Test methods, or classes. "
    "2. Preserve every existing when(...)/verify(...)/doThrow(...) call exactly; you may adjust the matcher args "
    "and thenReturn value but the call shape must remain. "
    "3. Preserve assertion style (AssertJ `assertThat` / JUnit `assertNotNull` etc.) and only refine the expected value. "
    "4. Replace trivial defaults (like `\"test\"`, `0`, `null`) with plausible values based on the dependency class summaries. "
    "5. Return ONLY the raw Java source, no markdown fences, no commentary."
)


def _dep_summaries(component: SpringComponent, project_root: Path) -> str:
    """Load each dependency's source file and extract a minimal signature summary.

    This gives the LLM enough context to emit sensible `thenReturn(...)` values and
    argument choices without re-deriving them.
    """
    from indexer import get_parser
    summaries: List[str] = []
    if not component.dependencies:
        return ""
    src_dir = project_root / "src" / "main" / "java"
    for dep in component.dependencies:
        if not dep.fqn:
            continue
        rel_path = dep.fqn.replace(".", "/") + ".java"
        dep_file = src_dir / rel_path
        if not dep_file.exists():
            continue
        try:
            source = dep_file.read_text(encoding="utf-8")
        except Exception:
            continue
        signatures = _extract_public_signatures(source)
        if signatures:
            summaries.append(f"// {dep.type} ({dep.fqn})\n" + "\n".join(signatures))
    if not summaries:
        return ""
    return "\n\n".join(summaries)


_SIG_RE = re.compile(
    r"(public\s+[^{;=]+?\([^)]*\))\s*(?:throws\s+[^{;]+)?\s*[{;]",
    re.MULTILINE,
)


def _extract_public_signatures(source: str) -> List[str]:
    out: List[str] = []
    for m in _SIG_RE.finditer(source):
        sig = " ".join(m.group(1).split()).strip()
        if sig and "class " not in sig and "interface " not in sig:
            out.append(sig + ";")
    return out[:25]


def _split_scaffold(scaffold: str) -> Dict[str, List[str]]:
    """Split the scaffold into (prelude, test_blocks, epilogue) for per-method polishing.

    Returns a dict with keys `prelude`, `tests` (list of strings), `epilogue`.
    A "test block" is: `@Test ... void name(...) { ... }` up through its matching closing brace.
    """
    lines = scaffold.splitlines()
    prelude_end = 0
    # Find the index of the first line that starts a @Test annotation.
    for i, ln in enumerate(lines):
        if ln.strip().startswith("@Test") or ln.strip().startswith("@org.junit.jupiter.api.Test"):
            prelude_end = i
            break
    if prelude_end == 0:
        return {"prelude": scaffold, "tests": [], "epilogue": ""}

    prelude = "\n".join(lines[:prelude_end])
    rest = "\n".join(lines[prelude_end:])

    # Peel off the final closing brace of the class.
    last_close = rest.rfind("}")
    body = rest[:last_close].rstrip()
    epilogue = rest[last_close:]

    # Split by lines that begin with @Test; each block runs up to (but excluding) the next such line.
    blocks: List[str] = []
    current: List[str] = []
    for ln in body.splitlines():
        stripped = ln.strip()
        if stripped.startswith("@Test") or stripped.startswith("@org.junit.jupiter.api.Test"):
            if current:
                blocks.append("\n".join(current).rstrip())
                current = []
        current.append(ln)
    if current:
        blocks.append("\n".join(current).rstrip())

    return {"prelude": prelude, "tests": blocks, "epilogue": epilogue}


def _polish_block(llm, system_prompt: str, dep_context: str, original_class: str, test_block: str) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    user = (
        f"Dependency summaries (public signatures):\n{dep_context or '(none available)'}\n\n"
        f"Class under test (source):\n{original_class}\n\n"
        f"Polish ONLY the following @Test block. Return ONLY the refined Java code for this single method.\n\n"
        f"{test_block}"
    )
    try:
        result = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user)])
        content = result.content
        if isinstance(content, list):
            try:
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            except Exception:
                content = str(content)
        content = (content or "").strip()
        if content.startswith("```java"):
            content = content[len("```java"):]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip() or test_block
    except Exception as e:
        print(f"[yellow]Polish failed for one block: {e}[/yellow]")
        return test_block


def fill_ai_logic(static_code: str, original_source: str, component: Optional[SpringComponent] = None,
                  project_root: Optional[Path] = None) -> str:
    """Optional AI polish over the rule-based scaffold.

    Always returns a usable Java file: if the API key is missing or any step fails,
    the original scaffold flows through untouched.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[yellow]GOOGLE_API_KEY not set. Skipping AI polish; outputting rule-based scaffold.[/yellow]")
        return static_code

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception as e:
        print(f"[yellow]langchain-google-genai unavailable ({e}); using scaffold only.[/yellow]")
        return static_code

    model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    try:
        llm = ChatGoogleGenerativeAI(model=model_name)
    except Exception as e:
        print(f"[yellow]Could not initialize Gemini ({e}); using scaffold only.[/yellow]")
        return static_code

    dep_context = ""
    if component and project_root:
        dep_context = _dep_summaries(component, project_root)

    parts = _split_scaffold(static_code)
    test_blocks = parts["tests"]
    if not test_blocks:
        print("[yellow]No @Test blocks detected to polish; returning scaffold.[/yellow]")
        return static_code

    print(f"[bold cyan]Polishing {len(test_blocks)} test methods via Gemini in parallel...[/bold cyan]")
    polished_blocks: List[str] = [""] * len(test_blocks)
    with ThreadPoolExecutor(max_workers=min(4, len(test_blocks))) as pool:
        futures = {
            pool.submit(_polish_block, llm, SYSTEM_PROMPT, dep_context, original_source, blk): idx
            for idx, blk in enumerate(test_blocks)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            polished_blocks[idx] = fut.result()

    return parts["prelude"] + "\n\n" + "\n\n".join(polished_blocks) + "\n" + parts["epilogue"]
