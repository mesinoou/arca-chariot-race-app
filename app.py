# -*- coding: utf-8 -*-
"""
鉄輪式三列戦車レース 演出付きMVPアプリ

起動:
    pip install flask
    python app.py

画面:
    GM管理画面:        http://127.0.0.1:5000/control
    Discord共有画面:   http://127.0.0.1:5000/display

このMVPは、sim_engine.py の Ver.0.5.1 簡易シミュレーターを利用し、
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

ROUND_INFO = sim_engine.round_info()
PROGRAM_LABELS = sim_engine.program_labels()

STATE: Dict[str, Any] = {
    "race": None,
    "index": 0,
    "odds": None,
}

DEFAULT_ODDS_SIMULATIONS = 1000
MIN_ODDS_SIMULATIONS = 100
MAX_ODDS_SIMULATIONS = 10000
MIN_ODDS = 1.1
MAX_ODDS = 99.9
BET_PAYOUT_POOL = 0.9

COMBO_BET_TARGET_COUNTS = {
    "exacta": 2,
    "quinella": 2,
    "trifecta": 3,
}


def audience_template(key: str, default: str = "", **values: Any) -> str:
    return sim_engine.commentary_text("audience", key, default, **values)


def race_response_payload(race: Dict[str, Any], index: int) -> Dict[str, Any]:
    total_events = len(race["events"])
    safe_index = min(max(index, 0), total_events - 1)
    visible_indices = audience_event_indices(race)
    audience_index = audience_index_at_or_before(race, safe_index)
    total_audience_events = len(visible_indices)
    return {
        "ok": True,
        "race": race,
        "index": safe_index,
        "current_index": safe_index,
        "current_event_number": safe_index + 1,
        "total_events": total_events,
        "is_last_event": safe_index >= total_events - 1,
        "event": race["events"][safe_index],
        "audience_index": audience_index,
        "audience_event": race["events"][audience_index],
        "current_audience_event_number": audience_event_number(race, audience_index),
        "total_audience_events": total_audience_events,
        "is_last_audience_event": bool(visible_indices) and audience_index >= visible_indices[-1],
        "odds": race.get("odds"),
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


def odds_value(payout_pool: float, rate: float) -> float:
    if rate <= 0:
        return MAX_ODDS
    return round(min(MAX_ODDS, max(MIN_ODDS, payout_pool / rate)), 1)


def clamp_simulations(value: Any) -> int:
    try:
        simulations = int(value)
    except (TypeError, ValueError):
        simulations = DEFAULT_ODDS_SIMULATIONS
    return min(MAX_ODDS_SIMULATIONS, max(MIN_ODDS_SIMULATIONS, simulations))


def combo_key(names: List[str], unordered: bool = False) -> str:
    selected = sorted(names) if unordered else names
    return "|".join(selected)


def combo_odds_from_counts(counts: Dict[str, int], simulations: int) -> Dict[str, float]:
    return {
        key: odds_value(BET_PAYOUT_POOL, count / max(1, simulations))
        for key, count in counts.items()
    }


def calculate_odds(rank: str, program: str, simulations: int, seed: Optional[int] = None) -> Dict[str, Any]:
    sim_seed = seed if seed is not None else random.randint(1, 999999999)
    rng = random.Random(sim_seed)
    specs = sim_engine.make_program(rank, program)
    stats: Dict[str, Dict[str, int]] = {
        s.name: {"starts": 0, "wins": 0, "top3": 0, "retirements": 0}
        for s in specs
    }
    combo_counts = {
        "exacta": {},
        "quinella": {},
        "trifecta": {},
        "perfect": {},
    }

    for _ in range(simulations):
        result = sim_engine.race_once(specs, rng, log_enabled=False)
        final_names = [t.name for t in result.order]
        combo_keys = {
            "exacta": combo_key(final_names[:2]),
            "quinella": combo_key(final_names[:2], unordered=True),
            "trifecta": combo_key(final_names[:3]),
            "perfect": combo_key(final_names),
        }
        for bet_type, key in combo_keys.items():
            combo_counts[bet_type][key] = combo_counts[bet_type].get(key, 0) + 1

        rank_by_name = {t.name: idx + 1 for idx, t in enumerate(result.order)}
        for state in result.states:
            tank_stats = stats[state.name]
            tank_stats["starts"] += 1
            position = rank_by_name[state.name]
            if position == 1:
                tank_stats["wins"] += 1
            if position <= 3:
                tank_stats["top3"] += 1
            if state.retired:
                tank_stats["retirements"] += 1

    tank_rows: List[Dict[str, Any]] = []
    for spec in specs:
        tank_stats = stats[spec.name]
        starts = max(1, tank_stats["starts"])
        win_rate = tank_stats["wins"] / starts
        top3_rate = tank_stats["top3"] / starts
        retirement_rate = tank_stats["retirements"] / starts
        tank_rows.append({
            "name": spec.name,
            "style": spec.style,
            "winRate": win_rate,
            "top3Rate": top3_rate,
            "retirementRate": retirement_rate,
            "winOdds": odds_value(BET_PAYOUT_POOL, win_rate),
            "placeOdds": odds_value(BET_PAYOUT_POOL, top3_rate),
        })

    return {
        "rank": rank,
        "program": program,
        "programLabel": PROGRAM_LABELS.get(program, program),
        "simulations": simulations,
        "seed": sim_seed,
        "tanks": tank_rows,
        "comboOdds": {
            bet_type: combo_odds_from_counts(counts, simulations)
            for bet_type, counts in combo_counts.items()
        },
    }


def normalize_bet_targets(bet: Dict[str, Any]) -> List[str]:
    raw_targets = bet.get("targets")
    if raw_targets is None:
        raw_targets = bet.get("target")

    if isinstance(raw_targets, list):
        return [str(t) for t in raw_targets if str(t)]
    if isinstance(raw_targets, str):
        return [t for t in raw_targets.split("|") if t]
    return []


def expected_target_count(bet_type: str, total_tanks: int) -> Optional[int]:
    if bet_type in ("win", "place"):
        return 1
    if bet_type == "perfect":
        return total_tanks
    return COMBO_BET_TARGET_COUNTS.get(bet_type)


def valid_bet_targets(bet_type: str, targets: List[str], final_order: List[str]) -> bool:
    expected_count = expected_target_count(bet_type, len(final_order))
    if expected_count is None:
        return False
    if len(targets) != expected_count:
        return False
    if len(set(targets)) != len(targets):
        return False
    return all(target in final_order for target in targets)


def odds_for_bet(odds: Dict[str, Any], bet_type: str, targets: List[str]) -> Optional[float]:
    if bet_type == "win":
        for row in odds.get("tanks", []):
            if targets and row.get("name") == targets[0]:
                return row.get("winOdds")
    if bet_type == "place":
        for row in odds.get("tanks", []):
            if targets and row.get("name") == targets[0]:
                return row.get("placeOdds")
    if bet_type in ("exacta", "trifecta", "perfect"):
        return odds.get("comboOdds", {}).get(bet_type, {}).get(combo_key(targets), MAX_ODDS)
    if bet_type == "quinella":
        return odds.get("comboOdds", {}).get(bet_type, {}).get(combo_key(targets, unordered=True), MAX_ODDS)
    return None


def evaluate_bet_result(race: Dict[str, Any], odds: Dict[str, Any], bet: Dict[str, Any]) -> Dict[str, Any]:
    bet_type = bet.get("type", "win")
    targets = normalize_bet_targets(bet)
    try:
        stake = max(0, int(bet.get("stake", 0)))
    except (TypeError, ValueError):
        stake = 0

    final_order = race.get("finalOrder", [])
    valid = valid_bet_targets(bet_type, targets, final_order)
    hit = False
    if valid and bet_type == "win":
        hit = bool(final_order) and targets[0] == final_order[0]
    elif valid and bet_type == "place":
        hit = targets[0] in final_order[:3]
    elif valid and bet_type == "exacta":
        hit = targets == final_order[:2]
    elif valid and bet_type == "quinella":
        hit = set(targets) == set(final_order[:2])
    elif valid and bet_type == "trifecta":
        hit = targets == final_order[:3]
    elif valid and bet_type == "perfect":
        hit = targets == final_order

    odds_value_for_bet = odds_for_bet(odds, bet_type, targets)
    if odds_value_for_bet is None:
        odds_value_for_bet = 0
    payout = int(round(stake * odds_value_for_bet)) if hit else 0
    return {
        "type": bet_type,
        "targets": targets,
        "stake": stake,
        "odds": odds_value_for_bet,
        "valid": valid,
        "hit": hit,
        "payout": payout,
        "profit": payout - stake,
        "finalOrder": final_order,
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
    action_match = re.match(r"\s*([^:：]+)[:：]", line)
    if action_match:
        action_actor = action_match.group(1).strip()
        for n in names:
            if n == action_actor:
                return n
    for n in names:
        if n in line:
            return n
    return None


def target_from_log(line: str, names: List[str], actor: Optional[str]) -> Optional[str]:
    target_match = re.search(r"→\s*([^\s]+)", line)
    if target_match:
        target_text = target_match.group(1).strip()
        for n in names:
            if n != actor and n == target_text:
                return n
    for n in names:
        if n == actor:
            continue
        if re.search(rf"→\s*{re.escape(n)}(?:\s|$)", line):
            return n
    return None


def classify_log_line(line: str) -> str:
    accident_result_terms = ("大破", "横転", "激突", "車体損傷", "奇跡の復帰", "耐久0")
    if "事故判定" in line or any(term in line for term in accident_result_terms):
        return "accident"
    if line.strip().startswith("→") and "立て直し" in line:
        return "accident"
    if "命中" in line:
        return "hit"
    if "失敗" in line:
        return "failure"
    if "成功" in line or "大成功" in line:
        return "success"
    return "log"


def dice_pair_from_sum(dice: int) -> List[int]:
    pairs = [(a, dice - a) for a in range(1, 7) if 1 <= dice - a <= 6]
    if not pairs:
        return [1, 1]
    return list(pairs[len(pairs) // 2])


def dice_result_class(dice: int, result: str) -> str:
    if dice == 2:
        return "fumble"
    if dice >= 11:
        return "crit"
    if result in ("成功", "命中", "順位判定"):
        return "success"
    return "failure"


def dice_result_label(dice: int, result: str) -> str:
    if dice == 2:
        return "出目2 / 事故級失敗"
    if dice >= 11:
        return "大成功 / 自動成功"
    return result


def dice_label_from_line(line: str) -> str:
    stripped = line.strip()
    if "前列狙い" in stripped:
        return "前列狙い"
    if stripped.startswith("最終判定"):
        return "最終順位判定"
    if stripped.startswith("カーブ制御"):
        return "カーブ制御"
    if stripped.startswith("障害制御"):
        return "障害制御"
    if stripped.startswith("制御判定"):
        return stripped.split(":", 1)[0]

    action_match = re.match(r"[^:：]+[:：]([^ →]+)", stripped)
    if action_match:
        return action_match.group(1).split("→", 1)[0]
    return "判定"


def dice_info_from_parts(
    line: str,
    label: str,
    dice: int,
    total: int,
    result: str,
    target: Optional[int] = None,
    target_label: str = "目標値",
    opposed: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "label": label,
        "dice": dice,
        "diceValues": dice_pair_from_sum(dice),
        "bonus": total - dice,
        "total": total,
        "target": target,
        "targetLabel": target_label,
        "result": dice_result_label(dice, result),
        "rawResult": result,
        "resultClass": dice_result_class(dice, result),
        "breakdown": line.strip(),
        "opposed": opposed,
    }


def parse_dice_info(line: str) -> Optional[Dict[str, Any]]:
    stripped = line.strip()
    label = dice_label_from_line(stripped)

    opposed_match = re.search(
        r"攻(?P<attack_dice>\d+)(?P<attack_formula>.*?)=(?P<attack_total>-?\d+)\s*/\s*"
        r"避(?P<defense_dice>\d+)(?P<defense_formula>.*?)=(?P<defense_total>-?\d+)\s*"
        r"→\s*(?P<result>命中|失敗)",
        stripped,
    )
    if opposed_match:
        attack_dice = int(opposed_match.group("attack_dice"))
        attack_total = int(opposed_match.group("attack_total"))
        defense_dice = int(opposed_match.group("defense_dice"))
        defense_total = int(opposed_match.group("defense_total"))
        opposed = {
            "label": "回避",
            "dice": defense_dice,
            "diceValues": dice_pair_from_sum(defense_dice),
            "bonus": defense_total - defense_dice,
            "total": defense_total,
        }
        return dice_info_from_parts(
            stripped,
            label,
            attack_dice,
            attack_total,
            opposed_match.group("result"),
            target=defense_total,
            target_label="回避達成値",
            opposed=opposed,
        )

    roll_match = re.search(
        r"出目(?P<dice>\d+)(?P<formula>.*?)=(?P<total>-?\d+)\s*"
        r"(?:/\s*(?:目標)?(?P<target>-?\d+))?\s*"
        r"(?:→\s*(?P<result>[^、\s]+))?",
        stripped,
    )
    if roll_match:
        dice = int(roll_match.group("dice"))
        total = int(roll_match.group("total"))
        target = roll_match.group("target")
        result = roll_match.group("result") or "順位判定"
        return dice_info_from_parts(
            stripped,
            label,
            dice,
            total,
            result,
            target=int(target) if target is not None else None,
        )

    fumble_match = re.search(r"出目(?P<dice>2)\s*→\s*(?P<result>[^、\s]+)", stripped)
    if fumble_match:
        dice = int(fumble_match.group("dice"))
        return dice_info_from_parts(
            stripped,
            label,
            dice,
            dice,
            fumble_match.group("result"),
            target=None,
        )

    return None


def event_subject(event: Dict[str, Any]) -> str:
    return event.get("actor") or event.get("target") or "戦車"


def action_label(event: Dict[str, Any]) -> str:
    dice_info = event.get("diceInfo") or {}
    if dice_info.get("label"):
        return str(dice_info["label"])
    title = str(event.get("title") or "")
    if "：" in title:
        return title.split("：", 1)[1]
    text = str(event.get("gm_text") or event.get("text") or "")
    match = re.match(r"[^:：]+[:：]([^ →]+)", text)
    if match:
        return match.group(1).split("→", 1)[0]
    return title or "行動"


def accident_result_key(result: str) -> str:
    if result == "大破リタイア":
        return "accident_result_destroyed"
    if result == "横転":
        return "accident_result_rollover"
    if result == "激突":
        return "accident_result_crash"
    if result == "車体損傷":
        return "accident_result_damage"
    if result == "立て直し":
        return "accident_result_recover"
    if result == "奇跡の復帰":
        return "accident_result_miracle"
    if result == "耐久0でリタイア":
        return "accident_result_hp_zero"
    return "accident_result"


def accident_result_audience_text(event: Dict[str, Any]) -> str:
    subject = event_subject(event)
    result = str(event.get("accidentResult") or "")
    roll = event.get("accidentRoll")
    roll_text = str(roll) if roll not in (None, "") else "?"
    defaults = {
        "大破リタイア": "事故ダイスは{roll}。{subject}は大破、リタイア！",
        "横転": "事故ダイスは{roll}。{subject}が横転！ 後列へ弾かれ、車体に大きな損傷！",
        "激突": "事故ダイスは{roll}。{subject}が激突！ 隊列を下げ、車体を削られる！",
        "車体損傷": "事故ダイスは{roll}。{subject}の車体が損傷！ 火花を散らして走行を続ける。",
        "立て直し": "事故ダイスは{roll}。{subject}が必死に立て直す！ なんとか姿勢を戻した。",
        "奇跡の復帰": "事故ダイスは{roll}。{subject}が奇跡の復帰！ 土煙を割ってレースへ戻る。",
        "耐久0でリタイア": "事故ダイスは{roll}。{subject}は耐久が尽き、リタイア！",
    }
    return audience_template(
        accident_result_key(result),
        defaults.get(result, "事故ダイスは{roll}。{subject}に事故結果が降りかかる！"),
        subject=subject,
        roll=roll_text,
    )


def audience_text_for_event(event: Dict[str, Any]) -> str:
    event_type = event.get("type", "")
    text = str(event.get("text") or "")
    actor = event.get("actor")
    target = event.get("target")
    label = action_label(event)
    dice_info = event.get("diceInfo") or {}
    result = str(dice_info.get("rawResult") or dice_info.get("result") or event.get("title") or "")

    if event_type in ("title", "placement_start", "round_start", "placement", "move"):
        return text
    if event_type == "ranking_update":
        return audience_template("ranking_update", "隊列が更新された。")
    if event_type == "goal":
        order = event.get("order") or []
        if order:
            order_top3 = "、".join(f"{i + 1}着 {name}" for i, name in enumerate(order[:3]))
            return audience_template("goal_with_order", "ゴール！ {order_top3}", order_top3=order_top3)
        return audience_template("goal_default", "ゴール！ 最終順位が確定した。")
    if event_type == "final_roll":
        return audience_template("final_roll", "{subject}、最後の伸び脚を競る。", subject=event_subject(event))
    if event_type == "hit" and actor and target:
        return audience_template("hit_with_target", "{actor}の妨害が{target}を捕らえた！", actor=actor, target=target)
    if event_type == "hit":
        return audience_template("hit", "{subject}に衝撃が走る！", subject=event_subject(event))
    if event_type == "accident" and event.get("accidentResult"):
        return accident_result_audience_text(event)
    if event_type == "accident_roll":
        return audience_template("accident_roll", "事故判定のダイスが転がる。")
    if event_type == "accident":
        if "大破" in text or "リタイア" in text:
            return audience_template(
                "accident_retire",
                "{subject}、大きく崩れてリタイア寸前！",
                subject=event_subject(event),
            )
        return audience_template("accident", "事故発生！ 車体が大きく跳ねる！")
    if event_type == "success":
        if "大成功" in text or dice_info.get("resultClass") == "crit":
            return audience_template(
                "success_crit",
                "{subject}、{label}で大成功！",
                subject=event_subject(event),
                label=label,
            )
        return audience_template("success", "{subject}、{label}に成功！", subject=event_subject(event), label=label)
    if event_type == "failure":
        return audience_template("failure", "{subject}、{label}は伸びきらない！", subject=event_subject(event), label=label)
    if event_type == "log" and ("奇跡" in text or "復帰" in text):
        return audience_template("miracle", "土煙の中から戦車が復帰する！")
    return text


def summary_text_for_event(event: Dict[str, Any]) -> str:
    event_type = event.get("type", "")
    actor = event.get("actor")
    target = event.get("target")
    label = action_label(event)
    dice_info = event.get("diceInfo") or {}
    result = dice_info.get("rawResult") or event.get("title") or ""

    if event_type == "ranking_update":
        return "暫定順位更新"
    if event_type == "round_start":
        return str(event.get("title") or "ラウンド開始")
    if event_type == "placement":
        return f"{actor}: {label}" if actor else label
    if event_type == "move":
        return f"{actor}: {event.get('from')}→{event.get('to')}"
    if event_type == "hit" and actor and target:
        return f"{actor}→{target}: 命中"
    if event_type in ("success", "failure", "final_roll"):
        prefix = f"{actor}: " if actor else ""
        return f"{prefix}{label} {result}".strip()
    if event_type == "goal":
        return "ゴール"
    if event_type == "accident":
        if event.get("accidentResult"):
            actor_prefix = f"{actor}: " if actor else ""
            return f"{actor_prefix}事故 {event.get('accidentResult')}".strip()
        return "事故"
    if event_type == "accident_roll":
        return "事故判定"
    return str(event.get("title") or event.get("text") or "イベント")


def is_visible_to_audience(event: Dict[str, Any]) -> bool:
    event_type = event.get("type", "")
    text = str(event.get("gm_text") or event.get("text") or "")
    if event_type == "ranking_update":
        return False
    if event_type == "accident_roll":
        return False
    if event_type == "log":
        return "奇跡" in text or "復帰" in text or "リタイア" in text
    if event_type == "success" and not event.get("actor") and "制御判定" in text:
        return False
    return True


def importance_for_event(event: Dict[str, Any]) -> str:
    if not event.get("audience_visible", True):
        return "hidden"
    event_type = event.get("type", "")
    text = str(event.get("gm_text") or event.get("text") or event.get("audience_text") or "")
    dice_info = event.get("diceInfo") or {}
    if event_type == "goal":
        return "critical"
    if event_type == "accident" or "大破" in text or "リタイア" in text:
        return "critical"
    if "大成功" in text or dice_info.get("resultClass") == "crit":
        return "critical"
    if event_type == "hit":
        return "high"
    if event_type in ("title", "placement_start", "round_start", "move"):
        return "normal"
    if event_type in ("placement", "success", "failure", "final_roll"):
        return "normal"
    return "low"


def enrich_event(event: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(event)
    enriched["gm_text"] = str(enriched.get("gm_text") or enriched.get("text") or "")
    enriched["audience_text"] = str(enriched.get("audience_text") or audience_text_for_event(enriched))
    enriched["summary_text"] = str(enriched.get("summary_text") or summary_text_for_event(enriched))
    enriched["audience_visible"] = bool(enriched.get("audience_visible", is_visible_to_audience(enriched)))
    enriched["importance"] = str(enriched.get("importance") or importance_for_event(enriched))
    return enriched


def audience_event_indices(race: Dict[str, Any]) -> List[int]:
    return [
        idx for idx, event in enumerate(race.get("events", []))
        if event.get("audience_visible", True)
    ]


def audience_index_at_or_before(race: Dict[str, Any], index: int) -> int:
    indices = audience_event_indices(race)
    if not indices:
        return min(max(index, 0), len(race.get("events", [])) - 1)
    previous = [idx for idx in indices if idx <= index]
    if previous:
        return previous[-1]
    return indices[0]


def next_audience_index(race: Dict[str, Any], index: int) -> int:
    indices = audience_event_indices(race)
    if not indices:
        return min(max(index + 1, 0), len(race.get("events", [])) - 1)
    for idx in indices:
        if idx > index:
            return idx
    return indices[-1]


def audience_event_number(race: Dict[str, Any], audience_index: int) -> int:
    indices = audience_event_indices(race)
    if audience_index in indices:
        return indices.index(audience_index) + 1
    return max(1, len([idx for idx in indices if idx <= audience_index]))


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
        "text": audience_template(
            "title",
            "グランド・サーキット・アルカ、出走準備完了。鉄輪会の旗が振り上げられる。",
        ),
        "board": board,
    })

    current_round = 0
    pending_accident: Optional[Dict[str, Any]] = None
    for raw in log_lines:
        line = raw.rstrip()
        if not line:
            continue

        accident_roll_match = re.search(
            r"事故判定(?::\s*(?P<actor>.+?)\((?P<reason>.*?)\)|\((?P<old_reason>.*?)\)):\s*1d6=(?P<roll>[1-6])",
            line,
        )
        if accident_roll_match:
            actor = (accident_roll_match.group("actor") or "").strip() or actor_from_log(line, names)
            reason = accident_roll_match.group("reason") or accident_roll_match.group("old_reason") or ""
            pending_accident = {
                "actor": actor,
                "reason": reason,
                "roll": int(accident_roll_match.group("roll")),
                "gm_text": line.strip(),
            }
            events.append({
                "type": "accident_roll",
                "round": current_round,
                "actor": actor,
                "title": "事故判定",
                "text": line.strip(),
                "gm_text": line.strip(),
                "board": board,
                "accidentRoll": pending_accident["roll"],
                "accidentReason": reason,
                "audience_visible": False,
                "importance": "hidden",
            })
            continue

        accident_result_match = re.search(
            r"→\s*(?:(?P<actor>.+?)\s+)?(?P<result>大破リタイア|横転|激突|車体損傷|立て直し|奇跡の復帰|耐久0でリタイア)",
            line,
        )
        if accident_result_match:
            actor = (accident_result_match.group("actor") or "").strip()
            if actor not in names:
                actor = str((pending_accident or {}).get("actor") or actor_from_log(line, names) or "")
            result_name = accident_result_match.group("result")
            roll = (pending_accident or {}).get("roll")
            reason = str((pending_accident or {}).get("reason") or "")
            board = {k: dict(v) for k, v in board.items()}
            if actor in board:
                board[actor]["highlight"] = "accident"
                if result_name in ("大破リタイア", "耐久0でリタイア"):
                    board[actor]["retired"] = True
                    board[actor]["hp"] = 0
                elif result_name == "横転":
                    board[actor]["area"] = "後列"
            events.append({
                "type": "accident",
                "round": current_round,
                "actor": actor or None,
                "title": f"事故結果：{result_name}",
                "text": line.strip(),
                "gm_text": line.strip(),
                "board": board,
                "accidentRoll": roll,
                "accidentResult": result_name,
                "accidentReason": reason,
            })
            if actor in board:
                board = {k: dict(v) for k, v in board.items()}
                board[actor]["highlight"] = ""
            pending_accident = None
            continue

        if line.strip() == "=== 配置決めフェーズ ===":
            events.append({
                "type": "placement_start",
                "round": 0,
                "roundName": "配置決め",
                "title": "配置決めフェーズ",
                "text": audience_template(
                    "placement_start",
                    "各車が発走直後の位置取りに入る。前へ割り込むか、混戦に構えるか、後方から脚を溜めるか。",
                ),
                "board": board,
            })
            continue

        placement_match = re.search(
            r"配置決め: (.+?) (前列狙い|中列配置|後列配置).*?→ (?:(大成功|成功|失敗|出目2・失敗)、)?(後列|中列|前列)(?:配置)? .*?\(駆(-?\d+) 安(-?\d+)\)",
            line,
        )
        if placement_match:
            name, intent, outcome, area, drive, stability = placement_match.groups()
            name = name.strip()
            dice_info = parse_dice_info(line)
            board = {k: dict(v) for k, v in board.items()}
            if name in board:
                board[name]["area"] = area
                board[name]["drive"] = int(drive)
                board[name]["stability"] = int(stability)
                board[name]["highlight"] = "move" if area == "前列" else ("success" if area == "後列" else "")
            if intent == "前列狙い":
                if outcome == "大成功":
                    text = audience_template(
                        "placement_front_crit",
                        "{name}が鮮やかに前列を奪取する。駆動力を温存したまま、先頭集団へ滑り込んだ。",
                        name=name,
                    )
                elif outcome == "成功":
                    text = audience_template(
                        "placement_front_success",
                        "{name}が強引に前列へ割り込む。駆動力を使ったが、発走直後の好位置を取った。",
                        name=name,
                    )
                else:
                    text = audience_template(
                        "placement_front_failure",
                        "{name}は前列を狙うが割り込みきれない。駆動力と安定を削り、中列からの再加速を迫られる。",
                        name=name,
                    )
            elif intent == "後列配置":
                text = audience_template(
                    "placement_back",
                    "{name}は後方に控える。序盤の位置を捨て、温存した駆動力で後半に賭ける構えだ。",
                    name=name,
                )
            else:
                text = audience_template(
                    "placement_middle",
                    "{name}は中列に構える。混戦の中央で、出方をうかがう。",
                    name=name,
                )
            events.append({
                "type": "placement",
                "round": 0,
                "roundName": "配置決め",
                "actor": name,
                "title": f"{name}：{intent}",
                "text": text,
                "gm_text": line.strip(),
                "board": board,
                "diceInfo": dice_info,
            })
            if name in board:
                board = {k: dict(v) for k, v in board.items()}
                board[name]["highlight"] = ""
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
                "gm_text": line.strip(),
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
                "text": audience_template(
                    "move",
                    "{name}が隊列を押し上げ、{src}から{dst}へ躍り出る。",
                    name=name,
                    src=src,
                    dst=dst,
                ),
                "gm_text": line.strip(),
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
                "gm_text": line.strip(),
                "board": board,
                "order": [t.name for t in result.order],
            })
            continue

        if "最終判定" in line:
            actor = actor_from_log(line, names)
            dice_info = parse_dice_info(line)
            events.append({
                "type": "final_roll",
                "round": current_round,
                "actor": actor,
                "target": None,
                "title": "最終順位判定",
                "text": line.strip(),
                "gm_text": line.strip(),
                "board": board,
                "diceInfo": dice_info,
            })
            continue

        actor = actor_from_log(line, names)
        target = target_from_log(line, names, actor)
        event_type = classify_log_line(line)
        dice_info = parse_dice_info(line)
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
            "target": target,
            "title": title,
            "text": line.strip(),
            "gm_text": line.strip(),
            "board": board,
            "diceInfo": dice_info,
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

    return [enrich_event(event) for event in events]


def create_race(rank: str, program: str, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    commentary_rng = random.Random(f"{seed}:commentary")
    specs = sim_engine.make_program(rank, program)
    result = sim_engine.race_once(specs, rng, log_enabled=True, commentary_rng=commentary_rng)
    events = log_to_events(result.log, specs, result, rank, program, seed)
    race = {
        "rank": rank,
        "program": program,
        "programLabel": PROGRAM_LABELS.get(program, program),
        "seed": seed,
        "tanks": [tank_to_public_dict(s) for s in specs],
        "events": events,
        "finalOrder": [t.name for t in result.order],
        "accidentCount": result.accident_count,
    }
    current_odds = STATE.get("odds")
    if current_odds and current_odds.get("rank") == rank and current_odds.get("program") == program:
        race["odds"] = current_odds
    return race


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
    return jsonify(race_response_payload(race, 0))


@app.post("/api/calculate_odds")
def api_calculate_odds():
    payload = request.get_json(force=True) or {}
    rank = payload.get("rank", "A")
    program = payload.get("program", "standard")
    simulations = clamp_simulations(payload.get("simulations", DEFAULT_ODDS_SIMULATIONS))
    seed_raw = payload.get("seed")
    seed = int(seed_raw) if seed_raw not in (None, "") else None

    odds = calculate_odds(rank, program, simulations, seed)
    STATE["odds"] = odds
    race = STATE.get("race")
    if race and race.get("rank") == rank and race.get("program") == program:
        race["odds"] = odds
    return jsonify({"ok": True, "odds": odds})


@app.post("/api/evaluate_bet")
def api_evaluate_bet():
    payload = request.get_json(force=True) or {}
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    odds = race.get("odds") or STATE.get("odds")
    if odds is None:
        return jsonify({"ok": False, "error": "odds are not calculated"}), 400
    if odds.get("rank") != race.get("rank") or odds.get("program") != race.get("program"):
        return jsonify({"ok": False, "error": "odds do not match current race"}), 400
    if STATE.get("index", 0) < len(race["events"]) - 1:
        return jsonify({"ok": False, "error": "race is not finished"}), 400
    result = evaluate_bet_result(race, odds, payload.get("bet", {}))
    return jsonify({"ok": True, "result": result})


@app.post("/api/next")
def api_next():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = min(STATE["index"] + 1, len(race["events"]) - 1)
    return jsonify(race_response_payload(race, STATE["index"]))


@app.post("/api/next_audience")
def api_next_audience():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = next_audience_index(race, STATE.get("index", 0))
    return jsonify(race_response_payload(race, STATE["index"]))


@app.post("/api/prev")
def api_prev():
    race = STATE.get("race")
    if race is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = max(STATE["index"] - 1, 0)
    return jsonify(race_response_payload(race, STATE["index"]))


@app.post("/api/reset_view")
def api_reset_view():
    if STATE.get("race") is None:
        return jsonify({"ok": False, "error": "race is not initialized"}), 400
    STATE["index"] = 0
    race = STATE["race"]
    return jsonify(race_response_payload(race, 0))


@app.get("/api/state")
def api_state():
    race = STATE.get("race")
    if race is None:
        return jsonify({
            "ok": False,
            "race": None,
            "index": 0,
            "current_index": 0,
            "current_event_number": 0,
            "total_events": 0,
            "is_last_event": True,
        })
    idx = STATE.get("index", 0)
    return jsonify(race_response_payload(race, idx))


if __name__ == "__main__":
    app.run(debug=True)
