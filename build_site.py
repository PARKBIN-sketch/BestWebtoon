"""
build_site.py — history.json을 scouting_desk_mockup.html의 REAL_DATA에 자동으로 병합합니다.

지금까지 새 데이터가 쌓일 때마다 사람이 대화창에서 파일을 올리고,
Claude가 파이썬으로 손수 병합해서 새 HTML을 만들어주던 작업을
그대로 스크립트로 옮긴 것입니다. GitHub Actions에서 크롤러가 끝난
직후 이 스크립트가 자동으로 실행되어, 사람이 손 델 일이 없어집니다.

사용법: python build_site.py
  - data/history.json 을 읽어서
  - scouting_desk_mockup.html 안의 "const REAL_DATA = [...]" 부분만 통째로 교체하고
  - 나머지(디자인, 로직, CSS 등)는 전혀 건드리지 않습니다.

주의: 이 스크립트는 REAL_DATA "값"만 갈아끼웁니다. 신호 배지 구조, 색상,
정렬 로직 같은 사이트 자체의 기능 변경은 여전히 Claude와 상의해서
scouting_desk_mockup.html 코드를 직접 고치는 방식으로 진행해야 합니다.
"""
import json
import re
import sys
from pathlib import Path

HISTORY_PATH = Path("data") / "history.json"
# 사이트의 [분류 내보내기]로 받은 파일을 이 경로에 올리면, 다음 빌드부터 사이트에 기본값으로 포함됨
LABELS_PATH = Path("data") / "labels.json"
# 크롤러가 쌓는 정식 연재 추적 기록(data/official_tracking.json)
OFFICIAL_PATH = Path("data") / "official_tracking.json"
# build_analysis.py가 계산한 정식연재 지표 분석 결과 (사이트의 #/analysis 페이지가 읽음)
ANALYSIS_PATH = Path("data") / "analysis.json"
POSITION_EXC_PATH = Path("data") / "position_exceptions.json"   # 관심도 위치 탭: 통계에서 뺄 작품 {번호: 사유}
CURRENT_PATH = Path("data") / "current_webtoons.json"       # 현재 연재작 관심 수·연재 시작일 (collect_current.py가 모음)
BADGE_NAMES_PATH = Path("data") / "badge_names.json"       # 선정 배지 "당시 명칭" 추천 목록 (경로별 이름)
PATH_TAGS_PATH = Path("data") / "path_tags.json"           # 공식 명단·라벨 메모로 확인된 선정 경로 (titleId별 목록)
AWARD_LOOKUP_PATH = Path("data") / "award_lookup.json"     # lookup_awards.py가 제목으로 찾은 결과 (추정으로만 표시)
PAST_NOTICES_PATH = Path("data") / "past_notices.json"     # scan_past_notices.py가 만드는 "지난 회차 공지 후보" 기록
SITE_PATH = Path("scouting_desk_mockup.html")


def build_real_data(history: dict) -> list[dict]:
    """history.json의 titleId별 누적 이력을, 사이트가 바로 쓸 수 있는
    REAL_DATA 배열 형태로 변환합니다. (지금까지 대화창에서 반복했던
    병합 스크립트와 동일한 로직입니다.)
    """
    result = []
    for tid, entry in history.items():
        view_history = entry.get("viewHistory", [])
        view_dates = entry.get("viewDates", [])

        growth_pct = None
        if len(view_history) >= 2 and view_history[0] > 0:
            growth_pct = round(
                (view_history[-1] - view_history[0]) / view_history[0] * 100, 1
            )

        result.append({
            "titleId": int(tid),
            "titleName": entry.get("titleName"),
            "author": entry.get("author"),
            "authorNames": entry.get("authorNames") or [],
            "genre": entry.get("genre"),
            "viewCount": view_history[-1] if view_history else 0,
            "starScore": round(entry.get("starScore") or 0, 5),   # 분석이 파이썬 계산과 같은 값을 쓰도록 소수점 5자리까지 보존 (화면에는 toFixed로 표시)
            "up": entry.get("up", False),
            "bestChallengeLevelUp": entry.get("bestChallengeLevelUp", False),
            "finish": entry.get("finish"),
            "webtoonLevelCode": entry.get("webtoonLevelCode"),
            "thumbnailUrl": entry.get("thumbnailUrl"),
            "titleUrl": entry.get("titleUrl"),
            "signals": entry.get("signals", []),
            "episodeCount": entry.get("episodeCount"),
            "cadenceDays": entry.get("cadenceDays"),
            "latestSubtitle": entry.get("latestSubtitle"),
            "latestDate": entry.get("latestDate"),
            "firstEpisodeDate": entry.get("firstEpisodeDate"),
            "posterThumbnailUrl": entry.get("posterThumbnailUrl"),
            "deepCheckedAt": entry.get("deepCheckedAt"),
            "episodeDates": entry.get("episodeDates"),
            "latestNo": entry.get("latestNo"),
            "firstNo": entry.get("firstNo"),
            "favoriteCount": entry.get("favoriteCount"),
            "favoriteDates": entry.get("favoriteDates") or [],
            "favoriteValues": entry.get("favoriteValues") or [],
            "keywords": entry.get("keywords", []),
            "updateRank": entry.get("updateRank"),
            "allUpdateRank": entry.get("allUpdateRank"),
            "viewHistory": view_history,
            "viewDates": view_dates,
            "growthPct": growth_pct,
        })
    return result


def load_labels() -> dict:
    """사이트에서 수동으로 분류한 결과(data/labels.json)를 읽습니다. 없거나 깨졌으면 빈 값."""
    if not LABELS_PATH.exists():
        return {}
    try:
        payload = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        print("[build_site] labels.json을 읽지 못했습니다 — 분류 없이 진행합니다.")
        return {}
    labels = payload.get("labels", payload) if isinstance(payload, dict) else {}
    return labels if isinstance(labels, dict) else {}


def load_reviews() -> dict:
    """사이트에서 기록한 작품 검토(data/labels.json 안의 reviews). 없거나 깨졌으면 빈 값."""
    if not LABELS_PATH.exists():
        return {}
    try:
        payload = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    reviews = payload.get("reviews", {}) if isinstance(payload, dict) else {}
    return reviews if isinstance(reviews, dict) else {}


def load_starts() -> dict:
    """사이트에서 직접 입력한 연재 시작일(data/labels.json의 starts). 없거나 깨졌으면 빈 값."""
    if not LABELS_PATH.exists():
        return {}
    try:
        payload = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    starts = payload.get("starts", {}) if isinstance(payload, dict) else {}
    return starts if isinstance(starts, dict) else {}


RANK_PATH = Path("data") / "rank_history.json"
RANK_DAY_KEYS = {"mon": "MONDAY", "tue": "TUESDAY", "wed": "WEDNESDAY", "thu": "THURSDAY", "fri": "FRIDAY",
                 "sat": "SATURDAY", "sun": "SUNDAY", "dailyPlus": "DAILYPLUS"}


def load_latest_ranks():
    """가장 최근 목록 순위 기록 → (날짜, {작품번호: {요일키: [인기순, 조회순, 별점순, 목록 작품 수]}}). 없으면 (None, {})."""
    if not RANK_PATH.exists():
        return None, {}
    try:
        snaps = json.loads(RANK_PATH.read_text(encoding="utf-8")).get("snapshots") or []
    except (OSError, ValueError):
        return None, {}
    if not snaps:
        return None, {}
    snap = snaps[-1]
    out = {}
    for wk, entry in (snap.get("lists") or {}).items():
        key = RANK_DAY_KEYS.get(wk)
        if not key:
            continue
        pos = {o: {tid: i + 1 for i, tid in enumerate(entry.get(o) or [])} for o in ("user", "view", "star")}
        for tid in pos["user"]:
            out.setdefault(tid, {})[key] = [pos["user"].get(tid), pos["view"].get(tid), pos["star"].get(tid), entry.get("n")]
    return snap.get("date"), out


def load_current() -> dict:
    """현재 연재작 데이터에서 분포도 페이지가 쓰는 값만 줄여서 가져옵니다. 없으면 빈 값."""
    if not CURRENT_PATH.exists():
        return {}
    try:
        raw = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    works = {}
    for tid, w in (raw.get("works") or {}).items():
        works[tid] = {k: w.get(k) for k in ("title", "author", "days", "rest", "adult", "active", "firstEpisodeDate", "episodeCount") if w.get(k) is not None}
        works[tid]["favorite"] = (w.get("favorite") or [])[-1:]        # 분포도는 가장 최근 값만 씀
    rank_date, ranks = load_latest_ranks()
    for tid, rk in ranks.items():
        if tid in works:
            works[tid]["rk"] = rk
    out = {"updated": raw.get("updated"), "works": works}
    if rank_date:
        out["rankDate"] = rank_date
    fin = (raw.get("finished") or {}).get("ids")
    if isinstance(fin, list) and fin:
        out["finishedIds"] = [str(x) for x in fin]          # 네이버 완결 탭에 있는 작품 번호 (분포도의 '완결 탭 작품' 표시용)
    return out


def load_personal() -> dict:
    """사이트에서 기록한 ★ 찜·✕ 관심없음·워치리스트 상태/메모(data/labels.json의 personal). 없거나 깨졌으면 빈 값."""
    if not LABELS_PATH.exists():
        return {}
    try:
        payload = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    personal = payload.get("personal", {}) if isinstance(payload, dict) else {}
    return personal if isinstance(personal, dict) else {}


def load_analysis() -> dict:
    """정식연재 지표 분석 결과. 없거나 깨졌으면 빈 값 (페이지에는 '아직 계산 안 됨'이 표시됨)."""
    if not ANALYSIS_PATH.exists():
        return {}
    try:
        data = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _yymmdd(text):
    """'25.01.06' 같은 날짜 글자를 date로. 못 읽으면 None."""
    import datetime as _dt
    try:
        a, b, c = str(text).split(".")
        return _dt.date(2000 + int(a), int(b), int(c))
    except (ValueError, TypeError, AttributeError):
        return None


def load_position(history: dict) -> dict:
    """'관심도 위치' 탭용: 베스트도전 작품마다 [번호, 제목, 집단, 관심 수, 연재일수, 삭제된 회차 수, 관심 수를 마지막으로 확인한 지 며칠].

    집단 0 그 외 / 1 정식연재작 / 2 챌린저스 / 3 독자PICK.
      - 선정 경로 태그(data/path_tags.json)가 '챌린저스'면 2, '독자PICK…'이고 근거가 공식 공지(A)나 목록(L)이면 3
        (메모 근거 C는 제외) — 챌린저스·독자PICK이 정식연재와 겹치면 그쪽으로 분류
      - 아니면 공식 추적 목록에 있거나 라벨이 '정식 연재 확정'이면 1, 나머지는 0
    연재일수: 정식연재작은 베스트도전에서 보낸 기간(첫 회 ~ 분류 시점, 정식 시작일이 더 빠르면 그날까지),
      나머지는 첫 회부터 데이터 기준일까지. 날짜를 모르면 None.
    삭제된 회차 수 = 마지막 회차 번호 - 남은 회차 수 (둘 다 알 때만). 표시용이며 통계에서 빼지 않음.
    data/position_exceptions.json에 적은 작품은 정식연재작이되 연재일수 None으로 두고, 화면에서 통계에서 뺌.
    """
    import datetime as _dt
    labels = load_labels()
    official = load_official_tracking()
    open_dates = {}
    for v in official.values():
        if isinstance(v, dict) and v.get("benchTitleId") and v.get("openDate"):
            open_dates[str(v["benchTitleId"])] = v["openDate"]
    try:
        tags = json.loads(PATH_TAGS_PATH.read_text(encoding="utf-8")) if PATH_TAGS_PATH.exists() else {}
    except (ValueError, OSError):
        tags = {}
    try:
        exc = json.loads(POSITION_EXC_PATH.read_text(encoding="utf-8")) if POSITION_EXC_PATH.exists() else {}
    except (ValueError, OSError):
        exc = {}
    exc = {str(k): str(v) for k, v in exc.items() if not str(k).startswith("_")}

    last_dates = [(w.get("viewDates") or [""])[-1] for w in history.values()]
    last_dates = [d for d in last_dates if d]
    if not last_dates:
        return {}
    base = _dt.date.fromisoformat(max(last_dates))

    rows, fav_dates = [], []
    for tid, w in history.items():
        fav = w.get("favoriteCount")
        if not fav:
            continue
        tag = (tags.get(tid) or [{}])[0] if isinstance(tags.get(tid), list) and tags.get(tid) else {}
        path = tag.get("path") or ""
        lb = labels.get(tid) or {}
        if path == "챌린저스":
            group = 2
        elif path.startswith("독자PICK") and tag.get("conf") in ("A", "L"):
            group = 3
        elif tid in open_dates or lb.get("status") == "confirmed" or tid in exc:
            group = 1
        else:
            group = 0
        first = _yymmdd(w.get("firstEpisodeDate"))
        if tid in exc:
            days = None
        elif group == 1:
            end = _yymmdd(lb.get("noticeDate"))
            if end and tid in open_dates:
                try:
                    end = min(end, _dt.date.fromisoformat(open_dates[tid]))
                except ValueError:
                    pass
            days = (end - first).days if first and end and end > first else None
        else:
            days = (base - first).days if first and base > first else None
        ln, ec = w.get("latestNo"), w.get("episodeCount")
        deleted = ln - ec if isinstance(ln, int) and isinstance(ec, int) and ln >= ec else None
        fd = (w.get("favoriteDates") or [""])[-1]
        fav_age = None
        if fd:
            fav_dates.append(fd)
            try:
                fav_age = max((base - _dt.date.fromisoformat(fd)).days, 0)
            except ValueError:
                pass
        rows.append([int(tid), w.get("titleName") or "", group, int(fav), days, deleted, fav_age])
    return {"updated": base.isoformat(), "favFrom": min(fav_dates) if fav_dates else None, "favTo": max(fav_dates) if fav_dates else None,
            "exc": exc, "works": rows}


def load_official_tracking() -> dict:
    """정식 연재 추적 기록. 없거나 깨졌으면 빈 값."""
    if not OFFICIAL_PATH.exists():
        return {}
    try:
        data = json.loads(OFFICIAL_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_past_notices() -> dict:
    """지난 회차 제목 훑기 결과. 없거나 깨졌으면 빈 값."""
    if not PAST_NOTICES_PATH.exists():
        return {"scanned": {}}
    try:
        data = json.loads(PAST_NOTICES_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"scanned": {}}
    scanned = data.get("scanned") if isinstance(data, dict) else None
    return {"scanned": scanned if isinstance(scanned, dict) else {}}


def load_path_tags(history: dict) -> dict:
    """선정 경로 배지용 데이터. {titleId: [[경로, 시기, 기수/부문, 등급, 근거, 확정/추정], ...]}.

    - data/path_tags.json: 공식 명단과 제목이 일치했거나 내 라벨 메모가 경로를 적은 작품 → '확정' (근거가 AI 요약본(C)이면 '추정')
    - data/award_lookup.json: 제목 조회에서 decision이 auto인 작품 → '추정' (같은 이름의 다른 작품일 수 있음)
      사이트에 카드가 있는 작품(history에 있는 작품)만 담고, 이미 같은 경로가 확정으로 있으면 건너뜀.
    """
    out: dict[str, list] = {}
    try:
        confirmed = json.loads(PATH_TAGS_PATH.read_text(encoding="utf-8")) if PATH_TAGS_PATH.exists() else {}
    except (ValueError, OSError):
        confirmed = {}
    for tid, tags in confirmed.items():
        if tid not in history or not isinstance(tags, list):
            continue
        out[tid] = [[t.get("path"), t.get("when") or "", t.get("sub") or "", t.get("grade") or "", t.get("conf") or "", "확정" if t.get("conf") != "C" else "추정"]
                    for t in tags if isinstance(t, dict) and t.get("path")]
    try:
        lookup = json.loads(AWARD_LOOKUP_PATH.read_text(encoding="utf-8")).get("results", {}) if AWARD_LOOKUP_PATH.exists() else {}
    except (ValueError, OSError):
        lookup = {}
    for rec in lookup.values():
        if rec.get("decision") != "auto" or not rec.get("candidates"):
            continue
        tid = str(rec["candidates"][0].get("titleId"))
        if tid not in history:
            continue
        if any(t[0] == rec.get("path") for t in out.get(tid, [])):
            continue
        out.setdefault(tid, []).append([rec.get("path"), rec.get("when") or "", rec.get("sub") or "", rec.get("grade") or "",
                                        rec.get("conf") or "", "추정"])
    return out


def to_js_literal(obj) -> str:
    """JSON을 <script> 안에 안전하게 넣을 문자열로 만듭니다 (</script> 방지)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def main() -> None:
    if not HISTORY_PATH.exists():
        print(f"[build_site] {HISTORY_PATH}가 없습니다 — 크롤러가 먼저 실행돼야 합니다.")
        return
    if not SITE_PATH.exists():
        print(f"[build_site] {SITE_PATH}가 저장소 루트에 없습니다 — 한 번은 직접 올려둬야 합니다.")
        return

    # 분석 결과를 먼저 새로 계산함 (분석 패키지가 없거나 실패해도 사이트 빌드는 계속 진행)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))   # 같은 폴더의 build_analysis.py를 찾도록
        import build_analysis
        build_analysis.main()
    except Exception as e:   # noqa: BLE001
        print(f"[build_site] 분석 계산을 건너뜁니다: {e}")

    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    real_data = build_real_data(history)
    data_literal = to_js_literal(real_data)

    html = SITE_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"  const REAL_DATA = \[.*?\];\n", re.DOTALL)
    match = pattern.search(html)
    if not match:
        print("[build_site] REAL_DATA 선언부를 못 찾았습니다 — HTML 구조가 바뀐 것 같습니다.")
        return

    new_html = html[:match.start()] + f"  const REAL_DATA = {data_literal};\n" + html[match.end():]

    # 수동 분류 결과(data/labels.json)를 사이트 기본값(SAVED_LABELS)으로 포함
    labels = load_labels()
    labels_match = re.compile(r"  const SAVED_LABELS = \{.*?\};\n", re.DOTALL).search(new_html)
    if labels_match:
        new_html = (new_html[:labels_match.start()]
                    + f"  const SAVED_LABELS = {to_js_literal(labels)};\n"
                    + new_html[labels_match.end():])
    else:
        print("[build_site] SAVED_LABELS 선언부를 못 찾아 분류 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    # 작품 검토 기록(data/labels.json의 reviews)도 같은 방식으로 사이트 기본값(SAVED_REVIEWS)에 포함
    reviews = load_reviews()
    reviews_match = re.compile(r"  const SAVED_REVIEWS = \{.*?\};\n", re.DOTALL).search(new_html)
    if reviews_match:
        new_html = (new_html[:reviews_match.start()]
                    + f"  const SAVED_REVIEWS = {to_js_literal(reviews)};\n"
                    + new_html[reviews_match.end():])
    else:
        print("[build_site] SAVED_REVIEWS 선언부를 못 찾아 검토 기록 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    # ★ 찜·✕ 관심없음·워치리스트 메모(data/labels.json의 personal)도 같은 방식으로 사이트 기본값(SAVED_PERSONAL)에 포함
    personal = load_personal()
    personal_match = re.compile(r"  const SAVED_PERSONAL = \{.*?\};\n", re.DOTALL).search(new_html)
    if personal_match:
        new_html = (new_html[:personal_match.start()]
                    + f"  const SAVED_PERSONAL = {to_js_literal(personal)};\n"
                    + new_html[personal_match.end():])
    else:
        print("[build_site] SAVED_PERSONAL 선언부를 못 찾아 찜·관심없음 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    official = load_official_tracking()
    official_match = re.compile(r"  const OFFICIAL_TRACKING = \{.*?\};\n", re.DOTALL).search(new_html)
    if official_match:
        new_html = (new_html[:official_match.start()]
                    + f"  const OFFICIAL_TRACKING = {to_js_literal(official)};\n"
                    + new_html[official_match.end():])
    else:
        print("[build_site] OFFICIAL_TRACKING 선언부를 못 찾아 정식 추적 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    path_tags = load_path_tags(history)
    path_match = re.compile(r"  const PATH_TAGS = \{.*?\};\n", re.DOTALL).search(new_html)
    if path_match:
        new_html = (new_html[:path_match.start()]
                    + f"  const PATH_TAGS = {to_js_literal(path_tags)};\n"
                    + new_html[path_match.end():])
    else:
        print("[build_site] PATH_TAGS 선언부를 못 찾아 선정 경로 배지 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    badge_names = json.loads(BADGE_NAMES_PATH.read_text(encoding="utf-8")) if BADGE_NAMES_PATH.exists() else None
    names_match = re.compile(r"  const BADGE_NAMES = \{.*?\};\n", re.DOTALL).search(new_html)
    if badge_names is not None and names_match:
        new_html = (new_html[:names_match.start()]
                    + f"  const BADGE_NAMES = {to_js_literal(badge_names)};\n"
                    + new_html[names_match.end():])

    for const_name, value in (("CURRENT_WEBTOONS", load_current()), ("SAVED_STARTS", load_starts())):
        m = re.compile(rf"  const {const_name} = \{{.*?\}};\n", re.DOTALL).search(new_html)
        if m:
            new_html = new_html[:m.start()] + f"  const {const_name} = {to_js_literal(value)};\n" + new_html[m.end():]
        else:
            print(f"[build_site] {const_name} 선언부를 못 찾아 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    # 관심도 위치 탭용 베스트도전 작품 목록(BC_POSITION)
    pos_match = re.compile(r"  const BC_POSITION = \{.*?\};\n", re.DOTALL).search(new_html)
    position = load_position(history)
    if pos_match:
        new_html = new_html[:pos_match.start()] + f"  const BC_POSITION = {to_js_literal(position)};\n" + new_html[pos_match.end():]
    else:
        print("[build_site] BC_POSITION 선언부를 못 찾아 관심도 위치 탭 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    analysis = load_analysis()
    analysis_match = re.compile(r"  const ANALYSIS = \{.*?\};", re.DOTALL).search(new_html)
    if analysis_match:
        new_html = (new_html[:analysis_match.start()]
                    + f"  const ANALYSIS = {to_js_literal(analysis)};"
                    + new_html[analysis_match.end():])
    else:
        print("[build_site] ANALYSIS 선언부를 못 찾아 분석 결과 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    past = load_past_notices()
    past_match = re.compile(r"  const PAST_NOTICES = \{.*?\};\n", re.DOTALL).search(new_html)
    if past_match:
        new_html = (new_html[:past_match.start()]
                    + f"  const PAST_NOTICES = {to_js_literal(past)};\n"
                    + new_html[past_match.end():])
    else:
        print("[build_site] PAST_NOTICES 선언부를 못 찾아 지난 회차 공지 후보 반영을 건너뜁니다 (HTML을 최신 버전으로 올려주세요).")

    SITE_PATH.write_text(new_html, encoding="utf-8")
    print(f"[build_site] 완료 — {len(real_data)}개 작품, 분류 {len(labels)}건, 검토 기록 {len(reviews)}건, 찜·관심없음 기록 {len(personal)}건, 정식 추적 {len(official)}건, 지난 회차 훑은 작품 {len(past["scanned"])}개, 분석 결과 {"있음" if analysis.get("computedAt") else "없음"} 반영, 관심도 위치 {len(position.get("works", []))}작품, 선정 경로 배지 {len(path_tags)}작품, {SITE_PATH} 갱신됨")


if __name__ == "__main__":
    main()
