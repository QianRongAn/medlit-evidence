"""撤稿研究模型分数：供人工排序参考，不代表未来撤稿概率。

模型与标准化器来自 scripts/train_model.py 的产物（models/*.joblib）。
特征构建与训练共用 app/risk_features.py，保证两边完全一致。

模型文件缺失时所有预测返回 None，前端不展示风险徽章，功能静默降级。
"""
import os
import math

from .risk_features import feature_vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL_PATH = os.path.join(ROOT, "models", "lgb.joblib")
SCALER_PATH = os.path.join(ROOT, "models", "scaler.joblib")

_model = None
_scaler = None
_load_failed = False


def _load():
    global _model, _scaler, _load_failed
    if _model is not None or _load_failed:
        return _model is not None
    try:
        import joblib
        if not (os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH)):
            _load_failed = True
            return False
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        _model, _scaler = model, scaler
        return True
    except Exception:
        _load_failed = True
        return False


def model_available():
    """模型与标准化器是否就绪（供 /health 与首页仪表盘展示）。"""
    return _load()


def predict_risk(rec):
    """返回 0–100 研究模型分数及未校准说明；模型不可用时返回 None。"""
    if rec.get("source") == "offline":
        return None  # 演示改写摘要不用于模型评分。
    if not _load():
        return None
    try:
        vec = [feature_vector(rec)]
        Xs = _scaler.transform(vec)
        proba = float(_model.predict_proba(Xs)[0][1])
        if not math.isfinite(proba) or not 0 <= proba <= 1:
            return None
        return {
            "kind": "research_model_score",
            "score": round(proba * 100, 1),
            "scale": [0, 100],
            "calibrated": False,
            "description": "研究模型分数，仅供人工排序；未校准，不代表未来撤稿概率。",
        }
    except Exception:
        return None
