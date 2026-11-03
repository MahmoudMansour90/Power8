# Power Risk Index for Data Center Construction Planning (v3.7)

MOCCI -- interactive Cost, Reliability, and Availability pillar explorer,
built on real EIA-861/EIA-860/EIA-930/HIFLD data through 2025 (2028 for
forecasts). The Composite Power Risk Index remains an honest placeholder --
no synthetic or invented numbers -- until it's built out.

One page, one URL, with a tab per pillar (Cost / Reliability / Availability /
Composite) -- no separate page URLs to navigate between.

## v3.7 -- Forecast uncertainty band added; Connecticut re-diagnosed

Two things changed in `PSCI_Panel_Pipeline_FIXED_3.ipynb` since v3.6, both
independently re-verified here rather than taken on faith:

**1. Forecast uncertainty band -- now real, wired in.** The notebook now
computes `PSCI_lower`/`PSCI_upper` for 2026-2028 by re-ranking the S2
(peak-demand) forecast's confidence bounds through the same pooled
percentile curve as the point estimate, holding S1/S3 fixed (S3 is
time-invariant and S1 has no modeled uncertainty). This is methodologically
sound and is now shown as a shaded band on the Risk Score trend chart,
labeled "S2 demand uncertainty" -- matching the notebook's own chosen
label, since it isn't a true composite-score CI. QA note: 1,155 of 9,327
projected rows (12.4%) have a band that doesn't strictly enclose the point
estimate; independently confirmed this is rank-denominator rounding noise
(max width 0.08 points, not concentrated in any one state) rather than a
real inconsistency, and it's defensively clipped at prep time so the
rendered band always encloses its own point.

**2. Connecticut -- the geography half of the fix landed correctly; a new,
separate data bug was caught before shipping.** CELL 2 of the notebook now
correctly keeps Census TIGER 2024's native 2022+ planning-region rows for
CT instead of swapping in the old 8 counties -- confirmed directly, all
3,109 FIPS in the output now match this app's map file exactly, closing
the v3.6 gap. However, inspecting the actual VALUES (not just FIPS
presence) turned up a second, new problem: every Connecticut row has
`Effective_MW`, `County_Peak_MW`, and `Population` all exactly 0 and
`Primary_BA` = `'Unknown'` for all 13 years -- not a real reading, and a
regression from the prior notebook version, which had genuine non-zero CT
values under the old FIPS. Root-caused by reproducing the notebook's own
matching logic in isolation: the new `CT_CROSSWALK` dictionary (Dim1) maps
old county names to the long-form region string (`'...Planning Region'`),
but the real TIGER 2024 name field is the bare region name (`'Capitol'`,
no suffix) -- confirmed directly from `dim3_tcs_county.csv`, which doesn't
go through this crosswalk and has real CT values. Dim2's own county match
(`lookup_fips_local()`) has no Connecticut handling at all, a second,
separate gap. Until both are fixed in the notebook, Connecticut's
Risk_Score/PSCI_score are suppressed back to NaN here (TCS/S3, unaffected
by either bug, is left as real data) -- it still shows as "no data" on the
map, now for the correct, currently-true reason. Full diagnosis and the
exact fix needed are in `data_prep_availability.py`'s module docstring.

## v3.6 -- Availability (Capacity) pillar goes live (PSCI)

The Availability tab is no longer a placeholder. It now shows the Power
Supply Capacity Index (PSCI) from `PSCI_Panel_Pipeline_FIXED_2.ipynb`,
2016-2025 historical + 2026-2028 projected, following the exact same
structure, interaction model, and map/legend conventions as `cost_pillar.py`
and `reliability_pillar.py` (see `availability_pillar.py`'s own module
docstring for the full detail).

**Risk framing:** `Risk_Score = 100 - PSCI_score` (0-100, higher = worse),
consistent with Cost's cents/kWh and Reliability's CRI, both of which also
use "higher = worse." `PSCI_score` itself (0-100, higher = better) is also
shown, since it's the notebook's own native unit.

**Methodology, verified directly against the notebook source and
independently re-derived from the raw CSVs** (not just taken on faith from
the handoff that produced them): PSCI_score = (S1_score + S2_inv_score +
S3_score) / 3 * 100, where each sub-score is a POOLED percentile rank (ties
averaged) across all 40,404 county-years at once (2016-2028, historical and
projected together) of, respectively, generation capacity (Effective_MW),
inverted peak demand (1 - percentile rank of County_Peak_MW -- lower
relative demand = more spare capacity = better), and transmission
connectivity (TCS_raw, voltage-weighted HIFLD circuit miles). Recomputing
(S1+S2_inv+S3)/3*100 directly from the raw columns reproduces the notebook's
own PSCI_score column to within float rounding on every row, and the
resulting distribution (mean 50.00, std 13.49, range 7.91-97.41 across all
40,404 county-years) matches the handoff's own stated figures exactly.
PSCI_Tier is NOT a population-balanced quintile -- it's fixed cutoffs
(80/60/40/20) on the composite score, so tier sizes are uneven by
construction (the average of three independently percentile-ranked
components is bell-shaped around 50, not uniform, even though each
component alone is a true percentile rank). TCS (S3) is a 2025 HIFLD
snapshot, time-invariant, broadcast to all 13 panel years -- an explicit,
disclosed methodological choice in the notebook itself (see its CELL 11),
not an oversight.

**Known caveats (see `data_prep_availability.py`'s module docstring for the
full writeup):**
- **Connecticut geography mismatch.** The PSCI notebook computes
  Connecticut at the OLD 8-county FIPS (09001-09015); this app's shared
  `counties_fips.json` (and the live Cost/Reliability panels) use the NEW
  2022+ 9-planning-region FIPS (09110-09190). The two aren't a clean 1:1
  rename, so no crosswalk is applied -- Connecticut's 9 planning regions
  show as "no data" (gray) on the Availability map only; Cost and
  Reliability are unaffected. Needs a notebook-level re-run against the new
  regions, not a prep-script patch.
- **FIPS leading-zero loss, fixed in prep.** The source CSVs store FIPS as
  a bare int, dropping the leading zero for state FIPS 01/04/05/06/08/09
  (AL/AZ/AR/CA/CO/CT) -- 287 of 3,108 counties. Fixed the same way as every
  other pillar (`dtype={'FIPS': str}` + `.str.zfill(5)`).
- **No EIA-930 2016-2017 reliability caveat applied.** The notebook treats
  all ten historical years of County_Peak_MW on equal footing; it contains
  no handling for EIA-930's generally-understood early-reporting-years data
  quality, unlike this project's earlier, explicit discussion of that
  issue. Flagged for judgment, not altered.
- **No forecast uncertainty band on Risk Score.** The notebook never
  re-ranks its County_Peak_MW confidence bounds through the pooled
  percentile step, so there's no validated way to propagate a CI onto the
  composite score. The Availability trend chart's 2026-2028 segment is a
  dashed point-forecast line only -- a deliberate difference from
  Reliability's CRI chart (which does have a real, notebook-computed band),
  not an oversight.

## v3.5 -- "Compare counties" made selection-aware, plus a real trajectory column

The bottom "Compare counties" table on both tabs used to be a single,
context-free leaderboard: pick a scope (nationwide or one state), sort by
the current or forecast value, show the top/bottom N -- completely
disconnected from whatever county was clicked or searched above it. Two
changes, after thinking through with the user what would actually add
insight beyond the map rather than just restating it in table form:

- **A new "Change to {forecast year} (%)" column**, computed from the two
  values the table already carries (last reported/observed value and the
  forecast-horizon value) -- no new data pulled. This is trajectory
  information a single-year map snapshot cannot show at all: which
  counties are trending cheaper/more reliable versus worse, independent of
  where they rank today.
- **The table is now selection-aware.** The moment a county is clicked or
  searched, the comparison section automatically switches into a "Peers of
  selected county" mode, scoped to that county's own state, showing a
  window of counties ranked just above and below it (its own row marked
  with a star) instead of the generic, state-blind top/bottom-N list. The
  reasoning: for continuous values like price and CRI, "nearest by rank"
  and "nearest by raw value" are effectively the same set, so rank-window
  is simplest; and scoping to the county's own state by default is what's
  actually decision-relevant for a siting choice (incentives, permitting,
  and workforce are state-bound, so a same-state peer is a real
  alternative, not just a nationally similar number in an unrelated
  state). A "Compare to" toggle (shown only once a county is selected)
  switches back to the original top/bottom-N leaderboard at any time, and
  that manual choice -- along with any manual Scope/State/Sort/N
  adjustment -- is never overwritten except by an actual NEW selection
  (confirmed directly: changing the year slider or any other unrelated
  control afterwards does not reset it).

Verified with `AppTest` against the real app and real data, through both
selection paths (map click and search dropdowns), on both tabs: the mode
toggle is hidden until something is selected; selecting a county correctly
force-switches mode to "Peers of selected county" and scope to that
county's own state; the resulting table carries a `Rank` column, the new
`Change to {year} (%)` column, and a starred row for the selected county
at its correct rank position; a manual toggle back to the leaderboard
survives an unrelated rerun (year-slider change); and zero exceptions
throughout.

## v3.4 -- content/UI simplification round, plus a real county-scope data fix

**Fixed: the "contiguous US" map scope was silently including five U.S.
territories.** Found while answering the user's own question about how many
counties the maps cover -- the user's skepticism ("the contiguous US have
less than 3198 counties?!") was correct. Root cause: `data_prep.py`'s county
geojson filter only ever excluded Alaska (`02`) and Hawaii (`15`) FIPS
prefixes; it never excluded American Samoa (`60`), Guam (`66`), the Northern
Mariana Islands (`69`), Puerto Rico (`72`), or the U.S. Virgin Islands (`78`)
-- 89 territory features in total (78 of them Puerto Rico alone). Fixed by
filtering against an explicit 49-entry allow-list (48 contiguous states + DC)
instead of an exclude-list, and regenerating `data/counties_fips.json`. The
correct contiguous-US county/county-equivalent count is **3,109**, not 3,198.
Verified directly: all 89 dropped features were confirmed territory-prefixed
(none were a real contiguous county), no real county was ever dropped, and
`data/state_borders.json` came out byte-identical (MD5-compared) before and
after, since `build_state_borders()` was already filtering correctly.

**Main page:** the top-level "Scope:" summary box is removed entirely.

**Cost and Reliability tabs, both:**
- The top note is replaced with a single plain-language instruction note
  ("Drag the slider to select a year... Click any county on the map or
  search for a county name below..."), and the old bottom duplicate caption
  saying effectively the same thing is removed.
- The year ruler under the slider now marks **every** year, not every 2nd
  year (the slider itself was always every-year-selectable; only the visual
  ruler changes).
- The legend no longer shows numeric endpoint values underneath the
  gradient bar, and the "square-root scale" (Cost) / "CRI is a constructed
  0-100 index" (Reliability) captions under the legend are removed.
- Reliability's legend low/high labels are changed from the generic "Lower
  Risk"/"Higher Risk" to the more descriptive **"Lower Risk / Higher
  Reliability"** and **"Higher Risk / Lower Reliability."**

**Cost tab:** the "Total reported industrial volume" line under a selected
county's metrics is removed.

**Reliability tab:** a new metrics row is added alongside the existing CRI
value -- the selected county's own **SAIDI** and **SAIFI** for the selected
year, and the **national median SAIFI** alongside the existing national
median SAIDI (all four from already-validated columns already present in
`reliability_panel.parquet`, nothing newly computed).

**One correction made to the request as given:** the requested top-note
wording ("Drag the slider to select a year from 2001 to 2028") is accurate
for Cost, but Reliability's real data starts in 2013, not 2001 -- so
Reliability's note says "2013 to 2028" instead. Everything else in the
requested wording is used as given.

**Availability and Composite tabs:** both are shortened from a multi-line
explanation of why the pillar isn't built yet to a single-line honest
placeholder -- "To be added." (Availability) and "To be developed from the
Cost, Reliability, and Availability pillars." (Composite). No synthetic
numbers are shown in either, same as before.

All of the above was verified with Streamlit's `AppTest` framework against
the real running app and real data (not just read from source): the Scope
note's removal, both tabs' new note text, zero duplicate captions, all-years
ruler (28 ticks for Cost 2001-2028, 16 for Reliability 2013-2028), the new
legend labels, the absence of the industrial-volume line, the new SAIDI/
SAIFI/national-median-SAIFI metrics rendering with real numbers for a real
county (Pulaski County, MO, FIPS 29019: CRI 38.1, county SAIDI 316.0 min/
customer, county SAIFI 0.94, national median SAIFI 1.53), both placeholder
tabs' exact text, and -- unchanged from v3.3 -- that map click <-> search
dropdown sync and forecast-year rendering still work with zero exceptions
after all these edits.

## v3.3 -- third round of fixes from real post-deployment use

**Click and search unified into one experience.** v3.2 tried giving a map
click a different, more compact panel than a search; after using it for
real, one consistent experience was preferred. Now clicking a county or
searching for one both open the exact same full detail panel, always for
the latest actual/observed year: price/CRI, national standing, national
median, reporting utilities, national rank, (Cost) total reported volume,
the full trend chart, and (Reliability) the SAIDI/SAIFI expander.

**Clicking a county now also updates the State/County search dropdowns**
above the map to that same county, so the map and the search boxes stay
visually in sync. Mechanically this needs an extra, invisible rerun: a
fresh click queues the target county, and the dropdowns pick it up at the
very top of the next script pass, before they're drawn -- Streamlit
refuses to overwrite a dropdown's value after it has already rendered
earlier in the same pass, confirmed directly while building this (the
first attempt at this feature hit exactly that error and was corrected
before being shipped).

**Cost's color scale is no longer linear at all -- it's a square-root
scale.** Last round's fix (capping the top of a linear scale at the 98th
percentile) fixed the "everything looks yellow" problem but, as the user
found testing it for real, simply moved the problem to the top of the
scale: every county at or above the cap -- including essentially all of
California -- was clamped to the exact same darkest color. A pure
percentile-rank scale was tried next and measured directly against this
app's real data before being rejected: California is only about 2% of all
counties by count, so ranking by count alone crushed it into a sliver
under 2% of the color ramp -- nothing was clamped anymore, but it still
wasn't visually distinguishable. Coloring by the square root of price,
over the full uncapped range, is what actually balances both ends:
measured directly, it moves the ordinary bulk of counties from a cramped
16-23% of the ramp (straight linear) to 37-45%, while giving California's
own spread a genuine ~25%-wide band instead of being clamped or crushed.
No percentile cap is needed with this transform, so the legend's numeric
endpoints are the real global min/max again.

**Reliability's legend caption shortened** -- dropped the "(not binned
into natural-break classes)" aside, per explicit request.

## v3.2 -- data fix + second map/UI bug-fix round, from real post-deployment use

**Louisiana data gap fixed at the source.** Louisiana counties were
completely missing from the Cost pillar for 2001-2008 (visible on the map as
all-gray for those years) -- this was a real pipeline bug, not an EIA data
gap, confirmed by tracing it with real data: Louisiana is the only U.S.
state whose Census population-file county names end in "Parish" instead of
"County", and the pipeline's population-key cleanup only ever stripped the
"County" suffix. Every Louisiana county's population join silently failed
for those years, which zeroed out its allocated volume and dropped it from
the final output. Fixed with a one-line change in the frozen pipeline
notebook (strip "Parish" too); the pipeline was rerun end-to-end and the
corrected output was independently re-verified against EIA's own published
totals (within 0.01-0.3%) before being loaded into this app. Louisiana now
has real county-level data every year, 2001-2025.

**Map legend, color scale, no-data handling, and click behavior reworked,**
fixing four real bugs the user found using v3.1 for real:

- **The color legend no longer starts with gray, and most counties no
  longer look the same washed-out yellow.** Root cause: the old single-trace
  map reserved a gray band at the bottom of the SAME color ramp real data
  was drawn from (via a sentinel value below the lowest real value), and
  used the single highest value anywhere in the dataset -- a rare outlier --
  as the top of that ramp, crushing ordinary counties into its low end.
  Fixed by splitting the map into two independent Choropleth traces (real
  data vs. no-data), so gray is never part of the real-data ramp at all, and
  by capping the Cost scale's top end at the 98th percentile across all
  counties and years (a handful of outliers above that are simply shown at
  the darkest color, not hidden). Reliability's scale was already a fixed
  0-100 and needed no change.
- **Real values are no longer ever shown as gray "no data."** Root cause:
  the old sentinel approach compared every value against one global floor
  computed across ALL years combined, so a real but relatively low value in
  an early year (confirmed: 19 of 23 Wyoming counties in 2003) could fall
  below that floor and land in the reserved gray band, indistinguishable
  from genuinely missing counties. The two-trace split removes this
  possibility structurally -- a real value is simply never compared against
  a sentinel at all.
- **A new custom legend** (replacing Plotly's native colorbar, which is
  turned off entirely now) matches the reference design: a horizontal
  gradient bar labeled "Lower Price"/"Higher Price" (Cost) or "Lower
  Risk"/"Higher Risk" (Reliability), numeric endpoint values underneath, and
  a separate gray "No data reported" swatch below that, with a short italic
  caption. The Reliability caption describes CRI honestly as a constructed
  0-100 index, not "Jenks natural breaks" -- that phrasing (seen in an
  earlier reference image) doesn't match how CRI is actually computed.
- **Clicking a county no longer dims the whole map.** Root cause: Plotly's
  default behavior is to fade every unselected point once any point is
  selected. Fixed with an explicit "stay fully visible whether selected or
  not" setting on every map trace.

**Click and search are now genuinely different experiences**, resolving the
earlier open question about how they should relate:
- **Click** a county -> a compact, clearly bordered card appears below the
  map with that county's price/CRI, national standing, national median,
  reporting utilities, and national rank **for whichever year the slider is
  currently on** (not always the latest year) -- no trend chart.
- **Search** for a county (the two dropdowns above the map) -> the full
  experience: the same metrics for the latest actual/observed year, plus
  total reported volume (Cost), the full historical + forecast trend chart,
  and (Reliability) the SAIDI/SAIFI history expander.

**Metric fonts rebalanced.** A long explanatory phrase (e.g. "more reliable
than 19% of counties") is no longer rendered at the same oversized font as a
short number -- metrics now show a short value (e.g. "19%") with the
explanatory sentence as a smaller caption underneath.

**Removed:** the "Years of CRI history" line, per explicit request.

## v3.1 -- map rework, fixing real bugs found after deploying v3

After v3 was deployed and tested for real, the map had genuine bugs that
this sandbox's own testing could never have caught (its map rendering could
not be visually verified here at all -- see "A verification note on the
maps" below, carried over from v3). Every one of these is fixed by
rebuilding the map on a different architecture, not patched:

- **State borders no longer mask the county data or block clicks.** Root
  cause: the map was a Plotly *animation* (one frame per year); only the
  very first frame actually carried the county geometry, so every other
  year rendered no county shapes at all -- and nothing to click. The map is
  now a single static choropleth, fully rebuilt on every rerun when the
  year changes. There is no animation anywhere anymore.
- **Alaska and Hawaii are now structurally impossible to show**, not just
  cropped out of view. Root cause: Plotly's `scope='usa'` basemap draws
  AK/HI inset boxes as a fixed part of that basemap, regardless of any
  view-window cropping. That basemap is now turned off entirely
  (`visible=False`); the map shows only our own county choropleth and our
  own state-border lines (dissolved from the same AK/HI-free county
  geometry in `data_prep.py`'s `build_state_borders()`). With no AK/HI
  geometry anywhere in either trace, there's nothing left to draw.
- **Search is back to two dropdowns** -- State, then County (with its
  FIPS) -- replacing the single combined search box.
- **The detail panel always shows the latest actual/observed year**,
  regardless of which year the map slider is on, and regardless of whether
  it was opened by a map click or by searching.
- **The year slider marks every 2 years** (not every single year) with a
  small ruler under the slider, and **forecast-year labels are colored
  differently** from actual-year labels. Every single year is still
  individually selectable via the slider itself -- the ruler is a visual
  guide alongside it.
- **No mention of the specific forecast model's name** anywhere in the UI.
- **No download affordances anywhere** -- chart image export is removed
  from every chart's toolbar, and table CSV/clipboard export is disabled
  app-wide (`.streamlit/config.toml`).

## What was new in v3 (still true in v3.1)

- **2025 data included.** Cost now runs 2001-2025 with a 2026-2028 forecast;
  Reliability now runs 2013-2025 with a 2026-2028 projection.
- **Cost now carries `Reporting_Utilities`** (utility names serving each
  county-year, largest first), matching Reliability's existing convention.
- **Contiguous U.S. only.**
- **Thicker, darker state borders** (now the app's own line trace -- see above).
- **No "About this data and methodology" section anywhere** -- removed per
  request; backtest scorecards, disclosures, and the CRI 100-ceiling
  explanation are gone from the UI.
- **No 68%/CI-level/likely-range/probability numbers shown anywhere** -- not
  in the hover tooltip, the click panel, or the search panel. Forecast years
  are tagged "(forecast)" only. The shaded uncertainty band stays on the
  trend chart as a visual, with no numeric label attached to it.
- **No confidence grade shown anywhere**, and the "no data" legend is a
  single short line ("Gray = not available (no reporting).").
- **Map click and county search open the same detail panel**, always at the
  latest actual/observed year (see v3.1 above). Search additionally shows a
  couple of extra fields (national rank, total volume / years of history)
  that the click panel does not.
- **National comparison stat added for Cost** (`Pct_Counties_MoreExpensive_SameYear`,
  computed once in `data_prep.py`), mirroring Reliability's own pre-computed
  `Pct_Counties_Less_Reliable_SameYear`. Both are scoped to observed years only.

## What's in this folder

- `app.py` -- main entry point: password gate, header, tabs
- `cost_pillar.py`, `reliability_pillar.py`, `availability_pillar.py` --
  each real pillar's page, as its own module so they stay easy to work on
  independently
- `composite_pillar.py` -- honest "not yet available" placeholder
- `map_utils.py` -- shared choropleth styling: the static (non-animated)
  per-rerun choropleth (built as two separate traces -- real data and "no
  data" -- see v3.2 above), the app's own state-border line trace, the
  every-year year ruler (v3.4), click-to-FIPS resolution, the custom HTML
  gradient legend, and the click-dimming fix -- used by all three real
  pillars' maps
- `data_prep.py` -- regenerates the Cost/Reliability files in `data/` from
  each pillar's notebook outputs (run this again whenever either pillar's
  underlying data is refreshed) -- see the top of that file for the exact
  input filenames. Also dissolves the county boundary file into
  `state_borders.json` (see `build_state_borders()`).
- `data_prep_availability.py` -- the Availability pillar's own prep script
  (kept separate from `data_prep.py` since it has its own inputs and its
  own documented data-quality caveats -- see its module docstring). Reads
  `psci_composite_panel.csv` + `psci_composite_proj.csv` (place them
  alongside this script, same names `PSCI_Panel_Pipeline_FIXED_2.ipynb`
  exports) and writes `avail_panel.parquet`, `avail_forecast.parquet`,
  `avail_county_lookup.parquet` to `data/`.
- `data/` -- the static data snapshot the app actually loads: parquet files
  per pillar, plus `counties_fips.json` (contiguous-US-only county boundary
  file, 3,109 counties/county-equivalents -- 48 states + DC, no territories;
  includes Connecticut's 2022+ planning regions, see v3.4 above) and
  `state_borders.json` (per-state boundary lines, dissolved from the same
  county file)
- `assets/mocci_logo.png` -- the MOCCI logo (password screen + header)
- `.streamlit/secrets.toml.example` -- template for the password secret
- `.streamlit/config.toml` -- disables table CSV/clipboard export app-wide
- `requirements.txt`

## Password protection

Gated by a single shared password, checked against `st.secrets["app_password"]`.
The real password is never stored in this folder or in source control --
only `secrets.toml.example` (a template) is included.

**Local run:** copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and put a real password in it. That file is
already in `.gitignore`.

**Streamlit Community Cloud:** no `secrets.toml` file needed in the repo.
After deploying, go to the app's **Settings -> Secrets** and paste:
```
app_password = "your real password here"
```

## Deploy to Streamlit Community Cloud

1. Create a new GitHub repository and push everything in this folder to it
   (the `data/` folder and logo included).
2. Go to https://share.streamlit.io/, connect your GitHub account.
3. Select the repository, branch `main`, main file path `app.py`, deploy.
4. Set the password in the app's Secrets before sharing the link.

## Run locally

```
pip install -r requirements.txt
streamlit run app.py
```

## Updating a pillar's data later

Each pillar's notebook is the source of truth; this app never recomputes
anything, only reshapes and displays what the notebook already validated.

1. Rerun the relevant pillar's notebook, producing fresh output files.
2. Place those fresh files alongside `data_prep.py` (see the paths at the
   top of that script).
3. Run `python3 data_prep.py` -- it regenerates every file in `data/`.
4. Commit and push the updated `data/` files. Streamlit Community Cloud
   redeploys automatically.

## A verification note on the maps

Every Plotly geo trace (`go.Choropleth`, `go.Scattergeo`, any
`projection_type`) fetches a base topology file from `cdn.plot.ly` at
render time, in the browser -- confirmed directly in this rebuild: the
request fires the same way for `'albers usa'` and for `'mercator'`, and
even with the basemap turned off (`visible=False`). This is how Plotly's
geo module works for every deployment, not something specific to this app.
In the sandboxed environment this app was built in, that CDN host is
blocked by the sandbox's own network policy, so **the map itself (the
colored county shapes and the state-border lines) could not be rendered or
visually inspected there, in any version through this v3.3 round.** This is
the same limitation disclosed since v3's README; it is unrelated to -- and
not an explanation for -- the bugs the user found after deploying earlier
versions, which were real code bugs (see the version sections above) now
fixed and verified by other means:

- **`build_static_choropleth()`'s two-trace split** (the real-data trace vs.
  the no-data trace, and the click-dimming fix) was unit-tested directly in
  Python against synthetic data for three cases -- a mix of real and
  missing counties, all-real, and all-missing -- confirming it builds a
  valid figure with the right trace count and `unselected`/`selected`
  marker opacity in every case, independent of rendering.
- **The custom HTML gradient legend and Cost's new square-root color
  scale** were verified two ways: the sqrt-vs-linear-vs-percentile-rank
  comparison in the v3.3 section above was computed directly against this
  app's real price data (not assumed), and the rendered legend (labels,
  gradient CSS, numeric endpoints, no-data swatch, captions) was read back
  directly from a live running instance of the app.
- **The click/search unification and the click-driven dropdown sync** were
  verified directly against the app's real data (not just read, but
  exercised) using Streamlit's own `AppTest` framework, which runs the
  actual app script and reads back its real output: a simulated map click
  was confirmed to populate both search dropdowns with the clicked county,
  render the identical full detail panel a search would (same metrics,
  trend chart, and -- Reliability -- SAIDI/SAIFI expander), survive a
  second click on a different county and a third click back on the first,
  and leave the ordinary search flow (no click involved) working exactly
  as before -- all with zero Python exceptions. The first version of the
  dropdown-sync code was caught failing this exact test (Streamlit
  refuses to overwrite a dropdown after it has already rendered earlier in
  the same script pass) and was corrected before being included here.
- The **state-border dissolution** (`build_state_borders()`) was verified
  visually offline with matplotlib (no CDN dependency) -- a clean,
  recognizable, AK/HI-free contiguous-US outline.
- Everything else that doesn't depend on the geo trace rendering -- the
  year slider and its every-2-years/forecast-colored ruler, the
  two-dropdown search, the comparison table -- was verified directly in a
  running instance of this app, including confirming no Python traceback
  occurs anywhere in that flow.

**What to confirm once deployed (or running locally with real network
access):** the map renders visible, contiguous-US-only county shapes;
Alaska/Hawaii do not appear anywhere, including no empty inset boxes; state
borders read clearly and no longer sit on top of / block the county colors;
a map click on any year (not just the default) opens the correct county's
detail panel; the year ruler's every-2-years marks and forecast-year
coloring look right under the slider; and no download icon appears on any
chart or table.

## Adding the Composite index later

Follow the same pattern used for Availability (see v3.6 above) and before
it, Cost and Reliability: once the composite methodology is validated,
write a real `composite_pillar.py` following `reliability_pillar.py` /
`availability_pillar.py` as the template, and wire it into the Composite
tab in `app.py` in place of the current placeholder import.

## Availability pillar follow-ups

Tracked here rather than as GitHub issues since this is a single-maintainer
research tool -- see v3.7 above and `data_prep_availability.py`'s module
docstring for full context on each:

1. **Connecticut Dim1/Dim2, two fixes still needed in the notebook**
   (geography is already correct as of v3.7):
   - CELL 3/10's `CT_CROSSWALK` dict values must be the bare region name
     (e.g. `'Capitol'`), not the long form (`'Capitol Planning Region'`),
     to match the real TIGER 2024 name field and fix Dim1 (generation).
   - CELL 9's `lookup_fips_local()` needs its own CT_CROSSWALK-based
     fallback added (it currently has none) to fix Dim2 (peak demand,
     population, Primary_BA).
   Once both are fixed and re-verified against real (non-zero) CT values,
   remove the Connecticut suppression block in `data_prep_availability.py`.
2. Decide whether to apply an EIA-930 2016-2017 data-quality caveat to
   County_Peak_MW / S2, consistent with this project's earlier discussion
   of that issue for the Cost/Reliability pillars.
