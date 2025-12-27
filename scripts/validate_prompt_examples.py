"""Validate SQL examples from the system prompt against actual DuckDB database."""
import duckdb
from pathlib import Path

# Connect to the map database
db_path = Path(__file__).parent.parent / "factoryverse-map-snapshot.duckdb"
if not db_path.exists():
    db_path = Path(__file__).parent.parent / ".fv-output" / "factoryverse-map.duckdb"

print(f"Connecting to database: {db_path}")
con = duckdb.connect(str(db_path), read_only=True)

# Load spatial extension
print("Loading spatial extension...")
con.execute("INSTALL spatial;")
con.execute("LOAD spatial;")
print("✅ Spatial extension loaded\n")

# Test queries from the system prompt
test_queries = {
    "water_patch_largest": """
        SELECT 
            patch_id, 
            tile_count, 
            ST_X(centroid) as x, 
            ST_Y(centroid) as y
        FROM water_patch
        ORDER BY tile_count DESC
        LIMIT 10;
    """,
    
    "water_patch_near_position": """
        SELECT 
            patch_id, 
            tile_count, 
            ST_X(centroid) as x, 
            ST_Y(centroid) as y,
            SQRT(POWER(ST_X(centroid) - 100, 2) + POWER(ST_Y(centroid) - 200, 2)) as distance
        FROM water_patch
        WHERE SQRT(POWER(ST_X(centroid) - 100, 2) + POWER(ST_Y(centroid) - 200, 2)) < 100
        ORDER BY distance;
    """,
    
    "resource_patch_iron_ore": """
        SELECT 
            patch_id, 
            resource_name, 
            tile_count, 
            total_amount, 
            ST_X(centroid) as x, 
            ST_Y(centroid) as y
        FROM resource_patch
        WHERE resource_name = 'iron-ore'
        ORDER BY total_amount DESC;
    """,
    
    "resource_patch_nearest_iron": """
        SELECT 
            patch_id, 
            total_amount, 
            ST_X(centroid) as x, 
            ST_Y(centroid) as y,
            SQRT(POWER(ST_X(centroid), 2) + POWER(ST_Y(centroid), 2)) as distance
        FROM resource_patch
        WHERE resource_name = 'iron-ore'
        ORDER BY distance
        LIMIT 1;
    """,
    
    "map_entity_position_struct": """
        SELECT entity_key, entity_name, position.x, position.y
        FROM map_entity
        WHERE ST_Distance(
            ST_Point(position.x, position.y),
            ST_Point(100, 200)
        ) < 50
        LIMIT 5;
    """,
    
    "resource_patch_distance_calculation": """
        SELECT 
            patch_id,
            resource_name,
            total_amount,
            ST_X(centroid) as x,
            ST_Y(centroid) as y,
            SQRT(POWER(ST_X(centroid) - 50, 2) + POWER(ST_Y(centroid) - 75, 2)) as distance
        FROM resource_patch
        WHERE resource_name = 'iron-ore'
        ORDER BY distance
        LIMIT 5;
    """,
    
    "cross_join_distance": """
        SELECT 
            rp.patch_id,
            ST_X(rp.centroid) as patch_x,
            ST_Y(rp.centroid) as patch_y,
            ST_X(wp.centroid) as water_x,
            ST_Y(wp.centroid) as water_y,
            SQRT(
                POWER(ST_X(rp.centroid) - ST_X(wp.centroid), 2) + 
                POWER(ST_Y(rp.centroid) - ST_Y(wp.centroid), 2)
            ) as distance
        FROM resource_patch rp
        CROSS JOIN water_patch wp
        WHERE rp.resource_name = 'iron-ore'
        ORDER BY distance
        LIMIT 1;
    """,
}

print("\n" + "="*80)
print("VALIDATING SQL EXAMPLES FROM SYSTEM PROMPT")
print("="*80 + "\n")

failed_queries = []
passed_queries = []

for name, query in test_queries.items():
    print(f"Testing: {name}")
    print("-" * 40)
    try:
        result = con.execute(query).fetchall()
        print(f"✅ SUCCESS - Returned {len(result)} rows")
        if result:
            print(f"   Sample row: {result[0]}")
        passed_queries.append(name)
    except Exception as e:
        print(f"❌ FAILED - {type(e).__name__}: {e}")
        failed_queries.append((name, str(e)))
    print()

print("="*80)
print("SUMMARY")
print("="*80)
print(f"✅ Passed: {len(passed_queries)}/{len(test_queries)}")
print(f"❌ Failed: {len(failed_queries)}/{len(test_queries)}")

if failed_queries:
    print("\nFailed queries:")
    for name, error in failed_queries:
        print(f"  - {name}: {error}")
    exit(1)
else:
    print("\n🎉 All queries validated successfully!")
    exit(0)
