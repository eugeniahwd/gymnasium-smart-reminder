"""Fungsi EDA (dipanggil oleh notebooks/01_eda.ipynb). Setiap fungsi mengembalikan matplotlib Figure."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src.ml.feature_engineering import CLASSES, FEATURE_COLUMNS, LABEL_COLUMN, NUMERIC_FEATURES

PALETTE = {"Low": "#4C9F70", "Medium": "#E0A030", "High": "#C8553D"}


def plot_class_distribution(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(5, 3.5))
    counts = df[LABEL_COLUMN].value_counts().reindex(CLASSES)
    ax.bar(counts.index, counts.values, color=[PALETTE[c] for c in counts.index])
    for i, v in enumerate(counts.values):
        ax.text(i, v + 8, f"{v} ({v / len(df):.0%})", ha="center", fontsize=9)
    ax.set_title("Distribusi kelas prioritas")
    ax.set_ylabel("Jumlah baris")
    fig.tight_layout()
    return fig


def plot_features_by_class(df: pd.DataFrame):
    cols = [
        "attendance_rate_30d", "attendance_rate_90d", "consecutive_absences", "no_response_streak",
        "days_since_last_attendance", "reminder_response_rate",
    ]
    fig, axes = plt.subplots(2, 3, figsize=(12, 6))
    for ax, col in zip(axes.ravel(), cols):
        sns.boxplot(data=df, x=LABEL_COLUMN, y=col, order=CLASSES, palette=PALETTE, hue=LABEL_COLUMN,
                    legend=False, ax=ax, fliersize=2)
        ax.set_title(col, fontsize=10)
        ax.set_xlabel("")
    fig.suptitle("Distribusi fitur utama per kelas prioritas", y=1.0)
    fig.tight_layout()
    return fig


def plot_correlation(df: pd.DataFrame):
    corr = df[NUMERIC_FEATURES].corr()
    fig, ax = plt.subplots(figsize=(8, 6.5))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, vmin=-1, vmax=1,
                annot_kws={"size": 7}, ax=ax, cbar_kws={"shrink": 0.8})
    ax.set_title("Korelasi antar fitur numerik")
    fig.tight_layout()
    return fig


def plot_missing(df: pd.DataFrame):
    miss = (df[FEATURE_COLUMNS].isna().mean() * 100).sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.barh(miss.index, miss.values, color="#7A8CC2")
    ax.set_xlabel("% missing")
    ax.set_title("Missing value per fitur")
    fig.tight_layout()
    return fig


def plot_by_persona(df: pd.DataFrame):
    ct = pd.crosstab(df["persona"], df[LABEL_COLUMN], normalize="index").reindex(columns=CLASSES) * 100
    fig, ax = plt.subplots(figsize=(6, 3.8))
    ct.plot(kind="bar", stacked=True, ax=ax, color=[PALETTE[c] for c in CLASSES], rot=0)
    ax.set_ylabel("% baris")
    ax.set_xlabel("")
    ax.set_title("Komposisi kelas prioritas per persona")
    ax.legend(title="Prioritas", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    return fig


def save_eda_figures(df: pd.DataFrame, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    figs = {
        "eda_class_distribution.png": plot_class_distribution,
        "eda_features_by_class.png": plot_features_by_class,
        "eda_correlation.png": plot_correlation,
        "eda_missing.png": plot_missing,
        "eda_persona.png": plot_by_persona,
    }
    paths = []
    for name, fn in figs.items():
        fig = fn(df)
        fig.savefig(out_dir / name, dpi=130, bbox_inches="tight")
        plt.close(fig)
        paths.append(out_dir / name)
    return paths
