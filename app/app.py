"""Streamlit frontend for the UBS Key Player Battle."""

from html import escape
from math import cos, pi, sin

import streamlit as st


MOCK_PLAYERS = (
    {"id": "mock-davos-18", "name": "Mock Player A", "team": "HC Davos", "number": 18},
    {
        "id": "mock-selects-23",
        "name": "Mock Player B",
        "team": "U.S. Collegiate Selects",
        "number": 23,
    },
)

# Synthetic frontend fixtures only; no values are derived from match data.
# Metric, chart maximum, Player A value, Player B value, display format.
DEMO_METRICS = (
    ("xGsum", 1, .8, .5, ".2f"),
    ("Shots", 10, 5, 6, ".0f"),
    ("Shots on target %", 100, 60, 67, ".0f"),
    ("Fast crossings", 10, 8, 4, ".0f"),
    ("Shots (PRE)", 5, 3, 4, ".0f"),
)
DEMO_FAN_SHARES = {"mock-davos-18": 62, "mock-selects-23": 38}


def apply_styles() -> None:
    """Apply the shared mobile-first battle theme."""
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        .stApp { background: #091525; color: #f4f8fc; }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stMainBlockContainer"] {
            max-width: 30rem;
            padding: 2rem 1.5rem 3rem;
            text-align: center;
            font-family: Arial, Helvetica, sans-serif;
        }
        .st-key-enter-battle, .st-key-choose, .st-key-hold {
            min-height: calc(100vh - var(--battle-top) - var(--battle-bottom));
            min-height: calc(100svh - var(--battle-top) - var(--battle-bottom));
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            gap: 1.25rem;
        }
        .st-key-enter-battle > *, .st-key-choose > *, .st-key-hold > * { flex-shrink: 0; }
        /* Keep Streamlit's outer gaps out of the viewport height budget. */
        [data-testid="stMainBlockContainer"]:has(:is(.st-key-enter-battle, .st-key-choose, .st-key-hold)) {
            --battle-top: max(1.75rem, env(safe-area-inset-top, 0px));
            --battle-bottom: max(1.5rem, env(safe-area-inset-bottom, 0px));
            box-sizing: border-box;
            padding-top: var(--battle-top);
            padding-bottom: var(--battle-bottom);
        }
        [data-testid="stMainBlockContainer"]:has(:is(.st-key-enter-battle, .st-key-choose, .st-key-hold))
            > [data-testid="stVerticalBlock"] {
            gap: 0;
        }
        .st-key-enter-battle p { margin-bottom: 0; }
        .st-key-enter-battle h1,
        .st-key-enter-battle h2 {
            padding: 0;
            margin: 0;
        }
        .st-key-enter-battle h1 {
            font-size: clamp(2rem, 8vw, 2.8rem);
            font-weight: 800;
            line-height: 1.15;
            text-align: center;
        }
        .st-key-enter-battle h2 { margin-top: .75rem; }
        .st-key-brand p {
            color: #39b4e3;
            font-size: .8rem;
            font-weight: 700;
            letter-spacing: .18em;
        }
        .st-key-progress {
            width: 100%;
            max-width: 100%;
            margin: 0 auto .5rem;
            align-items: center;
        }
        .st-key-progress [data-testid="stHorizontalBlock"] {
            width: min(9rem, 100%);
            margin-inline: auto;
            flex-wrap: nowrap;
            gap: .4rem;
        }
        .st-key-progress [data-testid="stColumn"] {
            min-width: 0;
            flex: 1 1 0;
        }
        .st-key-progress hr {
            border: 0;
            height: .22rem;
            border-radius: 1rem;
            background: #293d56;
            margin: 0;
        }
        .st-key-progress [data-testid="stColumn"]:first-child hr {
            background: #39b4e3;
        }
        .st-key-lightning p {
            color: #39b4e3;
            font-size: 6rem;
            line-height: 1;
            width: 11rem;
            height: 11rem;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid #293d56;
            border-radius: 50%;
            background: #14243c;
            margin: clamp(.75rem, 3svh, 2rem) auto;
        }
        h1 {
            color: #f4f8fc;
            font-size: clamp(2rem, 8vw, 2.8rem);
            font-weight: 800;
            line-height: 1.2;
            letter-spacing: -.035em;
        }
        h2 {
            color: #a0b4c9;
            font-size: .9rem;
            font-weight: 700;
            letter-spacing: .12em;
            padding-top: 1rem;
        }
        .st-key-prompt p {
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.4;
            margin: .25rem auto;
            max-width: 20rem;
        }
        .st-key-match p { color: #acbdcf; font-size: .9rem; }
        .st-key-enter-action {
            /* Spare height belongs above the arrow, not above the progress. */
            margin-top: auto;
            padding-top: 1.5rem;
            align-items: center;
        }
        .st-key-enter-action [data-testid="stElementContainer"] {
            width: 100%;
        }
        .st-key-enter-action [data-testid="stButton"] {
            width: 100%;
            display: flex;
            justify-content: center;
        }
        .st-key-enter-action button {
            margin-inline: auto;
            flex-shrink: 0;
            width: 5rem;
            height: 5rem;
            min-height: 5rem;
            border-radius: 50%;
            border: 2px solid #39b4e3;
            background: transparent;
            color: #39b4e3;
        }
        .st-key-enter-action button p { font-size: 1.8rem; }
        .st-key-enter-action button:hover {
            background: #8af2f7;
            border-color: #8af2f7;
            color: #071525;
        }
        .st-key-enter-action button:focus-visible {
            outline: 3px solid #f4f8fc;
            outline-offset: 5px;
        }
        /* Reserve toolbar clearance on later screens; keep Screen 1 unchanged. */
        [data-testid="stMainBlockContainer"]:has(:is(.st-key-choose, .st-key-hold)) {
            --battle-top: calc(4.5rem + env(safe-area-inset-top, 0px));
        }
        .st-key-choose h1 { margin: 0; padding: 0; font-size: 2.4rem; text-align: center; }
        .st-key-choose-intro p, .st-key-choose-note p { text-align: center; }
        .st-key-choose p { margin-bottom: 0; }
        .st-key-choose .st-key-progress [data-testid="stColumn"]:first-child hr {
            background: #293d56;
        }
        .st-key-choose .st-key-progress [data-testid="stColumn"]:nth-child(2) hr {
            background: #39b4e3;
        }
        .st-key-choose-intro p, .st-key-choose-note p { color: #acbdcf; }
        .st-key-player-grid {
            /* Both panels resolve cqw against this one shared grid container. */
            container-type: inline-size;
        }
        .st-key-player-grid > [data-testid="stHorizontalBlock"] {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: .75rem;
            align-items: stretch;
        }
        .st-key-player-grid [data-testid="stColumn"] {
            min-width: 0;
            width: 100%;
            max-width: 100%;
            box-sizing: border-box;
        }
        .st-key-player-grid [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {
            height: 100%;
        }
        [class*="st-key-player-number-"] p {
            display: grid;
            place-items: center;
            min-height: 7rem;
            border-radius: .75rem;
            background: #1d3453;
            font-size: 3.5rem;
            font-weight: 800;
            color: #f4f8fc;
        }
        .st-key-choose button {
            min-height: 2.75rem;
            background: #f4f8fc;
            border: 1px solid #acbdcf;
            color: #091525;
            font-weight: 600;
        }
        .st-key-choose button p { color: inherit; font-weight: inherit; }
        .st-key-choose button[kind="primary"] {
            background: #39b4e3;
            border-color: #39b4e3;
            color: #091525;
        }
        .st-key-choose button:hover:not(:disabled) {
            background: #dce8f3;
            border-color: #39b4e3;
            color: #091525;
        }
        .st-key-choose button[kind="primary"]:hover:not(:disabled) {
            background: #83dbf5;
        }
        .st-key-choose-nav button[kind="tertiary"] {
            background: transparent;
            border-color: transparent;
            color: #acbdcf;
        }
        .st-key-choose-nav button[kind="tertiary"]:hover {
            background: #14243c;
            color: #f4f8fc;
        }
        .st-key-choose button:focus-visible {
            outline: 3px solid #f4f8fc;
            outline-offset: 3px;
        }
        .st-key-choose button:disabled {
            background: #23344b;
            border-color: #52657d;
            color: #acbdcf;
            opacity: 1;
            cursor: not-allowed;
        }
        .st-key-choose-nav { margin-top: auto; padding-top: .5rem; }
        /* Each card is one native button, including its number and identity. */
        .st-key-player-grid [data-testid="stElementContainer"],
        .st-key-player-grid [data-testid="stButton"] { height: 100%; }
        .st-key-choose .st-key-player-grid button {
            width: 100%;
            height: 100%;
            min-height: clamp(18rem, 40svh, 22rem);
            padding: .875rem .75rem;
            box-sizing: border-box;
            background: #14243c;
            color: #c4d2e1;
            border: 2px solid #293d56;
            border-radius: 1.25rem;
            align-items: flex-start;
        }
        .st-key-choose .st-key-player-grid button[kind="primary"] {
            border-color: #39b4e3;
            background: #14243c;
        }
        .st-key-choose .st-key-player-grid button:hover:not(:disabled) {
            border-color: #39b4e3;
            background: #1a2e48;
            color: #f4f8fc;
        }
        /* Stretch the native button label before sizing its shared number panel. */
        .st-key-player-grid button > div,
        .st-key-player-grid button [data-has-shortcut],
        .st-key-player-grid button [data-testid="stMarkdownContainer"] {
            width: 100%;
            min-width: 0;
            box-sizing: border-box;
        }
        .st-key-player-grid button > div { flex: 1 1 0; }
        .st-key-choose .st-key-player-grid button p {
            width: 100%;
            min-width: 0;
            box-sizing: border-box;
            font-size: .9rem;
            line-height: 1.5;
            text-align: center;
            white-space: normal;
            overflow-wrap: anywhere;
            margin: 0;
            font-weight: 400;
        }
        .st-key-player-grid button br { display: none; }
        .st-key-player-grid button strong {
            display: grid;
            place-items: center;
            /* Half the shared grid minus its gap, card padding, and borders.
               Do not use the content-sized button label as the width reference. */
            width: min(12rem, calc((100cqw - .75rem) / 2 - 1.5rem - 4px));
            height: clamp(8rem, 20svh, 11rem);
            min-width: 0;
            box-sizing: border-box;
            padding: .5rem;
            margin-inline: auto;
            margin-bottom: 1rem;
            background: #1d3453;
            border-radius: .875rem;
            color: #f4f8fc;
            font-size: clamp(3rem, 14vw, 4.5rem);
            line-height: 1.1;
            font-weight: 800;
        }
        .st-key-player-grid button[kind="primary"] strong { color: #39b4e3; }
        .st-key-player-grid button em {
            display: block;
            margin-bottom: .5rem;
            font-size: 1rem;
            line-height: 1.4;
            font-style: normal;
            font-weight: 700;
            color: #f4f8fc;
        }
        .st-key-hold { gap: 1rem; }
        .st-key-hold h1 { font-size: 2rem; padding: 0; margin: 0; text-align: center; }
        .st-key-hold p { margin: 0; line-height: 1.5; text-align: center; }
        .st-key-hold-heading { gap: .75rem; }
        .st-key-hold-subtitle p, .st-key-hold-note p {
            color: #c4d2e1;
            font-size: 1rem;
        }
        .st-key-hold-note { gap: .5rem; }
        .st-key-hold-note > [data-testid="stElementContainer"]:first-child p {
            color: #f4f8fc;
            font-size: 1.1rem;
            font-weight: 700;
        }
        .st-key-hold .st-key-progress [data-testid="stColumn"]:first-child hr {
            background: #293d56;
        }
        .st-key-hold .st-key-progress [data-testid="stColumn"]:nth-child(4) hr {
            background: #39b4e3;
        }
        .st-key-hold-player {
            display: flex;
            flex-direction: column;
            height: auto;
            width: 100%;
            max-width: 16rem;
            margin: .5rem auto;
            box-sizing: border-box;
            background: #14243c;
            border: 2px solid #39b4e3;
            border-radius: 1.25rem;
            padding: 1rem 1rem 1.25rem;
            gap: 0;
        }
        .st-key-hold-player [data-testid="stVerticalBlock"],
        .st-key-hold-player [data-testid="stElementContainer"] {
            height: auto;
            flex-shrink: 0;
        }
        /* A single static summary avoids Markdown margins and nested widget sizing. */
        .st-key-hold-player .vote-player-summary {
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            width: 100%;
            box-sizing: border-box;
            text-align: center;
        }
        .st-key-hold-player .vote-player-number {
            display: grid;
            place-items: center;
            width: 100%;
            aspect-ratio: 1.3;
            padding: .75rem;
            box-sizing: border-box;
            background: #1d3453;
            border-radius: .875rem;
            color: #39b4e3;
            font-size: 4rem;
            font-weight: 800;
            line-height: 1.15;
        }
        .st-key-hold-player h3 {
            color: #f4f8fc;
            font-size: 1.25rem;
            line-height: 1.35;
            padding: 0;
            margin: .875rem 0 0;
            text-align: center;
        }
        .st-key-hold-player .vote-player-team {
            margin: .5rem 0 0;
            color: #c4d2e1;
            font-size: .95rem;
            line-height: 1.5;
            overflow-wrap: anywhere;
        }
        .st-key-hold-action [data-testid="stElementContainer"],
        .st-key-hold-action [data-testid="stButton"] { width: 100%; }
        .st-key-hold-action [data-testid="stButton"] {
            display: flex;
            justify-content: center;
            padding: .6rem;
        }
        .st-key-hold-action button {
            width: 9rem;
            min-height: 9rem;
            aspect-ratio: 1;
            box-sizing: border-box;
            flex-shrink: 0;
            border-radius: 50%;
            border: .3rem solid #f7bf32;
            box-shadow: inset 0 0 0 .35rem #091525;
            background: #f7bf32;
            color: #091525;
            font-weight: 700;
        }
        .st-key-hold button p { color: inherit; }
        /* Keep the native accessible name; show only the large lightning glyph. */
        .st-key-hold-action button p { font-size: 0; line-height: 1; }
        .st-key-hold-action button p::before {
            content: "ϟ";
            font-size: 5.5rem;
            line-height: 1;
        }
        .st-key-hold-action button:hover {
            background: #ffda72;
            color: #091525;
        }
        .st-key-hold button:focus-visible {
            box-shadow: 0 0 0 .6rem #f4f8fc;
        }
        .st-key-hold-change { margin-top: auto; align-items: center; }
        .st-key-hold-change [data-testid="stButton"] {
            display: flex;
            justify-content: center;
        }
        .st-key-hold-change button {
            background: transparent;
            border: 1px solid transparent;
            color: #39b4e3;
            min-height: 2.75rem;
        }
        .st-key-hold-change button:hover { background: #14243c; color: #83dbf5; }
        [data-testid="stMainBlockContainer"]:has(.st-key-reveal) {
            padding-top: calc(5rem + env(safe-area-inset-top, 0px));
            padding-bottom: max(1.5rem, env(safe-area-inset-bottom, 0px));
        }
        [data-testid="stMainBlockContainer"]:has(.st-key-reveal)
            > [data-testid="stVerticalBlock"] { gap: 0; }
        /* Let wrapped text determine row height instead of shrinking widgets. */
        .st-key-reveal,
        .st-key-reveal-heading,
        .st-key-reveal-chart,
        .st-key-reveal-legend,
        .st-key-reveal-agreement {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            height: auto;
            min-width: 0;
        }
        .st-key-reveal { gap: 1.5rem; }
        .st-key-reveal-heading { gap: .75rem; text-align: center; }
        .st-key-reveal-heading h1, .st-key-reveal-heading p { text-align: center; }
        .st-key-reveal-chart { gap: 1rem; }
        .st-key-reveal-legend { gap: .875rem; }
        .st-key-reveal [data-testid="stElementContainer"],
        .st-key-reveal [data-testid="stVerticalBlock"] {
            height: auto;
            flex-shrink: 0;
        }
        .st-key-reveal-legend p {
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .st-key-reveal-chart [data-testid="stImage"] img { max-width: 100%; height: auto; }
        .st-key-reveal h1 { color: #f4f8fc; font-size: 2.2rem; padding: 0; margin: 0; }
        .st-key-reveal p { color: #c4d2e1; line-height: 1.5; margin: 0; }
        @media (max-width: 480px) {
            [data-testid="stMainBlockContainer"]:has(.st-key-reveal) {
                padding-inline: 1rem;
            }
        }
        .st-key-reveal [data-testid="stCaptionContainer"] p {
            color: #bdccdc;
            font-size: .9rem;
        }
        .st-key-reveal .st-key-progress [data-testid="stColumn"]:first-child hr {
            background: #293d56;
        }
        .st-key-reveal .st-key-progress [data-testid="stColumn"]:nth-child(4) hr {
            background: #f7bf32;
        }
        .st-key-statistics .st-key-progress [data-testid="stColumn"]:nth-child(4) hr {
            background: #293d56;
        }
        .st-key-statistics .st-key-progress [data-testid="stColumn"]:nth-child(3) hr {
            background: #39b4e3;
        }
        .st-key-statistics-actions { gap: .75rem; }
        .st-key-statistics-actions button {
            min-height: 2.75rem;
            border: 1px solid #39b4e3;
            background: #39b4e3;
            color: #091525;
        }
        .st-key-statistics-actions button[kind="tertiary"] {
            background: transparent;
            color: #39b4e3;
            border-color: transparent;
        }
        .st-key-statistics-actions button:hover { background: #14243c; color: #83dbf5; }
        .st-key-statistics-actions button:focus-visible {
            outline: 3px solid #f4f8fc;
            outline-offset: 3px;
        }
        .st-key-reveal-status p {
            color: #f7bf32;
            font-size: .8rem;
            font-weight: 700;
            letter-spacing: .08em;
        }
        .st-key-reveal-agreement {
            padding: 1rem;
            border-radius: 1rem;
            background: #14243c;
            gap: .5rem;
        }
        .st-key-reveal-agreement [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
        .reveal-fan-bar {
            height: .65rem;
            margin: .65rem 0 .5rem;
            background: #293d56;
            border-radius: 1rem;
            overflow: hidden;
        }
        .reveal-fan-bar > span { display: block; height: 100%; background: #39b4e3; }
        .reveal-fan-labels { display: flex; justify-content: space-between; gap: .5rem; }
        .reveal-fan-labels span { color: #bdccdc; font-size: .85rem; }
        .reveal-legend { display: grid; gap: .6rem; text-align: left; }
        .reveal-legend-row { display: flex; align-items: center; gap: .6rem; color: #c4d2e1; }
        .reveal-line { width: 1.5rem; flex: 0 0 1.5rem; border-top: 3px solid #39b4e3; }
        .reveal-line-other { border-top: 3px dashed #f4f8fc; }
        .st-key-reveal-table table {
            width: 100%;
            table-layout: fixed;
            border-collapse: collapse;
            border: 0;
            font-size: .85rem;
            color: #f4f8fc;
            background: #091525;
        }
        .st-key-reveal-table th, .st-key-reveal-table td {
            padding: .65rem .35rem;
            border: 0;
            border-bottom: 1px solid #293d56;
            white-space: normal;
            overflow-wrap: anywhere;
            text-align: right;
        }
        .st-key-reveal-table th:first-child { width: 48%; text-align: left; }
        .st-key-reveal-table thead th { color: #bdccdc; font-weight: 500; border-top: 1px solid #293d56; }
        .st-key-reveal-table tbody th { font-weight: 400; }
        .st-key-reveal-table strong { color: #39b4e3; }
        .st-key-reveal-table caption {
            text-align: left;
            color: #bdccdc;
            font-size: .85rem;
            padding-bottom: .5rem;
        }
        .st-key-reveal button:disabled {
            background: #14243c;
            border: 1px solid #52657d;
            color: #acbdcf;
            opacity: 1;
            min-height: 2.75rem;
        }
        .st-key-reveal button p { color: inherit; }
        .st-key-reveal-home [data-testid="stButton"] {
            display: flex;
            justify-content: center;
        }
        .st-key-reveal-home button {
            min-height: 2.75rem;
            background: #091525;
            color: #39b4e3;
            border: 1px solid #39b4e3;
        }
        .st-key-reveal-home button:hover {
            background: #14243c;
            color: #83dbf5;
            border-color: #83dbf5;
        }
        .st-key-reveal-home button:focus-visible {
            outline: 3px solid #f4f8fc;
            outline-offset: 3px;
        }
        @media (max-width: 480px), (max-height: 740px) {
            .st-key-enter-battle, .st-key-choose { gap: 1rem; }
            .st-key-lightning p {
                width: 8rem;
                height: 8rem;
                font-size: 4.5rem;
                margin: .75rem auto;
            }
            .st-key-enter-battle h1 { font-size: 2.4rem; }
            .st-key-enter-battle h2 {
                font-size: .8rem;
                letter-spacing: .09em;
            }
            .st-key-enter-action button {
                width: 4rem;
                height: 4rem;
                min-height: 4rem;
            }
        }
        /* Screen 1: distribute the entry content below the Streamlit toolbar. */
        [data-testid="stMainBlockContainer"]:has(.st-key-enter-battle) {
            --battle-top: calc(4.5rem + env(safe-area-inset-top, 0px));
        }
        .st-key-enter-battle {
            gap: clamp(.875rem, 2.1svh, 1.25rem);
            align-items: stretch;
        }
        .st-key-enter-battle [data-testid="stElementContainer"] {
            width: 100%;
            height: auto;
            flex-shrink: 0;
        }
        .st-key-enter-battle p, .st-key-enter-battle h2 {
            text-align: center;
        }
        .st-key-enter-battle .st-key-brand,
        .st-key-enter-battle .st-key-prompt,
        .st-key-enter-battle .st-key-match { align-items: center; }
        .st-key-enter-battle .st-key-lightning {
            margin-top: clamp(1rem, 4svh, 2.5rem);
        }
        .st-key-enter-battle .st-key-lightning p {
            width: clamp(8rem, 18svh, 11rem);
            height: auto;
            aspect-ratio: 1;
            font-size: clamp(4.5rem, 10svh, 6rem);
            margin: 0 auto clamp(.75rem, 2svh, 1.5rem);
        }
        .st-key-enter-battle .st-key-enter-action {
            margin-top: auto;
            padding-top: clamp(1rem, 3svh, 2rem);
        }
        .st-key-enter-demo-actions {
            margin-top: auto;
            padding-top: 1rem;
            gap: .75rem;
        }
        .st-key-enter-demo-actions button {
            min-height: 2.75rem;
            background: #14243c;
            border: 1px solid #39b4e3;
            color: #39b4e3;
        }
        .st-key-enter-demo-actions button[kind="primary"] {
            background: #39b4e3;
            color: #091525;
        }
        .st-key-enter-demo-actions button p { color: inherit; }
        .st-key-enter-demo-actions button:hover {
            background: #83dbf5;
            color: #091525;
        }
        .st-key-enter-demo-actions button:focus-visible {
            outline: 3px solid #f4f8fc;
            outline-offset: 3px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def go_to_choose() -> None:
    """Start an unvoted battle afresh, or return to an already locked Reveal."""
    if st.session_state.mock_vote is not None:
        st.session_state.screen = "reveal"
        return
    st.session_state.selected_player_id = None
    st.session_state.screen = "choose"


def start_new_demo() -> None:
    """Explicitly discard only the current session's synthetic demo vote and pick."""
    st.session_state.mock_vote = None
    st.session_state.selected_player_id = None
    st.session_state.screen = "choose"


def render_progress() -> None:
    """Render shared progress bars; the screen container styles the active step."""
    with st.container(key="progress"):
        for column in st.columns(4):
            with column:
                st.divider()


def render_enter_battle() -> None:
    """Render Screen 1: Enter the Battle."""
    with st.container(key="enter-battle"):
        render_progress()
        with st.container(key="brand"):
            st.write("UBS KEY PLAYER BATTLE")
        with st.container(key="lightning"):
            st.write("ϟ")
        # Explicit line break keeps both lines inside one equally styled heading.
        st.html("<h1>ENTER<br>THE BATTLE</h1>")
        st.header("MOST DANGEROUS PLAYER", anchor=False)
        with st.container(key="prompt"):
            st.write("Who was the most dangerous player tonight?")
        with st.container(key="match"):
            st.write("HC Davos vs U.S. Collegiate Selects")
        if st.session_state.mock_vote is not None:
            with st.container(key="enter-demo-actions"):
                st.button(
                    "Start new demo", key="start-new-demo", type="primary",
                    width="stretch", on_click=start_new_demo,
                    help="Clear this session's synthetic vote and choose again.",
                )
                st.button(
                    "View previous results", key="view-previous-results",
                    width="stretch", on_click=navigate, args=("reveal",),
                )
        else:
            with st.container(key="enter-action"):
                st.button(
                    "❯",
                    key="enter-battle-next",
                    help="Continue to Choose",
                    on_click=go_to_choose,
                )


def navigate(screen: str) -> None:
    st.session_state.screen = screen


def select_player(player_id: str) -> None:
    """Save a tentative pick and show statistics without recording a vote."""
    if player_id in {player["id"] for player in MOCK_PLAYERS}:
        if st.session_state.mock_vote is not None:
            navigate("reveal")
            return
        st.session_state.selected_player_id = player_id
        navigate("statistics")


def render_player_card(player: dict) -> None:
    """Use one keyboard-accessible native button as the entire player card."""
    player_id = player["id"]
    selected = st.session_state.selected_player_id == player_id
    checkmark = " ✓" if selected else ""
    st.button(
        f"**{player['number']}**  \n*{player['name']}{checkmark}*  \n"
        f"#{player['number']} · {player['team']}",
        key=f"select-{player_id}",
        type="primary" if selected else "secondary",
        width="stretch",
        wrap=True,
        help=f"Select {player['name']}, number {player['number']}, {player['team']}",
        on_click=select_player,
        args=(player_id,),
    )


def render_choose() -> None:
    """Screen 2: choose one mock player without revealing any KPIs."""
    with st.container(key="choose"):
        render_progress()
        st.title("CHOOSE", anchor=False)
        with st.container(key="choose-intro"):
            st.write("Who was more dangerous? Tap your pick.")
            st.caption("Demo players and statistics only — not official match results.")
        with st.container(key="player-grid"):
            for column, player in zip(st.columns(2), MOCK_PLAYERS):
                with column:
                    render_player_card(player)
        with st.container(key="choose-note"):
            st.write("Pick a player, review the stats, then confirm your vote.")
        with st.container(key="choose-nav"):
            st.button(
                "← Back", key="choose-back", on_click=navigate,
                args=("enter",), type="tertiary",
            )


def selected_player() -> dict | None:
    return next(
        (player for player in MOCK_PLAYERS
         if player["id"] == st.session_state.selected_player_id),
        None,
    )


def confirm_mock_vote() -> None:
    """Record at most one mock vote per session, only from explicit confirmation."""
    if st.session_state.mock_vote is not None:
        navigate("reveal")
        return
    player = selected_player()
    if st.session_state.screen != "hold_to_vote" or player is None:
        return
    st.session_state.mock_vote = {"player_id": player["id"], "is_mock": True}
    navigate("reveal")


def render_hold_to_vote() -> None:
    """Final decision after reviewing statistics; only confirmation records a vote."""
    if st.session_state.mock_vote is not None:
        navigate("reveal")
        st.rerun()
    with st.container(key="hold"):
        render_progress()
        with st.container(key="hold-heading"):
            st.title("Still sure?", anchor=False)
            with st.container(key="hold-subtitle"):
                st.write("Keep your pick, or switch.")
        player = selected_player()
        if player is None:
            st.warning("Choose a player before locking in your vote.")
            with st.container(key="hold-change"):
                st.button("Back to Choose", on_click=navigate, args=("choose",))
            return
        with st.container(key="hold-player"):
            st.html(
                '<section class="vote-player-summary" aria-label="Your selected player">'
                f'<div class="vote-player-number">{escape(str(player["number"]))}</div>'
                f'<h3>{escape(player["name"])}</h3>'
                f'<p class="vote-player-team">#{escape(str(player["number"]))} · '
                f'{escape(player["team"])}</p>'
                '</section>'
            )
        with st.container(key="hold-action"):
            st.button(
                "Confirm vote", key="lock-in-vote",
                help="Tap to confirm one mock vote for your selected player.",
                on_click=confirm_mock_vote,
            )
        with st.container(key="hold-note"):
            st.write("Tap to lock in your vote")
            st.write("or change your pick before confirming")
        with st.container(key="hold-change"):
            st.button(
                "Change pick", key="change-pick", on_click=navigate,
                args=("choose",), type="tertiary",
            )


def demo_radar_svg(pick_id: str) -> str:
    """Draw a responsive five-axis chart using only standard Python and SVG."""
    def point(axis: int, fraction: float) -> tuple[float, float]:
        angle = -pi / 2 + axis * 2 * pi / 5
        return 230 + 115 * fraction * cos(angle), 175 + 115 * fraction * sin(angle)

    def polygon(values: list[float]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in
                        (point(axis, value) for axis, value in enumerate(values)))

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 12 440 328" '
        'role="img" aria-labelledby="title desc">',
        '<title id="title">Demo player KPI comparison</title>',
        '<desc id="desc">Five axes normalized to stated demo maxima. '
        'Exact values are in the comparison table below. Cyan is your highlighted pick; '
        'the white dashed line is the other player.</desc>',
        '<rect width="460" height="350" fill="#091525"/>',
    ]
    for level in (.25, .5, .75, 1):
        parts.append(f'<polygon points="{polygon([level] * 5)}" '
                     'fill="none" stroke="#293d56" stroke-width="1.5"/>')
    for axis in range(5):
        x, y = point(axis, 1)
        parts.append(f'<line x1="230" y1="175" x2="{x}" y2="{y}" stroke="#293d56"/>')
    # Draw the other player first so the cyan pick remains easy to see.
    for player in sorted(MOCK_PLAYERS, key=lambda item: item["id"] == pick_id):
        index = next(i for i, item in enumerate(MOCK_PLAYERS) if item["id"] == player["id"])
        values = [metric[2 + index] / metric[1] for metric in DEMO_METRICS]
        selected = player["id"] == pick_id
        color = "#39b4e3" if selected else "#f4f8fc"
        dash = "" if selected else ' stroke-dasharray="7 4"'
        parts.append(f'<polygon points="{polygon(values)}" fill="{color}" '
                     f'fill-opacity=".15" stroke="{color}" stroke-width="3"{dash}/>')
    labels = (
        (230, 32, ("xGsum",)),
        (395, 145, ("Shots",)),
        (325, 310, ("Shots on", "target %")),
        (130, 310, ("Fast crossings",)),
        (65, 145, ("Shots (PRE)",)),
    )
    for x, y, lines in labels:
        parts.append(f'<text x="{x}" y="{y}" text-anchor="middle" '
                     'fill="#c4d2e1" font-family="Arial, sans-serif" font-size="16">')
        for line_index, line in enumerate(lines):
            parts.append(f'<tspan x="{x}" dy="{0 if line_index == 0 else 21}">{line}</tspan>')
        parts.append('</text>')
    parts.append('</svg>')
    return "".join(parts)


def demo_metric_leads() -> list[int]:
    """Count strictly higher values for each player across the demo metrics."""
    return [sum(metric[2 + index] > metric[3 - index] for metric in DEMO_METRICS)
            for index in range(2)]


def demo_comparison_insight() -> str:
    leads = demo_metric_leads()
    ranking = sorted(range(2), key=lambda index: leads[index], reverse=True)
    return "Demo metrics (higher is better): " + "; ".join(
        f"#{MOCK_PLAYERS[index]['number']} leads in {leads[index]} of {len(DEMO_METRICS)}"
        for index in ranking
    ) + "."


def demo_comparison_table(pick_id: str) -> str:
    """Use the same fixtures as the radar, highlighting strictly higher values."""
    parts = ['<table><caption>Cyan bold values are higher; higher is better.</caption><thead><tr>',
             '<th scope="col">Metric</th>']
    for player in MOCK_PLAYERS:
        suffix = " · pick" if player["id"] == pick_id else ""
        parts.append(f'<th scope="col">#{player["number"]}{suffix}</th>')
    parts.append('</tr></thead><tbody>')
    for name, maximum, a, b, value_format in DEMO_METRICS:
        parts.append(f'<tr><th scope="row">{escape(name)}</th>')
        for value, other in ((a, b), (b, a)):
            text = format(value, value_format) + ("%" if name.endswith("%") else "")
            if value > other:
                text = f'<strong aria-label="{text}, higher value">{text}</strong>'
            parts.append(f'<td>{text}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table>')
    return "".join(parts)


def render_player_statistics(player_pick: dict) -> None:
    """Share the unchanged KPI comparison before and after confirmation."""
    with st.container(key="reveal-chart"):
        st.image(demo_radar_svg(player_pick["id"]), width="stretch")
        with st.container(key="reveal-legend"):
            legend = ['<div class="reveal-legend">']
            for player in MOCK_PLAYERS:
                is_pick = player["id"] == player_pick["id"]
                line_class = "reveal-line" if is_pick else "reveal-line reveal-line-other"
                suffix = " · your pick (solid cyan)" if is_pick else " (dashed white)"
                legend.append(
                    f'<div class="reveal-legend-row"><span class="{line_class}" aria-hidden="true"></span>'
                    f'<span>{escape(player["name"])} · #{player["number"]}{suffix}</span></div>'
                )
            legend.append('</div>')
            st.html("".join(legend))
        st.caption(
            "Radar: values divided by fixed demo maxima, not percentiles. "
            "Maxima: xGsum 1.00; Shots 10; Shots on target 100%; "
            "Fast crossings 10; Shots (PRE) 5."
        )
    st.write(demo_comparison_insight())
    with st.container(key="reveal-table"):
        st.html(demo_comparison_table(player_pick["id"]))


def continue_to_confirmation() -> None:
    if st.session_state.mock_vote is not None:
        navigate("reveal")
    elif st.session_state.screen == "statistics" and selected_player() is not None:
        navigate("hold_to_vote")


def render_statistics() -> None:
    """Show player KPIs before the final decision, without fan voting results."""
    if st.session_state.mock_vote is not None:
        navigate("reveal")
        st.rerun()
    with st.container(key="statistics"):
        with st.container(key="reveal"):
            player = selected_player()
            if player is None:
                st.warning("Choose a player before viewing the statistics.")
                st.button("Back to Choose", on_click=navigate, args=("choose",))
                return
            render_progress()
            with st.container(key="reveal-heading"):
                st.title("PLAYER STATISTICS", anchor=False)
                st.caption("Demo player statistics only — not official match results.")
                st.write(f"Your current pick: **{player['name']} · #{player['number']}**")
            render_player_statistics(player)
            with st.container(key="statistics-actions"):
                st.button("Continue to confirmation", key="statistics-continue",
                          on_click=continue_to_confirmation, width="stretch")
                st.button("Change pick", key="statistics-change-pick",
                          on_click=navigate, args=("choose",), type="tertiary")


def render_reveal() -> None:
    """Reveal demo statistics only after a valid session vote is confirmed."""
    vote = st.session_state.mock_vote
    voted_player = next(
        (player for player in MOCK_PLAYERS
         if isinstance(vote, dict) and player["id"] == vote.get("player_id")),
        None,
    )
    with st.container(key="reveal"):
        if voted_player is None:
            st.warning("Lock in your vote before unlocking the Reveal.")
            st.button("Back to Choose", on_click=navigate, args=("choose",))
            return
        render_progress()
        with st.container(key="reveal-heading"):
            with st.container(key="reveal-status"):
                st.write("VOTE LOCKED IN")
            st.title("RESULTS", anchor=False)
            st.caption("Demo data only — synthetic KPIs and fan shares, not official match results.")
            st.write(f"Your pick: **{voted_player['name']} · #{voted_player['number']}**")
        agreement = DEMO_FAN_SHARES[voted_player["id"]]
        with st.container(key="reveal-agreement"):
            st.write(f"**{agreement}% of fans agree with you — synthetic demo**")
            other = next(player for player in MOCK_PLAYERS if player["id"] != voted_player["id"])
            st.html(
                f'<div class="reveal-fan-bar" role="progressbar" '
                f'aria-label="Synthetic fan agreement with your pick" aria-valuemin="0" '
                f'aria-valuemax="100" aria-valuenow="{agreement}">'
                f'<span style="width: {agreement}%"></span></div>'
                f'<div class="reveal-fan-labels"><span>#{voted_player["number"]} · your pick</span>'
                f'<span>#{other["number"]} · {100 - agreement}%</span></div>'
            )
        render_player_statistics(voted_player)
        with st.container(key="reveal-home"):
            st.button(
                "Home", icon=":material/home:", key="reveal-home-button",
                on_click=navigate, args=("enter",),
            )


def main() -> None:
    st.set_page_config(
        page_title="UBS Key Player Battle",
        page_icon="⚡",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    apply_styles()
    if "screen" not in st.session_state:
        st.session_state.screen = "enter"
    st.session_state.setdefault("selected_player_id", None)
    st.session_state.setdefault("mock_vote", None)

    screens = {
        "enter": render_enter_battle,
        "choose": render_choose,
        "statistics": render_statistics,
        "hold_to_vote": render_hold_to_vote,
        "reveal": render_reveal,
    }
    screens.get(st.session_state.screen, render_enter_battle)()


if __name__ == "__main__":
    main()
