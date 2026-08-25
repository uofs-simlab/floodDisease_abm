"""Geospatial study area used by the flood-disease ABM."""

from agents._shelter import Shelter
from agents._healthcare import Healthcare
from agents._house import House
from agents._school import School
from agents._government import Government
from agents._business import Business
import mesa_geo as mg
import geopandas as gpd
from pathlib import Path
from shapely.affinity import scale as scale_geometry
from shapely.geometry import Point, box
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree
import random
import math
import hashlib


_GPKG_LAYER_BY_ATTR = {
    "houses": "houses",
    "businesses": "businesses",
    "schools": "schools",
    "shelter": "shelters",
    "healthcare": "healthcare",
    "government": "government",
}

        
class StudyArea(mg.GeoSpace):
    def __init__(self, model, houses_file, businesses_file, schools_file, shelter_file, healthcare_file, government_file, crs) -> None:
        super().__init__(crs=crs)
        self.model = model
        
        # Initialize the layer lists used by the model.
        attributes = ["houses", "businesses", "schools", "healthcare", "shelter", "government", "flood_areas"]
        for attr in attributes:
            setattr(self, attr, [])
        
        self.data_crs = "EPSG:4269"  # Input CRS used in QGIS.
        self._flood_agents_cache = {}
        self._active_flood_file = None
        self._active_flood_geometry = None
        self._active_flood_prepared = None
        self._active_flood_tree = None
        self._flood_depth_cache_hour = None
        self._flood_depth_cache = {}
        
        # Load place-based agents from the GIS layers.
        self._load_entity_agents_from_file(model, houses_file, House, "houses", crs)
        self._load_entity_agents_from_file(model, businesses_file, Business, "businesses", crs)
        self._load_entity_agents_from_file(model, schools_file, School, "schools", crs)
        self._load_entity_agents_from_file(model, shelter_file, Shelter, "shelter", crs)
        self._load_entity_agents_from_file(model, healthcare_file, Healthcare, "healthcare", crs)
        self._load_entity_agents_from_file(model, government_file, Government, "government", crs)
        
        self.stagnant_areas = []
    

    def _load_entity_agents_from_file(self, model, file_path, agent_class, attr_name, crs):
        layer_name = _GPKG_LAYER_BY_ATTR.get(attr_name)
        if str(file_path).lower().endswith(".gpkg") and layer_name:
            gdf = gpd.read_file(file_path, layer=layer_name)
        else:
            gdf = gpd.read_file(file_path)
        if gdf.crs is None:
            gdf = gdf.set_crs(self.data_crs)  # Fallback only.
        gdf = gdf.to_crs(crs)
        gdf = gdf[gdf.geometry.notnull() & gdf.is_valid & ~gdf.geometry.is_empty]
        # Use globally unique, type-prefixed IDs so entity IDs never collide with
        # person IDs or IDs from other GIS layers in GeoSpace internals.
        gdf.index = [f"{attr_name}_{i}" for i in range(len(gdf))]
        gdf.index.name = "unique_id"
        agent_creator = mg.AgentCreator(agent_class, model=model)
        agents = agent_creator.from_GeoDataFrame(gdf)
        getattr(self, attr_name).extend(agents)
        self.add_agents(agents)
        # print(f"{attr_name}: crs={gdf.crs}, n={len(gdf)}, bounds={gdf.total_bounds}")
        
        
    def _mask_critical_facilities(self, gdf, model):
        """Remove flood coverage at shelters and healthcare facilities."""
        clearance_m = max(
            0.0,
            float(model.flood_critical_facility_clearance_m),
        )
        critical_geometries = [
            agent.geometry
            for layer_name in ("shelter", "healthcare")
            for agent in getattr(self, layer_name, [])
            if getattr(agent, "geometry", None) is not None
            and not agent.geometry.is_empty
        ]
        if not critical_geometries:
            return gdf

        critical_area = unary_union(critical_geometries)
        if clearance_m > 0.0:
            critical_area = critical_area.buffer(clearance_m)
        if critical_area.is_empty:
            return gdf

        masked = gdf.copy()
        masked["geometry"] = masked.geometry.difference(critical_area)
        return masked[masked.geometry.notnull() & masked.is_valid & ~masked.geometry.is_empty].copy()


    def _build_flood_agents_from_file(self, model, flood_file, crs):
        gdf = gpd.read_file(flood_file)
        if gdf.crs is None:
            gdf = gdf.set_crs(self.data_crs)
        gdf = gdf.to_crs(crs)
        gdf = gdf[gdf.geometry.notnull() & gdf.is_valid & ~gdf.geometry.is_empty]

        bounds = self.total_bounds
        if bounds is not None and not gdf.empty:
            minx, miny, maxx, maxy = bounds
            pad = float(model.flood_clip_padding_m)
            map_extent = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
            gdf = gdf[gdf.geometry.intersects(map_extent)].copy()
            if not gdf.empty:
                gdf["geometry"] = gdf.geometry.intersection(map_extent)
                gdf = gdf[gdf.geometry.notnull() & gdf.is_valid & ~gdf.geometry.is_empty]
        if gdf.empty:
            return []

        # Critical facilities remain flood-free in both the map and hazard queries.
        gdf = self._mask_critical_facilities(gdf, model)
        if gdf.empty:
            return []
    
        # Try to use a depth column if the flood file provides one.
        depth_col = None
        for cand in ["depth", "DEPTH", "Depth", "depth_m", "DEPTH_M", "water_depth", "WDEP"]:
            if cand in gdf.columns:
                depth_col = cand
                break
    
        simplify_tol = float(model.flood_simplify_tolerance_m)
        max_pieces = max(1, int(model.flood_max_visual_polygons))
        pieces = []
        for geom in gdf.geometry.explode(index_parts=False):
            if geom is None or geom.is_empty:
                continue
            simplified = geom.simplify(simplify_tol, preserve_topology=True).buffer(0)
            if simplified.is_empty:
                continue
            if hasattr(simplified, "geoms"):
                pieces.extend([piece for piece in simplified.geoms if not piece.is_empty])
            else:
                pieces.append(simplified)
        if len(pieces) > max_pieces:
            pieces = sorted(pieces, key=lambda geom: geom.area, reverse=True)[:max_pieces]

        default_depth_m = float(model.flood_depth_default_m)
        variation_depth_m = float(model.flood_depth_variation_m)
        file_name = Path(str(flood_file)).name
        minx, miny, maxx, maxy = gdf.total_bounds
        direction = str(model.flood_wave_direction)
        if direction == "southeast_to_northwest":
            source = (maxx, miny)
            target = (minx, maxy)
        elif direction == "north_to_south":
            source = ((minx + maxx) / 2.0, maxy)
            target = ((minx + maxx) / 2.0, miny)
        elif direction == "east_to_west":
            source = (maxx, (miny + maxy) / 2.0)
            target = (minx, (miny + maxy) / 2.0)
        else:
            source = (minx, miny)
            target = (maxx, maxy)
        direction_x = target[0] - source[0]
        direction_y = target[1] - source[1]
        direction_len_sq = max(1.0, direction_x * direction_x + direction_y * direction_y)
        agents = []
        for idx, piece in enumerate(pieces):
            a = FloodInundationArea(model, piece, crs)
            a.flood_file = flood_file
            a.unique_id = f"flood_{file_name}_{idx}"
    
            # Stable per-polygon depth in meters.
            if depth_col is not None:
                # Approximate by the median depth of intersecting features.
                sel = gdf[gdf.geometry.intersects(piece)]
                if not sel.empty:
                    try:
                        a.depth_m = float(sel[depth_col].median())
                    except Exception:
                        a.depth_m = default_depth_m
                else:
                    a.depth_m = default_depth_m
            else:
                a.depth_m = default_depth_m
    
            agents.append(a)
            a.base_depth = float(a.depth_m if depth_col is not None else default_depth_m)
            a.var_depth = variation_depth_m
            a.noise_seed = int.from_bytes(
                hashlib.sha256(f"{a.geometry.wkt[:500]}|{file_name}".encode("utf-8")).digest()[:4],
                "big",
            )
            center = a.geometry.representative_point()
            projection = ((center.x - source[0]) * direction_x + (center.y - source[1]) * direction_y) / direction_len_sq
            a.wave_position = max(0.0, min(1.0, projection))
            a.wave_enabled = bool(model.flood_wave_enabled)
            a.wave_start_hour = int(model.flood_start_hour)
            a.wave_rise_hours = float(model.flood_wave_rise_hours)
            a.wave_fall_hours = float(model.flood_wave_fall_hours)
            a.wave_peak_hour = int(model.flood_wave_peak_hour)

        return agents


    def add_flood_maps(self, model, flood_file, crs):
        flood_key = str(flood_file or "").strip()
        if not flood_key or flood_key == self._active_flood_file:
            return
        agents = self._flood_agents_cache.get(flood_key)
        if agents is None:
            agents = self._build_flood_agents_from_file(model, flood_key, crs)
            self._flood_agents_cache[flood_key] = agents
        self.add_agents(agents)
        for agent in agents:
            if agent not in self.flood_areas:
                self.flood_areas.append(agent)
        self._active_flood_file = flood_key
        self._refresh_active_flood_geometry()


    def _refresh_active_flood_geometry(self) -> None:
        geoms = [a.geometry for a in self.flood_areas]
        self._active_flood_geometry = unary_union(geoms).buffer(0) if geoms else None
        self._active_flood_prepared = prep(self._active_flood_geometry) if self._active_flood_geometry is not None else None
        self._active_flood_tree = STRtree(geoms) if geoms else None
        self._flood_depth_cache_hour = None
        self._flood_depth_cache.clear()


    def _load_flood_maps_from_file(self, model, flood_file, crs):
        self.add_flood_maps(model, flood_file, crs)

            
    def remove_flood_maps(self, flood_file: str) -> None:
        flood_key = str(flood_file or "").strip()
        if not flood_key:
            return
        to_remove = [a for a in getattr(self, "flood_areas", [])
                     if getattr(a, "flood_file", None) == flood_key]
        for a in to_remove:
            try:
                self.remove_agent(a)
            except Exception:
                pass
            if a in self.flood_areas:
                self.flood_areas.remove(a)
        if self._active_flood_file == flood_key:
            self._active_flood_file = None
        self._refresh_active_flood_geometry()

    
    def get_flood_height_at_position(self, pt):
        if pt is None:
            return 0.0
        hours = self.model.hours
        if self._flood_depth_cache_hour != hours:
            self._flood_depth_cache_hour = hours
            self._flood_depth_cache.clear()
        try:
            cache_key = tuple(round(float(value), 3) for value in pt.bounds)
        except Exception:
            return 0.0
        cached = self._flood_depth_cache.get(cache_key)
        if cached is not None:
            return cached
        if self._active_flood_prepared is None or not self._active_flood_prepared.intersects(pt):
            self._flood_depth_cache[cache_key] = 0.0
            return 0.0
        mult  = float(self.model.flood_depth_multiplier)
        hmax = 0.0
        candidate_indices = (
            self._active_flood_tree.query(pt, predicate="intersects")
            if self._active_flood_tree is not None else range(len(self.flood_areas))
        )
        for index in candidate_indices:
            fa = self.flood_areas[int(index)]
            try:
                if not fa.geometry.contains(pt):
                    continue
            except Exception:
                continue
            d = 0.0
            try:
                # Prefer the per-area method if present.
                d = float(fa.depth_at(pt, hours=hours) or 0.0)
            except Exception:
                d = 0.0
            # Fallback: if the point is inside the polygon, assume shallow water.
            try:
                if (d <= 0.0) and fa.geometry.contains(pt):
                    mean_d = float(getattr(fa, "mean_depth", 0.0) or 0.0)
                    d = max(0.15, mean_d)
            except Exception:
                pass
            d *= mult
            if d > hmax:
                hmax = d
        self._flood_depth_cache[cache_key] = hmax
        return hmax

    def intersects_active_flood(self, geometry) -> bool:
        """Test a geometry against the prepared active flood footprint."""
        if geometry is None or self._active_flood_prepared is None:
            return False
        try:
            return bool(self._active_flood_prepared.intersects(geometry))
        except Exception:
            return False

    
    
    def max_depth_within_radius(self, geometry, radius_m: float) -> float:
        try:
            center = geometry.representative_point() if hasattr(geometry, "representative_point") else geometry
            buf = center.buffer(float(radius_m))
        except Exception:
            return 0.0
    
        hours = self.model.hours
        max_depth = 0.0
        for fa in self.flood_areas:
            try:
                if fa.geometry.intersects(buf):
                    # Sample at the center for speed.
                    d = fa.depth_at(center, hours=hours)
                    if d > max_depth:
                        max_depth = d
            except Exception:
                continue
        return max_depth

    
    def move_agent(self, agent, new_position):
        # Normalize to a shapely Point.
        if hasattr(new_position, "geometry"):
            new_point = new_position.geometry
        else:
            new_point = new_position
        if not isinstance(new_point, Point):
            raise ValueError("new_position must be a shapely Point or an object with .geometry as Point")
    
        # Remove from the GeoSpace index without calling our own override.
        try:
            super(StudyArea, self).remove_agent(agent)
        except Exception:
            pass
    
        # Update geometry.
        agent.geometry = new_point
    
        # Re-add so the spatial index is refreshed.
        super(StudyArea, self).add_agents([agent])



    @property
    def total_bounds(self):
        # Union bounds over the loaded place layers.
        layers = (self.houses + self.businesses + self.schools +
                  self.healthcare + self.shelter + self.government)
        if not layers:
            return None
        xs, ys = [], []
        for a in layers:
            minx, miny, maxx, maxy = a.geometry.bounds
            xs += [minx, maxx]; ys += [miny, maxy]
        return (min(xs), min(ys), max(xs), max(ys))


    def add_stagnant_from_flood_file(self, model, flood_file, crs, spawn_hour: int):
        active_geoms = [
            a.geometry for a in getattr(self, "flood_areas", [])
            if getattr(a, "flood_file", None) == str(flood_file or "").strip() and getattr(a, "geometry", None) is not None
        ]
        gdf = None
        if active_geoms:
            source_geoms = active_geoms
        else:
            gdf = gpd.read_file(flood_file)
            if gdf.crs is None: gdf = gdf.set_crs(self.data_crs)
            gdf = gdf.to_crs(crs)
            gdf = gdf[gdf.geometry.notnull() & gdf.is_valid & ~gdf.geometry.is_empty]

            bounds = self.total_bounds
            if bounds is not None and not gdf.empty:
                minx, miny, maxx, maxy = bounds
                pad = float(model.flood_clip_padding_m)
                map_extent = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
                gdf = gdf[gdf.geometry.intersects(map_extent)].copy()
                if not gdf.empty:
                    gdf["geometry"] = gdf.geometry.intersection(map_extent)
                    gdf = gdf[gdf.geometry.notnull() & gdf.is_valid & ~gdf.geometry.is_empty]
            if gdf.empty:
                return
            gdf = self._mask_critical_facilities(gdf, model)
            if gdf.empty:
                return
            source_geoms = list(gdf.geometry.explode(index_parts=False))
    
        # Random seed per run and flood file.
        base_seed = model.stagnant_seed
        if base_seed in (None, 0, "0", ""):
            base_seed = random.randrange(1 << 30)
        stable_file_seed = int.from_bytes(
            hashlib.sha256(str(flood_file).encode("utf-8")).digest()[:4],
            "big",
        )
        rng = random.Random(int(base_seed) ^ stable_file_seed ^ int(spawn_hour))
    
        # Tunable knobs pulled from the model or defaults.
        shrink_min = float(model.stagnant_shrink_min)
        shrink_max = float(model.stagnant_shrink_max)
        simplify_tol = float(model.stagnant_simplify_tolerance)
        min_area = float(model.stagnant_min_area)
        keep_frac = float(model.stagnant_keep_fraction)
        half_life_h = float(model.stagnant_half_life_h)
        infl_m = float(model.stagnant_influence_m)
        life_min_h = max(1.0, float(model.stagnant_lifetime_min_h))
        life_max_h = max(life_min_h, float(model.stagnant_lifetime_max_h))
        flood_area = float(unary_union(source_geoms).area)
        pool_area_fraction = max(0.0, min(1.0, float(model.stagnant_area_fraction)))
        max_pool_area = flood_area * pool_area_fraction
    
        # Favor deeper places when a depth column exists.
        depth_col = None
        if gdf is not None:
            for cand in ["depth", "DEPTH", "Depth", "depth_m", "DEPTH_M", "water_depth", "WDEP"]:
                if cand in gdf.columns:
                    depth_col = cand
                    break
        if depth_col:
            try:
                dmin = float(gdf[depth_col].quantile(0.1))
                dmax = float(gdf[depth_col].quantile(0.9))
                if dmax <= dmin: dmax = dmin + 1e-6
            except Exception:
                depth_col = None
    
        # Erode, simplify, and split the selected flood geometry. Keep this bounded
        # for interactive runs; the full Uvalde inundation layer is too detailed.
        max_bases = max(1, int(model.stagnant_max_source_polygons))
        bases = []
        for geom in source_geoms:
            if geom is None or geom.is_empty:
                continue
            simplified = geom.simplify(simplify_tol, preserve_topology=True).buffer(0)
            if simplified.is_empty:
                continue
            if hasattr(simplified, "geoms"):
                bases.extend([piece for piece in simplified.geoms if not piece.is_empty])
            else:
                bases.append(simplified)
        if len(bases) > max_bases:
            bases = sorted(bases, key=lambda geom: geom.area, reverse=True)[:max_bases]
    
        candidates = []
        people = list(model.people)
        for base in bases:
            # Random shrink per base yields varied puddle sizes each run.
            shrink = rng.uniform(shrink_min, shrink_max)
            puddle = base.buffer(-shrink).simplify(simplify_tol, preserve_topology=True)
            if puddle.is_empty:
                continue
    
            subs = list(puddle.geoms) if hasattr(puddle, "geoms") else [puddle]
            for sub in subs:
                if sub.is_empty or sub.area < min_area:
                    continue
                if rng.random() > keep_frac:
                    continue
    
                # Keep larger and deeper sub-polygons more often.
                if depth_col:
                    try:
                        sel = gdf[gdf.geometry.intersects(sub)]
                        if not sel.empty:
                            dmed = float(sel[depth_col].median())
                            depth_w = min(1.0, max(0.0, (dmed - dmin) / (dmax - dmin)))
                        else:
                            depth_w = 0.5
                    except Exception:
                        depth_w = 0.5
                else:
                    depth_w = 0.5
    
                base_index = rng.uniform(0.6, 1.3) * (0.7 + 0.6 * depth_w)
    
                a = StagnantPoolArea(
                    model, sub, crs,
                    spawn_hour=spawn_hour,
                    base_index=base_index,
                    half_life_h=half_life_h,
                    influence_m=infl_m,
                    lifetime_h=rng.uniform(life_min_h, life_max_h),
                )
                population_score = sum(
                    1 for person in people
                    if getattr(person, "geometry", None) is not None
                    and sub.distance(person.geometry) <= infl_m
                )
                candidates.append((a, population_score))
    
        # A vectorborne run should always leave a visible source when the
        # inundation footprint contains at least one usable polygon. The
        # probabilistic filtering above can otherwise discard every candidate.
        if not candidates and bases:
            fallback_base = max(bases, key=lambda geom: geom.area)
            fallback_shrink = min(shrink_max, max(shrink_min, 0.05 * math.sqrt(fallback_base.area)))
            fallback = fallback_base.buffer(-fallback_shrink).buffer(0)
            if fallback.is_empty:
                fallback = fallback_base.buffer(-0.5 * fallback_shrink).buffer(0)
            if fallback.is_empty:
                fallback = fallback_base
            if not fallback.is_empty and fallback.area >= min_area:
                fallback_agent = StagnantPoolArea(
                    model, fallback, crs,
                    spawn_hour=spawn_hour,
                    base_index=1.0,
                    half_life_h=half_life_h,
                    influence_m=infl_m,
                    lifetime_h=life_max_h,
                )
                candidates.append((fallback_agent, 0))

        if candidates:
            max_spots = max(1, int(model.stagnant_max_spots_per_wave))
            # Prefer population-relevant candidates, but retain random variation
            # and enforce spatial separation so all pools do not overlap one area.
            candidates.sort(key=lambda item: (item[1] + rng.random() * 2.0), reverse=True)
            agents = []
            pool_radius = math.sqrt(max_pool_area / max(1, max_spots) / math.pi) if max_pool_area > 0.0 else 0.0
            separation_m = max(25.0, infl_m * 0.25, pool_radius * 1.5)
            for candidate, _score in candidates:
                center = candidate.geometry.representative_point()
                if all(center.distance(existing.geometry.representative_point()) >= separation_m for existing in agents):
                    agents.append(candidate)
                if len(agents) >= max_spots:
                    break
            if not agents:
                agents = [candidates[0][0]]

            # Represent each selected location as a compact local pool. This
            # prevents a connected flood polygon from becoming one giant pool.
            if max_pool_area > 0.0:
                target_area = max_pool_area / max(1, len(agents))
                flood_union = unary_union(source_geoms)
                target_radius = math.sqrt(target_area / math.pi)
                for agent in agents:
                    center = agent.geometry.representative_point()
                    compact = center.buffer(target_radius).intersection(flood_union).buffer(0)
                    if compact.is_empty:
                        compact = scale_geometry(
                            agent.geometry,
                            xfact=math.sqrt(target_area / max(float(agent.geometry.area), 1e-9)),
                            yfact=math.sqrt(target_area / max(float(agent.geometry.area), 1e-9)),
                            origin="centroid",
                        ).buffer(0)
                    if not compact.is_empty:
                        if compact.area > target_area:
                            compact = scale_geometry(
                                compact,
                                xfact=math.sqrt(target_area / compact.area),
                                yfact=math.sqrt(target_area / compact.area),
                                origin="centroid",
                            ).buffer(0)
                        agent.geometry = compact
            for index, agent in enumerate(agents):
                agent.unique_id = f"stagnant_{int(spawn_hour)}_{index}"
            self.add_agents(agents)
            self.stagnant_areas.extend(agents)

    def get_stagnant_hazard_at_position(self, pt):
        if pt is None:
            return 0.0
        now = int(self.model.hours)
        hmax = 0.0
        for sa in self.stagnant_areas:
            try:
                h = float(sa.hazard_at(pt, hours=now) or 0.0)
            except Exception:
                h = 0.0
            if h > hmax:
                hmax = h
        return max(0.0, hmax)

    def prune_expired_stagnant_areas(self, now_hour: int | None = None) -> None:
        now = int(self.model.hours if now_hour is None else now_hour)
        survivors = []
        for sa in self.stagnant_areas:
            try:
                expired = bool(sa.is_expired(now))
            except Exception:
                expired = False
            if expired:
                try:
                    self.remove_agent(sa)
                except Exception:
                    pass
            else:
                survivors.append(sa)
        self.stagnant_areas = survivors



class FloodInundationArea(mg.GeoAgent):
    def __init__(self, *args, **kwargs):
        """
        Accept either (model, geometry, crs) OR (unique_id, model, geometry, crs),
        and also tolerate kwargs like unique_id=...
        """
        unique_id = kwargs.get("unique_id", None)

        if kwargs:
            model = kwargs.get("model")
            geometry = kwargs.get("geometry")
            crs = kwargs.get("crs")
        elif len(args) == 3:
            model, geometry, crs = args
        elif len(args) == 4:
            unique_id, model, geometry, crs = args
        else:
            raise TypeError(
                "FloodInundationArea expects (model, geometry, crs) or (unique_id, model, geometry, crs)"
            )

        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            try:
                super().__init__(model, geometry, crs)
            except TypeError:
                super().__init__(unique_id, model, geometry, crs)

        if unique_id is not None:
            self.unique_id = unique_id
            
        
    def depth_at(self, pt, hours=None, time_bucket_hours=6):
        now = int(hours if hours is not None else getattr(self.model, "hours", 0))
        if bool(getattr(self, "wave_enabled", False)):
            start = float(getattr(self, "wave_start_hour", 0)) + float(getattr(self, "wave_position", 0.0)) * float(getattr(self, "wave_rise_hours", 1.0))
            peak = float(getattr(self, "wave_peak_hour", start + 1.0))
            fall = float(getattr(self, "wave_fall_hours", 1.0))
            if now < start:
                return 0.0
            if now < peak:
                envelope = min(1.0, max(0.0, (now - start) / max(1.0, peak - start)))
            else:
                envelope = min(1.0, max(0.0, 1.0 - (now - peak) / max(1.0, fall)))
            if envelope <= 0.0:
                return 0.0
        else:
            envelope = 1.0

        # Stable coord bucket to avoid tiny sub-pixel flips.
        x = int(pt.x * 1.0)   # scale if your CRS is meters; you can use 0.5 or 2.0, etc.
        y = int(pt.y * 1.0)
        tb = 0 if hours is None else int(hours // max(1, time_bucket_hours))
        seed = (self.noise_seed ^ (x * 73856093) ^ (y * 19349663) ^ (tb * 83492791)) & 0xFFFFFFFF
    
        rng = random.Random(seed)
        # Zero-mean local offset in [−var/2, +var/2].
        offset = (rng.random() - 0.5) * self.var_depth
        return max(0.0, (self.base_depth + offset) * envelope)
    
    
class StagnantPoolArea(mg.GeoAgent):
    """Breeding hazard that decays with time and distance from polygon."""
    def __init__(self, model=None, geometry=None, crs=None, unique_id=None, *, spawn_hour: int, base_index: float,
                 half_life_h: float, influence_m: float, lifetime_h: float):
        try:
            super().__init__(model=model, geometry=geometry, crs=crs, unique_id=unique_id)
        except TypeError:
            try:
                super().__init__(model, geometry, crs)
            except TypeError:
                super().__init__(unique_id, model, geometry, crs)
        self.spawn_hour = int(spawn_hour)
        self.base_index = float(base_index)
        self.half_life_h = float(half_life_h)
        self.influence_m = float(influence_m)
        self.lifetime_h = float(lifetime_h)

    def hazard_at(self, pt, hours=None):
        if pt is None: return 0.0
        now = int(hours if hours is not None else getattr(self.model, "hours", 0))
        age_h = max(0, now - self.spawn_hour)
        if age_h > self.lifetime_h:
            return 0.0
        # temporal decay (half-life)
        time_mult = 0.0 if self.half_life_h <= 0 else (0.5 ** (age_h / self.half_life_h))
        # spatial decay: full inside, cosine taper to zero by influence_m outside
        try:
            if self.geometry.contains(pt):
                space_mult = 1.0
            else:
                d = self.geometry.exterior.distance(pt)
                if d >= self.influence_m:
                    space_mult = 0.0
                else:
                    x = max(0.0, min(1.0, d / self.influence_m))
                    space_mult = 0.5 * (1 + math.cos(math.pi * x))
        except Exception:
            space_mult = 0.0
        return max(0.0, self.base_index * time_mult * space_mult)

    def is_expired(self, hours=None):
        now = int(hours if hours is not None else getattr(self.model, "hours", 0))
        return (now - self.spawn_hour) > self.lifetime_h

    