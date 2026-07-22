from __future__ import annotations

from html import escape as _escape
from pathlib import Path

import streamlit as st

from daily_thirty.decide import decide
from daily_thirty.state import load_config, load_position, record_buy, save_position


def main() -> None:
    st.set_page_config(page_title="Daily Thirty", page_icon="£", layout="centered")
    st.markdown(
        """
        <style>
        .stApp { background: #eef2f4; color: #12202a; }
        h1 { font-family: "Segoe UI", system-ui, sans-serif; font-weight: 700; letter-spacing: -0.03em; }
        .decision-box {
            background: #ffffff; border-left: 4px solid #0f6b5c; border-radius: 4px;
            padding: 1.25rem 1.5rem; white-space: pre-wrap; font-size: 1.05rem;
            line-height: 1.5; color: #12202a; box-shadow: 0 1px 2px rgba(18,32,42,0.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Daily Thirty")
    st.caption("£30 a day · one stock · HOLD or SELL & ROTATE")

    cfg = load_config()
    pos = load_position()

    # --- Current position ---
    st.subheader("Your position")
    if pos is None:
        st.info("No position saved yet. Run **Get today's decision**, then record your buy below.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Ticker", pos.ticker)
        c2.metric("Shares", f"{pos.shares:.4f}")
        c3.metric("Entry", f"{pos.entry_price:.2f}")

    # --- Decision ---
    st.subheader("Today")
    if st.button("Get today's decision", type="primary", use_container_width=True):
        with st.spinner("Checking prices…"):
            result = decide(cfg, pos)
        st.session_state["last_decision"] = result.message
        st.session_state["last_action"] = result.action

    if "last_decision" in st.session_state:
        action = st.session_state.get("last_action", "")
        if action == "HOLD":
            st.success("HOLD")
        elif action == "SELL_AND_ROTATE":
            st.warning("SELL & ROTATE")
        else:
            st.info("FIRST BUY / OPEN")
        st.markdown(
            f'<div class="decision-box">{_escape(st.session_state["last_decision"])}</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Record trades ---
    st.subheader("After you trade in your broker")
    tab_buy, tab_sell = st.tabs(["I bought", "I sold"])

    with tab_buy:
        with st.form("buy_form"):
            ticker = st.text_input("Ticker", value=(pos.ticker if pos else "")).upper().strip()
            shares = st.number_input("Shares", min_value=0.0, step=0.0001, format="%.6f")
            fill = st.number_input("Fill price", min_value=0.0, step=0.01, format="%.2f")
            submitted = st.form_submit_button("Save buy", use_container_width=True)
        if submitted:
            if not ticker or shares <= 0 or fill <= 0:
                st.error("Enter ticker, shares, and fill price.")
            else:
                existing = load_position()
                new_pos = record_buy(existing, ticker, shares, fill)
                if existing and existing.ticker == ticker:
                    st.success(
                        f"Added to {ticker}. Now {new_pos.shares:.6f} shares @ avg {new_pos.entry_price:.2f}."
                    )
                else:
                    st.success(
                        f"Saved {new_pos.shares:.6f} × {new_pos.ticker} @ {new_pos.entry_price:.2f}."
                    )
                save_position(new_pos)
                st.rerun()

    with tab_sell:
        with st.form("sell_form"):
            fill = st.number_input(
                "Sell fill price", min_value=0.0, step=0.01, format="%.2f", key="sell_fill"
            )
            submitted = st.form_submit_button("Save sell (clear position)", use_container_width=True)
        if submitted:
            current = load_position()
            if current is None:
                st.error("No position to sell.")
            elif fill <= 0:
                st.error("Enter the fill price.")
            else:
                proceeds = current.shares * fill
                st.success(
                    f"Sold {current.shares:.6f} × {current.ticker} @ {fill:.2f} → £{proceeds:.2f}."
                )
                save_position(None)
                st.rerun()

    st.divider()
    with st.expander("Watchlist (from config.yaml)"):
        st.write(", ".join(str(t) for t in cfg.get("watchlist", [])))
        st.caption(f"Stop: {float(cfg.get('stop_pct', 0.04)):.0%} below entry · Daily: £{cfg.get('daily_pounds', 30)}")
        st.caption(f"Config: `{Path.cwd() / 'config.yaml'}`")


if __name__ == "__main__":
    main()
