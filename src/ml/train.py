"""Training & evaluasi model prioritas follow-up.

Jalankan:  python -m src.ml.train            # penuh (tuning), tulis artefak + grafik + dokumen
           python -m src.ml.train --fast     # grid kecil (untuk tes cepat)

Protokol (docs/AI_SPEC.md bagian A3):
- Split 80/20 stratified DAN grouped per customer_id (tidak ada customer di train sekaligus test).
- Tuning memakai StratifiedGroupKFold 5-fold pada TRAIN saja (scoring macro-F1).
- Model dipilih berdasarkan macro-F1 cross-validation (bukan test set); test set hanya untuk pelaporan.
- Sanity check leakage: akurasi test > 97% dianggap mencurigakan.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import warnings
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.ml import evaluate as ev
from src.ml.baseline import RULE_DESCRIPTION, RuleBaseline
from src.ml.feature_engineering import (
    CATEGORICAL_FEATURES,
    CLASSES,
    FEATURE_COLUMNS,
    ID_COLUMNS,
    LABEL_COLUMN,
    NUMERIC_FEATURES,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "processed" / "training_dataset.csv"
ARTIFACT_DIR = ROOT / "src" / "ml" / "artifacts"
FIG_DIR = ROOT / "docs" / "figures"
DOC_PATH = ROOT / "docs" / "MODEL_EVALUATION.md"
SEED = 42
LEAKAGE_ACC_THRESHOLD = 0.97
DOC_START, DOC_END = "<!-- RESULTS_START -->", "<!-- RESULTS_END -->"


# ----------------------------------------------------------------------------- data & pipeline
def load_dataset(path: Path = DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["reference_date"])
    missing = [c for c in FEATURE_COLUMNS + [LABEL_COLUMN] + ID_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom tidak ada di dataset: {missing}")
    return df


def make_preprocessor() -> ColumnTransformer:
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline(
        [("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]
    )
    return ColumnTransformer([("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)])


def make_pipeline(model) -> Pipeline:
    return Pipeline([("prep", make_preprocessor()), ("model", model)])


def split_train_test(df: pd.DataFrame, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Split ~80/20 stratified + grouped: ambil satu fold dari StratifiedGroupKFold(5)."""
    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    train_idx, test_idx = next(sgkf.split(df[FEATURE_COLUMNS], df[LABEL_COLUMN], groups=df["customer_id"]))
    overlap = set(df.iloc[train_idx]["customer_id"]) & set(df.iloc[test_idx]["customer_id"])
    assert not overlap, f"Customer muncul di train dan test: {sorted(overlap)[:5]}"
    return train_idx, test_idx


def model_grids(fast: bool, seed: int) -> dict[str, tuple[Pipeline, dict]]:
    lr = make_pipeline(LogisticRegression(max_iter=3000, class_weight="balanced"))
    rf = make_pipeline(RandomForestClassifier(class_weight="balanced", random_state=seed, n_jobs=1))
    if fast:
        lr_grid = {"model__C": [0.1, 1.0]}
        rf_grid = {"model__n_estimators": [100], "model__max_depth": [4, 8], "model__min_samples_leaf": [3]}
    else:
        lr_grid = {"model__C": [0.01, 0.1, 1.0, 10.0]}
        rf_grid = {
            "model__n_estimators": [200, 400],
            "model__max_depth": [4, 6, 8, None],
            "model__min_samples_leaf": [1, 3, 5],
        }
    return {"Logistic Regression": (lr, lr_grid), "Random Forest": (rf, rf_grid)}


# ----------------------------------------------------------------------------- cross-validation seluruh data
def cross_validate_all(df: pd.DataFrame, estimators: dict, seed: int) -> pd.DataFrame:
    """5-fold grouped CV pada SELURUH data (hyperparameter tetap) untuk melihat variansi antar fold."""
    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed + 1)
    X, y, g = df[FEATURE_COLUMNS], df[LABEL_COLUMN], df["customer_id"]
    rows = {}
    for name, est in estimators.items():
        f1s, rec = [], []
        for tr, te in sgkf.split(X, y, g):
            m = clone(est).fit(X.iloc[tr], y.iloc[tr])
            met = ev.compute_metrics(y.iloc[te], m.predict(X.iloc[te]))
            f1s.append(met["macro_f1"])
            rec.append(met["recall_high"])
        rows[name] = {
            "macro_f1_mean": np.mean(f1s), "macro_f1_std": np.std(f1s),
            "recall_high_mean": np.mean(rec), "recall_high_std": np.std(rec),
        }
    return pd.DataFrame(rows).T


# ----------------------------------------------------------------------------- orkestrasi
def run_training(
    data_path: Path = DATA_PATH,
    output_dir: Path | None = None,
    fig_dir: Path | None = None,
    fast: bool = False,
    seed: int = SEED,
    write: bool = True,
    update_docs: bool = True,
    verbose: bool = True,
) -> dict:
    log = print if verbose else (lambda *a, **k: None)
    df = load_dataset(data_path)
    assert not set(ID_COLUMNS) & set(FEATURE_COLUMNS), "ID/tanggal tidak boleh menjadi fitur"
    train_idx, test_idx = split_train_test(df, seed)
    train, test = df.iloc[train_idx], df.iloc[test_idx]
    X_tr, y_tr, g_tr = train[FEATURE_COLUMNS], train[LABEL_COLUMN], train["customer_id"]
    X_te, y_te = test[FEATURE_COLUMNS], test[LABEL_COLUMN]
    log(f"Data: {len(df)} baris | train {len(train)} ({train.customer_id.nunique()} customer) | "
        f"test {len(test)} ({test.customer_id.nunique()} customer) | overlap customer: 0")

    # --- model
    estimators: dict[str, Pipeline] = {
        "Dummy (kelas terbanyak)": make_pipeline(DummyClassifier(strategy="most_frequent")),
        "Baseline rule-based": Pipeline([("rule", RuleBaseline())]),
    }
    cv_inner = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    searches, best_params, cv_scores = {}, {}, {}
    for name, (pipe, grid) in model_grids(fast, seed).items():
        gs = GridSearchCV(pipe, grid, scoring="f1_macro", cv=cv_inner, n_jobs=1, refit=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gs.fit(X_tr, y_tr, groups=g_tr)
        i = gs.best_index_
        estimators[name] = gs.best_estimator_
        searches[name] = gs
        best_params[name] = {k.replace("model__", ""): v for k, v in gs.best_params_.items()}
        cv_scores[name] = {
            "cv_macro_f1_mean": float(gs.cv_results_["mean_test_score"][i]),
            "cv_macro_f1_std": float(gs.cv_results_["std_test_score"][i]),
        }
        log(f"{name}: CV macro-F1 {cv_scores[name]['cv_macro_f1_mean']:.3f} ± "
            f"{cv_scores[name]['cv_macro_f1_std']:.3f} | params {best_params[name]}")
    for name in ["Dummy (kelas terbanyak)", "Baseline rule-based"]:
        estimators[name].fit(X_tr, y_tr)

    # --- evaluasi test
    preds = {n: m.predict(X_te) for n, m in estimators.items()}
    test_metrics = {n: ev.compute_metrics(y_te, p) for n, p in preds.items()}
    train_f1 = {n: ev.compute_metrics(y_tr, m.predict(X_tr))["macro_f1"] for n, m in estimators.items()}

    # --- pemilihan model (berdasar CV, bukan test)
    candidates = ["Logistic Regression", "Random Forest"]
    chosen = max(candidates, key=lambda n: cv_scores[n]["cv_macro_f1_mean"])
    baseline_recall = test_metrics["Baseline rule-based"]["recall_high"]
    guard_ok = test_metrics[chosen]["recall_high"] >= baseline_recall
    log(f"Model terpilih: {chosen} | recall High test {test_metrics[chosen]['recall_high']:.3f} "
        f"vs baseline {baseline_recall:.3f} -> {'OK' if guard_ok else 'GAGAL'}")

    # --- sanity check leakage
    acc = test_metrics[chosen]["accuracy"]
    leakage_suspected = acc > LEAKAGE_ACC_THRESHOLD
    if leakage_suspected:
        log(f"!!! AKURASI TEST {acc:.3f} > {LEAKAGE_ACC_THRESHOLD}: curigai leakage, periksa generator & fitur.")

    # --- CV seluruh data (variansi antar fold)
    cv_all_estimators = {
        "Dummy (kelas terbanyak)": estimators["Dummy (kelas terbanyak)"],
        "Baseline rule-based": estimators["Baseline rule-based"],
        "Logistic Regression": estimators["Logistic Regression"],
        "Random Forest": estimators["Random Forest"],
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv_all = cross_validate_all(df, cv_all_estimators, seed)

    # --- interpretasi
    importance = ev.compute_permutation_importance(estimators[chosen], X_te, y_te, seed)
    lr_coef = ev.lr_coefficient_frame(estimators["Logistic Regression"])

    gap = pd.DataFrame(
        {
            "Train macro-F1": {n: train_f1[n] for n in candidates},
            "CV macro-F1 (train)": {n: cv_scores[n]["cv_macro_f1_mean"] for n in candidates},
            "Test macro-F1": {n: test_metrics[n]["macro_f1"] for n in candidates},
        }
    )

    results = {
        "df_shape": df.shape, "train_idx": train_idx, "test_idx": test_idx,
        "train_customers": set(train["customer_id"]), "test_customers": set(test["customer_id"]),
        "estimators": estimators, "preds": preds, "y_test": y_te,
        "test_metrics": test_metrics, "cv_scores": cv_scores, "cv_all": cv_all, "best_params": best_params,
        "chosen": chosen, "guard_ok": guard_ok, "leakage_suspected": leakage_suspected,
        "importance": importance, "lr_coef": lr_coef, "gap": gap, "train_f1": train_f1,
        "class_dist": df[LABEL_COLUMN].value_counts(normalize=True).reindex(CLASSES).to_dict(),
        "seed": seed, "fast": fast,
    }

    if write:
        out_dir = Path(output_dir or ARTIFACT_DIR)
        figs = Path(fig_dir or FIG_DIR)
        # dokumen hanya diperbarui pada run default (bukan saat output_dir kustom, mis. di test)
        doc = DOC_PATH if (update_docs and output_dir is None) else None
        write_outputs(results, out_dir, figs, doc_path=doc)
        log(f"Artefak tersimpan di {out_dir}")
    return results


# ----------------------------------------------------------------------------- output
def write_outputs(results: dict, out_dir: Path, fig_dir: Path, doc_path: Path | None = DOC_PATH) -> None:
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)
    chosen = results["chosen"]
    version = f"{'lr' if chosen == 'Logistic Regression' else 'rf'}-{datetime.now():%Y%m%d}-v1"

    joblib.dump(results["estimators"][chosen], out_dir / "priority_model.joblib")
    metadata = {
        "model_version": version,
        "model_name": chosen,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "seed": results["seed"],
        "classes": list(results["estimators"][chosen].classes_),
        "features": {"numeric": NUMERIC_FEATURES, "categorical": CATEGORICAL_FEATURES},
        "best_params": {k: {a: (b if b is None or isinstance(b, (int, float, str)) else str(b)) for a, b in v.items()}
                        for k, v in results["best_params"].items()},
        "n_rows": int(results["df_shape"][0]),
        "n_train": len(results["train_idx"]),
        "n_test": len(results["test_idx"]),
        "test_metrics": {k: {m: v for m, v in met.items() if m != "per_class"}
                         for k, met in results["test_metrics"].items() if k == chosen},
        "test_metrics_per_class": results["test_metrics"][chosen]["per_class"],
        "cv_macro_f1": results["cv_scores"][chosen],
        "baseline_rule": RULE_DESCRIPTION,
        "versions": {"sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__,
                     "python": platform.python_version()},
        "sklearn_version": sklearn.__version__,
        "disclaimer": "Dilatih pada data synthetic; prototype, bukan klaim performa di kondisi nyata.",
    }
    (out_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    tm = results["test_metrics"]
    figures = {
        "model_confusion_matrices.png": ev.plot_confusion_matrices(tm),
        "model_comparison_test.png": ev.plot_model_comparison(tm),
        "model_comparison_cv.png": ev.plot_cv_comparison(results["cv_all"]),
        "model_permutation_importance.png": ev.plot_permutation_importance(
            results["importance"], f"Permutation importance - {chosen} (test set)"),
        "model_lr_coefficients.png": ev.plot_lr_coefficients(results["lr_coef"]),
    }
    for name, fig in figures.items():
        fig.savefig(fig_dir / name, dpi=130, bbox_inches="tight")
        plt.close(fig)

    if doc_path is not None and Path(doc_path).exists():
        update_doc(Path(doc_path), build_results_markdown(results, version))


def build_results_markdown(results: dict, version: str) -> str:
    tm, chosen = results["test_metrics"], results["chosen"]
    cmp_df = ev.comparison_table(tm)
    cv_all = results["cv_all"].rename(columns={
        "macro_f1_mean": "Macro-F1 (rata-rata)", "macro_f1_std": "Macro-F1 (std)",
        "recall_high_mean": "Recall High (rata-rata)", "recall_high_std": "Recall High (std)"})
    imp = results["importance"].head(8).copy()
    imp["importance"] = imp["importance"].round(4)
    imp["std"] = imp["std"].round(4)
    cm = np.array(tm[chosen]["confusion_matrix"])
    cm_df = pd.DataFrame(cm, index=[f"Aktual {c}" for c in CLASSES], columns=[f"Prediksi {c}" for c in CLASSES])
    cm_df = cm_df.astype(str)
    params = json_safe(results["best_params"])
    leak = ("**PERINGATAN: akurasi test melewati 97%, curigai leakage.**" if results["leakage_suspected"]
            else "Akurasi test di bawah 97%: tidak ada tanda leakage dari uji kewajaran ini.")
    guard = "terpenuhi" if results["guard_ok"] else "TIDAK terpenuhi"
    return "\n".join([
        f"_Bagian ini dibuat otomatis oleh `python -m src.ml.train` (versi model `{version}`, seed {results['seed']}, "
        f"scikit-learn {sklearn.__version__}). Jangan diedit manual._",
        "",
        f"Data: {results['df_shape'][0]} baris; train {len(results['train_idx'])}, test {len(results['test_idx'])}; "
        f"customer di train dan test tidak beririsan. Distribusi kelas: "
        + ", ".join(f"{c} {v:.1%}" for c, v in results["class_dist"].items()) + ".",
        "",
        "### Hasil pada test set",
        "",
        ev.to_markdown(cmp_df, index_name="Model"),
        "",
        f"**Model terpilih: {chosen}** (dipilih dari macro-F1 cross-validation pada data train, bukan dari test set). "
        f"Syarat recall High >= baseline: {guard}. {leak}",
        "",
        f"Hyperparameter terpilih: `{params}`",
        "",
        "### Metrik per kelas (model terpilih, test set)",
        "",
        ev.to_markdown(ev.per_class_table(tm[chosen]), index_name="Kelas"),
        "",
        "### Confusion matrix (model terpilih, test set)",
        "",
        ev.to_markdown(cm_df, index_name=""),
        "",
        "![Confusion matrix](figures/model_confusion_matrices.png)",
        "",
        "### Gap train vs CV vs test (macro-F1)",
        "",
        ev.to_markdown(results["gap"], index_name="Model"),
        "",
        "### Cross-validation 5-fold pada seluruh data (grouped per customer)",
        "",
        "Test set hanya berisi sekitar 260 baris, sehingga satu split memiliki variansi cukup besar. "
        "Tabel ini merata-ratakan lima fold (hyperparameter tetap):",
        "",
        ev.to_markdown(cv_all, index_name="Model"),
        "",
        "![Perbandingan CV](figures/model_comparison_cv.png)",
        "",
        "### Fitur paling berpengaruh (permutation importance, test set)",
        "",
        ev.to_markdown(imp[["feature", "importance", "std"]].set_index("feature"), floatfmt="{:.4f}", index_name="Fitur"),
        "",
        "![Permutation importance](figures/model_permutation_importance.png)",
        "",
        "![Koefisien LR](figures/model_lr_coefficients.png)",
    ])


def json_safe(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def update_doc(doc_path: Path, markdown: str) -> None:
    text = doc_path.read_text(encoding="utf-8")
    block = f"{DOC_START}\n{markdown}\n{DOC_END}"
    if DOC_START in text and DOC_END in text:
        text = re.sub(re.escape(DOC_START) + r".*?" + re.escape(DOC_END), lambda _: block, text, flags=re.S)
    else:
        text += "\n\n" + block + "\n"
    doc_path.write_text(text, encoding="utf-8")


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    parser = argparse.ArgumentParser(description="Latih dan evaluasi model prioritas follow-up.")
    parser.add_argument("--fast", action="store_true", help="grid kecil untuk uji cepat")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    run_training(fast=args.fast, seed=args.seed)


if __name__ == "__main__":
    main()
