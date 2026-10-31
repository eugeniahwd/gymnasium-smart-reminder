"""Evaluasi model: metrik, tabel, dan grafik. Semua fungsi plot mengembalikan matplotlib Figure."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

from src.ml.feature_engineering import CLASSES, FEATURE_COLUMNS


def compute_metrics(y_true, y_pred) -> dict:
    """Metrik lengkap untuk satu set prediksi."""
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=CLASSES, zero_division=0)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=CLASSES, average="macro", zero_division=0)),
        "recall_high": float(r[CLASSES.index("High")]),
        "per_class": {
            c: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
            for i, c in enumerate(CLASSES)
        },
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=CLASSES).tolist(),
    }


def comparison_table(metrics_by_model: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for name, m in metrics_by_model.items():
        rows.append(
            {
                "Model": name,
                "Accuracy": m["accuracy"],
                "Macro-F1": m["macro_f1"],
                "Recall High": m["recall_high"],
                "Precision High": m["per_class"]["High"]["precision"],
                "F1 High": m["per_class"]["High"]["f1"],
            }
        )
    return pd.DataFrame(rows).set_index("Model")


def per_class_table(metric: dict) -> pd.DataFrame:
    df = pd.DataFrame(metric["per_class"]).T.loc[CLASSES]
    df["support"] = df["support"].astype(int)
    return df.rename(columns={"precision": "Precision", "recall": "Recall", "f1": "F1", "support": "Support"})


def to_markdown(df: pd.DataFrame, floatfmt: str = "{:.3f}", index_name: str | None = None) -> str:
    """DataFrame -> tabel Markdown (tanpa dependensi tabulate)."""
    idx = index_name or (df.index.name or "")
    cols = [idx] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for i, row in df.iterrows():
        cells = [str(i)] + [floatfmt.format(v) if isinstance(v, (float, np.floating)) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- grafik
def plot_confusion_matrices(metrics_by_model: dict[str, dict]):
    n = len(metrics_by_model)
    fig, axes = plt.subplots(1, n, figsize=(3.6 * n, 3.6))
    axes = np.atleast_1d(axes)
    for ax, (name, m) in zip(axes, metrics_by_model.items()):
        cm = np.array(m["confusion_matrix"])
        ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(3), CLASSES)
        ax.set_yticks(range(3), CLASSES)
        ax.set_xlabel("Prediksi")
        ax.set_ylabel("Aktual")
        ax.set_title(name, fontsize=10)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, cm[i, j], ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.tight_layout()
    return fig


def plot_model_comparison(metrics_by_model: dict[str, dict]):
    df = comparison_table(metrics_by_model)[["Accuracy", "Macro-F1", "Recall High"]]
    fig, ax = plt.subplots(figsize=(8, 4))
    df.plot(kind="bar", ax=ax, rot=0, color=["#7A8CC2", "#4C9F70", "#C8553D"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Skor (test set)")
    ax.set_title("Perbandingan model pada test set")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return fig


def plot_cv_comparison(cv_summary: pd.DataFrame):
    """cv_summary: index=model, kolom macro_f1_mean/std dan recall_high_mean/std."""
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(cv_summary))
    w = 0.38
    ax.bar(x - w / 2, cv_summary["macro_f1_mean"], w, yerr=cv_summary["macro_f1_std"], capsize=3,
           label="Macro-F1", color="#4C9F70")
    ax.bar(x + w / 2, cv_summary["recall_high_mean"], w, yerr=cv_summary["recall_high_std"], capsize=3,
           label="Recall High", color="#C8553D")
    ax.set_xticks(x, cv_summary.index)
    ax.set_ylim(0, 1)
    ax.set_title("Cross-validation 5-fold (grouped per customer, seluruh data): rata-rata ± std")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return fig


def compute_permutation_importance(pipeline, X_test, y_test, seed: int, n_repeats: int = 20) -> pd.DataFrame:
    res = permutation_importance(pipeline, X_test[FEATURE_COLUMNS], y_test, scoring="f1_macro",
                                 n_repeats=n_repeats, random_state=seed)
    return (
        pd.DataFrame({"feature": FEATURE_COLUMNS, "importance": res.importances_mean, "std": res.importances_std})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )


def plot_permutation_importance(imp: pd.DataFrame, title: str = "Permutation importance (test set, penurunan macro-F1)"):
    d = imp.iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(d["feature"], d["importance"], xerr=d["std"], color="#7A8CC2", capsize=2)
    ax.axvline(0, color="grey", lw=0.8)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Penurunan macro-F1 saat fitur diacak")
    fig.tight_layout()
    return fig


def lr_coefficient_frame(lr_pipeline) -> pd.DataFrame:
    """Koefisien Logistic Regression (pada fitur terstandarisasi) per kelas."""
    names = [n.split("__", 1)[1] for n in lr_pipeline.named_steps["prep"].get_feature_names_out()]
    clf = lr_pipeline.named_steps["model"]
    return pd.DataFrame(clf.coef_.T, index=names, columns=list(clf.classes_))[CLASSES]


def plot_lr_coefficients(coef: pd.DataFrame, top: int = 12):
    order = coef["High"].abs().sort_values(ascending=False).head(top).index
    d = coef.loc[order].iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(d.index, d["High"], color=["#C8553D" if v > 0 else "#4C9F70" for v in d["High"]])
    ax.axvline(0, color="grey", lw=0.8)
    ax.set_title("Koefisien Logistic Regression untuk kelas High\n(positif = menaikkan peluang High)", fontsize=10)
    fig.tight_layout()
    return fig
