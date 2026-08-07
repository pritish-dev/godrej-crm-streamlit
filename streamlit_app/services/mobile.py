"""
mobile.py - Mobile / PWA optimisations for the CRM dashboard.

This is intentionally ADDITIVE and NON-INVASIVE:
  * All layout tweaks are wrapped in an `@media (max-width: 768px)` query, so the
    desktop web experience is completely unchanged.
  * It only injects CSS + a couple of meta tags. It never touches data, auth,
    Google Sheets, or any page logic.

Called once from app.py. Safe to remove at any time with zero side effects.
"""
import streamlit as st


def apply_mobile_optimizations() -> None:
    """Inject responsive CSS + PWA-friendly meta tags. Phone-only styling."""
    # NOTE: the blank line between the <meta> tags and <style> is REQUIRED.
    # Streamlit's markdown renderer (react-markdown, CommonMark) otherwise
    # folds <style> into the <meta> HTML block, which ends at the first blank
    # line inside the CSS — leaking the media query's trailing "}" as a stray
    # "}" at the top of every page. The blank line makes <style>…</style> its
    # own HTML block, immune to the blank lines between CSS rules.
    st.markdown(
        """
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Godrej CRM">
<meta name="theme-color" content="#B8232F">

<style>
/* ===== Phone-only tweaks. Desktop (>768px) is untouched. ===== */
@media (max-width: 768px) {
    /* Reclaim vertical space that desktop padding wastes on a phone. */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 0.7rem !important;
        padding-right: 0.7rem !important;
    }

    /* Bigger, thumb-friendly tap targets for buttons and inputs. */
    .stButton > button,
    .stDownloadButton > button {
        min-height: 44px;
        font-size: 0.95rem;
    }
    .stTextInput input,
    .stNumberInput input,
    .stDateInput input,
    .stSelectbox div[data-baseweb="select"] {
        min-height: 44px;
        font-size: 16px; /* 16px stops iOS from auto-zooming on focus */
    }

    /* Let wide tables/dataframes scroll horizontally instead of squishing. */
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        overflow-x: auto !important;
    }

    /* Stack st.columns vertically so nothing gets crushed off-screen. */
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    [data-testid="stHorizontalBlock"] > div {
        min-width: 100% !important;
    }

    /* Compact metric cards so 2 fit per row nicely. */
    [data-testid="stMetric"] {
        padding: 0.4rem 0.6rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
    }

    /* Make Plotly charts fill the phone width. */
    .js-plotly-plot,
    .stPlotlyChart {
        width: 100% !important;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )
