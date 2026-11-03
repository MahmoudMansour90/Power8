"""
Shared choropleth-map styling for every pillar's page, so the maps look and
behave consistently app-wide (same state-border treatment, same "no data"
convention, same contiguous-US-only framing, same year-selection behavior).

v3.1 -- replaced the earlier animated-frame map entirely (see git history /
README for that rework: static per-rerun choropleth, no AK/HI basemap, HTML
year ruler alongside st.select_slider).

v3.2 -- this revision fixes four more real bugs the user found after
deploying v3.1, by changing HOW "no data" and color-scaling work, not by
patching the old approach:

  1. "Legend starts with gray, most counties look yellow" -- root cause: the
     old single-trace design used a sentinel z-value below vmin plus a
     remapped colorscale that reserved a gray band at the bottom of the
     SAME scale real data was drawn from. That's gone. There are now TWO
     separate go.Choropleth traces per map: one for counties with a real
     value (drawn with the named colorscale directly, zmin/zmax = the real
     data's own range, nothing reserved for gray), and one for counties
     with no data at all (solid NO_DATA_COLOR, its own tiny colorscale).
     Gray is no longer part of the real-data color ramp in any way.
  2. "WY counties in 2003 are gray even though they have real values" --
     root cause: that same sentinel approach computed one GLOBAL vmin
     across every year combined, so any real value below that global
     floor (common for early years, since prices trend up over decades)
     landed inside the reserved gray band and was visually indistinguishable
     from true no-data. Confirmed directly: 19 of 23 WY counties in 2003 had
     real prices below the global vmin. Fixed structurally by the two-trace
     split above: a real value is never sentinel-compared against a global
     floor, so it can never be miscolored as "no data" again.
  3. "Most counties look yellow" (Cost only) -- root cause: zmax was the
     single highest value across all counties/years, a rare outlier, which
     crushed the bulk of ordinary counties into the low end of the scale.
     Fixed by cost_pillar.py capping the real-data trace's zmax at the 98th
     percentile; values above that are simply clamped to the darkest color
     (standard Plotly cmin/cmax clamping) rather than stretching the ramp.
     Reliability keeps its fixed 0-100 scale, which was already fine.
  4. "The whole map dims when you click a county" -- root cause: Plotly's
     default behavior once any point is selected (on_select='rerun') is to
     fade every unselected point. Fixed with an explicit
     unselected=dict(marker=dict(opacity=1)) (and selected=... opacity=1
     for symmetry) on every Choropleth trace -- confirmed directly via
     Python introspection that go.Choropleth supports both attributes.

  Plotly's native colorbar is no longer used at all (both traces are
  showscale=False) -- it's replaced by render_gradient_legend(), a custom
  HTML legend matching the user's reference design: a horizontal gradient
  bar with low/high labels above it and numeric endpoints below, plus a
  separate "no data" gray swatch underneath.

Carried over unchanged from v3.1:
  - No Plotly basemap at all (visible=False) and no AK/HI geometry anywhere
    in our own geojson or state-border data -- Alaska/Hawaii structurally
    impossible to show.
  - State borders are the app's own go.Scattergeo line trace, dissolved
    from the same AK/HI-free county geometry (data_prep.py).
  - Year control is a plain st.select_slider (every year selectable) with
    an HTML "ruler" underneath marking every 2nd year and coloring
    forecast-year labels differently -- render_year_slider/render_year_ruler,
    unchanged.
  - No chart download affordances (NO_DOWNLOAD_CONFIG); table CSV/clipboard
    export disabled globally via .streamlit/config.toml.
"""
import numpy as np
import streamlit as st
import plotly.graph_objects as go

NO_DATA_COLOR = '#d9d9d9'   # distinct, visible gray -- not white/background
FORECAST_TICK_COLOR = '#e35b1e'   # distinct from actual-year ticks
ACTUAL_TICK_COLOR = '#444444'

# Plotly config applied to EVERY st.plotly_chart call in the app: removes
# the camera/"download plot as png" modebar button. Table CSV/clipboard
# export is a separate, global Streamlit setting -- see
# .streamlit/config.toml (client.disableDataExport = true).
NO_DOWNLOAD_CONFIG = {'modeBarButtonsToRemove': ['toImage'], 'displaylogo': False}

# Named colorscale stops (sequential.YlOrRd / sequential.OrRd from
# plotly.express.colors, confirmed directly against the installed plotly
# version rather than assumed). Plotly's go.Choropleth accepts these names
# directly as `colorscale=`, so this dict is only needed here to draw the
# matching CSS gradient in the custom HTML legend.
_YLORRD = ['rgb(255,255,204)', 'rgb(255,237,160)', 'rgb(254,217,118)', 'rgb(254,178,76)',
           'rgb(253,141,60)', 'rgb(252,78,42)', 'rgb(227,26,28)', 'rgb(189,0,38)', 'rgb(128,0,38)']
_ORRD = ['rgb(255,247,236)', 'rgb(254,232,200)', 'rgb(253,212,158)', 'rgb(253,187,132)',
         'rgb(252,141,89)', 'rgb(239,101,72)', 'rgb(215,48,31)', 'rgb(179,0,0)', 'rgb(127,0,0)']
_NAMED_COLORSCALES = {'YlOrRd': _YLORRD, 'OrRd': _ORRD}

# Shared trace-level kwargs that fix the "map dims on click" bug (#4 above),
# applied identically to every Choropleth trace this module builds.
_NO_DIM_ON_SELECT = dict(
    selected=dict(marker=dict(opacity=1)),
    unselected=dict(marker=dict(opacity=1)),
)


def build_static_choropleth(df, geojson, state_borders, color_col, color_scale, vmin, vmax, hover_text):
    """Build ONE static (non-animated) contiguous-US county choropleth for
    a single year, re-built fresh on every Streamlit rerun when the year
    selector changes.

    df must have one row per county FIPS IN SCOPE (i.e. every contiguous
    county, not just the ones with real data that year -- see each
    pillar's _year_df() helper) with columns ['FIPS', color_col]. hover_text
    is a precomputed per-row text list/array aligned POSITIONALLY to df's
    row order (not by pandas index label), expected to already say
    something sensible ("no data reported") for rows where color_col is NaN.

    Two separate Choropleth traces are drawn: one for counties with a real
    value (the named color_scale, its own vmin/vmax -- no gray reserved
    anywhere in it), and one for counties with no value at all (solid
    NO_DATA_COLOR). Neither shows Plotly's native colorbar
    (showscale=False) -- see render_gradient_legend() for the replacement
    custom HTML legend drawn underneath the map.

    geojson: the shared, AK/HI-free county boundary file.
    state_borders: dict with 'lons'/'lats' lists (None-separated rings),
    produced by data_prep.py's build_state_borders() from the SAME AK/HI-free
    county geometry -- so state lines, like the choropleth itself, can never
    include Alaska or Hawaii.
    """
    hover_arr = np.asarray(hover_text, dtype=object)
    mask_real = df[color_col].notna().to_numpy()
    fips_arr = df['FIPS'].to_numpy()
    z_arr = df[color_col].to_numpy()

    traces = []
    if mask_real.any():
        traces.append(go.Choropleth(
            geojson=geojson, locations=fips_arr[mask_real], z=z_arr[mask_real],
            zmin=vmin, zmax=vmax, colorscale=color_scale,
            hovertext=hover_arr[mask_real], hoverinfo='text',
            marker_line_width=0, marker_line_color='rgba(0,0,0,0)',
            showscale=False, **_NO_DIM_ON_SELECT,
        ))
    if (~mask_real).any():
        traces.append(go.Choropleth(
            geojson=geojson, locations=fips_arr[~mask_real], z=[0] * int((~mask_real).sum()),
            zmin=0, zmax=1, colorscale=[[0, NO_DATA_COLOR], [1, NO_DATA_COLOR]],
            hovertext=hover_arr[~mask_real], hoverinfo='text',
            marker_line_width=0, marker_line_color='rgba(0,0,0,0)',
            showscale=False, **_NO_DIM_ON_SELECT,
        ))

    borders = go.Scattergeo(
        lon=state_borders['lons'], lat=state_borders['lats'], mode='lines',
        line=dict(width=1.8, color='rgba(25,25,25,0.9)'),
        hoverinfo='skip', showlegend=False,
    )
    traces.append(borders)

    fig = go.Figure(data=traces)
    # NOTE: visible=False turns off Plotly's drawn basemap shapes (land,
    # countries, lakes, AK/HI insets) -- it does NOT stop Plotly from
    # fetching cdn.plot.ly's base topology file for the chosen projection
    # at render time; that fetch happens for every projection_type, not
    # just 'albers usa' (confirmed directly: an identical blocked request
    # occurs with 'mercator' too, just for a different file). Since no
    # AK/HI coordinates exist anywhere in our own geojson or state-border
    # data, Albers USA's built-in insets are never invoked regardless, so
    # it's kept for its better-proportioned look of the contiguous US.
    fig.update_geos(
        visible=False, projection_type='albers usa',
        fitbounds='geojson', bgcolor='rgba(0,0,0,0)',
    )
    fig.update_layout(
        height=560, margin=dict(l=0, r=0, t=10, b=10),
        paper_bgcolor='rgba(0,0,0,0)', showlegend=False,
    )
    return fig


def render_year_slider(key, years, default_year, last_actual_year):
    """The actual, draggable year control -- a plain st.select_slider over
    EVERY year (full resolution, same as before), paired with an HTML
    'ruler' underneath marking every 2nd year and coloring forecast-year
    labels differently from actual-year ones (Plotly's own slider/animation
    is no longer used anywhere, so this replaces its tick-marking and
    per-step coloring, neither of which Plotly's animate-slider API
    actually supports natively for per-step font color)."""
    default_year = default_year if default_year in years else years[-1]
    sel_year = st.select_slider(
        'Year', options=years, value=default_year, key=key,
    )
    render_year_ruler(years, last_actual_year, sel_year)
    return sel_year


def render_year_ruler(years, last_actual_year, current_year):
    """Visual-only HTML strip: a tick + label for EVERY year (per explicit
    request -- v3.2/v3.3 only marked every 2nd year), forecast-year labels
    in a distinct color, with the currently-selected year bolded. Purely
    informational -- the st.select_slider above it is what's actually
    draggable, and already supports every single year."""
    ymin, ymax = years[0], years[-1]
    span = (ymax - ymin) or 1
    marks = list(years)
    ticks_html = []
    for y in marks:
        pct = (y - ymin) / span * 100
        is_forecast = y > last_actual_year
        color = FORECAST_TICK_COLOR if is_forecast else ACTUAL_TICK_COLOR
        weight = '700' if y == current_year else '400'
        underline = 'text-decoration:underline;' if y == current_year else ''
        ticks_html.append(
            f'<div style="position:absolute; left:{pct:.3f}%; transform:translateX(-50%); '
            f'font-size:0.72rem; color:{color}; font-weight:{weight}; {underline}">{y}</div>'
        )
    st.markdown(
        f"""
        <div style="position:relative; height:18px; margin:-6px 6px 6px 6px;">
            {''.join(ticks_html)}
        </div>
        <div style="display:flex; gap:14px; font-size:0.78rem; color:#555; margin-bottom:6px;">
            <span><span style="color:{ACTUAL_TICK_COLOR}; font-weight:700;">&#9679;</span> actual year</span>
            <span><span style="color:{FORECAST_TICK_COLOR}; font-weight:700;">&#9679;</span> forecast year</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_clicked_fips(selection_state):
    """Pull FIPS out of a Streamlit plotly_chart on_select event payload
    (st.session_state[key] when the chart was built with
    on_select='rerun'). Returns None if nothing was clicked."""
    if not selection_state:
        return None
    points = selection_state.get('selection', {}).get('points', [])
    if not points:
        return None
    cd = points[0].get('location') or points[0].get('customdata')
    if cd is None:
        return None
    if isinstance(cd, (list, tuple)):
        cd = cd[0]
    return str(cd).zfill(5)


def render_gradient_legend(color_scale, low_label, high_label, caption=None,
                            no_data_label='No data reported'):
    """Custom HTML legend matching the user's reference design, replacing
    Plotly's native colorbar (now turned off on both Choropleth traces):
    a horizontal gradient bar with low/high descriptive labels above it,
    and a separate gray "no data" swatch underneath -- completely
    independent of the real-data color ramp (see module docstring,
    fix #1/#2), so it can never be confused with it.

    v3.4: the numeric endpoint values that used to sit under the gradient
    bar are gone, and `caption` is optional (omit it for no caption line at
    all) -- both removed per explicit request on both pillars."""
    stops = _NAMED_COLORSCALES[color_scale]
    gradient_css = ', '.join(stops)
    caption_html = (
        f'<div style="margin-top:9px; font-size:0.76rem; color:#777; font-style:italic;">'
        f'{caption}</div>' if caption else ''
    )
    st.markdown(
        f"""
        <div style="margin-top:6px; margin-bottom:10px; max-width:420px;">
          <div style="display:flex; justify-content:space-between;
                      font-size:0.82rem; color:#333; font-weight:600;">
            <span>{low_label}</span><span>{high_label}</span>
          </div>
          <div style="height:14px; border-radius:3px; margin:3px 0;
                      background:linear-gradient(to right, {gradient_css});
                      border:1px solid rgba(0,0,0,0.15);"></div>
          <div style="margin-top:9px; display:flex; align-items:center; gap:8px;">
            <div style="width:14px; height:14px; background:{NO_DATA_COLOR};
                        border:1px solid rgba(80,80,80,0.5); flex-shrink:0;
                        border-radius:2px;"></div>
            <span style="font-size:0.8rem; color:#555;">{no_data_label}</span>
          </div>
          {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
