"""
build_analysis.py — 정식연재 여부와 지표의 관계를 계산해서 data/analysis.json으로 저장합니다.

입력
  - data/history.json          : 크롤러가 쌓은 작품별 추적 데이터 (별점·조회수·화수)
  - data/reference_cases.json  : 조사 목록에서 뽑은 기준 데이터 (작품 번호, 뱃지 분류, 관심 수)
출력
  - data/analysis.json         : 사이트의 분석 페이지(#/analysis)가 그대로 읽는 계산 결과

계산 (정식연재 = 1, 정식연재 없음 = 0 인 작품만 비교, 수상작·완결·분류 불가는 제외)
  1) 지표별 스피어만 상관: 지표 값 순위와 정식연재 여부가 얼마나 같이 움직이는지 (p < 0.05면 유의)
  2) 로지스틱 회귀: 별점·로그 조회수·관심 전환율을 표준화해 넣고 1 표준편차 증가당 오즈비와 95% 신뢰구간
  3) 표본 점검: 변수당 사건 수(EPV) — 경험칙 10 미만이면 추정이 불안정할 수 있음 (Peduzzi 외, 1996)
  4) 다중검정 보정: 지표 6개를 동시에 검정하므로 유의 기준(0.05)을 지표 수로 나눈 값(본페로니)으로도 함께 판정

scipy·numpy가 없으면 계산하지 않고 {"error": ...}만 저장합니다 (사이트 빌드는 계속 진행).
사용법: python build_analysis.py
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

HISTORY_PATH = Path("data") / "history.json"
REFERENCE_PATH = Path("data") / "reference_cases.json"
ANALYSIS_PATH = Path("data") / "analysis.json"

ALPHA = 0.05          # 통계에서 흔히 쓰는 관례적 유의 기준
EPV_MIN = 10          # 변수당 사건 수 경험칙 (Peduzzi 외, 1996)

# (키, 이름) — 지표 비교 표의 순서
INDICATORS = [
    ("star", "별점"),
    ("viewsPerEp", "화당 조회수"),
    ("views", "누적 조회수"),
    ("favorite", "관심 수"),
    ("conversion", "관심 전환율 (관심÷조회수 ×1000)"),
    ("episodes", "화수"),
]


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def metrics_for(entry: dict, favorite):
    """한 작품의 지표 값. 계산할 수 없는 값은 None."""
    vh = entry.get("viewHistory") or []
    views = vh[-1] if vh else None
    eps = entry.get("episodeCount")
    star = entry.get("starScore")
    out = {
        "star": star if star else None,
        "views": views if views else None,
        "episodes": eps if eps else None,
        "viewsPerEp": (views / eps) if views and eps else None,
        "favorite": favorite if favorite else None,
        "conversion": (favorite / views * 1000) if favorite and views else None,
    }
    return out


def interpret(rho: float, p: float, ratio):
    if abs(rho) < 0.1:
        return "거의 차이 없음"
    side = "높음" if rho > 0 else "낮음"
    if p < ALPHA:
        return f"정식연재 쪽이 {side} · 기준(p<{ALPHA})은 통과, 보정 전 결과"
    if p < 0.1:
        return f"정식연재 쪽이 {side} · 경계선 수준 (확정 못 함)"
    return f"정식연재 쪽이 {side}으로 보이나 우연일 수 있음"


def logistic_fit(X, y):
    """IRLS(뉴턴법) 로지스틱 회귀. X는 절편 포함. (계수, 표준오차) 반환, 수렴 실패면 None."""
    import numpy as np
    beta = np.zeros(X.shape[1])
    for _ in range(100):
        eta = X @ beta
        p = 1 / (1 + np.exp(-np.clip(eta, -30, 30)))
        w = p * (1 - p)
        if np.any(w < 1e-10):
            return None                      # 완전 분리 등 — 추정 불가
        H = X.T @ (X * w[:, None])
        try:
            step = np.linalg.solve(H, X.T @ (y - p))
        except np.linalg.LinAlgError:
            return None
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            cov = np.linalg.inv(H)
            return beta, np.sqrt(np.diag(cov))
    return None


def compute(history: dict, reference: dict) -> dict:
    try:
        import numpy as np
        from scipy import stats
    except ImportError as e:
        return {"error": f"분석 라이브러리(numpy, scipy)가 없어 계산하지 못했습니다: {e}"}

    cases = (reference or {}).get("cases") or []
    group_counts = {}
    for c in cases:
        group_counts[c["group"]] = group_counts.get(c["group"], 0) + 1

    rows = []   # (y, metrics)
    for c in cases:
        if c["group"] not in ("official", "none"):
            continue
        entry = history.get(str(c["titleId"]))
        if not entry:
            continue
        rows.append((1 if c["group"] == "official" else 0, metrics_for(entry, c.get("favorite"))))

    dates = [d for e in history.values() for d in (e.get("viewDates") or [])]
    result = {
        "computedAt": date.today().isoformat(),
        "historyLastDate": max(dates) if dates else None,
        "referenceSource": (reference or {}).get("source"),
        "alpha": ALPHA,
        "groups": group_counts,
        "compared": len(rows),
        "comparedOfficial": sum(y for y, _ in rows),
        "indicators": [],
        "logistic": None,
    }
    if len(rows) < 10 or result["comparedOfficial"] < 3:
        result["error"] = "비교할 작품이 너무 적어 계산하지 않았습니다."
        return result

    # 1) 지표별 스피어만 + 중앙값
    for key, label in INDICATORS:
        pairs = [(y, m[key]) for y, m in rows if m[key] is not None]
        ys = np.array([p[0] for p in pairs], dtype=float)
        xs = np.array([p[1] for p in pairs], dtype=float)
        if len(pairs) < 10 or ys.sum() < 3 or ys.sum() == len(ys):
            continue
        rho, p = stats.spearmanr(xs, ys)
        med_off = float(np.median(xs[ys == 1]))
        med_none = float(np.median(xs[ys == 0]))
        ratio = med_off / med_none if med_none else None
        result["indicators"].append({
            "key": key, "label": label,
            "medianOfficial": round(med_off, 2), "medianNone": round(med_none, 2),
            "ratio": round(ratio, 2) if ratio is not None else None,
            "rho": round(float(rho), 2), "p": round(float(p), 3), "pExact": float(p), "n": len(pairs),
            "significant": bool(p < ALPHA),
            "verdict": "유의" if p < ALPHA else "확정 못 함 (우연일 수 있음)",
            "note": interpret(float(rho), float(p), ratio),
        })
    result["significantCount"] = sum(1 for i in result["indicators"] if i["significant"])
    result["indicatorCount"] = len(result["indicators"])
    # 지표 여러 개를 한꺼번에 검정하면 우연히 p<0.05가 하나쯤 나올 수 있어서, 기준을 지표 수로 나눠 다시 봄 (본페로니 보정)
    m = result["indicatorCount"]
    result["alphaCorrected"] = round(ALPHA / m, 4) if m else None
    for i in result["indicators"]:
        i["significantCorrected"] = bool(m and i.pop("pExact") < ALPHA / m)
    result["significantCorrectedCount"] = sum(1 for i in result["indicators"] if i["significantCorrected"])

    # 2) 로지스틱 회귀 (별점, 로그 조회수, 관심 전환율)
    keys = [("star", "별점", lambda v: v), ("views", "로그 조회수", math.log), ("conversion", "관심 전환율 (관심÷조회수 ×1000)", lambda v: v)]
    complete = [(y, m) for y, m in rows if all(m[k] is not None for k, _, _ in keys)]
    y = np.array([r[0] for r in complete], dtype=float)
    cols = np.array([[f(m[k]) for k, _, f in keys] for _, m in complete], dtype=float)
    events, n, k = int(y.sum()), len(y), len(keys)
    logistic = {"n": n, "events": events, "variables": k,
                "epv": round(events / k, 2) if k else None, "epvMin": EPV_MIN,
                "sampleOk": bool(events / k >= EPV_MIN), "rows": []}
    sd = cols.std(axis=0, ddof=1)
    if n >= 20 and events >= 3 and np.all(sd > 0):
        Z = (cols - cols.mean(axis=0)) / sd
        X = np.column_stack([np.ones(n), Z])
        fit = logistic_fit(X, y)
        if fit is not None:
            beta, se = fit
            for i, (_, label, _) in enumerate(keys, start=1):
                lo, hi = beta[i] - 1.96 * se[i], beta[i] + 1.96 * se[i]
                pval = 2 * (1 - stats.norm.cdf(abs(beta[i] / se[i])))
                includes_one = lo < 0 < hi
                logistic["rows"].append({
                    "label": label,
                    "or": round(float(math.exp(beta[i])), 2),
                    "lo": round(float(math.exp(lo)), 2), "hi": round(float(math.exp(hi)), 2),
                    "p": round(float(pval), 3),
                    "verdict": "구간이 1을 포함 → 방향 확정 불가" if includes_one
                               else ("정식연재 가능성 증가" if beta[i] > 0 else "정식연재 가능성 감소"),
                })
        else:
            logistic["error"] = "회귀가 수렴하지 않았습니다 (표본이 너무 적거나 값이 한쪽으로 치우침)."
    else:
        logistic["error"] = "회귀를 돌리기에 표본이 부족합니다."
    result["logistic"] = logistic
    return result


def main() -> None:
    history = load_json(HISTORY_PATH)
    reference = load_json(REFERENCE_PATH)
    if not history or not reference:
        print("[분석] history.json 또는 reference_cases.json이 없어 계산을 건너뜁니다.")
        return
    result = compute(history, reference)
    ANALYSIS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if result.get("error"):
        print(f"[분석] {result['error']}")
    else:
        print(f"[분석] 비교 {result['compared']}개(정식연재 {result['comparedOfficial']}) · 유의한 지표 {result['significantCount']}/{result['indicatorCount']} → {ANALYSIS_PATH}")


if __name__ == "__main__":
    main()
