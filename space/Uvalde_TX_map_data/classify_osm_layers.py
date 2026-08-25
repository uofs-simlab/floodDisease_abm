from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed"


HOUSE_TYPES = {
    "residential",
    "house",
    "apartments",
    "detached",
    "semidetached_house",
    "terrace",
    "bungalow",
    "dormitory",
    "ger",
    "cabin",
    "hut",
}

SCHOOL_AMENITIES = {"school", "college", "university", "kindergarten"}
HEALTHCARE_AMENITIES = {"hospital", "clinic", "doctors", "pharmacy", "dentist"}
SHELTER_AMENITIES = {"shelter"}
GOVERNMENT_AMENITIES = {"townhall", "police", "fire_station", "courthouse", "post_office"}
BUSINESS_AMENITIES = {
    "bank",
    "restaurant",
    "cafe",
    "fast_food",
    "bar",
    "pub",
    "fuel",
    "marketplace",
    "theatre",
    "cinema",
    "mall",
    "parking",
}

BUSINESS_BUILDINGS = {"commercial", "retail", "office", "industrial", "warehouse", "supermarket", "service", "shop", "kiosk"}
GOVERNMENT_BUILDINGS = {"government", "civic", "public", "administrative"}
SHELTER_BUILDINGS = {"shelter"}
SCHOOL_BUILDINGS = {"school", "college", "university", "kindergarten"}
HEALTHCARE_BUILDINGS = {"hospital", "clinic", "doctors", "pharmacy", "dentist"}
NON_CAMPUS_BUILDINGS = {"roof", "hangar", "shed", "ruins"}
LANDUSE_HOUSE = {"residential"}
LANDUSE_BUSINESS = {"commercial", "retail", "industrial"}
LANDUSE_SCHOOL = {"education"}
LANDUSE_GOV = {"civic_admin", "institutional", "military"}
SHELTER_NAME_KEYWORDS = {"shelter", "warming center", "warming centre", "salvation army", "red cross"}
HOUSE_NAME_KEYWORDS = {
    "apartments",
    "apartment",
    "residence",
    "residential",
    "home",
    "house",
    "condo",
    "condominium",
    "dorm",
    "lodging",
    "inn",
    "hotel",
    "motel",
    "guest house",
}


PARCEL_LAYER_CANDIDATES = [
    RAW_DIR / "uvalde_property_parcels.geojson",
    RAW_DIR / "uvalde_property_parcels.gpkg",
    RAW_DIR / "property_parcels.geojson",
    RAW_DIR / "property_parcels.gpkg",
]


RESIDENTIAL_UNKNOWN_AREA_THRESHOLD = 250.0
SMALL_BUILDING_AREA_THRESHOLD = 140.0
BUSINESS_POI_DISTANCE_M = 40.0
SCHOOL_POI_DISTANCE_M = 30.0
HEALTHCARE_POI_DISTANCE_M = 35.0
SHELTER_POI_DISTANCE_M = 60.0
SHELTER_TARGET_COUNT = 3
SCHOOL_CAMPUS_MATCH_DISTANCE_M = 120.0
SCHOOL_CAMPUS_BUFFER_M = 20.0


def read_layer(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs("EPSG:4326")


def first_nonempty_series(gdf: gpd.GeoDataFrame, columns: list[str]) -> pd.Series:
    for col in columns:
        if col in gdf.columns:
            values = gdf[col].astype("string")
            if values.notna().any():
                return values.fillna("")
    return pd.Series([""] * len(gdf), index=gdf.index, dtype="string")


def normalize_text(value: str) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def layer_mask_by_values(series: pd.Series, values: set[str]) -> pd.Series:
    return series.map(normalize_text).isin(values)


def name_contains(series: pd.Series, keywords: set[str]) -> pd.Series:
    norm = series.fillna("").map(normalize_text)
    return norm.apply(lambda value: any(keyword in value for keyword in keywords))


def save_gpkg(gdf: gpd.GeoDataFrame, path: Path, layer_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.empty:
        print(f"No features for {layer_name}")
        return
    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty]
    gdf.to_file(path, layer=layer_name, driver="GPKG")
    print(f"Wrote {len(gdf)} features -> {path.name}:{layer_name}")


def save_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.empty:
        print(f"No features for {path.name}")
        return
    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty]
    gdf.to_file(path, driver="GeoJSON")
    print(f"Wrote {len(gdf)} features -> {path}")


def geometry_area_m2(gdf: gpd.GeoDataFrame) -> pd.Series:
    if gdf.empty:
        return pd.Series(dtype="float64", index=gdf.index)
    projected = gdf.to_crs(3857)
    return projected.geometry.area.reindex(gdf.index)


def build_school_campuses(buildings: gpd.GeoDataFrame, pois: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    school_buildings = buildings[buildings["category"].eq("school")].copy()
    school_pois = pois[pois["category"].eq("school")].copy()

    if school_buildings.empty and school_pois.empty:
        return gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs="EPSG:4326")

    campuses: list[dict] = []
    used_building_index: set = set()

    if not school_pois.empty:
        school_buildings_proj = school_buildings.to_crs(3857)
        school_pois_proj = school_pois.to_crs(3857)

        for poi_idx, poi_row in school_pois_proj.iterrows():
            distance = school_buildings_proj.geometry.distance(poi_row.geometry)
            matched = school_buildings_proj[distance.le(SCHOOL_CAMPUS_MATCH_DISTANCE_M)].copy()
            if not matched.empty:
                used_building_index.update(matched.index.tolist())
                campus_geom = matched.geometry.union_all().buffer(SCHOOL_CAMPUS_BUFFER_M)
            else:
                campus_geom = poi_row.geometry.buffer(40.0)
            campuses.append({
                "name": str(school_pois.loc[poi_idx].get("name", "") or "school_campus"),
                "geometry": campus_geom,
            })

    unmatched = school_buildings.drop(index=list(used_building_index), errors="ignore")
    if not unmatched.empty:
        unmatched_proj = unmatched.to_crs(3857)
        explicit_mask = unmatched_proj["building_tag"].map(normalize_text).isin(SCHOOL_BUILDINGS) | name_contains(unmatched["name_clean"], {"school", "academy", "elementary", "middle school", "high school", "university", "college"})
        for idx, row in unmatched_proj[explicit_mask].iterrows():
            campuses.append({
                "name": str(unmatched.loc[idx].get("name_clean", "") or f"school_{idx}"),
                "geometry": row.geometry.buffer(10.0),
            })

    campuses_gdf = gpd.GeoDataFrame(campuses, geometry="geometry", crs="EPSG:3857") if campuses else gpd.GeoDataFrame(columns=["name", "geometry"], geometry="geometry", crs="EPSG:3857")
    if campuses_gdf.empty:
        return campuses_gdf.to_crs("EPSG:4326")
    campuses_gdf["category"] = "school"
    campuses_gdf = campuses_gdf.to_crs("EPSG:4326")
    campuses_gdf = campuses_gdf[campuses_gdf.geometry.notnull() & ~campuses_gdf.geometry.is_empty]
    return campuses_gdf


def load_first_existing_layer(paths: list[Path]) -> gpd.GeoDataFrame | None:
    for path in paths:
        if path.exists():
            return read_layer(path)
    return None


def parcel_category_from_row(row: pd.Series) -> str:
    landuse = normalize_text(row.get("LandUse", row.get("landuse", "")))
    zoning = normalize_text(row.get("Zoning", row.get("zoning", "")))
    use_code = normalize_text(row.get("UseCode", row.get("use_code", "")))

    if any(token in landuse for token in ["res", "single", "multi", "mobile"]) or any(token in zoning for token in ["res", "sf", "mf"]):
        return "house"
    if any(token in landuse for token in ["school", "education"]) or any(token in use_code for token in ["school", "college", "university"]):
        return "school"
    if any(token in landuse for token in ["hospital", "clinic", "medical"]) or any(token in use_code for token in ["medical", "hospital", "clinic"]):
        return "healthcare"
    if any(token in landuse for token in ["government", "civic", "public"]) or any(token in zoning for token in ["gov", "civic"]):
        return "government"
    if any(token in landuse for token in ["commercial", "retail", "office", "industrial"]) or any(token in zoning for token in ["com", "ind"]):
        return "business"
    return ""


def apply_parcel_refinement(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    parcels = load_first_existing_layer(PARCEL_LAYER_CANDIDATES)
    if parcels is None or parcels.empty:
        print("No parcel layer found; skipping parcel refinement.")
        return buildings

    parcel_fields = [field for field in ["LandUse", "landuse", "Zoning", "zoning", "UseCode", "use_code"] if field in parcels.columns]
    if not parcel_fields:
        print("Parcel layer does not expose usable classification fields; skipping parcel refinement.")
        return buildings

    unknown_mask = buildings["category"].eq("unknown")
    if not unknown_mask.any():
        return buildings

    parcel_data = parcels[parcel_fields + ["geometry"]].copy()
    building_unknowns = buildings.loc[unknown_mask].to_crs(3857)
    parcel_data = parcel_data.to_crs(3857)

    joined = gpd.sjoin(building_unknowns[["geometry"]], parcel_data, how="left", predicate="within")
    if joined.empty:
        print("Parcel refinement found no building overlaps.")
        return buildings

    joined = joined.loc[~joined.index.duplicated(keep="first")]
    joined["parcel_category"] = joined.apply(parcel_category_from_row, axis=1)
    refined = joined[joined["parcel_category"].ne("")]["parcel_category"]
    if refined.empty:
        print("Parcel refinement did not promote any buildings.")
        return buildings

    buildings.loc[refined.index, "category"] = refined
    print(f"Parcel refinement promoted {len(refined)} buildings.")
    return buildings


def promote_target_shelters(buildings: gpd.GeoDataFrame, pois: gpd.GeoDataFrame, target_count: int = SHELTER_TARGET_COUNT) -> gpd.GeoDataFrame:
    explicit = buildings[buildings["category"].eq("shelter")].copy()
    remaining_needed = max(0, int(target_count) - len(explicit))
    if remaining_needed <= 0:
        return buildings

    pois_name = pois["name"] if "name" in pois.columns else pd.Series([""] * len(pois), index=pois.index)
    shelter_poi_keywords = {"shelter", "salvation army", "red cross", "warming center", "warming centre"}
    shelter_pois = pois[pois["category"].eq("shelter") | name_contains(pois_name, shelter_poi_keywords)]
    if shelter_pois.empty:
        return buildings

    candidates = buildings[buildings["category"].eq("unknown")].copy()
    if candidates.empty:
        return buildings

    candidate_proj = candidates.to_crs(3857)
    shelter_pois_proj = shelter_pois.to_crs(3857)
    joined = gpd.sjoin_nearest(
        candidate_proj[["geometry", "name_clean", "building_tag"]],
        shelter_pois_proj[["geometry"]],
        how="left",
        max_distance=200.0,
        distance_col="shelter_distance_m",
    )
    joined = joined[joined["index_right"].notna()].copy()
    if joined.empty:
        return buildings

    joined["score"] = 0.0
    joined.loc[joined["shelter_distance_m"].le(30.0), "score"] += 3.0
    joined.loc[joined["shelter_distance_m"].le(60.0), "score"] += 2.0
    joined.loc[joined["shelter_distance_m"].le(120.0), "score"] += 1.0
    joined.loc[name_contains(joined["name_clean"], {"church", "chapel", "cathedral", "mosque", "synagogue", "mission", "community", "center", "centre", "ymca"}), "score"] += 2.0
    joined.loc[layer_mask_by_values(joined["building_tag"], {"church", "chapel", "cathedral", "mosque", "synagogue", "religious"}), "score"] += 2.0

    selected = joined.sort_values(["score", "shelter_distance_m"], ascending=[False, True]).head(remaining_needed)
    if not selected.empty:
        buildings.loc[selected.index, "category"] = "shelter"
        print(f"Promoted {len(selected)} additional shelter candidates toward target {target_count}.")
    return buildings


def main() -> None:
    buildings = read_layer(RAW_DIR / "osm_buildings.geojson")
    pois = read_layer(RAW_DIR / "osm_pois.geojson")
    landuse_path = RAW_DIR / "osm_landuse.geojson"
    landuse = read_layer(landuse_path) if landuse_path.exists() else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    building_tag = first_nonempty_series(buildings, ["building"])
    building_name = first_nonempty_series(buildings, ["name"])

    buildings = buildings.copy()
    buildings["building_tag"] = building_tag
    buildings["name_clean"] = building_name
    buildings["landuse_tag"] = ""

    if not landuse.empty:
        landuse_small = landuse[["geometry"]].copy()
        landuse_small["landuse_tag"] = first_nonempty_series(landuse, ["landuse"])
        joined = gpd.sjoin(buildings, landuse_small, how="left", predicate="within")
        if "landuse_tag_left" in joined.columns and "landuse_tag_right" in joined.columns:
            joined["landuse_tag"] = joined["landuse_tag_left"].fillna(joined["landuse_tag_right"]).fillna("")
            joined = joined.drop(columns=[c for c in ["landuse_tag_left", "landuse_tag_right", "index_right"] if c in joined.columns])
        elif "landuse_tag_right" in joined.columns:
            joined["landuse_tag"] = joined["landuse_tag_right"].fillna("")
            joined = joined.drop(columns=[c for c in ["landuse_tag_right", "index_right"] if c in joined.columns])
        buildings = joined

    building_norm = buildings["building_tag"].map(normalize_text)
    landuse_norm = buildings["landuse_tag"].map(normalize_text)
    building_area_m2 = geometry_area_m2(buildings)
    buildings["category"] = "unknown"

    house_mask = layer_mask_by_values(buildings["building_tag"], HOUSE_TYPES) | landuse_norm.isin(LANDUSE_HOUSE) | name_contains(buildings["name_clean"], HOUSE_NAME_KEYWORDS)
    school_mask = (
        building_norm.isin(SCHOOL_BUILDINGS)
        | landuse_norm.isin(LANDUSE_SCHOOL)
        | name_contains(buildings["name_clean"], {"school", "academy", "elementary", "middle school", "high school", "university", "college"})
    ) & ~building_norm.isin(NON_CAMPUS_BUILDINGS)
    healthcare_mask = building_norm.isin(HEALTHCARE_BUILDINGS) | name_contains(buildings["name_clean"], {"hospital", "clinic", "medical", "health", "urgent care"})
    government_mask = building_norm.isin(GOVERNMENT_BUILDINGS) | landuse_norm.isin(LANDUSE_GOV) | name_contains(buildings["name_clean"], {"city hall", "town hall", "county", "courthouse", "police", "fire"})
    shelter_mask = building_norm.isin(SHELTER_BUILDINGS) | name_contains(buildings["name_clean"], SHELTER_NAME_KEYWORDS)
    business_mask = building_norm.isin(BUSINESS_BUILDINGS) | landuse_norm.isin(LANDUSE_BUSINESS) | name_contains(buildings["name_clean"], {"store", "shop", "market", "office", "restaurant", "cafe", "bank", "plaza", "mall", "commercial", "retail", "industrial"})
    residential_unknown_mask = (
        buildings["category"].eq("unknown")
        & landuse_norm.isin(LANDUSE_HOUSE)
        & building_area_m2.le(RESIDENTIAL_UNKNOWN_AREA_THRESHOLD)
    )
    small_unknown_mask = (
        buildings["category"].eq("unknown")
        & building_area_m2.le(SMALL_BUILDING_AREA_THRESHOLD)
        & ~business_mask
        & ~school_mask
        & ~healthcare_mask
        & ~government_mask
        & ~shelter_mask
    )

    buildings.loc[business_mask, "category"] = "business"
    buildings.loc[house_mask, "category"] = "house"
    buildings.loc[school_mask, "category"] = "school"
    buildings.loc[healthcare_mask, "category"] = "healthcare"
    buildings.loc[government_mask, "category"] = "government"
    buildings.loc[shelter_mask, "category"] = "shelter"
    buildings.loc[residential_unknown_mask, "category"] = "house"
    buildings.loc[small_unknown_mask, "category"] = "house"

    pois = pois.copy()
    pois["amenity_tag"] = first_nonempty_series(pois, ["amenity"])
    pois["shop_tag"] = first_nonempty_series(pois, ["shop"])
    pois["office_tag"] = first_nonempty_series(pois, ["office"])
    pois["tourism_tag"] = first_nonempty_series(pois, ["tourism"])
    pois["leisure_tag"] = first_nonempty_series(pois, ["leisure"])
    pois["building_tag"] = first_nonempty_series(pois, ["building"])
    pois["category"] = "business"

    amenity_norm = pois["amenity_tag"].map(normalize_text)
    pois.loc[amenity_norm.isin(SCHOOL_AMENITIES), "category"] = "school"
    pois.loc[amenity_norm.isin(HEALTHCARE_AMENITIES), "category"] = "healthcare"
    pois.loc[amenity_norm.isin(SHELTER_AMENITIES), "category"] = "shelter"
    pois.loc[amenity_norm.isin(GOVERNMENT_AMENITIES), "category"] = "government"
    pois.loc[amenity_norm.isin(BUSINESS_AMENITIES), "category"] = "business"
    pois.loc[pois["shop_tag"].map(lambda x: normalize_text(x) != ""), "category"] = "business"
    pois.loc[pois["office_tag"].map(lambda x: normalize_text(x) != ""), "category"] = "business"
    pois.loc[name_contains(pois.get("name", pd.Series([""] * len(pois))), SHELTER_NAME_KEYWORDS), "category"] = "shelter"
    pois.loc[name_contains(pois.get("name", pd.Series([""] * len(pois))), HOUSE_NAME_KEYWORDS), "category"] = "business"

    buildings = promote_target_shelters(buildings, pois, target_count=SHELTER_TARGET_COUNT)

    school_poi_mask = pois["category"].eq("school")
    if school_poi_mask.any():
        school_candidates = buildings[
            buildings["category"].eq("unknown")
            & ~landuse_norm.isin(LANDUSE_HOUSE)
            & ~landuse_norm.isin(LANDUSE_BUSINESS)
            & ~landuse_norm.isin(LANDUSE_GOV)
        ]
        if not school_candidates.empty:
            candidate_proj = school_candidates.to_crs(3857)
            school_pois_proj = pois[school_poi_mask].to_crs(3857)
            if not school_pois_proj.empty:
                school_join = gpd.sjoin_nearest(
                    candidate_proj[["geometry"]],
                    school_pois_proj[["geometry"]],
                    how="left",
                    max_distance=SCHOOL_POI_DISTANCE_M,
                    distance_col="school_distance_m",
                )
                school_candidate_index = school_join.index[school_join["index_right"].notna()]
                buildings.loc[school_candidate_index, "category"] = "school"

    healthcare_poi_mask = pois["category"].eq("healthcare")
    if healthcare_poi_mask.any():
        healthcare_candidates = buildings[
            ~buildings["category"].eq("house")
            & ~buildings["category"].eq("school")
            & ~buildings["category"].eq("government")
            & ~buildings["category"].eq("shelter")
        ]
        if not healthcare_candidates.empty:
            candidate_proj = healthcare_candidates.to_crs(3857)
            healthcare_pois_proj = pois[healthcare_poi_mask].to_crs(3857)
            if not healthcare_pois_proj.empty:
                healthcare_join = gpd.sjoin_nearest(
                    candidate_proj[["geometry"]],
                    healthcare_pois_proj[["geometry"]],
                    how="left",
                    max_distance=HEALTHCARE_POI_DISTANCE_M,
                    distance_col="healthcare_distance_m",
                )
                healthcare_candidate_index = healthcare_join.index[healthcare_join["index_right"].notna()]
                buildings.loc[healthcare_candidate_index, "category"] = "healthcare"

    business_poi_mask = pois["category"].eq("business")
    if business_poi_mask.any():
        building_candidates = buildings[buildings["category"].eq("unknown") & ~landuse_norm.isin(LANDUSE_HOUSE)]
        if not building_candidates.empty:
            candidate_proj = building_candidates.to_crs(3857)
            business_pois_proj = pois[business_poi_mask].to_crs(3857)
            if not business_pois_proj.empty:
                proximity_join = gpd.sjoin_nearest(
                    candidate_proj[["geometry"]],
                    business_pois_proj[["geometry"]],
                    how="left",
                    max_distance=BUSINESS_POI_DISTANCE_M,
                    distance_col="poi_distance_m",
                )
                business_candidate_index = proximity_join.index[proximity_join["index_right"].notna()]
                buildings.loc[business_candidate_index, "category"] = "business"

    more_house_keywords = {"apartment", "apartments", "residence", "residential", "home", "house", "condo", "condominium", "dorm", "lodging", "inn", "hotel", "motel", "guest house"}
    more_school_keywords = {"school", "academy", "elementary", "middle school", "high school", "university", "college", "campus"}
    remaining_unknown = buildings["category"].eq("unknown")
    house_like = remaining_unknown & (
        landuse_norm.isin(LANDUSE_HOUSE)
        | name_contains(buildings["name_clean"], more_house_keywords)
        | building_area_m2.le(350.0)
    )
    school_like = remaining_unknown & (
        landuse_norm.isin(LANDUSE_SCHOOL)
        | name_contains(buildings["name_clean"], more_school_keywords)
    ) & ~building_norm.isin(NON_CAMPUS_BUILDINGS)
    business_like = remaining_unknown & ~(house_like | school_like)
    buildings.loc[house_like, "category"] = "house"
    buildings.loc[school_like, "category"] = "school"
    buildings.loc[business_like, "category"] = "business"

    buildings = apply_parcel_refinement(buildings)

    out_dir = PROCESSED_DIR
    save_gpkg(buildings, out_dir / "abm_places.gpkg", "buildings_all")
    save_gpkg(buildings[buildings["category"] == "house"], out_dir / "abm_places.gpkg", "houses")
    save_gpkg(buildings[buildings["category"] == "business"], out_dir / "abm_places.gpkg", "businesses")
    save_gpkg(buildings[buildings["category"] == "school"], out_dir / "abm_places.gpkg", "schools")
    save_gpkg(buildings[buildings["category"] == "healthcare"], out_dir / "abm_places.gpkg", "healthcare")
    save_gpkg(buildings[buildings["category"] == "shelter"], out_dir / "abm_places.gpkg", "shelters")
    save_gpkg(buildings[buildings["category"] == "government"], out_dir / "abm_places.gpkg", "government")
    save_gpkg(buildings[buildings["category"] == "unknown"], out_dir / "abm_places.gpkg", "buildings_unknown")

    save_gpkg(pois, out_dir / "abm_places.gpkg", "pois_all")
    save_gpkg(pois[pois["category"] == "house"], out_dir / "abm_places.gpkg", "pois_house")
    save_gpkg(pois[pois["category"] == "business"], out_dir / "abm_places.gpkg", "pois_business")
    save_gpkg(pois[pois["category"] == "school"], out_dir / "abm_places.gpkg", "pois_school")
    save_gpkg(pois[pois["category"] == "healthcare"], out_dir / "abm_places.gpkg", "pois_healthcare")
    save_gpkg(pois[pois["category"] == "shelter"], out_dir / "abm_places.gpkg", "pois_shelter")
    save_gpkg(pois[pois["category"] == "government"], out_dir / "abm_places.gpkg", "pois_government")

    save_geojson(buildings[["category", "building_tag", "name_clean", "geometry"]], out_dir / "buildings_classified.geojson")
    save_geojson(pois[["category", "amenity_tag", "shop_tag", "office_tag", "name", "geometry"]], out_dir / "pois_classified.geojson")

    school_campuses = build_school_campuses(buildings, pois)
    save_geojson(school_campuses, out_dir / "schools_campuses.geojson")

    print("Done.")


if __name__ == "__main__":
    main()