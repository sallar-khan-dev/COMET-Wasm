import json
from pathlib import Path
import pandas as pd
from sklearn.datasets import load_iris, load_breast_cancer, load_wine, load_digits
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.cluster import KMeans
from sklearn.neural_network import MLPClassifier

ROOT = Path(__file__).resolve().parents[2]

def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))

def save_csv(path, X, y, feature_names):
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(X, columns=feature_names)
    df["label"] = y
    df.to_csv(path, index=False)

def metrics(y_true, y_pred):
    avg = "binary" if len(set(y_true)) == 2 else "macro"
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average=avg, zero_division=0)
    return {"accuracy": float(accuracy_score(y_true, y_pred)), "precision": float(p), "recall": float(r), "f1": float(f1)}

def export_lr_iris():
    data = load_iris()
    X = data.data.astype(float)
    y = (data.target == 2).astype(int)
    feature_names = [n.replace(" (cm)", "").replace(" ", "_") for n in data.feature_names]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.30, random_state=42, stratify=y)
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    clf = LogisticRegression(max_iter=1000, random_state=42)
    clf.fit(X_train_s, y_train)
    pred = clf.predict(X_test_s)
    model = {
        "model": "LogisticRegression", "dataset": "Iris", "task": "virginica_vs_non_virginica",
        "feature_names": feature_names, "weights": clf.coef_[0].astype(float).tolist(),
        "bias": float(clf.intercept_[0]), "mean": scaler.mean_.astype(float).tolist(),
        "scale": scaler.scale_.astype(float).tolist(), "metrics": metrics(y_test, pred),
        "profile_hint": {"compute_class": "lightweight_linear", "memory_class": "very_low", "complexity": "O(d)", "features": int(X.shape[1]), "train_samples": int(X_train.shape[0]), "test_samples": int(X_test.shape[0])}
    }
    out_dir = ROOT / "models" / "logistic_regression" / "iris_lr"
    save_json(out_dir / "model.json", model)
    save_csv(out_dir / "test_samples.csv", X_test, y_test, feature_names)
    save_csv(ROOT / "datasets" / "iris" / "iris_binary_test.csv", X_test, y_test, feature_names)
    save_json(ROOT / "datasets" / "iris" / "iris_lr_metadata.json", model)
    print("Saved LR model:", out_dir / "model.json")
    print(json.dumps(model["metrics"], indent=2))

def export_sklearn_zoo():
    datasets = {"breast_cancer": load_breast_cancer(), "wine": load_wine(), "digits": load_digits()}
    classifiers = {
        "naive_bayes": GaussianNB(),
        "decision_tree": DecisionTreeClassifier(max_depth=8, random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=50, max_depth=8, random_state=42),
        "svm": SVC(kernel="rbf", gamma="scale", probability=False, random_state=42),
        "mlp": MLPClassifier(hidden_layer_sizes=(32,), max_iter=500, random_state=42),
    }
    summary = []
    for dname, data in datasets.items():
        X = data.data.astype(float)
        y = data.target
        feature_names = [str(n).replace(" ", "_").replace("(", "").replace(")", "") for n in getattr(data, "feature_names", [f"f{i}" for i in range(X.shape[1])])]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.30, random_state=42, stratify=y)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)
        save_csv(ROOT / "datasets" / dname / "test_samples.csv", X_test, y_test, feature_names)
        for mname, clf in classifiers.items():
            try:
                clf.fit(X_train_s, y_train)
                pred = clf.predict(X_test_s)
                met = metrics(y_test, pred)
                obj = {"model": mname, "dataset": dname, "feature_names": feature_names, "mean": scaler.mean_.astype(float).tolist(), "scale": scaler.scale_.astype(float).tolist(), "metrics": met, "profile_hint": {"features": int(X.shape[1]), "train_samples": int(X_train.shape[0]), "test_samples": int(X_test.shape[0])}}
                out = ROOT / "models" / mname / dname
                save_json(out / "metadata.json", obj)
                save_csv(out / "test_samples.csv", X_test, y_test, feature_names)
                summary.append({"dataset": dname, "model": mname, **met})
            except Exception as e:
                summary.append({"dataset": dname, "model": mname, "error": str(e)})
    iris = load_iris()
    X = iris.data.astype(float)
    km = KMeans(n_clusters=3, n_init=10, random_state=42)
    labels = km.fit_predict(X)
    save_json(ROOT / "models" / "kmeans" / "iris" / "metadata.json", {"model": "KMeans", "dataset": "iris", "centroids": km.cluster_centers_.astype(float).tolist(), "profile_hint": {"compute_class": "centroid_distance", "memory_class": "low_medium", "complexity": "O(k*d)"}})
    save_csv(ROOT / "models" / "kmeans" / "iris" / "samples.csv", X, labels, [f"f{i}" for i in range(X.shape[1])])
    summary.append({"dataset": "iris", "model": "kmeans", "note": "unsupervised_centroid_export"})
    save_json(ROOT / "models" / "model_zoo_summary.json", summary)
    print("Saved model zoo summary:", ROOT / "models" / "model_zoo_summary.json")

if __name__ == "__main__":
    export_lr_iris()
    export_sklearn_zoo()
