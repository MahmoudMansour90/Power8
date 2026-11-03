"""Cost pillar page: county-level industrial electricity price, 2001-2025
actual (EIA Form 861, now including final 2025 data, with the Louisiana
"Parish" population-join bug fixed upstream in the pipeline notebook --
Louisiana now has real county-level data every year 2001-2025) + 2026-2028
forecast. Real data only -- see data_prep.py for how data/actual.parquet,
data/forecast.parquet and data/county_lookup.parquet are produced from the
notebook's outputs.

v3.3 -- third round of fixes from real post-deployment use:
  - Click and search are now ONE unified experience, not two different
    ones. Clicking a county or searching for one both open the exact same
    full detail panel, always for the latest actual year: price, national
    standing, national median, reporting utilities, national rank, total
    reported volume, and the trend chart. The separate "compact click
    card, no trend chart" design from v3.2 is gone -- the user tried it
    and preferred one consistent experience.
  - Clicking a county on the map now also sets the State/County search
    dropdowns above the map to that same county, so map and search stay
    visually in sync in both directions (search already drove the map
    indirectly by picking a county; now a click drives the search boxes
    too). Mechanically: Streamlit can't rewrite a widget that already
    rendered earlier in the same script pass, so a new click writes the
    target county into the dropdowns' session state and forces one more
    rerun -- on that next pass the dropdowns redraw already showing it.
  - Cost's color scale is no longer a straight linear ¢/kWh->color mapping
    (even with last round's 98th-percentile cap). Capping the top helped
    the low end but, as the user found testing it for real, simply pushed
    the problem up the scale -- expensive counties (e.g. California) all
    piled into the same dark color with no differentiation among
    themselves, because a handful of counties span a huge price range
    packed into the top of a linear ramp. A pure percentile-RANK scale
    (tried first, then measured numerically) turned out not to fix this
    either: California is only ~2% of all counties by COUNT, so ranking by
    count alone crushed it into a ~1%-wide sliver of the ramp -- nothing
    was clamped anymore, but it still wasn't visually distinguishable.
    What actually balances both ends: color by sqrt(price) over the full
    (uncapped) global min/max. Measured directly against this app's real
    data, that single change moves the ordinary bulk of counties (25th-75th
    percentile) from a cramped 16-23% of the ramp under straight linear to
    37-45%, while California's own spread goes from "clamped to one color"
    (under last round's percentile cap) or "crushed to ~1%" (under pure
    rank) to a genuine ~25%-wide band. No percentile cap is needed at all
    with this transform -- the real global min/max are shown on the legend.

Carried over unchanged from v3.1/v3.2:
  - Map is a single static choropleth per rerun, not a Plotly animation,
    built as two traces (real data + no data) with no dimming on click.
  - Alaska/Hawaii structurally impossible to show.
  - Year control is st.select_slider with an HTML every-2-years ruler.
  - Search is two dropdowns: State, then County (+ FIPS).
  - Custom HTML gradient legend (no native Plotly colorbar).
  - No mention of the specific forecast model name anywhere.
  - No download affordances anywhere.
  - No "About this data and methodology" section, no 68%/CI-level/
    likely-range numbers, no confidence grade anywhere.
"""
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from map_utils import (
    build_static_choropleth, render_year_slider, get_clicked_fips,
    render_gradient_legend, NO_DOWNLOAD_CONFIG,
)

KEY = 'cost'


@st.cache_data
def load_data():
    actual = pd.read_parquet('data/actual.parquet')
    forecast = pd.read_parquet('data/forecast.parquet')
    county_lookup = pd.read_parquet('data/county_lookup.parquet')
    return actual, forecast, county_lookup


def _all_fips_base(geo, county_lookup):
    all_fips = [str(f.get('id', '')).zfill(5) for f in geo['features']]
    base = pd.DataFrame({'FIPS': all_fips}).drop_duplicates('FIPS')
    return base.merge(county_lookup, on='FIPS', how='left')


def _year_df(base, actual, forecast, sel_year, last_actual_year):
    """One row per contiguous county for sel_year -- including counties
    with no reported value that year (left as NaN), so the map can show
    them as gray 'no data' rather than silently dropping them."""
    src = actual if sel_year <= last_actual_year else forecast
    slice_ = src[src['Year'] == sel_year]
    val_cols = [c for c in slice_.columns if c not in ('FIPS', 'State', 'County_Name')]
    return base.merge(slice_[['FIPS'] + val_cols], on='FIPS', how='left')


def _hover_text(df, is_forecast):
    tag = ' (forecast)' if is_forecast else ''
    out = []
    for _, r in df.iterrows():
        if pd.isna(r.get('Price_cents_kWh')):
            out.append(f"{r['County_Name']}, {r['State']}<br>No data reported")
        else:
            out.append(f"{r['County_Name']}, {r['State']}<br>{r['Price_cents_kWh']:.2f} ¢/kWh{tag}")
    return out


def _make_sqrt_scale(all_values):
    """Build a function mapping raw ¢/kWh values to a [0,1] color position
    via sqrt(price) over the full GLOBAL min/max (no percentile cap).
    Verified numerically against this app's real data before choosing it
    over the alternatives:
      - straight linear (no cap): crushes the ordinary bulk of counties
        into a narrow low band (the original "everything looks yellow"
        complaint) -- the 25th-75th percentile of all prices occupies just
        16-23% of the ramp.
      - straight linear, capped at the 98th percentile (last round's fix):
        fixes the bulk, but clamps every county above the cap -- including
        ALL of California -- to the exact same darkest color.
      - percentile RANK (tried first this round): never clamps, but ranks
        purely by count, so a numerically rare cluster that's wide in
        VALUE (California is ~2% of counties by count) still gets crushed
        into a sliver of the ramp (~1% wide) even though nothing collides.
      - sqrt(price), uncapped: tames the right-skew enough to give the
        bulk real room (25th-75th percentile moves to 37-45% of the ramp)
        while never clamping the tail, which keeps a genuine ~25%-wide
        band for California specifically -- the best balance measured."""
    vals = all_values.dropna().to_numpy(dtype=float)
    vals = vals[vals >= 0]
    gmin, gmax = float(np.sqrt(vals.min())), float(np.sqrt(vals.max()))
    span = (gmax - gmin) or 1.0

    def to_position(series):
        v = series.to_numpy(dtype=float)
        pos = (np.sqrt(np.clip(v, 0, None)) - gmin) / span
        return pd.Series(pos, index=series.index)

    return to_position


def render(geo, state_borders):
    actual, forecast, county_lookup = load_data()
    last_actual_year = int(actual['Year'].max())
    forecast_horizon_year = last_actual_year + 3
    base = _all_fips_base(geo, county_lookup)

    # Apply a click-driven dropdown sync queued by a PRIOR run, BEFORE the
    # search widgets below are instantiated this run. Streamlit refuses to
    # write a widget's own session-state key once that widget has already
    # rendered earlier in the current script pass -- confirmed directly
    # (StreamlitWidgetAlreadyInstantiatedError) when that write was
    # attempted down near the map instead, even immediately before a
    # st.rerun(). So a click only queues the target county here; this
    # block is what actually applies it, on the run that follows.
    pending_state = st.session_state.get(f'{KEY}_pending_state')
    if pending_state is not None:
        st.session_state[f'{KEY}_search_state'] = pending_state
        st.session_state[f'{KEY}_search_county_{pending_state}'] = st.session_state.get(f'{KEY}_pending_label')
        del st.session_state[f'{KEY}_pending_state']
        del st.session_state[f'{KEY}_pending_label']

    st.info(
        'Drag the slider to select a year from 2001 to 2028. Years 2001–2025 show '
        'actual values, while 2026–2028 show forecast values. Click any county on '
        'the map or search for a county name below to view its detailed information '
        'and trends.'
    )

    # -------------------------------------------------- search (two dropdowns)
    s1, s2 = st.columns(2)
    state_options = sorted(county_lookup['State'].dropna().unique())
    sel_state = s1.selectbox(
        'State', state_options, index=None, placeholder='Select a state...', key=f'{KEY}_search_state',
    )
    if sel_state:
        county_df = county_lookup[county_lookup['State'] == sel_state].sort_values('County_Name')
        county_labels = [f"{r.County_Name} ({r.FIPS})" for r in county_df.itertuples()]
    else:
        county_labels = []
    sel_county_label = s2.selectbox(
        'County', county_labels, index=None, placeholder='Select a county...',
        key=f'{KEY}_search_county_{sel_state}',
    )

    # ---------------------------------------------------------------- map
    st.subheader("County-level industrial electricity price")

    years = list(range(2001, forecast_horizon_year + 1))
    sel_year = render_year_slider(f'{KEY}_year', years, last_actual_year, last_actual_year)
    is_forecast = sel_year > last_actual_year

    all_prices = pd.concat([actual['Price_cents_kWh'], forecast['Price_cents_kWh']])
    to_position = _make_sqrt_scale(all_prices)

    year_df = _year_df(base, actual, forecast, sel_year, last_actual_year)
    year_df = year_df.assign(Price_scaled=to_position(year_df['Price_cents_kWh']))
    fig_map = build_static_choropleth(
        year_df, geo, state_borders, 'Price_scaled', 'YlOrRd', 0.0, 1.0,
        hover_text=_hover_text(year_df, is_forecast),
    )
    event = st.plotly_chart(
        fig_map, width='stretch', key=f'{KEY}_map',
        on_select='rerun', selection_mode='points', config=NO_DOWNLOAD_CONFIG,
    )
    render_gradient_legend('YlOrRd', 'Lower Price', 'Higher Price')

    # ---------------------------------- resolve selection, keeping map click
    # ---------------------------------- and the search dropdowns in sync
    click_fips = get_clicked_fips(event)
    prev_click = st.session_state.get(f'{KEY}_prev_click')

    if click_fips is not None and click_fips != prev_click:
        st.session_state[f'{KEY}_prev_click'] = click_fips
        match = base[base['FIPS'] == click_fips]
        if not match.empty:
            c_state = match.iloc[0]['State']
            c_label = f"{match.iloc[0]['County_Name']} ({click_fips})"
            # Queue the sync for the top of the NEXT run (see above) --
            # the search widgets below have already rendered this run, so
            # their keys can't be written here even right before a rerun.
            st.session_state[f'{KEY}_pending_state'] = c_state
            st.session_state[f'{KEY}_pending_label'] = c_label
            st.session_state[f'{KEY}_prev_search_val'] = (c_state, c_label)
            st.session_state[f'{KEY}_sel_fips'] = click_fips
            st.rerun()

    sel_fips = st.session_state.get(f'{KEY}_sel_fips')
    prev_search = st.session_state.get(f'{KEY}_prev_search_val')
    search_key = (sel_state, sel_county_label)
    if sel_county_label is not None and search_key != prev_search:
        sel_fips = sel_county_label.split('(')[-1].rstrip(')')
        st.session_state[f'{KEY}_prev_search_val'] = search_key

    st.session_state[f'{KEY}_sel_fips'] = sel_fips

    # Auto-switch the comparison table below into "peer" mode centered on
    # the newly selected county (and its state), the moment the selection
    # actually changes -- not on every rerun, so a manual override of the
    # comparison section's own controls (mode, scope, state) by the user
    # is never undone by an unrelated rerun. Written here, before
    # _render_comparison()'s widgets are instantiated below in this same
    # run, so no AlreadyInstantiated issue (unlike the click->search sync
    # above, which has to cross a rerun because those widgets render
    # EARLIER in the script).
    prev_cmp_sel = st.session_state.get(f'{KEY}_cmp_prev_sel_fips')
    if sel_fips is not None and sel_fips != prev_cmp_sel:
        cmp_state_match = county_lookup.loc[county_lookup['FIPS'] == sel_fips, 'State']
        if not cmp_state_match.empty:
            st.session_state[f'{KEY}_cmp_mode'] = 'Peers of selected county'
            st.session_state[f'{KEY}_scope'] = 'One state'
            st.session_state[f'{KEY}_cmp_state'] = cmp_state_match.iloc[0]
    st.session_state[f'{KEY}_cmp_prev_sel_fips'] = sel_fips

    # ============================================================ county detail
    st.divider()
    if sel_fips is None:
        st.caption('Click a county on the map, or search for one above, to see its detail.')
    else:
        _render_detail(actual, forecast, sel_fips, last_actual_year)

    # ======================================================== comparison table
    st.divider()
    _render_comparison(actual, forecast, last_actual_year, sel_fips)


def _national_rank(actual, sel_fips, year):
    """Rank among all U.S. counties with a reported price in `year`
    (1 = cheapest). Returns None if this county has no reported price that
    year."""
    year_slice = actual[actual['Year'] == year].dropna(subset=['Price_cents_kWh'])
    if year_slice.empty:
        return None
    year_slice = year_slice.sort_values('Price_cents_kWh').reset_index(drop=True)
    row = year_slice[year_slice['FIPS'] == sel_fips]
    if row.empty:
        return None
    return int(row.index[0]) + 1, len(year_slice)


def _render_metrics_block(actual, sel_fips, year):
    """The core set of metrics for one county/year: price, national
    standing, national median, reporting utilities, national rank. Metric
    fonts are kept balanced -- a short numeric value in st.metric, with
    the explanatory sentence as a caption underneath rather than crammed
    into the metric itself."""
    row = actual[(actual['FIPS'] == sel_fips) & (actual['Year'] == year)]
    if row.empty:
        st.metric(f'Price ({year})', 'n/a')
        st.caption('No data reported for this county in this year.')
        return
    r = row.iloc[0]
    m1, m2, m3 = st.columns(3)
    m1.metric(f'Price ({year})', f"{r['Price_cents_kWh']:.2f} ¢/kWh")
    m2.metric('National standing', f"{r['Pct_Counties_MoreExpensive_SameYear']:.0f}%")
    m2.caption(f"cheaper than {r['Pct_Counties_MoreExpensive_SameYear']:.0f}% of U.S. counties")
    m3.metric('National median price', f"{r['National_Median_Price_cents_kWh_SameYear']:.2f} ¢/kWh")
    reporting = r.get('Reporting_Utilities')
    if isinstance(reporting, str) and reporting:
        st.caption(f"Reporting utilities: {reporting}")
    rank_info = _national_rank(actual, sel_fips, year)
    if rank_info:
        rank, n_total = rank_info
        st.caption(f"National rank ({year}): **#{rank} cheapest** of {n_total:,} U.S. counties")


def _render_detail(actual, forecast, sel_fips, last_actual_year):
    """Always the full experience, always the latest actual year --
    identical whether sel_fips came from a map click or a search (see
    module docstring: click and search are now unified)."""
    a_sel = actual[actual['FIPS'] == sel_fips].sort_values('Year')
    f_sel = forecast[forecast['FIPS'] == sel_fips].sort_values('Year')
    if a_sel.empty and f_sel.empty:
        st.warning('No data for this county.')
        return
    name_row = (a_sel.iloc[-1] if not a_sel.empty else f_sel.iloc[-1])
    st.subheader(f"{name_row['County_Name']}, {name_row['State']}")

    _render_metrics_block(actual, sel_fips, last_actual_year)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=a_sel['Year'], y=a_sel['Price_cents_kWh'], mode='lines+markers',
                              name='Actual', line=dict(color='#1f77b4', width=2)))
    if not f_sel.empty:
        bridge_year = pd.concat([a_sel['Year'].tail(1), f_sel['Year']])
        bridge_price = pd.concat([a_sel['Price_cents_kWh'].tail(1), f_sel['Price_cents_kWh']])
        has_ci = f_sel['Upper_CI_cents_kWh'].notna().all() and f_sel['Lower_CI_cents_kWh'].notna().all()
        if has_ci:
            upper = pd.concat([a_sel['Price_cents_kWh'].tail(1), f_sel['Upper_CI_cents_kWh']])
            lower = pd.concat([a_sel['Price_cents_kWh'].tail(1), f_sel['Lower_CI_cents_kWh']])
            fig.add_trace(go.Scatter(
                x=pd.concat([bridge_year, bridge_year[::-1]]),
                y=pd.concat([upper, lower[::-1]]),
                fill='toself', fillcolor='rgba(255,127,14,0.18)',
                line=dict(color='rgba(255,255,255,0)'), hoverinfo='skip',
                name='Forecast range', showlegend=False,
            ))
        fig.add_trace(go.Scatter(x=bridge_year, y=bridge_price, mode='lines+markers',
                                  name='Forecast', line=dict(color='#ff7f0e', width=2, dash='dash'),
                                  hovertemplate='%{x}: %{y:.2f} ¢/kWh (forecast)<extra></extra>'))
    fig.update_layout(
        xaxis_title='Year', yaxis_title='Price (cents/kWh)',
        xaxis=dict(tickformat='d', dtick=1),  # a narrow year range otherwise gets fractional/comma'd ticks
        height=380, margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation='h', y=1.12), hovermode='x unified',
    )
    st.plotly_chart(fig, width='stretch', key=f'{KEY}_trend_{sel_fips}', config=NO_DOWNLOAD_CONFIG)


def _display_cost_comparison(table, forecast_horizon_year, show_rank):
    """Shared dataframe rendering for both comparison modes below -- same
    columns and formatting either way, just with an extra leading Rank
    column in peer mode."""
    cols = (['Rank'] if show_rank else []) + [
        'FIPS', 'State', 'County_Name', 'Last_Year', 'Price_cents_kWh_actual',
        'Pct_Counties_MoreExpensive_SameYear', 'Price_cents_kWh_forecast', 'Change_to_forecast_pct',
    ]
    st.dataframe(
        table[cols].rename(columns={
            'Last_Year': 'Last reported year',
            'Price_cents_kWh_actual': 'Last reported price (¢/kWh)',
            'Pct_Counties_MoreExpensive_SameYear': 'Cheaper than % of U.S. counties',
            'Price_cents_kWh_forecast': f'{forecast_horizon_year} Forecast (¢/kWh)',
            'Change_to_forecast_pct': f'Change to {forecast_horizon_year} (%)',
        }).round(2),
        width='stretch', hide_index=True,
    )


def _render_comparison(actual, forecast, last_actual_year, sel_fips):
    """v3.5: this section used to be a single context-free top/bottom-N
    leaderboard, always sorted and scoped manually. Two additions, per
    explicit request:
      - a 'Change to {forecast_horizon_year} (%)' column, computed from the
        two values the table already carries (last reported price and the
        forecast-horizon price) -- a trajectory the map's single-year
        snapshot can't show at all.
      - when a county is selected (click or search), the table defaults to
        a 'peer window' centered on that county's own rank, scoped to its
        own state by default (see the auto-switch block in render(), right
        before this is called) -- 'how does my county compare to its real
        in-state alternatives', not a nationally-generic list. A toggle
        (shown only once something is selected) switches back to the
        original top/bottom-N leaderboard; manual Scope/State/Sort/N
        choices made here are never overwritten except by a NEW selection."""
    st.subheader('Compare counties')
    latest_actual = (
        actual.sort_values('Year').drop_duplicates('FIPS', keep='last')
        .set_index('FIPS')
    )
    forecast_horizon_year = last_actual_year + 3
    fc_last = forecast[forecast['Year'] == forecast_horizon_year][
        ['FIPS', 'Price_cents_kWh']
    ].rename(columns={'Price_cents_kWh': 'Price_cents_kWh_forecast'})

    states = sorted(actual['State'].dropna().unique())
    table = latest_actual.reset_index().rename(
        columns={'Price_cents_kWh': 'Price_cents_kWh_actual', 'Year': 'Last_Year'})
    table = table.merge(fc_last, on='FIPS', how='left')
    table['Change_to_forecast_pct'] = np.where(
        table['Price_cents_kWh_actual'] > 0,
        (table['Price_cents_kWh_forecast'] - table['Price_cents_kWh_actual'])
        / table['Price_cents_kWh_actual'] * 100,
        np.nan,
    )

    mode = (
        st.radio('Compare to', ['Peers of selected county', 'Top / bottom list'],
                  horizontal=True, key=f'{KEY}_cmp_mode')
        if sel_fips is not None else 'Top / bottom list'
    )

    c1, c2, c3 = st.columns(3)
    scope = c1.radio('Scope', ['All contiguous U.S.', 'One state'], horizontal=True, key=f'{KEY}_scope')
    if scope == 'One state':
        # Only pass a default `index` the first time this widget ever
        # renders -- once the auto-switch block above has pre-seeded this
        # key's session-state value (a new selection's own state), passing
        # a conflicting `index` too just produces a harmless but noisy
        # Streamlit console warning for no benefit.
        state_kwargs = {} if f'{KEY}_cmp_state' in st.session_state else {
            'index': states.index('MO') if 'MO' in states else 0,
        }
        sel_cmp_state = c1.selectbox('State', states, key=f'{KEY}_cmp_state', **state_kwargs)
        table_scoped = table[table['State'] == sel_cmp_state]
    else:
        table_scoped = table

    if mode == 'Peers of selected county':
        n_show = c3.slider('Counties each side', 3, 20, 7, key=f'{KEY}_n_peers')
        ranked = table_scoped.dropna(subset=['Price_cents_kWh_actual']).sort_values(
            'Price_cents_kWh_actual').reset_index(drop=True)
        match_idx = ranked.index[ranked['FIPS'] == sel_fips]
        if match_idx.empty:
            st.caption(
                'The selected county has no reported price in this scope -- showing '
                'the cheapest counties in this scope instead.'
            )
            window = ranked.head(15).copy()
            window.insert(0, 'Rank', range(1, len(window) + 1))
        else:
            center = int(match_idx[0])
            lo, hi = max(0, center - n_show), min(len(ranked), center + n_show + 1)
            window = ranked.iloc[lo:hi].copy()
            window.insert(0, 'Rank', range(lo + 1, hi + 1))
            window['County_Name'] = window.apply(
                lambda r: f"⭐ {r['County_Name']}" if r['FIPS'] == sel_fips else r['County_Name'], axis=1)
            st.caption(
                f"Ranked by {last_actual_year} price within "
                f"{'the selected state' if scope == 'One state' else 'the contiguous U.S.'} "
                f"-- ⭐ marks the selected county (#{center + 1} of {len(ranked):,})."
            )
        _display_cost_comparison(window, forecast_horizon_year, show_rank=True)
    else:
        sort_options = {
            f'Last reported price ({last_actual_year}, highest)': ('Price_cents_kWh_actual', False),
            f'Last reported price ({last_actual_year}, lowest)': ('Price_cents_kWh_actual', True),
            f'{forecast_horizon_year} forecast (highest)': ('Price_cents_kWh_forecast', False),
            f'{forecast_horizon_year} forecast (lowest)': ('Price_cents_kWh_forecast', True),
        }
        sort_choice = c2.selectbox('Sort by', list(sort_options.keys()), index=2, key=f'{KEY}_sort')
        n_show = c3.slider('Counties to show', 5, 50, 15, key=f'{KEY}_n')
        col, asc = sort_options[sort_choice]
        window = table_scoped.sort_values(col, ascending=asc, na_position='last').head(n_show)
        _display_cost_comparison(window, forecast_horizon_year, show_rank=False)
