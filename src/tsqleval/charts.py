"""Charts for the Text-to-SQL evaluation report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BLUE = "#2E5EAA"
LIGHT = "#8FB3F5"
RED = "#D64545"
GRAY = "#9AA5B1"


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def outcome_by_version(summary: pd.DataFrame, path: Path) -> Path:
    """Stacked bars: correct / executed-but-wrong / execution error."""
    versions = summary["version"]
    correct = summary["correct"]
    wrong = summary["executed"] - summary["correct"]
    errors = summary["questions"] - summary["executed"]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(versions, correct, color=BLUE, label="Correct")
    ax.bar(versions, wrong, bottom=correct, color=LIGHT, label="Executed, wrong result")
    ax.bar(versions, errors, bottom=correct + wrong, color=RED, label="Execution error")
    for i, version in enumerate(versions):
        ax.text(i, correct[i] / 2, str(int(correct[i])), ha="center", color="white", fontsize=10)
    ax.set_ylabel("Questions")
    ax.set_title("Outcome by system version")
    ax.legend(frameon=False, loc="lower right")
    return _save(fig, path)


def accuracy_by_difficulty(table: pd.DataFrame, path: Path) -> Path:
    levels = list(dict.fromkeys(table["difficulty"]))
    versions = list(dict.fromkeys(table["version"]))
    width = 0.8 / max(1, len(versions))
    fig, ax = plt.subplots(figsize=(7.5, 4))
    x = np.arange(len(levels))
    for offset, version in enumerate(versions):
        subset = table[table["version"] == version].set_index("difficulty").reindex(levels)
        ax.bar(x + offset * width, subset["accuracy"], width=width, label=version,
               color=[BLUE, LIGHT][offset % 2])
    ax.set_xticks(x + width * (len(versions) - 1) / 2)
    ax.set_xticklabels(levels)
    ax.set_ylabel("Accuracy")
    ax.set_ylim(0, 1)
    ax.set_title("Accuracy by question difficulty")
    ax.legend(frameon=False)
    return _save(fig, path)


def error_breakdown(table: pd.DataFrame, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(table["reason"], table["count"], color=GRAY)
    ax.invert_yaxis()
    ax.set_xlabel("Questions")
    ax.set_title("Failure reasons (both versions combined)")
    return _save(fig, path)
