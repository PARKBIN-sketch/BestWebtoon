"""
probe_sort.py — 요일웹툰 목록에서 정렬(인기순·업데이트순·조회순·별점순)과 조회수를 읽을 수 있는지 "시험"만 합니다.
읽기만 하고 기존 데이터는 건드리지 않습니다. 결과: data/sort_probe.json

확인하는 것
  1) 요일 목록(weekday), 매일+(dailyPlus), 완결(finished) 주소가 응답하는지, 작품 수가 몇 개인지
  2) order 값을 바꿔 보면 순서가 바뀌는지 (순서가 바뀌면 그 순서 자체가 정렬 정보)
  3) viewCount가 0이 아닌 값으로 오는 경우가 있는지 / 별점(starScore)이 오는지
주소와 order 값은 확실하지 않아 여러 후보를 모두 시도하고, 성공/실패를 그대로 기록합니다.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler

OUT = Path("data") / "sort_probe.json"
BASE = "https://comic.naver.com/api/webtoon/titlelist"
ORDERS = ["", "user", "update", "view", "star", "USER", "UPDATE", "VIEW", "STAR", "popularity", "viewCount", "starScore"]

TARGETS = [                                   # (이름, 주소, 목록 위치)
    ("weekday", f"{BASE}/weekday", "titleListMap"),
    ("weekday_mon", f"{BASE}/weekday?week=MONDAY", "titleListMap"),
    ("dailyPlus", f"{BASE}/weekday?week=DAILY", "titleListMap"),
    ("dailyPlus2", f"{BASE}/weekday?week=DAILYPLUS", "titleListMap"),
    ("finished_p1", f"{BASE}/finished?page=1", "titleList"),
]


def get(url):
    try:
        r = requests.get(url, headers=crawler.HEADERS, timeout=20)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, (r.text[:200] if body is None else "")
    except Exception as e:
        return None, None, repr(e)[:200]


def flatten(body, key):
    """응답에서 작품 목록(요일별이면 합침)을 꺼냄."""
    if not isinstance(body, dict):
        return []
    m = body.get(key)
    if isinstance(m, dict):
        return [it for v in m.values() if isinstance(v, list) for it in v]
    if isinstance(m, list):
        return m
    for v in body.values():                   # 키가 다르면 첫 번째 리스트를 씀
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def summarize(items):
    ids = [str(i.get("titleId")) for i in items]
    vc = [i.get("viewCount") for i in items]
    ss = [i.get("starScore") for i in items]
    return {
        "count": len(items), "keys": sorted(items[0].keys()) if items else [],
        "first10": [(i.get("titleId"), i.get("titleName"), i.get("viewCount"), i.get("starScore")) for i in items[:10]],
        "viewCount_nonzero": sum(1 for v in vc if v), "viewCount_max": max([v for v in vc if isinstance(v, (int, float))] or [None]),
        "starScore_nonnull": sum(1 for v in ss if v), "ids": ids,
    }


def main():
    out = {"results": [], "pagination_note": ""}
    for name, url, key in TARGETS:
        base_ids = None
        for order in ORDERS:
            u = url + (("&" if "?" in url else "?") + f"order={order}" if order else "")
            status, body, err = get(u)
            items = flatten(body, key) if status == 200 else []
            s = summarize(items) if items else {}
            ids = s.pop("ids", [])
            if order == "":
                base_ids = ids
            rec = {"name": name, "url": u, "status": status, "err": err, **s}
            if ids and base_ids:
                rec["same_order_as_default"] = ids == base_ids
                rec["same_set_as_default"] = set(ids) == set(base_ids)
            out["results"].append(rec)
            print(name, order or "(기본)", status, s.get("count"), "nonzeroView", s.get("viewCount_nonzero"), "same_order", rec.get("same_order_as_default"))
            time.sleep(0.6)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
