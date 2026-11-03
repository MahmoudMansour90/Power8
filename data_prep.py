"""
data_prep.py -- Power Risk Index for Data Center Construction Planning (v3)
=============================================================================
Converts each pillar's notebook-computed outputs into the compact
parquet/JSON snapshot the Streamlit app actually loads. The notebooks
compute everything; this script and the app never recompute anything
EXCEPT the one genuinely new, cheap, one-time statistic noted below.
Re-run this after either pillar's notebook produces new validated
outputs, then push the updated data/ files.

Inputs (place alongside this script, same names the source notebooks export):
  Cost pillar:
    Industrial_Price_Panel_Long_2001_2025.xlsx   (now carries Reporting_Utilities)
    county_price_forecast_3yr_theta.csv          (2026-2028)
  Reliability pillar (from the MOCCI_Reliability_Export v3 handoff):
    reliability_cri_panel_2013_2025.csv
    county_cri_forecast_3yr.csv                  (2026-2028)
    county_cri_not_projected.csv
    county_cri_latest_year_gaps.csv
    cri_model_metadata.json

The one computed addition: Cost has no pre-built national-comparison
statistic analogous to Reliability's own Pct_Counties_Less_Reliable_SameYear
(that one is already in the Reliability panel -- not recomputed here).
For Cost, Pct_Counties_MoreExpensive_SameYear is computed once here, at
prep time (never per-render in the app): for each OBSERVED year, the
percentage of counties with a HIGHER industrial price than this county.
Scoped to observed years only -- forecast years have no such statistic in
either pillar, by design (see the interface-refinements discussion).

Outputs -> data/:
  actual.parquet, forecast.parquet, county_lookup.parquet                 (Cost)
  reliability_panel.parquet, reliability_forecast.parquet,
  reliability_not_projected.parquet, reliability_latest_year_gaps.parquet,
  reliability_county_lookup.parquet, reliability_metadata.json            (Reliability)
  counties_fips.json  (shared county boundary file -- AK/HI dropped below)
  state_borders.json  (NEW in v3.1 -- see build_state_borders() below:
                        per-state boundary LINES dissolved from the same
                        AK/HI-free county geometry, drawn as the map's own
                        go.Scattergeo trace instead of relying on Plotly's
                        scope='usa' basemap, which is what let Alaska/Hawaii
                        insets show up no matter how the view was cropped.
                        Since this geometry is built only from counties
                        already in counties_fips.json, AK/HI are now
                        structurally impossible to include here either.)
"""
import json
import shutil
import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

# Hardcoded state-FIPS -> USPS-abbreviation map, 50 states + DC only --
# Alaska (02), Hawaii (15) and the territories are deliberately absent, so
# a county belonging to any of them can never be grouped into a state
# border trace even if it slipped through the AK/HI filter below.
STATE_FIPS = {
    '01': 'AL', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO', '09': 'CT',
    '10': 'DE', '11': 'DC', '12': 'FL', '13': 'GA', '16': 'ID', '17': 'IL',
    '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS', '29': 'MO',
    '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH', '34': 'NJ', '35': 'NM',
    '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH', '40': 'OK', '41': 'OR',
    '42': 'PA', '44': 'RI', '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX',
    '49': 'UT', '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY',
}


def build_state_borders(geo):
    """Dissolve the (already AK/HI-filtered) county geojson into per-state
    boundary LINE geometry, for the app's own go.Scattergeo state-border
    trace. Verified (v3.1 rework) against a GEOSException
    ('side location conflict') caused by minor self-intersections in the
    TIGER-derived county polygons -- fixed with .buffer(0) per geometry
    before unioning, the standard polygon-repair trick."""
    by_state = {}
    for feat in geo['features']:
        fips = str(feat.get('id', '')).zfill(5)
        state_fips = fips[:2]
        if state_fips not in STATE_FIPS:
            continue
        by_state.setdefault(state_fips, []).append(shape(feat['geometry']).buffer(0))

    lons, lats = [], []
    for state_fips, geoms in by_state.items():
        merged = unary_union(geoms).simplify(0.01, preserve_topology=True)
        polys = list(merged.geoms) if merged.geom_type == 'MultiPolygon' else [merged]
        for poly in polys:
            for ring in [poly.exterior] + list(poly.interiors):
                xs, ys = ring.xy
                lons.extend(list(xs))
                lats.extend(list(ys))
                lons.append(None)
                lats.append(None)
    return {'lons': lons, 'lats': lats}

OUT_DIR = 'data'

# ============================================================== COST PILLAR
PANEL_LONG_PATH = 'Industrial_Price_Panel_Long_2001_2025.xlsx'
FORECAST_CSV_PATH = 'county_price_forecast_3yr_theta.csv'

panel_long = pd.read_excel(PANEL_LONG_PATH)
panel_long['FIPS'] = panel_long['FIPS'].astype(str).str.extract(r'(\d+)')[0].str.zfill(5)
# Only real counties -- never the State-UNALLOC statewide placeholder rows
# (they have no 5-digit FIPS and must never be mapped or rank-compared).
panel_long = panel_long[panel_long['FIPS'].str.len() == 5].copy()
assert 'Reporting_Utilities' in panel_long.columns, (
    "Reporting_Utilities missing from the panel -- re-export from the "
    "revised Cost pipeline notebook before running this script."
)

forecast_df = pd.read_csv(FORECAST_CSV_PATH, dtype={'FIPS': str})
forecast_df['FIPS'] = forecast_df['FIPS'].str.zfill(5)

# ---- National comparison stat (computed once, here -- not per-render) ----
# Pct_Counties_MoreExpensive_SameYear: % of counties with a HIGHER
# industrial price than this one, within the same observed year. Mirrors
# Reliability's Pct_Counties_Less_Reliable_SameYear in spirit: "this
# county is cheaper than {this value}% of U.S. counties in {Year}."
panel_long['_rank_pct'] = panel_long.groupby('Year')['Ind_Price_cents_kWh'].rank(pct=True, method='average')
panel_long['Pct_Counties_MoreExpensive_SameYear'] = ((1 - panel_long['_rank_pct']) * 100).round(1)
panel_long['National_Median_Price_cents_kWh_SameYear'] = (
    panel_long.groupby('Year')['Ind_Price_cents_kWh'].transform('median')
)
panel_long = panel_long.drop(columns=['_rank_pct'])

actual = panel_long.rename(columns={'Ind_Price_cents_kWh': 'Price_cents_kWh'})[
    ['FIPS', 'State', 'County_Name', 'Year', 'Price_cents_kWh', 'Total_MWh',
     'Reporting_Utilities', 'Num_Reporting', 'Pct_Counties_MoreExpensive_SameYear',
     'National_Median_Price_cents_kWh_SameYear']
].copy()

forecast = forecast_df.rename(
    columns={'Forecast_Year': 'Year', 'Forecast_Price_cents_kWh': 'Price_cents_kWh'}
)[['FIPS', 'State', 'County_Name', 'Year', 'Years_Ahead', 'Price_cents_kWh',
   'Lower_CI_cents_kWh', 'Upper_CI_cents_kWh', 'CI_Level_%',
   'Expected_MAPE_%', 'Error_Band_Source']].copy()
# Lower_CI/Upper_CI/CI_Level_%/Expected_MAPE_% are kept ONLY for the
# shaded-band chart visual -- per the confirmed interface decision, the
# app never prints any of these as text or a metric anywhere (hover,
# click panel, or search panel).

cost_county_lookup = (
    pd.concat([actual[['FIPS', 'State', 'County_Name']], forecast[['FIPS', 'State', 'County_Name']]])
    .drop_duplicates('FIPS').sort_values(['State', 'County_Name']).reset_index(drop=True)
)

actual.to_parquet(f'{OUT_DIR}/actual.parquet', index=False)
forecast.to_parquet(f'{OUT_DIR}/forecast.parquet', index=False)
cost_county_lookup.to_parquet(f'{OUT_DIR}/county_lookup.parquet', index=False)

print(f"[Cost] actual.parquet: {len(actual):,} rows, {actual['FIPS'].nunique():,} counties, "
      f"years {actual['Year'].min()}-{actual['Year'].max()}")
print(f"[Cost] forecast.parquet: {len(forecast):,} rows, years "
      f"{forecast['Year'].min()}-{forecast['Year'].max()}")
print(f"[Cost] county_lookup.parquet: {len(cost_county_lookup):,} counties")
print(f"[Cost] Reporting_Utilities populated: "
      f"{(actual['Reporting_Utilities'].notna() & (actual['Reporting_Utilities'] != '')).mean():.1%} of rows")

# ======================================================= RELIABILITY PILLAR
REL_PANEL_PATH = 'reliability_cri_panel_2013_2025.csv'
REL_FORECAST_PATH = 'county_cri_forecast_3yr.csv'
REL_NOT_PROJECTED_PATH = 'county_cri_not_projected.csv'
REL_LATEST_GAPS_PATH = 'county_cri_latest_year_gaps.csv'
REL_METADATA_PATH = 'cri_model_metadata.json'

rel_panel = pd.read_csv(REL_PANEL_PATH, dtype={'FIPS': str})
rel_panel['FIPS'] = rel_panel['FIPS'].str.zfill(5)

rel_forecast = pd.read_csv(REL_FORECAST_PATH, dtype={'FIPS': str})
rel_forecast['FIPS'] = rel_forecast['FIPS'].str.zfill(5)
# REVISED (interface refinement): the exported Popup_Headline includes a
# "(likely range X-Y)" parenthetical. The confirmed interface decision is
# to suppress all 68%/likely-range/probability-band text everywhere, so a
# brief version is derived here -- "Projected 2028: Moderate" -- once, at
# prep time, rather than string-parsing it in the app on every render.
rel_forecast['Popup_Headline_Brief'] = (
    rel_forecast['Popup_Headline'].str.replace(r'\s*\(likely range[^)]*\)', '', regex=True)
)

rel_not_projected = pd.read_csv(REL_NOT_PROJECTED_PATH, dtype={'FIPS': str})
rel_not_projected['FIPS'] = rel_not_projected['FIPS'].str.zfill(5)

rel_latest_gaps = pd.read_csv(REL_LATEST_GAPS_PATH, dtype={'FIPS': str})
rel_latest_gaps['FIPS'] = rel_latest_gaps['FIPS'].str.zfill(5)

rel_county_lookup = (
    pd.concat([
        rel_panel[['FIPS', 'State', 'County_Name']],
        rel_forecast[['FIPS', 'State', 'County_Name']],
        rel_not_projected[['FIPS', 'State', 'County_Name']],
    ])
    .drop_duplicates('FIPS').sort_values(['State', 'County_Name']).reset_index(drop=True)
)

rel_panel.to_parquet(f'{OUT_DIR}/reliability_panel.parquet', index=False)
rel_forecast.to_parquet(f'{OUT_DIR}/reliability_forecast.parquet', index=False)
rel_not_projected.to_parquet(f'{OUT_DIR}/reliability_not_projected.parquet', index=False)
rel_latest_gaps.to_parquet(f'{OUT_DIR}/reliability_latest_year_gaps.parquet', index=False)
rel_county_lookup.to_parquet(f'{OUT_DIR}/reliability_county_lookup.parquet', index=False)
shutil.copy(REL_METADATA_PATH, f'{OUT_DIR}/reliability_metadata.json')

print(f"\n[Reliability] reliability_panel.parquet: {len(rel_panel):,} rows, "
      f"{rel_panel['FIPS'].nunique():,} counties, years "
      f"{rel_panel['Year'].min()}-{rel_panel['Year'].max()}")
print(f"[Reliability] reliability_forecast.parquet: {len(rel_forecast):,} rows, years "
      f"{rel_forecast['Year'].min()}-{rel_forecast['Year'].max()}")
print(f"[Reliability] reliability_not_projected.parquet: {len(rel_not_projected):,} rows")
print(f"[Reliability] reliability_latest_year_gaps.parquet: {len(rel_latest_gaps):,} rows")
print(f"[Reliability] reliability_county_lookup.parquet: {len(rel_county_lookup):,} counties")

# ============================================================ SHARED FILES
with open(f'{OUT_DIR}/counties_fips.json') as f:
    geo = json.load(f)
n_before = len(geo['features'])
# REVISED (interface refinement): no Alaska/Hawaii anywhere -- the project
# scope is the contiguous US only. Dropped once, here, from the shared
# boundary file, rather than filtered repeatedly by every pillar page.
#
# BUG FIX (confirmed 2026-10-29, caught by the user asking a simple "how
# many counties" question that the app itself never answered): the
# original filter here only excluded Alaska (02) and Hawaii (15) by FIPS
# prefix. The source county-boundary file also includes five U.S.
# territories as "county-equivalent" features -- American Samoa (60, 3
# features), Guam (66, 1), the Northern Mariana Islands (69, 4), Puerto
# Rico (72, 78), and the U.S. Virgin Islands (78, 3), 89 features total --
# none of which were ever excluded, so a file documented and labeled
# "contiguous US only" silently carried 89 territory counties that don't
# belong in that scope at all (confirmed directly: state-FIPS prefixes
# 60/66/69/72/78 were all present). build_state_borders() below was
# already safe from this (it filters by the STATE_FIPS allow-list, not by
# excluding 02/15), which is exactly why state_borders.json was correct
# the whole time and only the per-county choropleth geometry -- and every
# pillar's FIPS universe, built from it at runtime by each page's
# _all_fips_base() -- was affected. Fixed the same way: filter by
# membership in the STATE_FIPS allow-list (48 contiguous states + DC)
# instead of by excluding two specific codes, so this can't silently admit
# a sixth non-contiguous entity in the future either.
geo['features'] = [
    feat for feat in geo['features']
    if str(feat.get('id', '')).zfill(5)[:2] in STATE_FIPS
]
n_after = len(geo['features'])
with open(f'{OUT_DIR}/counties_fips.json', 'w') as f:
    json.dump(geo, f)
print(f"\ncounties_fips.json: kept {n_after:,} of {n_before:,} source features "
      f"(dropped {n_before - n_after:,} -- AK/HI plus five U.S. territories), "
      "contiguous US + DC only.")

# NEW in v3.1: dissolve the (now AK/HI-free) county geometry into per-state
# boundary lines, drawn by the app as its own go.Scattergeo trace -- see
# map_utils.build_static_choropleth(). This replaces relying on Plotly's
# scope='usa' built-in state-border layer, which is what was impossible to
# separate from that basemap's fixed Alaska/Hawaii inset boxes.
state_borders = build_state_borders(geo)
with open(f'{OUT_DIR}/state_borders.json', 'w') as f:
    json.dump(state_borders, f)
n_rings = state_borders['lons'].count(None)
n_pts = len(state_borders['lons']) - n_rings
print(f"state_borders.json: {len(STATE_FIPS)} states, {n_rings} rings, {n_pts:,} points.")
