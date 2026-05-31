# -*- coding: utf-8 -*-
"""
鉄輪式三列戦車レース 演出付きMVPアプリ

起動:
    pip install flask
    python app.py

画面:
    GM管理画面:        http://127.0.0.1:5000/control
    Discord共有画面:   http://127.0.0.1:5000/display

このMVPは、sim_engine.py の Ver.0.3 簡易シミュレーターを利用し、
1レース分の詳細ログをイベント列に変換してブラウザ上で再生します。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional
import random
import re

from flask import Flask, jsonify, render_template, request

import sim_engine

app = Flask(__name__)

ROUND_INFO = {
    1: {
        "name": "発走直線",
        "text": "鉄輪の鐘が鳴り、六台の戦車が一斉に飛び出す。最初に前へ出るのはどの車体か。",
    },
    2: {
        "name": "第一カーブ",
        "text": "石畳の急カーブへ戦車が雪崩れ込む。内側を刺す者、外から速度を保つ者、隊列が大きく揺れる。",
    },
    3: {
        "name": "混戦直線",
        "text": "直線に戻った瞬間、砲声と車輪の軋みが混ざる。ここから妨害が激しくなる。",
    },
    4: {
        "name": "障害帯",
        "text": "瓦礫、段差、可動柵。無理に速度を出せば、車体ごと跳ね飛ばされる危険な区間だ。",
    },
    5: {
        "name": "第二カーブ・鉄輪橋",
        "text": "鉄輪橋へ向かう最後の大カーブ。ここで崩れれば、最終直線には届かない。",
    },
    6: {
        "name": "最終直線",
        "text": "観客席が揺れる。ゴールラインは目前。残った駆動力と先行点が最後の差になる。",
    },
}

PROGRAM_LABELS = {
    "standard": "標準公式戦",
    "speed": "高速戦",
    "technique": "技巧戦",
    "heavy": "重装戦",
    "shooting": "射撃戦",
    "chaos": "荒れ場戦",
}

STATE: Dict[str, Any] = {
    "race": None,
    "index": 0,
}


def tank_to_public_dict(t: sim_engine.TankSpec) -> Dict[str, Any]:
    return {
        "name": t.name,
        "style": t.style,
        "rank": t.rank,
        "grade_points": sim_engine.tank_grade_points(t),
        "mobility": t.mobility,
        "handling": t.handling,
        "armor": t.armor,
        "firepower": t.firepower,
        "stability": t.stability,
        "drive": t.drive,
        "ammo": t.ammo,
        "hp": t.hp,
    }


def initial_board(specs: List[sim_engine.TankSpec]) -> Dict[str, Dict[str, Any]]:
    return {
        s.name: {
            "name": s.name,
            "style": s.style,
            "area": "中列",
            "lead": 0,
            "hp": s.hp,
            "maxHp": s.hp,
            "stability": s.stability,
            "maxStability": s.stability,
            "drive": s.drive,
            "ammo": s.ammo,
            "retired": False,
            "highlight": "",
        }
        for s in specs
    }


def parse_status_line(line: str, board: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # 例: 1.黄金王獅子[前列 先2 HP21 安4 駆3 弾2]
    pattern = re.compile(r"\d+\.([^\[]+)\[(後列|中列|前列) 先(-?\d+) HP(-?\d+) 安(-?\d+) 駆(-?\d+) 弾(-?\d+)\]")
    new_board = {k: dict(v) for k, v in board.items()}
    for m in pattern.finditer(line):
        name, area, lead, hp, stability, drive, ammo = m.groups()
        name = name.strip()
        if name not in new_board:
            continue
        new_board[name].update({
            "area": area,
            "lead": int(lead),
            "hp": int(hp),
            "stability": int(stability),
            "drive": int(drive),
            "ammo": int(ammo),
        })
    return new_board


def final_board_from_states(states: List[sim_engine.TankState], board: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    new_board = {k: dict(v) for k, v in board.items()}
    for st in states:
        if st.name not in new_board:
            continue
        new_board[st.name].update({
            "area": st.area.jp,
            "lead": st.lead,
            "hp": st.hp,
            "stability": st.stability,
            "drive": st.drive,
            "ammo": st.ammo,
            "retired": st.retired,
        })
    return new_board


def actor_from_log(line: str, names: List[str]) -> Optional[str]:
    for n in names:
        if n in line:
            return n
    return None


def classify_log_line(line: str) -> str:
    if "事故判定" in line or "大破" in line or "横転" in line or "激突" in line:
        return "accident"
    if "命中" in line:
        return "hit"
    if "失敗" in line:
        return "failure"
    if "成功" in line or "大成功" in line:
        return "success"
    return "log"


def log_to_events(
    log_lines: List[str],
    specs: List[sim_engine.TankSpec],
    result: sim_engine.RaceResult,
    rank: str,
    program: str,
    seed: int,
) -> List[Dict[str, Any]]:
    names = [s.name for s in specs]
    board = initial_board(specs)
    events: List[Dict[str, Any]] = []

    events.append({
        "type": "title",
        "title": f"{rank}級 {PROGRAM_LABELS.get(program, program)}",
        "text": "グランド・サーキット・アルカ、出走準備完了。鉄輪会の旗が振り上げられる。",
        "board": board,
    })

    current_round = 0
    for raw in log_lines:
        line = raw.rstrip()
        if not line:
            continue

        round_match = re.match(r"=== R(\d+) ===", line.strip())
        if round_match:
            current_round = int(round_match.group(1))
            info = ROUND_INFO.get(current_round, {"name": f"第{current_round}R", "text": ""})
            events.append({
                "type": "round_start",
                "round": current_round,
                "roundName": info["name"],
                "title": f"第{current_round}R：{info['name']}",
                "text": info["text"],
                "board": board,
            })
            continue

        if "暫定順位:" in line:
            board = parse_status_line(line, board)
            events.append({
                "type": "ranking_update",
                "round": current_round,
                "title": "暫定順位更新",
                "text": line.replace("  暫定順位: ", ""),
                "board": board,
            })
            continue

        move_match = re.search(r"移動確定: (.+?) (後列|中列|前列)→(後列|中列|前列)", line)
        if move_match:
            name, src, dst = move_match.groups()
            name = name.strip()
            if name in board:
                board = {k: dict(v) for k, v in board.items()}
                board[name]["area"] = dst
                board[name]["highlight"] = "move"
            events.append({
                "type": "move",
                "round": current_round,
                "actor": name,
                "from": src,
                "to": dst,
                "title": f"{name}、{dst}へ！",
                "text": f"{name}が隊列を押し上げ、{src}から{dst}へ躍り出る。",
                "board": board,
            })
            continue

        if "確定順位:" in line:
            board = final_board_from_states(result.states, board)
            order_text = line.replace("  確定順位: ", "")
            events.append({
                "type": "goal",
                "round": current_round,
                "title": "ゴール！",
                "text": order_text,
                "board": board,
                "order": [t.name for t in result.order],
            })
            continue

        if "最終判定" in line:
            actor = actor_from_log(line, names)
            events.append({
                "type": "final_roll",
                "round": current_round,
                "actor": actor,
                "title": "最終順位判定",
                "text": line.strip(),
                "board": board,
            })
            continue

        actor = actor_from_log(line, names)
        event_type = classify_log_line(line)
        title = "判定ログ"
        if event_type == "hit":
            title = "妨害命中"
        elif event_type == "success":
            title = "成功"
        elif event_type == "failure":
            title = "失敗"
        elif event_type == "accident":
            title = "事故発生！"

        # ハイライトは一時的につける
        if actor and actor in board:
            board = {k: dict(v) for k, v in board.items()}
            board[actor]["highlight"] = event_type

        events.append({
            "type": event_type,
            "round": current_round,
            "actor": actor,
            "title": title,
            "text": line.strip(),
            "board": board,
        })

        # 次イベントに残り続けないようハイライトを薄める
        if actor and actor in board:
            board = {k: dict(v) for k, v in board.items()}
            board[actor]["highlight"] = ""

    if not any(e["type"] == "goal" for e in events):
        board = final_board_from_states(result.states, board)
        events.append({
            "type": "goal",
            "round": 6,
            "title": "ゴール！",
            "text": " / ".join(f"{i+1}.{t.name}" for i, t in enumerate(result.order)),
            "board": board,
            "order": [t.name for t in result.order],
        })

    return events


def create_race(rank: str, program: str, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    specs = sim_engine.make_program(rank, program)
    result = sim_engine.race_once(specs, rng, log_enabled=True)
    events = log_to_events(result.log, specs, result, rank, program, seed)

    return {
        "rank": rank,
        "program": program,
        "programLabel": PROGRAM_LABELS.get(program, program),
        "seed": seed,
        "tanks": [tank_to_public_dict(s) for s in specs],
        "events": events,
        "finalOrder": [t.name for t in result.order],
        "accidentCount": result.accident_count,
    }


@app.route("/")
def index():
    return render_template("index.html", programs=PROGRAM_LABELS)


@app.route("/control")
def control():
    return render_template("control.html", programs=PROGRAM_LABELS)


@app.route("/display")
def display():
    return render_template("display.html")


@app.post("/api/new_race")
def api_new_race():
    payload = request.get_json(force=True) or {}
    rank = payload.get("rank", "A")
    program = payload.get("program", "standard")
    seed_raw = payload.get("seed", "")
    if seed_raw in (None, ""):
        seed = random.randint(1, 999999)
    else:
        seed = int(seed_raw)

    race = create_race(rank, program, seed)
    STATE["race"] = race
    STATE["index"] = 0
    return jsonify({"ok": True, "race": race, "index": 0})


@app.post("/api/next")
def api_next():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = min(STATE["index"] + 1, len(race["events"]) - 1)
    return jsonify({"ok": True, "index": STATE["index"], "event": race["events"][STATE["index"]]})


@app.post("/api/prev")
def api_prev():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = max(STATE["index"] - 1, 0)
    return jsonify({"ok": True, "index": STATE["index"], "event": race["events"][STATE["index"]]})


@app.post("/api/reset_view")
def api_reset_view():
    if STATE.get("race") is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = 0
    race = STATE["race"]
    return jsonify({"ok": True, "index": 0, "event": race["events"][0]})


@app.get("/api/state")
def api_state():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "race": None, "index": 0})
    idx = STATE.get("index", 0)
    return jsonify({
        "ok": True,
        "race": race,
        "index": idx,
        "event": race["events"][idx],
    })


if __name__ == "__main__":
    app.run(debug=True)
