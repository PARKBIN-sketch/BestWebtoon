"""
probe_current.py — 현재 연재 중인 정식연재(요일웹툰) 작품 목록과 관심 수를 가져올 수 있는지 "시험"만 해 봅니다.

하는 일 (읽기만 하고, 기존 데이터는 건드리지 않습니다)
  1) 요일별 연재 목록 주소가 응답하는지, 작품 번호·제목·요일·장르 같은 항목이 들어 있는지 확인
  2) 그중 몇 작품(기본 5개)을 골라 작품 정보 주소에서 관심 수(favoriteCount)와 첫 회 날짜가 오는지 확인
  3) 응답 모양을 data/current_probe.json에 저장 → 이 파일을 보고 본 수집기를 설계합니다.

사용:  python probe_current.py            (5작품 시험)
       python probe_current.py --sample 10
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scouting_desk_crawler as crawler   # 헤더·요청 간격·작품 정보 조회를 그대로 씀

OUT_PATH = Path("data") / "current_probe.json"
LIST_URLS = [                                  # 앞에서부터 모두 시도해서 모양을 기록합니다.
    "https://comic.naver.com/api/webtoon/titlelist/weekday",
    "https://comic.naver.com/api/webtoon/titlelist/weekday?order=user",
]


def shape(obj, depth=0):
    """응답 구조를 짧게 요약 (키 이름과 값의 종류만)."""
    if depth > 3:
        return "…"
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return [f"list({len(obj)})", shape(obj[0], depth + 1)] if obj else ["list(0)"]
    return type(obj).__name__


def find_items(obj, out):
    """응답 안에서 titleId와 titleName을 가진 항목을 모두 모읍니다 (구조가 달라도 찾도록)."""
    if isinstance(obj, dict):
        if "titleId" in obj and "titleName" in obj:
            out.append(obj)
        for v in obj.values():
            find_items(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_items(v, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=5)
    args = ap.parse_args()

    result = {"lists": [], "samples": []}
    picked = []
    for url in LIST_URLS:
        rec = {"url": url}
        try:
            res = requests.get(url, headers=crawler.HEADERS, timeout=15)
            rec["http_status"] = res.status_code
            if res.status_code == 200:
                data = res.json()
                rec["shape"] = shape(data)
                items = find_items(data, [])
                rec["item_count"] = len(items)
                rec["item_keys"] = sorted({k for it in items[:50] for k in it})
                rec["first_item"] = items[0] if items else None
                if items and not picked:
                    step = max(1, len(items) // max(1, args.sample))
                    picked = items[::step][: args.sample]
        except Exception as exc:               # 어떤 실패든 기록만 하고 계속
            rec["error"] = str(exc)
        result["lists"].append(rec)
        time.sleep(crawler.REQUEST_DELAY_SEC)

    for it in picked:
        tid = it.get("titleId")
        rec = {"titleId": tid, "titleName": it.get("titleName")}
        try:
            info = crawler.fetch_title_info(int(tid))
            rec["info"] = {k: info.get(k) for k in ("status", "favoriteCount", "webtoonLevelCode", "finish", "http_status", "error") if k in info}
            time.sleep(crawler.REQUEST_DELAY_SEC)
            deep = crawler.fetch_deep_info(int(tid))
            rec["deep"] = {k: deep.get(k) for k in ("episodeCount", "firstEpisodeDate", "latestDate", "cadenceDays")}
        except Exception as exc:
            rec["error"] = str(exc)
        result["samples"].append(rec)
        time.sleep(crawler.REQUEST_DELAY_SEC)

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [l for l in result["lists"] if l.get("item_count")]
    print(f"[probe] 목록 주소 {len(ok)}/{len(LIST_URLS)}개 응답 · 항목 {max([l.get('item_count', 0) for l in result['lists']] or [0])}개 · 시험 작품 {len(result['samples'])}개 → {OUT_PATH}")


if __name__ == "__main__":
    main()
