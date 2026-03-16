import streamlit as st
import pandas as pd
from datetime import timedelta, datetime
import io
import numpy as np

# 1. ASIGURARE DEPENDENȚE
try:
    import openpyxl
except ImportError:
    import openpyxl

import plotly.express as px
import plotly.graph_objects as go

# PDF import
from pdf_report import generate_full_pdf_report

# 2. CONFIGURARE PAGINĂ ȘI DESIGN
st.set_page_config(page_title="TradingView Payout & Strategy", page_icon="logo-lvlup.png", layout="wide")

st.markdown("""
    <style>
    /* ── GENERAL ── */
    .stApp { background-color: #0e1117; color: white; }

    .stat-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 15px;
        height: 110px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .stat-label {
        color: #8b949e;
        font-size: 13px;
        text-transform: uppercase;
        font-weight: 600;
        margin-bottom: 8px;
        letter-spacing: 0.5px;
    }
    .stat-value {
        font-size: 24px;
        font-weight: bold;
        line-height: 1.2;
    }
    .stat-sub {
        font-size: 13px;
        color: #8b949e;
        margin-top: 4px;
    }

    div[data-testid="stExpander"] { background-color: #161b22; border: 1px solid #30363d; }
    .top-box { background-color: #0d2111; border-left: 5px solid #00cf8d; padding: 12px; border-radius: 8px; margin-bottom: 10px; border-right: 1px solid #30363d; border-top: 1px solid #30363d; border-bottom: 1px solid #30363d; }
    .bottom-box { background-color: #210d0d; border-left: 5px solid #cf0000; padding: 12px; border-radius: 8px; margin-bottom: 10px; border-right: 1px solid #30363d; border-top: 1px solid #30363d; border-bottom: 1px solid #30363d; }

    .day-card { padding: 10px; border-radius: 8px; text-align: center; margin: 2px; border: 1px solid #30363d; }
    .day-win { background-color: #0d2111; border-color: #00cf8d; }
    .day-loss { background-color: #210d0d; border-color: #cf0000; }
    .day-neutral { background-color: #161b22; opacity: 0.5; }

    /* ── @MEDIA PRINT — Fix grafice tăiate ── */
    @media print {
        header[data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        .stDownloadButton,
        footer,
        #MainMenu { display: none !important; }

        .main .block-container {
            max-width: 100% !important;
            padding: 0.5cm 1cm !important;
        }

        /* Forțează graficele Plotly să nu fie tăiate */
        .js-plotly-plot,
        .plotly,
        [data-testid="stPlotlyChart"],
        .element-container:has(.js-plotly-plot) {
            width: 100% !important;
            max-width: 100% !important;
            page-break-inside: avoid !important;
            break-inside: avoid !important;
            overflow: visible !important;
        }

        .js-plotly-plot svg,
        .js-plotly-plot .main-svg {
            width: 100% !important;
            height: auto !important;
            max-width: 100% !important;
        }

        [data-testid="column"],
        [data-testid="stColumns"] {
            break-inside: avoid !important;
            page-break-inside: avoid !important;
        }

        .stat-card, .top-box, .bottom-box {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
            page-break-inside: avoid !important;
        }

        [data-testid="stExpander"],
        .element-container {
            page-break-inside: avoid !important;
            break-inside: avoid !important;
        }

        table { font-size: 8pt !important; }

        * {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)


# --- FUNCȚIE CALCUL PROBABILITĂȚI ȘIRURI ---
def get_streak_probabilities(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame(), ""
    df_sorted = df.sort_values('Entry Time')
    results = df_sorted['Result'].tolist()
    win_streaks, loss_streaks = {}, {}
    curr_streak_len, curr_type = 0, None
    for i in range(len(results) - 1):
        if i == 0: curr_streak_len, curr_type = 1, results[i]
        else:
            if results[i] == results[i-1]: curr_streak_len += 1
            else: curr_streak_len, curr_type = 1, results[i]
        next_is_win = 1 if results[i+1] == 'Win' else 0
        target_dict = win_streaks if curr_type == 'Win' else loss_streaks
        if curr_streak_len not in target_dict: target_dict[curr_streak_len] = [0, 0]
        target_dict[curr_streak_len][0] += next_is_win
        target_dict[curr_streak_len][1] += 1

    last_streak_type = results[-1]
    active_streak_len = 0
    for res in reversed(results):
        if res == last_streak_type: active_streak_len += 1
        else: break
    active_streak_label = f"{active_streak_len} {last_streak_type}"

    def format_dict(d, label):
        data = []
        for k in sorted(d.keys()):
            prob = (d[k][0] / d[k][1]) * 100
            data.append({"Șir curent": f"{k} {label}", "Probabilitate Win Următor": f"{prob:.1f}%", "Eșantion": f"{d[k][1]} ori"})
        return pd.DataFrame(data)

    return format_dict(win_streaks, "Win"), format_dict(loss_streaks, "Loss"), active_streak_label


def get_max_streaks(df):
    if df.empty: return 0, 0
    results = df.sort_values('Entry Time')['Result'].tolist()
    max_win, max_loss = 0, 0
    curr_win, curr_loss = 0, 0
    for r in results:
        if r == 'Win':
            curr_win += 1; curr_loss = 0; max_win = max(max_win, curr_win)
        else:
            curr_loss += 1; curr_win = 0; max_loss = max(max_loss, curr_loss)
    return max_win, max_loss


def simulate_payout_timeline(df, num_accounts, payout_days):
    df_sorted = df.sort_values('Entry Time').copy()
    if df_sorted.empty: return 0.0, [], [0.0]*num_accounts

    account_balances = [0.0] * num_accounts
    cycle_drawdowns = [0.0] * num_accounts
    payout_cycles = []
    current_acc_idx = 0
    payout_interval = timedelta(days=payout_days)
    cycle_start = df_sorted['Entry Time'].iloc[0]
    trades_count = 0

    for index, row in df_sorted.iterrows():
        if row['Entry Time'] >= cycle_start + payout_interval:
            total_cycle_payout = sum([max(0, b) for b in account_balances])
            payout_cycles.append({
                'Interval': f"{cycle_start.strftime('%d %b')} - {(cycle_start + payout_interval).strftime('%d %b')}",
                'Payout': total_cycle_payout,
                'Max DD Ciclu': min(cycle_drawdowns),
                'Trades': trades_count,
                'Luna': cycle_start.strftime('%B %Y')
            })
            account_balances = [0.0] * num_accounts
            cycle_drawdowns = [0.0] * num_accounts
            trades_count = 0
            cycle_start = row['Entry Time']

        pnl = row['Net P&L USD']
        account_balances[current_acc_idx] += pnl
        trades_count += 1

        if account_balances[current_acc_idx] < cycle_drawdowns[current_acc_idx]:
            cycle_drawdowns[current_acc_idx] = account_balances[current_acc_idx]

        if row['Result'] == 'Loss' or (row['Result'] == 'Win' and account_balances[current_acc_idx] >= 0):
            current_acc_idx = (current_acc_idx + 1) % num_accounts

    total_payout_sum = sum([c['Payout'] for c in payout_cycles])
    return total_payout_sum, payout_cycles, account_balances


def render_weekly_calendar(df, title_key):
    st.markdown("### 📅 Calendar Profit Săptămânal")

    col_sel, col_info = st.columns([1, 3])
    with col_sel:
        ref_date = st.date_input("Caută o săptămână (alege orice zi):", datetime.now().date(), key=f"cal_date_{title_key}")

    start_week = ref_date - timedelta(days=ref_date.weekday())
    end_week = start_week + timedelta(days=6)

    with col_info:
        st.write(f"**Săptămâna curentă vizualizată:** {start_week.strftime('%d %b %Y')} — {end_week.strftime('%d %b %Y')}")

    mask = (df['Entry Time'].dt.date >= start_week) & (df['Entry Time'].dt.date <= end_week)
    df_week = df.loc[mask].copy()
    df_week['DateStr'] = df_week['Entry Time'].dt.strftime('%Y-%m-%d')
    daily_stats = df_week.groupby('DateStr').agg(PnL=('Net P&L USD', 'sum'), Count=('Trade #', 'count')).to_dict('index')

    cols = st.columns(7)
    days_names = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']

    for i in range(7):
        curr_day = start_week + timedelta(days=i)
        curr_day_str = curr_day.strftime('%Y-%m-%d')
        with cols[i]:
            st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:14px;'>{days_names[i]}<br><span style='font-size:12px; color:#888'>{curr_day.strftime('%d %b')}</span></div>", unsafe_allow_html=True)
            if curr_day_str in daily_stats:
                pnl = daily_stats[curr_day_str]['PnL']
                cnt = daily_stats[curr_day_str]['Count']
                css_class = "day-win" if pnl >= 0 else "day-loss"
                pnl_fmt = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
                st.markdown(f"""<div class="day-card {css_class}"><div style="font-size:18px; font-weight:bold;">{pnl_fmt}</div><div style="font-size:12px;">{cnt} trades</div></div>""", unsafe_allow_html=True)
            else:
                st.markdown("""<div class="day-card day-neutral"><div style="font-size:18px;">-</div><div style="font-size:12px;">No activity</div></div>""", unsafe_allow_html=True)
    st.markdown("---")


def render_risk_management(df):
    if df.empty:
        st.warning("Nu există date pentru Risk Management.")
        return

    wins = df[df['Result'] == 'Win']
    losses = df[df['Result'] == 'Loss']
    total = len(df)
    win_rate = len(wins) / total if total > 0 else 0
    loss_rate = 1 - win_rate
    avg_win = wins['Net P&L USD'].mean() if not wins.empty else 0
    avg_loss = abs(losses['Net P&L USD'].mean()) if not losses.empty else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 1

    kelly = win_rate - (loss_rate / rr_ratio) if rr_ratio > 0 else 0
    kelly_half = kelly / 2

    st.markdown("## 💰 Risk Management")
    st.markdown("---")

    st.markdown("### 📊 Statistici Reale din Strategia Ta")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{win_rate*100:.1f}%")
    c2.metric("Avg Win / Avg Loss (RR)", f"{rr_ratio:.2f}")
    c3.metric("Avg Win", f"${avg_win:,.2f}")
    c4.metric("Avg Loss", f"${avg_loss:,.2f}")
    st.markdown("---")

    st.markdown("### ⚙️ Configurare Manuală Cont")
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        account_size = st.number_input("Mărime Cont ($):", min_value=1000, max_value=500000, value=25000, step=1000)
    with col_b:
        daily_dd_pct = st.slider("Daily Max Drawdown (%):", 1, 15, 5)
    with col_c:
        max_dd_pct = st.slider("Overall Max Drawdown (%):", 1, 20, 10)
    with col_d:
        max_trades_per_day = st.number_input("Max trades/zi:", min_value=1, max_value=20, value=3)

    daily_dd_usd = account_size * (daily_dd_pct / 100)
    max_dd_usd = account_size * (max_dd_pct / 100)

    dd_col1, dd_col2 = st.columns(2)
    with dd_col1:
        st.markdown(f"""
            <div style="background:#1a1005; border:1px solid #ffa500; border-left:5px solid #ffa500;
                        border-radius:10px; padding:12px; text-align:center; margin-top:8px;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Daily Max Drawdown</p>
                <h3 style="color:#ffa500; margin:5px 0;">{daily_dd_pct}% = ${daily_dd_usd:,.2f}</h3>
                <p style="margin:0; font-size:12px; color:#888;">Limita per zi — resetează zilnic</p>
            </div>""", unsafe_allow_html=True)
    with dd_col2:
        st.markdown(f"""
            <div style="background:#210d0d; border:1px solid #ff4b4b; border-left:5px solid #ff4b4b;
                        border-radius:10px; padding:12px; text-align:center; margin-top:8px;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Overall Max Drawdown</p>
                <h3 style="color:#ff4b4b; margin:5px 0;">{max_dd_pct}% = ${max_dd_usd:,.2f}</h3>
                <p style="margin:0; font-size:12px; color:#888;">Limita totala cont — cont blown daca depasesti</p>
            </div>""", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("### 🎯 Kelly Criterion — Risc Optim per Trade")

    FUNDED_MAX_RISK_PCT = 1.0
    kelly_pct = max(0, kelly) * 100
    half_kelly_pct = max(0, kelly_half) * 100
    quarter_kelly_pct = max(0, kelly / 4) * 100
    recommended_pct = min(half_kelly_pct, FUNDED_MAX_RISK_PCT)
    kelly_usd = account_size * (recommended_pct / 100)

    st.info(f"""
📌 **Notă despre Kelly Criterion:** Formula matematică sugerează {half_kelly_pct:.1f}% (Half Kelly) bazat pe statisticile tale.
Însă pentru **funded accounts**, riscul maxim recomandat per trade este **1%** din cauza regulilor stricte de drawdown.
Riscul afișat ca *Recomandat* ține cont de ambele.
""")

    col_k1, col_k2, col_k3 = st.columns(3)
    with col_k1:
        st.markdown(f"""
            <div style="background:#161b22; border:1px solid #30363d; border-left: 5px solid #888;
                        border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; opacity:0.7; font-size:12px;">Half Kelly (teoretic)</p>
                <h2 style="color:#aaa; margin:5px 0;">{half_kelly_pct:.1f}%</h2>
                <p style="margin:0; font-size:12px; opacity:0.5;">${account_size * max(0, kelly_half):,.2f} per trade</p>
                <p style="margin:0; font-size:11px; color:#888;">📊 Optim matematic — ignoră regulile funded</p>
            </div>""", unsafe_allow_html=True)
    with col_k2:
        st.markdown(f"""
            <div style="background:#0d2111; border:1px solid #00cf8d; border-left: 5px solid #00cf8d;
                        border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; opacity:0.7; font-size:12px;">✅ RECOMANDAT FUNDED</p>
                <h2 style="color:#00cf8d; margin:5px 0;">{recommended_pct:.1f}%</h2>
                <p style="margin:0; font-size:12px; opacity:0.8;">${kelly_usd:,.2f} per trade</p>
                <p style="margin:0; font-size:11px; color:#00cf8d;">✅ Respectă regulile DD funded</p>
            </div>""", unsafe_allow_html=True)
    with col_k3:
        st.markdown(f"""
            <div style="background:#161b22; border:1px solid #30363d; border-left: 5px solid #4a9eff;
                        border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; opacity:0.7; font-size:12px;">Conservator</p>
                <h2 style="color:#4a9eff; margin:5px 0;">0.5%</h2>
                <p style="margin:0; font-size:12px; opacity:0.5;">${account_size * 0.005:,.2f} per trade</p>
                <p style="margin:0; font-size:11px; color:#888;">🛡️ Maxim protecție capital</p>
            </div>""", unsafe_allow_html=True)

    st.write("")
    if kelly <= 0:
        st.error("⚠️ Kelly negativ — strategia ta nu are edge suficient cu parametrii actuali. Revizuiește RR ratio sau win rate.")
    else:
        st.success(f"📌 Recomandat pentru funded: risc **{recommended_pct:.1f}%** per trade = **${kelly_usd:,.2f}** pe un cont de **${account_size:,}**")

    st.markdown("---")

    st.markdown("### 📐 Fixed Fractional Risk — Comparație Scenarii")
    risk_scenarios = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    scenario_data = []
    for r in risk_scenarios:
        risk_usd = account_size * (r / 100)
        losses_before_daily = int(daily_dd_usd / risk_usd) if risk_usd > 0 else 0
        losses_before_overall = int(max_dd_usd / risk_usd) if risk_usd > 0 else 0
        estimated_daily_risk = risk_usd * max_trades_per_day
        daily_ok = "✅" if estimated_daily_risk <= daily_dd_usd else "❌"
        if r == 1.0: status = "✅ Recomandat funded"
        elif r == 0.5: status = "🛡️ Conservator"
        elif r <= FUNDED_MAX_RISK_PCT: status = "✅ Acceptabil"
        else: status = "⚠️ Agresiv pentru funded"
        scenario_data.append({
            "Risc %": f"{r}%",
            "$ per Trade": f"${risk_usd:,.2f}",
            f"L consecutive → Daily DD ({daily_dd_pct}%)": f"{losses_before_daily} trades {daily_ok}",
            f"L consecutive → Overall DD ({max_dd_pct}%)": f"{losses_before_overall} trades",
            "Risc zilnic maxim (est.)": f"${estimated_daily_risk:,.2f}",
            "Status": status
        })

    df_scenarios = pd.DataFrame(scenario_data)

    def highlight_recommended(row):
        if "Recomandat" in row["Status"]:
            return ['background-color: #0d2111; color: white'] * len(row)
        elif "Agresiv" in row["Status"]:
            return ['background-color: #210d0d; color: white'] * len(row)
        return [''] * len(row)

    st.dataframe(df_scenarios.style.apply(highlight_recommended, axis=1), use_container_width=True, hide_index=True)
    st.markdown("---")

    st.markdown("### 📉 Max Loss Streak Analysis")
    results_list = df.sort_values('Entry Time')['Result'].tolist()
    max_win_s, max_loss_s = get_max_streaks(df)
    active_loss_streak = 0
    for r in reversed(results_list):
        if r == 'Loss': active_loss_streak += 1
        else: break

    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Max Loss Streak Istoric", f"{max_loss_s} trades")
    col_s2.metric("Max Win Streak Istoric", f"{max_win_s} trades")
    delta_label = "⚠️ Atenție!" if active_loss_streak >= max_loss_s * 0.7 else "✅ Normal"
    col_s3.metric("Streak Pierderi Activ Acum", f"{active_loss_streak} trades", delta=delta_label, delta_color="inverse")

    st.markdown("#### 💸 Impact Financiar — Streak de Pierderi pe Scenarii de Risc")

    df_daily_loss = df.copy()
    df_daily_loss['Date'] = df_daily_loss['Entry Time'].dt.date
    daily_pnl = df_daily_loss.groupby('Date')['Net P&L USD'].sum()
    worst_day_loss = abs(daily_pnl.min()) if not daily_pnl.empty else 0
    worst_day_str = str(daily_pnl.idxmin()) if not daily_pnl.empty else "N/A"

    st.markdown(f"""
        <div style="background:#1a1005; border:1px solid #ffa500; border-radius:8px; padding:10px; margin-bottom:12px;">
            <span style="color:#ffa500; font-weight:bold;">📅 Cea mai proastă zi din istoric:</span>
            <span style="color:white;"> {worst_day_str} — pierdere: </span>
            <span style="color:#ff4b4b; font-weight:bold;">${worst_day_loss:,.2f}</span>
            {"&nbsp;&nbsp;✅ Sub Daily DD limit" if worst_day_loss <= daily_dd_usd else f"&nbsp;&nbsp;❌ Depășea Daily DD limit de ${daily_dd_usd:,.2f}"}
        </div>""", unsafe_allow_html=True)

    streak_impact = []
    for r in risk_scenarios:
        risk_usd = account_size * (r / 100)
        total_loss_at_max_streak = risk_usd * max_loss_s
        pct_overall = (total_loss_at_max_streak / account_size) * 100 if account_size > 0 else 0
        daily_risk_max = risk_usd * max_trades_per_day
        pct_daily = (daily_risk_max / account_size) * 100 if account_size > 0 else 0
        daily_status = "✅ OK" if daily_risk_max <= daily_dd_usd else "❌ Risc Daily DD"
        overall_status = "✅ OK" if pct_overall <= max_dd_pct else "❌ Risc Blown"
        streak_impact.append({
            "Risc %": f"{r}%",
            "$ per Trade": f"${risk_usd:,.2f}",
            f"Risc/zi ({max_trades_per_day}T)": f"${daily_risk_max:,.2f} ({pct_daily:.1f}%) {daily_status}",
            f"Worst streak ({max_loss_s}L) total": f"${total_loss_at_max_streak:,.2f} ({pct_overall:.1f}%) {overall_status}",
        })

    df_streak_impact = pd.DataFrame(streak_impact)

    def highlight_survived(row):
        col_overall = f"Worst streak ({max_loss_s}L) total"
        col_daily = f"Risc/zi ({max_trades_per_day}T)"
        if col_overall in row and "Risc Blown" in row[col_overall]:
            return ['background-color: #210d0d; color: white'] * len(row)
        if col_daily in row and "Risc Daily" in row[col_daily]:
            return ['background-color: #1a1005; color: white'] * len(row)
        return ['background-color: #0d2111; color: white'] * len(row)

    st.dataframe(df_streak_impact.style.apply(highlight_survived, axis=1), use_container_width=True, hide_index=True)

    streak_counts = {}
    curr = 0
    for r in results_list:
        if r == 'Loss': curr += 1
        else:
            if curr > 0: streak_counts[curr] = streak_counts.get(curr, 0) + 1
            curr = 0
    if curr > 0: streak_counts[curr] = streak_counts.get(curr, 0) + 1

    if streak_counts:
        df_streak_dist = pd.DataFrame(list(streak_counts.items()), columns=['Streak Lungime', 'Frecvență']).sort_values('Streak Lungime')
        fig_streak = px.bar(df_streak_dist, x='Streak Lungime', y='Frecvență',
                            title="Distribuție Loss Streaks (câte ori a apărut fiecare lungime)",
                            template="plotly_dark", color='Frecvență', color_continuous_scale='Reds')
        fig_streak.update_layout(xaxis=dict(tickmode='linear', dtick=1))
        st.plotly_chart(fig_streak, use_container_width=True, key="loss_streak_dist_rm")

    st.markdown("---")

    worst_case_loss = kelly_usd * max_loss_s
    worst_case_daily = kelly_usd * max_trades_per_day
    is_safe_overall = worst_case_loss <= max_dd_usd
    is_safe_daily = worst_case_daily <= daily_dd_usd
    overall_msg = "✅ Sub Overall DD limit" if is_safe_overall else "❌ Depășește Overall DD — consideră reducerea riscului"
    daily_msg = "✅ Sub Daily DD limit" if is_safe_daily else "❌ Depășește Daily DD — risc sa fii oprit zilnic"

    st.markdown(f"""
        <div style="background:#161b22; border:1px solid #30363d; border-radius:10px; padding:20px;">
            <h4 style="color:#00cf8d; margin-top:0;">📋 Sumar Recomandări pentru Contul Tău</h4>
            <ul style="line-height: 2.4; font-size: 15px;">
                <li>🎯 <b>Risc recomandat per trade (Half Kelly):</b> <span style="color:#00cf8d;">{half_kelly_pct:.1f}% = ${kelly_usd:,.2f}</span></li>
                <li>📉 <b>Max loss streak istoric:</b> {max_loss_s} trades consecutive</li>
                <li>💰 <b>Pierdere worst streak la {half_kelly_pct:.1f}% risc:</b> ${worst_case_loss:,.2f} ({(worst_case_loss / account_size * 100) if account_size > 0 else 0:.1f}% din cont) — <b>{overall_msg}</b></li>
                <li>⚡ <b>Risc maxim intr-o zi ({max_trades_per_day} trades):</b> ${worst_case_daily:,.2f} ({(worst_case_daily / account_size * 100) if account_size > 0 else 0:.1f}% din cont) — <b>{daily_msg}</b></li>
                <li>🟠 <b>Daily DD limit:</b> {daily_dd_pct}% = ${daily_dd_usd:,.2f} &nbsp;|&nbsp; 🔴 <b>Overall DD limit:</b> {max_dd_pct}% = ${max_dd_usd:,.2f}</li>
            </ul>
        </div>""", unsafe_allow_html=True)


def render_monte_carlo(df):
    if df.empty:
        st.warning("Nu există date pentru Monte Carlo.")
        return

    st.markdown("## 🎲 Simulare Monte Carlo")
    st.markdown("Amestecă aleator ordinea trade-urilor tale de **N ori** și arată distribuția posibilelor outcome-uri reale.")
    st.markdown("---")

    st.markdown("### ⚙️ Configurare")
    mc_c1, mc_c2, mc_c3, mc_c4, mc_c5 = st.columns(5)
    with mc_c1:
        mc_account = st.number_input("Cont ($):", min_value=1000, max_value=500000, value=25000, step=1000, key="mc_account")
    with mc_c2:
        mc_daily_dd = st.slider("Daily DD (%):", 1, 15, 5, key="mc_daily_dd")
    with mc_c3:
        mc_overall_dd = st.slider("Overall DD (%):", 1, 20, 10, key="mc_overall_dd")
    with mc_c4:
        mc_trades_per_day = st.number_input("Max trades/zi:", min_value=1, max_value=20, value=3, key="mc_tpd")
    with mc_c5:
        mc_risk_pct = st.selectbox("Risc % per trade:", [0.25, 0.5, 0.75, 1.0, 1.5, 2.0], index=3, key="mc_risk2")

    mc_daily_dd_usd = mc_account * (mc_daily_dd / 100)
    mc_overall_dd_usd = mc_account * (mc_overall_dd / 100)
    mc_risk_usd = mc_account * (mc_risk_pct / 100)

    mc_col1, mc_col2 = st.columns(2)
    with mc_col1:
        n_simulations = st.slider("Număr simulări:", 100, 2000, 500, step=100, key="mc_n_sims")
    with mc_col2:
        n_trades_sim = st.slider("Trades simulate per run:", 10, min(500, len(df)), min(100, len(df)), step=10, key="mc_n_trades")

    st.markdown("---")

    if st.button("▶️ Rulează Simularea Monte Carlo", key="mc_run2", use_container_width=True):
        pnl_values = df['Net P&L USD'].values
        normalized = np.where(pnl_values > 0, 1.0, -1.0)
        all_curves = []
        final_balances = []
        blown_daily_count = 0
        blown_overall_count = 0
        survived_count = 0
        np.random.seed(None)
        progress = st.progress(0, text="Simulare în curs...")

        for i in range(n_simulations):
            sampled = np.random.choice(normalized, size=n_trades_sim, replace=True)
            balance = 0.0; daily_balance = 0.0; blown = False; blown_by = None; curve = [0.0]
            for j, outcome in enumerate(sampled):
                pnl = outcome * mc_risk_usd
                balance += pnl; daily_balance += pnl
                if (j + 1) % mc_trades_per_day == 0: daily_balance = 0.0
                if daily_balance <= -mc_daily_dd_usd: blown = True; blown_by = 'daily'; break
                if balance <= -mc_overall_dd_usd: blown = True; blown_by = 'overall'; break
                curve.append(balance)
            all_curves.append(curve)
            final_balances.append(balance)
            if blown:
                if blown_by == 'daily': blown_daily_count += 1
                else: blown_overall_count += 1
            else: survived_count += 1
            if (i + 1) % 50 == 0:
                progress.progress((i + 1) / n_simulations, text=f"Simulare în curs... {i+1}/{n_simulations}")

        progress.empty()

        survival_rate = (survived_count / n_simulations) * 100
        blown_rate = 100 - survival_rate
        median_final = float(np.median(final_balances))
        p10_final = float(np.percentile(final_balances, 10))
        p25_final = float(np.percentile(final_balances, 25))
        p75_final = float(np.percentile(final_balances, 75))
        p90_final = float(np.percentile(final_balances, 90))
        best_final = float(np.max(final_balances))
        worst_final = float(np.min(final_balances))

        res_c1, res_c2, res_c3, res_c4 = st.columns(4)
        with res_c1:
            color = "#00cf8d" if survival_rate >= 70 else "#ffa500" if survival_rate >= 50 else "#ff4b4b"
            st.markdown(f"""<div style="background:#161b22; border:1px solid {color}; border-left:5px solid {color};
                border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Rata Supraviețuire</p>
                <h2 style="color:{color}; margin:5px 0;">{survival_rate:.1f}%</h2>
                <p style="margin:0; font-size:12px; color:#888;">{survived_count}/{n_simulations} runs ok</p>
            </div>""", unsafe_allow_html=True)
        with res_c2:
            st.markdown(f"""<div style="background:#161b22; border:1px solid #ff4b4b; border-left:5px solid #ff4b4b;
                border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Rata Blown</p>
                <h2 style="color:#ff4b4b; margin:5px 0;">{blown_rate:.1f}%</h2>
                <p style="margin:0; font-size:12px; color:#888;">Daily: {blown_daily_count} | Overall: {blown_overall_count}</p>
            </div>""", unsafe_allow_html=True)
        with res_c3:
            med_color = "#00cf8d" if median_final >= 0 else "#ff4b4b"
            st.markdown(f"""<div style="background:#161b22; border:1px solid #30363d; border-left:5px solid {med_color};
                border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Profit Median</p>
                <h2 style="color:{med_color}; margin:5px 0;">${median_final:,.0f}</h2>
                <p style="margin:0; font-size:12px; color:#888;">după {n_trades_sim} trades</p>
            </div>""", unsafe_allow_html=True)
        with res_c4:
            st.markdown(f"""<div style="background:#161b22; border:1px solid #30363d; border-left:5px solid #4a9eff;
                border-radius:10px; padding:15px; text-align:center;">
                <p style="margin:0; font-size:12px; opacity:0.7; text-transform:uppercase;">Interval P10 — P90</p>
                <h2 style="color:#4a9eff; margin:5px 0; font-size:16px;">${p10_final:,.0f} → ${p90_final:,.0f}</h2>
                <p style="margin:0; font-size:12px; color:#888;">worst 10% — best 10%</p>
            </div>""", unsafe_allow_html=True)

        st.write("")
        fig_mc = go.Figure()
        for idx, curve in enumerate(all_curves[:300]):
            is_blown = len(curve) < n_trades_sim + 1
            fig_mc.add_trace(go.Scatter(y=curve, mode='lines',
                line=dict(color='rgba(255,75,75,0.07)' if is_blown else 'rgba(0,207,141,0.05)', width=1),
                showlegend=False, hoverinfo='skip'))

        max_len = max(len(c) for c in all_curves)
        padded = [c + [c[-1]] * (max_len - len(c)) for c in all_curves]
        median_curve = np.median(padded, axis=0)
        p25_curve = np.percentile(padded, 25, axis=0)
        p75_curve = np.percentile(padded, 75, axis=0)

        fig_mc.add_trace(go.Scatter(
            y=list(p75_curve) + list(p25_curve[::-1]),
            x=list(range(len(p75_curve))) + list(range(len(p25_curve)-1, -1, -1)),
            fill='toself', fillcolor='rgba(0,207,141,0.08)',
            line=dict(color='rgba(0,0,0,0)'), showlegend=True, name='Zona P25-P75'))
        fig_mc.add_trace(go.Scatter(y=median_curve, mode='lines',
            line=dict(color='#00cf8d', width=2.5), name='Median'))
        fig_mc.add_hline(y=0, line_dash="dash", line_color="#555", opacity=0.6)
        fig_mc.add_hline(y=-mc_daily_dd_usd, line_dash="dot", line_color="#ffa500",
                         opacity=0.9, annotation_text=f"Daily DD -{mc_daily_dd}%", annotation_position="bottom right")
        fig_mc.add_hline(y=-mc_overall_dd_usd, line_dash="dot", line_color="#ff4b4b",
                         opacity=0.9, annotation_text=f"Overall DD -{mc_overall_dd}%", annotation_position="bottom right")
        fig_mc.update_layout(
            title=f"Monte Carlo — {n_simulations} Simulări | {mc_risk_pct}% risc | {n_trades_sim} trades",
            template="plotly_dark", xaxis_title="Trade #", yaxis_title="P&L ($)",
            height=500, margin=dict(t=50, b=40, l=0, r=130), legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig_mc, use_container_width=True, key="mc_equity_curves2")

        colors_hist = ['#00cf8d' if x >= 0 else '#ff4b4b' for x in final_balances]
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(x=final_balances, nbinsx=60,
            marker_color=colors_hist, opacity=0.85, name="Profit final"))
        fig_hist.add_vline(x=0, line_dash="dash", line_color="white", opacity=0.4)
        fig_hist.add_vline(x=median_final, line_dash="solid", line_color="#00cf8d", opacity=0.9,
                           annotation_text=f"Median ${median_final:,.0f}", annotation_position="top right")
        fig_hist.add_vline(x=p10_final, line_dash="dot", line_color="#ffa500", opacity=0.7,
                           annotation_text=f"P10 ${p10_final:,.0f}", annotation_position="top left")
        fig_hist.update_layout(title=f"Distribuție Profit Final după {n_trades_sim} Trades",
            template="plotly_dark", xaxis_title="Profit Final ($)", yaxis_title="Frecvență",
            height=320, margin=dict(t=50, b=40, l=0, r=0))
        st.plotly_chart(fig_hist, use_container_width=True, key="mc_hist2")

        if survival_rate >= 80: st.success("🟢 **Excelent** — strategia ta este foarte robustă la acest nivel de risc.")
        elif survival_rate >= 60: st.warning("🟡 **Acceptabil** — strategia supraviețuiește în majoritatea scenariilor, dar există risc real de blown.")
        elif survival_rate >= 40: st.warning("🟠 **Riscant** — aproape jumătate din simulări ating limitele DD. Consideră reducerea riscului la 0.5%.")
        else: st.error("🔴 **Periculos** — majoritatea simulărilor blow contul. Risc prea mare pentru funded accounts.")
    else:
        st.info("👆 Configurează parametrii de mai sus și apasă **▶️ Rulează** pentru a vedea simularea.")


def render_advanced_analysis(df):
    if df.empty:
        st.warning("Nu există date pentru Analize Avansate.")
        return

    st.markdown("## 🔬 Analize Avansate")
    st.markdown("---")

    st.markdown("### ⚠️ Detecție Overtrading")
    st.markdown("Analizează dacă zilele cu **mai multe trade-uri** au rezultate mai slabe — semn de overtrading.")

    df_ot = df.copy()
    df_ot['Date'] = df_ot['Entry Time'].dt.date
    daily_agg = df_ot.groupby('Date').agg(
        Trades=('Net P&L USD', 'count'), PnL=('Net P&L USD', 'sum'),
        Wins=('Result', lambda x: (x == 'Win').sum()),
        WR=('Result', lambda x: (x == 'Win').sum() / len(x) * 100)
    ).reset_index()

    bins = [0, 1, 2, 3, 5, 100]
    labels = ['1 trade', '2 trades', '3 trades', '4-5 trades', '6+ trades']
    daily_agg['Grup'] = pd.cut(daily_agg['Trades'], bins=bins, labels=labels)
    grup_stats = daily_agg.groupby('Grup', observed=True).agg(
        Zile=('Date', 'count'), WR_Med=('WR', 'mean'),
        PnL_Med=('PnL', 'median'), PnL_Total=('PnL', 'sum')
    ).reset_index().dropna()

    if not grup_stats.empty:
        fig_ot = px.bar(grup_stats, x='Grup', y='WR_Med',
            text=grup_stats.apply(lambda r: f"{r['WR_Med']:.0f}% WR | ${r['PnL_Med']:,.0f} | {int(r['Zile'])}z", axis=1),
            template='plotly_dark', color='WR_Med', color_continuous_scale='RdYlGn',
            title='Win Rate Mediu pe Număr de Trades/Zi')
        fig_ot.update_traces(textposition='outside')
        fig_ot.update_layout(height=380, margin=dict(t=50,b=40,l=0,r=0), yaxis_title="Win Rate (%)")
        st.plotly_chart(fig_ot, use_container_width=True, key="overtrading_bar")

        if len(daily_agg) > 3:
            fig_scatter = px.scatter(daily_agg, x='Trades', y='PnL', color='WR',
                color_continuous_scale='RdYlGn', template='plotly_dark',
                title='Profit per Zi vs Număr de Trades (fiecare punct = o zi)',
                labels={'Trades': 'Nr. Trades în zi', 'PnL': 'Profit Zi ($)', 'WR': 'Win Rate %'},
                hover_data={'Date': True, 'Trades': True, 'PnL': ':.2f', 'WR': ':.1f'})
            fig_scatter.add_hline(y=0, line_dash="dash", line_color="#555")
            z = np.polyfit(daily_agg['Trades'], daily_agg['PnL'], 1)
            p = np.poly1d(z)
            x_line = np.linspace(daily_agg['Trades'].min(), daily_agg['Trades'].max(), 50)
            trend_color = '#ff4b4b' if z[0] < 0 else '#00cf8d'
            fig_scatter.add_trace(go.Scatter(x=x_line, y=p(x_line), mode='lines',
                line=dict(color=trend_color, width=2, dash='dot'), name='Trend'))
            fig_scatter.update_layout(height=380, margin=dict(t=50,b=40,l=0,r=0))
            st.plotly_chart(fig_scatter, use_container_width=True, key="overtrading_scatter")

        if len(grup_stats) >= 2:
            wr_1 = grup_stats.iloc[0]['WR_Med']
            wr_last = grup_stats.iloc[-1]['WR_Med']
            if wr_last < wr_1 - 10: st.error(f"🔴 **Overtrading detectat** — Win Rate scade de la **{wr_1:.0f}%** la **{wr_last:.0f}%**.")
            elif wr_last < wr_1 - 5: st.warning(f"🟡 **Posibil overtrading** — Win Rate ușor mai mic în zilele cu multe trades ({wr_1:.0f}% → {wr_last:.0f}%).")
            else: st.success(f"🟢 **Fără semne de overtrading** — performanța rămâne constantă indiferent de numărul de trades/zi.")

    st.markdown("---")
    st.markdown("### 🔗 Correlații între Trade-uri Consecutive")

    df_corr = df.sort_values('Entry Time').copy()
    df_corr['Result_Bin'] = (df_corr['Result'] == 'Win').astype(int)
    df_corr['Next_Result'] = df_corr['Result_Bin'].shift(-1)
    df_corr['Prev_Result'] = df_corr['Result_Bin'].shift(1)
    df_corr = df_corr.dropna(subset=['Next_Result', 'Prev_Result'])

    ww = len(df_corr[(df_corr['Result_Bin'] == 1) & (df_corr['Next_Result'] == 1)])
    wl = len(df_corr[(df_corr['Result_Bin'] == 1) & (df_corr['Next_Result'] == 0)])
    lw = len(df_corr[(df_corr['Result_Bin'] == 0) & (df_corr['Next_Result'] == 1)])
    ll = len(df_corr[(df_corr['Result_Bin'] == 0) & (df_corr['Next_Result'] == 0)])

    p_win_after_win = ww / (ww + wl) * 100 if (ww + wl) > 0 else 0
    p_win_after_loss = lw / (lw + ll) * 100 if (lw + ll) > 0 else 0
    overall_wr = df_corr['Result_Bin'].mean() * 100

    corr_c1, corr_c2, corr_c3 = st.columns(3)
    with corr_c1:
        color = "#00cf8d" if p_win_after_win >= overall_wr else "#ff4b4b"
        st.markdown(f"""<div style="background:#161b22; border:1px solid {color}; border-left:5px solid {color};
            border-radius:10px; padding:15px; text-align:center;">
            <p style="margin:0; font-size:12px; opacity:0.7;">P(Win | trade anterior = Win)</p>
            <h2 style="color:{color}; margin:5px 0;">{p_win_after_win:.1f}%</h2>
            <p style="margin:0; font-size:12px; color:#888;">{ww}W + {wl}L = {ww+wl} cazuri</p>
        </div>""", unsafe_allow_html=True)
    with corr_c2:
        color2 = "#00cf8d" if p_win_after_loss >= overall_wr else "#ff4b4b"
        st.markdown(f"""<div style="background:#161b22; border:1px solid {color2}; border-left:5px solid {color2};
            border-radius:10px; padding:15px; text-align:center;">
            <p style="margin:0; font-size:12px; opacity:0.7;">P(Win | trade anterior = Loss)</p>
            <h2 style="color:{color2}; margin:5px 0;">{p_win_after_loss:.1f}%</h2>
            <p style="margin:0; font-size:12px; color:#888;">{lw}W + {ll}L = {lw+ll} cazuri</p>
        </div>""", unsafe_allow_html=True)
    with corr_c3:
        st.markdown(f"""<div style="background:#161b22; border:1px solid #4a9eff; border-left:5px solid #4a9eff;
            border-radius:10px; padding:15px; text-align:center;">
            <p style="margin:0; font-size:12px; opacity:0.7;">Win Rate General (referință)</p>
            <h2 style="color:#4a9eff; margin:5px 0;">{overall_wr:.1f}%</h2>
            <p style="margin:0; font-size:12px; color:#888;">baza de comparație</p>
        </div>""", unsafe_allow_html=True)

    st.write("")
    matrix = np.array([[p_win_after_loss, 100-p_win_after_loss], [p_win_after_win, 100-p_win_after_win]])
    fig_heat = go.Figure(data=go.Heatmap(
        z=matrix, x=['→ Win', '→ Loss'], y=['After Loss', 'After Win'],
        colorscale='RdYlGn', zmin=0, zmax=100,
        text=[[f"{matrix[i][j]:.1f}%" for j in range(2)] for i in range(2)],
        texttemplate="%{text}", textfont={"size": 18}))
    fig_heat.update_layout(title="Matricea de Tranziție Win/Loss (%)",
        template="plotly_dark", height=280, margin=dict(t=50,b=40,l=80,r=0))
    st.plotly_chart(fig_heat, use_container_width=True, key="transition_matrix")

    diff = p_win_after_loss - p_win_after_win
    if abs(diff) < 3: st.success(f"🟢 **Trades independente** — Win rate stabil după Win ({p_win_after_win:.1f}%) și Loss ({p_win_after_loss:.1f}%).")
    elif diff > 3: st.info(f"🔵 **Mean Reversion detectat** — după o pierdere ai mai multe șanse de win ({p_win_after_loss:.1f}% vs {p_win_after_win:.1f}%).")
    else: st.warning(f"🟡 **Momentum detectat** — win-urile tind să fie urmate de alte win-uri ({p_win_after_win:.1f}% vs {p_win_after_loss:.1f}%).")

    if len(df_corr) >= 20:
        pnl_series = df_corr['Net P&L USD'].values
        lags = range(1, min(11, len(pnl_series)//2))
        autocorrs = [pd.Series(pnl_series).autocorr(lag=l) for l in lags]
        fig_ac = px.bar(x=list(lags), y=autocorrs, template='plotly_dark',
            title='Autocorrelație PnL (lag 1-10 trades)',
            labels={'x': 'Lag (trades)', 'y': 'Correlație'},
            color=autocorrs, color_continuous_scale='RdYlGn')
        fig_ac.add_hline(y=0, line_dash="dash", line_color="#555")
        fig_ac.add_hline(y=0.2, line_dash="dot", line_color="#ffa500", opacity=0.5, annotation_text="prag semnificativ")
        fig_ac.add_hline(y=-0.2, line_dash="dot", line_color="#ffa500", opacity=0.5)
        fig_ac.update_layout(height=320, margin=dict(t=50,b=40,l=0,r=0))
        st.plotly_chart(fig_ac, use_container_width=True, key="autocorr_bar")

    st.markdown("---")
    st.markdown("### 📊 Benchmark vs Buy & Hold SPY")

    bench_col1, bench_col2 = st.columns(2)
    with bench_col1:
        bench_capital = st.number_input("Capital inițial ($):", min_value=1000, max_value=500000, value=25000, step=1000, key="bench_cap")
    with bench_col2:
        spy_annual_return = st.slider("Return anual estimat SPY (%):", 5, 20, 10)

    df_bench = df.sort_values('Entry Time').copy()
    df_bench['Cumulative_PnL'] = df_bench['Net P&L USD'].cumsum()
    start_date = df_bench['Entry Time'].min()
    end_date = df_bench['Entry Time'].max()
    days_total = (end_date - start_date).days if (end_date - start_date).days > 0 else 1
    daily_return = (1 + spy_annual_return / 100) ** (1/365) - 1
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    spy_values = [bench_capital * ((1 + daily_return) ** i) - bench_capital for i in range(len(date_range))]
    df_spy = pd.DataFrame({'Date': date_range, 'SPY_PnL': spy_values})

    strategy_final = df_bench['Cumulative_PnL'].iloc[-1] if len(df_bench) > 0 else 0
    spy_final = bench_capital * ((1 + spy_annual_return / 100) ** (days_total / 365)) - bench_capital
    spy_annual_pnl_pct = (strategy_final / bench_capital * 100) / (days_total / 365) if days_total > 0 else 0
    diff_vs_spy = strategy_final - spy_final

    bench_m1, bench_m2, bench_m3, bench_m4 = st.columns(4)
    with bench_m1:
        s_color = "#00cf8d" if strategy_final >= 0 else "#ff4b4b"
        st.markdown(f"""<div style="background:#161b22; border:1px solid {s_color}; border-left:5px solid {s_color};
            border-radius:10px; padding:12px; text-align:center;">
            <p style="margin:0; font-size:11px; opacity:0.7;">Profit Strategia Ta</p>
            <h3 style="color:{s_color}; margin:4px 0;">${strategy_final:,.0f}</h3>
            <p style="margin:0; font-size:11px; color:#888;">{strategy_final/bench_capital*100:.1f}% din capital</p>
        </div>""", unsafe_allow_html=True)
    with bench_m2:
        st.markdown(f"""<div style="background:#161b22; border:1px solid #4a9eff; border-left:5px solid #4a9eff;
            border-radius:10px; padding:12px; text-align:center;">
            <p style="margin:0; font-size:11px; opacity:0.7;">Profit SPY Buy&Hold</p>
            <h3 style="color:#4a9eff; margin:4px 0;">${spy_final:,.0f}</h3>
            <p style="margin:0; font-size:11px; color:#888;">{spy_annual_return}%/an × {days_total/365:.1f} ani</p>
        </div>""", unsafe_allow_html=True)
    with bench_m3:
        d_color = "#00cf8d" if diff_vs_spy >= 0 else "#ff4b4b"
        st.markdown(f"""<div style="background:#161b22; border:1px solid {d_color}; border-left:5px solid {d_color};
            border-radius:10px; padding:12px; text-align:center;">
            <p style="margin:0; font-size:11px; opacity:0.7;">Alpha vs SPY</p>
            <h3 style="color:{d_color}; margin:4px 0;">${diff_vs_spy:+,.0f}</h3>
            <p style="margin:0; font-size:11px; color:#888;">{"✅ Bati SPY" if diff_vs_spy >= 0 else "❌ Sub SPY"}</p>
        </div>""", unsafe_allow_html=True)
    with bench_m4:
        st.markdown(f"""<div style="background:#161b22; border:1px solid #30363d; border-left:5px solid #888;
            border-radius:10px; padding:12px; text-align:center;">
            <p style="margin:0; font-size:11px; opacity:0.7;">Return Anual Strategia Ta</p>
            <h3 style="color:#fff; margin:4px 0;">{spy_annual_pnl_pct:.1f}%/an</h3>
            <p style="margin:0; font-size:11px; color:#888;">vs {spy_annual_return}%/an SPY</p>
        </div>""", unsafe_allow_html=True)

    st.write("")
    fig_bench = go.Figure()
    fig_bench.add_trace(go.Scatter(x=df_spy['Date'], y=df_spy['SPY_PnL'], mode='lines',
        name=f'SPY Buy&Hold ({spy_annual_return}%/an)', line=dict(color='#4a9eff', width=2, dash='dot')))
    fig_bench.add_trace(go.Scatter(x=df_bench['Entry Time'], y=df_bench['Cumulative_PnL'], mode='lines',
        name='Strategia Ta', line=dict(color='#00cf8d', width=2.5)))
    fig_bench.add_hline(y=0, line_dash="dash", line_color="#555", opacity=0.5)
    fig_bench.update_layout(title="Equity Curve: Strategia Ta vs SPY Buy & Hold",
        template="plotly_dark", xaxis_title="Data", yaxis_title="Profit ($)",
        height=420, margin=dict(t=50,b=40,l=0,r=0), legend=dict(orientation="h", y=1.02))
    st.plotly_chart(fig_bench, use_container_width=True, key="benchmark_chart")

    if strategy_final > spy_final * 1.5: st.success(f"🏆 **Excelent** — strategia ta generează de **{strategy_final/spy_final:.1f}x** mai mult decât SPY!")
    elif strategy_final > spy_final: st.success(f"✅ **Bine** — strategia ta bate SPY cu **${diff_vs_spy:,.0f}** în plus.")
    elif strategy_final > 0: st.warning(f"🟡 **Sub benchmark** — ești profitabil, dar SPY Buy & Hold ar fi dat mai mult (${spy_final:,.0f} vs ${strategy_final:,.0f}).")
    else: st.error(f"🔴 **Underperformance** — strategia ta este în pierdere în timp ce SPY ar fi dat +${spy_final:,.0f}.")


def render_full_analysis(df, title_prefix, selected_months_list, df_streak=None):
    if df.empty:
        st.warning(f"Nu există date pentru {title_prefix}.")
        return

    total_pnl = df['Net P&L USD'].sum()
    wins_count = len(df[df['Net P&L USD'] > 0])
    losses_count = len(df[df['Net P&L USD'] < 0])
    wr = (wins_count / len(df) * 100) if len(df) > 0 else 0
    pos_profit = df[df['Net P&L USD'] > 0]['Net P&L USD'].sum()
    neg_loss = abs(df[df['Net P&L USD'] < 0]['Net P&L USD'].sum())
    pf = pos_profit / neg_loss if neg_loss > 0 else pos_profit
    avg_win = df[df['Net P&L USD'] > 0]['Net P&L USD'].mean() if wins_count > 0 else 0
    avg_loss = abs(df[df['Net P&L USD'] < 0]['Net P&L USD'].mean()) if losses_count > 0 else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else avg_win

    df_dd = df.sort_values('Entry Time').copy()
    df_dd['Cumulative'] = df_dd['Net P&L USD'].cumsum()
    df_dd['Peak'] = df_dd['Cumulative'].cummax()
    df_dd['Drawdown'] = df_dd['Cumulative'] - df_dd['Peak']
    gen_max_dd = df_dd['Drawdown'].min()

    max_win_streak, max_loss_streak = get_max_streaks(df_streak if df_streak is not None else df)
    best_trade = df['Net P&L USD'].max()
    worst_trade = df['Net P&L USD'].min()

    r1_c1, r1_c2, r1_c3 = st.columns(3)
    with r1_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Profit Net Brut</div><div class='stat-value' style='color:#00cf8d'>${total_pnl:,.2f}</div></div>", unsafe_allow_html=True)
    with r1_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Drawdown (1 Cont)</div><div class='stat-value' style='color:#ff4b4b'>${gen_max_dd:,.2f}</div></div>", unsafe_allow_html=True)
    with r1_c3:
        rr_color = "#00cf8d" if rr_ratio >= 1 else "#ff4b4b"
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Risk / Reward Ratio</div><div class='stat-value' style='color:{rr_color}'>{rr_ratio:.2f}R</div><div class='stat-sub'>Avg Win / Avg Loss</div></div>", unsafe_allow_html=True)
    st.write("")

    r2_c1, r2_c2, r2_c3 = st.columns(3)
    with r2_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Profit Factor</div><div class='stat-value'>{pf:.2f}</div></div>", unsafe_allow_html=True)
    with r2_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Win Rate General</div><div class='stat-value'>{wr:.1f}%</div></div>", unsafe_allow_html=True)
    with r2_c3:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Total Trades</div><div class='stat-value'>{len(df)}</div><div class='stat-sub'>{wins_count}W / {losses_count}L</div></div>", unsafe_allow_html=True)
    st.write("")

    r3_c1, r3_c2, r3_c3 = st.columns(3)
    with r3_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Avg Win</div><div class='stat-value' style='color:#00cf8d'>${avg_win:,.2f}</div></div>", unsafe_allow_html=True)
    with r3_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Avg Loss</div><div class='stat-value' style='color:#ff4b4b'>${avg_loss:,.2f}</div></div>", unsafe_allow_html=True)
    with r3_c3:
        longs = df[df['Direction'] == 'Long']
        shorts = df[df['Direction'] == 'Short']
        l_w = len(longs[longs['Net P&L USD'] > 0]); l_l = len(longs[longs['Net P&L USD'] < 0])
        s_w = len(shorts[shorts['Net P&L USD'] > 0]); s_l = len(shorts[shorts['Net P&L USD'] < 0])
        st.markdown(f"""<div class="stat-card"><div class="stat-label">Trade Direction</div>
            <div style="display: flex; justify-content: space-between; font-size:14px;">
                <span>🔼 <strong>Long:</strong> {len(longs)}</span><span style="color:#aaa;">({l_w}W / {l_l}L)</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size:14px;">
                <span>🔽 <strong>Short:</strong> {len(shorts)}</span><span style="color:#aaa;">({s_w}W / {s_l}L)</span>
            </div></div>""", unsafe_allow_html=True)
    st.write("")

    r4_c1, r4_c2, r4_c3 = st.columns(3)
    with r4_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Win Streak</div><div class='stat-value' style='color:#00cf8d'>{max_win_streak} wins</div></div>", unsafe_allow_html=True)
    with r4_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Loss Streak</div><div class='stat-value' style='color:#ff4b4b'>{max_loss_streak} losses</div></div>", unsafe_allow_html=True)
    with r4_c3:
        st.markdown(f"""<div class="stat-card"><div class="stat-label">Best / Worst Trade</div>
            <div style="display: flex; justify-content: space-between; font-size:14px; margin-top:4px;">
                <span>🏆 Best:</span><span style="color:#00cf8d; font-weight:bold;">${best_trade:,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size:14px; margin-top:4px;">
                <span>💀 Worst:</span><span style="color:#ff4b4b; font-weight:bold;">${worst_trade:,.2f}</span>
            </div></div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader(f"💰 Analiză Cicluri Payout — {title_prefix}")

    col_input1, col_input2 = st.columns(2)
    with col_input1:
        num_acc = st.slider("Număr de conturi funded:", 1, 10, 4, key=f"sl_acc_{title_prefix}")
    with col_input2:
        payout_days = st.select_slider("Ciclu Payout (zile):", options=[7, 14, 15, 21, 30], value=14, key=f"sl_days_{title_prefix}")

    total_pay, cycles, current_bal = simulate_payout_timeline(df, num_acc, payout_days)
    max_dd_global = min([c['Max DD Ciclu'] for c in cycles]) if cycles else 0.0

    col_payout, col_balance = st.columns([1, 1])
    with col_payout:
        st.markdown(f"""
            <div style="height: 260px; padding: 20px; border-radius: 12px; background-color: #1a1c24; border-left: 5px solid #00cf8d; display: flex; flex-direction: column; justify-content: center; align-items: center; box-sizing: border-box; gap: 10px; border: 1px solid #30363d;">
                <div>
                    <p style="margin:0; opacity:0.7; font-size:14px; text-transform: uppercase; text-align: center;">Total Payout ({payout_days} zile)</p>
                    <h1 style="margin:5px 0; color:#00cf8d; font-size:42px; line-height: 1; text-align: center;">${total_pay:,.2f}</h1>
                </div>
                <div style="border-top: 1px solid #333; width: 100%; padding-top: 10px;">
                    <p style="margin:0; opacity:0.7; font-size:12px; text-transform: uppercase; text-align: center; color: #ff4b4b;">Worst Cycle Drawdown</p>
                    <h3 style="margin:0; color:#ff4b4b; font-size:24px; text-align: center;">${max_dd_global:,.2f}</h3>
                </div>
                <p style="margin:0; font-size:13px; opacity:0.5;">{len(cycles) if cycles else 0} cicluri identificate</p>
            </div>""", unsafe_allow_html=True)
    with col_balance:
        with st.container(height=260):
            st.write("**Balanță Curentă Conturi:**")
            for i in range(num_acc):
                val = current_bal[i]
                color = "#00cf8d" if val >= 0 else "#ff4b4b"
                st.markdown(f"<div style='display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid #333;'><span style='font-size:14px;'>Cont {i+1}</span><span style='color:{color}; font-weight:bold;'>${val:,.2f}</span></div>", unsafe_allow_html=True)
    st.markdown("---")

    if cycles:
        df_c = pd.DataFrame(cycles)
        if 'Luna' in df_c.columns:
            df_c['Luna'] = pd.to_datetime(df_c['Luna'])
            df_c = df_c.sort_values('Luna')
        monthly_pay = df_c.groupby('Luna', sort=False)['Payout'].sum().reset_index()
        monthly_pay['Luna_Formatata'] = monthly_pay['Luna'].dt.strftime('%b %Y')
        fig_p = px.bar(monthly_pay, x='Luna_Formatata', y='Payout',
                    title=f"Profit Net pe Luni (Ciclu {payout_days} zile)",
                    text_auto='.2s', template="plotly_dark", color_discrete_sequence=['#00cf8d'])
        fig_p.update_layout(xaxis={'categoryorder':'trace'}, hovermode="x unified", margin=dict(t=50, b=0, l=0, r=0))
        st.plotly_chart(fig_p, use_container_width=True, key=f"payout_bar_{title_prefix}")
        with st.expander("Vezi Timeline Detaliat (Inclusiv Drawdown pe fiecare ciclu)"):
            df_cycles_viz = df_c[['Interval', 'Payout', 'Max DD Ciclu', 'Trades']].iloc[::-1]
            st.dataframe(df_cycles_viz.style.format({'Payout': '${:,.2f}', 'Max DD Ciclu': '${:,.2f}'}), use_container_width=True)
    else:
        st.info(f"Nu există suficiente date pentru a completa un ciclu de {payout_days} zile.")

    render_weekly_calendar(df, title_prefix)

    st.markdown("### 🎲 Analiză Probabilistică")
    df_win_prob, df_loss_prob, active_label = get_streak_probabilities(df)

    def style_streak_row(row):
        if row['Șir curent'] == active_label:
            color = '#00cf8d' if 'Win' in active_label else '#cf0000'
            return [f'background-color: {color}; color: white; font-weight: bold'] * len(row)
        return [''] * len(row)

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        if not df_win_prob.empty: st.table(df_win_prob.style.apply(style_streak_row, axis=1))
        else: st.table(df_win_prob)
    with col_p2:
        if not df_loss_prob.empty: st.table(df_loss_prob.style.apply(style_streak_row, axis=1))
        else: st.table(df_loss_prob)

    st.markdown("---")
    st.subheader("⏰ Analiză pe Ore (INTRARE)")
    hour_stats = df.groupby('Hour').agg(
        Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
        Total_Trades=('Result', 'count'), WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reset_index()
    hour_stats['Time Label'] = hour_stats['Hour'].apply(lambda x: f"{int(x):02d}:00")
    fig_hour = px.bar(hour_stats, x='Time Label', y='Profit',
                    text=hour_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
    fig_hour.update_traces(textposition='outside')
    st.plotly_chart(fig_hour, use_container_width=True, key=f"hour_in_{title_prefix}")

    top_col, bottom_col = st.columns(2)
    with top_col:
        st.markdown("#### 🟢 Top 5 Winning Hours (Intrare)")
        for _, row in hour_stats[hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5).iterrows():
            st.markdown(f"""<div class="top-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
    with bottom_col:
        st.markdown("#### 🔴 Top 5 Losing Hours (Intrare)")
        for _, row in hour_stats[hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5).iterrows():
            st.markdown(f"""<div class="bottom-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("⏱️ Analiză pe Minutele din Oră (INTRARE)")
    if 'Minute' in df.columns:
        min_stats = df.groupby('Minute').agg(
            Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
            Total_Trades=('Result', 'count'), WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
        ).reset_index()
        min_stats['Time Label'] = min_stats['Minute'].apply(lambda x: f"xx:{int(x):02d}")
        fig_min = px.bar(min_stats, x='Time Label', y='Profit',
                        text=min_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                        template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
        fig_min.update_traces(textposition='outside')
        st.plotly_chart(fig_min, use_container_width=True, key=f"min_in_{title_prefix}")

        top_col_m, bottom_col_m = st.columns(2)
        with top_col_m:
            st.markdown("#### 🟢 Top 5 Winning Minutes (Intrare)")
            for _, row in min_stats[min_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5).iterrows():
                st.markdown(f"""<div class="top-box">Minutul <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
        with bottom_col_m:
            st.markdown("#### 🔴 Top 5 Losing Minutes (Intrare)")
            for _, row in min_stats[min_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5).iterrows():
                st.markdown(f"""<div class="bottom-box">Minutul <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🚪 Analiză pe Ore (IEȘIRE)")
    exit_hour_stats = df.dropna(subset=['Exit_Hour']).groupby('Exit_Hour').agg(
        Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
        Total_Trades=('Result', 'count'), WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reset_index()
    exit_hour_stats['Time Label'] = exit_hour_stats['Exit_Hour'].apply(lambda x: f"{int(x):02d}:00")
    fig_exit_hour = px.bar(exit_hour_stats, x='Time Label', y='Profit',
                    text=exit_hour_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
    fig_exit_hour.update_traces(textposition='outside')
    st.plotly_chart(fig_exit_hour, use_container_width=True, key=f"hour_out_{title_prefix}")

    top_col_ex, bottom_col_ex = st.columns(2)
    with top_col_ex:
        st.markdown("#### 🟢 Top 5 Winning Hours (Ieșire)")
        for _, row in exit_hour_stats[exit_hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5).iterrows():
            st.markdown(f"""<div class="top-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
    with bottom_col_ex:
        st.markdown("#### 🔴 Top 5 Losing Hours (Ieșire)")
        for _, row in exit_hour_stats[exit_hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5).iterrows():
            st.markdown(f"""<div class="bottom-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("⏱️ Analiză pe Minutele din Oră (IEȘIRE)")
    if 'Exit_Minute' in df.columns:
        exit_min_stats = df.dropna(subset=['Exit_Minute']).groupby('Exit_Minute').agg(
            Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
            Total_Trades=('Result', 'count'), WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
        ).reset_index()
        exit_min_stats['Time Label'] = exit_min_stats['Exit_Minute'].apply(lambda x: f"xx:{int(x):02d}")
        fig_min_ex = px.bar(exit_min_stats, x='Time Label', y='Profit',
                        text=exit_min_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}%", axis=1),
                        template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
        fig_min_ex.update_traces(textposition='outside')
        st.plotly_chart(fig_min_ex, use_container_width=True, key=f"min_out_{title_prefix}")

        top_col_m_ex, bottom_col_m_ex = st.columns(2)
        with top_col_m_ex:
            st.markdown("#### 🟢 Top 5 Winning Minutes (Ieșire)")
            for _, row in exit_min_stats[exit_min_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5).iterrows():
                st.markdown(f"""<div class="top-box">Minutul <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
        with bottom_col_m_ex:
            st.markdown("#### 🔴 Top 5 Losing Minutes (Ieșire)")
            for _, row in exit_min_stats[exit_min_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5).iterrows():
                st.markdown(f"""<div class="bottom-box">Minutul <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br><small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("⏱️ Analiză Durată Trade-uri")
    if 'Duration_Min' in df.columns:
        df_wins_dur = df[df['Result'] == 'Win']['Duration_Min'].dropna()
        df_loss_dur = df[df['Result'] == 'Loss']['Duration_Min'].dropna()

        def fmt_dur(minutes):
            if pd.isna(minutes) or minutes == 0: return "N/A"
            h = int(minutes // 60); m = int(minutes % 60)
            return f"{h}h {m}m" if h > 0 else f"{m}m"

        dur_c1, dur_c2, dur_c3, dur_c4 = st.columns(4)
        with dur_c1:
            avg_w = df_wins_dur.mean() if not df_wins_dur.empty else 0
            st.markdown(f"<div class='stat-card'><div class='stat-label'>Durată Medie Win</div><div class='stat-value' style='color:#00cf8d'>{fmt_dur(avg_w)}</div></div>", unsafe_allow_html=True)
        with dur_c2:
            avg_l = df_loss_dur.mean() if not df_loss_dur.empty else 0
            st.markdown(f"<div class='stat-card'><div class='stat-label'>Durată Medie Loss</div><div class='stat-value' style='color:#ff4b4b'>{fmt_dur(avg_l)}</div></div>", unsafe_allow_html=True)
        with dur_c3:
            max_dur = df['Duration_Min'].max()
            st.markdown(f"<div class='stat-card'><div class='stat-label'>Trade Cel Mai Lung</div><div class='stat-value'>{fmt_dur(max_dur)}</div></div>", unsafe_allow_html=True)
        with dur_c4:
            min_dur = df['Duration_Min'].min()
            st.markdown(f"<div class='stat-card'><div class='stat-label'>Trade Cel Mai Scurt</div><div class='stat-value'>{fmt_dur(min_dur)}</div></div>", unsafe_allow_html=True)

        st.write("")
        df_dur_plot = df[['Duration_Min', 'Result']].dropna()
        if not df_dur_plot.empty:
            fig_dur = px.histogram(df_dur_plot, x='Duration_Min', color='Result',
                color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'},
                nbins=30, template='plotly_dark',
                labels={'Duration_Min': 'Durată (minute)', 'count': 'Nr. Trades'},
                title='Distribuție Durată Trade-uri (Win vs Loss)')
            st.plotly_chart(fig_dur, use_container_width=True, key=f"dur_hist_{title_prefix}")

    st.markdown("---")
    st.subheader("📊 Performanță pe Zile")
    order_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    day_stats = df.groupby('Day').agg(
        Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
        WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reindex(order_days).dropna(subset=['Profit']).reset_index()
    fig_day = px.bar(day_stats, x='Day', y='Profit',
                    text=day_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
    fig_day.update_traces(textposition='outside')
    st.plotly_chart(fig_day, use_container_width=True, key=f"day_bar_{title_prefix}")

    st.markdown("---")
    st.subheader("📆 Performanță pe Luni")
    month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    month_stats = df.groupby('Month').agg(
        Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
        WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reset_index()
    month_stats['Month'] = pd.Categorical(month_stats['Month'], categories=month_order, ordered=True)
    month_stats = month_stats.sort_values('Month').dropna(subset=['Profit'])
    fig_month = px.bar(month_stats, x='Month', y='Profit',
                    text=month_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
    fig_month.update_traces(textposition='outside')
    st.plotly_chart(fig_month, use_container_width=True, key=f"month_bar_{title_prefix}")

    st.markdown("---")
    st.subheader("📅 Profit pe Ani")
    yearly = df.groupby('Year').agg(
        Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
        WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reset_index()
    fig_yr = px.bar(yearly, x='Year', y='Profit',
                    text=yearly.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='Greens')
    fig_yr.update_traces(textposition='outside')
    st.plotly_chart(fig_yr, use_container_width=True, key=f"year_bar_{title_prefix}")

    st.markdown("---")
    st.subheader("🎯 Analiză pe Signal / Setup")
    if 'Signal' in df.columns:
        df_sig = df.dropna(subset=['Signal'])
        df_sig = df_sig[df_sig['Signal'].astype(str).str.strip() != '']
        if not df_sig.empty:
            signal_stats = df_sig.groupby('Signal').agg(
                Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
                Total=('Result', 'count'), WR=('Result', lambda x: (x == 'Win').sum() / len(x) * 100),
                Avg_Win=('Net P&L USD', lambda x: x[x > 0].mean() if (x > 0).any() else 0),
                Avg_Loss=('Net P&L USD', lambda x: abs(x[x < 0].mean()) if (x < 0).any() else 0),
            ).reset_index()
            signal_stats['RR'] = signal_stats.apply(
                lambda r: r['Avg_Win'] / r['Avg_Loss'] if r['Avg_Loss'] > 0 else r['Avg_Win'], axis=1)
            fig_sig = px.bar(signal_stats, x='Signal', y='Profit',
                text=signal_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                template='plotly_dark', color='Profit', color_continuous_scale='RdYlGn')
            fig_sig.update_traces(textposition='outside')
            st.plotly_chart(fig_sig, use_container_width=True, key=f"signal_bar_{title_prefix}")
            with st.expander("Tabel detaliat pe Signal"):
                display_sig = signal_stats[['Signal', 'Total', 'W', 'L', 'WR', 'Profit', 'Avg_Win', 'Avg_Loss', 'RR']].copy()
                display_sig.columns = ['Signal', 'Total', 'Win', 'Loss', 'Win Rate %', 'Profit', 'Avg Win', 'Avg Loss', 'R:R']
                st.dataframe(display_sig.style.format({'Win Rate %': '{:.1f}%', 'Profit': '${:,.2f}', 'Avg Win': '${:,.2f}', 'Avg Loss': '${:,.2f}', 'R:R': '{:.2f}'}), use_container_width=True)
        else:
            st.info("Nu există date Signal / Setup în acest set de trade-uri.")
    else:
        st.info("Coloana 'Signal' nu a fost găsită în date.")

    st.markdown("---")
    st.subheader("📈 Equity Curve Strategie (Global)")
    df_sorted = df.sort_values('Entry Time').copy()
    df_sorted['Cumulative'] = df_sorted['Net P&L USD'].cumsum()
    st.plotly_chart(px.line(df_sorted, x='Entry Time', y='Cumulative', template="plotly_dark", color_discrete_sequence=['#00cf8d']), use_container_width=True, key=f"equity_{title_prefix}")

    st.markdown("---")
    with st.expander(f"📑 Jurnal Detaliat — {title_prefix}"):
        cols_to_show = ['Entry Time', 'Exit Time', 'Direction', 'Signal', 'Net P&L USD', 'Result', 'Trade #', 'Duration_Min']
        existing_cols = [col for col in cols_to_show if col in df.columns]
        st.dataframe(df[existing_cols].sort_values('Entry Time', ascending=False), use_container_width=True)


# ============================================================
# 4. LOGICĂ DATE + FILTRE + UI PRINCIPAL
# ============================================================
col_left, col_mid, col_right = st.columns([2, 1, 2])
with col_mid:
    #st.image("logo-lvlup.png", use_container_width=True)

    #st.markdown("<h2 style='text-align: center;'>TradingView Strategy</h2>", unsafe_allow_html=True)

uploaded_file = st.file_uploader("Încarcă fișierul .XLSX", type=["xlsx"])

if uploaded_file:
    try:
        df_raw = pd.read_excel(uploaded_file, sheet_name='List of trades', engine='openpyxl')
        df_entries = df_raw[df_raw['Type'].str.contains('Entry', na=False)].copy()
        df_exits = df_raw[df_raw['Type'].str.contains('Exit', na=False)].copy()

        df_entries['Entry Time'] = pd.to_datetime(df_entries['Date and time'])
        df_exits['Exit Time'] = pd.to_datetime(df_exits['Date and time'])

        df_combined = pd.merge(df_exits, df_entries[['Trade #', 'Entry Time', 'Type']], on='Trade #', how='left')
        df_combined = df_combined.drop_duplicates(subset='Trade #', keep='first')
        df_combined['Entry Time'] = df_combined['Entry Time'].fillna(df_combined['Exit Time'])

        def get_direction(val):
            val_str = str(val).lower()
            if 'long' in val_str: return 'Long'
            if 'short' in val_str: return 'Short'
            return 'Other'

        type_col = 'Type_y' if 'Type_y' in df_combined.columns else 'Type'
        df_combined['Direction'] = df_combined[type_col].apply(get_direction)

        if 'Net P&L USD' in df_combined.columns:
            pnl_col = 'Net P&L USD'
        elif 'Profit/Loss USD' in df_combined.columns:
            pnl_col = 'Profit/Loss USD'
        elif 'Profit/Loss' in df_combined.columns:
            pnl_col = 'Profit/Loss'
        else:
            pnl_col = None
            df_combined['Net P&L USD'] = 0
            st.warning("Atenție: Nu am găsit nicio coloană de Profit/Loss!")

        if pnl_col:
            df_combined['Net P&L USD'] = pd.to_numeric(df_combined[pnl_col], errors='coerce').fillna(0)

        df_combined['Result'] = df_combined['Net P&L USD'].apply(lambda x: 'Win' if x > 0 else 'Loss')
        df_combined['Hour'] = df_combined['Entry Time'].dt.hour
        df_combined['Minute'] = df_combined['Entry Time'].dt.minute
        df_combined['Exit_Hour'] = df_combined['Exit Time'].dt.hour
        df_combined['Exit_Minute'] = df_combined['Exit Time'].dt.minute
        df_combined['Duration_Min'] = (df_combined['Exit Time'] - df_combined['Entry Time']).dt.total_seconds() / 60.0
        df_combined['Day'] = df_combined['Entry Time'].dt.day_name()
        df_combined['Month'] = df_combined['Entry Time'].dt.month_name()
        df_combined['Year'] = df_combined['Entry Time'].dt.year

        if 'Signal' not in df_combined.columns:
            df_combined['Signal'] = 'N/A'

        cutoff = datetime.strptime("15:30", "%H:%M").time()
        df_combined['Session'] = df_combined['Entry Time'].apply(
            lambda x: "Sesiunea 1" if x.time() < cutoff else "Sesiunea 2")

        st.markdown("### 🔍 Filtrare Date")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            all_years = sorted(df_combined['Year'].unique())
            selected_years = st.multiselect("Anii:", all_years, default=all_years)
        with c2:
            m_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
            avail_m = [m for m in m_order if m in df_combined['Month'].unique()]
            selected_months = st.multiselect("Lunile:", avail_m, default=avail_m)
        with c3:
            d_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            avail_d = [d for d in d_order if d in df_combined['Day'].unique()]
            selected_days = st.multiselect("Zilele:", avail_d, default=avail_d)
        with c4:
            all_dirs = sorted(df_combined['Direction'].unique())
            selected_dirs = st.multiselect("Direcție (Long/Short):", all_dirs, default=all_dirs)
        with c5:
            all_results = ["Win", "Loss"]
            selected_results = st.multiselect("Rezultat (Win/Loss):", all_results, default=all_results)

        df_final = df_combined[
            (df_combined['Year'].isin(selected_years)) &
            (df_combined['Month'].isin(selected_months)) &
            (df_combined['Day'].isin(selected_days)) &
            (df_combined['Direction'].isin(selected_dirs)) &
            (df_combined['Result'].isin(selected_results))
        ]

        wins_f = len(df_final[df_final['Result'] == 'Win'])
        losses_f = len(df_final[df_final['Result'] == 'Loss'])
        with st.expander(f"📋 Toate Tranzacțiile Filtrate — {len(df_final)} trades ({wins_f}W / {losses_f}L)", expanded=False):
            cols_to_show = ['Entry Time', 'Exit Time', 'Direction', 'Signal', 'Net P&L USD', 'Result', 'Trade #', 'Session', 'Duration_Min']
            existing_cols = [col for col in cols_to_show if col in df_final.columns]
            st.dataframe(df_final[existing_cols].sort_values('Entry Time', ascending=False), use_container_width=True)
            csv_data = df_final[existing_cols].sort_values('Entry Time', ascending=False).to_csv(index=False)
            st.download_button(label="⬇️ Export CSV", data=csv_data, file_name="trades_filtrate.csv", mime="text/csv")

        tab_global, tab_s1, tab_s2, tab_risk, tab_mc, tab_adv = st.tabs([
            "🌍 Global", "🌅 Sesiunea 1", "🌆 Sesiunea 2",
            "💰 Risk Management", "🎲 Monte Carlo", "🔬 Analize Avansate"
        ])
        with tab_global:
            render_full_analysis(df_final, "Global", [])
        with tab_s1:
            render_full_analysis(df_final[df_final['Session'] == "Sesiunea 1"], "Sesiunea 1", [])
        with tab_s2:
            render_full_analysis(df_final[df_final['Session'] == "Sesiunea 2"], "Sesiunea 2", [])
        with tab_risk:
            render_risk_management(df_final)
        with tab_mc:
            render_monte_carlo(df_final)
        with tab_adv:
            render_advanced_analysis(df_final)

        # ── EXPORT PDF COMPLET ──
        st.markdown("---")
        st.markdown("<h3 style='text-align: center;'>📄 Exportă Raportul Complet</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center; color:#8b949e;'>"
            "PDF complet cu statistici, grafice, Risk Management și tabelele detaliate."
            "</p>",
            unsafe_allow_html=True
        )

        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 2])
        with col_btn2:
            if st.button("🔄 Generează PDF Complet", use_container_width=True, type="primary"):
                with st.spinner("Se generează PDF-ul complet cu toate graficele... (~10-20 secunde)"):
                    pdf_data_full = generate_full_pdf_report(df_final)
                st.download_button(
                    label="📥 Descarcă Raport PDF Complet",
                    data=pdf_data_full,
                    file_name="Raport_Trading_Complet.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with col_btn3:
            st.markdown(
                """
                <div style='padding-top: 4px;'>
                    <button onclick='window.print()'
                        style='width:100%; background:#161b22; color:#e6edf3;
                               border:1px solid #30363d; border-radius:8px;
                               padding:10px 0; font-size:14px; cursor:pointer;
                               margin-top: 0px;'>
                        🖨️ Print / Save as PDF din Browser
                    </button>
                </div>
                """,
                unsafe_allow_html=True
            )

    except Exception as e:
        st.error(f"Eroare la citirea sau procesarea datelor: {e}")
        import traceback
        st.code(traceback.format_exc())
