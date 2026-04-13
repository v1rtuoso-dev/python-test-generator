import os
from jinja2 import Environment, FileSystemLoader
from models import SpringComponent
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from rich import print

def get_template_env():
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    return Environment(loader=FileSystemLoader(templates_dir))

def generate_static_test(component: SpringComponent) -> str:
    env = get_template_env()
    # Choose template based on stereotype
    template_name = "service.jinja" # Fallback/Default for Service, Component, RestClient
    if component.stereotype in ("RestController", "Controller"):
        template_name = "controller.jinja"
    elif component.stereotype == "Repository":
        template_name = "repository.jinja"
    elif component.stereotype == "Plain":
        template_name = "plain.jinja"
        
    template = env.get_template(template_name)
    
    # Collect imports mapping FQNs
    imports = set()
    for dep in component.dependencies:
        if dep.fqn:
            imports.add(dep.fqn)
            
    return template.render(component=component, imports=sorted(list(imports)))

def fill_ai_logic(static_code: str, original_source: str) -> str:
    """Uses LLM to replace the basic // TODO logic with actual Mockito tests."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[yellow]GOOGLE_API_KEY not found in environment. Skipping AI test generation phase. Outputting static stubs.[/yellow]")
        return static_code
        
    try:
        # Initialize Gemini with a modern model via env var or default to gemini-3.1-pro
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro")
        llm = ChatGoogleGenerativeAI(model=model_name)
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert Spring Boot developer. You are provided with the original Java source class, and a scaffolded JUnit 5 Test class."),
            ("user", "Fill in the mocked responses (`when(mock.method()).thenReturn(...)`) and the assertions in the provided test scaffold. "
                     "Return ONLY the complete Java test code. No explanations. No markdown formatting around the output, ONLY pure java text.\n\n"
                     "Original Class:\n{source}\n\nScaffold Test:\n{scaffold}")
        ])
        
        chain = prompt | llm
        print("[bold cyan]Submitting to Gemini for test synthesis...[/bold cyan]")
        result = chain.invoke({"source": original_source, "scaffold": static_code})
        
        code = result.content
        if isinstance(code, list):
            try:
                code = "".join([part.get("text", "") for part in code if isinstance(part, dict)])
            except Exception:
                code = str(code)
                
        code = code.strip()
        if code.startswith("```java"):
            code = code[7:]
            if code.endswith("```"):
                code = code[:-3]
        elif code.startswith("```"):
            code = code[3:]
            if code.endswith("```"):
                code = code[:-3]
            
        return code.strip()
    except Exception as e:
        print(f"[red]Failed during AI generation: {e}[/red]")
        return static_code
