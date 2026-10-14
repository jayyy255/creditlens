"""Static figures from aggregate-only investigation results (requires matplotlib)."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "docs/eda"


def main():
    app = json.loads((ROOT / "results/applications.json").read_text())
    names = ["bureau", "bureau_balance", "previous_application", "POS_CASH_balance", "installments_payments", "credit_card_balance"]
    histories = {name: json.loads((ROOT / f"results/{name}.json").read_text()) for name in names}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#cdd8cb", "axes.labelcolor": "#465c4b",
                         "text.color": "#243d30", "xtick.color": "#647463", "ytick.color": "#647463"})
    fig, axes = plt.subplots(2, 2, figsize=(15, 11), facecolor="#f7f9f4")
    fig.subplots_adjust(top=.86, hspace=.5, wspace=.43, bottom=.1, left=.17, right=.96)
    fig.suptitle("CreditLens: actual-data investigation", fontsize=23, fontweight="bold", x=.17, ha="left", y=.96)
    fig.text(.17, .91, f"{app['integrity']['exploration_rows']:,} exploration applicants · final holdout excluded from target analysis", color="#6b7e68")
    green, light, amber = "#2a7957", "#b8ce98", "#bf8a3e"
    missing = sorted(app["missing"], key=lambda r: -r["missing_rate"])
    chosen = missing[:5] + [next(r for r in missing if r["column"] == name) for name in ["EXT_SOURCE_1", "OCCUPATION_TYPE", "EXT_SOURCE_3", "EXT_SOURCE_2"]]
    ax = axes[0, 0]
    ax.barh([r["column"] for r in chosen][::-1], [r["missing_rate"] for r in chosen][::-1], color=green)
    ax.set_title("Missingness is not a sufficient removal rule", loc="left", fontweight="bold", pad=17)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.set_xlim(0, .8)
    ax.set_xlabel("Missing values in the exploration population")
    ax.grid(axis="x", alpha=.15); ax.set_axisbelow(True)

    ax = axes[0, 1]
    rows = [r for r in app["target_segments"] if r["feature"] == "age_band"]
    x = np.arange(len(rows)); y = np.array([r["rate"] for r in rows])
    err = np.array([[r["rate"] - r["ci95"][0] for r in rows], [r["ci95"][1] - r["rate"] for r in rows]])
    ax.bar(x, y, color=[green, green, light, light, light], width=.65)
    ax.errorbar(x, y, yerr=err, fmt="none", color="#273f30", capsize=4)
    ax.set_xticks(x, ["Under 30", "30–39", "40–49", "50–59", "60+"])
    ax.axhline(app["integrity"]["exploration_event_rate"], color=amber, linestyle="--", label="Exploration event rate")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.set_ylim(0, .14)
    ax.set_title("Observed event rates differ across age groups", loc="left", fontweight="bold", pad=17)
    ax.set_ylabel("Repayment-difficulty target rate"); ax.legend(frameon=False, fontsize=8)
    ax.text(0, -.23, "95% Wilson intervals. Unadjusted association, not a causal effect.", transform=ax.transAxes, fontsize=8)

    ax = axes[1, 0]
    labels = ["Bureau", "Bureau monthly history", "Previous applications", "POS / cash balances", "Installment payments", "Credit-card balances"]
    ax.barh(labels[::-1], [histories[name]["labeled_coverage_rate"] for name in names][::-1], color=green)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.set_xlim(0, 1.05)
    ax.set_title("Available history varies by source", loc="left", fontweight="bold", pad=17)
    ax.set_xlabel("Share of all labeled applicants with matched records")
    ax.grid(axis="x", alpha=.15); ax.set_axisbelow(True)

    ax = axes[1, 1]
    fields = ["AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY"]
    x = np.arange(3)
    for offset, statistic, color, label in [(-.23, "median", green, "Median"), (0, "p99", light, "99th percentile"), (.23, "max", amber, "Maximum")]:
        ax.bar(x + offset, [app["numeric"][name][statistic] for name in fields], width=.23, color=color, label=label)
    ax.set_yscale("log"); ax.set_ylim(1000, 300_000_000)
    ax.set_xticks(x, ["Income", "Requested credit", "Annuity"])
    ax.set_title("Income has an extreme upper tail", loc="left", fontweight="bold", pad=17)
    ax.set_ylabel("Dataset monetary units (log scale)"); ax.legend(frameon=False, fontsize=8)
    ax.text(0, -.23, "Exact exploration quantiles. No clipping or log transformation applied.", transform=ax.transAxes, fontsize=8)
    fig.text(.17, .035, "Read-only investigation · no model trained · transformation choices await user review", color="#6b7e68", fontsize=10)
    figures = ROOT / "figures"
    figures.mkdir(exist_ok=True)
    fig.savefig(figures / "investigation-overview.png", dpi=150, facecolor=fig.get_facecolor())
    fig.savefig(figures / "investigation-overview.svg", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
