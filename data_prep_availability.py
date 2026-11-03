"""
data_prep_availability.py -- Availability / Capacity pillar (PSCI), v2
=============================================================================
Converts the PSCI notebook's own outputs (PSCI_Panel_Pipeline_FIXED_3.ipynb,
CELL 12's composite export) into the compact parquet snapshot the Streamlit
app actually loads. Mirrors data_prep.py's Cost/Reliability sections exactly:
the notebook computes everything; this script never recomputes anything the
notebook already computed, with two documented exceptions: the national
comparison stat (mirrors Cost/Reliability's identical pattern) and the
Connecticut defensive suppression below (a data-quality guard, not a
methodology choice).

Inputs (place alongside this script, same names the PSCI notebook exports):
  psci_composite_panel.csv   (2016-2025 historical, 31,090 rows)
  psci_composite_proj.csv    (2026-2028 projected, 9,327 rows)

PSCI methodology, confirmed directly against the notebook's CELL 12 source
and independently re-derived from the raw CSVs (not just taken on the
handoff's word) -- unchanged from v1, see git history for the original
verification:
  - S1_score = pooled percentile rank of Effective_MW (generation capacity)
  - S2_inv_score = 1 - pooled percentile rank of County_Peak_MW (demand) --
    inverted because LOWER relative peak demand = MORE spare capacity
  - S3_score = pooled percentile rank of TCS_raw (voltage-weighted
    transmission circuit miles, HIFLD 2025 snapshot, time-invariant)
  - PSCI_score = (S1_score + S2_inv_score + S3_score) / 3 * 100

RISK FRAMING (locked, consistent with Cost and Reliability's own "higher
score = worse" convention):
  Risk_Score = 100 - PSCI_score            (0-100, higher = worse)
  Risk_Tier mapping (PSCI tier -> Risk tier, locked 1:1 inverse):
    PSCI Tier 1 Very High  -> Risk Tier 5 Very Low Risk
    PSCI Tier 2 High       -> Risk Tier 4 Low Risk
    PSCI Tier 3 Moderate   -> Risk Tier 3 Moderate Risk
    PSCI Tier 4 Low        -> Risk Tier 2 High Risk
    PSCI Tier 5 Very Low   -> Risk Tier 1 Very High Risk

v2 CHANGES FROM v1:

1. FORECAST UNCERTAINTY BAND -- NEW, wired in (previously absent by design).
   The notebook now computes PSCI_lower/PSCI_upper for 2026-2028 (CELL 12,
   Step 5): S1 and S3 are deterministic/time-invariant (no CI exists for
   them), so the only modeled uncertainty is S2 -- the notebook re-ranks
   County_Peak_MW_Lower/Upper through the SAME pooled percentile curve used
   for the point estimate, holding S1_score/S3_score fixed, and explicitly
   labels this "S2 demand uncertainty (95% PI)" rather than a composite CI.
   This is methodologically sound (the point estimate's own derivation is
   held fixed; only the already-modeled demand uncertainty is propagated)
   and is what's shown as the shaded band in availability_pillar.py.
   Converted here to Risk_Score terms: Risk_Score_Lower = 100 - PSCI_upper,
   Risk_Score_Upper = 100 - PSCI_lower.
   QA note: recomputing this independently, 1,155 of 9,327 projected rows
   (12.4%) have a band that doesn't strictly bracket the point estimate --
   confirmed this is pure rank-denominator rounding noise (max width 0.08
   points on a 0-100 scale, mean 0.024, NOT concentrated in Connecticut or
   any other state) from the notebook's rank_against_pooled() helper using
   a slightly different array length than the original point-score rank.
   Defensively clipped below (min/max against the point estimate) so the
   rendered band always encloses its own point -- this changes nothing
   about the notebook's values, it only guarantees a sane polygon.

2. CONNECTICUT -- FIPS geography is now fixed (confirmed), but Dim1/Dim2
   VALUES are newly broken and are suppressed here as a precaution. Detail:
   the notebook's CELL 2 now correctly keeps Census TIGER 2024's native
   2022+ planning-region rows for CT (09110-09190, matching this app's map
   file exactly -- confirmed, all 3,109 FIPS in psci_composite_all.csv now
   match the map's FIPS universe 1:1). However, independently inspecting
   the actual output values shows EVERY Connecticut row has
   Effective_MW == 0, County_Peak_MW == 0, Population == 0, and
   Primary_BA == 'Unknown' for all 13 years -- not a plausible real state
   for 9 populated counties, and a regression from the prior notebook
   version (FIXED_2), which had real non-zero Dim1/Dim2 values for CT
   under the old county FIPS. Root-caused directly (reproduced with the
   notebook's own CT_CROSSWALK/match_counties_to_fips logic in isolation):
     a) Dim1 (CELL 3/10's CT_CROSSWALK): its dictionary values are the
        long form ("...Planning Region", e.g. 'Capitol Planning Region'),
        but the real TIGER 2024 county_name field -- confirmed directly
        from this run's own dim3_tcs_county.csv, which doesn't go through
        this crosswalk at all -- is the BARE region name ('Capitol', no
        suffix). Every CT lookup in Pass 3 of match_counties_to_fips()
        therefore misses, every CT generator row goes unmatched, and the
        COUNTIES-merge fillna(0) silently zeroes every county instead of
        leaving it genuinely absent.
     b) Dim2 (CELL 9's lookup_fips_local(), used for the EIA-861 service-
        territory -> BA -> county join that drives County_Peak_MW,
        Primary_BA, and -- via the same county_fips_df -- Population/
        County_Sales_MWh) has NO Connecticut handling at all: it's a bare
        COUNTY_LOOKUP.get((state, name)) with no CT_CROSSWALK fallback,
        so it can only ever match CT if the raw EIA county name happens to
        already be the new region name verbatim, which it never is.
   This is a separate, SECOND bug from (a) -- fixing CT_CROSSWALK's string
   values only repairs Dim1; Dim2's lookup_fips_local() needs its own
   CT_CROSSWALK-based fallback (with the corrected bare-name values) added
   before Connecticut's Dim1/Dim2 data can be trusted.
   Until that's fixed and re-verified, PSCI_score/Risk_Score (and every
   column derived from them) are set back to NaN for Connecticut here --
   same "no data" / gray-on-map outcome as v1, but now for the CORRECT,
   currently-true reason (verified-broken source values) rather than v1's
   reason (FIPS mismatch, which IS now fixed). TCS_raw (S3, pure geometry,
   unaffected by either bug) is left as-is and is genuine, real data --
   only the composite score and its two broken inputs are suppressed.

Outputs -> data/:
  avail_panel.parquet        (2016-2025 historical, with the national
                               comparison stats above)
  avail_forecast.parquet     (2026-2028 projected, with the Risk_Score
                               uncertainty band)
  avail_county_lookup.parquet
"""
import numpy as np
import pandas as pd

OUT_DIR = 'data'

PANEL_CSV_PATH = 'psci_composite_panel.csv'
PROJ_CSV_PATH = 'psci_composite_proj.csv'

PSCI_TO_RISK_TIER = {
    'Tier 1 – Very High': 'Tier 5 – Very Low Risk',
    'Tier 2 – High':      'Tier 4 – Low Risk',
    'Tier 3 – Moderate':  'Tier 3 – Moderate Risk',
    'Tier 4 – Low':       'Tier 2 – High Risk',
    'Tier 5 – Very Low':  'Tier 1 – Very High Risk',
}

# Still-broken Dim1/Dim2 for CT -- see module docstring, item 2. Suppressed
# by FIPS prefix (09 = Connecticut) rather than listing all 9 region codes,
# so this stays correct whether the notebook's output set shifts slightly.
CT_FIPS_PREFIX = '09'

panel = pd.read_csv(PANEL_CSV_PATH, dtype={'FIPS': str})
panel['FIPS'] = panel['FIPS'].str.zfill(5)

proj = pd.read_csv(PROJ_CSV_PATH, dtype={'FIPS': str})
proj['FIPS'] = proj['FIPS'].str.zfill(5)

for df in (panel, proj):
    df['Risk_Score'] = (100 - df['PSCI_score']).round(2)
    df['Risk_Tier'] = df['PSCI_Tier'].map(PSCI_TO_RISK_TIER)
    assert df['Risk_Tier'].notna().all(), (
        "Unmapped PSCI_Tier value found -- check PSCI_TO_RISK_TIER against "
        "the notebook's actual tier labels before re-running."
    )

# ---- Forecast uncertainty band (NEW in v2) ---------------------------------
# PSCI_lower/PSCI_upper -> Risk_Score terms, with a defensive clip so the
# rendered band always encloses its own point estimate (see module
# docstring item 1 for why ~12% of rows need this and why it's safe).
proj['Risk_Score_Lower'] = (100 - proj['PSCI_upper']).round(2)
proj['Risk_Score_Upper'] = (100 - proj['PSCI_lower']).round(2)
proj['Risk_Score_Lower'] = np.minimum(proj['Risk_Score_Lower'], proj['Risk_Score'])
proj['Risk_Score_Upper'] = np.maximum(proj['Risk_Score_Upper'], proj['Risk_Score'])

# ---- Connecticut defensive suppression (NEW in v2, see docstring item 2) --
ct_mask = panel['FIPS'].str.startswith(CT_FIPS_PREFIX)
ct_mask_proj = proj['FIPS'].str.startswith(CT_FIPS_PREFIX)
n_ct_panel, n_ct_proj = int(ct_mask.sum()), int(ct_mask_proj.sum())
for col in ['S1_score', 'S2_inv_score', 'PSCI_score', 'PSCI_Tier', 'Risk_Score', 'Risk_Tier',
            'Effective_MW', 'County_Peak_MW', 'Primary_BA']:
    if col in panel.columns:
        panel.loc[ct_mask, col] = np.nan
for col in ['S1_score', 'S2_inv_score', 'PSCI_score', 'PSCI_Tier', 'Risk_Score', 'Risk_Tier',
            'Effective_MW', 'County_Peak_MW', 'County_Peak_MW_Lower', 'County_Peak_MW_Upper',
            'Risk_Score_Lower', 'Risk_Score_Upper']:
    if col in proj.columns:
        proj.loc[ct_mask_proj, col] = np.nan
# S3_score/TCS_raw deliberately left untouched for CT -- real, unaffected data.

# ---- National comparison stats (computed once, here -- not per-render) ----
# Observed years only, by the same interface decision already applied to
# Cost (Pct_Counties_MoreExpensive_SameYear) and Reliability
# (Pct_Counties_Less_Reliable_SameYear): forecast years get no such stat.
# Connecticut's now-NaN PSCI_score/Effective_MW/County_Peak_MW correctly
# fall out of both the ranking and the medians below (pandas skips NaN).
panel['_rank_pct'] = panel.groupby('Year')['PSCI_score'].rank(pct=True, method='average')
panel['Pct_Counties_BetterAvailability_SameYear'] = (panel['_rank_pct'] * 100).round(1)
panel['National_Median_Effective_MW_SameYear'] = (
    panel.groupby('Year')['Effective_MW'].transform('median')
)
panel['National_Median_Peak_MW_SameYear'] = (
    panel.groupby('Year')['County_Peak_MW'].transform('median')
)
panel['National_Median_TCS_SameYear'] = (
    panel.groupby('Year')['TCS_raw'].transform('median')
)
panel = panel.drop(columns=['_rank_pct'])

panel_cols = [
    'FIPS', 'County_Name', 'State', 'State_Name', 'Year',
    'Effective_MW', 'County_Peak_MW', 'TCS_raw', 'TCS_segment_count',
    'Primary_BA', 'S1_score', 'S2_inv_score', 'S3_score',
    'PSCI_score', 'PSCI_Tier', 'Risk_Score', 'Risk_Tier', 'Data_Type',
    'Pct_Counties_BetterAvailability_SameYear',
    'National_Median_Effective_MW_SameYear', 'National_Median_Peak_MW_SameYear',
    'National_Median_TCS_SameYear',
]
proj_cols = [
    'FIPS', 'County_Name', 'State', 'State_Name', 'Year',
    'Effective_MW', 'County_Peak_MW', 'County_Peak_MW_Lower', 'County_Peak_MW_Upper',
    'TCS_raw', 'TCS_segment_count', 'S1_score', 'S2_inv_score', 'S3_score',
    'PSCI_score', 'PSCI_Tier', 'Risk_Score', 'Risk_Tier',
    'Risk_Score_Lower', 'Risk_Score_Upper', 'Data_Type',
]
avail_panel = panel[panel_cols].sort_values(['State', 'County_Name', 'Year']).reset_index(drop=True)
avail_forecast = proj[proj_cols].sort_values(['State', 'County_Name', 'Year']).reset_index(drop=True)

avail_county_lookup = (
    pd.concat([avail_panel[['FIPS', 'State', 'County_Name']],
               avail_forecast[['FIPS', 'State', 'County_Name']]])
    .drop_duplicates('FIPS').sort_values(['State', 'County_Name']).reset_index(drop=True)
)

avail_panel.to_parquet(f'{OUT_DIR}/avail_panel.parquet', index=False)
avail_forecast.to_parquet(f'{OUT_DIR}/avail_forecast.parquet', index=False)
avail_county_lookup.to_parquet(f'{OUT_DIR}/avail_county_lookup.parquet', index=False)

print(f"[Availability] avail_panel.parquet: {len(avail_panel):,} rows, "
      f"{avail_panel['FIPS'].nunique():,} counties, years "
      f"{avail_panel['Year'].min()}-{avail_panel['Year'].max()}")
print(f"[Availability] avail_forecast.parquet: {len(avail_forecast):,} rows, years "
      f"{avail_forecast['Year'].min()}-{avail_forecast['Year'].max()}")
print(f"[Availability] avail_county_lookup.parquet: {len(avail_county_lookup):,} counties")
print(f"[Availability] Risk_Score summary (historical, pooled):")
print(avail_panel['Risk_Score'].describe().round(2).to_string())
print(f"\n[Availability] Risk_Tier distribution (historical):")
print(avail_panel['Risk_Tier'].value_counts(dropna=False).sort_index().to_string())

print(f"\n[Availability] CAVEAT -- Connecticut: FIPS geography now matches this "
      f"app's map (09110-09190, {n_ct_panel} historical + {n_ct_proj} forecast "
      f"county-year rows found) but Dim1/Dim2 values for CT are verified broken "
      f"(all zero -- a notebook county-matching bug, confirmed independently, "
      f"NOT a real reading) as of this run, so Risk_Score/PSCI_score have been "
      f"suppressed back to NaN for CT here -- it will still show as 'no data' "
      f"on the map, for a different and currently-accurate reason than before. "
      f"See this script's module docstring, item 2, for the exact fix needed "
      f"in the notebook (two separate bugs: CELL 3/10's CT_CROSSWALK uses the "
      f"wrong target string format for Dim1, and CELL 9's lookup_fips_local() "
      f"has no Connecticut handling at all for Dim2).")
