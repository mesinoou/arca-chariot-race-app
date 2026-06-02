#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鉄輪式三列戦車レース Ver.0.3 簡易シミュレータ

このスクリプトは、アルカ・ヴェルジア「グランド・サーキット・アルカ」の
戦車レースルール検討用に作った検証用実装です。

重要:
- 卓上運用向けの簡易AIです。厳密な最適AIではありません。
- これまでチャット上で出した統計値を完全再現する乱数シード・実装ログではなく、
  現行ルールを再検証するための再現用プログラムです。
- 状態異常なし、大成功は出目11以上かつ自動成功、先行点倍化なし、配置決めフェーズありのVer.0.4相当です。

実行例:
    python chariot_race_sim_v03.py --program standard --rank A --races 20000 --seed 42
    python chariot_race_sim_v03.py --program all --rank A --races 5000 --seed 1
    python chariot_race_sim_v03.py --program all --rank all --races 3000 --seed 7
    python chariot_race_sim_v03.py --program standard --rank A --races 1 --seed 5 --log
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import argparse
import json
import math
import random
import statistics


# ============================================================
# 基本定義
# ============================================================

class Area(Enum):
    BACK = 0
    MID = 1
    FRONT = 2

    def right(self) -> "Area":
        return Area(min(2, self.value + 1))

    def left(self) -> "Area":
        return Area(max(0, self.value - 1))

    @property
    def jp(self) -> str:
        return {Area.BACK: "後列", Area.MID: "中列", Area.FRONT: "前列"}[self]


class Action(Enum):
    CRUISE = "巡航"
    ACCEL = "加速"
    OVERTAKE = "危険な追い抜き"
    DEFEND = "防御走行"
    REPAIR = "立て直し"
    CONTACT = "接触妨害"
    DANGEROUS_CONTACT = "危険接触"
    SHOOT = "射撃妨害"
    HEAVY_SHOOT = "重射撃"
    PIN_SHOOT = "牽制射撃"


@dataclass
class TankSpec:
    name: str
    style: str
    rank: str
    mobility: int
    handling: int
    armor: int
    firepower: int
    stability: int
    drive: int
    ammo: int
    hp: int
    # 行動AIタイプ。styleと同じでもよいが、調整用に分ける。
    ai: str = ""


@dataclass
class TankState:
    spec: TankSpec
    area: Area = Area.MID
    hp: int = 0
    stability: int = 0
    drive: int = 0
    ammo: int = 0
    lead: int = 0
    retired: bool = False
    move_reserved: bool = False
    blocked_this_round: bool = False

    # 統計
    accidents: int = 0
    caused_control_failures: int = 0
    damage_dealt: int = 0
    controls_failed: int = 0

    def __post_init__(self) -> None:
        self.hp = self.spec.hp
        self.stability = self.spec.stability
        self.drive = self.spec.drive
        self.ammo = self.spec.ammo

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def style(self) -> str:
        return self.spec.style

    @property
    def mobility(self) -> int:
        return self.spec.mobility

    @property
    def handling(self) -> int:
        return self.spec.handling

    @property
    def armor(self) -> int:
        return self.spec.armor

    @property
    def firepower(self) -> int:
        return self.spec.firepower

    @property
    def max_stability(self) -> int:
        return self.spec.stability

    def stability_mod(self) -> int:
        if self.stability >= 4:
            return 1
        if self.stability >= 2:
            return 0
        if self.stability == 1:
            return -1
        return -2

    def recover_stability(self, amount: int) -> None:
        self.stability = min(self.max_stability, self.stability + amount)

    def lose_stability(self, amount: int) -> None:
        self.stability -= amount

    def vehicle_condition_mod(self) -> int:
        if self.retired:
            return -99
        mod = 0
        if self.hp <= self.spec.hp / 4:
            mod -= 2
        elif self.hp <= self.spec.hp / 2:
            mod -= 1
        if self.stability <= 0:
            mod -= 2
        return mod

    def drive_mod(self) -> int:
        if self.drive <= 0:
            return 0
        if self.drive <= 2:
            return 1
        if self.drive <= 4:
            return 2
        return 3


@dataclass
class Roll:
    dice: int
    total: int
    auto_success: bool
    crit: bool
    fumble: bool


@dataclass
class RaceResult:
    order: List[TankState]
    states: List[TankState]
    accident_count: int
    log: List[str] = field(default_factory=list)


def d6(rng: random.Random) -> int:
    return rng.randint(1, 6)


def roll_2d6(rng: random.Random, bonus: int = 0, target: Optional[int] = None) -> Roll:
    a, b = d6(rng), d6(rng)
    dice = a + b
    total = dice + bonus
    fumble = dice == 2
    crit = dice >= 11
    # Ver.0.3: 出目11以上は自動成功かつ大成功
    auto_success = crit
    return Roll(dice=dice, total=total, auto_success=auto_success, crit=crit, fumble=fumble)


def success(roll: Roll, target: int) -> bool:
    return roll.auto_success or roll.total >= target


# ============================================================
# 車格点
# ============================================================

CONTROL_COST = {
    -1: {-1: 0, 0: 0, 1: 0, 2: 0, 3: 0},
     0: {-1: 0, 0: 0, 1: 0, 2: 0, 3: 1},
     1: {-1: 0, 0: 0, 1: 0, 2: 1, 3: 3},
     2: {-1: 0, 0: 0, 1: 1, 2: 4, 3: 7},
     3: {-1: 0, 0: 1, 1: 3, 2: 7, 3: 12},
}


def weighted_motion(v: int) -> int:
    # -1=0, 0=2, +1=4, +2=6, +3=8
    return max(0, (v + 1) * 2)


def weighted_nonnegative(v: int) -> int:
    return v * 2


def tank_grade_points(t: TankSpec) -> int:
    hp_points = math.ceil(t.hp / 3)
    return (
        weighted_motion(t.mobility)
        + weighted_motion(t.handling)
        + CONTROL_COST[t.mobility][t.handling]
        + weighted_nonnegative(t.firepower)
        + weighted_nonnegative(t.armor)
        + t.stability
        + t.drive
        + t.ammo
        + hp_points
    )


# ============================================================
# 外部データ
# ============================================================

DATA_DIR = Path(__file__).resolve().parent / "data"
_DATA_CACHE: Dict[str, Tuple[float, Any]] = {}
TANK_FIELDS = [
    "name",
    "style",
    "rank",
    "mobility",
    "handling",
    "armor",
    "firepower",
    "stability",
    "drive",
    "ammo",
    "hp",
    "ai",
]


def load_json_data(filename: str) -> Any:
    """data/*.json を読み込む。失敗時は調整しやすい例外に整える。"""
    path = DATA_DIR / filename
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError as exc:
        raise RuntimeError(f"JSONデータファイルが見つかりません: {path}") from exc

    cached = _DATA_CACHE.get(filename)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSONデータファイルの形式が不正です: {path} "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    _DATA_CACHE[filename] = (mtime, data)
    return data


def tank_data() -> Dict[str, Any]:
    data = load_json_data("tanks.json")
    if not isinstance(data, dict) or not isinstance(data.get("ranks"), dict):
        raise RuntimeError("tanks.json は ranks オブジェクトを含む必要があります")
    return data


def program_data() -> Dict[str, Any]:
    data = load_json_data("programs.json")
    if not isinstance(data, dict) or not isinstance(data.get("programs"), dict):
        raise RuntimeError("programs.json は programs オブジェクトを含む必要があります")
    return data


def commentary_data() -> Dict[str, Any]:
    data = load_json_data("commentary_templates.json")
    if not isinstance(data, dict):
        raise RuntimeError("commentary_templates.json はオブジェクトである必要があります")
    return data


def commentary_text(
    section: str,
    key: str,
    default: str = "",
    rng: Optional[random.Random] = None,
    **values: Any,
) -> str:
    """実況テンプレートを取得して整形する。

    テンプレートを配列にした場合だけ rng で選択する。rng 未指定時は先頭を使い、
    レース処理用乱数を消費しない。
    """
    section_data = commentary_data().get(section, {})
    template: Any = default
    if isinstance(section_data, dict):
        template = section_data.get(key, default)
    if isinstance(template, list):
        if not template:
            template = default
        else:
            template = rng.choice(template) if rng is not None else template[0]
    if template is None:
        template = default
    try:
        return str(template).format(**values)
    except KeyError as exc:
        raise RuntimeError(
            f"commentary_templates.json の {section}.{key} に必要な値がありません: {exc.args[0]}"
        ) from exc


def round_info() -> Dict[int, Dict[str, str]]:
    raw = commentary_data().get("round_info", {})
    if not isinstance(raw, dict):
        raise RuntimeError("commentary_templates.json の round_info はオブジェクトである必要があります")
    info: Dict[int, Dict[str, str]] = {}
    for round_key, value in raw.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"round_info.{round_key} はオブジェクトである必要があります")
        try:
            round_no = int(round_key)
        except ValueError as exc:
            raise RuntimeError(f"round_info のキーは数値文字列である必要があります: {round_key}") from exc
        info[round_no] = {
            "name": str(value.get("name", f"第{round_no}R")),
            "text": str(value.get("text", "")),
        }
    return info


def _tank_spec_from_json(rank: str, index: int, entry: Any, fields: List[str]) -> TankSpec:
    if isinstance(entry, list):
        if len(entry) != len(fields):
            raise RuntimeError(
                f"tanks.json の {rank}[{index}] は fields と同じ要素数である必要があります"
            )
        values = dict(zip(fields, entry))
    elif isinstance(entry, dict):
        values = dict(entry)
    else:
        raise RuntimeError(f"tanks.json の {rank}[{index}] は配列またはオブジェクトである必要があります")

    missing = [name for name in TANK_FIELDS if name not in values]
    if missing:
        raise RuntimeError(f"tanks.json の {rank}[{index}] に不足項目があります: {', '.join(missing)}")

    try:
        spec = TankSpec(**{name: values[name] for name in TANK_FIELDS})
    except TypeError as exc:
        raise RuntimeError(f"tanks.json の {rank}[{index}] から TankSpec を生成できません: {exc}") from exc
    if spec.rank != rank:
        raise RuntimeError(f"tanks.json の {rank}[{index}] の rank が一致しません: {spec.rank}")
    return spec


def make_rank_tanks(rank: str) -> Dict[str, TankSpec]:
    """指定ランクの戦車候補を tanks.json から生成する。"""
    data = tank_data()
    ranks = data["ranks"]
    if rank not in ranks:
        available = ", ".join(sorted(ranks.keys()))
        raise ValueError(f"unknown rank: {rank} (available: {available})")

    fields = data.get("fields", TANK_FIELDS)
    if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields):
        raise RuntimeError("tanks.json の fields は文字列配列である必要があります")

    entries = ranks[rank]
    if not isinstance(entries, list):
        raise RuntimeError(f"tanks.json の ranks.{rank} は配列である必要があります")

    tanks = [_tank_spec_from_json(rank, idx, entry, fields) for idx, entry in enumerate(entries)]
    return {t.name: t for t in tanks}


def program_names() -> List[str]:
    return list(program_data()["programs"].keys())


def program_labels() -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for name, config in program_data()["programs"].items():
        if not isinstance(config, dict):
            raise RuntimeError(f"programs.json の programs.{name} はオブジェクトである必要があります")
        labels[name] = str(config.get("label", name))
    return labels


def make_program(rank: str, program: str) -> List[TankSpec]:
    specs_by_name = make_rank_tanks(rank)
    by_style: Dict[str, List[TankSpec]] = {}
    for spec in specs_by_name.values():
        by_style.setdefault(spec.style, []).append(spec)

    programs = program_data()["programs"]
    if program not in programs:
        available = ", ".join(programs.keys())
        raise ValueError(f"unknown program: {program} (available: {available})")

    config = programs[program]
    if not isinstance(config, dict) or not isinstance(config.get("entries"), list):
        raise RuntimeError(f"programs.json の programs.{program}.entries は配列である必要があります")

    selected: List[TankSpec] = []
    for entry_no, entry in enumerate(config["entries"]):
        if not isinstance(entry, dict):
            raise RuntimeError(f"programs.json の {program}.entries[{entry_no}] はオブジェクトである必要があります")
        style = str(entry.get("style", ""))
        try:
            index = int(entry.get("index", 0))
            selected.append(by_style[style][index])
        except KeyError as exc:
            raise RuntimeError(f"programs.json の {program}.entries[{entry_no}] に未知の style があります: {style}") from exc
        except IndexError as exc:
            raise RuntimeError(
                f"programs.json の {program}.entries[{entry_no}] は {style} の index {index} を参照できません"
            ) from exc
    return selected


# ============================================================
# 行動AI
# ============================================================

BASE_WEIGHTS: Dict[str, Dict[Action, int]] = {
    "逃げ": {
        Action.ACCEL: 45,
        Action.CRUISE: 20,
        Action.DEFEND: 15,
        Action.OVERTAKE: 10,
        Action.SHOOT: 5,
        Action.REPAIR: 5,
    },
    "万能": {
        Action.ACCEL: 30,
        Action.CRUISE: 20,
        Action.DEFEND: 15,
        Action.SHOOT: 10,
        Action.CONTACT: 10,
        Action.OVERTAKE: 10,
        Action.REPAIR: 5,
    },
    "追込": {
        # 後半で差し替える
        Action.CRUISE: 40,
        Action.REPAIR: 20,
        Action.ACCEL: 20,
        Action.DEFEND: 10,
        Action.OVERTAKE: 5,
        Action.SHOOT: 5,
    },
    "重戦車": {
        Action.CONTACT: 30,
        Action.DANGEROUS_CONTACT: 20,
        Action.HEAVY_SHOOT: 15,
        Action.SHOOT: 15,
        Action.CRUISE: 10,
        Action.DEFEND: 5,
        Action.ACCEL: 5,
    },
    "射撃": {
        Action.SHOOT: 35,
        Action.HEAVY_SHOOT: 20,
        Action.PIN_SHOOT: 15,
        Action.CRUISE: 15,
        Action.ACCEL: 10,
        Action.CONTACT: 5,
    },
    "荒くれ": {
        Action.OVERTAKE: 30,
        Action.DANGEROUS_CONTACT: 25,
        Action.ACCEL: 20,
        Action.CONTACT: 10,
        Action.SHOOT: 5,
        Action.CRUISE: 5,
        Action.REPAIR: 5,
    },
}


def action_weights(t: TankState, round_no: int) -> Dict[Action, int]:
    style = t.spec.ai or t.style
    weights = dict(BASE_WEIGHTS[style])

    # 追込型は後半に追い抜きを増やす
    if style == "追込" and round_no >= 4:
        weights = {
            Action.ACCEL: 35,
            Action.OVERTAKE: 30,
            Action.CRUISE: 15,
            Action.DEFEND: 10,
            Action.REPAIR: 5,
            Action.SHOOT: 5,
        }

    # 前列にいる時は守り・先行点狙いを増やす
    if t.area == Area.FRONT:
        weights[Action.DEFEND] = weights.get(Action.DEFEND, 0) + 10
        weights[Action.CRUISE] = weights.get(Action.CRUISE, 0) + 10
        weights[Action.OVERTAKE] = max(0, weights.get(Action.OVERTAKE, 0) - 10)

    # 後列にいる時は前進行動を増やす
    if t.area == Area.BACK:
        weights[Action.ACCEL] = weights.get(Action.ACCEL, 0) + 10
        weights[Action.OVERTAKE] = weights.get(Action.OVERTAKE, 0) + 10
        weights[Action.DEFEND] = max(0, weights.get(Action.DEFEND, 0) - 10)

    # 安定値が低い時
    if t.stability <= 1:
        if style != "荒くれ":
            weights[Action.REPAIR] = weights.get(Action.REPAIR, 0) + 20
            weights[Action.OVERTAKE] = max(0, weights.get(Action.OVERTAKE, 0) - 10)
            weights[Action.DANGEROUS_CONTACT] = max(0, weights.get(Action.DANGEROUS_CONTACT, 0) - 10)
        else:
            weights[Action.REPAIR] = weights.get(Action.REPAIR, 0) + 10

    # 耐久値が半分以下
    if t.hp <= t.spec.hp / 2:
        weights[Action.DEFEND] = weights.get(Action.DEFEND, 0) + 10
        weights[Action.REPAIR] = weights.get(Action.REPAIR, 0) + 5
        weights[Action.DANGEROUS_CONTACT] = max(0, weights.get(Action.DANGEROUS_CONTACT, 0) - 10)

    return weights


def choose_weighted(rng: random.Random, weights: Dict[Action, int]) -> Action:
    total = sum(max(0, w) for w in weights.values())
    if total <= 0:
        return Action.CRUISE
    x = rng.uniform(0, total)
    acc = 0.0
    for action, weight in weights.items():
        w = max(0, weight)
        acc += w
        if x <= acc:
            return action
    return list(weights.keys())[-1]


def legal_actions(t: TankState, tanks: List[TankState], weights: Dict[Action, int]) -> Dict[Action, int]:
    w = dict(weights)

    same_area_targets = [x for x in tanks if (not x.retired and x is not t and x.area == t.area)]
    other_area_targets = [x for x in tanks if (not x.retired and x is not t and x.area != t.area)]

    if t.drive <= 0:
        w[Action.ACCEL] = 0
        w[Action.OVERTAKE] = 0
    if t.drive < 2:
        w[Action.OVERTAKE] = 0
    if t.ammo <= 0:
        w[Action.SHOOT] = 0
        w[Action.HEAVY_SHOOT] = 0
        w[Action.PIN_SHOOT] = 0
    if t.ammo < 2:
        w[Action.HEAVY_SHOOT] = 0
    if not same_area_targets:
        w[Action.CONTACT] = 0
        w[Action.DANGEROUS_CONTACT] = 0
    if not other_area_targets:
        w[Action.SHOOT] = 0
        w[Action.HEAVY_SHOOT] = 0
        w[Action.PIN_SHOOT] = 0

    # 使えない分を巡航・加速に少し戻す
    if sum(max(0, v) for v in w.values()) <= 0:
        return {Action.CRUISE: 1}
    return w


def choose_action(rng: random.Random, t: TankState, tanks: List[TankState], round_no: int) -> Action:
    w = legal_actions(t, tanks, action_weights(t, round_no))
    return choose_weighted(rng, w)


def choose_target(
    rng: random.Random,
    attacker: TankState,
    tanks: List[TankState],
    action: Action,
) -> Optional[TankState]:
    if action in (Action.CONTACT, Action.DANGEROUS_CONTACT):
        candidates = [x for x in tanks if not x.retired and x is not attacker and x.area == attacker.area]
    else:
        candidates = [x for x in tanks if not x.retired and x is not attacker and x.area != attacker.area]

    if not candidates:
        return None

    # 射撃型: 前列・先行点・安定低・前方を狙う
    if action in (Action.SHOOT, Action.HEAVY_SHOOT, Action.PIN_SHOOT):
        def score(x: TankState) -> Tuple[int, int, int, float]:
            return (
                x.area.value,
                x.lead,
                -x.stability,
                rng.random(),
            )
        return max(candidates, key=score)

    # 接触系: 同エリアの低装甲・前列・先行点持ちを狙う
    if action in (Action.CONTACT, Action.DANGEROUS_CONTACT):
        def score2(x: TankState) -> Tuple[int, int, int, float]:
            return (
                x.area.value,
                x.lead,
                -x.armor,
                rng.random(),
            )
        return max(candidates, key=score2)

    return rng.choice(candidates)


# ============================================================
# レース処理
# ============================================================

def is_curve_round(round_no: int) -> bool:
    return round_no in (2, 5)


def is_obstacle_round(round_no: int) -> bool:
    return round_no == 4


def shooting_modifier(attacker: TankState, defender: TankState) -> int:
    dist = abs(attacker.area.value - defender.area.value)
    mod = 0
    if dist >= 2:
        mod -= 2
    # 前方から後方へ: +1
    if attacker.area.value > defender.area.value:
        mod += 1
    # 後方から前方へ: -1
    elif attacker.area.value < defender.area.value:
        mod -= 1
    return mod


def resolve_control_check(
    rng: random.Random,
    defender: TankState,
    base_target: int,
    log: Optional[List[str]] = None,
    reason: str = "",
) -> bool:
    """
    戻り値: 制御失敗したかどうか。
    """
    if defender.retired:
        return False

    r = roll_2d6(rng, defender.handling + defender.stability_mod())
    ok = success(r, base_target)

    if log is not None:
        log.append(
            f"    制御判定{reason}: 出目{r.dice}+操{defender.handling}"
            f"+安補{defender.stability_mod()}={r.total} / 目標{base_target}"
            f" → {'成功' if ok else '失敗'}"
        )

    if r.fumble:
        accident(rng, defender, log, reason="制御出目2")
        return True

    if ok:
        return False

    fail_by = base_target - r.total
    defender.controls_failed += 1
    defender.blocked_this_round = True
    defender.move_reserved = False
    defender.lose_stability(1)

    if fail_by >= 5:
        defender.area = defender.area.left()
        defender.lead = 0
        defender.lose_stability(1)
        accident(rng, defender, log, reason=f"制御{fail_by}不足")
    elif fail_by >= 3:
        if defender.area != Area.BACK:
            defender.area = defender.area.left()
            defender.lead = 0
        else:
            defender.lose_stability(1)

    return True


def accident(rng: random.Random, t: TankState, log: Optional[List[str]] = None, reason: str = "") -> None:
    if t.retired:
        return
    t.accidents += 1
    result = d6(rng)
    if log is not None:
        log.append(f"    事故判定({reason}): 1d6={result}")

    if result == 1:
        t.retired = True
        t.hp = 0
        t.lead = 0
        if log is not None:
            log.append(f"    → {t.name} 大破リタイア")
    elif result == 2:
        t.area = Area.BACK
        t.hp -= 5
        t.lead = 0
        if log is not None:
            log.append(f"    → 横転: 後列へ、HP-5")
    elif result == 3:
        t.area = t.area.left()
        t.hp -= 3
        t.lead = 0
        if log is not None:
            log.append(f"    → 激突: 1段階後退、HP-3")
    elif result == 4:
        t.hp -= 3
        if log is not None:
            log.append(f"    → 車体損傷: HP-3")
    elif result == 5:
        t.stability = max(t.stability, 1)
        if log is not None:
            log.append(f"    → 立て直し: 安定1")
    elif result == 6:
        t.stability = max(t.stability, 2)
        if log is not None:
            log.append(f"    → 奇跡の復帰: 安定2、先行点維持")

    if t.hp <= 0 and not t.retired:
        t.retired = True
        t.lead = 0
        if log is not None:
            log.append(f"    → {t.name} 耐久0でリタイア")


def apply_damage(
    rng: random.Random,
    attacker: TankState,
    defender: TankState,
    raw_damage: int,
    stability_loss: int,
    control_bonus: int,
    log: Optional[List[str]] = None,
    source: str = "",
) -> None:
    if defender.retired:
        return
    actual = max(0, raw_damage - defender.armor)
    defender.hp -= actual
    attacker.damage_dealt += actual
    defender.lose_stability(stability_loss)

    if log is not None:
        log.append(
            f"    {source}命中: {defender.name} HP-{actual} 安定-{stability_loss}"
            f" (残HP{defender.hp}, 安定{defender.stability})"
        )

    if defender.hp <= 0:
        accident(rng, defender, log, reason="耐久0")
        if not defender.retired:
            defender.retired = True
        return

    if actual == 0:
        target = 6 + control_bonus
    else:
        target = 6 + actual + control_bonus

    failed = resolve_control_check(rng, defender, target, log, reason=f"/{source}")
    if failed:
        attacker.caused_control_failures += 1


def resolve_attack(
    rng: random.Random,
    attacker: TankState,
    defender: TankState,
    action: Action,
    round_no: int,
    log: Optional[List[str]] = None,
) -> None:
    if attacker.retired or defender.retired:
        return

    if action in (Action.CONTACT, Action.DANGEROUS_CONTACT):
        bonus = max(attacker.firepower, attacker.handling)
        attack_roll = roll_2d6(rng, bonus)
        defense_roll = roll_2d6(rng, defender.handling)
        hit = attack_roll.auto_success or attack_roll.total >= defense_roll.total

        if attack_roll.fumble:
            attacker.lose_stability(1)
            if action == Action.DANGEROUS_CONTACT:
                accident(rng, attacker, log, reason="危険接触出目2")
            if log is not None:
                log.append(f"  {attacker.name}:{action.value} 出目2 → 反動")
            return

        if log is not None:
            log.append(
                f"  {attacker.name}:{action.value}→{defender.name} "
                f"攻{attack_roll.dice}+{bonus}={attack_roll.total} / "
                f"避{defense_roll.dice}+操{defender.handling}={defense_roll.total} "
                f"→ {'命中' if hit else '失敗'}"
            )

        if not hit:
            attacker.lose_stability(1)
            return

        # 妨害大成功: 制御判定目標値+2固定
        crit_bonus = 2 if attack_roll.crit else 0

        if action == Action.CONTACT:
            apply_damage(rng, attacker, defender, 3, 1, crit_bonus, log, "接触")
        else:
            # 危険接触は命中時点で突破予約
            attacker.move_reserved = True
            attacker.lose_stability(1)
            apply_damage(rng, attacker, defender, 5, 2, crit_bonus, log, "危険接触")

        # カーブ・障害の追加制御
        if action == Action.DANGEROUS_CONTACT:
            if is_curve_round(round_no):
                curve_control(rng, attacker, action, log)
            elif is_obstacle_round(round_no):
                obstacle_control(rng, attacker, action, log)

    elif action in (Action.SHOOT, Action.HEAVY_SHOOT, Action.PIN_SHOOT):
        if action == Action.HEAVY_SHOOT:
            attacker.ammo -= 2
        else:
            attacker.ammo -= 1

        mod = shooting_modifier(attacker, defender)
        attack_roll = roll_2d6(rng, attacker.firepower + mod)
        defense_roll = roll_2d6(rng, defender.handling)
        hit = attack_roll.auto_success or attack_roll.total >= defense_roll.total

        if attack_roll.fumble:
            if log is not None:
                log.append(f"  {attacker.name}:{action.value} 出目2 → 不発")
            return

        if log is not None:
            log.append(
                f"  {attacker.name}:{action.value}→{defender.name} "
                f"攻{attack_roll.dice}+火{attacker.firepower}+補{mod}={attack_roll.total} / "
                f"避{defense_roll.dice}+操{defender.handling}={defense_roll.total} "
                f"→ {'命中' if hit else '失敗'}"
            )

        if not hit:
            return

        # 妨害大成功: 制御判定目標値+2固定
        crit_bonus = 2 if attack_roll.crit else 0

        if action == Action.PIN_SHOOT:
            # 牽制射撃: ダメージなし、安定-1、制御目標値6
            defender.lose_stability(1)
            failed = resolve_control_check(rng, defender, 6 + crit_bonus, log, reason="/牽制射撃")
            if failed:
                attacker.caused_control_failures += 1
        elif action == Action.SHOOT:
            apply_damage(rng, attacker, defender, 2, 0, crit_bonus, log, "射撃")
        elif action == Action.HEAVY_SHOOT:
            # 重射撃は通常+1、大成功ならさらに+2
            apply_damage(rng, attacker, defender, 4, 0, 1 + crit_bonus, log, "重射撃")


def curve_control(
    rng: random.Random,
    t: TankState,
    action: Action,
    log: Optional[List[str]] = None,
) -> None:
    if t.retired:
        return
    if action == Action.OVERTAKE:
        target = 9 + t.mobility
    else:
        target = 7 + t.mobility

    r = roll_2d6(rng, t.handling + t.stability_mod())
    ok = success(r, target)
    if log is not None:
        log.append(
            f"    カーブ制御: {t.name} 出目{r.dice}+操{t.handling}"
            f"+安補{t.stability_mod()}={r.total} / 目標{target}"
            f" → {'成功' if ok else '失敗'}"
        )

    if r.fumble:
        accident(rng, t, log, reason="カーブ出目2")
        return
    if ok:
        if r.crit:
            t.lead += 1
            if log is not None:
                log.append(f"    カーブ制御大成功: {t.name} 先行点+1")
        return

    fail_by = target - r.total
    t.lose_stability(1)
    if fail_by >= 3:
        t.move_reserved = False
        t.blocked_this_round = True
    if fail_by >= 5:
        t.lose_stability(1)
        accident(rng, t, log, reason=f"カーブ{fail_by}不足")


def obstacle_control(
    rng: random.Random,
    t: TankState,
    action: Action,
    log: Optional[List[str]] = None,
) -> None:
    if t.retired:
        return
    if action == Action.ACCEL:
        target = 8
    elif action in (Action.OVERTAKE, Action.DANGEROUS_CONTACT):
        target = 9
    else:
        return

    r = roll_2d6(rng, t.handling + t.stability_mod())
    ok = success(r, target)
    if log is not None:
        log.append(
            f"    障害制御: {t.name} 出目{r.dice}+操{t.handling}"
            f"+安補{t.stability_mod()}={r.total} / 目標{target}"
            f" → {'成功' if ok else '失敗'}"
        )

    if r.fumble:
        accident(rng, t, log, reason="障害出目2")
        return
    if ok:
        return

    fail_by = target - r.total
    t.lose_stability(1)
    if fail_by >= 3:
        t.move_reserved = False
        t.blocked_this_round = True
    if fail_by >= 5:
        t.lose_stability(1)
        accident(rng, t, log, reason=f"障害{fail_by}不足")


def resolve_movement_action(
    rng: random.Random,
    t: TankState,
    action: Action,
    round_no: int,
    log: Optional[List[str]] = None,
) -> None:
    if t.retired:
        return

    if action == Action.CRUISE:
        bonus = max(t.mobility, t.handling)
        r = roll_2d6(rng, bonus)
        ok = success(r, 6)
        if log is not None:
            log.append(f"  {t.name}:巡航 出目{r.dice}+{bonus}={r.total}/6 → {'成功' if ok else '失敗'}")
        if r.fumble:
            t.lose_stability(1)
            return
        if not ok:
            t.lose_stability(1)
            return
        t.recover_stability(1)
        if r.crit:
            if t.area == Area.FRONT:
                t.lead += 1
                if log is not None:
                    log.append(f"    巡航大成功: 前列のため先行点+1")
            else:
                t.move_reserved = True
                if log is not None:
                    log.append(f"    巡航大成功: 移動予約")
        # 第4R障害帯でも巡航大成功は追加制御なし
        return

    if action == Action.ACCEL:
        t.drive -= 1
        r = roll_2d6(rng, t.mobility)
        ok = success(r, 8)
        if log is not None:
            log.append(f"  {t.name}:加速 出目{r.dice}+機{t.mobility}={r.total}/8 → {'成功' if ok else '失敗'}")
        if r.fumble:
            t.lose_stability(1)
            return
        if not ok:
            t.lose_stability(1)
            return
        if t.area == Area.FRONT:
            t.lead += 2 if r.crit else 1
        else:
            t.move_reserved = True
            if r.crit:
                t.lead += 1
        if is_curve_round(round_no):
            curve_control(rng, t, action, log)
        elif is_obstacle_round(round_no):
            obstacle_control(rng, t, action, log)
        return

    if action == Action.OVERTAKE:
        t.drive -= 2
        target = 8 if is_curve_round(round_no) else 10
        r = roll_2d6(rng, t.handling)
        ok = success(r, target)
        if log is not None:
            log.append(f"  {t.name}:危険な追い抜き 出目{r.dice}+操{t.handling}={r.total}/{target} → {'成功' if ok else '失敗'}")
        if r.fumble:
            accident(rng, t, log, reason="追い抜き出目2")
            return
        if not ok:
            t.lose_stability(2)
            return
        if t.area == Area.FRONT:
            t.lead += 2 if r.crit else 1
        else:
            t.move_reserved = True
            t.lead += 2 if r.crit else 1
        if is_curve_round(round_no):
            curve_control(rng, t, action, log)
        elif is_obstacle_round(round_no):
            obstacle_control(rng, t, action, log)
        return

    if action == Action.DEFEND:
        t.recover_stability(1)
        if log is not None:
            log.append(f"  {t.name}:防御走行 安定+1")
        return

    if action == Action.REPAIR:
        r = roll_2d6(rng, t.handling)
        ok = success(r, 7)
        if log is not None:
            log.append(f"  {t.name}:立て直し 出目{r.dice}+操{t.handling}={r.total}/7 → {'成功' if ok else '失敗'}")
        if r.fumble:
            return
        if r.crit:
            t.recover_stability(3)
        elif ok:
            t.recover_stability(2)
        else:
            t.recover_stability(1)
        return


def apply_move_reservations(tanks: List[TankState], log: Optional[List[str]] = None) -> None:
    for t in tanks:
        if t.retired:
            continue
        if t.move_reserved and not t.blocked_this_round:
            old = t.area
            t.area = t.area.right()
            if log is not None and old != t.area:
                log.append(f"    移動確定: {t.name} {old.jp}→{t.area.jp}")
        t.move_reserved = False
        t.blocked_this_round = False


def final_order(rng: random.Random, tanks: List[TankState], log: Optional[List[str]] = None) -> List[TankState]:
    # リタイアしていない戦車をエリア別に判定
    scored: List[Tuple[float, TankState]] = []
    for t in tanks:
        if t.retired:
            # リタイアは下位。細かいリタイア時期は簡略化
            score = -1000 + rng.random()
        elif t.area == Area.FRONT:
            r = roll_2d6(rng, t.lead + t.mobility + t.drive_mod() + t.vehicle_condition_mod())
            score = 200 + r.total
            if log is not None:
                log.append(
                    f"  最終判定 {t.name}(前列): 出目{r.dice}+先{t.lead}+機{t.mobility}"
                    f"+駆補{t.drive_mod()}+状態{t.vehicle_condition_mod()}={r.total}"
                )
        elif t.area == Area.MID:
            r = roll_2d6(rng, t.mobility + t.drive_mod() + t.vehicle_condition_mod())
            score = 100 + r.total
            if log is not None:
                log.append(
                    f"  最終判定 {t.name}(中列): 出目{r.dice}+機{t.mobility}"
                    f"+駆補{t.drive_mod()}+状態{t.vehicle_condition_mod()}={r.total}"
                )
        else:
            r = roll_2d6(rng, t.handling + t.drive_mod() + t.vehicle_condition_mod())
            score = r.total
            if log is not None:
                log.append(
                    f"  最終判定 {t.name}(後列): 出目{r.dice}+操{t.handling}"
                    f"+駆補{t.drive_mod()}+状態{t.vehicle_condition_mod()}={r.total}"
                )
        scored.append((score, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored]



# ============================================================
# 配置決めフェーズ Ver.0.4
# ============================================================

PLACEMENT_WEIGHTS: Dict[str, Dict[str, int]] = {
    # front / middle / back
    "逃げ": {"front": 80, "middle": 15, "back": 5},
    "追込": {"front": 15, "middle": 30, "back": 55},
    "万能": {"front": 30, "middle": 50, "back": 20},
    "重戦車": {"front": 25, "middle": 60, "back": 15},
    "射撃": {"front": 10, "middle": 40, "back": 50},
    "荒くれ": {"front": 50, "middle": 35, "back": 15},
}


def choose_placement(rng: random.Random, t: TankState) -> str:
    weights = PLACEMENT_WEIGHTS.get(t.style, {"front": 25, "middle": 50, "back": 25})
    total = sum(weights.values())
    x = rng.uniform(0, total)
    acc = 0.0
    for key, weight in weights.items():
        acc += weight
        if x <= acc:
            return key
    return "middle"


def resolve_placement_phase(
    rng: random.Random,
    tanks: List[TankState],
    log: Optional[List[str]] = None,
) -> None:
    """レース開始前の初期配置決め。

    前列狙い: 2d6 + 機動力 + 操縦性 / 目標値9
      成功: 前列配置、駆動力-1
      失敗: 中列配置、駆動力-1、安定値-1
      出目2: 中列配置、駆動力-1、安定値-2
      出目11以上: 自動成功・大成功、前列配置、駆動力消費なし
    中列配置: 補正なし
    後列配置: 駆動力+1
    """
    if log is not None:
        log.append(commentary_text("sim_log", "placement_phase_start", "\n=== 配置決めフェーズ ==="))

    for t in tanks:
        intent = choose_placement(rng, t)
        if intent == "back":
            t.area = Area.BACK
            t.drive += 1
            if log is not None:
                log.append(
                    f"配置決め: {t.name} 後列配置 → 後列 駆動力+1 "
                    f"(駆{t.drive} 安{t.stability})"
                )
            continue

        if intent == "middle":
            t.area = Area.MID
            if log is not None:
                log.append(
                    f"配置決め: {t.name} 中列配置 → 中列 補正なし "
                    f"(駆{t.drive} 安{t.stability})"
                )
            continue

        # front
        bonus = t.mobility + t.handling
        r = roll_2d6(rng, bonus)
        target = 9
        if r.fumble:
            t.area = Area.MID
            t.drive = max(0, t.drive - 1)
            t.lose_stability(2)
            outcome = "出目2・失敗"
        elif r.crit:
            t.area = Area.FRONT
            outcome = "大成功"
        elif success(r, target):
            t.area = Area.FRONT
            t.drive = max(0, t.drive - 1)
            outcome = "成功"
        else:
            t.area = Area.MID
            t.drive = max(0, t.drive - 1)
            t.lose_stability(1)
            outcome = "失敗"

        if log is not None:
            log.append(
                f"配置決め: {t.name} 前列狙い 出目{r.dice}+機{t.mobility}+操{t.handling}={r.total}"
                f"/9 → {outcome}、{t.area.jp}配置 (駆{t.drive} 安{t.stability})"
            )

def race_once(
    specs: List[TankSpec],
    rng: random.Random,
    log_enabled: bool = False,
    commentary_rng: Optional[random.Random] = None,
) -> RaceResult:
    tanks = [TankState(spec=s) for s in specs]
    log: List[str] = []

    # Ver.0.4: 出走直後の配置決めフェーズ
    resolve_placement_phase(rng, tanks, log if log_enabled else None)

    for round_no in range(1, 7):
        if log_enabled:
            log.append(commentary_text("sim_log", "round_start", "\n=== R{round_no} ===", rng=commentary_rng, round_no=round_no))
        # ラウンド開始時の予約クリア
        for t in tanks:
            t.move_reserved = False
            t.blocked_this_round = False

        # 先に行動を選ぶ
        planned: List[Tuple[TankState, Action, Optional[TankState]]] = []
        for t in tanks:
            if t.retired:
                continue
            action = choose_action(rng, t, tanks, round_no)
            target = None
            if action in (Action.CONTACT, Action.DANGEROUS_CONTACT, Action.SHOOT, Action.HEAVY_SHOOT, Action.PIN_SHOOT):
                target = choose_target(rng, t, tanks, action)
                if target is None:
                    action = Action.CRUISE
            planned.append((t, action, target))

        # 移動系・防御・立て直しを先に解決
        for t, action, target in planned:
            if t.retired:
                continue
            if action in (Action.CRUISE, Action.ACCEL, Action.OVERTAKE, Action.DEFEND, Action.REPAIR):
                resolve_movement_action(rng, t, action, round_no, log if log_enabled else None)

        # 妨害系を解決
        for t, action, target in planned:
            if t.retired:
                continue
            if action in (Action.CONTACT, Action.DANGEROUS_CONTACT, Action.SHOOT, Action.HEAVY_SHOOT, Action.PIN_SHOOT):
                if target is not None and not target.retired:
                    resolve_attack(rng, t, target, action, round_no, log if log_enabled else None)

        # 移動確定
        apply_move_reservations(tanks, log if log_enabled else None)

        # 安定値が極端に低い場合の軽い事故誘発
        for t in tanks:
            if t.retired:
                continue
            if t.stability <= -2:
                accident(rng, t, log if log_enabled else None, reason="安定崩壊")
                t.stability = max(t.stability, 0)

        if log_enabled:
            ordered = sorted([t for t in tanks if not t.retired], key=lambda x: (x.area.value, x.lead, x.hp), reverse=True)
            log.append(commentary_text("sim_log", "ranking_prefix", "  暫定順位: ", rng=commentary_rng) + " / ".join(
                f"{i+1}.{x.name}[{x.area.jp} 先{x.lead} HP{x.hp} 安{x.stability} 駆{x.drive} 弾{x.ammo}]"
                for i, x in enumerate(ordered)
            ))

    if log_enabled:
        log.append(commentary_text("sim_log", "final_phase_start", "\n=== 最終順位判定 ===", rng=commentary_rng))
    order = final_order(rng, tanks, log if log_enabled else None)
    accidents = sum(t.accidents for t in tanks)

    if log_enabled:
        log.append(commentary_text("sim_log", "final_order_prefix", "  確定順位: ", rng=commentary_rng) + " / ".join(f"{i+1}.{t.name}" for i, t in enumerate(order)))

    return RaceResult(order=order, states=tanks, accident_count=accidents, log=log)


# ============================================================
# 集計
# ============================================================

@dataclass
class Stats:
    starts: int = 0
    wins: int = 0
    top3: int = 0
    retirements: int = 0
    total_rank: int = 0
    accidents: int = 0
    caused_control_failures: int = 0
    damage_dealt: int = 0


def simulate(
    rank: str,
    program: str,
    races: int,
    seed: int,
    log_one: bool = False,
) -> Tuple[List[TankSpec], Dict[str, Stats], float, Optional[List[str]]]:
    rng = random.Random(seed)
    specs = make_program(rank, program)
    stats: Dict[str, Stats] = {s.name: Stats() for s in specs}
    accident_sum = 0
    sample_log: Optional[List[str]] = None

    for i in range(races):
        result = race_once(specs, rng, log_enabled=(log_one and i == 0))
        if log_one and i == 0:
            sample_log = result.log

        accident_sum += result.accident_count
        rank_by_name = {t.name: idx + 1 for idx, t in enumerate(result.order)}

        for t in result.states:
            st = stats[t.name]
            st.starts += 1
            pos = rank_by_name[t.name]
            st.total_rank += pos
            if pos == 1:
                st.wins += 1
            if pos <= 3:
                st.top3 += 1
            if t.retired:
                st.retirements += 1
            st.accidents += t.accidents
            st.caused_control_failures += t.caused_control_failures
            st.damage_dealt += t.damage_dealt

    avg_accidents = accident_sum / races
    return specs, stats, avg_accidents, sample_log


def pct(x: float) -> float:
    return x * 100.0


def print_stats(specs: List[TankSpec], stats: Dict[str, Stats], avg_accidents: float, races: int) -> None:
    print(f"平均事故数: {avg_accidents:.2f}回 / レース")
    print()
    print("| 戦車 | 型 | 車格点 | 勝率 | 3着内率 | リタイア率 | 完走時勝率 | 安定複勝指数 | 平均順位 | 事故率 | 制御崩し/戦 | 与ダメ/戦 |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    rows = []
    for s in specs:
        st = stats[s.name]
        win = st.wins / st.starts
        top3 = st.top3 / st.starts
        ret = st.retirements / st.starts
        finish = max(1e-9, 1.0 - ret)
        finish_win = win / finish
        stable = pct(top3 - ret)
        avg_rank = st.total_rank / st.starts
        accidents_per_start = st.accidents / st.starts
        control_per_race = st.caused_control_failures / st.starts
        dmg_per_race = st.damage_dealt / st.starts
        rows.append((win, s, st, top3, ret, finish_win, stable, avg_rank, accidents_per_start, control_per_race, dmg_per_race))

    rows.sort(key=lambda x: x[0], reverse=True)
    for win, s, st, top3, ret, finish_win, stable, avg_rank, accidents_per_start, control_per_race, dmg_per_race in rows:
        print(
            f"| {s.name} | {s.style} | {tank_grade_points(s)} | "
            f"{pct(win):.2f}% | {pct(top3):.2f}% | {pct(ret):.2f}% | "
            f"{pct(finish_win):.2f}% | {stable:.2f} | {avg_rank:.2f} | "
            f"{pct(accidents_per_start):.2f}% | {control_per_race:.2f} | {dmg_per_race:.2f} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="鉄輪式三列戦車レース Ver.0.3 簡易シミュレータ")
    parser.add_argument("--rank", choices=["D", "C", "B", "A", "S", "all"], default="A")
    parser.add_argument("--program", choices=program_names() + ["all"], default="standard")
    parser.add_argument("--races", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log", action="store_true", help="最初の1レースだけ詳細ログを出す")
    args = parser.parse_args()

    ranks = ["D", "C", "B", "A", "S"] if args.rank == "all" else [args.rank]
    programs = program_names() if args.program == "all" else [args.program]

    for rank in ranks:
        for program in programs:
            print()
            print("=" * 80)
            print(f"ランク: {rank} / 番組: {program} / 試行数: {args.races} / seed: {args.seed}")
            print("=" * 80)
            specs, stats, avg_accidents, sample_log = simulate(
                rank=rank,
                program=program,
                races=args.races,
                seed=args.seed,
                log_one=args.log,
            )
            print_stats(specs, stats, avg_accidents, args.races)
            if sample_log:
                print("\n--- sample race log ---")
                print("\n".join(sample_log))


if __name__ == "__main__":
    main()
