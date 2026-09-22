"""撤稿风险预测：加载训练好的 LightGBM 模型，对单篇文献预测"未来翻车"的概率。

模型与标准化器来自 scripts/train_model.py 的产物（models/*.joblib）。
特征构建与训练共用 app/risk_features.py，保证两边完全一致。

模型文件缺失时所有预测返回 None，前端不展示风险徽章，功能静默降级。
"""
import os

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
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
        return True
    except Exception:
        _load_failed = True
        return False


def risk_level(score):
    """风险概率 -> 分档（与前端展示配色对应）。"""
    if score >= 0.60:
        return "高"
    if score >= 0.40:
        return "中高"
    if score >= 0.20:
        return "中低"
    return "低"


def predict_risk(rec):
    """输入一条文献记录，返回 {"score": 0-1 概率, "level": 分档}；不可用返回 None。"""
    if not _load():
        return None
    try:
        vec = [feature_vector(rec)]
        Xs = _scaler.transform(vec)
        proba = float(_model.predict_proba(Xs)[0][1])
        return {"score": round(proba, 3), "level": risk_level(proba)}
    except Exception:
        return None
