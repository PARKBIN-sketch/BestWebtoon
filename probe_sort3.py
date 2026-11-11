"""
probe_sort3.py — 3차 시험 (읽기만 함). 결과: data/sort_probe3.json
화면이 실제로 쓰는 주소 형식으로 시험합니다.
  https://comic.naver.com/api/webtoon/titlelist/weekday?week=dailyPlus&order=user  → {"titleList": [...]}
 1) week = mon,tue,wed,thu,fri,sat,sun,dailyPlus  ×  order = user,update,view,star (소문자)
    - 각 목록의 작품 수, viewCount가 0이 아닌 작품 수, 작품 번호·viewCount·순위
    - 요일 값이 맞는지(요일별 작품 수가 기존 수집과 맞는지)
 2) 완결 목록: finished?page=N&order=user/view/star 의 전체 쪽수·작품 수
"""
import json, sys, time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler

OUT = Path("data") / "sort_probe3.json"
B = "https://comic.naver.com/api/webtoon/titlelist"
WEEKS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun", "dailyPlus"]
ORDERS = ["user", "update", "view", "star"]


def get(url):
    try:
        r = requests.get(url, headers=crawler.HEADERS, timeout=20)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text[:200]
    except Exception as e:
        return None, repr(e)[:200]


def main():
    out = {"lists": {}, "summary": [], "finished": {}}
    for w in WEEKS:
        for o in ORDERS:
            url = f"{B}/weekday?week={w}&order={o}"
            s, b = get(url)
            lst = b.get("titleList") if isinstance(b, dict) else None
            if not isinstance(lst, list):
                out["summary"].append({"week": w, "order": o, "status": s, "keys": list(b.keys())[:6] if isinstance(b, dict) else str(b)[:100]})
                print(w, o, s, "titleList 없음")
                time.sleep(0.5)
                continue
            out["lists"][f"{w}|{o}"] = [[i["titleId"], i.get("viewCount"), i.get("starScore")] for i in lst]
            out["summary"].append({"week": w, "order": o, "status": s, "count": len(lst),
                                   "viewCount_nonzero": sum(1 for i in lst if i.get("viewCount")),
                                   "adult": sum(1 for i in lst if i.get("adult")), "rest": sum(1 for i in lst if i.get("rest")),
                                   "top5": [i.get("titleName") for i in lst[:5]]})
            print(w, o, s, len(lst), "view≠0:", out["summary"][-1]["viewCount_nonzero"])
            time.sleep(0.5)
    for o in ["user", "view", "star"]:
        pages, tot, ids = [], 0, []
        for p in range(1, 80):
            s, b = get(f"{B}/finished?page={p}&order={o}")
            lst = b.get("titleList") if isinstance(b, dict) else None
            if p == 1 and isinstance(b, dict):
                out["finished"][f"{o}_top"] = {k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in b.items()}
            if not lst:
                break
            tot += len(lst)
            pages.append([p, len(lst), sum(1 for i in lst if i.get("viewCount"))])
            ids += [[i["titleId"], i.get("viewCount"), i.get("starScore")] for i in lst]
            time.sleep(0.5)
        out["finished"][o] = {"pages": len(pages), "total": tot, "view_nonzero": sum(1 for x in ids if x[1]), "list": ids}
        print("finished", o, "쪽수", len(pages), "작품", tot)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
