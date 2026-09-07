# North America Lake Ice-Out Intelligence — Master Plan

## Product goal

Transform the existing LSPP Ice-Out Monitor into a continental lake ice-out intelligence system for the northern United States and Canada, ready for spring 2027.

The product must answer, for a selected lake:

1. Is the lake still ice covered now?
2. What percentage of the lake appears open water?
3. What is the probability the lake will be functionally ice-out by a selected date?
4. What is the most likely ice-out window?
5. What changed since the last observation?
6. Why is the forecast moving earlier or later?
7. How confident is the result and what evidence is stale or missing?

This is NOT an ice-safety product. Ice-out probability must never be represented as ice thickness, load-bearing safety, or permission to travel on ice.

## Product principle

Preserve the strongest parts of the current LSPP experience:

- map-first lake discovery
- date stepping
- historical imagery comparison
- MODIS / VIIRS imagery
- NDSI snow/ice interpretation
- lake-level probability readout
- simple plain-language status labels
- transparent provenance
- low-cost static/serverless delivery

Replace the current local Wawa-based empirical probability proxy with a continental, lake-specific hierarchical model.

## Public product name

Recommended display name: **Lake Ice-Out Forecast**

Supporting descriptor: **North American Lake Ice-Out Tracker**

Suggested URL family:

- `/national-tools/ice-out/`
- `/national-tools/ice-out/minnesota/`
- `/national-tools/ice-out/minnesota/lake-vermilion/`
- `/national-tools/ice-out/maine/moosehead-lake/`
- `/national-tools/ice-out/ontario/lake-nipissing/`
- `/national-tools/ice-out/quebec/<lake-slug>/`

The tool may live inside the existing national-tools infrastructure, but the product copy should explicitly say United States + Canada.

## Lake registry

Use a canonical lake registry rather than hard-coded arrays.

### Primary continental registry

HydroLAKES is the preferred cross-border backbone because it provides roughly 1.4 million lake/reservoir polygons >= 10 ha plus stable IDs and useful morphometry including:

- lake area
- shoreline length
- estimated average depth
- volume
- residence time
- elevation
- connected hydrologic identifiers

License: CC-BY 4.0. Attribution must be retained.

### National enrichment

United States:

- USGS 3D Hydrography Program / legacy NHD/NHDPlus crosswalks
- state lake names and official identifiers where available

Canada:

- NRCan National Hydro Network for national coverage
- migrate/enrich from Canadian Hydrospatial Network as coverage expands
- Open Government Licence attribution

### Canonical entity fields

Each lake record should contain at minimum:

- `lake_id`
- `hydrolakes_id`
- `country`
- `admin1` (state/province/territory)
- `name`
- `alternate_names[]`
- `centroid_lat`
- `centroid_lon`
- `polygon`
- `area_km2`
- `shoreline_km`
- `shoreline_development`
- `elevation_m`
- `avg_depth_m`
- `depth_source`
- `volume_mcm`
- `residence_time_days`
- `inflow_class`
- `outflow_class`
- `reservoir_flag`
- `historical_iceout_source_count`
- `historical_iceout_year_count`
- `historical_iceout_median_doy`
- `historical_iceout_p10_doy`
- `historical_iceout_p90_doy`
- `model_confidence_class`

## Evidence stack

Use the source hierarchy:

**Observed lake evidence -> observed regional weather/snow -> official forecast -> historical climatology -> derived model -> user-facing recommendation**

### Satellite observations

#### Tier 1 — lake surface classification

Use NASA Harmonized Landsat Sentinel-2 (HLS) where operationally practical.

Why:

- 30 m spatial resolution
- combined Landsat + Sentinel observations every ~2–3 days globally
- materially better for small and medium lakes than MODIS/VIIRS

Derive lake-surface classes from lake polygon pixels:

- open water
- snow/ice
- cloud
- shadow/invalid

Store:

- open-water fraction
- ice/snow fraction
- valid-observation fraction
- cloud fraction
- observation timestamp
- sensor
- quality flags

#### Tier 2 — daily continental context

NASA MODIS Terra/Aqua and VIIRS remain valuable because of their daily cadence.

Use:

- MOD10A1 / MOD10A1F
- MYD10A1 / MYD10A1F
- VIIRS Version 2 snow products such as VNP10A1F and JPSS equivalents

MODIS gives a daily record from 2000 at 500 m. VIIRS provides daily 375 m products. Gap-filled products include observation-age information and therefore must never be treated as a fresh observation without checking pixel age.

#### Tier 3 — optional microwave large-lake signal

For sufficiently large lakes, evaluate passive-microwave lake-ice products as a cloud-independent secondary signal. Do not use 5 km microwave products for small lakes.

## Historical ice-out labels

### Direct observed labels

Seed the model with authoritative histories where available.

Sources include:

- NSIDC Global Lake and River Ice Phenology Database
- Minnesota DNR lake ice-out histories
- Maine DACF ice-out histories
- other state/provincial/territorial agencies where licensing and definitions are suitable
- long-running lake associations only when provenance is clear

Every label must retain:

- source
- source URL or dataset ID
- observation definition
- year
- date
- confidence / provenance class

Important: ice-out definitions vary by source. Do not erase that distinction. Preserve a definition code such as:

- `OPEN_WATER_COMPLETE`
- `NAVIGABLE_END_TO_END`
- `PERCENT_OPEN_90`
- `LOCAL_OBSERVER_CONSISTENT`

### Satellite-derived historical labels

For lakes with no direct history, backfill historical ice-out labels using HLS/Landsat/MODIS/VIIRS time series over the lake polygon.

Derived label concept:

`ice_out_date = first date when open_water_fraction >= threshold and remains above persistence rule, subject to observation quality`

Example persistence rule:

- >= 90% open water on a valid observation
- followed by no return to material ice cover on subsequent valid observations

Use a lake-specific uncertainty interval when clouds create an observation gap.

## Weather and cryosphere features

### Historical / climatology

Use ERA5-Land for retrospective model training and climatology.

Candidate variables:

- hourly / daily 2 m temperature
- accumulated thawing degree days
- freezing degree days from autumn/winter
- snow depth
- snowfall / precipitation
- rainfall during thaw
- wind speed
- solar radiation
- surface pressure where useful

### Operational forecast — United States

Primary:

- NWS API / NBM-derived grid forecast where practical

Continental fallback / longer horizon:

- NOAA GFS
- GEFS for probabilistic spread if operational budget permits

### Operational forecast — Canada

Primary short range:

- ECCC HRDPS ~2.5 km, 48 h, four runs/day
- HRDPS-North where northern-domain coverage is needed

Land/snow enrichment:

- ECCC HRDLPS where useful

Longer-range fallback:

- GDPS / GFS

## Model design

The production model should be hierarchical so it performs for both data-rich and data-poor lakes.

### Layer A — lake climatology prior

Estimate a baseline ice-out distribution using:

- latitude
- longitude / climate region
- elevation
- area
- average depth
- volume
- shoreline complexity
- inflow/outflow indicators
- reservoir flag
- long-term temperature / snow climatology
- direct historical ice-out observations where available
- nearby calibrated lakes

Output:

- baseline median ice-out DOY
- baseline p10 / p90 window
- climatology confidence

### Layer B — current-season winter severity

Update the prior with current-season conditions:

- accumulated freezing degree days
- snowpack / snow depth anomaly
- winter mean temperature anomaly
- recent snow events
- inferred ice/snow surface state from satellite

### Layer C — spring melt trajectory

Core predictors:

- accumulated thawing degree days
- recent 3/7/14-day temperature means
- forecast thaw degree days
- rainfall on snow/ice
- wind exposure
- solar radiation
- snow depletion around/on lake
- trend in satellite open-water fraction

The accumulated thawing-degree-day method has a long scientific history for lake breakup prediction and should be a first-class interpretable feature, not a hidden incidental variable.

### Layer D — direct satellite assimilation

As valid lake observations arrive, they should increasingly dominate the forecast.

Examples:

- 0–5% open water: climatology + weather still dominate
- 5–30% open water: active breakup regime; increase satellite weight
- 30–70%: satellite trend dominates date estimate
- >70% valid open water: short-horizon forecast becomes strongly observational
- >=90% with persistence: classify as ice-out according to the selected functional definition

### Model family

Start interpretable and benchmark more complex models against it.

Baseline:

- survival / time-to-event model or logistic daily hazard model

Candidate challengers:

- gradient boosted trees (XGBoost / LightGBM)
- calibrated ensemble of survival model + boosted trees

Do NOT ship a black-box model unless it materially beats the interpretable baseline in out-of-sample calibration and date error.

## Probability outputs

Do not expose a single unsupported percentage.

For each lake return:

- probability ice-out by today
- probability ice-out by user-selected date
- most likely ice-out date
- 50% date
- 85% conservative date
- likely window (e.g. 20–80% or 10–90%)
- confidence score
- confidence reason
- latest valid satellite observation
- current open-water estimate
- direction of change since previous valid observation

## Confidence model

Confidence is separate from probability.

Suggested components:

- historical label depth
- lake morphology quality
- satellite observation recency
- valid pixel fraction
- cloud persistence
- agreement among sensors
- forecast-model spread
- consistency between weather-derived and satellite-derived trajectory

Example confidence classes:

- High
- Moderate
- Low
- Insufficient fresh evidence

A stale cloud-gap-filled pixel must reduce confidence based on age.

## User experience

### First viewport

The first screen should answer the decision immediately:

**Lake name**

**Ice-out probability by selected date: 72%**

**Most likely: April 28–May 2**

**Current satellite estimate: 31% open water · observed 9h ago**

**Trend: breakup accelerating**

Then one sentence:

> Warmth over the next four days adds substantial thaw energy, regional snowpack is below normal, and the latest clear satellite pass shows open water expanding along the south and west shore.

### Map

Map layers:

- current true-color imagery
- NDSI / snow-ice classification
- open-water classification
- lake polygon
- latest observation footprint / timestamp

### Timeline

Allow:

- date stepping
- current spring replay
- historical year comparisons
- selected-date probability curve

### Nearby lakes

This is a major emergent feature.

For any lake show:

- nearby lakes likely to open earlier
- nearby lakes likely to open later
- lakes already observed ice-free

This supports anglers, paddlers, cabin owners, outfitters and spring-trip planners.

## Lake search and discovery

Search should accept:

- lake name
- city/town
- state/province
- map click
- coordinates

Resolve duplicate lake names using admin region and nearby municipality.

Do not generate an indexable page for every unnamed 10 ha pond.

## SEO architecture

Only index lake pages with material user value.

Eligibility score can include:

- named lake
- meaningful size
- search demand / impressions
- historical ice-out record
- recreation / tourism relevance
- quality of model inputs
- current-season satellite coverage

Programmatic pages must contain genuinely lake-specific content, not templated filler.

Each indexable page should include:

- current probability / status
- historical median and range
- current-year comparison
- latest satellite evidence
- local climate / lake morphometry explanation
- nearby lake comparison
- source provenance
- canonical URL
- internal links to state/province and nearby-lake pages

## Geographic release scope

### Phase 1 — benchmark regions

United States:

- Minnesota
- Wisconsin
- Michigan
- Maine
- New Hampshire
- Vermont
- northern New York
- Alaska large lakes where data resolution is suitable

Canada:

- Ontario
- Quebec
- Manitoba
- Saskatchewan
- Alberta
- British Columbia interior/northern lakes
- New Brunswick
- Nova Scotia
- Newfoundland and Labrador
- territories where satellite/weather coverage and lake geometry support a defensible result

### Phase 2

Expand dynamically to any qualifying northern lake in HydroLAKES / national hydrography where the model passes minimum evidence thresholds.

## Validation benchmark

The system is not ready because it looks plausible. It is ready when retrospective forecasts beat simple climatology.

### Holdout design

Use leave-one-year-out and spatial holdouts.

Spatial holdouts are mandatory so the system proves it can generalize to lakes with weak/no direct history.

### Baselines

Benchmark against:

1. historical median date only
2. latitude/elevation regional climatology
3. thaw-degree-day-only model
4. current LSPP Wawa-class-style shifted climatology

### Primary metrics

- median absolute error of predicted ice-out date
- mean absolute error
- Brier score for `ice-out by date` probabilities
- calibration error by probability bin
- interval coverage for predicted 80% window
- satellite classification precision/recall on manually reviewed lake scenes

### Release targets

Data-rich lakes:

- median absolute date error <= 3 days
- 80% prediction interval coverage between 75% and 85%
- calibrated probability bins with <= 0.08 absolute calibration error

Data-poor lakes:

- median absolute date error <= 5 days
- must beat simple regional climatology by >= 15%

Satellite classification:

- >= 90% precision for declaring >=90% open water on manually validated clear scenes

Do not surface a high-confidence date estimate for lakes that fail minimum evidence coverage.

## Value function

Score candidate releases from 0–100.

- 25 points — forecast accuracy and calibration
- 20 points — lake coverage / discovery quality
- 15 points — satellite evidence quality and freshness
- 15 points — decision usefulness
- 10 points — speed / reliability / low operating cost
- 10 points — SEO quality / entity uniqueness
- 5 points — accessibility / mobile usability

Release threshold: >= 90/100.

Hard vetoes regardless of score:

- probability presented as ice safety
- stale imagery presented as current
- lake identity ambiguity that can return the wrong lake
- national scaling that still relies on Wawa proxy day offsets
- indexable thin lake pages
- unbounded paid API/runtime dependency

## Loss function

Optimize the system against:

`L = 0.30*DateError + 0.20*ProbabilityMiscalibration + 0.15*FalseIceOutDeclaration + 0.10*StaleEvidence + 0.10*WrongLakeResolution + 0.05*Latency + 0.05*RuntimeCost + 0.05*ThinPageRisk`

Weights are conceptual and should be normalized per benchmark.

False ice-out declarations receive an additional asymmetric penalty because declaring a lake open too early is more damaging than being conservatively late.

## Cost architecture

The public site must not require a continuously running Replit/server process.

Preferred design:

1. Scheduled batch jobs during ice season.
2. Precompute lake-state observations and forecasts for qualifying lakes.
3. Store compact JSON / Parquet artifacts in object storage.
4. Serve user reads from CDN/static/serverless endpoints.
5. Compute on demand only for lower-priority lakes, then cache.
6. Increase refresh frequency as a lake approaches expected breakup.

Suggested cadence:

- winter / far from breakup: daily or less
- within 21 days of climatological median: 2–4 times/day weather refresh
- satellite classification: on new valid scene arrival
- within active breakup window: refresh lake forecast whenever weather or satellite state changes materially

## Implementation phases

### Phase 0 — preserve and isolate current LSPP

- Keep the existing LSPP tool stable.
- Extract current UI components and imagery logic into reusable modules.
- Add regression tests around existing date stepping, imagery layers and lake markers.

### Phase 1 — continental registry

- ingest HydroLAKES
- filter northern US + Canada
- add normalized lake names / admin geography
- add US/Canada source IDs
- build search index
- expose lake entity endpoint

### Phase 2 — historical model dataset

- ingest NSIDC phenology
- ingest high-value state/provincial histories
- crosswalk to canonical lake IDs
- derive satellite historical labels
- compute ERA5-Land features by lake/year

### Phase 3 — benchmark model

- implement climatology baseline
- implement ATDD baseline
- implement hierarchical survival/logistic model
- run temporal + spatial holdouts
- publish validation report in repo

### Phase 4 — current-season operational pipeline

- ingest current MODIS/VIIRS/HLS scenes
- ingest NWS/NBM/GFS and ECCC HRDPS/GDPS features
- calculate lake state and forecast JSON
- add freshness/confidence system

### Phase 5 — product UI

- lake search
- map + imagery
- probability/window hero
- reason codes
- nearby lake comparison
- historical replay
- share metadata

### Phase 6 — SEO and launch

- create only eligible lake pages
- state/province hubs
- XML sitemap partitioning
- canonical rules
- internal links
- Search Console monitoring

## Spring 2027 readiness gate

By January 2027:

- registry complete for target regions
- training dataset assembled
- baseline validation running

By February 2027:

- operational satellite/weather ingestion running unattended
- top benchmark lakes passing accuracy targets
- state/province hub templates complete

By March 2027:

- public beta live before major southern/northern Midwest breakup begins
- daily model validation dashboard active
- failure/stale-data states tested

## First benchmark lake set

Use a deliberately varied test panel rather than only easy lakes:

- Lake Minnetonka, MN
- Lake Vermilion, MN
- Leech Lake, MN
- Lake Winnipesaukee, NH
- Moosehead Lake, ME
- Sebago Lake, ME
- Lake Nipissing, ON
- Lake Simcoe, ON
- Lake of the Woods, ON/MN
- one shallow northern Michigan lake
- one deep northern Michigan lake
- Mijinemungshing Lake, ON
- Old Woman Lake, ON

Add additional lakes based on available verified historical records.

## Core product moat

The defensible asset is not the satellite imagery itself. It is the accumulated system that turns multiple public data sources into a lake-specific, calibrated decision:

**lake entity -> current observed ice state -> historical prior -> winter severity -> thaw trajectory -> forecast weather -> probability distribution -> confidence -> explanation -> nearby alternatives**

That is the system to build.