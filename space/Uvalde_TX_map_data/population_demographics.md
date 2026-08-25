# Uvalde Population And Demographic Defaults

This note maps the flood-disease ABM population fields to the closest available U.S. Census measures for the compact Uvalde AOI.

## Geography

- AOI file: `space/Uvalde_TX_map_data/uvalde_aoi.geojson`
- AOI area: about 60.3 square miles
- Reference populated place: Uvalde city, Texas
- Reference rural fringe: the low-density part of Uvalde County outside the city limits

The AOI is much larger than the city footprint, but the urban population is concentrated inside Uvalde city. A practical population estimate for the selected corridor is therefore the Uvalde city population plus a small rural fringe increment.

## Recommended Population Sizes

- Real-world AOI reference population: about 15,800 people
- Operational model default after housing augmentation: 15,455 people

Why two numbers:

- Census QuickFacts reports a July 1, 2025 population estimate of 15,455 for Uvalde city and 24,963 for Uvalde County.
- The AOI appears to contain essentially all of Uvalde city plus sparsely populated surrounding land, so a city-led estimate is appropriate.
- Raw OSM building coverage is sparse in this AOI: only 661 total building footprints were downloaded, with 281 classified houses.
- To support a city-scale Uvalde population, the house layer is augmented with synthetic residential units placed along developed local roads inside the AOI.
- The augmented target uses the Uvalde city population estimate of 15,455 and 2.83 persons per household, which implies about 5,461 residential units.
- If the house inventory is refined later with parcels or denser building footprints, `N_persons` should be raised toward the real-world AOI estimate.

## Model-Ready Defaults

These are the values now used as the Uvalde runtime preset.

| Model field | Recommended value | Source or rationale |
| --- | ---: | --- |
| `N_persons` | 15,455 | Uvalde city July 1, 2025 population estimate |
| `male_share_pct` | 51.1 | Uvalde city ACS / Census Reporter sex split |
| `female_share_pct` | 48.9 | Uvalde city ACS / Census Reporter sex split |
| `age_0_14_pct` | 22.0 | Derived from city age bands: `0-9` plus half of `10-19` |
| `age_15_64_pct` | 60.8 | Residual after `0-14` and `65+` |
| `age_65_100_pct` | 17.2 | Uvalde city QuickFacts 65+ share |
| `ethnicity_white_pct` | 17.5 | White alone, not Hispanic or Latino |
| `ethnicity_black_pct` | 0.4 | Black alone |
| `ethnicity_hispanic_pct` | 78.3 | Hispanic or Latino |
| `ethnicity_other_pct` | 3.8 | Remainder to 100 after the three fields above |
| `perc_education_people` | 0.73 | High school graduate or higher, age 25+ |
| worldview mix | 25 / 25 / 25 / 25 | No Census analogue in the current model |

## Fields The Model Still Treats Heuristically

- House locations are partially synthetic because OSM building coverage is incomplete for the AOI.
- School campuses are normalized into a separate campus layer so the model does not treat every school outbuilding as a separate school.
- Wealth class is still assigned with fixed internal shares in `agents/_personAssign.py`.
- Vehicle ownership is still assigned from wealth class and age, not from a Census vehicle-availability table.
- Worldview categories are conceptual model inputs, not Census demographic fields.

## Sources

- U.S. Census Bureau QuickFacts: Uvalde city, Texas; Uvalde County, Texas
- Census Reporter profile for Uvalde city, Texas using ACS 2024 5-year estimates
- Census Reporter profile for Uvalde County, Texas using ACS 2024 5-year estimates