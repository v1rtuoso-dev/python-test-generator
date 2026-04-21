from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class Dependency(BaseModel):
    name: str
    type: str
    fqn: Optional[str] = None
    source: str = "field"  # field | constructor | lombok

class MethodArg(BaseModel):
    name: str
    type: str
    annotations: List[str] = Field(default_factory=list)
    default: str = "null"  # Pre-rendered default literal, filled in Phase 2

class CallSite(BaseModel):
    """A call in the form `<dep>.<method>(...)` that we detected inside a method body."""
    dep_name: str
    method: str
    arg_count: int = 0
    # Whether we believe this call is a returning call (best-effort heuristic based on usage context).
    returns_value: bool = False

class MethodInfo(BaseModel):
    name: str
    return_type: str
    args: List[MethodArg] = Field(default_factory=list)
    throws_declared: List[str] = Field(default_factory=list)
    throws_thrown: List[str] = Field(default_factory=list)
    body_calls: List[CallSite] = Field(default_factory=list)
    # HTTP metadata for controller methods
    http_mapping: Optional[str] = None  # e.g. GET, POST
    http_path: Optional[str] = None      # e.g. /users/{id}
    # Rendered blocks (populated by the filler in Phase 2)
    args_init_block: str = ""
    stubs_block: str = ""
    verify_block: str = ""
    assert_line: str = ""
    extra_tests: List[str] = Field(default_factory=list)

class SpringComponent(BaseModel):
    name: str
    package: str
    stereotype: str = ""
    dependencies: List[Dependency] = Field(default_factory=list)
    methods: List[MethodInfo] = Field(default_factory=list)
    super_class: Optional[str] = None
    interfaces: List[str] = Field(default_factory=list)
    is_record: bool = False
    record_components: List[MethodArg] = Field(default_factory=list)
    lombok_annotations: List[str] = Field(default_factory=list)
    class_level_request_mapping: Optional[str] = None
    # Full resolved imports available in the source (simple name -> FQN). Helps fallback resolution.
    local_imports: Dict[str, str] = Field(default_factory=dict)
