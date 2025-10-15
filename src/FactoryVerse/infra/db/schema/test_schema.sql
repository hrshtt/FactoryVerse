-- Test script to verify FactoryVerse schema is working correctly
-- Run this after the container starts to validate the schema

-- Test basic table existence
SELECT 
    schemaname,
    tablename,
    tableowner
FROM pg_tables 
WHERE schemaname = 'factoryverse'
ORDER BY tablename;

-- Test spatial extension
SELECT PostGIS_Version();

-- Test basic data insertion (if any data exists)
SELECT COUNT(*) as entity_count FROM factoryverse.entities;
SELECT COUNT(*) as resource_tile_count FROM factoryverse.resource_tiles;
SELECT COUNT(*) as resource_rock_count FROM factoryverse.resource_rocks;

-- Test spatial functions
SELECT 
    ST_Point(0, 0) as test_point,
    ST_Distance(ST_Point(0, 0), ST_Point(1, 1)) as test_distance;

-- Test JSONB functionality
SELECT 
    '{"test": "value"}'::jsonb as test_jsonb,
    '{"test": "value"}'::jsonb ? 'test' as test_jsonb_contains;

-- Test views
SELECT COUNT(*) as entities_with_position_count FROM factoryverse.entities_with_position;
SELECT COUNT(*) as resource_tiles_with_position_count FROM factoryverse.resource_tiles_with_position;

-- Test indexes
SELECT 
    indexname,
    indexdef
FROM pg_indexes 
WHERE schemaname = 'factoryverse'
ORDER BY tablename, indexname;

-- Test triggers
SELECT 
    trigger_name,
    event_manipulation,
    event_object_table
FROM information_schema.triggers 
WHERE trigger_schema = 'factoryverse'
ORDER BY event_object_table, trigger_name;

-- Test functions
SELECT 
    routine_name,
    routine_type
FROM information_schema.routines 
WHERE routine_schema = 'factoryverse'
ORDER BY routine_name;

-- Summary
SELECT 
    'Schema validation complete' as status,
    (SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'factoryverse') as table_count,
    (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'factoryverse') as index_count,
    (SELECT COUNT(*) FROM information_schema.views WHERE table_schema = 'factoryverse') as view_count;
