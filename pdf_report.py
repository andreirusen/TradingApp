"""
pdf_report.py  –  Modul complet pentru generarea raportului PDF trading
Folosește: reportlab (layout), matplotlib (grafice), pillow (imagini)
"""

import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak, HRFlowable, KeepTogether
)
from reportlab.platypus import BalancedColumns
from reportlab.lib.colors import HexColor, white, black


# ── PALETA CULORI ──────────────────────────────────────────────────────────────
BG_DARK     = HexColor("#0e1117")
BG_CARD     = HexColor("#161b22")
BG_CARD2    = HexColor("#1a1c24")
BORDER      = HexColor("#30363d")
GREEN       = HexColor("#00cf8d")
RED         = HexColor("#ff4b4b")
ORANGE      = HexColor("#ffa500")
BLUE        = HexColor("#4a9eff")
TEXT_MAIN   = HexColor("#e6edf3")
TEXT_MUTED  = HexColor("#8b949e")
WHITE       = white

# matplotlib dark theme settings
MPL_BG      = "#0e1117"
MPL_FG      = "#e6edf3"
MPL_GREEN   = "#00cf8d"
MPL_RED     = "#ff4b4b"
MPL_BLUE    = "#4a9eff"
MPL_ORANGE  = "#ffa500"
MPL_GRID    = "#30363d"


# ── HELPER: matplotlib figură → bytes PNG ─────────────────────────────────────
def fig_to_bytes(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


# ── HELPER: bytes PNG → ReportLab Image (lățime fixă, înălțime proporțională) ─
def bytes_to_rl_image(buf, width_cm=17.0):
    from PIL import Image as PILImage
    buf.seek(0)
    pil = PILImage.open(buf)
    w_px, h_px = pil.size
    aspect = h_px / w_px
    w_pt = width_cm * cm
    h_pt = w_pt * aspect
    buf.seek(0)
    return RLImage(buf, width=w_pt, height=h_pt)


# ── STILURI REPORTLAB ──────────────────────────────────────────────────────────
def make_styles():
    base = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TradingTitle",
        parent=base["Title"],
        fontSize=26,
        textColor=GREEN,
        spaceAfter=4,
        spaceBefore=0,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "TradingSubtitle",
        parent=base["Normal"],
        fontSize=11,
        textColor=TEXT_MUTED,
        spaceAfter=16,
        alignment=TA_CENTER,
        fontName="Helvetica",
    )
    h1_style = ParagraphStyle(
        "H1",
        parent=base["Heading1"],
        fontSize=16,
        textColor=GREEN,
        spaceBefore=18,
        spaceAfter=6,
        fontName="Helvetica-Bold",
        borderPad=0,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=base["Heading2"],
        fontSize=13,
        textColor=TEXT_MAIN,
        spaceBefore=14,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    normal_style = ParagraphStyle(
        "Normal2",
        parent=base["Normal"],
        fontSize=9,
        textColor=TEXT_MAIN,
        fontName="Helvetica",
        spaceAfter=2,
    )
    muted_style = ParagraphStyle(
        "Muted",
        parent=base["Normal"],
        fontSize=8,
        textColor=TEXT_MUTED,
        fontName="Helvetica",
    )
    label_style = ParagraphStyle(
        "Label",
        parent=base["Normal"],
        fontSize=8,
        textColor=TEXT_MUTED,
        fontName="Helvetica",
        spaceAfter=1,
    )
    value_green = ParagraphStyle(
        "ValGreen",
        parent=base["Normal"],
        fontSize=18,
        textColor=GREEN,
        fontName="Helvetica-Bold",
    )
    value_red = ParagraphStyle(
        "ValRed",
        parent=base["Normal"],
        fontSize=18,
        textColor=RED,
        fontName="Helvetica-Bold",
    )
    value_white = ParagraphStyle(
        "ValWhite",
        parent=base["Normal"],
        fontSize=18,
        textColor=TEXT_MAIN,
        fontName="Helvetica-Bold",
    )
    value_blue = ParagraphStyle(
        "ValBlue",
        parent=base["Normal"],
        fontSize=18,
        textColor=BLUE,
        fontName="Helvetica-Bold",
    )
    return dict(
        title=title_style, subtitle=subtitle_style,
        h1=h1_style, h2=h2_style,
        normal=normal_style, muted=muted_style,
        label=label_style,
        val_green=value_green, val_red=value_red,
        val_white=value_white, val_blue=value_blue,
    )


# ── HELPER: tabel KPI 3-pe-rând ────────────────────────────────────────────────
def kpi_table(items, styles):
    """
    items = [(label, value, color_hex_str), ...]
    Returnează un Table ReportLab cu carduri dark.
    """
    cell_w = 5.5 * cm
    col_widths = [cell_w] * 3

    rows = []
    for i in range(0, len(items), 3):
        chunk = items[i:i+3]
        while len(chunk) < 3:
            chunk.append(("", "", "#161b22"))
        row = []
        for (lbl, val, col) in chunk:
            cell_content = [
                Paragraph(lbl.upper(), styles["label"]),
                Paragraph(str(val),
                          ParagraphStyle("kv", fontSize=16, textColor=HexColor(col),
                                         fontName="Helvetica-Bold", spaceAfter=0)),
            ]
            row.append(cell_content)
        rows.append(row)

    tbl = Table(rows, colWidths=col_widths, hAlign="LEFT")
    ts = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), BG_CARD),
        ("BOX",         (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",   (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1),  8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",(0, 0), (-1, -1), 10),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), 6),
    ])
    tbl.setStyle(ts)
    return tbl


# ── HELPER: tabel date pandas → ReportLab ─────────────────────────────────────
def df_to_rl_table(df_in, max_rows=30, col_widths=None, styles=None):
    df_in = df_in.head(max_rows)
    data = [list(df_in.columns)] + df_in.values.tolist()
    data = [[str(c)[:40] for c in row] for row in data]

    if col_widths is None:
        n = len(df_in.columns)
        total = 17.0 * cm
        col_widths = [total / n] * n

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    ts = TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0),  BG_CARD2),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  GREEN),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0),  8),
        ("BOTTOMPADDING",(0, 0), (-1, 0),  6),
        ("TOPPADDING",   (0, 0), (-1, 0),  6),
        # Body
        ("BACKGROUND",   (0, 1), (-1, -1), BG_CARD),
        ("TEXTCOLOR",    (0, 1), (-1, -1), TEXT_MAIN),
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
        ("TOPPADDING",   (0, 1), (-1, -1), 4),
        # Grid
        ("GRID",         (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS",(0,1), (-1,-1),  [BG_CARD, HexColor("#1a1c24")]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])
    tbl.setStyle(ts)
    return tbl


# ═══════════════════════════════════════════════════════════════════════════════
# ── GRAFICE MATPLOTLIB ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def setup_ax(ax, title=""):
    ax.set_facecolor(MPL_BG)
    ax.tick_params(colors=MPL_FG, labelsize=7)
    ax.spines[:].set_color(MPL_GRID)
    ax.xaxis.label.set_color(MPL_FG)
    ax.yaxis.label.set_color(MPL_FG)
    ax.title.set_color(MPL_FG)
    if title:
        ax.set_title(title, fontsize=9, pad=6)
    ax.grid(axis="y", color=MPL_GRID, linewidth=0.5, alpha=0.6)


def chart_equity_curve(df):
    df_s = df.sort_values("Entry Time").copy()
    df_s["cum"] = df_s["Net P&L USD"].cumsum()

    fig, ax = plt.subplots(figsize=(14, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Equity Curve")

    x = range(len(df_s))
    ax.plot(df_s["Entry Time"], df_s["cum"], color=MPL_GREEN, linewidth=1.8)
    ax.fill_between(df_s["Entry Time"], df_s["cum"], 0,
                    where=df_s["cum"] >= 0, alpha=0.15, color=MPL_GREEN)
    ax.fill_between(df_s["Entry Time"], df_s["cum"], 0,
                    where=df_s["cum"] < 0,  alpha=0.15, color=MPL_RED)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_xlabel("Data", fontsize=8)
    ax.set_ylabel("P&L cumulat ($)", fontsize=8)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_pnl_by_hour(df):
    hour_stats = df.groupby("Hour").agg(
        Profit=("Net P&L USD", "sum"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
    ).reset_index()
    hour_stats["Label"] = hour_stats["Hour"].apply(lambda h: f"{int(h):02d}:00")
    colors_bar = [MPL_GREEN if v >= 0 else MPL_RED for v in hour_stats["Profit"]]

    fig, ax = plt.subplots(figsize=(14, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Profit Net pe Ore (Intrare)")
    bars = ax.bar(hour_stats["Label"], hour_stats["Profit"], color=colors_bar, width=0.6)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_xlabel("Ora", fontsize=8)
    ax.set_ylabel("Profit ($)", fontsize=8)
    for bar, wr in zip(bars, hour_stats["WR"]):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + (abs(h)*0.03 if h >= 0 else -abs(h)*0.06),
                f"{wr:.0f}%", ha="center", va="bottom" if h >= 0 else "top",
                fontsize=6, color=MPL_FG)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_pnl_by_day(df):
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    day_stats = df.groupby("Day").agg(
        Profit=("Net P&L USD", "sum"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
    ).reindex(order).dropna()
    labels = [d[:3] for d in day_stats.index]
    colors_bar = [MPL_GREEN if v >= 0 else MPL_RED for v in day_stats["Profit"]]

    fig, ax = plt.subplots(figsize=(7, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Profit Net pe Zile")
    bars = ax.bar(labels, day_stats["Profit"], color=colors_bar, width=0.5)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Profit ($)", fontsize=8)
    for bar, wr in zip(bars, day_stats["WR"]):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + (abs(h)*0.04 if h >= 0 else -abs(h)*0.08),
                f"{wr:.0f}%", ha="center", va="bottom" if h >= 0 else "top",
                fontsize=7, color=MPL_FG)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_pnl_by_month(df):
    m_order = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]
    ms = df.groupby("Month").agg(
        Profit=("Net P&L USD", "sum"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
    ).reset_index()
    ms["Month"] = pd.Categorical(ms["Month"], categories=m_order, ordered=True)
    ms = ms.sort_values("Month")
    colors_bar = [MPL_GREEN if v >= 0 else MPL_RED for v in ms["Profit"]]

    fig, ax = plt.subplots(figsize=(14, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Profit Net pe Luni")
    bars = ax.bar([m[:3] for m in ms["Month"]], ms["Profit"], color=colors_bar, width=0.6)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Profit ($)", fontsize=8)
    for bar, wr in zip(bars, ms["WR"]):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, h + (abs(h)*0.03 if h >= 0 else -abs(h)*0.07),
                f"{wr:.0f}%", ha="center", va="bottom" if h >= 0 else "top",
                fontsize=6.5, color=MPL_FG)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_win_loss_pie(wins, losses):
    fig, ax = plt.subplots(figsize=(4.5, 4.5), facecolor=MPL_BG)
    ax.set_facecolor(MPL_BG)
    sizes = [wins, losses]
    clrs  = [MPL_GREEN, MPL_RED]
    labels = [f"Win\n{wins}", f"Loss\n{losses}"]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=clrs, autopct="%1.1f%%",
        startangle=90, pctdistance=0.75,
        wedgeprops=dict(linewidth=2, edgecolor=MPL_BG)
    )
    for t in texts: t.set_color(MPL_FG); t.set_fontsize(9)
    for at in autotexts: at.set_color("white"); at.set_fontsize(8); at.set_fontweight("bold")
    ax.set_title("Win vs Loss", color=MPL_FG, fontsize=10, pad=8)
    fig.tight_layout(pad=0.3)
    return fig_to_bytes(fig)


def chart_direction(df):
    dirs = df.groupby("Direction").agg(
        Profit=("Net P&L USD", "sum"),
        Count=("Result", "count"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
    ).reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5), facecolor=MPL_BG)
    for ax in axes: ax.set_facecolor(MPL_BG); ax.spines[:].set_color(MPL_GRID); ax.tick_params(colors=MPL_FG)

    colors_dir = [MPL_GREEN if v >= 0 else MPL_RED for v in dirs["Profit"]]
    axes[0].bar(dirs["Direction"], dirs["Profit"], color=colors_dir, width=0.4)
    axes[0].axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    axes[0].set_title("Profit Long vs Short", color=MPL_FG, fontsize=9)
    axes[0].set_ylabel("Profit ($)", fontsize=8, color=MPL_FG)
    axes[0].grid(axis="y", color=MPL_GRID, alpha=0.5, linewidth=0.5)

    axes[1].bar(dirs["Direction"], dirs["WR"],
                color=[MPL_BLUE, MPL_ORANGE][:len(dirs)], width=0.4)
    axes[1].set_title("Win Rate Long vs Short (%)", color=MPL_FG, fontsize=9)
    axes[1].set_ylabel("Win Rate (%)", fontsize=8, color=MPL_FG)
    axes[1].grid(axis="y", color=MPL_GRID, alpha=0.5, linewidth=0.5)
    for ax in axes:
        ax.xaxis.label.set_color(MPL_FG)
        ax.yaxis.label.set_color(MPL_FG)

    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_signal(df):
    if "Signal" not in df.columns:
        return None
    df_s = df.dropna(subset=["Signal"])
    df_s = df_s[df_s["Signal"].astype(str).str.strip().str.upper() != "N/A"]
    df_s = df_s[df_s["Signal"].astype(str).str.strip() != ""]
    if df_s.empty:
        return None

    sig = df_s.groupby("Signal").agg(
        Profit=("Net P&L USD", "sum"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100),
        Total=("Result", "count")
    ).reset_index().sort_values("Profit", ascending=False)

    colors_bar = [MPL_GREEN if v >= 0 else MPL_RED for v in sig["Profit"]]
    fig, ax = plt.subplots(figsize=(14, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Profit per Signal / Setup")
    bars = ax.bar(sig["Signal"].astype(str), sig["Profit"], color=colors_bar, width=0.6)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Profit ($)", fontsize=8)
    for bar, wr, tot in zip(bars, sig["WR"], sig["Total"]):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2,
                h + (abs(h)*0.04 if h >= 0 else -abs(h)*0.08),
                f"{wr:.0f}% ({int(tot)})", ha="center",
                va="bottom" if h >= 0 else "top", fontsize=6.5, color=MPL_FG)
    plt.xticks(rotation=30, ha="right", fontsize=7)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_drawdown(df):
    df_s = df.sort_values("Entry Time").copy()
    df_s["cum"] = df_s["Net P&L USD"].cumsum()
    df_s["peak"] = df_s["cum"].cummax()
    df_s["dd"] = df_s["cum"] - df_s["peak"]

    fig, ax = plt.subplots(figsize=(14, 3), facecolor=MPL_BG)
    setup_ax(ax, "Drawdown Cumulat")
    ax.fill_between(df_s["Entry Time"], df_s["dd"], 0, color=MPL_RED, alpha=0.4)
    ax.plot(df_s["Entry Time"], df_s["dd"], color=MPL_RED, linewidth=1.2)
    ax.axhline(0, color=MPL_GRID, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Drawdown ($)", fontsize=8)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_pnl_distribution(df):
    wins_v  = df[df["Net P&L USD"] > 0]["Net P&L USD"]
    loss_v  = df[df["Net P&L USD"] < 0]["Net P&L USD"]

    fig, ax = plt.subplots(figsize=(10, 3.5), facecolor=MPL_BG)
    setup_ax(ax, "Distribuție P&L per Trade")
    if not wins_v.empty:
        ax.hist(wins_v, bins=25, color=MPL_GREEN, alpha=0.75, label="Win")
    if not loss_v.empty:
        ax.hist(loss_v, bins=25, color=MPL_RED,   alpha=0.75, label="Loss")
    ax.axvline(0, color="white", linewidth=0.8, linestyle="--")
    ax.set_xlabel("P&L per Trade ($)", fontsize=8)
    ax.set_ylabel("Frecvență", fontsize=8)
    ax.legend(facecolor=MPL_BG, edgecolor=MPL_GRID, labelcolor=MPL_FG, fontsize=8)
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


def chart_risk_scenarios(df, account_size=25000, daily_dd_pct=5, max_dd_pct=10,
                          max_trades_per_day=3):
    """Bar chart cu scenarii de risc"""
    risk_pcts = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    daily_dd_usd   = account_size * daily_dd_pct / 100
    max_dd_usd     = account_size * max_dd_pct / 100

    # Max loss streak
    results = df.sort_values("Entry Time")["Result"].tolist()
    max_ls = 0; cur = 0
    for r in results:
        if r == "Loss": cur += 1; max_ls = max(max_ls, cur)
        else: cur = 0

    labels, daily_risks, streak_losses = [], [], []
    for rp in risk_pcts:
        risk_usd = account_size * rp / 100
        labels.append(f"{rp}%")
        daily_risks.append(risk_usd * max_trades_per_day)
        streak_losses.append(risk_usd * max_ls)

    x = np.arange(len(labels))
    w = 0.35
    fig, ax = plt.subplots(figsize=(10, 4), facecolor=MPL_BG)
    setup_ax(ax, f"Risc per Trade — Impact Daily DD vs Worst Streak ({max_ls}L)")

    bars1 = ax.bar(x - w/2, daily_risks,  w, label=f"Risc/zi ({max_trades_per_day} trades)",
                   color=MPL_ORANGE, alpha=0.85)
    bars2 = ax.bar(x + w/2, streak_losses, w, label=f"Worst streak ({max_ls}L) total",
                   color=MPL_RED, alpha=0.85)

    ax.axhline(daily_dd_usd, color=MPL_ORANGE, linewidth=1.5, linestyle="--",
               label=f"Daily DD limit ${daily_dd_usd:,.0f}")
    ax.axhline(max_dd_usd,   color=MPL_RED,    linewidth=1.5, linestyle=":",
               label=f"Overall DD limit ${max_dd_usd:,.0f}")

    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("Pierdere ($)", fontsize=8)
    ax.set_xlabel("Risc % per Trade", fontsize=8)
    ax.legend(facecolor=MPL_BG, edgecolor=MPL_GRID, labelcolor=MPL_FG, fontsize=7,
              loc="upper left")
    fig.tight_layout(pad=0.5)
    return fig_to_bytes(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# ── FUNCȚIA PRINCIPALĂ ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def generate_full_pdf_report(df: pd.DataFrame) -> bytes:
    """
    Primește DataFrame-ul filtrat (același ca df_final din app.py)
    Returnează bytes PDF complet.
    """
    buf = io.BytesIO()
    styles = make_styles()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
        title="Raport Trading — TradingView Payout & Strategy",
        author="LvlUp Trading",
    )

    story = []

    # ── COVER PAGE ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("📊 RAPORT TRADING", styles["title"]))
    story.append(Paragraph("TradingView Payout &amp; Strategy Analysis", styles["subtitle"]))

    if not df.empty:
        d_start = df["Entry Time"].min().strftime("%d %b %Y")
        d_end   = df["Entry Time"].max().strftime("%d %b %Y")
        story.append(Paragraph(f"Perioadă: {d_start} — {d_end}", styles["subtitle"]))

    story.append(HRFlowable(width="100%", thickness=1, color=GREEN, spaceAfter=14))
    story.append(Spacer(1, 0.5*cm))

    # ── SECȚIUNEA 1: STATISTICI GENERALE ──────────────────────────────────────
    story.append(Paragraph("1. STATISTICI GENERALE", styles["h1"]))

    if df.empty:
        story.append(Paragraph("Nu există date.", styles["normal"]))
    else:
        wins   = df[df["Net P&L USD"] > 0]
        losses = df[df["Net P&L USD"] < 0]
        total  = len(df)
        wr     = len(wins) / total * 100 if total > 0 else 0

        avg_win  = wins["Net P&L USD"].mean()  if not wins.empty  else 0
        avg_loss = abs(losses["Net P&L USD"].mean()) if not losses.empty else 0
        rr       = avg_win / avg_loss if avg_loss > 0 else 0
        pf       = wins["Net P&L USD"].sum() / abs(losses["Net P&L USD"].sum()) \
                   if not losses.empty and losses["Net P&L USD"].sum() != 0 else 0

        df_dd = df.sort_values("Entry Time").copy()
        df_dd["cum"]  = df_dd["Net P&L USD"].cumsum()
        df_dd["peak"] = df_dd["cum"].cummax()
        df_dd["dd"]   = df_dd["cum"] - df_dd["peak"]
        max_dd = df_dd["dd"].min()

        results_list = df.sort_values("Entry Time")["Result"].tolist()
        max_ws = max_ls = cw = cl = 0
        for r in results_list:
            if r == "Win":  cw += 1; cl = 0; max_ws = max(max_ws, cw)
            else:           cl += 1; cw = 0; max_ls = max(max_ls, cl)

        kpi_items = [
            ("Profit Net Total",  f"${df['Net P&L USD'].sum():,.2f}", "#00cf8d"),
            ("Win Rate",          f"{wr:.1f}%", "#00cf8d"),
            ("Total Trades",      f"{total}  ({len(wins)}W / {len(losses)}L)", "#e6edf3"),
            ("Profit Factor",     f"{pf:.2f}", "#4a9eff"),
            ("Risk/Reward Ratio", f"{rr:.2f}R", "#4a9eff"),
            ("Max Drawdown",      f"${max_dd:,.2f}", "#ff4b4b"),
            ("Avg Win",           f"${avg_win:,.2f}", "#00cf8d"),
            ("Avg Loss",          f"${avg_loss:,.2f}", "#ff4b4b"),
            ("Best Trade",        f"${df['Net P&L USD'].max():,.2f}", "#00cf8d"),
            ("Worst Trade",       f"${df['Net P&L USD'].min():,.2f}", "#ff4b4b"),
            ("Max Win Streak",    f"{max_ws} wins",   "#00cf8d"),
            ("Max Loss Streak",   f"{max_ls} losses", "#ff4b4b"),
        ]
        story.append(kpi_table(kpi_items, styles))
        story.append(Spacer(1, 0.4*cm))

    # ── SECȚIUNEA 2: GRAFICE ───────────────────────────────────────────────────
    story.append(Paragraph("2. GRAFICE PERFORMANȚĂ", styles["h1"]))

    # Equity Curve
    story.append(Paragraph("Equity Curve", styles["h2"]))
    eq_buf = chart_equity_curve(df)
    story.append(bytes_to_rl_image(eq_buf, 17.0))
    story.append(Spacer(1, 0.3*cm))

    # Drawdown
    story.append(Paragraph("Drawdown Cumulat", styles["h2"]))
    dd_buf = chart_drawdown(df)
    story.append(bytes_to_rl_image(dd_buf, 17.0))
    story.append(Spacer(1, 0.3*cm))

    # Pie + Direction side by side
    story.append(Paragraph("Distribuție Win/Loss &amp; Direcție", styles["h2"]))
    pie_buf = chart_win_loss_pie(len(wins), len(losses))
    dir_buf = chart_direction(df)
    side_data = [[bytes_to_rl_image(pie_buf, 7.5),
                  bytes_to_rl_image(dir_buf, 8.5)]]
    side_tbl = Table(side_data, colWidths=[8.0*cm, 9.2*cm])
    side_tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(side_tbl)
    story.append(Spacer(1, 0.3*cm))

    # Profit pe Ore
    story.append(Paragraph("Profit pe Ore (Intrare)", styles["h2"]))
    hr_buf = chart_pnl_by_hour(df)
    story.append(bytes_to_rl_image(hr_buf, 17.0))
    story.append(Spacer(1, 0.3*cm))

    # Profit pe Zile + Luni
    story.append(Paragraph("Profit pe Zile &amp; Luni", styles["h2"]))
    day_buf  = chart_pnl_by_day(df)
    mon_buf  = chart_pnl_by_month(df)
    dm_data  = [[bytes_to_rl_image(day_buf, 7.5),
                 bytes_to_rl_image(mon_buf, 9.2)]]
    dm_tbl   = Table(dm_data, colWidths=[8.0*cm, 9.2*cm])
    dm_tbl.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(dm_tbl)
    story.append(Spacer(1, 0.3*cm))

    # Distribuție P&L
    story.append(Paragraph("Distribuție P&amp;L per Trade", styles["h2"]))
    dist_buf = chart_pnl_distribution(df)
    story.append(bytes_to_rl_image(dist_buf, 17.0))
    story.append(Spacer(1, 0.3*cm))

    # Signal chart (dacă există)
    sig_buf = chart_signal(df)
    if sig_buf:
        story.append(Paragraph("Profit per Signal / Setup", styles["h2"]))
        story.append(bytes_to_rl_image(sig_buf, 17.0))
        story.append(Spacer(1, 0.3*cm))

    # ── SECȚIUNEA 3: RISK MANAGEMENT ──────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("3. RISK MANAGEMENT", styles["h1"]))

    if not df.empty:
        wins_rm   = df[df["Result"] == "Win"]
        losses_rm = df[df["Result"] == "Loss"]
        avg_win_rm  = wins_rm["Net P&L USD"].mean()   if not wins_rm.empty   else 0
        avg_loss_rm = abs(losses_rm["Net P&L USD"].mean()) if not losses_rm.empty else 0
        wr_rm     = len(wins_rm) / len(df) if len(df) > 0 else 0
        rr_rm     = avg_win_rm / avg_loss_rm if avg_loss_rm > 0 else 1
        kelly     = max(0, wr_rm - (1-wr_rm)/rr_rm) if rr_rm > 0 else 0
        half_kelly_pct = kelly / 2 * 100
        recommended_pct = min(half_kelly_pct, 1.0)

        # Setări cont implicite
        account_size     = 25000
        daily_dd_pct     = 5
        max_dd_pct       = 10
        max_trades_per_day = 3

        story.append(Paragraph("3.1 Kelly Criterion &amp; Risc Recomandat", styles["h2"]))
        kelly_items = [
            ("Win Rate Real",        f"{wr_rm*100:.1f}%",        "#4a9eff"),
            ("RR Ratio Real",        f"{rr_rm:.2f}",             "#4a9eff"),
            ("Half Kelly (teoretic)", f"{half_kelly_pct:.2f}%",  "#8b949e"),
            ("Recomandat Funded",    f"{recommended_pct:.1f}%",  "#00cf8d"),
            ("Conservator",          "0.5%",                     "#4a9eff"),
            ("Avg Win / Avg Loss",   f"${avg_win_rm:,.2f} / ${avg_loss_rm:,.2f}", "#e6edf3"),
        ]
        story.append(kpi_table(kelly_items, styles))
        story.append(Spacer(1, 0.4*cm))

        # Grafic scenarii risc
        story.append(Paragraph("3.2 Scenarii Risc — Impact pe Drawdown", styles["h2"]))
        risk_buf = chart_risk_scenarios(df, account_size, daily_dd_pct, max_dd_pct, max_trades_per_day)
        story.append(bytes_to_rl_image(risk_buf, 17.0))
        story.append(Spacer(1, 0.4*cm))

        # Tabel scenarii
        story.append(Paragraph("3.3 Tabel Scenarii Fixed Fractional", styles["h2"]))
        risk_scenarios = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
        daily_dd_usd = account_size * daily_dd_pct / 100
        max_dd_usd   = account_size * max_dd_pct   / 100

        results_list_rm = df.sort_values("Entry Time")["Result"].tolist()
        max_ls_rm = 0; cur_rm = 0
        for r in results_list_rm:
            if r == "Loss": cur_rm += 1; max_ls_rm = max(max_ls_rm, cur_rm)
            else: cur_rm = 0

        scen_rows = [["Risc %", "$/Trade", f"L→Daily DD({daily_dd_pct}%)",
                       f"L→Overall DD({max_dd_pct}%)", "Risc/zi", "Status"]]
        for rp in risk_scenarios:
            risk_usd   = account_size * rp / 100
            l_daily    = int(daily_dd_usd / risk_usd) if risk_usd > 0 else 0
            l_overall  = int(max_dd_usd   / risk_usd) if risk_usd > 0 else 0
            daily_risk = risk_usd * max_trades_per_day
            ok_d       = "✓" if daily_risk <= daily_dd_usd else "✗"
            status     = "Recomandat" if rp == 1.0 else ("Conservator" if rp == 0.5 else
                         ("Acceptabil" if rp <= 1.0 else "Agresiv"))
            scen_rows.append([
                f"{rp}%", f"${risk_usd:,.0f}",
                f"{l_daily}L {ok_d}", f"{l_overall}L",
                f"${daily_risk:,.0f}", status
            ])

        scen_tbl = Table(scen_rows,
                         colWidths=[2.2*cm, 2.5*cm, 3.2*cm, 3.2*cm, 2.5*cm, 3.4*cm])
        scen_style = TableStyle([
            ("BACKGROUND",  (0,0), (-1,0), BG_CARD2),
            ("TEXTCOLOR",   (0,0), (-1,0), GREEN),
            ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,0), 8),
            ("BACKGROUND",  (0,1), (-1,-1), BG_CARD),
            ("TEXTCOLOR",   (0,1), (-1,-1), TEXT_MAIN),
            ("FONTNAME",    (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",    (0,1), (-1,-1), 8),
            ("GRID",        (0,0), (-1,-1), 0.4, BORDER),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
            ("RIGHTPADDING",(0,0), (-1,-1), 5),
            # Highlight recommended row (index 2 = 1.0%)
            ("BACKGROUND",  (0,2), (-1,2), HexColor("#0d2111")),
            ("TEXTCOLOR",   (0,2), (-1,2), GREEN),
        ])
        scen_tbl.setStyle(scen_style)
        story.append(scen_tbl)
        story.append(Spacer(1, 0.4*cm))

    # ── SECȚIUNEA 4: TABELE DETALIATE ─────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("4. TABELE DETALIATE", styles["h1"]))

    # Top 10 Ore Intrare
    story.append(Paragraph("4.1 Top Ore de Intrare (Win Rate)", styles["h2"]))
    hour_stats = df.groupby("Hour").agg(
        Profit=("Net P&L USD", "sum"),
        W=("Result", lambda x: (x == "Win").sum()),
        L=("Result", lambda x: (x == "Loss").sum()),
        Total=("Result", "count"),
        WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
    ).reset_index()
    hour_stats["Ora"] = hour_stats["Hour"].apply(lambda h: f"{int(h):02d}:00")
    hour_stats["Win Rate"] = hour_stats["WR"].apply(lambda x: f"{x:.1f}%")
    hour_stats["Profit"] = hour_stats["Profit"].apply(lambda x: f"${x:,.2f}")
    hour_stats["Scor"] = hour_stats.apply(lambda r: f"{int(r.W)}W / {int(r.L)}L", axis=1)
    top_hours = hour_stats.sort_values("WR", ascending=False).head(10)[["Ora","Win Rate","Profit","Scor","Total"]]
    story.append(df_to_rl_table(top_hours, max_rows=10,
                                col_widths=[3.0*cm, 3.5*cm, 4.0*cm, 4.0*cm, 2.5*cm],
                                styles=styles))
    story.append(Spacer(1, 0.4*cm))

    # Top 10 Minute Intrare
    if "Minute" in df.columns:
        story.append(Paragraph("4.2 Top Minute de Intrare (Win Rate)", styles["h2"]))
        min_stats = df.groupby("Minute").agg(
            Profit=("Net P&L USD", "sum"),
            W=("Result", lambda x: (x == "Win").sum()),
            L=("Result", lambda x: (x == "Loss").sum()),
            Total=("Result", "count"),
            WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100)
        ).reset_index()
        min_stats["Minut"] = min_stats["Minute"].apply(lambda m: f"xx:{int(m):02d}")
        min_stats["Win Rate"] = min_stats["WR"].apply(lambda x: f"{x:.1f}%")
        min_stats["Profit"] = min_stats["Profit"].apply(lambda x: f"${x:,.2f}")
        min_stats["Scor"] = min_stats.apply(lambda r: f"{int(r.W)}W / {int(r.L)}L", axis=1)
        top_mins = min_stats.sort_values("WR", ascending=False).head(10)[["Minut","Win Rate","Profit","Scor","Total"]]
        story.append(df_to_rl_table(top_mins, max_rows=10,
                                    col_widths=[3.0*cm, 3.5*cm, 4.0*cm, 4.0*cm, 2.5*cm],
                                    styles=styles))
        story.append(Spacer(1, 0.4*cm))

    # Top Signal
    if "Signal" in df.columns:
        df_sig2 = df.dropna(subset=["Signal"])
        df_sig2 = df_sig2[df_sig2["Signal"].astype(str).str.strip().str.upper() != "N/A"]
        df_sig2 = df_sig2[df_sig2["Signal"].astype(str).str.strip() != ""]
        if not df_sig2.empty:
            story.append(Paragraph("4.3 Performanță pe Signal / Setup", styles["h2"]))
            sig_stats = df_sig2.groupby("Signal").agg(
                Profit=("Net P&L USD", "sum"),
                W=("Result", lambda x: (x == "Win").sum()),
                L=("Result", lambda x: (x == "Loss").sum()),
                Total=("Result", "count"),
                WR=("Result", lambda x: (x == "Win").sum() / len(x) * 100),
                AvgW=("Net P&L USD", lambda x: x[x > 0].mean() if (x > 0).any() else 0),
                AvgL=("Net P&L USD", lambda x: abs(x[x < 0].mean()) if (x < 0).any() else 0),
            ).reset_index()
            sig_stats["RR"] = sig_stats.apply(
                lambda r: r["AvgW"]/r["AvgL"] if r["AvgL"] > 0 else r["AvgW"], axis=1)
            sig_stats["WR_fmt"] = sig_stats["WR"].apply(lambda x: f"{x:.1f}%")
            sig_stats["Profit_fmt"] = sig_stats["Profit"].apply(lambda x: f"${x:,.2f}")
            sig_stats["RR_fmt"] = sig_stats["RR"].apply(lambda x: f"{x:.2f}")
            sig_stats["Scor"] = sig_stats.apply(lambda r: f"{int(r.W)}W/{int(r.L)}L", axis=1)
            display_sig = sig_stats[["Signal","Total","WR_fmt","Profit_fmt","RR_fmt","Scor"]].copy()
            display_sig.columns = ["Signal","Total","Win Rate","Profit","R:R","Scor"]
            story.append(df_to_rl_table(display_sig.sort_values("Profit", ascending=False),
                                        max_rows=20,
                                        col_widths=[4.0*cm, 2.0*cm, 3.0*cm, 3.5*cm, 2.5*cm, 2.0*cm],
                                        styles=styles))
            story.append(Spacer(1, 0.4*cm))

    # Jurnal Trades (ultimele 50)
    story.append(Paragraph("4.4 Jurnal Trade-uri (ultimele 50)", styles["h2"]))
    cols_j = [c for c in ["Entry Time","Exit Time","Direction","Signal","Net P&L USD","Result","Duration_Min"]
              if c in df.columns]
    df_j = df[cols_j].sort_values("Entry Time", ascending=False).head(50).copy()
    if "Entry Time" in df_j.columns:
        df_j["Entry Time"] = df_j["Entry Time"].dt.strftime("%d.%m %H:%M")
    if "Exit Time" in df_j.columns:
        df_j["Exit Time"] = df_j["Exit Time"].dt.strftime("%d.%m %H:%M")
    if "Net P&L USD" in df_j.columns:
        df_j["Net P&L USD"] = df_j["Net P&L USD"].apply(lambda x: f"${x:,.2f}")
    if "Duration_Min" in df_j.columns:
        df_j["Duration_Min"] = df_j["Duration_Min"].apply(
            lambda x: f"{int(x//60)}h {int(x%60)}m" if pd.notna(x) and x > 0 else "—")

    n_cols_j = len(df_j.columns)
    total_w = 17.0 * cm
    col_ws_j = {
        "Entry Time": 2.5*cm, "Exit Time": 2.5*cm, "Direction": 2.0*cm,
        "Signal": 3.0*cm, "Net P&L USD": 2.8*cm, "Result": 1.8*cm, "Duration_Min": 2.4*cm
    }
    cw_j = [col_ws_j.get(c, total_w/n_cols_j) for c in df_j.columns]
    story.append(df_to_rl_table(df_j, max_rows=50, col_widths=cw_j, styles=styles))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Spacer(1, 2*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "Raport generat de <b>TradingView Payout &amp; Strategy</b> — LvlUp Trading",
        ParagraphStyle("footer", fontSize=10, textColor=TEXT_MUTED,
                    alignment=TA_CENTER, fontName="Helvetica")))
    story.append(Paragraph(
        "Datele sunt furnizate exclusiv în scop analitic. Nu reprezintă sfaturi financiare.",
        ParagraphStyle("footer2", fontSize=8, textColor=TEXT_MUTED,
                    alignment=TA_CENTER, fontName="Helvetica")))

    # ── BUILD ─────────────────────────────────────────────────────────────────
    def on_page(canvas, doc):
        """Background negru complet + footer pe fiecare pagină"""
        canvas.saveState()
        w, h = A4

        # ── Background negru pe toată pagina (desenat primul, sub orice altceva)
        canvas.setFillColor(BG_DARK)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)

        # ── Footer linie + text
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(1.5*cm, 1.2*cm, w - 1.5*cm, 1.2*cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(TEXT_MUTED)
        canvas.drawString(1.5*cm, 0.8*cm, "TradingView Payout & Strategy — LvlUp Trading")
        canvas.drawRightString(w - 1.5*cm, 0.8*cm, f"Pagina {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    buf.seek(0)
    return buf.read()
