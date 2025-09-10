# FactoryVerse

This repository explores the intersection of Large Language Models and complex systems optimization through the lens of Factorio gameplay. FactoryVerse treats Factorio not as a collection of objects to manipulate, but as a rich, spatial dataset to be analyzed, queried, and optimized at scale.

## Research Directions

FactoryVerse investigates two primary research questions:

1. **Game State as Spatial Dataset**: How can we model complex game environments as queryable, spatial databases that enable sophisticated analytical reasoning rather than purely reactive gameplay?

2. **Lua Mod Architecture for AI Research**: What mod design patterns best support systematic ablation studies, controlled experiments, and reproducible AI agent evaluation in complex simulation environments?

## The Factorio Game Loop

Understanding Factorio's core progression is essential for designing effective AI agents. The gameplay follows a tightening flywheel pattern:

### Primary Loop
1. **Prospect → Extract**: Locate resource patches; transition from manual mining to automated drilling systems
2. **Process → Assemble**: Smelt raw ores into intermediate materials; construct science pack production chains
3. **Research → Unlock**: Feed science packs to laboratories to advance the technology tree, unlocking higher-tier automation
4. **Scale → Optimize**: Expand production throughput, refactor inefficient layouts, increase sustained science-per-minute
5. **External Pressure → Defend**: Manage pollution-driven enemy evolution; clear expansion areas and establish defensive perimeters
6. **Culminate → Launch**: Construct and fuel a rocket silo; launching the satellite triggers primary victory condition

### Post-Victory Loop (Optional)
7. **Infinite Research**: Rocket launches yield space science packs that fuel repeating technologies, enabling long-term factory optimization beyond the win condition

### Success Criteria
- **Primary**: First rocket launch (victory screen)
- **Secondary**: Sustainable defense against evolving enemies, increasing science-per-minute throughput, continuous technological progression

The loop forms an accelerating flywheel: **Extract → Automate → Research → Scale → Repeat → Launch** — with steady-state infinite research sustaining long-horizon optimization.

## The Visual Context Challenge

Human players rely heavily on visual information that provides crucial gameplay context:

- **Spatial Validity**: Visual indicators for valid entity placement locations
- **Operational Range**: Highlighted coverage areas for drills, inserters, and other range-limited entities  
- **System Dynamics**: Animated sprites indicating flow rates, operational status, and bottlenecks
- **Multi-Scale Views**: Zoom levels that reveal different abstractions (individual machines vs. factory zones vs. global logistics)
- **Resource Flows**: Belt animations, pipe contents, and inventory states
- **Threat Assessment**: Pollution clouds, enemy base locations, and defensive coverage

These visual cues are difficult to capture for text-based LLMs without enabling direct screen observation across multiple frames to understand dynamics.

## FactoryVerse's Solution: Context on the Table

Rather than relying on visual interpretation, FactoryVerse makes implicit game context explicit through a queryable spatial database approach:

### Spatial Intelligence
- **PostGIS Integration**: Leverage mature spatial database capabilities for complex geometric queries
- **Multi-Scale Queries**: Query factory state at different levels of abstraction (entity-level → spatial-level → global logistics)
- **Proximity Analysis**: Identify spatial relationships, coverage gaps, and optimization opportunities

### Temporal Analytics  
- **Production Flow Analysis**: Track resource throughput rates, identify bottlenecks, and optimize production ratios
- **Evolution Tracking**: Monitor pollution spread, enemy base expansion, and defensive coverage over time
- **Performance Metrics**: Sustained science-per-minute, resource efficiency, and factory growth patterns

### Context Materialization
Instead of requiring LLMs to infer context from visual cues, FactoryVerse materializes this information as queryable data:

```sql
-- Find the best iron ore patches near your factory
SELECT 
  resource_name,
  total_amount,
  ST_Distance(centroid, ST_Point(0, 0)) AS distance_from_spawn
FROM sp_resource_patches 
WHERE resource_name = 'iron-ore'
ORDER BY total_amount DESC, distance_from_spawn ASC;

-- Check which resources aren't being mined yet
SELECT resource_name, COUNT(*) as uncovered_patches
FROM sp_resource_patches rp
WHERE NOT EXISTS (
  SELECT 1 FROM raw_entities e 
  WHERE e.name LIKE '%mining-drill%' 
    AND ST_DWithin(rp.centroid, ST_Point(e.pos_x, e.pos_y), 2)
)
GROUP BY resource_name;

-- Find water sources for offshore pumps
SELECT patch_id, coast_length, total_area
FROM get_water_coast(NULL)
WHERE coast_length > 20
ORDER BY coast_length DESC;
```

### Architecture Benefits

1. **Analytical Reasoning**: Enables system-level optimization rather than purely reactive object manipulation
2. **Scalable Observation**: Query exactly what's needed rather than loading entire game state
3. **Flexible Abstraction**: Create novel views and analyses

## Getting Started

[Installation and usage instructions would follow here, for sure]

## Research Applications

FactoryVerse enables investigation of several research questions in AI systems:

- **Multi-Scale Planning**: How do agents balance local optimization vs. global factory efficiency?
- **Spatial Reasoning**: Can LLMs effectively perform complex geometric and logistical reasoning through SQL interfaces?
- **System Dynamics**: How well can text-based models understand and optimize complex feedback loops?
- **Long-Horizon Optimization**: What strategies emerge for infinite research and continuous improvement scenarios?

## Contributing

---

*FactoryVerse: Complex Systems need Intelligent Analysis*