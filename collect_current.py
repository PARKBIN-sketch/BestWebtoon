"""
collect_current.py — 현재 연재 중인 정식연재(요일웹툰) 작품의 관심 수와 연재 시작일을 모아 둡니다.

왜 필요한가
  "어느 정도 관심 수면 좋은 성적인가"를 보려면 현재 정식연재 작품 전체의 관심 수 분포가 기준선이 됩니다.
  (스카우팅 데스크의 분포도 페이지가 이 파일을 읽습니다.)

무엇을 모으나 (작품 번호 하나가 한 작품 — 같은 작품이 여러 요일에 나오면 요일만 합쳐서 한 번만 셉니다)
  요일 목록(연재 중인 작품 전체) → 작품마다: 제목·작가·요일들·별점·휴재 여부
  작품 정보 주소 → 관심 수(favoriteCount), 오늘 값을 날짜와 함께 쌓음
  회차 목록 1페이지 → 연재 시작일(첫 화 날짜)·회차 수  ※ 한 번 얻으면 바뀌지 않아서 이후엔 다시 받지 않음
  성인 작품은 회차 목록을 못 읽는 경우가 있어 연재 시작일이 비어 있을 수 있음(2번 시도 후 포기)

  매일+ 목록(요일과 겹치지 않는 별도 목록) → 요일 항목에 'DAILYPLUS'로 함께 모음
  완결 목록(finished, 여러 쪽) → 작품 번호만 store["finished"]["ids"]에 저장 (분포도에서 '네이버 완결 탭에 있음' 표시에 씀)

출력  data/current_webtoons.json
  {"version":1,"updated":"YYYY-MM-DD","works":{"<번호>":{title,author,days,starScore,rest,adult,
     firstEpisodeDate,episodeCount,dates:[...],favorite:[...],active,lastSeen}}, "dupNames":[...]}

사용
  python collect_current.py --finished-only   # 완결 목록 번호만 새로 받음 (1~2분)
  python collect_current.py --limit 10     # 10작품만 시험
  python collect_current.py                # 전부 (하루 안에 끊기면 다시 실행해도 이어서 함)

같은 제목·작가인데 번호가 다른 작품은 합치지 않고 dupNames에 적어 둡니다(리메이크·시즌 분리일 수 있어서 사람이 확인).
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler

OUT_PATH = Path("data") / "current_webtoons.json"
LIST_URL = "https://comic.naver.com/api/webtoon/titlelist/weekday"
FINISHED_URL = "https://comic.naver.com/api/webtoon/titlelist/finished"
MIN_FINISHED = 1000         # 이보다 적게 받으면 오류로 보고 기존 값을 지우지 않음
SAVE_EVERY = 50
MAX_HISTORY = 400           # 날짜별 관심 수 기록 최대 개수
FIRST_TRY_LIMIT = 2         # 연재 시작일을 못 얻는 작품(성인 등)은 이 횟수까지만 시도


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", unicodedata.normalize("NFKC", s or "").lower())


def fetch_list():
    res = requests.get(LIST_URL, headers=crawler.HEADERS, timeout=20)
    res.raise_for_status()
    works = {}
    for day, items in (res.json().get("titleListMap") or {}).items():
        for it in items:
            tid = str(it.get("titleId"))
            w = works.setdefault(tid, {
                "title": it.get("titleName"), "author": it.get("author"), "days": [],
                "starScore": it.get("starScore"), "rest": bool(it.get("rest")), "adult": bool(it.get("adult")),
                "finish": bool(it.get("finish")),
            })
            if day not in w["days"]:
                w["days"].append(day)
    # 매일+는 요일 목록에 들어 있지 않은 별도 목록 (week=dailyPlus 는 {"titleList": [...]} 로 옴)
    res = requests.get(LIST_URL, params={"week": "dailyPlus", "order": "user"}, headers=crawler.HEADERS, timeout=20)
    res.raise_for_status()
    plus = res.json().get("titleList")
    if not isinstance(plus, list):
        raise RuntimeError("매일+ 목록 모양이 달라요 (titleList 없음)")
    for it in plus:
        tid = str(it.get("titleId"))
        w = works.setdefault(tid, {
            "title": it.get("titleName"), "author": it.get("author"), "days": [],
            "starScore": it.get("starScore"), "rest": bool(it.get("rest")), "adult": bool(it.get("adult")),
            "finish": bool(it.get("finish")),
        })
        if "DAILYPLUS" not in w["days"]:
            w["days"].append("DAILYPLUS")
    return works


def fetch_finished():
    """완결 목록 전체(쪽마다 약 45개)에서 작품 번호만 모음. 끝까지 못 읽으면 None."""
    ids, seen = [], set()
    for page in range(1, 200):
        try:
            res = requests.get(FINISHED_URL, params={"page": page, "order": "user"}, headers=crawler.HEADERS, timeout=20)
            res.raise_for_status()
            lst = res.json().get("titleList") or []
        except (requests.RequestException, ValueError):
            return None
        if not lst:
            break
        for it in lst:
            tid = str(it.get("titleId"))
            if tid not in seen:
                seen.add(tid); ids.append(tid)
        time.sleep(0.5)
    return ids if len(ids) >= MIN_FINISHED else None


def fetch_first(tid):
    """회차 목록 1페이지(오래된 순)에서 연재 시작일·회차 수를 얻음. 못 얻으면 (None, None)."""
    url = crawler.EPISODE_LIST_URL_TEMPLATE.format(title_id=tid, page=1)
    try:
        res = requests.get(url, headers=crawler.HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError):
        return None, None
    eps = data.get("articleList") or []
    first = eps[0].get("serviceDateDescription") if eps else None
    return first, (data.get("pageInfo") or {}).get("totalRows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="시험용: 이 개수만 조회")
    ap.add_argument("--finished-only", action="store_true", help="완결 목록 번호만 새로 받고 끝냄")
    args = ap.parse_args()

    today = date.today().isoformat()
    store = {"version": 1, "works": {}}
    if OUT_PATH.exists():
        store = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    works = store.setdefault("works", {})

    fin = fetch_finished()
    if fin is not None:
        store["finished"] = {"updated": today, "ids": fin}
        print(f"[collect] 완결 목록: {len(fin)}개")
    else:
        print("[collect] 완결 목록을 끝까지 읽지 못해 기존 값을 그대로 둡니다")
    if args.finished_only:
        OUT_PATH.parent.mkdir(exist_ok=True)
        OUT_PATH.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"[collect] 완결 목록만 갱신 → {OUT_PATH}")
        return

    current = fetch_list()
    print(f"[collect] 요일 목록: 작품 {len(current)}개 (요일 중복 제거 후)")
    for tid, meta in current.items():                     # 목록 정보는 매번 최신으로 덮어씀
        w = works.setdefault(tid, {"dates": [], "favorite": []})
        w.update(meta)
        w["active"] = True
        w["lastSeen"] = today
    for tid, w in works.items():                          # 목록에서 사라진 작품은 지우지 않고 표시만
        if tid not in current:
            w["active"] = False

    names = {}
    for tid, w in works.items():
        if w.get("active"):
            names.setdefault((norm(w.get("title")), norm(w.get("author"))), []).append(tid)
    store["dupNames"] = [{"title": works[ids[0]]["title"], "author": works[ids[0]]["author"], "ids": ids}
                         for ids in names.values() if len(ids) > 1]
    if store["dupNames"]:
        print(f"[collect] 제목·작가가 같고 번호가 다른 작품 {len(store['dupNames'])}건 → dupNames 확인 필요")

    todo = [tid for tid in current if (works[tid].get("lastDate") != today)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[collect] 오늘 조회할 작품 {len(todo)}개")

    done = 0
    for tid in todo:
        w = works[tid]
        info = crawler.fetch_title_info(int(tid))
        time.sleep(crawler.REQUEST_DELAY_SEC)
        fav = info.get("favoriteCount") if info.get("status") == "ok" else None
        if fav is not None:
            if w["dates"] and w["dates"][-1] == today:
                w["favorite"][-1] = fav
            else:
                w["dates"].append(today); w["favorite"].append(fav)
            w["dates"], w["favorite"] = w["dates"][-MAX_HISTORY:], w["favorite"][-MAX_HISTORY:]
        if not w.get("firstEpisodeDate") and w.get("firstTries", 0) < FIRST_TRY_LIMIT:
            first, rows = fetch_first(tid)
            w["firstTries"] = w.get("firstTries", 0) + 1
            if first:
                w["firstEpisodeDate"], w["episodeCount"] = first, rows
            time.sleep(crawler.REQUEST_DELAY_SEC)
        w["lastDate"] = today
        done += 1
        if done % SAVE_EVERY == 0:
            store["updated"] = today
            OUT_PATH.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"[collect] {done}/{len(todo)} 저장")

    store["updated"] = today
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with_fav = sum(1 for w in works.values() if w.get("active") and w.get("favorite"))
    with_first = sum(1 for w in works.values() if w.get("active") and w.get("firstEpisodeDate"))
    print(f"[collect] 완료 — 연재 중 {sum(1 for w in works.values() if w.get('active'))}개 · 관심 수 {with_fav}개 · 연재 시작일 {with_first}개 → {OUT_PATH}")


if __name__ == "__main__":
    main()
