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
def render_mt5_setups(df, orders):
    st.markdown("## 🎯 Setup-uri, Ieșiri & Execuție")
    if df.empty:
        st.warning("Nu există trade-uri pentru filtrele selectate.")
        return

    # ── Pe setup (comentariul ordinului de intrare) ──
    st.markdown("### 🧩 Performanță pe setup (comentariu EA)")
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
        fig_p = px.box(df, x='Direction', y='Points', color='Result', points=False,
                       color_discrete_map={'Win': '#00cf8d', 'Loss': '#ff4b4b'}, title='Puncte câștigate/pierdute')
        st.plotly_chart(_dark(fig_p, 340), use_container_width=True)
    with c2:
        fig_d = px.box(df, x='Exit Reason', y='Duration_Min', color='Direction', points=False,
                       color_discrete_map={'Long': '#00cf8d', 'Short': '#ff9f43'}, title='Durată (min) pe tip ieșire')
        st.plotly_chart(_dark(fig_d, 340), use_container_width=True)

    # ── Lot size în timp ──
    fig_v = px.scatter(df, x='Entry Time', y='Volume', color='Direction', opacity=0.7,
                       color_discrete_map={'Long': '#00cf8d', 'Short': '#ff9f43'},
                       title='Volum (loturi) pe trade — position sizing în timp')
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

    t_rep, t_bal, t_set, t_next, t_glob, t_risk, t_mc, t_adv = st.tabs([
        "📋 Raport MT5", "📈 Balanță & Randament", "🎯 Setup-uri & Execuție", "🔮 Next Trade (Win/Loss)",
        "🌍 Analiză Completă", "💰 Risk Management", "🎲 Monte Carlo", "🔬 Analize Avansate"])
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
