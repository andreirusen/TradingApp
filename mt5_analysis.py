"""
mt5_analysis.py — Analiză dedicată pentru rapoartele MetaTrader 5
================================================================
Suportă:
  • Strategy Tester Report exportat din MT5 (.xlsx)  → "Strategy Tester Report"
  • Trade History Report din cont (.xlsx)            → secțiunea "Deals"

Parsează:
  • Setările (Expert, Symbol, Period, Inputs, Deposit, Leverage)
  • Statisticile oficiale MT5 (Profit Factor, Sharpe, Recovery Factor, DD etc.)
  • Tabelul Orders  → statistici de execuție a ordinelor pending (filled / expired / canceled)
  • Tabelul Deals   → reconstruiește fiecare trade (in → out, FIFO) cu P&L net
                      (profit + comision + swap), setup (comentariul de intrare),
                      motiv de ieșire (TP / SL / altele) și balanța contului.

Trade-urile sunt normalizate în ACELAȘI format ca df_final din app.py
(Entry Time, Exit Time, Direction, Net P&L USD, Result, Signal ...),
deci toate analizele existente (Global, Risk, Monte Carlo, Avansate, PDF) merg direct.
"""

import io
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
             'August', 'September', 'October', 'November', 'December']
MONTHS_RO_SHORT = ['Ian', 'Feb', 'Mar', 'Apr', 'Mai', 'Iun', 'Iul', 'Aug', 'Sep', 'Oct', 'Noi', 'Dec']
DAYS_EN = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
SECTION_NAMES = {'Orders', 'Deals', 'Positions', 'Results', 'Settings', 'Working Orders'}
MT5_TIME_FMT = '%Y.%m.%d %H:%M:%S'


# ══════════════════════════════════════════════════════════════
# HELPERE PARSARE
# ══════════════════════════════════════════════════════════════
def _is_empty(x):
    return x is None or (isinstance(x, float) and np.isnan(x)) or (isinstance(x, str) and x.strip() == '')


def _num(x):
    """'7 000.48 (5.66%)' → 7000.48 ; '274 (71.53%)' → 274 ; 1.23 → 1.23"""
    if _is_empty(x):
        return None
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).replace('\xa0', ' ').strip()
    m = re.match(r'^(-?\d[\d ]*(?:[.,]\d+)?)', s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def _paren(x):
    """'7 000.48 (5.66%)' → 5.66 ; '17 (6 805.13)' → 6805.13"""
    if _is_empty(x):
        return None
    m = re.search(r'\(([^)]*)\)', str(x))
    return _num(m.group(1).replace('%', '')) if m else None


def _to_time(series):
    t = pd.to_datetime(series, format=MT5_TIME_FMT, errors='coerce')
    if t.isna().all():
        t = pd.to_datetime(series, errors='coerce')
    return t


def _find_row(raw, label):
    hits = raw.index[raw[0].astype(str).str.strip() == label].tolist()
    return hits[0] if hits else None


def _section_table(raw, name):
    """Citește un tabel MT5 (Orders / Deals / Positions) pe baza rândului de header."""
    idx = _find_row(raw, name)
    if idx is None or idx + 1 >= len(raw):
        return pd.DataFrame()
    header = raw.iloc[idx + 1]
    col_map, seen = {}, {}
    for pos, h in header.items():
        if _is_empty(h):
            continue
        h = str(h).strip()
        seen[h] = seen.get(h, 0) + 1
        col_map[pos] = h if seen[h] == 1 else f"{h} {seen[h]}"   # 'Time', 'Time 2' ...
    rows = []
    for i in range(idx + 2, len(raw)):
        first = raw.iat[i, 0]
        if _is_empty(first) or str(first).strip() in SECTION_NAMES:
            break
        rows.append(raw.iloc[i])
    if not rows:
        return pd.DataFrame(columns=list(col_map.values()))
    df = pd.DataFrame(rows)[list(col_map.keys())].rename(columns=col_map).reset_index(drop=True)
    return df


def is_mt5_report(file_bytes):
    """True dacă fișierul pare un raport MT5 (Tester sau History)."""
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine='openpyxl', nrows=4000)
    except Exception:
        return False
    col0 = raw[0].astype(str).str.strip()
    return ('Deals' in col0.values) and (
        col0.str.contains('Strategy Tester Report|Trade History Report', regex=True).any()
        or 'Orders' in col0.values)


# ══════════════════════════════════════════════════════════════
# PARSARE RAPORT
# ══════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def parse_mt5_report(file_bytes):
    raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine='openpyxl')
    raw = raw.reset_index(drop=True)
    raw.columns = range(raw.shape[1])

    report_type = str(raw.iat[0, 0]).strip() if len(raw) else 'MT5 Report'
    server = str(raw.iat[1, 0]).strip() if len(raw) > 1 and not _is_empty(raw.iat[1, 0]) else ''

    first_table = min([r for r in (_find_row(raw, 'Orders'), _find_row(raw, 'Deals'),
                                   _find_row(raw, 'Positions')) if r is not None] or [len(raw)])

    # ── Setări + statistici: perechi "Etichetă:" → următoarea valoare nenulă ──
    stats, inputs = {}, []
    in_inputs = False
    for i in range(first_table):
        row = raw.iloc[i].tolist()
        label0 = row[0]
        if not _is_empty(label0) and str(label0).strip() != 'Inputs:':
            in_inputs = False
        if not _is_empty(label0) and str(label0).strip() == 'Inputs:':
            in_inputs = True
        if in_inputs:
            for c in row[1:]:
                if not _is_empty(c) and '=' in str(c):
                    inputs.append(str(c).strip())
                    break
            continue
        j = 0
        while j < len(row):
            c = row[j]
            if isinstance(c, str) and c.strip().endswith(':'):
                val = None
                for k in range(j + 1, len(row)):
                    nxt = row[k]
                    if _is_empty(nxt):
                        continue
                    if isinstance(nxt, str) and nxt.strip().endswith(':'):
                        break
                    val = nxt
                    break
                stats[c.strip().rstrip(':').strip()] = val
            j += 1

    orders = _section_table(raw, 'Orders')
    deals = _section_table(raw, 'Deals')
    if deals.empty:
        raise ValueError("Nu am găsit secțiunea 'Deals' în raport. Exportă raportul complet din MT5 (Strategy Tester → Backtest → click dreapta → Report → Open XML/Excel).")

    deals['Time'] = _to_time(deals['Time'])
    for c in ['Volume', 'Price', 'Commission', 'Fee', 'Swap', 'Profit', 'Balance']:
        if c in deals.columns:
            deals[c] = pd.to_numeric(deals[c].apply(_num), errors='coerce').fillna(0.0)
    for c in ['Commission', 'Fee', 'Swap']:
        if c not in deals.columns:
            deals[c] = 0.0

    if not orders.empty:
        for tc in [c for c in orders.columns if c.startswith('Time') or c == 'Open Time']:
            orders[tc] = _to_time(orders[tc])

    trades = _build_trades(deals)

    # Depozit inițial
    bal_deals = deals[deals['Type'].astype(str).str.lower().str.strip() == 'balance']
    deposit = _num(stats.get('Initial Deposit'))
    if deposit is None:
        deposit = float(bal_deals['Profit'].iloc[0]) if not bal_deals.empty else 0.0

    # Inputs → dicționar
    inputs_dict = {}
    for s in inputs:
        k, _, v = s.partition('=')
        if v != '' and not k.startswith('═'):
            inputs_dict[k.strip()] = v.strip()

    return {
        'report_type': report_type, 'server': server, 'stats': stats,
        'inputs': inputs, 'inputs_dict': inputs_dict, 'orders': orders, 'deals': deals,
        'trades': trades, 'deposit': float(deposit or 0.0),
    }


def _exit_reason(comment):
    c = str(comment).strip().lower() if not _is_empty(comment) else ''
    if c.startswith('tp'):
        return 'Take Profit'
    if c.startswith('sl'):
        return 'Stop Loss'
    if c.startswith('so'):
        return 'Stop Out'
    if c == '':
        return 'Închidere EA / Timp'
    return 'Altele'


def _build_trades(deals):
    """Reconstruiește trade-urile din Deals (in → out), FIFO pe simbol.
    Fiecare deal 'out' = 1 trade (exact cum numără MT5 'Total Trades')."""
    open_pos = {}
    trades = []
    for r in deals.itertuples(index=False):
        d = r._asdict()
        typ = str(d.get('Type', '')).strip().lower()
        direc = str(d.get('Direction', '')).strip().lower()
        if typ not in ('buy', 'sell'):
            continue
        sym = str(d.get('Symbol', ''))
        vol = float(d.get('Volume') or 0)
        costs = float(d.get('Commission') or 0) + float(d.get('Fee') or 0)
        swap = float(d.get('Swap') or 0)
        profit = float(d.get('Profit') or 0)
        comment = d.get('Comment')
        lst = open_pos.setdefault(sym, [])

        def _open(volume, comm_alloc):
            lst.append({'time': d['Time'], 'side': 'Long' if typ == 'buy' else 'Short',
                        'vol': volume, 'rem': volume, 'price': float(d.get('Price') or 0),
                        'comment': comment, 'comm': comm_alloc})

        if direc == 'in':
            _open(vol, costs)
            continue

        if direc in ('out', 'out by', 'in/out', 'inout'):
            closing_side = 'Short' if typ == 'buy' else 'Long'
            to_close = vol
            consumed, entry_comm = [], 0.0
            for p in lst:
                if to_close <= 1e-9:
                    break
                if p['side'] != closing_side or p['rem'] <= 1e-9:
                    continue
                take = min(p['rem'], to_close)
                consumed.append((p, take))
                entry_comm += p['comm'] * (take / p['vol']) if p['vol'] else 0
                p['rem'] -= take
                to_close -= take
            lst[:] = [p for p in lst if p['rem'] > 1e-9]
            closed_vol = vol - to_close
            if consumed:
                w = sum(t for _, t in consumed)
                entry_price = sum(p['price'] * t for p, t in consumed) / w
                first = consumed[0][0]
                exit_price = float(d.get('Price') or 0)
                net = profit + costs + swap + entry_comm
                pts = (exit_price - entry_price) * (1 if closing_side == 'Long' else -1)
                trades.append({
                    'Entry Time': first['time'], 'Exit Time': d['Time'],
                    'Direction': closing_side, 'Symbol': sym, 'Volume': closed_vol,
                    'Entry Price': entry_price, 'Exit Price': exit_price, 'Points': pts,
                    'Signal': str(first['comment']).strip() if not _is_empty(first['comment']) else 'N/A',
                    'Exit Comment': '' if _is_empty(comment) else str(comment),
                    'Exit Reason': _exit_reason(comment),
                    'Gross Profit': profit, 'Commission': costs + entry_comm, 'Swap': swap,
                    'Net P&L USD': net, 'Balance After': float(d.get('Balance') or 0),
                })
            if direc in ('in/out', 'inout') and to_close > 1e-9:
                _open(to_close, 0.0)

    df = pd.DataFrame(trades)
    if df.empty:
        return df
    df = df.sort_values('Exit Time').reset_index(drop=True)
    df['Trade #'] = np.arange(1, len(df) + 1)
    df['Balance Before'] = df['Balance After'] - df['Net P&L USD']
    df['Return %'] = np.where(df['Balance Before'] > 0, df['Net P&L USD'] / df['Balance Before'] * 100, np.nan)
    return _normalize(df)


def _normalize(df):
    """Adaugă coloanele pe care le folosesc funcțiile existente din app.py."""
    df['Result'] = np.where(df['Net P&L USD'] > 0, 'Win', 'Loss')
    df['Hour'] = df['Entry Time'].dt.hour
    df['Minute'] = df['Entry Time'].dt.minute
    df['Exit_Hour'] = df['Exit Time'].dt.hour
    df['Exit_Minute'] = df['Exit Time'].dt.minute
    df['Duration_Min'] = (df['Exit Time'] - df['Entry Time']).dt.total_seconds() / 60.0
    df['Day'] = df['Entry Time'].dt.day_name()
    df['Month'] = df['Entry Time'].dt.month_name()
    df['Year'] = df['Entry Time'].dt.year
    cutoff = datetime.strptime("15:30", "%H:%M").time()
    df['Session'] = df['Entry Time'].apply(lambda x: "Sesiunea 1" if x.time() < cutoff else "Sesiunea 2")
    return df


# ══════════════════════════════════════════════════════════════
# UI HELPERE
# ══════════════════════════════════════════════════════════════
def _card(label, value, color='#e6edf3', sub=''):
    sub_html = f"<div class='stat-sub'>{sub}</div>" if sub else ''
    st.markdown(f"<div class='stat-card'><div class='stat-label'>{label}</div>"
                f"<div class='stat-value' style='color:{color}'>{value}</div>{sub_html}</div>",
                unsafe_allow_html=True)


def _cards_row(items):
    cols = st.columns(len(items))
    for col, it in zip(cols, items):
        with col:
            _card(*it)
    st.write("")


def _fmt_money(v):
    return '—' if v is None else f"${v:,.2f}"


def _dark(fig, h=380):
    fig.update_layout(template='plotly_dark', height=h, margin=dict(t=50, b=40, l=0, r=0),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig


def _group_stats(df, by):
    g = df.groupby(by).agg(
        Trades=('Net P&L USD', 'count'),
        W=('Result', lambda s: (s == 'Win').sum()),
        Profit=('Net P&L USD', 'sum'),
        Avg=('Net P&L USD', 'mean'),
        GW=('Net P&L USD', lambda s: s[s > 0].sum()),
        GL=('Net P&L USD', lambda s: -s[s < 0].sum()),
        AvgDur=('Duration_Min', 'mean'),
    ).reset_index()
    g['L'] = g['Trades'] - g['W']
    g['WR %'] = g['W'] / g['Trades'] * 100
    g['PF'] = np.where(g['GL'] > 0, g['GW'] / g['GL'].replace(0, np.nan), np.nan)
    return g


# ══════════════════════════════════════════════════════════════
# TAB 1 — RAPORTUL OFICIAL MT5
# ══════════════════════════════════════════════════════════════
def render_mt5_official(rep, trades_all):
    s = rep['stats']
    st.markdown("## 📋 Raport Oficial MetaTrader 5")
    st.caption("Valorile de mai jos sunt cele calculate de MT5, pe TOT raportul (filtrele nu se aplică aici).")

    meta = [("Expert", s.get('Expert')), ("Simbol", s.get('Symbol')), ("Perioadă", s.get('Period')),
            ("Broker", s.get('Company')), ("Depozit", s.get('Initial Deposit')),
            ("Levier", s.get('Leverage')), ("Calitate istoric", s.get('History Quality'))]
    meta_html = " &nbsp;•&nbsp; ".join(f"<b>{k}:</b> {v}" for k, v in meta if not _is_empty(v))
    st.markdown(f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;"
                f"font-size:14px;'>🤖 {meta_html}<br><span style='color:#8b949e'>{rep['server']}</span></div>",
                unsafe_allow_html=True)
    st.write("")

    net = _num(s.get('Total Net Profit'))
    dep = rep['deposit'] or None
    pf = _num(s.get('Profit Factor'))
    eq_dd = s.get('Equity Drawdown Maximal')
    bal_dd = s.get('Balance Drawdown Maximal')
    _cards_row([
        ("Total Net Profit", _fmt_money(net), '#00cf8d' if (net or 0) >= 0 else '#ff4b4b',
         f"{net / dep * 100:+.2f}% din depozit" if net is not None and dep else ''),
        ("Profit Factor", f"{pf:.2f}" if pf else '—', '#00cf8d' if (pf or 0) >= 1 else '#ff4b4b',
         f"Gross: {_fmt_money(_num(s.get('Gross Profit')))} / {_fmt_money(_num(s.get('Gross Loss')))}"),
        ("Equity DD Maximal", _fmt_money(_num(eq_dd)), '#ff4b4b',
         f"{_paren(eq_dd):.2f}% din peak" if _paren(eq_dd) is not None else ''),
        ("Balance DD Maximal", _fmt_money(_num(bal_dd)), '#ff4b4b',
         f"{_paren(bal_dd):.2f}% din peak" if _paren(bal_dd) is not None else ''),
    ])
    rf, sh, ep = _num(s.get('Recovery Factor')), _num(s.get('Sharpe Ratio')), _num(s.get('Expected Payoff'))
    lr = _num(s.get('LR Correlation'))
    _cards_row([
        ("Recovery Factor", f"{rf:.2f}" if rf is not None else '—', '#58a6ff', "Net Profit / Max DD"),
        ("Sharpe Ratio", f"{sh:.2f}" if sh is not None else '—', '#58a6ff', "calculat de MT5"),
        ("Expected Payoff", _fmt_money(ep), '#00cf8d' if (ep or 0) >= 0 else '#ff4b4b', "profit mediu / trade"),
        ("LR Correlation", f"{lr:.3f}" if lr is not None else '—', '#58a6ff',
         "liniaritate curbă (1 = perfectă)"),
    ])

    tt = _num(s.get('Total Trades'))
    pt, lt = s.get('Profit Trades (% of total)'), s.get('Loss Trades (% of total)')
    st_, lg = s.get('Short Trades (won %)'), s.get('Long Trades (won %)')
    _cards_row([
        ("Total Trades", f"{int(tt)}" if tt else '—', '#e6edf3', f"Deals: {s.get('Total Deals', '—')}"),
        ("Win Rate", f"{_paren(pt):.2f}%" if _paren(pt) is not None else '—', '#00cf8d',
         f"{int(_num(pt))} W / {int(_num(lt))} L" if _num(pt) is not None and _num(lt) is not None else ''),
        ("Long (won %)", str(lg) if lg else '—', '#00cf8d'),
        ("Short (won %)", str(st_) if st_ else '—', '#ff9f43'),
    ])
    aw, al = _num(s.get('Average profit trade')), _num(s.get('Average loss trade'))
    _cards_row([
        ("Avg Win / Avg Loss", f"{_fmt_money(aw)} / {_fmt_money(al)}", '#e6edf3',
         f"R:R = {aw / abs(al):.2f}" if aw and al else ''),
        ("Cel mai mare profit / pierdere",
         f"{_fmt_money(_num(s.get('Largest profit trade')))} / {_fmt_money(_num(s.get('Largest loss trade')))}", '#e6edf3'),
        ("Max consecutive wins", str(s.get('Maximum consecutive wins ($)', '—')), '#00cf8d'),
        ("Max consecutive losses", str(s.get('Maximum consecutive losses ($)', '—')), '#ff4b4b'),
    ])
    _cards_row([
        ("Holding min", str(s.get('Minimal position holding time', '—')), '#e6edf3'),
        ("Holding mediu", str(s.get('Average position holding time', '—')), '#e6edf3'),
        ("Holding max", str(s.get('Maximal position holding time', '—')), '#e6edf3'),
        ("Z-Score", str(s.get('Z-Score', '—')), '#e6edf3', "dependență între trade-uri"),
    ])

    # ── Verificare reconstrucție ──
    calc_net = trades_all['Net P&L USD'].sum() if not trades_all.empty else 0
    ok_n = tt is None or int(tt) == len(trades_all)
    ok_p = net is None or abs(calc_net - net) < 1.0
    if ok_n and ok_p:
        st.success(f"✅ Reconstrucție validată: {len(trades_all)} trade-uri, profit net {_fmt_money(calc_net)} — identic cu raportul MT5.")
    else:
        st.warning(f"⚠️ Reconstrucția din Deals diferă de raport: {len(trades_all)} trade-uri / {_fmt_money(calc_net)} "
                   f"vs. MT5 {tt} / {_fmt_money(net)}. Posibil închideri parțiale sau poziții încă deschise la final.")

    with st.expander(f"⚙️ Parametrii EA (Inputs) — {len(rep['inputs_dict'])} setări", expanded=False):
        rows, group = [], ''
        for line in rep['inputs']:
            k, _, v = line.partition('=')
            if k.strip().startswith('═') or v == '':
                group = k.replace('═', '').strip()
                continue
            rows.append({'Grup': group, 'Parametru': k.strip(), 'Valoare': v.strip()})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=400)
            set_txt = "\n".join(f"{r['Parametru']}={r['Valoare']}" for r in rows)
            st.download_button("⬇️ Export parametri (.set text)", set_txt, file_name="parametri_ea.txt",
                               mime="text/plain", key="mt5_dl_set")
        else:
            st.info("Raportul nu conține parametri de intrare.")

    with st.expander("📑 Toate statisticile brute din raport", expanded=False):
        st.dataframe(pd.DataFrame([{'Statistică': k, 'Valoare': str(v)} for k, v in rep['stats'].items()]),
                     use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 2 — BALANȚĂ, DRAWDOWN, RANDAMENT LUNAR
# ══════════════════════════════════════════════════════════════
def render_mt5_balance(df, deposit, is_filtered):
    st.markdown("## 📈 Balanță, Drawdown & Randament")
    if df.empty:
        st.warning("Nu există trade-uri pentru filtrele selectate.")
        return
    if is_filtered:
        st.info("ℹ️ Filtre active: curba e reconstruită doar din trade-urile filtrate (depozit + P&L cumulat).")

    d = df.sort_values('Exit Time').copy()
    d['Balance'] = deposit + d['Net P&L USD'].cumsum()
    d['Peak'] = d['Balance'].cummax().clip(lower=deposit)
    d['DD $'] = d['Balance'] - d['Peak']
    d['DD %'] = d['DD $'] / d['Peak'] * 100

    final_bal = d['Balance'].iloc[-1]
    total_ret = (final_bal / deposit - 1) * 100 if deposit else 0
    days = max((d['Exit Time'].iloc[-1] - d['Entry Time'].iloc[0]).days, 1)
    cagr = ((final_bal / deposit) ** (365.25 / days) - 1) * 100 if deposit and final_bal > 0 else 0
    max_dd_pct = d['DD %'].min()
    calmar = cagr / abs(max_dd_pct) if max_dd_pct < 0 else np.nan

    _cards_row([
        ("Balanță finală", _fmt_money(final_bal), '#00cf8d' if final_bal >= deposit else '#ff4b4b',
         f"Depozit: {_fmt_money(deposit)}"),
        ("Randament total", f"{total_ret:+.2f}%", '#00cf8d' if total_ret >= 0 else '#ff4b4b', f"{days} zile"),
        ("CAGR (anualizat)", f"{cagr:+.2f}%", '#58a6ff', "randament compus / an"),
        ("Max DD (balanță)", f"{max_dd_pct:.2f}%", '#ff4b4b',
         f"Calmar: {calmar:.2f}" if not np.isnan(calmar) else ''),
    ])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d['Exit Time'], y=d['Balance'], mode='lines', name='Balanță',
                             line=dict(color='#00cf8d', width=2)))
    fig.add_trace(go.Scatter(x=d['Exit Time'], y=d['Peak'], mode='lines', name='Peak',
                             line=dict(color='#8b949e', width=1, dash='dot')))
    fig.add_hline(y=deposit, line_dash='dash', line_color='#58a6ff', annotation_text='Depozit')
    fig.update_layout(title='Curba de balanță', yaxis_title='USD')
    st.plotly_chart(_dark(fig, 420), use_container_width=True)

    fig_dd = go.Figure(go.Scatter(x=d['Exit Time'], y=d['DD %'], fill='tozeroy', mode='lines',
                                  line=dict(color='#ff4b4b', width=1), name='DD %'))
    fig_dd.update_layout(title='Drawdown din peak (%)', yaxis_title='%')
    st.plotly_chart(_dark(fig_dd, 260), use_container_width=True)

    # Prop-firm check
    with st.expander("🏦 Verificare reguli Prop Firm pe balanță (daily / overall DD)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            lim_daily = st.number_input("Daily loss limit (%):", 0.5, 20.0, 5.0, 0.5, key="mt5_pf_daily")
        with c2:
            lim_total = st.number_input("Max loss limit (%, static din depozit):", 1.0, 30.0, 10.0, 0.5, key="mt5_pf_total")
        dd_day = d.groupby(d['Exit Time'].dt.date)['Net P&L USD'].sum()
        bal_start_day = (deposit + d.groupby(d['Exit Time'].dt.date)['Net P&L USD'].sum().cumsum().shift(1)).fillna(deposit)
        day_pct = dd_day / bal_start_day * 100
        worst_day = day_pct.min()
        breaches_daily = (day_pct <= -lim_daily).sum()
        min_bal_pct = (d['Balance'].min() / deposit - 1) * 100
        breach_total = min_bal_pct <= -lim_total
        _cards_row([
            ("Cea mai proastă zi", f"{worst_day:.2f}%", '#ff4b4b' if worst_day <= -lim_daily else '#00cf8d',
             str(day_pct.idxmin())),
            ("Zile peste limita daily", f"{breaches_daily}", '#ff4b4b' if breaches_daily else '#00cf8d'),
            ("Minim balanță vs depozit", f"{min_bal_pct:+.2f}%", '#ff4b4b' if breach_total else '#00cf8d',
             "❌ cont pierdut" if breach_total else "✅ în limită"),
        ])
        st.caption("Calcul pe balanță (trade-uri închise). Equity intraday poate fi mai jos — vezi Equity DD din raportul oficial.")

    # ── Randament lunar (heatmap) ──
    st.markdown("### 🗓️ Randament lunar (%)")
    d['YM'] = d['Exit Time'].dt.to_period('M')
    m = d.groupby('YM').agg(PnL=('Net P&L USD', 'sum'), End=('Balance', 'last'),
                            Trades=('Net P&L USD', 'count')).reset_index()
    m['Start'] = m['End'].shift(1).fillna(deposit)
    m['Ret %'] = m['PnL'] / m['Start'] * 100
    m['Year'] = m['YM'].dt.year
    m['Mo'] = m['YM'].dt.month
    piv = m.pivot(index='Year', columns='Mo', values='Ret %').reindex(columns=range(1, 13))
    yearly = d.groupby(d['Exit Time'].dt.year).agg(PnL=('Net P&L USD', 'sum'))
    y_start = (deposit + yearly['PnL'].cumsum().shift(1)).fillna(deposit)
    piv['An'] = (yearly['PnL'] / y_start * 100).reindex(piv.index)
    labels = MONTHS_RO_SHORT + ['TOTAL AN']
    z = piv.values
    text = [[('' if np.isnan(v) else f"{v:+.1f}%") for v in row] for row in z]
    fig_hm = go.Figure(go.Heatmap(z=z, x=labels, y=[str(y) for y in piv.index], text=text,
                                  texttemplate='%{text}', colorscale='RdYlGn', zmid=0,
                                  showscale=False, hovertemplate='%{y} %{x}: %{text}<extra></extra>'))
    fig_hm.update_yaxes(autorange='reversed', type='category')
    st.plotly_chart(_dark(fig_hm, 120 + 50 * len(piv)), use_container_width=True)

    pos_m = (m['Ret %'] > 0).sum()
    c1, c2, c3 = st.columns(3)
    with c1:
        _card("Luni profitabile", f"{pos_m}/{len(m)}", '#00cf8d', f"{pos_m / len(m) * 100:.0f}%")
    with c2:
        best = m.loc[m['Ret %'].idxmax()]
        _card("Cea mai bună lună", f"{best['Ret %']:+.2f}%", '#00cf8d', str(best['YM']))
    with c3:
        worst = m.loc[m['Ret %'].idxmin()]
        _card("Cea mai slabă lună", f"{worst['Ret %']:+.2f}%", '#ff4b4b', str(worst['YM']))
    st.write("")

    # ── Tabel anual ──
    st.markdown("### 📆 Rezumat pe ani")
    rows = []
    for y, g in d.groupby(d['Exit Time'].dt.year):
        start = g['Balance'].iloc[0] - g['Net P&L USD'].iloc[0]
        peak = g['Balance'].cummax().clip(lower=start)
        ddp = ((g['Balance'] - peak) / peak * 100).min()
        gw, gl = g.loc[g['Net P&L USD'] > 0, 'Net P&L USD'].sum(), -g.loc[g['Net P&L USD'] < 0, 'Net P&L USD'].sum()
        rows.append({'An': y, 'Trades': len(g), 'Win Rate': f"{(g['Result'] == 'Win').mean() * 100:.1f}%",
                     'Profit': f"${g['Net P&L USD'].sum():,.2f}",
                     'Randament': f"{g['Net P&L USD'].sum() / start * 100:+.2f}%",
                     'Profit Factor': f"{gw / gl:.2f}" if gl > 0 else '∞',
                     'Max DD': f"{min(ddp, 0):.2f}%"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# TAB 3 — SETUP-URI, IEȘIRI, EXECUȚIE
# ══════════════════════════════════════════════════════════════
def render_mt5_setups(df, orders, setup_label="comentariu EA", volume_label="loturi"):
    st.markdown("## 🎯 Setup-uri, Ieșiri & Execuție")
    if df.empty:
        st.warning("Nu există trade-uri pentru filtrele selectate.")
        return

    # ── Pe setup (comentariul ordinului de intrare) ──
    st.markdown(f"### 🧩 Performanță pe setup ({setup_label})")
    g = _group_stats(df, ['Signal', 'Direction'])
    fig = px.bar(g, x='Signal', y='Profit', color='Direction', text=g['WR %'].map(lambda v: f"WR {v:.0f}%"),
                 color_discrete_map={'Long': '#00cf8d', 'Short': '#ff9f43'}, title='Profit net pe setup')
    st.plotly_chart(_dark(fig), use_container_width=True)
    show = g.copy()
    show['Profit'] = show['Profit'].map(lambda v: f"${v:,.2f}")
    show['Avg'] = show['Avg'].map(lambda v: f"${v:,.2f}")
    show['WR %'] = show['WR %'].map(lambda v: f"{v:.1f}%")
    show['PF'] = show['PF'].map(lambda v: '∞' if pd.isna(v) else f"{v:.2f}")
    show['AvgDur'] = show['AvgDur'].map(lambda v: f"{v:.0f} min")
    st.dataframe(show[['Signal', 'Direction', 'Trades', 'W', 'L', 'WR %', 'Profit', 'Avg', 'PF', 'AvgDur']]
                 .rename(columns={'Signal': 'Setup', 'Avg': 'Avg/trade', 'AvgDur': 'Durată medie'}),
                 use_container_width=True, hide_index=True)

    # ── Motiv ieșire ──
    has_exit = 'Exit Reason' in df.columns and df['Exit Reason'].nunique() > 0 and not (df['Exit Reason'] == 'N/A').all()
    if not has_exit:
        df = df.assign(**{'Exit Reason': 'N/A'})
    st.markdown("### 🚪 Cum se închid trade-urile")
    c1, c2 = st.columns(2)
    er = _group_stats(df, 'Exit Reason')
    with c1:
        fig_pie = px.pie(er, names='Exit Reason', values='Trades', hole=0.5, title='Distribuție ieșiri',
                         color='Exit Reason', color_discrete_map={'Take Profit': '#00cf8d', 'Stop Loss': '#ff4b4b',
                                                                  'Închidere EA / Timp': '#58a6ff',
                                                                  'Stop Out': '#8b0000', 'Altele': '#8b949e'})
        st.plotly_chart(_dark(fig_pie, 340), use_container_width=True)
    with c2:
        fig_er = px.bar(er, x='Exit Reason', y='Profit', color='Exit Reason', title='P&L pe tip de ieșire',
                        color_discrete_map={'Take Profit': '#00cf8d', 'Stop Loss': '#ff4b4b',
                                            'Închidere EA / Timp': '#58a6ff', 'Stop Out': '#8b0000', 'Altele': '#8b949e'})
        fig_er.update_layout(showlegend=False)
        st.plotly_chart(_dark(fig_er, 340), use_container_width=True)
    other = df[df['Exit Reason'] == 'Închidere EA / Timp']
    if not other.empty:
        st.caption(f"ℹ️ {len(other)} trade-uri închise fără TP/SL (de ex. Hard Time / Close EOD) — "
                   f"P&L total {_fmt_money(other['Net P&L USD'].sum())}, ora medie de ieșire "
                   f"{other['Exit Time'].dt.strftime('%H:%M').mode().iloc[0]}.")

    # ── Rentabilitate % per trade (risc real pe cont) ──
    st.markdown("### 📐 Rezultat per trade în % din balanță")
    if 'Return %' not in df.columns:
        df = df.assign(**{'Return %': np.nan})
    c1, c2 = st.columns([2, 1])
    with c1:
        fig_r = px.histogram(df, x='Return %', color='Result', nbins=60, barmode='overlay',
                             color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'},
                             title='Distribuție % câștig / pierdere pe trade')
        st.plotly_chart(_dark(fig_r, 340), use_container_width=True)
    with c2:
        w = df[df['Result'] == 'Win']['Return %']
        l = df[df['Result'] == 'Loss']['Return %']
        _card("Win mediu", f"{w.mean():+.2f}%" if len(w) else '—', '#00cf8d', "din balanța curentă")
        st.write("")
        _card("Loss mediu (≈ risc real)", f"{l.mean():+.2f}%" if len(l) else '—', '#ff4b4b',
              f"cel mai mare: {l.min():+.2f}%" if len(l) else '')

    # ── Puncte / durată ──
    st.markdown("### ⏱️ Puncte & durată")
    c1, c2 = st.columns(2)
    with c1:
        if 'Points' in df.columns and df['Points'].notna().any():
            fig_p = px.box(df, x='Direction', y='Points', color='Result', points=False,
                           color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'}, title='Puncte câștigate/pierdute')
        else:
            fig_p = px.box(df, x='Direction', y='Net P&L USD', color='Result', points=False,
                           color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'}, title='P&L ($) câștigat/pierdut')
        st.plotly_chart(_dark(fig_p, 340), use_container_width=True)
    with c2:
        fig_d = px.box(df, x='Exit Reason', y='Duration_Min', color='Direction', points=False,
                       color_discrete_map={'Long': '#00cf8d', 'Short': '#ff9f43'}, title='Durată (min) pe tip ieșire')
        st.plotly_chart(_dark(fig_d, 340), use_container_width=True)

    # ── Lot size în timp ──
    if 'Volume' in df.columns and df['Volume'].notna().any() and df['Volume'].nunique() > 1:
        fig_v = px.scatter(df, x='Entry Time', y='Volume', color='Direction', opacity=0.7,
                           color_discrete_map={'Long': '#00cf8d', 'Short': '#ff9f43'},
                           title=f'Volum ({volume_label}) pe trade — position sizing în timp')
        st.plotly_chart(_dark(fig_v, 300), use_container_width=True)

    # ── Execuție ordine pending ──
    if orders is not None and not orders.empty and 'State' in orders.columns and 'Type' in orders.columns:
        st.markdown("### 📬 Execuția ordinelor pending")
        o = orders.copy()
        o['Type'] = o['Type'].astype(str).str.strip().str.lower()
        o['State'] = o['State'].astype(str).str.strip().str.lower()
        pend = o[o['Type'].str.contains('stop|limit', regex=True)]
        if 'Open Time' in pend.columns and not df.empty:
            lo, hi = df['Entry Time'].min().normalize(), df['Exit Time'].max() + pd.Timedelta(days=1)
            pend = pend[(pend['Open Time'] >= lo) & (pend['Open Time'] <= hi)]
        if not pend.empty:
            tab = pend.groupby(['Type', 'State']).size().unstack(fill_value=0)
            tab['Total'] = tab.sum(axis=1)
            if 'filled' in tab.columns:
                tab['Fill rate'] = (tab['filled'] / tab['Total'] * 100).map(lambda v: f"{v:.1f}%")
            st.dataframe(tab.reset_index().rename(columns={'Type': 'Tip ordin'}),
                         use_container_width=True, hide_index=True)
            st.caption("filled = declanșat • expired = fereastra a expirat fără breakout • "
                       "canceled = anulat (de ex. OCO după ce s-a declanșat partea opusă).")
        mkt = o[o['Type'].isin(['buy', 'sell']) & ~o.get('Comment', pd.Series('', index=o.index)).astype(str)
                .str.lower().str.match(r'^(tp|sl|so)\b|^nan$|^$')]
        if not mkt.empty:
            st.caption(f"📌 {len(mkt)} intrări la market (fallback), în afara ordinelor pending.")



# ══════════════════════════════════════════════════════════════
# TAB — PROBABILITATE TRADE URMĂTOR (Win / Loss după șir)
# ══════════════════════════════════════════════════════════════
def render_mt5_next_trade(df, get_streak_probabilities):
    st.markdown("## 🔮 Probabilitatea ca următorul trade să fie Win / Loss")
    st.caption("Pentru fiecare șir de rezultate (ex. 2 Win la rând) se numără ce a urmat istoric. "
               "„Eșantion” = de câte ori a apărut situația respectivă în date.")
    if df.empty:
        st.warning("Nu există trade-uri pentru filtrele selectate.")
        return

    setups = sorted(df['Signal'].unique())
    opt = ["Toate trade-urile"] + [f"Doar {s}" for s in setups] if len(setups) > 1 else ["Toate trade-urile"]
    alegere = st.radio("Calculează pe:", opt, horizontal=True, key="mt5_next_scope")
    d = df if alegere == "Toate trade-urile" else df[df['Signal'] == alegere.replace("Doar ", "", 1)]
    d = d.sort_values('Entry Time')
    if len(d) < 3:
        st.warning("Prea puține trade-uri pentru calcul.")
        return

    df_win, df_loss, active_label = get_streak_probabilities(d)
    base_wr = (d['Result'] == 'Win').mean() * 100

    # ── Situația curentă → predicție pentru trade-ul următor ──
    tabel = df_win if 'Win' in active_label else df_loss
    rand = tabel[tabel['Șir curent'] == active_label] if not tabel.empty else tabel
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _card("Șir activ acum", active_label, '#00cf8d' if 'Win' in active_label else '#ff4b4b',
              f"ultimul trade: {d['Exit Time'].iloc[-1]:%d.%m.%Y %H:%M}")
    if not rand.empty:
        r = rand.iloc[0]
        p_win = float(str(r['Probabilitate Win Următor']).rstrip('%'))
        n = int(str(r['Eșantion']).split()[0])
        with c2:
            _card("Probabilitate WIN următor", f"{p_win:.1f}%", '#00cf8d' if p_win >= base_wr else '#ff9f43',
                  f"vs. win rate general {base_wr:.1f}%")
        with c3:
            _card("Probabilitate LOSS următor", f"{100 - p_win:.1f}%", '#ff4b4b')
        with c4:
            _card("Eșantion", f"{n} ori", '#00cf8d' if n >= 30 else ('#ff9f43' if n >= 10 else '#ff4b4b'),
                  "solid" if n >= 30 else ("orientativ" if n >= 10 else "prea mic — nu te baza"))
    else:
        with c2:
            _card("Probabilitate WIN următor", "—", '#8b949e',
                  "șirul activ nu a mai apărut până acum")
        with c3:
            _card("Win rate general", f"{base_wr:.1f}%", '#58a6ff')
    st.write("")

    # ── Tabelele (același format ca la TradingView) ──
    def style_streak_row(row):
        if row['Șir curent'] == active_label:
            color = '#00cf8d' if 'Win' in active_label else '#cf0000'
            return [f'background-color: {color}; color: white; font-weight: bold'] * len(row)
        return [''] * len(row)

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("#### 🟢 După un șir de WIN-uri")
        if not df_win.empty:
            st.table(df_win.style.apply(style_streak_row, axis=1))
        else:
            st.info("Nu există date.")
    with col_p2:
        st.markdown("#### 🔴 După un șir de LOSS-uri")
        if not df_loss.empty:
            st.table(df_loss.style.apply(style_streak_row, axis=1))
        else:
            st.info("Nu există date.")
    st.caption(f"Rândul colorat = situația în care te afli acum. Win rate-ul de bază pe selecția curentă este "
               f"{base_wr:.1f}% — o probabilitate peste el înseamnă că după acel șir rezultatele au fost mai bune decât media. "
               f"Rândurile cu eșantion sub 10 sunt statistic nesigure.")

# ══════════════════════════════════════════════════════════════
# TAB — CONTURI FUNDED (simulare payout-uri)
# ══════════════════════════════════════════════════════════════
PAYOUT_STD = "Standard (activare N zile)"
PAYOUT_FN = "FundedNext (ciclu fix)"
PAYOUT_TYPES = [PAYOUT_STD, PAYOUT_FN]

ALLOC_MODES = {
    'copy': "🟢 Toate odată (copy-trading)",
    'rr': "🔄 Pe rând (fiecare trade pe alt cont)",
    'loss': "🔴 Schimbă contul după un Loss",
    'payout': "💰 Un cont până la payout, apoi următorul",
    'balance': "⚖️ Load-balance (contul cu cel mai mult buffer DD)",
}
ALLOC_HELP = {
    'copy': "Fiecare trade se deschide pe TOATE conturile. Profit maxim, dar toate conturile trec prin aceleași drawdown-uri.",
    'rr': "Trade 1 → contul A, trade 2 → contul B, trade 3 → contul C, apoi din nou A. Riscul se împarte uniform.",
    'loss': "Rămâi pe același cont cât timp câștigi; după un Loss treci pe următorul cont. Un șir de pierderi se împarte pe mai multe conturi.",
    'payout': "Tranzacționezi un singur cont până face payout, apoi treci pe următorul (scară de payout-uri).",
    'balance': "Fiecare trade merge pe contul cel mai departe de limita de Max DD — protejează conturile lovite.",
}

_COMMON_COLS = {
    "Max DD (%)": 10.0, "Daily DD (%)": 5.0, "Tip payout": PAYOUT_STD, "Zile (activare / ciclu)": 14,
    "Ziua cerere": 0, "Target payout (%)": 5.0, "Min payout (%)": 0.0, "Profit split (%)": 80.0, "Cost cont ($)": 0.0,
}
FUNDED_DEFAULT = pd.DataFrame([{"Nume": "Cont 1", "Mărime ($)": 100000.0, "Nr. conturi": 1,
                                "Risc/trade (%)": 1.0, **_COMMON_COLS}])
FUNDED_DEFAULT_ABS = pd.DataFrame([{"Nume": "Cont 1", "Mărime ($)": 50000.0, "Nr. conturi": 1,
                                    "Multiplicator (×)": 1.0, **_COMMON_COLS}])


class _FundedUnit:
    """Un cont funded individual (o copie). Ține starea, payout-urile, pierderile și istoricul."""

    def __init__(self, label, group, acc, risk_ea, opts, idx):
        self.label, self.group, self.acc, self.idx, self.opts = label, group, acc, idx, opts
        self.size = float(acc["Mărime ($)"])
        self.max_dd = float(acc["Max DD (%)"]) / 100
        self.daily_dd = float(acc["Daily DD (%)"]) / 100
        self.target = float(acc["Target payout (%)"] or 0) / 100
        self.min_pay = float(acc["Min payout (%)"] or 0) / 100
        self.n_days = int(acc["Zile (activare / ciclu)"])
        self.day_x = int(acc.get("Ziua cerere", 0) or 0)
        self.split = float(acc["Profit split (%)"]) / 100
        self.fee = float(acc["Cost cont ($)"] or 0)
        self.fn = str(acc.get("Tip payout", PAYOUT_STD)).startswith("FundedNext")
        if opts.get('mode') == 'abs':
            self.abs_mode, self.scale = True, float(acc.get("Multiplicator (×)", 1.0) or 1.0)
        else:
            self.abs_mode = False
            self.scale = float(acc["Risc/trade (%)"]) / risk_ea if risk_ea else 1.0
        self.payouts, self.fails, self.curve, self.instances = [], [], [], []
        self.instance, self.total_cost, self.noprof, self.n_trades = 0, 0.0, 0, 0
        self.active = True
        self._new_instance(None)

    # ── ciclu de viață ──
    def _new_instance(self, when):
        self.instance += 1
        self.total_cost += self.fee
        self.bal = self.peak = self.size
        self.cycle_start = None          # pornește la primul trade (activare)
        self.activated = False
        self.cycle_no, self.cyc_trades, self.cyc_min, self.cyc_worst_day = 1, 0, self.size, 0.0
        self.day, self.day_start, self.day_trades = None, self.size, 0
        self.inst = {'Instanță': self.instance, 'Cumpărat la': when, 'Payout-uri': 0, 'Încasat': 0.0, 'Trade-uri': 0}
        if when is not None:
            self.curve.append({'Time': when, 'Balance': self.size, 'Instanță': self.instance, 'Event': 'Cont nou'})

    def _close_instance(self, end, status, reason=''):
        start = self.inst['Cumpărat la'] if self.inst['Cumpărat la'] is not None else end
        self.instances.append({**self.inst, 'Cumpărat la': start, 'Închis la': end, 'Status': status,
                               'Motiv': reason, 'Zile activ': (end - start).days, 'Cost': self.fee,
                               'Net (încasat − cost)': self.inst['Încasat'] - self.fee})

    def floor(self):
        if self.opts['dd_type'] == 'static':
            return self.size * (1 - self.max_dd)
        return min(self.peak, self.size * (1 + self.max_dd)) - self.size * self.max_dd

    def buffer_ratio(self):
        return (self.bal - self.floor()) / (self.size * self.max_dd) if self.max_dd else 1.0

    # ── payout ──
    def _do_payout(self, when, reason):
        profit = self.bal - self.size
        days = (when - self.cycle_start).total_seconds() / 86400
        gross = min(profit, self.size * self.target) if (self.opts['cap_target'] and self.target > 0) else profit
        self.payouts.append({
            'Instanță': self.instance, 'Ciclu': self.cycle_no, 'Ciclu început': self.cycle_start,
            'Data payout': when, 'Zile ciclu': round(days, 1), 'Trade-uri': self.cyc_trades,
            'Profit brut': gross, 'Profit %': gross / self.size * 100,
            'Payout trader': gross * self.split, 'Partea firmei': gross * (1 - self.split),
            'Motiv': reason, 'Min balanță ciclu %': (self.cyc_min / self.size - 1) * 100,
            'Cea mai proastă zi %': self.cyc_worst_day,
            'Buffer DD folosit %': max(0.0, (self.size - self.cyc_min) / (self.size * self.max_dd) * 100) if self.max_dd else 0})
        self.inst['Payout-uri'] += 1
        self.inst['Încasat'] += gross * self.split
        self.curve.append({'Time': when, 'Balance': self.size, 'Instanță': self.instance, 'Event': 'PAYOUT'})
        self.bal = self.peak = self.size
        self.day_start = self.size
        self.cycle_start = when
        self.activated = True
        self.cycle_no += 1
        self.cyc_trades, self.cyc_min, self.cyc_worst_day = 0, self.size, 0.0

    def _profit_ok(self):
        p = self.bal - self.size
        return p > 0 and p >= self.size * self.min_pay - 1e-9

    def _std_times(self):
        wait = self.n_days if (not self.activated or self.opts['wait_each']) else 0
        elig = self.cycle_start + pd.Timedelta(days=wait)
        req = self.cycle_start + pd.Timedelta(days=self.day_x) if self.day_x > 0 else None
        return elig, req

    def _std_reason(self, now):
        if self.cycle_start is None or not self._profit_ok():
            return None
        elig, req = self._std_times()
        if now < elig:
            return None
        if req is not None and now >= req:
            return f'Ziua {self.day_x} (cerere programată)'
        if self.target > 0 and self.bal - self.size >= self.size * self.target - 1e-9:
            return 'Target atins'
        if req is None and self.target <= 0:
            return 'Imediat ce e eligibil'
        return None

    def time_events(self, now):
        """Evenimente care depind doar de timp (fără trade nou pe acest cont)."""
        if not self.active or self.cycle_start is None:
            return
        if self.fn:
            boundary = self.cycle_start + pd.Timedelta(days=self.n_days)
            while now >= boundary:
                if self._profit_ok():
                    self._do_payout(boundary, f'FundedNext: final ciclu {self.n_days} zile')
                else:
                    self.noprof += 1
                    self.cycle_start = boundary
                boundary = self.cycle_start + pd.Timedelta(days=self.n_days)
        else:
            elig, req = self._std_times()
            t_th = max(elig, req) if req is not None else elig
            if now >= t_th:
                r = self._std_reason(t_th)
                if r:
                    self._do_payout(t_th, r)

    # ── aplicare trade ──
    def apply_trade(self, tr):
        """Returnează 'win' / 'loss' / 'fail'."""
        ex = tr['Exit_Time']
        if self.inst['Cumpărat la'] is None:
            self.inst['Cumpărat la'] = tr['Entry_Time']
            self.curve.append({'Time': tr['Entry_Time'], 'Balance': self.size, 'Instanță': self.instance, 'Event': 'Start'})
        if self.cycle_start is None:
            self.cycle_start = tr['Entry_Time']          # activare = primul trade
        if ex.date() != self.day:
            self.day, self.day_start, self.day_trades = ex.date(), self.bal, 0
        bal_before = self.bal
        pnl = tr['PnL_abs'] * self.scale if self.abs_mode else self.bal * (tr['Return_pct'] / 100.0) * self.scale
        self.bal += pnl
        self.cyc_trades += 1
        self.day_trades += 1
        self.n_trades += 1
        self.inst['Trade-uri'] += 1
        self.peak = max(self.peak, self.bal)
        self.cyc_min = min(self.cyc_min, self.bal)
        day_base = self.size if self.opts['daily_base'] == 'cont' else self.day_start
        day_pct = (self.bal - self.day_start) / day_base * 100
        self.cyc_worst_day = min(self.cyc_worst_day, day_pct)

        reason, floor = None, self.floor()
        day_limit = day_base * self.daily_dd
        if self.day_start - self.bal >= day_limit - 1e-9:
            reason = 'Daily DD'
            detaliu = (f"Pierdere în ziua {ex:%d.%m.%Y}: {_fmt_money(self.bal - self.day_start)} ({day_pct:.2f}%) "
                       f"din {self.day_trades} trade-uri pe acest cont — limita era {_fmt_money(-day_limit)} "
                       f"(-{self.daily_dd * 100:g}%). Balanța la început de zi: {_fmt_money(self.day_start)}.")
            limita, atins = f"-{self.daily_dd * 100:g}% / zi", f"{day_pct:.2f}%"
        elif self.bal <= floor + 1e-9:
            reason = 'Max DD'
            tip = 'static' if self.opts['dd_type'] == 'static' else 'trailing'
            detaliu = (f"Balanța a coborât la {_fmt_money(self.bal)} ({(self.bal / self.size - 1) * 100:.2f}% față de mărimea "
                       f"contului), sub pragul de Max DD {tip} de {_fmt_money(floor)}. Peak-ul ciclului fusese {_fmt_money(self.peak)}.")
            limita, atins = f"{_fmt_money(floor)} (-{self.max_dd * 100:g}%)", _fmt_money(self.bal)
        if reason:
            self.fails.append({
                'Instanță': self.instance, 'Cumpărat la': self.inst['Cumpărat la'], 'Data fail': ex, 'Motiv': reason,
                'Limită': limita, 'Atins': atins, 'Detaliu': detaliu,
                'Trade fatal': (f"#{tr.get('Trade_no', '')} {tr.get('Direction', '')} {tr.get('Signal', '')} "
                                f"intrare {tr['Entry_Time']:%d.%m %H:%M} → ieșire {ex:%d.%m %H:%M}").strip(),
                'P&L trade fatal': pnl, 'Balanță înainte': bal_before, 'Balanță la fail': self.bal,
                'Ciclu început': self.cycle_start, 'Zile în ciclu': (ex - self.cycle_start).days,
                'Trade-uri în ciclu': self.cyc_trades, 'Zile de viață cont': (ex - self.inst['Cumpărat la']).days,
                'Payout-uri încasate înainte': self.inst['Payout-uri'], 'Încasat înainte': self.inst['Încasat'],
                'Pierdere vs mărime': self.bal - self.size})
            self.curve.append({'Time': ex, 'Balance': self.bal, 'Instanță': self.instance, 'Event': f'FAIL ({reason})'})
            self._close_instance(ex, '❌ Pierdut', reason)
            if self.opts['rebuy']:
                self._new_instance(ex)
            else:
                self.active = False
            return 'fail'

        self.curve.append({'Time': ex, 'Balance': self.bal, 'Instanță': self.instance, 'Event': ''})
        if not self.fn:
            r = self._std_reason(ex)
            if r:
                self._do_payout(ex, r)
        return 'win' if pnl > 0 else 'loss'

    def finish(self, last_time):
        if self.active:
            self._close_instance(last_time, '✅ Activ', '')
        return {'Activ': self.active, 'Balanță curentă': self.bal if self.active else None,
                'Profit neîncasat': (self.bal - self.size) if self.active else 0.0,
                'Zile ciclu curent': (last_time - self.cycle_start).days if (self.active and self.cycle_start is not None) else 0,
                'Instanțe (conturi cumpărate)': self.instance, 'Cost total': self.total_cost,
                'Cicluri fără profit': self.noprof, 'Trade-uri primite': self.n_trades}


def simulate_funded_portfolio(trades, acc_df, risk_ea, opts, alloc='copy'):
    """Simulează toate conturile funded împreună, cu modul de alocare a trade-urilor ales."""
    units = []
    for _, acc in acc_df.iterrows():
        n = int(acc["Nr. conturi"])
        name = str(acc["Nume"])
        for k in range(n):
            label = name if n == 1 else f"{name} · {k + 1}"
            units.append(_FundedUnit(label, name, acc, risk_ea, opts, len(units)))
    if not units or trades.empty:
        return units, {}
    ptr = 0
    cur_pay = len(units[0].payouts)

    def _next_active(start):
        for j in range(len(units)):
            u = units[(start + j) % len(units)]
            if u.active:
                return (start + j) % len(units)
        return None

    for t in trades.itertuples(index=False):
        tr = t._asdict()
        now = tr['Exit_Time']
        for u in units:
            u.time_events(now)
        if not any(u.active for u in units):
            break
        if alloc == 'copy':
            for u in units:
                if u.active:
                    u.apply_trade(tr)
            continue
        if alloc == 'balance':
            act = [u for u in units if u.active]
            target_u = max(act, key=lambda u: (round(u.buffer_ratio(), 6), -u.idx))
            target_u.apply_trade(tr)
            continue
        nptr = _next_active(ptr)
        if nptr is None:
            break
        if nptr != ptr:
            ptr, cur_pay = nptr, len(units[nptr].payouts)
        u = units[ptr]
        if alloc == 'payout' and len(u.payouts) > cur_pay:      # a făcut payout între timp → următorul cont
            ptr = _next_active(ptr + 1)
            u, cur_pay = units[ptr], len(units[ptr].payouts)
        res = u.apply_trade(tr)
        if alloc == 'rr':
            move = True
        elif alloc == 'loss':
            move = res in ('loss', 'fail')
        else:  # payout
            move = len(u.payouts) > cur_pay or res == 'fail'
        if move:
            nxt = _next_active(ptr + 1)
            if nxt is not None:
                ptr, cur_pay = nxt, len(units[nxt].payouts)
    last = trades['Exit_Time'].max()
    for u in units:                      # payout-uri care devin eligibile până la ultimul trade
        u.time_events(last)
    states = {u.label: u.finish(last) for u in units}
    return units, states


def render_mt5_funded(trades_all, risk_ea=1.0, mode='pct'):
    """mode='pct' (MT5): P&L = Return % × balanță × (risc cont / risc EA)
       mode='abs' (TradingView): P&L = Net P&L USD × multiplicator (contracte fixe, fără compunere)"""
    st.markdown("## 🏦 Simulare Conturi Funded")
    if mode == 'abs':
        st.caption("Fiecare cont ia TOATE trade-urile din fișier (copy-trading). P&L-ul fiecărui trade e cel din "
                   "TradingView × „Multiplicator” (ex. 2 = dublul contractelor). Fără compunere — contracte fixe. "
                   "După fiecare payout contul revine la mărimea inițială.")
    else:
        st.caption("Fiecare cont ia TOATE trade-urile din raport (copy-trading). Mărimea poziției se scalează după "
                   f"riscul setat față de riscul EA-ului din raport ({risk_ea:g}% / trade), cu compunere în cadrul ciclului. "
                   "După fiecare payout contul revine la mărimea inițială.")
    if trades_all.empty:
        st.warning("Nu există trade-uri.")
        return

    # ── Perioada ──
    st.markdown("### 📅 Perioada simulării")
    t = trades_all.sort_values('Exit Time').copy()
    dmin, dmax = t['Entry Time'].min().date(), t['Exit Time'].max().date()
    c1, c2 = st.columns([1, 2])
    with c1:
        mod_p = st.radio("Perioadă:", ["Tot raportul", "O singură lună", "Interval personalizat"], key="fd_mod_p")
    with c2:
        if mod_p == "O singură lună":
            luni = t['Exit Time'].dt.to_period('M').drop_duplicates().astype(str).tolist()
            luna = st.selectbox("Luna:", luni[::-1], key="fd_luna")
            p = pd.Period(luna, 'M')
            start, end = p.start_time.date(), p.end_time.date()
        elif mod_p == "Interval personalizat":
            rng = st.date_input("De la – până la:", (dmin, dmax), min_value=dmin, max_value=dmax, key="fd_rng")
            start, end = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (dmin, dmax))
        else:
            start, end = dmin, dmax
        st.markdown(f"<small style='color:#8b949e;'>Simulare: <b>{start:%d.%m.%Y}</b> → <b>{end:%d.%m.%Y}</b></small>",
                    unsafe_allow_html=True)
    t = t[(t['Entry Time'].dt.date >= start) & (t['Exit Time'].dt.date <= end)]
    if t.empty:
        st.warning("Nu există trade-uri în perioada aleasă.")
        return
    if 'Return %' not in t.columns:
        t['Return %'] = np.nan
    if 'Signal' not in t.columns:
        t['Signal'] = ''
    sim_t = t[['Entry Time', 'Exit Time', 'Return %', 'Net P&L USD', 'Trade #', 'Direction', 'Signal']].rename(
        columns={'Entry Time': 'Entry_Time', 'Exit Time': 'Exit_Time', 'Return %': 'Return_pct',
                 'Net P&L USD': 'PnL_abs', 'Trade #': 'Trade_no'})

    # ── Conturi ──
    st.markdown("### 🧾 Conturile tale funded")
    st.caption("Adaugă / șterge rânduri cu ➕ / 🗑️. „Nr. conturi” = câte conturi identice ai cu aceleași reguli "
               "(fiecare e simulat separat, ca să poată primi trade-uri diferite).")
    st.markdown(f"""<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 14px;font-size:13px;'>
    <b>Tip payout</b><br>
    • <b>{PAYOUT_STD}</b> — contul se activează după „Zile (activare / ciclu)” (ex. 14) numărate de la
      <b>primul trade</b>. După activare poți retrage oricând vrei:<br>
      &nbsp;&nbsp;– <b>Ziua cerere</b> = în a câta zi a ciclului ceri payout (ex. 16, 22, 40). 0 = nu folosești o zi fixă.<br>
      &nbsp;&nbsp;– <b>Target payout (%)</b> = ceri payout când profitul ajunge la acest procent (maximul). 0 = nu folosești target.<br>
      &nbsp;&nbsp;– <b>Min payout (%)</b> = sub acest profit nu ceri payout.<br>
      &nbsp;&nbsp;Ziua și target-ul pot fi folosite împreună (câștigă care vine primul). Dacă ambele sunt 0, ceri payout imediat ce e eligibil.<br>
    • <b>{PAYOUT_FN}</b> — ciclu automat (pune 14 sau 15 zile). La finalul fiecărui ciclu, dacă ai orice profit
      (≥ Min payout) se retrage și contul se resetează; dacă nu, începe un ciclu nou cu balanța curentă.
      Ziua cerere și target-ul nu se folosesc aici.
    </div>""", unsafe_allow_html=True)
    st.write("")
    base_default = FUNDED_DEFAULT_ABS if mode == 'abs' else FUNDED_DEFAULT
    ss_key = f"fd_accounts_{mode}"
    if ss_key not in st.session_state:
        st.session_state[ss_key] = base_default.copy()
    _prev = st.session_state[ss_key]
    for _c, _v in base_default.iloc[0].items():          # compatibilitate cu sesiuni mai vechi
        if _c not in _prev.columns:
            _prev[_c] = _v
    _prev.loc[~_prev['Tip payout'].isin(PAYOUT_TYPES), 'Tip payout'] = PAYOUT_STD
    st.session_state[ss_key] = _prev[list(base_default.columns)]
    scale_cfg = ({"Multiplicator (×)": st.column_config.NumberColumn(min_value=0.1, max_value=100.0, step=0.5,
                                                                    format="%.2f", required=True)}
                 if mode == 'abs' else
                 {"Risc/trade (%)": st.column_config.NumberColumn(min_value=0.05, max_value=10.0, step=0.05,
                                                                  format="%.2f", required=True)})
    acc_df = st.data_editor(
        st.session_state[ss_key], num_rows="dynamic", use_container_width=True, hide_index=True,
        key=f"fd_editor_{mode}_v2",
        column_config={
            "Nume": st.column_config.TextColumn(required=True),
            "Mărime ($)": st.column_config.NumberColumn(min_value=1000, step=1000, format="$%.0f", required=True),
            "Nr. conturi": st.column_config.NumberColumn(min_value=1, max_value=30, step=1, required=True),
            **scale_cfg,
            "Max DD (%)": st.column_config.NumberColumn(min_value=0.5, max_value=50.0, step=0.5, required=True),
            "Daily DD (%)": st.column_config.NumberColumn(min_value=0.5, max_value=50.0, step=0.5, required=True),
            "Tip payout": st.column_config.SelectboxColumn(options=PAYOUT_TYPES, required=True, width="medium"),
            "Zile (activare / ciclu)": st.column_config.NumberColumn(min_value=0, max_value=90, step=1, required=True),
            "Ziua cerere": st.column_config.NumberColumn(min_value=0, max_value=365, step=1,
                                                          help="0 = fără zi fixă"),
            "Target payout (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5,
                                                                help="0 = fără target"),
            "Min payout (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.1),
            "Profit split (%)": st.column_config.NumberColumn(min_value=1.0, max_value=100.0, step=5.0, required=True),
            "Cost cont ($)": st.column_config.NumberColumn(min_value=0.0, step=10.0, format="$%.0f"),
        })
    acc_df = acc_df.dropna(subset=["Nume", "Mărime ($)"]).copy()
    defaults = base_default.iloc[0].to_dict()
    for col, v in defaults.items():
        if col in acc_df.columns:
            acc_df[col] = acc_df[col].fillna(v)
    if acc_df.empty:
        st.info("Adaugă cel puțin un cont.")
        return
    n_units = int(acc_df["Nr. conturi"].sum())

    with st.expander("⚙️ Reguli generale", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            dd_type = st.radio("Tip Max DD:", ["Static (din mărimea contului)", "Trailing (de la peak-ul balanței)"],
                               key="fd_ddtype")
            daily_base = st.radio("Daily DD calculat din:", ["Mărimea contului", "Balanța de la începutul zilei"],
                                  key="fd_dailybase")
        with c2:
            wait_each = st.checkbox("Standard: perioada de așteptare se aplică din nou după fiecare payout",
                                    value=False, key="fd_wait_each",
                                    help="Debifat = aștepți doar la activare (primul trade), apoi retragi când vrei.")
            cap_target = st.checkbox("Payout plafonat la target (excedentul nu se plătește)", value=False, key="fd_cap")
            rebuy = st.checkbox("După fail, cumpăr un cont nou și continui", value=True, key="fd_rebuy")
        st.caption("⚠️ Simularea folosește balanța la închiderea trade-urilor. Equity-ul intraday (pozițiile deschise) "
                   "poate atinge limitele mai devreme.")
    opts = {'dd_type': 'static' if dd_type.startswith('Static') else 'trailing',
            'daily_base': 'cont' if daily_base.startswith('Mărimea') else 'zi',
            'cap_target': cap_target, 'rebuy': rebuy, 'mode': mode, 'wait_each': wait_each}

    # ── Mod de tranzacționare a conturilor ──
    alloc = 'copy'
    if n_units > 1:
        st.markdown("### 🔀 Cum tranzacționezi conturile")
        labels = list(ALLOC_MODES.values())
        pick_alloc = st.radio("Mod de alocare a trade-urilor:", labels, key="fd_alloc", horizontal=False)
        alloc = [k for k, v in ALLOC_MODES.items() if v == pick_alloc][0]
        st.caption(ALLOC_HELP[alloc])

        with st.expander("📊 Compară toate modurile de alocare (aceleași conturi și perioadă)", expanded=True):
            comp = []
            days_p = max((pd.Timestamp(end) - pd.Timestamp(start)).days + 1, 1)
            for k, lbl in ALLOC_MODES.items():
                us, sts = simulate_funded_portfolio(sim_t, acc_df, risk_ea, opts, k)
                pays = [p for u in us for p in u.payouts]
                tot = sum(p['Payout trader'] for p in pays)
                cost = sum(v['Cost total'] for v in sts.values())
                nf = sum(len(u.fails) for u in us)
                comp.append({'Mod': lbl, 'Payout-uri': len(pays), 'Total încasat': tot,
                             'Payout mediu': tot / len(pays) if pays else 0.0,
                             'Fail-uri': nf, 'Cost conturi': cost, 'Net': tot - cost,
                             'Net / lună': (tot - cost) / (days_p / 30.44),
                             'Conturi active la final': sum(1 for v in sts.values() if v['Activ'])})
            comp = pd.DataFrame(comp).sort_values('Net', ascending=False)
            best = comp.iloc[0]
            fig_cmp = px.bar(comp, x='Mod', y='Net', color='Fail-uri', color_continuous_scale='RdYlGn_r',
                             text=comp['Payout-uri'].map(lambda v: f"{v} payout"), title='Net încasat pe mod de alocare')
            st.plotly_chart(_dark(fig_cmp, 340), use_container_width=True)
            cs = comp.copy()
            for c in ['Total încasat', 'Payout mediu', 'Cost conturi', 'Net', 'Net / lună']:
                cs[c] = cs[c].map(lambda v: f"${v:,.2f}")
            st.dataframe(cs, use_container_width=True, hide_index=True)
            st.caption(f"🏆 Cel mai bun net în perioada aleasă: {best['Mod']} — {_fmt_money(best['Net'])} "
                       f"({int(best['Payout-uri'])} payout-uri, {int(best['Fail-uri'])} fail-uri). "
                       "Rezultatele trecute nu garantează viitorul — uită-te și la fail-uri, nu doar la net.")

    # ── Simulare (modul ales) ──
    units, states = simulate_funded_portfolio(sim_t, acc_df, risk_ea, opts, alloc)
    all_pay, all_fail, all_inst, curves, rows = [], [], [], {}, []
    for u in units:
        state = states.get(u.label) or u.finish(sim_t['Exit_Time'].max())
        pay, fail, inst = pd.DataFrame(u.payouts), pd.DataFrame(u.fails), pd.DataFrame(u.instances)
        name = u.label
        curves[name] = (pd.DataFrame(u.curve), u.acc)
        if not inst.empty:
            inst.insert(0, 'Cont', name)
            all_inst.append(inst)
        if not pay.empty:
            pay.insert(0, 'Cont', name)
            pay['Nr. conturi'] = 1
            pay['Total trader (toate copiile)'] = pay['Payout trader']
            all_pay.append(pay)
        if not fail.empty:
            fail.insert(0, 'Cont', name)
            all_fail.append(fail)
        npay = len(pay)
        tot_trader = pay['Payout trader'].sum() if npay else 0.0
        cost = state['Cost total']
        rows.append({
            'Cont': name, 'Tip payout': 'FundedNext' if u.fn else 'Standard',
            'Mărime': f"${u.size:,.0f}", 'Trade-uri primite': state['Trade-uri primite'],
            'Payout-uri': npay, 'Fail-uri': len(fail),
            'Rată succes': f"{npay / (npay + len(fail)) * 100:.0f}%" if (npay + len(fail)) else '—',
            'Total încasat': f"${tot_trader:,.2f}",
            'Payout mediu': f"${pay['Payout trader'].mean():,.2f}" if npay else '—',
            'Min / Max': f"${pay['Payout trader'].min():,.0f} / ${pay['Payout trader'].max():,.0f}" if npay else '—',
            'Zile medii / payout': f"{pay['Zile ciclu'].mean():.1f}" if npay else '—',
            'Cost conturi': f"${cost:,.0f}",
            'Net după cost': f"${tot_trader - cost:,.2f}",
            'Conturi cumpărate': state['Instanțe (conturi cumpărate)'],
            'Ultima pierdere': (f"{fail.iloc[-1]['Data fail']:%d.%m.%Y} — {fail.iloc[-1]['Motiv']}"
                                if not fail.empty else '—'),
            'Status final': (f"✅ activ, profit neîncasat ${state['Profit neîncasat']:,.0f} "
                             f"({state['Zile ciclu curent']} zile)") if state['Activ']
                            else f"❌ pierdut ({fail.iloc[-1]['Motiv']}, {fail.iloc[-1]['Data fail']:%d.%m.%Y})",
            '_net': tot_trader - cost, '_trader': tot_trader, '_cost': cost,
            '_fails': len(fail), '_noprof': state.get('Cicluri fără profit', 0),
        })
    pay_df = pd.concat(all_pay, ignore_index=True) if all_pay else pd.DataFrame()
    fail_df = pd.concat(all_fail, ignore_index=True) if all_fail else pd.DataFrame()
    inst_df = pd.concat(all_inst, ignore_index=True) if all_inst else pd.DataFrame()
    summ = pd.DataFrame(rows)

    # ── KPI ──
    st.markdown("### 📊 Rezumat payout-uri" + (f" — {ALLOC_MODES[alloc]}" if n_units > 1 else ""))
    days_period = max((pd.Timestamp(end) - pd.Timestamp(start)).days + 1, 1)
    months = days_period / 30.44
    total_trader = summ['_trader'].sum()
    total_cost = summ['_cost'].sum()
    n_pay_total = len(pay_df)
    n_fail_total = int(summ['_fails'].sum())
    _cards_row([
        ("Payout-uri (toate conturile)", f"{n_pay_total}", '#00cf8d', f"pe {n_units} cont(uri)"),
        ("Total încasat (trader)", _fmt_money(total_trader), '#00cf8d', f"în {days_period} zile"),
        ("Venit mediu / lună", _fmt_money(total_trader / months if months else 0), '#58a6ff',
         f"net după costuri: {_fmt_money((total_trader - total_cost) / months if months else 0)}"),
        ("Fail-uri", f"{n_fail_total}", '#ff4b4b' if n_fail_total else '#00cf8d',
         f"cost conturi: {_fmt_money(total_cost)}"),
    ])
    if not pay_df.empty:
        pt = pay_df['Payout trader']
        first = pay_df.sort_values('Data payout').iloc[0]
        all_dates = pay_df.sort_values('Data payout')['Data payout']
        gaps = all_dates.diff().dt.total_seconds().dropna() / 86400
        _cards_row([
            ("Payout mediu", _fmt_money(pt.mean()), '#e6edf3', f"median {_fmt_money(pt.median())}"),
            ("Cel mai mare / mic", f"{_fmt_money(pt.max())} / {_fmt_money(pt.min())}", '#e6edf3'),
            ("Primul payout", f"{(first['Data payout'] - pd.Timestamp(start)).days} zile",
             '#58a6ff', f"{first['Data payout']:%d.%m.%Y} ({first['Cont']})"),
            ("Zile între payout-uri (oricare cont)", f"{gaps.mean():.1f}" if len(gaps) else '—',
             '#58a6ff', f"max pauză: {gaps.max():.0f} zile" if len(gaps) else ''),
        ])
        mot = pay_df['Motiv']
        n_tgt = int(mot.str.startswith('Target').sum())
        n_day = int(mot.str.startswith('Ziua').sum())
        n_fn = int(mot.str.startswith('FundedNext').sum())
        n_imm = int(mot.str.startswith('Imediat').sum())
        n_noprof = int(summ['_noprof'].sum())
        _cards_row([
            ("Prin target atins", f"{n_tgt}", '#00cf8d', f"{n_tgt / len(pay_df) * 100:.0f}% din payout-uri"),
            ("În ziua programată", f"{n_day + n_imm}", '#58a6ff',
             f"imediat după eligibilitate: {n_imm}" if n_imm else "ziua cerere"),
            ("FundedNext (final ciclu)", f"{n_fn}", '#ff9f43', f"cicluri fără profit: {n_noprof}"),
            ("Buffer DD folosit (max)", f"{pay_df['Buffer DD folosit %'].max():.0f}%",
             '#ff4b4b' if pay_df['Buffer DD folosit %'].max() > 70 else '#00cf8d',
             f"mediu {pay_df['Buffer DD folosit %'].mean():.0f}% din Max DD • {pay_df['Trade-uri'].mean():.1f} trade-uri / payout"),
        ])

    if n_fail_total:
        st.error(f"❌ {n_fail_total} cont(uri) pierdut(e) în perioada aleasă — vezi mai jos „Conturi pierdute — când și de ce”.")
    else:
        st.success("✅ Niciun cont pierdut în perioada aleasă.")

    st.markdown("#### Pe fiecare cont")
    st.dataframe(summ.drop(columns=['_net', '_trader', '_cost', '_fails', '_noprof']), use_container_width=True, hide_index=True)

    if pay_df.empty:
        st.info("Niciun payout în perioada aleasă — încearcă o perioadă mai lungă, un target mai mic sau mai puține zile.")
    else:
        # ── Grafice ──
        st.markdown("### 📈 Payout-urile în timp")
        pdv = pay_df.sort_values('Data payout').copy()
        fig = px.bar(pdv, x='Data payout', y='Total trader (toate copiile)', color='Cont',
                     hover_data={'Payout trader': ':,.2f', 'Profit %': ':.2f', 'Zile ciclu': True, 'Motiv': True},
                     title='Fiecare payout (suma încasată de tine)',
                     labels={'Total trader (toate copiile)': 'Payout ($)'})
        st.plotly_chart(_dark(fig, 360), use_container_width=True)

        cum = pdv[['Data payout', 'Total trader (toate copiile)']].copy()
        cum['Cumulat'] = cum['Total trader (toate copiile)'].cumsum()
        fig_c = go.Figure(go.Scatter(x=cum['Data payout'], y=cum['Cumulat'], mode='lines+markers',
                                     line=dict(color='#00cf8d', width=2), name='Încasat cumulat'))
        if total_cost > 0:
            fig_c.add_hline(y=total_cost, line_dash='dash', line_color='#ff4b4b', annotation_text='Cost conturi')
        fig_c.update_layout(title='Bani încasați cumulat', yaxis_title='USD')
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(_dark(fig_c, 340), use_container_width=True)
        with c2:
            fig_h = px.histogram(pdv, x='Payout trader', color='Cont', nbins=20, title='Distribuția mărimii payout-urilor')
            st.plotly_chart(_dark(fig_h, 340), use_container_width=True)

        st.markdown("### 🗓️ Payout-uri pe lună")
        pdv['Luna'] = pdv['Data payout'].dt.to_period('M').astype(str)
        lun = pdv.groupby('Luna').agg(Payouts=('Nr. conturi', 'sum'),
                                      Total=('Total trader (toate copiile)', 'sum'),
                                      Mediu=('Payout trader', 'mean')).reset_index()
        all_m = pd.period_range(start, end, freq='M').astype(str)
        lun = pd.DataFrame({'Luna': all_m}).merge(lun, on='Luna', how='left').fillna(0)
        if not fail_df.empty:
            fm = fail_df.assign(Luna=fail_df['Data fail'].dt.to_period('M').astype(str)).groupby('Luna').size()
            lun['Fail-uri'] = lun['Luna'].map(fm).fillna(0).astype(int)
        else:
            lun['Fail-uri'] = 0
        fig_m = px.bar(lun, x='Luna', y='Total', text=lun['Payouts'].map(lambda v: f"{int(v)} payout"),
                       title='Total încasat pe lună', color_discrete_sequence=['#00cf8d'])
        st.plotly_chart(_dark(fig_m, 340), use_container_width=True)
        luni_cu = (lun['Total'] > 0).sum()
        st.caption(f"Luni cu cel puțin un payout: {luni_cu}/{len(lun)} • "
                   f"lună medie: {_fmt_money(lun['Total'].mean())} • cea mai slabă: {_fmt_money(lun['Total'].min())} • "
                   f"cea mai bună: {_fmt_money(lun['Total'].max())}")
        lun_show = lun.copy()
        lun_show['Total'] = lun_show['Total'].map(lambda v: f"${v:,.2f}")
        lun_show['Mediu'] = lun_show['Mediu'].map(lambda v: f"${v:,.2f}" if v else '—')
        lun_show['Payouts'] = lun_show['Payouts'].astype(int)
        with st.expander("Tabel lunar", expanded=False):
            st.dataframe(lun_show, use_container_width=True, hide_index=True)

        st.markdown("### 📋 Lista completă a payout-urilor")
        show = pdv.copy()
        for c in ['Ciclu început', 'Data payout']:
            show[c] = show[c].dt.strftime('%d.%m.%Y %H:%M')
        for c in ['Profit brut', 'Payout trader', 'Partea firmei', 'Total trader (toate copiile)']:
            show[c] = show[c].map(lambda v: f"${v:,.2f}")
        for c in ['Profit %', 'Min balanță ciclu %', 'Cea mai proastă zi %', 'Buffer DD folosit %']:
            show[c] = show[c].map(lambda v: f"{v:.2f}%")
        show = show.drop(columns=['Luna', 'Nr. conturi', 'Total trader (toate copiile)'], errors='ignore')
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Export payout-uri CSV",
                           pdv.drop(columns=['Luna', 'Nr. conturi', 'Total trader (toate copiile)'], errors='ignore').to_csv(index=False),
                           file_name="payouts_funded.csv", mime="text/csv", key="fd_dl")

    # ── Pierderi & istoricul conturilor ──
    st.markdown("### ❌ Conturi pierdute — când și de ce")
    if fail_df.empty:
        st.success("✅ Niciun cont pierdut în perioada aleasă — nicio limită de Daily DD sau Max DD nu a fost atinsă.")
    else:
        n_d = (fail_df['Motiv'] == 'Daily DD').sum()
        n_m = (fail_df['Motiv'] == 'Max DD').sum()
        first_f = fail_df.sort_values('Data fail').iloc[0]
        _cards_row([
            ("Conturi pierdute", f"{len(fail_df)}", '#ff4b4b',
             ''),
            ("Pe Daily DD", f"{n_d}", '#ff9f43'),
            ("Pe Max DD", f"{n_m}", '#ff4b4b'),
            ("Primul cont pierdut", f"{first_f['Data fail']:%d.%m.%Y}", '#ff4b4b',
             f"{first_f['Cont']} #{first_f['Instanță']} — după {first_f['Zile de viață cont']} zile"),
        ])
        for _, f in fail_df.sort_values('Data fail').iterrows():
            copii = ''
            st.markdown(f"""
            <div class="bottom-box">
              <b>❌ {f['Cont']} — contul #{f['Instanță']}{copii} pierdut pe {f['Data fail']:%d.%m.%Y %H:%M}</b>
              &nbsp;•&nbsp; motiv: <b style="color:#ff6b6b;">{f['Motiv']}</b>
              (limită {f['Limită']}, atins {f['Atins']})<br>
              <small>{f['Detaliu']}<br>
              Trade-ul care l-a pierdut: {f['Trade fatal']} → {_fmt_money(f['P&L trade fatal'])}
              (balanță {_fmt_money(f['Balanță înainte'])} → {_fmt_money(f['Balanță la fail'])}).<br>
              Cont cumpărat pe {f['Cumpărat la']:%d.%m.%Y}, a trăit {f['Zile de viață cont']} zile,
              a făcut <b>{int(f['Payout-uri încasate înainte'])} payout-uri</b> ({_fmt_money(f['Încasat înainte'])} încasați)
              înainte să fie pierdut.</small>
            </div>""", unsafe_allow_html=True)
        if rebuy:
            st.caption("🔁 După fiecare pierdere s-a cumpărat un cont nou (instanța următoare), începând cu trade-ul următor.")
        else:
            st.caption("⛔ Cumpărarea unui cont nou după fail e dezactivată — contul pierdut nu mai continuă.")

    if not inst_df.empty:
        st.markdown("### 📜 Istoricul fiecărui cont cumpărat")
        ih = inst_df.copy()
        ih['Cont #'] = ih['Cont'] + ' #' + ih['Instanță'].astype(str)
        for c in ['Cumpărat la', 'Închis la']:
            ih[c] = pd.to_datetime(ih[c]).dt.strftime('%d.%m.%Y')
        ih.loc[ih['Status'] == '✅ Activ', 'Închis la'] = '— (încă activ)'
        for c in ['Încasat', 'Cost', 'Net (încasat − cost)']:
            ih[c] = ih[c].map(lambda v: f"${v:,.2f}")
        st.dataframe(ih[['Cont #', 'Status', 'Motiv', 'Cumpărat la', 'Închis la', 'Zile activ', 'Trade-uri',
                         'Payout-uri', 'Încasat', 'Cost', 'Net (încasat − cost)']],
                     use_container_width=True, hide_index=True)
        if not fail_df.empty:
            with st.expander("Tabel detaliat pierderi (export)", expanded=False):
                fs = fail_df.copy()
                for c in ['Data fail', 'Ciclu început', 'Cumpărat la']:
                    fs[c] = fs[c].dt.strftime('%d.%m.%Y %H:%M')
                for c in ['P&L trade fatal', 'Balanță înainte', 'Balanță la fail', 'Pierdere vs mărime', 'Încasat înainte']:
                    fs[c] = fs[c].map(lambda v: f"${v:,.2f}")
                st.dataframe(fs, use_container_width=True, hide_index=True)
                st.download_button("⬇️ Export pierderi CSV", fail_df.to_csv(index=False),
                                   file_name="conturi_pierdute.csv", mime="text/csv", key="fd_dl_fail")

    # ── Curba unui cont ──
    st.markdown("### 🔍 Evoluția unui cont")
    pick = st.selectbox("Cont:", list(curves.keys()), key="fd_pick")
    curve, acc = curves[pick]
    if not curve.empty:
        size = float(acc["Mărime ($)"])
        fig_a = go.Figure(go.Scatter(x=curve['Time'], y=curve['Balance'], mode='lines',
                                     line=dict(color='#58a6ff', width=1.5), name='Balanță'))
        pe = curve[curve['Event'] == 'PAYOUT']
        fe = curve[curve['Event'].str.startswith('FAIL')]
        if not pay_df.empty:
            pp = pay_df[pay_df['Cont'] == pick]
            fig_a.add_trace(go.Scatter(x=pp['Data payout'], y=size + pp['Profit brut'], mode='markers',
                                       marker=dict(symbol='triangle-up', size=11, color='#00cf8d'),
                                       name='Payout', text=pp['Payout trader'].map(lambda v: f"Payout ${v:,.0f}"),
                                       hoverinfo='text+x'))
        if not fe.empty:
            fig_a.add_trace(go.Scatter(x=fe['Time'], y=fe['Balance'], mode='markers', name='Fail',
                                       marker=dict(symbol='x', size=12, color='#ff4b4b'), text=fe['Event'],
                                       hoverinfo='text+x'))
        if not str(acc.get('Tip payout', PAYOUT_STD)).startswith('FundedNext') and float(acc['Target payout (%)'] or 0) > 0:
            fig_a.add_hline(y=size * (1 + float(acc['Target payout (%)']) / 100), line_dash='dot',
                            line_color='#00cf8d', annotation_text='Target payout')
        if opts['dd_type'] == 'static':
            fig_a.add_hline(y=size * (1 - float(acc['Max DD (%)']) / 100), line_dash='dash',
                            line_color='#ff4b4b', annotation_text='Max DD')
        fig_a.add_hline(y=size, line_color='#8b949e', line_width=1)
        fig_a.update_layout(title=f"{pick} — balanța resetată după fiecare payout", yaxis_title='USD')
        st.plotly_chart(_dark(fig_a, 420), use_container_width=True)


# ══════════════════════════════════════════════════════════════
# TRADINGVIEW — pregătire date pentru aceleași analize
# ══════════════════════════════════════════════════════════════
def prepare_tv_df(df, deposit):
    """Primește df-ul TradingView din app.py și adaugă coloanele folosite de analizele MT5:
    Signal (= semnalul de INTRARE), Exit Reason (= semnalul de ieșire), Balance After / Before, Return %, Points."""
    d = df.copy().sort_values('Exit Time')
    if d.empty:
        return d

    def _clean(col):
        return (d[col].astype(str).str.strip().replace({'nan': 'N/A', '': 'N/A', 'None': 'N/A'})
                if col in d.columns else pd.Series('N/A', index=d.index))
    d['Signal'] = _clean('Entry Signal') if 'Entry Signal' in d.columns else _clean('Signal')
    d['Exit Reason'] = _clean('Exit Signal')
    bal = deposit + d['Net P&L USD'].cumsum()
    d['Balance After'] = bal
    d['Balance Before'] = bal - d['Net P&L USD']
    d['Return %'] = np.where(d['Balance Before'] > 0, d['Net P&L USD'] / d['Balance Before'] * 100, np.nan)
    if 'Entry Price' in d.columns and 'Exit Price' in d.columns:
        sign = np.where(d['Direction'] == 'Short', -1, 1)
        d['Points'] = (pd.to_numeric(d['Exit Price'], errors='coerce') -
                       pd.to_numeric(d['Entry Price'], errors='coerce')) * sign
    return d


# ══════════════════════════════════════════════════════════════
# PAGINA MT5 — PUNCT DE INTRARE
# ══════════════════════════════════════════════════════════════
def render_mt5_page(render_full_analysis, render_risk_management, render_monte_carlo,
                    render_advanced_analysis, generate_pdf=None, get_streak_probabilities=None):
    st.markdown("<h3 style='text-align:center;'>🤖 Analiză MetaTrader 5</h3>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center; color:#8b949e;'>Încarcă raportul exportat din MT5 "
                "(Strategy Tester → tab Backtest → click dreapta → <b>Report → Excel/XML</b>, "
                "sau History → Report pentru contul real).</p>", unsafe_allow_html=True)
    up = st.file_uploader("Încarcă raportul MT5 (.xlsx)", type=["xlsx"], key="mt5_uploader")
    if not up:
        return

    try:
        with st.spinner("Citesc raportul MT5..."):
            rep = parse_mt5_report(up.getvalue())
    except Exception as e:
        st.error(f"Nu am putut citi raportul MT5: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    trades = rep['trades']
    if trades.empty:
        st.warning("Raportul nu conține trade-uri închise.")
        return

    # ── Filtre ──
    st.markdown("### 🔍 Filtrare Date (MT5)")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        yrs = sorted(trades['Year'].unique())
        sel_y = st.multiselect("Anii:", yrs, default=yrs, key="mt5_f_y")
    with c2:
        mo = [m for m in MONTHS_EN if m in trades['Month'].unique()]
        sel_m = st.multiselect("Lunile:", mo, default=mo, key="mt5_f_m")
    with c3:
        dy = [d for d in DAYS_EN if d in trades['Day'].unique()]
        sel_d = st.multiselect("Zilele:", dy, default=dy, key="mt5_f_d")
    with c4:
        sg = sorted(trades['Signal'].unique())
        sel_s = st.multiselect("Setup (comentariu):", sg, default=sg, key="mt5_f_s")
    with c5:
        sel_r = st.multiselect("Rezultat:", ["Win", "Loss"], default=["Win", "Loss"], key="mt5_f_r")

    df = trades[trades['Year'].isin(sel_y) & trades['Month'].isin(sel_m) & trades['Day'].isin(sel_d)
                & trades['Signal'].isin(sel_s) & trades['Result'].isin(sel_r)].copy()
    is_filtered = len(df) != len(trades)

    w, l = (df['Result'] == 'Win').sum(), (df['Result'] == 'Loss').sum()
    with st.expander(f"📋 Toate trade-urile MT5 — {len(df)} trades ({w}W / {l}L)", expanded=False):
        cols = ['Trade #', 'Entry Time', 'Exit Time', 'Direction', 'Signal', 'Volume', 'Entry Price',
                'Exit Price', 'Points', 'Exit Reason', 'Commission', 'Swap', 'Net P&L USD', 'Return %',
                'Balance After', 'Duration_Min']
        view = df[cols].sort_values('Entry Time', ascending=False)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Export CSV", view.to_csv(index=False), file_name="mt5_trades.csv",
                           mime="text/csv", key="mt5_dl_csv")
    st.caption("🕒 Orele sunt ora serverului brokerului (MT5), nu ora României.")

    t_glob, t_rep, t_bal, t_set, t_next, t_fund, t_risk, t_mc, t_adv = st.tabs([
        "🌍 Analiză Completă", "📋 Raport MT5", "📈 Balanță & Randament", "🎯 Setup-uri & Execuție",
        "🔮 Next Trade (Win/Loss)", "🏦 Conturi Funded", "💰 Risk Management", "🎲 Monte Carlo",
        "🔬 Analize Avansate"])
    with t_rep:
        render_mt5_official(rep, trades)
    with t_bal:
        render_mt5_balance(df, rep['deposit'], is_filtered)
    with t_set:
        render_mt5_setups(df, rep['orders'])
    with t_next:
        if get_streak_probabilities is not None:
            render_mt5_next_trade(df, get_streak_probabilities)
        else:
            st.info("Funcția de probabilități nu este disponibilă.")
    with t_glob:
        render_full_analysis(df, "MT5", [])
    with t_fund:
        try:
            risk_ea = float(str(rep['inputs_dict'].get('InpRiskPct', '')).replace(',', '.'))
        except ValueError:
            risk_ea = None
        if not risk_ea:
            l = trades.loc[trades['Result'] == 'Loss', 'Return %']
            risk_ea = round(abs(l.median()), 2) if len(l) else 1.0
        render_mt5_funded(trades[trades['Signal'].isin(sel_s)], risk_ea, mode='pct')
    with t_risk:
        render_risk_management(df)
    with t_mc:
        render_monte_carlo(df)
    with t_adv:
        render_advanced_analysis(df)

    if generate_pdf is not None:
        st.markdown("---")
        st.markdown("<h3 style='text-align:center;'>📄 Exportă Raportul MT5</h3>", unsafe_allow_html=True)
        _, cb, _ = st.columns([1, 2, 1])
        with cb:
            if st.button("🔄 Generează PDF (trade-uri MT5)", use_container_width=True, type="primary", key="mt5_pdf_btn"):
                with st.spinner("Se generează PDF-ul... (~10-20 secunde)"):
                    pdf = generate_pdf(df)
                st.download_button("📥 Descarcă Raport PDF MT5", data=pdf, file_name="Raport_MT5.pdf",
                                   mime="application/pdf", use_container_width=True, key="mt5_pdf_dl")
