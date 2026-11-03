"""Power Risk Index for Data Center Construction Planning -- main app (v3).

Single page, one URL. Password-gated. Four pillars as tabs: Cost,
Reliability, and Availability are now real, validated pillars (see each
pillar's own module for data provenance); the Composite index remains an
honest placeholder (no synthetic data) until it's built out.

No separate "About" tab in this version -- removed per the confirmed
interface refinement; each pillar page is self-contained.
"""
import json
import streamlit as st

st.set_page_config(
    page_title='Power Risk Index for Data Center Construction Planning',
    page_icon='⚡', layout='wide',
)


def check_password():
    """Simple shared-password gate. The real password lives only in
    st.secrets (never in source control) -- see .streamlit/secrets.toml.example."""
    if st.session_state.get('authenticated'):
        return True

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.image('assets/mocci_logo.png', width=140)
        st.markdown("#### Power Risk Index for Data Center Construction Planning")
        st.caption('Missouri Consortium for Construction Innovation (MOCCI)')
        pw = st.text_input('Password', type='password', key='pw_input')
        if st.button('Enter', width='stretch'):
            real_pw = st.secrets.get('app_password')
            if real_pw is None:
                st.error('App password is not configured yet (set app_password in Secrets).')
            elif pw == real_pw:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error('Incorrect password.')
    return False


if not check_password():
    st.stop()


@st.cache_data
def load_geojson():
    with open('data/counties_fips.json') as f:
        return json.load(f)


@st.cache_data
def load_state_borders():
    with open('data/state_borders.json') as f:
        return json.load(f)


geo = load_geojson()
state_borders = load_state_borders()

h1, h2 = st.columns([1, 9])
with h1:
    st.image('assets/mocci_logo.png', width=90)
with h2:
    st.title('Power Risk Index for Data Center Construction Planning')
    st.caption('Missouri Consortium for Construction Innovation (MOCCI)')

tab_cost, tab_reliability, tab_availability, tab_composite = st.tabs(
    ['Cost', 'Reliability', 'Availability', 'Composite']
)

with tab_cost:
    import cost_pillar
    cost_pillar.render(geo, state_borders)

with tab_reliability:
    import reliability_pillar
    reliability_pillar.render(geo, state_borders)

with tab_availability:
    import availability_pillar
    availability_pillar.render(geo, state_borders)

with tab_composite:
    import composite_pillar
    composite_pillar.render()
