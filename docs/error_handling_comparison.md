# Error Handling: Old vs New Comparison

## Old Implementation (`rcon_helper.py`)

### Structure
```python
# Lua-side error wrapping
xpcall = f"local success, result = xpcall(function() return {remote_call} end, debug.traceback)"
handler = "if success then ... else rcon.print(helpers.table_to_json({success = false, error = result})) end"

# Python-side error parsing
if result.get('success') == False:
    raise Exception(f"Remote call failed: {result.get('error')}")
```

### Characteristics
✅ **Strengths**:
- Structured error contract (`{success, result/error}`)
- Full Lua traceback via `debug.traceback`
- Clean exception raising

❌ **Limitations**:
- Fixed error format (no verbosity control)
- All-or-nothing traceback (full or none)
- No filtering of internal frames
- Not integrated with Jupyter runtime

---

## New Implementation (`FactorioErrorParser`)

### Structure
```python
# Error parser with tunable verbosity
parser = FactorioErrorParser(
    verbosity=ErrorVerbosity.MODERATE,  # MINIMAL, MODERATE, or FULL
    max_traceback_frames=2,
    show_internal_frames=False
)

# Parse and format errors
formatted_error = parser.parse_and_format(raw_error)
```

### Characteristics
✅ **Improvements**:
- **Tunable verbosity**: 3 levels (MINIMAL, MODERATE, FULL)
- **Smart filtering**: Removes internal Factorio frames
- **Configurable frame limits**: Control traceback length
- **Error classification**: Detects Lua vs Python errors
- **LLM-optimized**: Formats for token efficiency
- **Integrated**: Works with Jupyter kernel errors

✅ **Preserved from old**:
- Full traceback available (when needed)
- Clean error messages
- Exception raising pattern

---

## Side-by-Side Comparison

### Error Output Examples

#### Old Implementation
```
Exception: Remote call failed: __FactoryVerse__/control.lua:123: attempt to index a nil value
stack traceback:
    __FactoryVerse__/control.lua:123: in function 'walk_to'
    __FactoryVerse__/agent_interface.lua:45: in function 'execute_action'
    __core__/lualib/event_handler.lua:104: in function <__core__/lualib/event_handler.lua:102>
    __base__/control.lua:67: in function <__base__/control.lua:65>
    [C]: in function 'pcall'
    __FactoryVerse__/control.lua:234: in function <__FactoryVerse__/control.lua:230>
```
**Issues**: 
- Includes internal frames (`__core__`, `__base__`)
- No control over verbosity
- Fixed format

---

#### New Implementation (MODERATE)
```
❌ LuaError: __FactoryVerse__/control.lua:123: attempt to index a nil value

Traceback (last 2 of 4 frames):
  ... [2 frames omitted]
  1. [C]: in function 'pcall'
  2. __FactoryVerse__/control.lua:234: in function <__FactoryVerse__/control.lua:230>
```
**Improvements**:
- Filtered internal frames
- Limited to 2 most relevant frames
- Clear omission indicator
- Numbered frames

---

#### New Implementation (MINIMAL)
```
❌ LuaError: __FactoryVerse__/control.lua:123: attempt to index a nil value
```
**Use case**: Minimal token usage for LLM

---

#### New Implementation (FULL)
```
❌ LuaError: __FactoryVerse__/control.lua:123: attempt to index a nil value

Full Traceback:
  1. __FactoryVerse__/control.lua:123: in function 'walk_to'
  2. __FactoryVerse__/agent_interface.lua:45: in function 'execute_action'
  3. [C]: in function 'pcall'
  4. __FactoryVerse__/control.lua:234: in function <__FactoryVerse__/control.lua:230>
```
**Use case**: Complete context when debugging

---

## Configuration Comparison

### Old (Fixed)
```python
# No configuration - always full traceback
rcon_helper = RconHelper(rcon_client)
```

### New (Tunable)
```python
# Configurable verbosity and frame limits
runtime = FactoryVerseRuntime(
    notebook_path="agent.ipynb",
    error_verbosity=ErrorVerbosity.MODERATE,  # Choose level
    max_traceback_frames=2                     # Control frame count
)
```

---

## Integration Points

### Old Implementation
- ✅ RCON layer only
- ❌ Not integrated with Jupyter runtime
- ❌ No error parsing for Python exceptions

### New Implementation
- ✅ RCON layer (via runtime)
- ✅ Jupyter kernel errors
- ✅ Python exceptions
- ✅ Unified error handling

---

## Token Efficiency for LLMs

### Comparison (Sample Error)

| Verbosity | Token Count* | Use Case |
|-----------|-------------|----------|
| Old (Fixed) | ~150 tokens | No control |
| MINIMAL | ~20 tokens | Production agents |
| MODERATE | ~60 tokens | Balanced (default) |
| FULL | ~120 tokens | Debugging |

*Approximate, depends on error complexity

---

## Recommendation

✅ **Use the new implementation** because:
1. **Tunable for LLM consumption**: Control token usage
2. **Smarter filtering**: Removes noise from internal frames
3. **Better integration**: Works with entire runtime
4. **Backward compatible**: Default behavior is sensible
5. **Future-proof**: Easy to extend with new features

The old `rcon_helper` pattern was excellent for its time, but the new `FactorioErrorParser` provides the flexibility needed for LLM agents while preserving the core benefits of structured error handling.
