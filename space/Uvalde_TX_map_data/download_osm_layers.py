from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import osmnx as ox


AOI_FILE = Path(__file__).resolve().parent / "uvalde_aoi.geojson"
RAW_DIR = Path(__file__).resolve().parent / "raw"


def load_aoi() -> gpd.GeoDataFrame:
    aoi = gpd.read_file(AOI_FILE)
    if aoi.empty:
        raise ValueError(f"AOI file is empty: {AOI_FILE}")
    if aoi.crs is None:
        aoi = aoi.set_crs("EPSG:4326")
    return aoi.to_crs("EPSG:4326")


def save_layer(gdf: gpd.GeoDataFrame, out_file: Path) -> None:
    if gdf.empty:
        print(f"No features found for {out_file.name}")
        return
    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty]
    gdf = gdf.set_crs(gdf.crs or "EPSG:4326")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_file, driver="GeoJSON")
    print(f"Wrote {len(gdf)} features to {out_file}")


def query_osm_layers(aoi: gpd.GeoDataFrame) -> None:
    polygon = aoi.geometry.iloc[0]

    ox.settings.use_cache = True
    ox.settings.log_console = True

    building_tags = {"building": True}
    poi_tags = {
        "amenity": [
            "school",
            "hospital",
            "clinic",
            "doctors",
            "pharmacy",
            "shelter",
            "place_of_worship",
            "townhall",
            "fire_station",
            "police",
            "library",
            "community_centre",
            "social_centre",
            "community_hall",
        ],
        "shop": True,
        "office": True,
        "tourism": True,
        "leisure": ["park", "sports_centre", "stadium", "fitness_centre"],
        "public_building": True,
        "building": ["church", "chapel", "cathedral", "mosque", "synagogue"],
    }
    landuse_tags = {
        "landuse": [
            "residential",
            "commercial",
            "retail",
            "industrial",
            "education",
            "institutional",
            "civic_admin",
            "military",
            "forest",
            "grass",
            "farmland",
            "cemetery",
        ]
    }

    road_tags = {
        "highway": [
            "residential",
            "living_street",
            "service",
            "unclassified",
            "tertiary",
            "tertiary_link",
            "secondary",
            "secondary_link",
        ]
    }

    buildings = ox.features_from_polygon(polygon, tags=building_tags)
    buildings = buildings.reset_index()
    buildings = gpd.GeoDataFrame(buildings, geometry="geometry", crs="EPSG:4326")
    buildings = gpd.clip(buildings, aoi)
    save_layer(buildings, RAW_DIR / "osm_buildings.geojson")

    pois = ox.features_from_polygon(polygon, tags=poi_tags)
    pois = pois.reset_index()
    pois = gpd.GeoDataFrame(pois, geometry="geometry", crs="EPSG:4326")
    pois = gpd.clip(pois, aoi)
    save_layer(pois, RAW_DIR / "osm_pois.geojson")

    landuse = ox.features_from_polygon(polygon, tags=landuse_tags)
    landuse = landuse.reset_index()
    landuse = gpd.GeoDataFrame(landuse, geometry="geometry", crs="EPSG:4326")
    landuse = gpd.clip(landuse, aoi)
    save_layer(landuse, RAW_DIR / "osm_landuse.geojson")

    roads = ox.features_from_polygon(polygon, tags=road_tags)
    roads = roads.reset_index()
    roads = gpd.GeoDataFrame(roads, geometry="geometry", crs="EPSG:4326")
    roads = roads[roads.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    roads = gpd.clip(roads, aoi)
    save_layer(roads, RAW_DIR / "osm_roads.geojson")


def main() -> None:
    aoi = load_aoi()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    query_osm_layers(aoi)


if __name__ == "__main__":
    main()