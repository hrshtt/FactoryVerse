import duckdb

from duckdb import DuckDBPyConnection
from FactoryVerse.services.duckdb.load_raw_snapshots import (
    ensure_schema as ensure_raw_schema,
    load_snapshot_dir,
)

DEFAULT_DB_PATH = "factoryverse.duckdb"


class DuckDBSetup:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.con = self.connect_db()
    
    def connect_db(self) -> DuckDBPyConnection:
        return self._connect_db(self.db_path)

    def close(self) -> None:
        self.con.close()

    def _connect_db(self, db_path: str = DEFAULT_DB_PATH) -> DuckDBPyConnection:
        """Open or create the DuckDB database."""
        con = duckdb.connect(db_path)
        con.install_extension('spatial')
        con.load_extension('spatial')
        con.execute("PRAGMA threads=8;")
        return con

    # -----------------------------
    # Spatial tables (resources, water, crude)
    # -----------------------------
    def create_spatial_resource_patches(self) -> None:
        """Create/refresh unioned polygon geometries for solid resource patches.

        Builds a table `sp_resource_patches` with: (tick, patch_id,
        resource_name, tiles, total_amount, geom, area_tiles, perimeter,
        centroid, bbox_geom) using row-span rectangles from `raw_resource_tiles`
        and summary columns from `raw_resource_patches`.

        Geometry assembly/metrics use DuckDB Spatial (GEOMETRY type).
        Reference: DuckDB Spatial functions docs: https://duckdb.org/docs/stable/core_extensions/spatial/functions.html
        """
        con = self.con
        con.execute("DROP TABLE IF EXISTS sp_resource_patches;")
        con.execute(
            r"""
            CREATE TABLE sp_resource_patches AS
            WITH spans AS (
              SELECT
                tick,
                patch_id,
                resource_name,
                CAST(tile_x AS DOUBLE)                 AS xmin,
                CAST(tile_y AS DOUBLE)                 AS ymin,
                CAST(tile_x + len AS DOUBLE)           AS xmax,
                CAST(tile_y + 1 AS DOUBLE)             AS ymax
              FROM raw_resource_tiles
              WHERE surface = 'nauvis'
            ),
            rects AS (
              SELECT
                tick, patch_id, resource_name,
                ST_MakeEnvelope(xmin, ymin, xmax, ymax) AS geom
              FROM spans
            ),
            patches AS (
              SELECT
                tick, patch_id, resource_name,
                ST_Union_Agg(geom) AS geom
              FROM rects
              GROUP BY tick, patch_id, resource_name
            )
            SELECT
              p.tick,
              p.patch_id,
              p.resource_name,
              rp.tiles,
              rp.total_amount,
              p.geom,
              ST_Area(p.geom)      AS area_tiles,
              ST_Perimeter(p.geom) AS perimeter,
              ST_Centroid(p.geom)  AS centroid,
              ST_Envelope(p.geom)  AS bbox_geom
            FROM patches p
            LEFT JOIN raw_resource_patches rp
              ON p.tick = rp.tick AND p.patch_id = rp.patch_id AND p.resource_name = rp.resource_name
              AND rp.surface = 'nauvis';
            """
        )
        # Spatial R-Tree index on geometry for fast predicates
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_sp_resource_patches_rtree ON sp_resource_patches USING rtree(geom);"
        )

    def create_spatial_water_patches(self) -> None:
        """Create/refresh unioned polygon geometries for water patches.

        Builds a table `sp_water_patches` with: (tick, patch_id,
        geom, area_tiles, perimeter, centroid, bbox_geom, tiles).
        Uses row-span rectangles from `raw_water_tiles` and joins counts from
        `raw_water_patches`.

        Reference: DuckDB Spatial functions docs: https://duckdb.org/docs/stable/core_extensions/spatial/functions.html
        """
        con = self.con
        con.execute("DROP TABLE IF EXISTS sp_water_patches;")
        con.execute(
            r"""
            CREATE TABLE sp_water_patches AS
            WITH spans AS (
              SELECT
                tick,
                patch_id,
                CAST(tile_x AS DOUBLE)                 AS xmin,
                CAST(tile_y AS DOUBLE)                 AS ymin,
                CAST(tile_x + len AS DOUBLE)           AS xmax,
                CAST(tile_y + 1 AS DOUBLE)             AS ymax
              FROM raw_water_tiles
              WHERE surface = 'nauvis'
            ),
            rects AS (
              SELECT
                tick, patch_id,
                ST_MakeEnvelope(xmin, ymin, xmax, ymax) AS geom
              FROM spans
            ),
            patches AS (
              SELECT
                tick, patch_id,
                ST_Union_Agg(geom) AS geom
              FROM rects
              GROUP BY tick, patch_id
            )
            SELECT
              p.tick,
              p.patch_id,
              p.geom,
              ST_Area(p.geom)      AS area_tiles,
              ST_Perimeter(p.geom) AS perimeter,
              ST_Centroid(p.geom)  AS centroid,
              ST_Envelope(p.geom)  AS bbox_geom,
              wp.tiles
            FROM patches p
            LEFT JOIN raw_water_patches wp
              ON p.tick = wp.tick AND p.patch_id = wp.patch_id
              AND wp.surface = 'nauvis';
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_sp_water_patches_rtree ON sp_water_patches USING rtree(geom);"
        )

    def create_spatial_crude_points(self) -> None:
        """Create/refresh crude oil wells as POINT geometries.

        Builds a table `sp_crude_wells` with one row per well (always 1x1),
        preserving `patch_id` and amount, and a POINT `geom` at (pos_x, pos_y).

        Reference: DuckDB Spatial functions docs: https://duckdb.org/docs/stable/core_extensions/spatial/functions.html
        """
        con = self.con
        con.execute("DROP TABLE IF EXISTS sp_crude_wells;")
        con.execute(
            r"""
            CREATE TABLE sp_crude_wells AS
            SELECT
              tick,
              patch_id,
              resource_name,
              tile_x,
              tile_y,
              pos_x,
              pos_y,
              amount,
              ST_Point(pos_x, pos_y) AS geom
            FROM raw_crude_tiles
            WHERE surface = 'nauvis';
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_sp_crude_wells_rtree ON sp_crude_wells USING rtree(geom);"
        )

    def create_all_spatial_tables(self) -> None:
        """Helper to create/refresh all spatial tables in one call."""
        self.create_spatial_resource_patches()
        self.create_spatial_water_patches()
        self.create_spatial_crude_points()

    def create_water_coast_macro(self) -> None:
        """Create macro for getting water patch boundaries/coasts.
        
        Creates a macro `get_water_coast` that returns the boundary geometry
        of water patches, useful for finding shorelines where offshore pumps
        can be placed.
        
        Usage:
        - get_water_coast(NULL, NULL) - all water patches (latest tick)
        - get_water_coast('patch_123', NULL) - specific patch (latest tick)
        - get_water_coast('patch_123', 1000) - specific patch with tick
        - get_water_coast(NULL, 1000) - all patches at specific tick
        """
        con = self.con
        con.execute("DROP MACRO IF EXISTS get_water_coast;")
        con.execute(
            r"""
            CREATE OR REPLACE MACRO get_water_coast(
                patch_id_filter,
                tick_filter
            ) AS TABLE (
                WITH ctx AS (
                    SELECT 
                        COALESCE(tick_filter, (SELECT MAX(w.tick) FROM sp_water_patches w)) AS tick
                ),
                filtered_patches AS (
                    SELECT w.patch_id, w.geom, w.area_tiles, w.perimeter
                    FROM sp_water_patches w, ctx
                    WHERE w.tick = ctx.tick
                      AND (patch_id_filter IS NULL OR w.patch_id = patch_id_filter)
                )
                SELECT 
                    fp.patch_id,
                    ST_Boundary(fp.geom) AS coast_geom,
                    ST_AsText(ST_Boundary(fp.geom)) AS coast_wkt,
                    ST_AsGeoJSON(ST_Boundary(fp.geom)) AS coast_geojson,
                    fp.area_tiles,
                    fp.perimeter,
                    ST_Length(ST_Boundary(fp.geom)) AS coast_length
                FROM filtered_patches fp
                ORDER BY fp.area_tiles DESC
            );
            """
        )

    def create_all_macros(self) -> None:
        """Helper to create/refresh all macros in one call."""
        self.create_water_coast_macro()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Load Factorio snapshot JSONs and build spatial tables in DuckDB.")
    ap.add_argument("snapshot_dir", help="Directory containing *.json snapshots to load")
    ap.add_argument("--db", dest="db", default=DEFAULT_DB_PATH, help=f"DuckDB path (default: {DEFAULT_DB_PATH})")
    args = ap.parse_args()

    setup = DuckDBSetup(args.db)
    con = setup.con

    # Ensure base raw schema exists, then load snapshots from directory
    ensure_raw_schema(con)
    loaded = load_snapshot_dir(con, args.snapshot_dir)
    print(f"Loaded {len(loaded)} snapshot files into {args.db}")

    # Build spatial tables
    setup.create_all_spatial_tables()
    
    # Create macros
    setup.create_all_macros()

    # Brief counts for confirmation
    res_cnt = con.execute("SELECT COUNT(*) FROM sp_resource_patches").fetchone()[0]
    wat_cnt = con.execute("SELECT COUNT(*) FROM sp_water_patches").fetchone()[0]
    cru_cnt = con.execute("SELECT COUNT(*) FROM sp_crude_wells").fetchone()[0]
    print(f"sp_resource_patches: {res_cnt} rows")
    print(f"sp_water_patches:    {wat_cnt} rows")
    print(f"sp_crude_wells:      {cru_cnt} rows")
    print("Macros created: get_water_coast")
