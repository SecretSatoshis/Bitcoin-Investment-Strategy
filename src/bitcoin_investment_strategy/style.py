"""Secret Satoshis chart style: palette, bundled fonts, the dark theme and the branded frame."""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

BG, SURFACE, ALTERNATE, BORDER = "#08080c", "#0e0e16", "#13131d", "#2a2a42"
PRIMARY, SECONDARY = "#e4e4ef", "#9090a8"
ORANGE, CASH, GREEN, RED, BLUE = "#F7931A", "#B0A5D8", "#69C99C", "#F07D82", "#77A7E8"
HIGHLIGHT = "#211a12"

FONT_DIR = Path(__file__).parent / "assets/fonts"
MONO = font_manager.FontProperties(fname=FONT_DIR / "JetBrainsMono-400.ttf")
MONO_MEDIUM = font_manager.FontProperties(fname=FONT_DIR / "JetBrainsMono-600.ttf")
DISPLAY = font_manager.FontProperties(fname=FONT_DIR / "Syne-700.ttf")

HEADER_LABEL = "BITCOIN SAVINGS STRATEGY"


def apply_theme() -> None:
    """Register the bundled fonts and set the dark theme for every following figure."""
    for font_file in FONT_DIR.glob("*.ttf"):
        font_manager.fontManager.addfont(str(font_file))
    plt.rcParams.update({
        "figure.figsize": (14, 7.875), "figure.dpi": 110,
        "figure.facecolor": BG, "savefig.facecolor": BG,
        "axes.facecolor": BG, "axes.edgecolor": BORDER,
        "axes.labelcolor": SECONDARY, "axes.titlecolor": PRIMARY,
        "axes.grid": False, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.spines.bottom": False,
        "axes.titlesize": 11, "axes.titleweight": "normal", "axes.titlepad": 17,
        "axes.labelsize": 10, "font.size": 10,
        "font.family": MONO.get_name(), "text.color": PRIMARY,
        "xtick.color": SECONDARY, "ytick.color": SECONDARY,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "legend.frameon": True, "legend.framealpha": 1,
        "legend.facecolor": SURFACE, "legend.edgecolor": BORDER,
        "legend.labelcolor": PRIMARY, "legend.fontsize": 9,
        "figure.autolayout": False,
    })


def brand_chart(fig, title, *, subtitle=None, footer=None, label=HEADER_LABEL,
                top=0.75, bottom=0.16, left=0.085, right=0.955, hspace=None):
    """Frame an existing figure with the Secret Satoshis header, title and footer."""
    fig.set_facecolor(BG)
    fig.add_artist(Rectangle((0.045, 0.943), 0.006, 0.017,
                             transform=fig.transFigure, facecolor=ORANGE, edgecolor="none"))
    fig.text(0.061, 0.951, "SECRET SATOSHIS", color=PRIMARY,
             fontproperties=MONO_MEDIUM, fontsize=11, va="center")
    fig.text(0.955, 0.951, label, color=SECONDARY,
             fontproperties=MONO, fontsize=9, va="center", ha="right")
    fig.add_artist(Line2D([0.045, 0.955], [0.922, 0.922], transform=fig.transFigure,
                          color=BORDER, linewidth=0.8))
    fig.text(0.045, 0.869, title, color=PRIMARY,
             fontproperties=DISPLAY, fontsize=21, va="center")
    if subtitle:
        fig.text(0.045, 0.813, subtitle, color=SECONDARY,
                 fontproperties=MONO, fontsize=9, va="center")
    fig.add_artist(Line2D([0.045, 0.955], [0.783, 0.783], transform=fig.transFigure,
                          color=ORANGE, linewidth=1.1))
    fig.add_artist(Line2D([0.045, 0.955], [0.089, 0.089], transform=fig.transFigure,
                          color=BORDER, linewidth=0.8))
    fig.text(0.045, 0.049, footer or "Source: Secret Satoshis savings model · Nominal USD",
             color=SECONDARY, fontproperties=MONO, fontsize=7.2,
             va="center", ha="left")
    fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom, hspace=hspace)
    for ax in fig.axes:
        ax.set_facecolor(BG)
        ax.tick_params(axis="both", which="both", colors=SECONDARY, length=0, pad=8)
        for tick in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
            tick.set_fontproperties(MONO)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(False, axis="x")
        ax.grid(True, axis="y", color=BORDER, linewidth=0.65)
    return fig


def brand_table(styler):
    """Style a pandas table without touching its cells, order or formatting."""
    return styler.set_table_styles([
        {"selector": "", "props": [("border-collapse", "collapse"),
                                   ("background-color", BG),
                                   ("color", PRIMARY),
                                   ("font-family", "'JetBrains Mono', monospace"),
                                   ("font-size", "12px"),
                                   ("min-width", "680px")]},
        {"selector": "thead th", "props": [("background-color", SURFACE),
                                           ("color", ORANGE),
                                           ("border-top", f"2px solid {ORANGE}"),
                                           ("border-bottom", f"1px solid {BORDER}"),
                                           ("padding", "12px 16px"),
                                           ("text-align", "left")]},
        {"selector": "tbody td", "props": [("background-color", BG),
                                           ("color", PRIMARY),
                                           ("border-bottom", f"1px solid {BORDER}"),
                                           ("padding", "9px 16px"),
                                           ("text-align", "left")]},
        {"selector": "tbody tr:nth-child(even) td", "props": [("background-color", SURFACE)]},
        {"selector": "tbody tr:hover td", "props": [("background-color", HIGHLIGHT)]},
    ], overwrite=True)
