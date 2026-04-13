# Spring Boot Unit Test Generator

An intelligent, Python-based CLI tool designed to automatically scaffold and generate production-ready JUnit 5, Mockito, and Spring Context tests for your Java applications.

Instead of writing repetitive, boilerplate mock setups, this tool automatically parses your raw Java code, figures out the architectural layer using Spring stereotypes, correctly maps package imports, and scaffolds the precise testing strategy required for the job. You can also hook up Google Gemini to have the AI write the actual assertions!

## Features

- **Layer-Aware Scaffolding**: 
  - `@Service`, `@Component`, `@RestClient` -> Outputs pure Unit Tests using Mockito (`@ExtendWith(MockitoExtension.class)`)
  - `@RestController`, `@Controller` -> Outputs Web Layer HTTP tests (`@WebMvcTest` + `MockMvc`)
  - `@Repository` -> Outputs Database layer slices (`@DataJpaTest`)
  - Plain Domain/Utility classes -> Outputs pure JUnit 5 instance tests.
- **Verification Heuristics**: Not all code needs to be tested. The generator explicitly filters out non-testable methods to prevent bloat. It ignores `private` methods, abstract classes, empty block functions, standard `main` execution blocks, and actively ignores trivial Getter/Setter accessors.
- **AI Synthesis**: If API keys are provided via the `.env` file, the tool sends both the original method AST and the structurally-perfect generated boilerplate to Gemini to auto-fill the logic, returns, and assertions cleanly.
- **Bulk Directory Generation**: A single command points to an existing Spring Boot application and will process every single file automatically.

---

## Setup

### 1. Environment Readiness (Python 3.10+)

We heavily advise running this within a local virtual environment due to the compiled dependency bindings on the `tree-sitter-java` library.

```bash
# Initialize a local virtual environment
python -m venv venv

# Activate it (Windows)
.\venv\Scripts\activate

# Install all primary dependencies 
pip install -r requirements.txt
```

### 2. Configuration (`.env`)

To leverage the AI capabilities, simply duplicate the provided `.env.example` file and rename it to `.env`:

```env
GOOGLE_API_KEY="your_actual_google_gemini_api_key"
GEMINI_MODEL="gemini-3.1-pro" # Ensure you use an active model tag available in Google GenAI
```

---

## 💻 Usage

The CLI is powered by Typer and comes with two highly flexible primary commands:

### Bulk Auto-Generation

Use `generate-all` to scan an entire active Spring Boot project. It searches `src/main/java` within the target project root, isolates classes that map to the acceptable rules, and writes a fully synchronized test suite identically into its `src/test/java` package layer.

```bash
python main.py generate-all "C:\path\to\your\spring-boot-project"
```

### Single File Generation

Use `generate` to focus entirely on scaffolding tests for a single new component you just wrote.

```bash
python main.py generate "C:\path\to\your\spring-boot-project\src\main\java\com\example\service\MyService.java"
```

*Note: The generator intelligently maps backwards from your provided path so the generated test is safely anchored directly inside the `src/test/java/` tree of the original Spring Boot application (instead of landing in this utility directory).*

---

## 🛠 Under the Hood

1. **Tree-Sitter Parsing**: Relies on native python `tree-sitter` for blazing fast AST traversal without requiring JVM startup. 
2. **Indexer Mapping**: A dynamic hash table index runs implicitly before Generation, linking local project variables to fully qualified import packages to guarantee generated tests compile.
3. **Jinja2 Synthesis**: Scaffolding operates entirely on deterministic Jinja Templates to prevent typical "AI Hallucination" on mocking imports. The AI is restricted only to solving the logic puzzles embedded within the `// Arrange` and `// Assert` block strings.
