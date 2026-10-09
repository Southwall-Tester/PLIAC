"""Small deterministic, executable scikit-learn experiments; no user code eval."""
import hashlib
import json

import numpy as np
import sklearn
from sklearn.datasets import make_moons
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier

from learning_agent.course_graph import CourseGraphError


def dataset(seed):
    x, y = make_moons(n_samples=600, noise=0.28, random_state=seed)
    return x, y


def config(value):
    if not isinstance(value, dict) or set(value) != {"train_percent", "depth", "features", "split"}:
        raise CourseGraphError("请填写训练比例、树深度、特征和划分方式。")
    if type(value["train_percent"]) is not int or value["train_percent"] not in (50, 60, 70):
        raise CourseGraphError("训练比例请选择 50%、60% 或 70%。")
    if type(value["depth"]) is not int or not 0 <= value["depth"] <= 12:
        raise CourseGraphError("树深度须为 0—12 的整数；0 表示自由生长。")
    if value["features"] not in ("sensors", "receipt") or value["split"] not in ("separate", "reuse"):
        raise CourseGraphError("请选择界面提供的特征与划分方式。")
    return dict(value)


def execute(seed, settings, *, test=False):
    settings = config(settings)
    x, y = dataset(seed)
    # receipt is intentionally a post-outcome proxy for teaching leakage.
    features = x if settings["features"] == "sensors" else np.column_stack([x, y])
    remaining, test_ids = train_test_split(np.arange(len(y)), test_size=0.2, stratify=y, random_state=seed)
    train_ids, valid_ids = train_test_split(remaining, train_size=settings["train_percent"] / 80,
                                          stratify=y[remaining], random_state=seed + 1)
    if settings["split"] == "reuse":
        valid_ids = train_ids.copy()
    model = DecisionTreeClassifier(max_depth=settings["depth"] or None, random_state=seed)
    model.fit(features[train_ids], y[train_ids])
    pred = model.predict(features[valid_ids])
    result = {"train_accuracy": float(accuracy_score(y[train_ids], model.predict(features[train_ids]))),
              "validation_accuracy": float(accuracy_score(y[valid_ids], pred)),
              "confusion_matrix": confusion_matrix(y[valid_ids], pred, labels=[0, 1]).tolist(),
              "counts": {"train": len(train_ids), "validation": len(valid_ids), "test": len(test_ids)},
              "overlap": len(set(train_ids) & set(valid_ids)), "tree_nodes": model.tree_.node_count,
              "split_hash": hashlib.sha256(json.dumps([train_ids.tolist(), valid_ids.tolist(), test_ids.tolist()]).encode()).hexdigest(),
              "dataset_hash": hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest(),
              "engine": {"name": "scikit-learn", "version": sklearn.__version__, "numpy_version": np.__version__}}
    # The ordinary experiment endpoint never computes or returns test scores.
    if test:
        result["test_accuracy"] = float(accuracy_score(y[test_ids], model.predict(features[test_ids])))
        result["test_confusion_matrix"] = confusion_matrix(y[test_ids], model.predict(features[test_ids]), labels=[0, 1]).tolist()
    return result


def preview(seed):
    x, y = dataset(seed)
    development, _ = train_test_split(np.arange(len(y)), test_size=0.2, stratify=y, random_state=seed)
    return [{"id": int(i), "x1": round(float(x[i, 0]), 5), "x2": round(float(x[i, 1]), 5),
             "target": int(y[i]), "receipt": int(y[i])} for i in development[:80]]


def reproduction(seed, settings, include_test=False):
    """Standalone script using the exact dataset/split/model recipe."""
    return f'''# PLIAC ML Lab — reproducible experiment
# pip install scikit-learn=={sklearn.__version__} numpy=={np.__version__}
import numpy as np
from sklearn.datasets import make_moons
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
seed = {seed!r}
settings = {settings!r}
x, y = make_moons(n_samples=600, noise=0.28, random_state=seed)
features = x if settings["features"] == "sensors" else np.column_stack([x, y])
remaining, test_ids = train_test_split(np.arange(len(y)), test_size=0.2, stratify=y, random_state=seed)
train_ids, valid_ids = train_test_split(remaining, train_size=settings["train_percent"] / 80, stratify=y[remaining], random_state=seed + 1)
if settings["split"] == "reuse":
    valid_ids = train_ids.copy()
model = DecisionTreeClassifier(max_depth=settings["depth"] or None, random_state=seed)
model.fit(features[train_ids], y[train_ids])
for name, ids in [("train", train_ids), ("validation", valid_ids)]{ ' + [("test", test_ids)]' if include_test else ''}:
    prediction = model.predict(features[ids])
    print(name, accuracy_score(y[ids], prediction), confusion_matrix(y[ids], prediction, labels=[0, 1]).tolist())
'''
