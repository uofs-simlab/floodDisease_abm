from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class FloodModuleBase:
    name = "base_flood"

    def step(self, model):
        pass


class FloodManager:
    """Container for flood modules with a single step entry point."""

    def __init__(self, modules):
        self.modules = modules or []

    def step(self, model):
        for m in self.modules:
            try:
                m.step(model)
            except Exception:
                logger.exception("Flood module %s failed at hour %s", getattr(m, "name", type(m).__name__), getattr(model, "hours", None))
                if bool(getattr(model, "strict_module_errors", False)):
                    raise


class RiverFloodModule(FloodModuleBase):
    """Flood-map timeline used by the current model."""

    name = "river_flood"

    def step(self, model):
        h = int(model.hours)

        # Activate and remove the single inundation footprint around the event.
        if model.enable_flood:
            flood_file = model.flood_file
            if h == int(model.flood_start_hour) and flood_file:
                model.add_flood_maps(flood_file)
            if h == int(model.flood_end_hour) and flood_file:
                model.remove_flood_maps(flood_file)

        # Stagnant hazard pools decay independently once they are spawned.
        if model.enable_stagnant and hasattr(model.space, "prune_expired_stagnant_areas"):
            model.space.prune_expired_stagnant_areas(now_hour=h)
