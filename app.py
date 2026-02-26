import streamlit as st
import pandas as pd
import subprocess
import sys
from datetime import timedelta, datetime

# 1. ASIGURARE DEPENDENȚE
try:
    import openpyxl
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

import plotly.express as px
import plotly.graph_objects as go

# 2. CONFIGURARE PAGINĂ ȘI DESIGN
st.set_page_config(page_title="TradingView Payout & Strategy", layout="wide")

st.markdown("""
    <style>
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
    </style>
    """, unsafe_allow_html=True)


# --- FUNCȚIE CALCUL PROBABILITĂȚI ȘIRURI ---
def get_streak_probabilities(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    results = df['Result'].tolist()
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
    def format_dict(d, label):
        data = []
        for k in sorted(d.keys()):
            prob = (d[k][0] / d[k][1]) * 100
            data.append({"Șir curent": f"{k} {label}", "Probabilitate Win Următor": f"{prob:.1f}%", "Eșantion": f"{d[k][1]} ori"})
        return pd.DataFrame(data)
    return format_dict(win_streaks, "Win"), format_dict(loss_streaks, "Loss")


# --- FUNCȚIE CALCUL MAX STREAK ---
def get_max_streaks(df):
    if df.empty: return 0, 0
    results = df.sort_values('Entry Time')['Result'].tolist()
    max_win, max_loss = 0, 0
    curr_win, curr_loss = 0, 0
    for r in results:
        if r == 'Win':
            curr_win += 1
            curr_loss = 0
            max_win = max(max_win, curr_win)
        else:
            curr_loss += 1
            curr_win = 0
            max_loss = max(max_loss, curr_loss)
    return max_win, max_loss


# --- FUNCȚIE SIMULARE FUNDED + TIMELINE PAYOUT ---
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


# --- FUNCȚIE RENDER CALENDAR SĂPTĂMÂNAL ---
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

                st.markdown(f"""
                    <div class="day-card {css_class}">
                        <div style="font-size:18px; font-weight:bold;">{pnl_fmt}</div>
                        <div style="font-size:12px;">{cnt} trades</div>
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                    <div class="day-card day-neutral">
                        <div style="font-size:18px;">-</div>
                        <div style="font-size:12px;">No activity</div>
                    </div>
                """, unsafe_allow_html=True)
    st.markdown("---")


# --- FUNCȚIE RENDER ANALIZĂ COMPLETĂ ---
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

    # RÂNDUL 1: Profit, PF, Win Rate
    r1_c1, r1_c2, r1_c3 = st.columns(3)
    with r1_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Profit Net Brut</div><div class='stat-value' style='color:#00cf8d'>${total_pnl:,.2f}</div></div>", unsafe_allow_html=True)
    with r1_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Profit Factor</div><div class='stat-value'>{pf:.2f}</div></div>", unsafe_allow_html=True)
    with r1_c3:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Win Rate General</div><div class='stat-value'>{wr:.1f}%</div></div>", unsafe_allow_html=True)

    st.write("")

    # RÂNDUL 2: Max DD, Total Trades, Trade Direction
    r2_c1, r2_c2, r2_c3 = st.columns(3)
    with r2_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Drawdown (1 Cont)</div><div class='stat-value' style='color:#ff4b4b'>${gen_max_dd:,.2f}</div></div>", unsafe_allow_html=True)
    with r2_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Total Trades</div><div class='stat-value'>{len(df)}</div><div class='stat-sub'>{wins_count}W / {losses_count}L</div></div>", unsafe_allow_html=True)
    with r2_c3:
        longs = df[df['Direction'] == 'Long']
        shorts = df[df['Direction'] == 'Short']
        l_w = len(longs[longs['Net P&L USD'] > 0])
        l_l = len(longs[longs['Net P&L USD'] < 0])
        s_w = len(shorts[shorts['Net P&L USD'] > 0])
        s_l = len(shorts[shorts['Net P&L USD'] < 0])
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Trade Direction</div>
            <div style="display: flex; justify-content: space-between; font-size:14px;">
                <span>🔼 <strong>Long:</strong> {len(longs)}</span>
                <span style="color:#aaa;">({l_w}W / {l_l}L)</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size:14px;">
                <span>🔽 <strong>Short:</strong> {len(shorts)}</span>
                <span style="color:#aaa;">({s_w}W / {s_l}L)</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")

    # RÂNDUL 3: Avg Win, Avg Loss, R:R Ratio
    r3_c1, r3_c2, r3_c3 = st.columns(3)
    with r3_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Avg Win</div><div class='stat-value' style='color:#00cf8d'>${avg_win:,.2f}</div></div>", unsafe_allow_html=True)
    with r3_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Avg Loss</div><div class='stat-value' style='color:#ff4b4b'>${avg_loss:,.2f}</div></div>", unsafe_allow_html=True)
    with r3_c3:
        rr_color = "#00cf8d" if rr_ratio >= 1 else "#ff4b4b"
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Risk / Reward Ratio</div><div class='stat-value' style='color:{rr_color}'>{rr_ratio:.2f}R</div><div class='stat-sub'>Avg Win / Avg Loss</div></div>", unsafe_allow_html=True)

    st.write("")

    # RÂNDUL 4: Max Win Streak, Max Loss Streak, Best/Worst Trade
    r4_c1, r4_c2, r4_c3 = st.columns(3)
    with r4_c1:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Win Streak</div><div class='stat-value' style='color:#00cf8d'>{max_win_streak} wins</div></div>", unsafe_allow_html=True)
    with r4_c2:
        st.markdown(f"<div class='stat-card'><div class='stat-label'>Max Loss Streak</div><div class='stat-value' style='color:#ff4b4b'>{max_loss_streak} losses</div></div>", unsafe_allow_html=True)
    with r4_c3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">Best / Worst Trade</div>
            <div style="display: flex; justify-content: space-between; font-size:14px; margin-top:4px;">
                <span>🏆 Best:</span><span style="color:#00cf8d; font-weight:bold;">${best_trade:,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size:14px; margin-top:4px;">
                <span>💀 Worst:</span><span style="color:#ff4b4b; font-weight:bold;">${worst_trade:,.2f}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

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
            </div>
        """, unsafe_allow_html=True)

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
                    text_auto='.2s',
                    template="plotly_dark",
                    color_discrete_sequence=['#00cf8d'])
        fig_p.update_layout(xaxis={'categoryorder':'trace'}, hovermode="x unified", margin=dict(t=50, b=0, l=0, r=0))
        st.plotly_chart(fig_p, use_container_width=True)
        with st.expander("Vezi Timeline Detaliat (Inclusiv Drawdown pe fiecare ciclu)"):
            df_cycles_viz = df_c[['Interval', 'Payout', 'Max DD Ciclu', 'Trades']].iloc[::-1]
            st.dataframe(df_cycles_viz.style.format({'Payout': '${:,.2f}', 'Max DD Ciclu': '${:,.2f}'}), use_container_width=True)
    else:
        st.info(f"Nu există suficiente date pentru a completa un ciclu de {payout_days} zile.")

    render_weekly_calendar(df, title_prefix)

    st.markdown("### 🎲 Analiză Probabilistică")
    df_win_prob, df_loss_prob = get_streak_probabilities(df)
    col_p1, col_p2 = st.columns(2)
    with col_p1: st.table(df_win_prob)
    with col_p2: st.table(df_loss_prob)

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
    st.plotly_chart(fig_hour, use_container_width=True)

    top_col, bottom_col = st.columns(2)
    with top_col:
        st.markdown("#### 🟢 Top 5 Winning Hours (Intrare)")
        top_5_wr = hour_stats[hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5)
        for _, row in top_5_wr.iterrows():
            st.markdown(f"""<div class="top-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br>
                        <small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
    with bottom_col:
        st.markdown("#### 🔴 Top 5 Losing Hours (Intrare)")
        bottom_5_wr = hour_stats[hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5)
        for _, row in bottom_5_wr.iterrows():
            st.markdown(f"""<div class="bottom-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br>
                        <small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

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
    st.plotly_chart(fig_exit_hour, use_container_width=True)

    top_col_ex, bottom_col_ex = st.columns(2)
    with top_col_ex:
        st.markdown("#### 🟢 Top 5 Winning Hours (Ieșire)")
        top_5_wr_ex = exit_hour_stats[exit_hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=False).head(5)
        for _, row in top_5_wr_ex.iterrows():
            st.markdown(f"""<div class="top-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br>
                        <small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)
    with bottom_col_ex:
        st.markdown("#### 🔴 Top 5 Losing Hours (Ieșire)")
        bottom_5_wr_ex = exit_hour_stats[exit_hour_stats['Total_Trades'] > 0].sort_values(by=['WR', 'Profit'], ascending=True).head(5)
        for _, row in bottom_5_wr_ex.iterrows():
            st.markdown(f"""<div class="bottom-box">Ora <b>{row['Time Label']}</b> — Win Rate: <b>{row['WR']:.1f}%</b> <br>
                        <small>Profit: ${row['Profit']:,.2f} | Scor: {int(row['W'])}W - {int(row['L'])}L</small></div>""", unsafe_allow_html=True)

    # --- DURATĂ TRADE-URI ---
    st.markdown("---")
    st.subheader("⏱️ Analiză Durată Trade-uri")
    if 'Duration_Min' in df.columns:
        df_wins_dur = df[df['Result'] == 'Win']['Duration_Min'].dropna()
        df_loss_dur = df[df['Result'] == 'Loss']['Duration_Min'].dropna()

        def fmt_dur(minutes):
            if pd.isna(minutes) or minutes == 0: return "N/A"
            h = int(minutes // 60)
            m = int(minutes % 60)
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
            fig_dur = px.histogram(
                df_dur_plot, x='Duration_Min', color='Result',
                color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'},
                nbins=30, template='plotly_dark',
                labels={'Duration_Min': 'Durată (minute)', 'count': 'Nr. Trades'},
                title='Distribuție Durată Trade-uri (Win vs Loss)'
            )

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
    st.plotly_chart(fig_day, use_container_width=True)

    st.markdown("---")
    st.subheader("📆 Performanță pe Luni")
    month_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    month_stats = df.groupby('Month').agg(
        Profit=('Net P&L USD', 'sum'),
        W=('Result', lambda x: (x == 'Win').sum()),
        L=('Result', lambda x: (x == 'Loss').sum()),
        WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
    ).reset_index()
    month_stats['Month'] = pd.Categorical(month_stats['Month'], categories=month_order, ordered=True)
    month_stats = month_stats.sort_values('Month').dropna(subset=['Profit'])
    fig_month = px.bar(month_stats, x='Month', y='Profit',
                    text=month_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                    template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
    fig_month.update_traces(textposition='outside')
    st.plotly_chart(fig_month, use_container_width=True)

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
    st.plotly_chart(fig_yr, use_container_width=True)


    # --- ANALIZĂ PE SIGNAL ---
    st.markdown("---")
    st.subheader("🎯 Analiză pe Signal / Setup")
    if 'Signal' in df.columns:
        df_sig = df.dropna(subset=['Signal'])
        df_sig = df_sig[df_sig['Signal'].astype(str).str.strip() != '']
        if not df_sig.empty:
            signal_stats = df_sig.groupby('Signal').agg(
                Profit=('Net P&L USD', 'sum'),
                W=('Result', lambda x: (x == 'Win').sum()),
                L=('Result', lambda x: (x == 'Loss').sum()),
                Total=('Result', 'count'),
                WR=('Result', lambda x: (x == 'Win').sum() / len(x) * 100),
                Avg_Win=('Net P&L USD', lambda x: x[x > 0].mean() if (x > 0).any() else 0),
                Avg_Loss=('Net P&L USD', lambda x: abs(x[x < 0].mean()) if (x < 0).any() else 0),
            ).reset_index()
            signal_stats['RR'] = signal_stats.apply(
                lambda r: r['Avg_Win'] / r['Avg_Loss'] if r['Avg_Loss'] > 0 else r['Avg_Win'], axis=1
            )
            fig_sig = px.bar(
                signal_stats, x='Signal', y='Profit',
                text=signal_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>{r['WR']:.0f}% ({int(r['W'])}W/{int(r['L'])}L)", axis=1),
                template='plotly_dark', color='Profit', color_continuous_scale='RdYlGn'
            )
            fig_sig.update_traces(textposition='outside')
            st.plotly_chart(fig_sig, use_container_width=True)

            with st.expander("Tabel detaliat pe Signal"):
                display_sig = signal_stats[['Signal', 'Total', 'W', 'L', 'WR', 'Profit', 'Avg_Win', 'Avg_Loss', 'RR']].copy()
                display_sig.columns = ['Signal', 'Total', 'Win', 'Loss', 'Win Rate %', 'Profit', 'Avg Win', 'Avg Loss', 'R:R']
                st.dataframe(display_sig.style.format({
                    'Win Rate %': '{:.1f}%', 'Profit': '${:,.2f}',
                    'Avg Win': '${:,.2f}', 'Avg Loss': '${:,.2f}', 'R:R': '{:.2f}'
                }), use_container_width=True)
        else:
            st.info("Nu există date Signal / Setup în acest set de trade-uri.")
    else:
        st.info("Coloana 'Signal' nu a fost găsită în date.")

    st.markdown("---")
    st.subheader("📈 Equity Curve Strategie (Global)")
    df_sorted = df.sort_values('Entry Time')
    df_sorted['Cumulative'] = df_sorted['Net P&L USD'].cumsum()
    st.plotly_chart(px.line(df_sorted, x='Entry Time', y='Cumulative', template="plotly_dark", color_discrete_sequence=['#00cf8d']), use_container_width=True)

    st.markdown("---")
    with st.expander(f"📑 Jurnal Detaliat — {title_prefix}"):
        cols_to_show = ['Entry Time', 'Exit Time', 'Direction', 'Signal', 'Net P&L USD', 'Result', 'Trade #', 'Duration_Min']
        existing_cols = [col for col in cols_to_show if col in df.columns]
        st.dataframe(df[existing_cols].sort_values('Entry Time', ascending=False), use_container_width=True)


# 4. LOGICĂ DATE + FILTRE
st.title("🏆 TradingView Payout & Strategy")
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

        df_combined['Direction'] = df_combined['Type_y'].apply(get_direction)
        df_combined['Hour'] = df_combined['Entry Time'].dt.hour
        df_combined['Exit_Hour'] = df_combined['Exit Time'].dt.hour
        df_combined['Year'] = df_combined['Entry Time'].dt.year
        df_combined['Month'] = df_combined['Entry Time'].dt.month_name()
        df_combined['Day'] = df_combined['Entry Time'].dt.day_name()
        df_combined['Result'] = df_combined['Net P&L USD'].apply(lambda x: 'Win' if x > 0 else 'Loss')
        df_combined['Duration_Min'] = (df_combined['Exit Time'] - df_combined['Entry Time']).dt.total_seconds() / 60

        def get_session(row_time):
            pivot = datetime.strptime("15:30", "%H:%M").time()
            return "Sesiunea 1" if row_time.time() < pivot else "Sesiunea 2"
        df_combined['Session'] = df_combined['Entry Time'].apply(get_session)

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
            st.download_button(
                label="⬇️ Export CSV",
                data=csv_data,
                file_name="trades_filtrate.csv",
                mime="text/csv"
            )

        tab_global, tab_s1, tab_s2 = st.tabs(["🌍 Global", "🌅 Sesiunea 1", "🌆 Sesiunea 2"])
        with tab_global: render_full_analysis(df_final, "Global", [])
        with tab_s1: render_full_analysis(df_final[df_final['Session'] == "Sesiunea 1"], "Sesiunea 1", [])
        with tab_s2: render_full_analysis(df_final[df_final['Session'] == "Sesiunea 2"], "Sesiunea 2", [])

    except Exception as e:
        st.error(f"Eroare: {e}")
