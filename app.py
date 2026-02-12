import streamlit as st
import pandas as pd
import subprocess
import sys

# Instalare automată openpyxl
try:
    import openpyxl
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# 1. CONFIGURARE PAGINĂ
st.set_page_config(page_title="Gold Alpha Master Pro", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: white; }
    .stMetric { background-color: #161b22; border-radius: 10px; padding: 15px; border: 1px solid #30363d; }
    div[data-testid="stExpander"] { background-color: #161b22; border: 1px solid #30363d; }
    </style>
    """, unsafe_allow_html=True)

# --- FUNCȚIE PROBABILITĂȚI ȘIRURI ---
def get_streak_probabilities(df):
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    results = df['Result'].tolist()
    win_streaks, loss_streaks = {}, {}
    curr_streak_len, curr_type = 0, None

    for i in range(len(results) - 1):
        if i == 0:
            curr_streak_len, curr_type = 1, results[i]
        else:
            if results[i] == results[i-1]:
                curr_streak_len += 1
            else:
                curr_streak_len, curr_type = 1, results[i]
        
        next_is_win = 1 if results[i+1] == 'Win' else 0
        target_dict = win_streaks if curr_type == 'Win' else loss_streaks
        if curr_streak_len not in target_dict: target_dict[curr_streak_len] = [0, 0]
        target_dict[curr_streak_len][0] += next_is_win
        target_dict[curr_streak_len][1] += 1

    def format_dict(d, label):
        data = []
        for k in sorted(d.keys()):
            prob = (d[k][0] / d[k][1]) * 100
            data.append({"Șir curent": f"{k} {label}", "Probabilitate Win Următor": f"{prob:.1f}%", "Trades": f"{d[k][1]}"})
        return pd.DataFrame(data)

    return format_dict(win_streaks, "Win"), format_dict(loss_streaks, "Loss")

# 2. FUNCȚIE ANALIZĂ
def render_full_analysis(df, title_prefix, selected_months_list):
    if df.empty:
        st.warning(f"Nu există date pentru {title_prefix} cu filtrele actuale.")
        return

    # Metrici KPI
    total_pnl = df['Net P&L USD'].sum()
    wins_count = len(df[df['Net P&L USD'] > 0])
    losses_count = len(df[df['Net P&L USD'] < 0])
    wr = (wins_count / len(df) * 100) if len(df) > 0 else 0
    pos_profit = df[df['Net P&L USD'] > 0]['Net P&L USD'].sum()
    neg_loss = abs(df[df['Net P&L USD'] < 0]['Net P&L USD'].sum())
    pf = pos_profit / neg_loss if neg_loss > 0 else pos_profit

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Profit Net", f"${total_pnl:,.2f}")
    m2.metric("Profit Factor", f"{pf:.2f}")
    m3.metric("Win Rate", f"{wr:.1f}%")
    m4.metric("Total (W/L)", f"{len(df)} ({wins_count}/{losses_count})")

    # --- TABELE PROBABILITĂȚI ---
    st.markdown("### 🎲 Probabilități după Șiruri")
    df_win_prob, df_loss_prob = get_streak_probabilities(df)
    col_p1, col_p2 = st.columns(2)
    with col_p1: st.table(df_win_prob)
    with col_p2: st.table(df_loss_prob)

    st.markdown("---")

    # --- GRAFICE RÂNDUL 1 ---
    col_eq, col_yr = st.columns(2)
    with col_eq:
        st.subheader("📈 Equity Curve")
        df_sorted = df.sort_values('Date and time')
        df_sorted['Equity'] = df_sorted['Net P&L USD'].cumsum()
        fig_eq = px.line(df_sorted, x='Date and time', y='Equity', template="plotly_dark", color_discrete_sequence=['#008000'])
        st.plotly_chart(fig_eq, use_container_width=True)
    
    with col_yr:
        st.subheader("📅 Profit pe Ani")
        yearly = df.groupby('Year').agg(
            Profit=('Net P&L USD', 'sum'),
            W=('Result', lambda x: (x == 'Win').sum()),
            L=('Result', lambda x: (x == 'Loss').sum()),
            WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
        ).reset_index()
        fig_yr = px.bar(yearly, x='Year', y='Profit', 
                        text=yearly.apply(lambda r: f"${r['Profit']:,.0f}<br>({r['WR']:.0f}% | {int(r['W'])}/{int(r['L'])})", axis=1),
                        template="plotly_dark", color='Profit', color_continuous_scale='Greens')
        fig_yr.update_traces(textposition='outside')
        st.plotly_chart(fig_yr, use_container_width=True)

    # --- GRAFICE RÂNDUL 2 ---
    col_day, col_month = st.columns(2)
    with col_day:
        st.subheader("📊 Profit pe Zile")
        order_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        day_stats = df.groupby('Day').agg(
            Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
            WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
        ).reindex(order_days).dropna(subset=['Profit']).reset_index()
        
        fig_day = px.bar(day_stats, x='Day', y='Profit', 
                         text=day_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>({r['WR']:.0f}% | {int(r['W'])}/{int(r['L'])})", axis=1),
                         template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
        fig_day.update_traces(textposition='outside')
        st.plotly_chart(fig_day, use_container_width=True)

    with col_month:
        st.subheader("📆 Profit pe Luni")
        # Folosim doar lunile selectate în filtru pentru a evita NaN
        order_months = [m for m in ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'] if m in selected_months_list]
        month_stats = df.groupby('Month').agg(
            Profit=('Net P&L USD', 'sum'), W=('Result', lambda x: (x == 'Win').sum()), L=('Result', lambda x: (x == 'Loss').sum()),
            WR=('Result', lambda x: (len(x[x=='Win'])/len(x))*100 if len(x)>0 else 0)
        ).reindex(order_months).dropna(subset=['Profit']).reset_index()
        
        fig_month = px.bar(month_stats, x='Month', y='Profit', 
                           text=month_stats.apply(lambda r: f"${r['Profit']:,.0f}<br>({r['WR']:.0f}% | {int(r['W'])}/{int(r['L'])})", axis=1),
                           template="plotly_dark", color='Profit', color_continuous_scale='RdYlGn')
        fig_month.update_traces(textposition='outside')
        st.plotly_chart(fig_month, use_container_width=True)

# 3. LOGICĂ DATA
st.title("🏆 Gold Alpha: Terminal Analiză")
uploaded_file = st.file_uploader("Încarcă fișierul XLSX", type=["xlsx"])

if uploaded_file:
    try:
        df_raw = pd.read_excel(uploaded_file, sheet_name='List of trades', engine='openpyxl')
        df_exits = df_raw[df_raw['Type'].str.contains('Exit', na=False)].copy()
        df_exits['Date and time'] = pd.to_datetime(df_exits['Date and time'])
        
        def get_session(row_time):
            t = row_time.time()
            pivot = datetime.strptime("15:30", "%H:%M").time()
            return "Sesiunea 1" if t < pivot else "Sesiunea 2"

        df_exits['Session'] = df_exits['Date and time'].apply(get_session)
        df_exits['Year'] = df_exits['Date and time'].dt.year
        df_exits['Month'] = df_exits['Date and time'].dt.month_name()
        df_exits['Day'] = df_exits['Date and time'].dt.day_name()
        df_exits['Result'] = df_exits['Net P&L USD'].apply(lambda x: 'Win' if x > 0 else 'Loss')

        st.markdown("### 🔍 Filtrare Date")
        c1, c2 = st.columns(2)
        with c1:
            all_years = sorted(df_exits['Year'].unique())
            selected_years = st.multiselect("Selectează Anii:", all_years, default=all_years)
        with c2:
            m_order = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
            avail_m = [m for m in m_order if m in df_exits['Month'].unique()]
            selected_months = st.multiselect("Selectează Lunile:", avail_m, default=avail_m)
        
        df_final = df_exits[(df_exits['Year'].isin(selected_years)) & (df_exits['Month'].isin(selected_months))]
        st.markdown("---")

        tab_global, tab_s1, tab_s2 = st.tabs(["🌎 Global", "🌅 Sesiunea 1", "🌆 Sesiunea 2"])
        with tab_global: render_full_analysis(df_final, "Global", selected_months)
        with tab_s1: render_full_analysis(df_final[df_final['Session'] == "Sesiunea 1"], "Sesiunea 1", selected_months)
        with tab_s2: render_full_analysis(df_final[df_final['Session'] == "Sesiunea 2"], "Sesiunea 2", selected_months)

    except Exception as e:
        st.error(f"Eroare: {e}")