from pydantic import BaseModel, Field
from typing import List, Optional

class Dependency(BaseModel):
    name: str
    type: str
    fqn: Optional[str] = None 

class MethodArg(BaseModel):
    name: str
    type: str

class MethodInfo(BaseModel):
    name: str
    return_type: str
    args: List[MethodArg] = Field(default_factory=list)

class SpringComponent(BaseModel):
    name: str 
    package: str 
    stereotype: str = "" 
    dependencies: List[Dependency] = Field(default_factory=list)
    methods: List[MethodInfo] = Field(default_factory=list)
