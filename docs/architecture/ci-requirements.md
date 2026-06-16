# CI Requirements

This document tracks CI requirements for FactoryVerse. We don't have CI yet, but we're building the validation infrastructure that will run in it.

## Validation Tiers

CI should run validations in order of speed (fail fast):

| Tier | Name | Runtime | Requires Factorio | Purpose |
|------|------|---------|-------------------|---------|
| 1 | **Static** | ~1s | No | Syntax, types, attribute validation |
| 2 | **Unit** | ~10s | No | Python unit tests |
| 3 | **Integration** | ~60s | Yes (Docker) | Runtime tests against Factorio |

---

## Tier 1: Static Validation

Fast checks that catch most doc/code drift without any runtime.

### 1.1 Documentation Type Checking

```bash
pytest tests/unit/test_documentation_coverage.py -v
```

**What it validates:**
- All example code has valid Python syntax
- All attribute accesses reference real attributes on known types
- Polymorphic return types are correctly handled
- Coverage of public methods

**Key test:** `test_all_examples_valid_attributes`
- Traces variable types through AST
- Validates against 16 introspected classes
- Catches bugs like `patch.total_amount` → should be `patch.total`

### 1.2 Type Mappings Completeness

The type system in `validators.py` must be exhaustive:

```python
# If you add a new accessor, add its return type:
ACCESSOR_RETURN_TYPES["new_view.new_method"] = "ReturnType"

# If you add a new class agents interact with:
_class_map["NewClass"] = NewClass
```

**Future:** Add a test that verifies all public methods on action classes have type mappings.

### 1.3 Linting (TODO)

```bash
ruff check src/
ruff format --check src/
```

### 1.4 Type Checking (TODO)

```bash
pyright src/FactoryVerse/
# or
mypy src/FactoryVerse/
```

---

## Tier 2: Unit Tests

Python tests that don't require Factorio.

```bash
pytest tests/unit/ -v
```

**Current tests:**
- `test_documentation_coverage.py` - Doc validation infrastructure
- `test_environment_tiers.py` - Environment tier logic
- `test_task_verification.py` - Task verification logic

---

## Tier 3: Integration Tests

Tests that require a running Factorio instance.

```bash
# Start Factorio server
uv run fv server start --num 1 --scenario test-ground

# Run integration tests
pytest tests/actions/ tests/functional/ -v
```

**Test categories:**
- `tests/actions/` - Individual action tests (walking, crafting, placement)
- `tests/functional/` - Multi-step workflows

**Docker requirement:** Integration tests need Factorio running. CI should:
1. Start Factorio Docker container
2. Wait for RCON to be responsive
3. Run tests
4. Tear down container

---

## CI Workflow (GitHub Actions Draft)

```yaml
name: CI

on: [push, pull_request]

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest tests/unit/test_documentation_coverage.py -v
      # TODO: Add ruff, pyright

  unit:
    runs-on: ubuntu-latest
    needs: static
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest tests/unit/ -v

  integration:
    runs-on: ubuntu-latest
    needs: unit
    services:
      factorio:
        image: factoriotools/factorio:stable
        # TODO: Configure with FactoryVerse mods
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --group dev
      - run: uv run pytest tests/actions/ tests/functional/ -v
```

---

## Validation Infrastructure Location

| Component | Location | Purpose |
|-----------|----------|---------|
| `StaticAttributeValidator` | `src/FactoryVerse/docs/validators.py` | Type-checks example code |
| `ExampleValidator` | `src/FactoryVerse/docs/validators.py` | Syntax validation |
| `CoverageValidator` | `src/FactoryVerse/docs/validators.py` | Doc coverage |
| Type mappings | `validators.py:ACCESSOR_RETURN_TYPES` | Exhaustive accessor→type map |
| Polymorphic types | `validators.py:POLYMORPHIC_RETURN_TYPES` | Context-dependent returns |
| Class introspection | `validators.py:_class_map` | Runtime type info |

---

## Adding New Validations

When you add new functionality:

1. **New accessor/method?** Add to `ACCESSOR_RETURN_TYPES`
2. **New class agents use?** Add to `_class_map` in `_build_class_map()`
3. **Polymorphic return?** Add to `POLYMORPHIC_RETURN_TYPES`
4. **New action class?** Register in `docs/reference/` modules

The type system is the research artifact. Gaps in validation = bugs.

---

## Open Questions

- [ ] How to run Factorio in CI? (Docker image with mods pre-installed?)
- [ ] Should we cache the Factorio Docker image?
- [ ] Integration test parallelization (multiple Factorio instances?)
- [ ] Test data management (scenarios, save files)
