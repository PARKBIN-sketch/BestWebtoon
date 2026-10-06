"""
backfill_history.py — data/history.json의 상세 확인 값을 일별 스냅샷에서 복구하는 일회성 스크립트

배경: 이전 버전의 update_history가 상세 확인(딥체크) 값(화수·최신 회차·연재주기·키워드 등)을
매일 "오늘 확인 안 한 작품의 빈 값"으로 덮어써서, history.json에는 가장 최근 실행에서 확인한
작품(약 250개)의 정보만 남아 있었습니다. 반면 data/YYYY-MM-DD.json 일별 스냅샷에는 그날
상세 확인한 작품의 값이 그대로 남아 있으므로, 날짜순으로 읽어서 되살립니다.

사용법 (저장소 루트에서, 한 번만):
    python backfill_history.py

규칙:
  - 작품마다 "가장 최근에 상세 확인된 값"을 채우고, 그 날짜를 deepCheckedAt에 기록합니다.
  - history.json에 이미 상세 값이 있는데 확인 날짜가 없으면, 그 값은 가장 최근 실행에서 온 것이므로
    history의 마지막 날짜를 확인 날짜로 간주해서 더 오래된 스냅샷 값이 덮어쓰지 않게 합니다.
  - 복구한 값은 며칠 전 상태일 수 있습니다. 다음 크롤러 실행부터는 최근 공지가 최신 회차인 작품을
    매일 다시 확인하고, 나머지는 순환 스캔으로 차례대로 갱신됩니다.
"""
import json
from pathlib import Path

DATA_DIR = Path("data")
HISTORY_PATH = DATA_DIR / "history.json"
HIATUS_CADENCE_DAYS = 60   # scouting_desk_crawler.py의 값과 같아야 함

DEEP_FIELDS = ["episodeCount", "cadenceDays", "latestSubtitle", "latestDate", "keywords",
               "firstEpisodeDate", "posterThumbnailUrl"]


def is_hiatus(entry: dict) -> bool:
    if "확정" in (entry.get("latestSubtitle") or ""):
        return False
    cadence = entry.get("cadenceDays")
    return cadence is not None and cadence >= HIATUS_CADENCE_DAYS


def main() -> None:
    if not HISTORY_PATH.exists():
        print("data/history.json이 없습니다. 저장소 루트에서 실행했는지 확인하세요.")
        return
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    before = sum(1 for e in history.values() if e.get("episodeCount") is not None)

    # 이미 상세 값이 있는데 확인 날짜가 없는 항목 = 가장 최근 실행에서 온 값
    for entry in history.values():
        if entry.get("episodeCount") is not None and not entry.get("deepCheckedAt"):
            dates = entry.get("viewDates") or []
            entry["deepCheckedAt"] = dates[-1] if dates else "0000-00-00"

    files = sorted(DATA_DIR.glob("????-??-??.json"))
    applied = 0
    for f in files:
        snap_date = f.stem
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            print(f"  건너뜀(읽기 실패): {f.name}")
            continue
        for item in items:
            if item.get("episodeCount") is None:          # 그날 상세 확인을 안 한 작품
                continue
            entry = history.get(str(item.get("titleId")))
            if entry is None:
                continue
            if snap_date <= (entry.get("deepCheckedAt") or ""):
                continue                                   # 이미 더 최근 값이 있음
            for field in DEEP_FIELDS:
                value = item.get(field)
                if value is None and field in ("firstEpisodeDate", "posterThumbnailUrl"):
                    continue
                if value is not None or field == "keywords":
                    entry[field] = value if value is not None else []
            entry["deepCheckedAt"] = snap_date
            applied += 1

    # 장기휴재 의심은 연재주기에서 나오므로, 복구된 값 기준으로 다시 계산
    for entry in history.values():
        signals = [s for s in (entry.get("signals") or []) if s != "hiatus_suspect"]
        if is_hiatus(entry):
            signals.append("hiatus_suspect")
        entry["signals"] = signals

    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    after = sum(1 for e in history.values() if e.get("episodeCount") is not None)
    print(f"스냅샷 {len(files)}개를 읽어 {applied}건을 반영했습니다.")
    print(f"상세 정보가 있는 작품: {before}개 → {after}개 (전체 {len(history)}개)")


if __name__ == "__main__":
    main()
