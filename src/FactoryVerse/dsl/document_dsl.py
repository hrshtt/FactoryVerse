"""DSL documentation for generating complete interface documentation.

Generates lean, precise documentation of all Python interfaces available to LLM agents:
- Top-level affordances (walking, crafting, etc.)
- Entity class hierarchy and their methods
- Item class hierarchy and their methods
- Recipe interfaces

Output is flat, no markdown formatting, just method signatures with return types.
"""

import inspect
from typing import Any, Dict, List, get_type_hints, get_origin, get_args
import sys


def _format_type(typ) -> str:
    """Format a type annotation as a string."""
    if typ is None or typ is type(None):
        return "None"
    
    # Handle string annotations
    if isinstance(typ, str):
        return typ
    
    # Get the origin for generic types
    origin = get_origin(typ)
    
    # Handle Optional[X] -> X | None
    if origin is type(None.__class__):  # Union type
        args = get_args(typ)
        if len(args) == 2 and type(None) in args:
            other = args[0] if args[1] is type(None) else args[1]
            return f"{_format_type(other)} | None"
        return " | ".join(_format_type(arg) for arg in args)
    
    # Handle List[X], Dict[K,V], etc.
    if origin is not None:
        args = get_args(typ)
        if args:
            args_str = ", ".join(_format_type(arg) for arg in args)
            origin_name = getattr(origin, '__name__', str(origin))
            return f"{origin_name}[{args_str}]"
        return getattr(origin, '__name__', str(origin))
    
    # Handle ForwardRef
    if hasattr(typ, '__forward_arg__'):
        return typ.__forward_arg__
    
    # Handle regular types
    if hasattr(typ, '__name__'):
        return typ.__name__
    
    # Handle strings (sometimes types are just strings)
    if isinstance(typ, str):
        return typ
        
    return str(typ)


def _get_method_signature(obj: Any, method_name: str) -> str:
    """Extract complete method signature with return type."""
    method = getattr(obj, method_name)
    
    try:
        sig = inspect.signature(method)
        
        # Get type hints (includes return type)
        try:
            hints = get_type_hints(method)
        except:
            hints = {}
        
        # Build parameter list
        params = []
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # Get type annotation
            if param_name in hints:
                type_str = _format_type(hints[param_name])
            elif param.annotation != inspect.Parameter.empty:
                type_str = _format_type(param.annotation)
            else:
                type_str = "Any"
            
            # Check if optional (has default)
            if param.default != inspect.Parameter.empty:
                params.append(f"{param_name}: {type_str} = ...")
            else:
                params.append(f"{param_name}: {type_str}")
        
        # Get return type
        if 'return' in hints:
            return_type = _format_type(hints['return'])
        elif sig.return_annotation != inspect.Signature.empty:
            return_type = _format_type(sig.return_annotation)
        else:
            return_type = "Any"
        
        params_str = ", ".join(params)
        return f"{method_name}({params_str}) -> {return_type}"
    
    except Exception as e:
        # Fallback for methods we can't introspect
        return f"{method_name}(...) -> Any"


def _get_class_methods_and_properties(cls: type) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Get all public methods and properties of a class with signatures."""
    methods = []
    properties = []
    
    for name in dir(cls):
        if name.startswith('_'):
            continue
        
        try:
            attr = getattr(cls, name)
        except:
            continue
        
        # Handle properties
        if isinstance(attr, property):
            try:
                # Try to get return type from property fget
                if attr.fget:
                    hints = get_type_hints(attr.fget)
                    return_type = _format_type(hints.get('return', 'Any'))
                else:
                    return_type = "Any"
                
                # Get first line of docstring
                doc = inspect.getdoc(attr) or ""
                doc_line = doc.split('\n')[0] if doc else ""
                
                properties.append({
                    'name': name,
                    'type': return_type,
                    'description': doc_line
                })
            except:
                continue
            continue
        
        # Skip non-callables
        if not callable(attr):
            continue
        
        # Get method signature
        try:
            sig = _get_method_signature(cls, name)
            
            # Get first line of docstring
            doc = inspect.getdoc(attr) or ""
            doc_line = doc.split('\n')[0] if doc else ""
            
            methods.append({
                'signature': sig,
                'description': doc_line
            })
        except:
            continue
    
    return methods, properties


def _get_class_methods_and_properties(cls: type, exclude_inherited_from: List[type] = None) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Get all public methods and properties of a class with signatures.
    
    Args:
        cls: Class to introspect
        exclude_inherited_from: List of base classes to exclude methods/properties from
    """
    methods = []
    properties = []
    
    # Get set of names to exclude (from base classes)
    excluded_names = set()
    if exclude_inherited_from:
        for base_cls in exclude_inherited_from:
            excluded_names.update(dir(base_cls))
    
    # Add regular methods and properties
    for name in dir(cls):
        if name.startswith('_'):
            continue
        
        # Skip if inherited from excluded base
        if name in excluded_names:
            continue
        
        try:
            attr = getattr(cls, name)
        except:
            continue
        
        # Handle properties
        if isinstance(attr, property):
            try:
                # Try to get return type from property fget
                if attr.fget:
                    hints = get_type_hints(attr.fget)
                    return_type = _format_type(hints.get('return', 'Any'))
                else:
                    return_type = "Any"
                
                # Get first line of docstring
                doc = inspect.getdoc(attr) or ""
                doc_line = doc.split('\n')[0] if doc else ""
                
                properties.append({
                    'name': name,
                    'type': return_type,
                    'description': doc_line
                })
            except:
                continue
            continue
        
        # Skip non-callables
        if not callable(attr):
            continue
        
        # Get method signature
        try:
            sig = _get_method_signature(cls, name)
            
            # Get first line of docstring
            doc = inspect.getdoc(attr) or ""
            doc_line = doc.split('\n')[0] if doc else ""
            
            methods.append({
                'signature': sig,
                'description': doc_line
            })
        except:
            continue

    # Add dataclass fields
    import dataclasses
    if dataclasses.is_dataclass(cls):
        # Get type hints for the class to get correct types
        try:
            hints = dataclasses.get_type_hints(cls)
        except:
            # Fallback for older python or issues
            try:
                hints = get_type_hints(cls)
            except:
                hints = {}
            
        for field in dataclasses.fields(cls):
            if field.name.startswith('_'):
                continue
            
            # Skip if inherited from excluded base
            if field.name in excluded_names:
                continue
            
            # Avoid duplicating if already added as property
            if any(p['name'] == field.name for p in properties):
                continue

            type_hint = hints.get(field.name, field.type)
            type_str = _format_type(type_hint)
            
            properties.append({
                'name': field.name,
                'type': type_str,
                'description': ""
            })

    return methods, properties


def _get_class_bases(cls: type) -> List[str]:
    """Get list of base class names (excluding object and ABC)."""
    bases = []
    for base in cls.__bases__:
        if base.__name__ in ('object', 'ABC'):
            continue
        bases.append(base.__name__)
    return bases


def introspect_mixins(show_full_docs: bool = False) -> str:
    """Generate documentation for DSL mixins.
    
    Args:
        show_full_docs: If True, show full docstrings. If False, show only first line.
    """
    from FactoryVerse.dsl import mixins
    import inspect
    
    output = []
    output.append("=== MIXINS ===\n")
    
    # Discover all mixin classes
    mixin_classes = []
    for name, obj in inspect.getmembers(mixins, inspect.isclass):
        if name.startswith('_'):
            continue
        if not name.endswith('Mixin'):
            continue
        mixin_classes.append((name, obj))
    
    mixin_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in mixin_classes:
        output.append(f"{class_name}:")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        # Show properties first
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description'] and not show_full_docs:
                    output.append(f"    {prop['description']}")
        
        # Then methods
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description'] and not show_full_docs:
                output.append(f"    {method['description']}")
        output.append("")
    
    return "\n".join(output)


def introspect_entity_types(show_inherited: bool = False) -> str:
    """Generate documentation for entity class hierarchy.
    
    Args:
        show_inherited: If True, show all methods including inherited from mixins.
                       If False, show only unique methods per class.
    """
    from FactoryVerse.dsl.entity import base
    import inspect
    
    output = []
    output.append("=== ENTITY TYPES ===\n")
    
    # Dynamically discover all entity classes
    entity_classes = []
    for name, obj in inspect.getmembers(base, inspect.isclass):
        # Skip private classes and imports
        if name.startswith('_'):
            continue
        # Only include classes defined in this module
        if obj.__module__ != 'FactoryVerse.dsl.entity.base':
            continue
        # Skip mixin classes
        if 'Mixin' in name:
            continue
        # Skip EntityPosition (it's a helper, not an entity)
        if name == 'EntityPosition':
            continue
        
        entity_classes.append((name, obj))
    
    # Sort by name for consistent output
    entity_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in entity_classes:
        # Get base classes
        bases = _get_class_bases(cls)
        if bases:
            output.append(f"{class_name}({', '.join(bases)}):")
        else:
            output.append(f"{class_name}:")
        
        if show_inherited:
            # Show all methods/properties
            methods, properties = _get_class_methods_and_properties(cls)
        else:
            # Show only unique methods/properties (exclude inherited from bases)
            exclude_bases = [base for base in cls.__bases__ if base.__name__ != 'object']
            methods, properties = _get_class_methods_and_properties(cls, exclude_inherited_from=exclude_bases)
        
        # Show properties first
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        # Then methods
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        
        # If no unique methods/properties, indicate it inherits everything
        if not methods and not properties and not show_inherited:
            output.append(f"  (inherits all from base classes)")
        
        output.append("")
    
    return "\n".join(output)


def introspect_affordances() -> str:
    """Generate documentation for top-level affordances."""
    from FactoryVerse.dsl.dsl import (
        _WalkingAccessor,
        _CraftingAccessor,
        _ResearchAccessor,
        _InventoryAccessor,
        _ReachableAccessor,
        _DuckDBAccessor
    )
    from FactoryVerse.dsl.ghosts import GhostManager
    
    output = []
    output.append("=== TOP-LEVEL AFFORDANCES ===\n")
    
    affordance_classes = {
        'walking': _WalkingAccessor,
        'crafting': _CraftingAccessor,
        'research': _ResearchAccessor,
        'inventory': _InventoryAccessor,
        'reachable': _ReachableAccessor,
        'map_db': _DuckDBAccessor,
        'ghosts': GhostManager,
    }
    
    for name, cls in affordance_classes.items():
        output.append(f"{name}:")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        # Show properties first
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        # Then methods
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        output.append("")
    
    return "\n".join(output)


def introspect_item_types() -> str:
    """Generate documentation for item class hierarchy."""
    from FactoryVerse.dsl.item import base
    
    output = []
    output.append("=== ITEM TYPES ===\n")
    
    # Get all item classes
    item_classes = [
        ('Item', base.Item),
        ('PlaceableItem', base.PlaceableItem),
        ('Fuel', base.Fuel),
    ]
    
    for class_name, cls in item_classes:
        # Get base classes
        bases = _get_class_bases(cls)
        if bases:
            output.append(f"{class_name}({', '.join(bases)}):")
        else:
            output.append(f"{class_name}:")
        
        # Show only unique methods/properties
        exclude_bases = [base for base in cls.__bases__ if base.__name__ != 'object']
        methods, properties = _get_class_methods_and_properties(cls, exclude_inherited_from=exclude_bases)
        
        # Show properties first
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        # Then methods
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        
        if not methods and not properties:
            output.append(f"  (inherits all from base classes)")
        
        output.append("")
    
    return "\n".join(output)


def introspect_recipe_types() -> str:
    """Generate documentation for recipe interfaces."""
    from FactoryVerse.dsl.recipe import base
    import inspect
    
    output = []
    output.append("=== RECIPE TYPES ===\n")
    
    # Dynamically discover recipe classes
    recipe_classes = []
    for name, obj in inspect.getmembers(base, inspect.isclass):
        if name.startswith('_'):
            continue
        if obj.__module__ != 'FactoryVerse.dsl.recipe.base':
            continue
        recipe_classes.append((name, obj))
    
    recipe_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in recipe_classes:
        output.append(f"{class_name}:")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        # Show properties first
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        # Then methods
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        output.append("")
    
    return "\n".join(output)


def introspect_base_classes() -> str:
    """Generate documentation for base classes (ReachableEntity, Item, etc.)."""
    from FactoryVerse.dsl.entity import base as entity_base
    from FactoryVerse.dsl.item import base as item_base
    
    output = []
    output.append("=== BASE CLASSES ===\n")
    
    # Base entity
    output.append("ReachableEntity(FactoryContextMixin, SpatialPropertiesMixin, PrototypeMixin):")
    methods, properties = _get_class_methods_and_properties(entity_base.ReachableEntity)
    
    if properties:
        for prop in properties:
            output.append(f"  {prop['name']}: {prop['type']}")
            if prop['description']:
                output.append(f"    {prop['description']}")
    
    for method in methods:
        output.append(f"  {method['signature']}")
        if method['description']:
            output.append(f"    {method['description']}")
    output.append("")
    
    # Base item classes
    for class_name, cls in [('Item', item_base.Item), ('PlaceableItem', item_base.PlaceableItem)]:
        bases = _get_class_bases(cls)
        if bases:
            output.append(f"{class_name}({', '.join(bases)}):")
        else:
            output.append(f"{class_name}:")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        output.append("")
    
    return "\n".join(output)


def introspect_specific_entities(show_inherited: bool = False) -> str:
    """Generate documentation for specific entity implementations."""
    from FactoryVerse.dsl.entity import base
    import inspect
    
    output = []
    output.append("=== SPECIFIC ENTITY TYPES ===\n")
    
    # Dynamically discover all entity classes
    entity_classes = []
    for name, obj in inspect.getmembers(base, inspect.isclass):
        if name.startswith('_'):
            continue
        if obj.__module__ != 'FactoryVerse.dsl.entity.base':
            continue
        if 'Mixin' in name:
            continue
        if name in ('EntityPosition', 'ReachableEntity'):  # Skip base and helpers
            continue
        
        entity_classes.append((name, obj))
    
    entity_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in entity_classes:
        bases = _get_class_bases(cls)
        if bases:
            output.append(f"{class_name}({', '.join(bases)}):")
        else:
            output.append(f"{class_name}:")
        
        if show_inherited:
            methods, properties = _get_class_methods_and_properties(cls)
        else:
            exclude_bases = [base for base in cls.__bases__ if base.__name__ != 'object']
            methods, properties = _get_class_methods_and_properties(cls, exclude_inherited_from=exclude_bases)
        
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        
        if not methods and not properties and not show_inherited:
            output.append(f"  (inherits all from base classes)")
        
        output.append("")
    
    return "\n".join(output)


def introspect_specific_items() -> str:
    """Generate documentation for specific item implementations."""
    from FactoryVerse.dsl.item import base
    
    output = []
    output.append("=== SPECIFIC ITEM TYPES ===\n")
    
    # Only Fuel is a specific implementation (Item and PlaceableItem are base)
    item_classes = [('Fuel', base.Fuel)]
    
    for class_name, cls in item_classes:
        bases = _get_class_bases(cls)
        if bases:
            output.append(f"{class_name}({', '.join(bases)}):")
        else:
            output.append(f"{class_name}:")
        
        exclude_bases = [base for base in cls.__bases__ if base.__name__ != 'object']
        methods, properties = _get_class_methods_and_properties(cls, exclude_inherited_from=exclude_bases)
        
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
                if prop['description']:
                    output.append(f"    {prop['description']}")
        
        for method in methods:
            output.append(f"  {method['signature']}")
            if method['description']:
                output.append(f"    {method['description']}")
        
        if not methods and not properties:
            output.append(f"  (inherits all from base classes)")
        
        output.append("")
    
    return "\n".join(output)


def generate_complete_interface_doc(show_inherited: bool = False) -> str:
    """Generate complete DSL interface documentation.
    
    Args:
        show_inherited: If True, show all methods including inherited from mixins.
                       If False (default), show only unique methods per class.
                       Setting to False reduces token count significantly.
    
    Output Order:
        1. Top-level affordances (walking, crafting, etc.)
        2. Entity capability protocols (ReachableEntity, GhostEntity, RemoteViewEntity)
        3. Resource capability protocols (ReachableResource, RemoteViewResource)
        4. Base classes (ReachableEntity, Item, PlaceableItem)
        5. Mixins (InspectableMixin, FuelableMixin, etc.)
        6. Specific entity types (Furnace, Container, etc.)
        7. Specific item types (Fuel)
        8. Recipe types
    """
    parts = [
        introspect_affordances(),
        introspect_view_categories(),
        # introspect_entity_protocols(),
        # introspect_resource_protocols(),
        introspect_base_classes(),
        introspect_mixins(),
        introspect_specific_entities(show_inherited=show_inherited),
        introspect_specific_items(),
        introspect_recipe_types(),
    ]
    
    return "\n".join(parts)


# Backwards compatibility
def get_all_affordances() -> Dict[str, str]:
    """Legacy method - returns affordances only."""
    return {'complete_doc': introspect_affordances()}


def describe_affordance(name: str) -> str:
    """Legacy method - returns affordance doc."""
    return introspect_affordances()


def list_affordances() -> List[str]:
    """Legacy method - returns affordance names."""
    return ['walking', 'crafting', 'research', 'inventory', 'reachable', 'ghosts']


def introspect_entity_protocols() -> str:
    """Generate documentation for entity capability protocols."""
    from FactoryVerse.dsl.entity import protocols
    import inspect
    
    output = []
    output.append("=== ENTITY CAPABILITY PROTOCOLS ===\n")
    
    # Discover all protocol classes
    protocol_classes = []
    for name, obj in inspect.getmembers(protocols, inspect.isclass):
        if name.startswith('_'):
            continue
        # Check if it's a Protocol
        if hasattr(obj, '__protocol_attrs__') or 'Protocol' in str(obj.__bases__):
            protocol_classes.append((name, obj))
    
    protocol_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in protocol_classes:
        output.append(f"{class_name}:")
        
        # Get docstring
        doc = inspect.getdoc(cls) or ""
        if doc:
            # Show first paragraph
            first_para = doc.split('\n\n')[0]
            for line in first_para.split('\n'):
                output.append(f"  {line}")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        # Show properties
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
        
        # Show methods
        for method in methods:
            output.append(f"  {method['signature']}")
        
        output.append("")
    
    return "\n".join(output)


def introspect_resource_protocols() -> str:
    """Generate documentation for resource capability protocols."""
    from FactoryVerse.dsl.resource import protocols
    import inspect
    
    output = []
    output.append("=== RESOURCE CAPABILITY PROTOCOLS ===\n")
    
    # Discover all protocol classes
    protocol_classes = []
    for name, obj in inspect.getmembers(protocols, inspect.isclass):
        if name.startswith('_'):
            continue
        if hasattr(obj, '__protocol_attrs__') or 'Protocol' in str(obj.__bases__):
            protocol_classes.append((name, obj))
    
    protocol_classes.sort(key=lambda x: x[0])
    
    for class_name, cls in protocol_classes:
        output.append(f"{class_name}:")
        
        # Get docstring
        doc = inspect.getdoc(cls) or ""
        if doc:
            # Show first paragraph
            first_para = doc.split('\n\n')[0]
            for line in first_para.split('\n'):
                output.append(f"  {line}")
        
        methods, properties = _get_class_methods_and_properties(cls)
        
        # Show properties
        if properties:
            for prop in properties:
                output.append(f"  {prop['name']}: {prop['type']}")
        
        # Show methods
        for method in methods:
            output.append(f"  {method['signature']}")
        
        output.append("")
    
    return "\n".join(output)

def introspect_view_categories() -> str:
    """Generate documentation for entity view categories."""
    output = []
    output.append("=== ENTITY VIEW CATEGORIES ===\n")
    output.append("Three view categories enforce access control based on entity source:\n")
    
    output.append("RemoteViewEntity (Read-Only):")
    output.append("  Returned by: map_db.get_entities(), map_db.get_entity()")
    output.append("  Allows: spatial properties, prototype data, inspect(), entity-specific planning")
    output.append("  Blocks: pickup(), add_fuel(), add_ingredients(), take_products(), store/take_items()")
    output.append("")
    
    output.append("ReachableEntity (Full Access):")
    output.append("  Returned by: reachable.get_entities(), reachable.get_entity()")
    output.append("  Allows: Everything - all spatial, planning, AND mutation methods")
    output.append("  Methods depend on entity's mixins (FuelableMixin, CrafterMixin, etc.)")
    output.append("")
    
    output.append("GhostEntity (Build-Only):")
    output.append("  Returned by: item.place_ghost(), ghosts.get_ghosts()")
    output.append("  Allows: spatial properties, prototype data, inspect(), planning, build(), remove()")
    output.append("  Blocks: pickup(), add_fuel(), add_ingredients(), store/take_items()")
    output.append("")
    
    return "\n".join(output)
