"""Availability / Capacity pillar page: Power Supply Capacity Index (PSCI),
2016-2025 history + 2026-2028 projection. Real data only -- produced by
PSCI_Panel_Pipeline_FIXED_2.ipynb and converted to the app's parquet
snapshot by data_prep_availability.py (see that file's module docstring
for the full methodology verification and data-quality caveats). The app
never recomputes anything the notebook already computed.

Mirrors reliability_pillar.py's structure and interaction model exactly
(unified click/search detail panel, static per-rerun choropleth, the same
year-slider/ruler, the same peer-window comparison table) -- same
rationale as that file's own docstring, not repeated here.

RISK FRAMING (consistent with Cost's cents/kWh and Reliability's CRI --
"higher score = worse" everywhere in this app):
  Risk_Score = 100 - PSCI_score, 0-100, higher = worse (lower availability).
  PSCI_score itself is also shown (0-100, higher = better) since it's the
  notebook's own native unit and useful alongside the risk framing.

Three sub-dimensions behind PSCI_score (all pooled-percentile-rank based,
see data_prep_availability.py):
  S1 -- generation capacity (Effective_MW)
  S2 (inverted) -- spare peak-demand headroom (County_Peak_MW, inverted:
       lower relative peak demand = more spare capacity = better)
  S3 -- transmission connectivity (TCS_raw, HIFLD 2025 snapshot,
       time-invariant across all 13 years)

KNOWN GAP carried through from data_prep_availability.py (not hidden --
surfaced in the info banner and the no-data legend, same as every other
gap this app already shows this way):
  - Connecticut's 9 planning regions (09110-09190) now match this app's
    FIPS geography, but their Dim1/Dim2 source values are independently
    verified broken (all zero -- a notebook county-matching bug, not a
    real reading), so Risk_Score/PSCI_score are suppressed back to NaN for
    CT at prep time and it still renders as "no data" -- see
    data_prep_availability.py's module docstring for the exact two-part
    notebook fix needed before this can be turned back on.

FORECAST UNCERTAINTY BAND (v2, new): the Risk Score trend chart now shows
a real shaded band for 2026-2028, built from the notebook's own
PSCI_lower/PSCI_upper (re-ranking the S2 demand forecast's confidence
bounds through the same pooled percentile curve as the point estimate,
S1/S3 held fixed -- see data_prep_availability.py). Labeled "S2 demand
uncertainty" in the legend, matching the notebook author's own chosen
label, since it is not a true composite-score confidence interval.
"""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from map_utils import (
    build_static_choropleth, render_year_slider, get_clicked_fips,
    render_gradient_legend, NO_DOWNLOAD_CONFIG,
)

KEY = 'avail'


@st.cache_data
def load_data():
    panel = pd.read_parquet('data/avail_panel.parquet')
    forecast = pd.read_parquet('data/avail_forecast.parquet')
    county_lookup = pd.read_parquet('data/avail_county_lookup.parquet')
    return panel, forecast, county_lookup


def _all_fips_base(geo, county_lookup):
    all_fips = [str(f.get('id', '')).zfill(5) for f in geo['features']]
    base = pd.DataFrame({'FIPS': all_fips}).drop_duplicates('FIPS')
    return base.merge(county_lookup, on='FIPS', how='left')


def _year_df(base, panel, forecast, sel_year, last_observed_year):
    """One row per contiguous county for sel_year, including counties
    with no PSCI value that year (left as NaN -> shown as gray 'no
    data') -- same convention as every other pillar in this app."""
    cols = ['FIPS', 'Risk_Score', 'Risk_Tier']
    if sel_year <= last_observed_year:
        slice_ = panel[panel['Year'] == sel_year][cols]
    else:
        slice_ = forecast[forecast['Year'] == sel_year][cols]
    slice_ = slice_.rename(columns={'Risk_Score': 'Risk_Score_value', 'Risk_Tier': 'Risk_Tier_value'})
    return base.merge(slice_, on='FIPS', how='left')


def _hover_text(df, is_forecast):
    out = []
    for _, r in df.iterrows():
        name = str(r['County_Name']).title() if pd.notna(r.get('County_Name')) else ''
        if pd.isna(r.get('Risk_Score_value')):
            out.append(f"{name}, {r['State']}<br>No data reported")
        else:
            tier = r.get('Risk_Tier_value', '')
            tag = ' (forecast)' if is_forecast else ''
            out.append(f"{name}, {r['State']}<br>Risk Score: {r['Risk_Score_value']:.1f} ({tier}){tag}")
    return out


def render(geo, state_borders):
    panel, forecast, county_lookup = load_data()
    last_observed_year = int(panel['Year'].max())
    forecast_horizon_year = last_observed_year + 3
    base = _all_fips_base(geo, county_lookup)

    # Click/search sync queued by a prior run -- identical mechanism to
    # cost_pillar.py / reliability_pillar.py, see those files for why this
    # has to happen before the search widgets below are instantiated.
    pending_state = st.session_state.get(f'{KEY}_pending_state')
    if pending_state is not None:
        st.session_state[f'{KEY}_search_state'] = pending_state
        st.session_state[f'{KEY}_search_county_{pending_state}'] = st.session_state.get(f'{KEY}_pending_label')
        del st.session_state[f'{KEY}_pending_state']
        del st.session_state[f'{KEY}_pending_label']

    st.info(
        'Drag the slider to select a year from 2016 to 2028. Years 2016–'
        f'{last_observed_year} show actual values, while {last_observed_year + 1}–'
        f'{forecast_horizon_year} show projected values. Click any county on '
        'the map or search for a county name below to view its detailed information '
        'and trends. Connecticut currently shows as "no data" pending a notebook fix to '
        'its generation/demand data (see caveats) -- Cost and Reliability are unaffected.'
    )

    # -------------------------------------------------- search (two dropdowns)
    s1, s2 = st.columns(2)
    state_options = sorted(county_lookup['State'].dropna().unique())
    sel_state = s1.selectbox(
        'State', state_options, index=None, placeholder='Select a state...', key=f'{KEY}_search_state',
    )
    if sel_state:
        county_df = county_lookup[county_lookup['State'] == sel_state].sort_values('County_Name')
        county_labels = [f"{r.County_Name.title()} ({r.FIPS})" for r in county_df.itertuples()]
    else:
        county_labels = []
    sel_county_label = s2.selectbox(
        'County', county_labels, index=None, placeholder='Select a county...',
        key=f'{KEY}_search_county_{sel_state}',
    )

    # ---------------------------------------------------------------- map
    st.subheader("Power Supply Capacity Risk")
    vmin, vmax = 0, 100  # fixed, same as Reliability's CRI

    years = list(range(2016, forecast_horizon_year + 1))
    sel_year = render_year_slider(f'{KEY}_year', years, last_observed_year, last_observed_year)
    is_forecast = sel_year > last_observed_year

    year_df = _year_df(base, panel, forecast, sel_year, last_observed_year)
    fig_map = build_static_choropleth(
        year_df, geo, state_borders, 'Risk_Score_value', 'OrRd', vmin, vmax,
        hover_text=_hover_text(year_df, is_forecast),
    )
    event = st.plotly_chart(
        fig_map, width='stretch', key=f'{KEY}_map',
        on_select='rerun', selection_mode='points', config=NO_DOWNLOAD_CONFIG,
    )
    render_gradient_legend(
        'OrRd', 'Lower Risk / Higher Availability', 'Higher Risk / Lower Availability',
    )

    # ---------------------------------- resolve selection, keeping map click
    # ---------------------------------- and the search dropdowns in sync
    click_fips = get_clicked_fips(event)
    prev_click = st.session_state.get(f'{KEY}_prev_click')

    if click_fips is not None and click_fips != prev_click:
        st.session_state[f'{KEY}_prev_click'] = click_fips
        match = base[base['FIPS'] == click_fips]
        if not match.empty:
            c_state = match.iloc[0]['State']
            c_label = f"{str(match.iloc[0]['County_Name']).title()} ({click_fips})"
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
        _render_detail(panel, forecast, sel_fips, last_observed_year)

    # ======================================================== comparison table
    st.divider()
    _render_comparison(panel, forecast, last_observed_year, sel_fips)


def _national_rank(panel, sel_fips, year):
    """Rank among all U.S. counties with a reported Risk_Score in `year`
    (1 = best availability / lowest risk). None if not covered that year."""
    year_slice = panel[panel['Year'] == year].dropna(subset=['Risk_Score'])
    if year_slice.empty:
        return None
    year_slice = year_slice.sort_values('Risk_Score').reset_index(drop=True)
    row = year_slice[year_slice['FIPS'] == sel_fips]
    if row.empty:
        return None
    return int(row.index[0]) + 1, len(year_slice)


def _render_metrics_block(panel, sel_fips, year):
    row = panel[(panel['FIPS'] == sel_fips) & (panel['Year'] == year)]
    if row.empty or pd.isna(row.iloc[0]['Risk_Score']):
        st.metric(f'Risk Score ({year})', f'No {year} data')
        st.caption('No data reported for this county in this year (see Connecticut caveat above if applicable).')
        return
    r = row.iloc[0]

    m1, m2, m3 = st.columns(3)
    m1.metric(f'Risk Score ({year})', f"{r['Risk_Score']:.1f}", r['Risk_Tier'])
    m2.metric('PSCI Score', f"{r['PSCI_score']:.1f}")
    m2.caption('0-100, higher = better availability (notebook\'s native unit)')
    better_pct = r.get('Pct_Counties_BetterAvailability_SameYear')
    if pd.notna(better_pct):
        m3.metric('National standing', f"Top {100 - better_pct:.0f}%")
        m3.caption(f"better availability than {better_pct:.0f}% of counties")
    else:
        m3.metric('National standing', 'N/A')

    n1, n2, n3 = st.columns(3)
    n1.metric(f'Generation capacity (S1)', f"{r['Effective_MW']:,.0f} MW")
    n1.caption(f"National median: {r['National_Median_Effective_MW_SameYear']:,.0f} MW")
    n2.metric(f'Peak demand (S2)', f"{r['County_Peak_MW']:,.0f} MW")
    n2.caption(f"National median: {r['National_Median_Peak_MW_SameYear']:,.0f} MW")
    n3.metric(f'Transmission score (S3)', f"{r['TCS_raw']:,.0f} vol-wtd mi")
    n3.caption(f"National median: {r['National_Median_TCS_SameYear']:,.0f} vol-wtd mi (time-invariant)")

    primary_ba = r.get('Primary_BA')
    if isinstance(primary_ba, str) and primary_ba and primary_ba != 'N/A (projected)':
        st.caption(f"Primary balancing authority: {primary_ba}")
    rank_info = _national_rank(panel, sel_fips, year)
    if rank_info:
        rank, n_total = rank_info
        st.caption(f"National rank ({year}): **#{rank} best availability** of {n_total:,} U.S. counties")


def _render_detail(panel, forecast, sel_fips, last_observed_year):
    """Always the full experience, always the latest observed year --
    identical whether sel_fips came from a map click or a search."""
    p_sel = panel[panel['FIPS'] == sel_fips].sort_values('Year')
    f_sel = forecast[forecast['FIPS'] == sel_fips].sort_values('Year')
    if p_sel.empty and f_sel.empty:
        st.warning('No data for this county.')
        return
    name_row = (p_sel.iloc[-1] if not p_sel.empty else f_sel.iloc[-1])
    st.subheader(f"{name_row['County_Name'].title()}, {name_row['State']}")

    _render_metrics_block(panel, sel_fips, last_observed_year)

    # ------------------------------------------------- Risk Score trend chart
    p_sel_valid = p_sel.dropna(subset=['Risk_Score'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p_sel['Year'], y=p_sel['Risk_Score'], mode='lines+markers',
                              name='Observed', line=dict(color='#1f77b4', width=2),
                              connectgaps=False))
    if not f_sel.empty and not p_sel_valid.empty:
        bridge_year = pd.concat([p_sel_valid['Year'].tail(1), f_sel['Year']])
        bridge_risk = pd.concat([p_sel_valid['Risk_Score'].tail(1), f_sel['Risk_Score']])
        has_band = f_sel['Risk_Score_Lower'].notna().all() and f_sel['Risk_Score_Upper'].notna().all()
        if has_band:
            upper = pd.concat([p_sel_valid['Risk_Score'].tail(1), f_sel['Risk_Score_Upper']])
            lower = pd.concat([p_sel_valid['Risk_Score'].tail(1), f_sel['Risk_Score_Lower']])
            fig.add_trace(go.Scatter(
                x=pd.concat([bridge_year, bridge_year[::-1]]),
                y=pd.concat([upper, lower[::-1]]),
                fill='toself', fillcolor='rgba(227,74,51,0.18)',
                line=dict(color='rgba(255,255,255,0)'), hoverinfo='skip',
                name='S2 demand uncertainty', showlegend=True,
            ))
        fig.add_trace(go.Scatter(x=bridge_year, y=bridge_risk, mode='lines+markers',
                                  name='Projected', line=dict(color='#e34a33', width=2, dash='dash'),
                                  hovertemplate='%{x}: %{y:.1f} (forecast)<extra></extra>'))
    fig.update_layout(
        xaxis_title='Year', yaxis_title='Risk Score (0-100, higher = worse)',
        xaxis=dict(tickformat='d', dtick=1),
        height=380, margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation='h', y=1.12), hovermode='x unified',
        yaxis_range=[0, 100],
    )
    st.plotly_chart(fig, width='stretch', key=f'{KEY}_trend_{sel_fips}', config=NO_DOWNLOAD_CONFIG)
    if not f_sel.empty:
        st.caption(
            'The shaded band reflects S2 (peak-demand) forecast uncertainty only, re-ranked '
            'through the same pooled percentile curve as the point estimate -- S1 and S3 have '
            'no modeled uncertainty, so it is not a full composite-score confidence interval.'
        )

    # ------------------------------------------------- sub-score breakdown
    with st.expander('Sub-score breakdown (latest observed year)'):
        latest = p_sel.dropna(subset=['PSCI_score'])
        if latest.empty:
            st.caption('No sub-score data available for this county.')
        else:
            r = latest.iloc[-1]
            labels = ['Generation capacity (S1)', 'Spare peak-demand capacity (S2, inverted)',
                      'Transmission connectivity (S3)']
            values = [r['S1_score'] * 100, r['S2_inv_score'] * 100, r['S3_score'] * 100]
            fig3 = go.Figure(go.Bar(
                x=values, y=labels, orientation='h',
                marker=dict(color=['#4575b4', '#91bfdb', '#fc8d59']),
                text=[f"{v:.0f}" for v in values], textposition='outside',
            ))
            fig3.update_layout(
                xaxis=dict(title='Pooled percentile rank (0-100, higher = better)', range=[0, 105]),
                height=260, margin=dict(l=10, r=10, t=20, b=10),
            )
            st.plotly_chart(fig3, width='stretch', key=f'{KEY}_subscores_{sel_fips}', config=NO_DOWNLOAD_CONFIG)
            st.caption(f"As of {int(r['Year'])}. Each sub-score is this county's pooled percentile rank "
                       "among all 40,404 county-years (2016-2028) -- not a raw physical quantity.")

    # ------------------------------------------------- supply vs demand
    with st.expander('Supply vs. demand trend (generation vs. peak demand)'):
        hist = p_sel[['Year', 'Effective_MW', 'County_Peak_MW']]
        fc = f_sel[['Year', 'Effective_MW', 'County_Peak_MW']]
        combo = pd.concat([hist, fc]).sort_values('Year')
        if combo.empty:
            st.caption('No generation/demand history available for this county.')
        else:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=combo['Year'], y=combo['Effective_MW'],
                                       name='Generation capacity (MW)', mode='lines+markers',
                                       line=dict(color='#1f77b4'), yaxis='y1'))
            fig2.add_trace(go.Scatter(x=combo['Year'], y=combo['County_Peak_MW'],
                                       name='Peak demand (MW)', mode='lines+markers',
                                       line=dict(color='#e35b1e'), yaxis='y2'))
            if not fc.empty:
                fig2.add_vrect(x0=last_observed_year + 0.5, x1=combo['Year'].max() + 0.5,
                                fillcolor='rgba(0,0,0,0.05)', line_width=0)
            fig2.update_layout(
                height=320, margin=dict(l=10, r=10, t=20, b=10),
                xaxis=dict(title='Year', tickformat='d', dtick=1),
                yaxis=dict(title='Generation capacity (MW)'),
                yaxis2=dict(title='Peak demand (MW)', overlaying='y', side='right'),
                legend=dict(orientation='h', y=1.15),
            )
            st.plotly_chart(fig2, width='stretch', key=f'{KEY}_supply_demand_{sel_fips}', config=NO_DOWNLOAD_CONFIG)
            st.caption('Shaded region marks the projected (2026-2028) years. Unlike Reliability\'s '
                       'SAIDI/SAIFI, both series here are projected, not history-only.')


def _display_availability_comparison(table, forecast_horizon_year, show_rank):
    cols = (['Rank'] if show_rank else []) + [
        'FIPS', 'State', 'County_Name', 'Last_Year', 'Risk_Score', 'Risk_Tier',
        'Pct_Counties_BetterAvailability_SameYear', 'Projected_Risk_Score',
        'Projected_Risk_Tier', 'Change_to_forecast_pct',
    ]
    st.dataframe(
        table[cols].rename(columns={
            'Last_Year': 'Last observed year', 'Risk_Score': 'Last observed Risk Score',
            'Risk_Tier': 'Tier',
            'Pct_Counties_BetterAvailability_SameYear': 'Better availability than % of counties',
            'Projected_Risk_Score': f'{forecast_horizon_year} Projected Risk Score',
            'Projected_Risk_Tier': f'{forecast_horizon_year} Tier',
            'Change_to_forecast_pct': f'Change to {forecast_horizon_year} (%)',
        }).round(1),
        width='stretch', hide_index=True,
    )


def _render_comparison(panel, forecast, last_observed_year, sel_fips):
    """Mirrors reliability_pillar.py's _render_comparison exactly (peer
    window centered on the selected county vs. a top/bottom-N leaderboard,
    both scoped to all contiguous U.S. or one state) -- see that file for
    the full rationale, not repeated here."""
    st.subheader('Compare counties')
    latest_panel = panel.sort_values('Year').drop_duplicates('FIPS', keep='last').set_index('FIPS')
    forecast_horizon_year = last_observed_year + 3
    fc_last = forecast[forecast['Year'] == forecast_horizon_year][
        ['FIPS', 'Risk_Score', 'Risk_Tier']
    ].rename(columns={'Risk_Score': 'Projected_Risk_Score', 'Risk_Tier': 'Projected_Risk_Tier'})

    states = sorted(panel['State'].dropna().unique())
    table = latest_panel.reset_index().rename(columns={'Year': 'Last_Year'})
    table = table.merge(fc_last, on='FIPS', how='left')
    table['County_Name'] = table['County_Name'].str.title()
    table['Change_to_forecast_pct'] = (
        (table['Projected_Risk_Score'] - table['Risk_Score']) / table['Risk_Score'] * 100
    ).where(table['Risk_Score'] > 0)

    mode = (
        st.radio('Compare to', ['Peers of selected county', 'Top / bottom list'],
                  horizontal=True, key=f'{KEY}_cmp_mode')
        if sel_fips is not None else 'Top / bottom list'
    )

    c1, c2, c3 = st.columns(3)
    scope = c1.radio('Scope', ['All contiguous U.S.', 'One state'], horizontal=True, key=f'{KEY}_scope')
    if scope == 'One state':
        state_kwargs = {} if f'{KEY}_cmp_state' in st.session_state else {
            'index': states.index('MO') if 'MO' in states else 0,
        }
        sel_cmp_state = c1.selectbox('State', states, key=f'{KEY}_cmp_state', **state_kwargs)
        table_scoped = table[table['State'] == sel_cmp_state]
    else:
        table_scoped = table

    if mode == 'Peers of selected county':
        n_show = c3.slider('Counties each side', 3, 20, 7, key=f'{KEY}_n_peers')
        ranked = table_scoped.dropna(subset=['Risk_Score']).sort_values('Risk_Score').reset_index(drop=True)
        match_idx = ranked.index[ranked['FIPS'] == sel_fips]
        if match_idx.empty:
            st.caption(
                'The selected county has no observed data in this scope -- showing '
                'the best-availability counties in this scope instead.'
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
                f"Ranked by {last_observed_year} Risk Score within "
                f"{'the selected state' if scope == 'One state' else 'the contiguous U.S.'} "
                f"-- ⭐ marks the selected county (#{center + 1} of {len(ranked):,})."
            )
        _display_availability_comparison(window, forecast_horizon_year, show_rank=True)
    else:
        sort_options = {
            f'Last observed Risk Score ({last_observed_year}, worst first)': ('Risk_Score', False),
            f'Last observed Risk Score ({last_observed_year}, best first)': ('Risk_Score', True),
            f'{forecast_horizon_year} projected Risk Score (worst first)': ('Projected_Risk_Score', False),
            f'{forecast_horizon_year} projected Risk Score (best first)': ('Projected_Risk_Score', True),
        }
        sort_choice = c2.selectbox('Sort by', list(sort_options.keys()), index=2, key=f'{KEY}_sort')
        n_show = c3.slider('Counties to show', 5, 50, 15, key=f'{KEY}_n')
        col, asc = sort_options[sort_choice]
        window = table_scoped.sort_values(col, ascending=asc, na_position='last').head(n_show)
        _display_availability_comparison(window, forecast_horizon_year, show_rank=False)
