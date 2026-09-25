import asyncio
import json
import random
import sqlite3
from datetime import datetime, date
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8872895896:AAFHWif78eEKLVq_yxXlJv1XGs_IFc33Y8M"
DB_PATH = "game.db"

# 👑 Список ID администраторов (узнать свой ID: @userinfobot)
ADMIN_IDS = [8182536846]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ================== БАЗА ДАННЫХ ==================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 100,
            level INTEGER DEFAULT 1,
            exp INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            last_bonus TEXT,
            last_chest TEXT,
            inventory TEXT DEFAULT '',
            achievements TEXT DEFAULT '',
            daily_quests TEXT DEFAULT '',
            daily_quests_date TEXT DEFAULT '',
            total_games INTEGER DEFAULT 0,
            pvp_wins INTEGER DEFAULT 0,
            pvp_losses INTEGER DEFAULT 0,
            roulette_spins INTEGER DEFAULT 0,
            purchases INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pvp_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            opponent_id INTEGER,
            bet INTEGER,
            creator_number INTEGER,
            opponent_number INTEGER,
            status TEXT DEFAULT 'waiting'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            key TEXT PRIMARY KEY,
            name TEXT,
            price INTEGER,
            description TEXT,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_id INTEGER,
            details TEXT,
            timestamp TEXT
        )
    """)

    # 🍀 Флаги админов
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_flags (
            admin_id INTEGER PRIMARY KEY,
            infinite_luck INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

    # Заполняем магазин по умолчанию
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM shop_items")
    if cur.fetchone()[0] == 0:
        for key, item in DEFAULT_SHOP_ITEMS.items():
            cur.execute(
                "INSERT INTO shop_items (key, name, price, description) VALUES (?, ?, ?, ?)",
                (key, item["name"], item["price"], item["desc"]),
            )
        conn.commit()
    conn.close()


DEFAULT_SHOP_ITEMS = {
    "double_exp": {"name": "⭐ Двойной опыт (1 игра)", "price": 100, "desc": "Удваивает опыт за следующую игру"},
    "lucky_charm": {"name": "🍀 Талисман удачи", "price": 200, "desc": "+20% к выигрышу в рулетке"},
    "extra_life": {"name": "❤️ Доп. попытка", "price": 150, "desc": "Даёт вторую попытку в угадай число"},
    "pvp_pass": {"name": "🎫 PvP пропуск", "price": 300, "desc": "Участие в PvP без комиссии"},
    "vip_title": {"name": "👑 VIP-статус", "price": 1000, "desc": "Особый титул в профиле"},
}


def get_shop_items():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key, name, price, description FROM shop_items WHERE active=1")
    rows = cur.fetchall()
    conn.close()
    return {r[0]: {"name": r[1], "price": r[2], "desc": r[3]} for r in rows}


def get_user(user_id: int, username: str = None) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or "Игрок"),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
    conn.close()
    keys = [
        "user_id", "username", "balance", "level", "exp", "wins", "losses",
        "last_bonus", "last_chest", "inventory", "achievements", "daily_quests",
        "daily_quests_date", "total_games", "pvp_wins", "pvp_losses",
        "roulette_spins", "purchases", "banned",
    ]
    return dict(zip(keys, row))


def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()


def get_top(limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT username, balance, level, wins, pvp_wins "
        "FROM users ORDER BY balance DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def log_admin(admin_id: int, action: str, target_id: Optional[int] = None, details: str = ""):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admin_log (admin_id, action, target_id, details, timestamp) VALUES (?, ?, ?, ?, ?)",
        (admin_id, action, target_id, details, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(balance), AVG(level), SUM(wins), SUM(pvp_wins) FROM users")
    row = cur.fetchone()
    conn.close()
    return {
        "total_users": row[0] or 0,
        "total_money": row[1] or 0,
        "avg_level": round(row[2] or 0, 2),
        "total_wins": row[3] or 0,
        "total_pvp_wins": row[4] or 0,
    }


# ================== ФЛАГИ АДМИНОВ ==================
def get_admin_flag(admin_id: int) -> dict:
    """Возвращает флаги админа"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT infinite_luck FROM admin_flags WHERE admin_id=?", (admin_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO admin_flags (admin_id) VALUES (?)", (admin_id,))
        conn.commit()
        luck = 0
    else:
        luck = row[0]
    conn.close()
    return {"infinite_luck": bool(luck)}


def toggle_admin_flag(admin_id: int, flag: str) -> bool:
    """Переключает флаг и возвращает новое значение"""
    if flag not in ("infinite_luck",):
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT {flag} FROM admin_flags WHERE admin_id=?", (admin_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO admin_flags (admin_id) VALUES (?)", (admin_id,))
        conn.commit()
        new_val = 1
        cur.execute(f"UPDATE admin_flags SET {flag}=? WHERE admin_id=?", (new_val, admin_id))
    else:
        new_val = 0 if row[0] else 1
        cur.execute(f"UPDATE admin_flags SET {flag}=? WHERE admin_id=?", (new_val, admin_id))
    conn.commit()
    conn.close()
    return bool(new_val)


def has_infinite_luck(user_id: int) -> bool:
    """Проверяет, включено ли бесконечное везение"""
    if not is_admin(user_id):
        return False
    return get_admin_flag(user_id)["infinite_luck"]


# ================== ИНВЕНТАРЬ ==================
def parse_list(s: str) -> list:
    return [x for x in s.split(",") if x] if s else []


# ================== ДОСТИЖЕНИЯ ==================
ACHIEVEMENTS = {
    "first_win": {"name": "🥇 Первая победа", "desc": "Выиграй в угадай число"},
    "hunter_10": {"name": "🏹 Охотник x10", "desc": "10 побед в угадай число"},
    "hunter_50": {"name": "🎯 Снайпер x50", "desc": "50 побед в угадай число"},
    "rich_1000": {"name": "💰 Богач", "desc": "Накопи 1000 монет"},
    "rich_10000": {"name": "💎 Миллионер", "desc": "Накопи 10000 монет"},
    "roulette_10": {"name": "🎰 Азартный", "desc": "10 вращений рулетки"},
    "pvp_first": {"name": "⚔️ Первый PvP бой", "desc": "Выиграй в PvP"},
    "pvp_master": {"name": "🛡️ Гладиатор", "desc": "10 побед в PvP"},
    "level_5": {"name": "⭐ Опытный", "desc": "Достигни 5 уровня"},
    "level_10": {"name": "🌟 Ветеран", "desc": "Достигни 10 уровня"},
    "shopper": {"name": "🛍️ Покупатель", "desc": "Сделай 5 покупок"},
    "chest_lover": {"name": "🎁 Кладоискатель", "desc": "Открой 10 сундуков"},
    "legendary_loot": {"name": "🌟 Легенда", "desc": "Получи легендарный предмет из сундука"},
}


def check_achievements(user_id: int):
    user = get_user(user_id)
    earned = parse_list(user["achievements"])
    new_achievements = []

    def unlock(key: str):
        if key not in earned and key in ACHIEVEMENTS:
            earned.append(key)
            new_achievements.append(ACHIEVEMENTS[key]["name"])

    if user["wins"] >= 1: unlock("first_win")
    if user["wins"] >= 10: unlock("hunter_10")
    if user["wins"] >= 50: unlock("hunter_50")
    if user["balance"] >= 1000: unlock("rich_1000")
    if user["balance"] >= 10000: unlock("rich_10000")
    if user["roulette_spins"] >= 10: unlock("roulette_10")
    if user["pvp_wins"] >= 1: unlock("pvp_first")
    if user["pvp_wins"] >= 10: unlock("pvp_master")
    if user["level"] >= 5: unlock("level_5")
    if user["level"] >= 10: unlock("level_10")
    if user["purchases"] >= 5: unlock("shopper")

    update_user(user_id, achievements=",".join(earned))
    return new_achievements


# ================== ДНЕВНЫЕ ЗАДАНИЯ ==================
DAILY_TASKS_POOL = [
    {"desc": "🎲 Сыграй 3 раза в 'Угадай число'", "type": "play_guess", "target": 3, "reward": 50},
    {"desc": "🎰 Сделай 2 вращения рулетки", "type": "spin_roulette", "target": 2, "reward": 40},
    {"desc": "⚔️ Проведи 1 PvP-бой", "type": "play_pvp", "target": 1, "reward": 100},
    {"desc": "🎁 Получи ежедневный бонус", "type": "get_bonus", "target": 1, "reward": 30},
    {"desc": "🛍️ Купи что-нибудь в магазине", "type": "buy_item", "target": 1, "reward": 60},
    {"desc": "📦 Открой сундук", "type": "open_chest", "target": 1, "reward": 70},
]


def get_daily_quests(user_id: int) -> list:
    user = get_user(user_id)
    today = date.today().isoformat()
    if user["daily_quests_date"] != today:
        selected = random.sample(DAILY_TASKS_POOL, 3)
        tasks = [{
            "desc": t["desc"], "type": t["type"], "target": t["target"],
            "progress": 0, "reward": t["reward"], "done": False, "claimed": False,
        } for t in selected]
        update_user(user_id, daily_quests=json.dumps(tasks), daily_quests_date=today)
        return tasks
    try:
        return json.loads(user["daily_quests"]) if user["daily_quests"] else []
    except Exception:
        return []


def update_quest_progress(user_id: int, quest_type: str, amount: int = 1):
    tasks = get_daily_quests(user_id)
    changed = False
    for t in tasks:
        if t["type"] == quest_type and not t["done"]:
            t["progress"] += amount
            if t["progress"] >= t["target"]:
                t["progress"] = t["target"]
                t["done"] = True
            changed = True
    if changed:
        update_user(user_id, daily_quests=json.dumps(tasks))


# ================== СУНДУК ==================
CHEST_LOOT = [
    ("money", "💰 20 монет", 20, 0.30, "common"),
    ("money", "💰 50 монет", 50, 0.20, "common"),
    ("money", "💰 100 монет", 100, 0.12, "rare"),
    ("money", "💰 250 монет", 250, 0.06, "rare"),
    ("money", "💰 500 монет", 500, 0.03, "epic"),
    ("money", "💎 2000 монет", 2000, 0.01, "legendary"),
    ("exp", "⭐ 25 опыта", 25, 0.10, "common"),
    ("exp", "⭐ 75 опыта", 75, 0.05, "rare"),
    ("item", "⭐ Двойной опыт", 0, 0.05, "rare"),
    ("item", "🍀 Талисман удачи", 0, 0.04, "rare"),
    ("item", "❤️ Доп. попытка", 0, 0.03, "epic"),
    ("item", "🎫 PvP пропуск", 0, 0.01, "epic"),
]

RARITY_EMOJI = {
    "common": "⚪",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
}


def open_chest_for(user_id: int) -> dict:
    # 🍀 Бесконечное везение — всегда легендарный лут
    if has_infinite_luck(user_id):
        chosen = [l for l in CHEST_LOOT if l[4] == "legendary"][0]
        type_, name, value, _, rarity = chosen
        user = get_user(user_id)
        result = {"type": type_, "name": name, "value": value, "rarity": rarity}
        if type_ == "money":
            update_user(user_id, balance=user["balance"] + value)
        elif type_ == "exp":
            exp = user["exp"] + value
            level = user["level"]
            while exp >= 100:
                exp -= 100
                level += 1
            update_user(user_id, exp=exp, level=level)
        return result

    rarities_chance = random.random()
    if rarities_chance < 0.70:
        allowed = ["common"]
    elif rarities_chance < 0.93:
        allowed = ["common", "rare"]
    elif rarities_chance < 0.995:
        allowed = ["rare", "epic"]
    else:
        allowed = ["epic", "legendary"]

    candidates = [l for l in CHEST_LOOT if l[4] in allowed]
    total = sum(c[3] for c in candidates)
    pick = random.uniform(0, total)
    acc = 0
    chosen = candidates[0]
    for c in candidates:
        acc += c[3]
        if pick <= acc:
            chosen = c
            break

    type_, name, value, _, rarity = chosen
    user = get_user(user_id)
    result = {"type": type_, "name": name, "value": value, "rarity": rarity}

    if type_ == "money":
        update_user(user_id, balance=user["balance"] + value)
    elif type_ == "exp":
        exp = user["exp"] + value
        level = user["level"]
        while exp >= 100:
            exp -= 100
            level += 1
        update_user(user_id, exp=exp, level=level)
    elif type_ == "item":
        item_key_map = {
            "⭐ Двойной опыт": "double_exp",
            "🍀 Талисман удачи": "lucky_charm",
            "❤️ Доп. попытка": "extra_life",
            "🎫 PvP пропуск": "pvp_pass",
        }
        key = item_key_map.get(name, "double_exp")
        inv = parse_list(user["inventory"])
        inv.append(key)
        update_user(user_id, inventory=",".join(inv))

    return result


# ================== FSM ==================
class GameStates(StatesGroup):
    waiting_number = State()
    waiting_pvp_bet = State()
    waiting_pvp_number = State()


class AdminStates(StatesGroup):
    waiting_user_id_give = State()
    waiting_amount_give = State()
    waiting_user_id_ban = State()
    waiting_username_msg = State()
    waiting_shop_price = State()


# ================== БОТ ==================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

active_games = {}
active_pvp = {}


# ================== КЛАВИАТУРЫ ==================
def main_menu(user_id: int = None):
    rows = [
        [
            InlineKeyboardButton(text="🎲 Угадай число", callback_data="play"),
            InlineKeyboardButton(text="🎰 Рулетка", callback_data="roulette"),
        ],
        [
            InlineKeyboardButton(text="⚔️ PvP", callback_data="pvp"),
            InlineKeyboardButton(text="🛒 Магазин", callback_data="shop"),
        ],
        [
            InlineKeyboardButton(text="📋 Задания", callback_data="quests"),
            InlineKeyboardButton(text="🏅 Достижения", callback_data="achiev"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            InlineKeyboardButton(text="🏆 Топ", callback_data="top"),
        ],
        [
            InlineKeyboardButton(text="🎁 Бонус", callback_data="bonus"),
            InlineKeyboardButton(text="📦 Сундук", callback_data="chest"),
        ],
    ]
    if user_id and is_admin(user_id):
        rows.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(callback: str = "back"):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback)]]
    )


def game_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]]
    )


def shop_kb():
    items = get_shop_items()
    rows = []
    for key, item in items.items():
        rows.append([
            InlineKeyboardButton(
                text=f"{item['name']} — 💰{item['price']}",
                callback_data=f"buy_{key}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pvp_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать игру", callback_data="pvp_create")],
            [InlineKeyboardButton(text="🎯 Присоединиться", callback_data="pvp_join")],
            [InlineKeyboardButton(text="📜 Список игр", callback_data="pvp_list")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
        ]
    )


def admin_kb(admin_id: int = None):
    luck_status = "🟢 ВКЛ" if (admin_id and has_infinite_luck(admin_id)) else "🔴 ВЫКЛ"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
            [
                InlineKeyboardButton(text="💰 Выдать монеты", callback_data="adm_give"),
                InlineKeyboardButton(text="💸 Забрать монеты", callback_data="adm_take"),
            ],
            [
                InlineKeyboardButton(text="🚫 Бан", callback_data="adm_ban"),
                InlineKeyboardButton(text="✅ Разбан", callback_data="adm_unban"),
            ],
            [InlineKeyboardButton(
                text=f"🍀 Бесконечное везение: {luck_status}",
                callback_data="adm_toggle_luck",
            )],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")],
            [InlineKeyboardButton(text="🛒 Управление магазином", callback_data="adm_shop")],
            [InlineKeyboardButton(text="📜 Лог действий", callback_data="adm_log")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
        ]
    )


def admin_shop_kb():
    items = get_shop_items()
    rows = []
    for key, item in items.items():
        rows.append([
            InlineKeyboardButton(
                text=f"✏️ {item['name']} — {item['price']}",
                callback_data=f"adm_edit_{key}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ================== СТАРТ ==================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id, message.from_user.username)
    if is_admin(message.from_user.id):
        luck = "🍀 Везение ВКЛ" if has_infinite_luck(message.from_user.id) else ""
        text = (
            f"👑 Привет, <b>админ</b>!\n\n"
            f"🎮 Игровой бот\n"
            f"{luck}\n"
            f"Тебе доступна админ-панель 👇"
        )
    else:
        text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            "🎮 Добро пожаловать в игровой бот v2.2!\n\n"
            "💡 <b>Возможности:</b>\n"
            "🎲 Угадай число\n"
            "🎰 Рулетка\n"
            "⚔️ PvP-бои\n"
            "🛒 Магазин\n"
            "📋 Дневные задания\n"
            "📦 Ежедневный сундук\n"
            "🏅 Достижения\n\n"
            "Выбирай действие 👇"
        )
    await message.answer(text, reply_markup=main_menu(message.from_user.id), parse_mode="HTML")


# ================== ПРОФИЛЬ ==================
@dp.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    user = get_user(call.from_user.id, call.from_user.username)
    inv = parse_list(user["inventory"])
    ach = parse_list(user["achievements"])
    vip = "👑 " if "vip_title" in inv else ""
    banned = " 🚫 <b>ЗАБАНЕН</b>" if user["banned"] else ""
    luck = " 🍀 <b>ВЕЗЕНИЕ ВКЛ</b>" if has_infinite_luck(call.from_user.id) else ""
    text = (
        f"👤 <b>Профиль</b> {vip}{banned}{luck}\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📛 Имя: {user['username']}\n"
        f"💰 Баланс: <b>{user['balance']}</b>\n"
        f"⭐ Уровень: <b>{user['level']}</b> (опыт: {user['exp']}/100)\n"
        f"🏅 Побед: <b>{user['wins']}</b> | Поражений: <b>{user['losses']}</b>\n"
        f"⚔️ PvP: <b>{user['pvp_wins']}</b>W / <b>{user['pvp_losses']}</b>L\n"
        f"🎰 Вращений: <b>{user['roulette_spins']}</b>\n"
        f"🎒 Инвентарь: <b>{len(inv)}</b> предметов\n"
        f"🏅 Достижений: <b>{len(ach)}/{len(ACHIEVEMENTS)}</b>"
    )
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "top")
async def cb_top(call: CallbackQuery):
    top = get_top(10)
    if not top:
        text = "🏆 Топ пуст."
    else:
        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        lines = ["🏆 <b>Топ-10 игроков</b>\n"]
        for i, (name, balance, level, wins, pvp_wins) in enumerate(top):
            lines.append(f"{medals[i]} {name} — 💰{balance} | ⭐{level} | 🏅{wins} | ⚔️{pvp_wins}")
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()


# ================== БОНУС ==================
@dp.callback_query(F.data == "bonus")
async def cb_bonus(call: CallbackQuery):
    user = get_user(call.from_user.id, call.from_user.username)
    today = date.today().isoformat()
    if user["last_bonus"] == today:
        await call.answer("🎁 Бонус уже получен сегодня!", show_alert=True)
        return
    reward = 50 if has_infinite_luck(call.from_user.id) else random.randint(20, 50)
    update_user(call.from_user.id, balance=user["balance"] + reward, last_bonus=today)
    update_quest_progress(call.from_user.id, "get_bonus")
    ach = check_achievements(call.from_user.id)
    text = f"🎁 Ты получил <b>{reward}</b> монет!"
    if ach:
        text += f"\n\n🏅 Новые достижения: {', '.join(ach)}"
    await call.answer(text, show_alert=True)


# ================== СУНДУК ==================
@dp.callback_query(F.data == "chest")
async def cb_chest(call: CallbackQuery):
    user = get_user(call.from_user.id, call.from_user.username)
    today = date.today().isoformat()

    if user["last_chest"] == today:
        await call.answer(
            "📦 Сундук уже открыт сегодня!\nВозвращайся завтра 🕐",
            show_alert=True,
        )
        return

    msg = await call.message.edit_text(
        "📦 <b>Открываем сундук...</b>\n\n▫️▫️▫️▫️▫️▫️▫️",
        parse_mode="HTML",
    )
    await asyncio.sleep(0.6)
    await msg.edit_text("📦 <b>Открываем сундук...</b>\n\n🟨🟨🟨▫️▫️▫️▫️", parse_mode="HTML")
    await asyncio.sleep(0.5)
    await msg.edit_text("📦 <b>Открываем сундук...</b>\n\n🟨🟨🟨🟨🟨▫️▫️", parse_mode="HTML")
    await asyncio.sleep(0.5)

    result = open_chest_for(call.from_user.id)
    update_user(call.from_user.id, last_chest=today)
    update_quest_progress(call.from_user.id, "open_chest")

    rarity_emoji = RARITY_EMOJI.get(result["rarity"], "⚪")
    rarity_name = {
        "common": "Обычное",
        "rare": "Редкое",
        "epic": "Эпическое",
        "legendary": "🌟 ЛЕГЕНДАРНОЕ",
    }.get(result["rarity"], "Обычное")

    text = (
        f"🎉 <b>Сундук открыт!</b>\n\n"
        f"{rarity_emoji} Редкость: <b>{rarity_name}</b>\n"
        f"🎁 Добыча: <b>{result['name']}</b>\n"
    )

    user = get_user(call.from_user.id)
    ach = check_achievements(call.from_user.id)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM admin_log WHERE admin_id=? AND action='chest_opened'", (call.from_user.id,))
    chests = cur.fetchone()[0]
    conn.close()
    if chests >= 10:
        earned = parse_list(user["achievements"])
        if "chest_lover" not in earned:
            earned.append("chest_lover")
            update_user(call.from_user.id, achievements=",".join(earned))
            ach.append(ACHIEVEMENTS["chest_lover"]["name"])

    if result["rarity"] == "legendary":
        earned = parse_list(get_user(call.from_user.id)["achievements"])
        if "legendary_loot" not in earned:
            earned.append("legendary_loot")
            update_user(call.from_user.id, achievements=",".join(earned))
            ach.append(ACHIEVEMENTS["legendary_loot"]["name"])

    log_admin(call.from_user.id, "chest_opened", call.from_user.id, result["name"])

    if ach:
        text += f"\n🏅 Новые достижения: {', '.join(ach)}"

    await msg.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="back")]]
        ),
        parse_mode="HTML",
    )
    await call.answer()


# ================== УГАДАЙ ЧИСЛО ==================
@dp.callback_query(F.data == "play")
async def cb_play(call: CallbackQuery, state: FSMContext):
    user = get_user(call.from_user.id)
    if user["balance"] < 5 and not has_infinite_luck(call.from_user.id):
        await call.answer("❌ Нужно минимум 5 монет!", show_alert=True)
        return

    number = random.randint(1, 100)
    active_games[call.from_user.id] = {"number": number, "tries": 0}
    await state.set_state(GameStates.waiting_number)
    await call.message.edit_text(
        "🎲 <b>Угадай число (1–100)</b>\n\n"
        "Стоимость попытки: <b>5 монет</b>\n"
        "Приз: <b>50 монет + 10 опыта</b>\n\n"
        "Напиши число 👇",
        reply_markup=game_menu(),
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(GameStates.waiting_number, F.text)
async def handle_guess(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in active_games:
        await message.answer("❗ Игра не активна. /start")
        await state.clear()
        return

    user = get_user(user_id, message.from_user.username)
    infinite_luck = has_infinite_luck(user_id)

    if user["balance"] < 5 and not infinite_luck:
        await message.answer("❌ Нет монет!")
        await state.clear()
        del active_games[user_id]
        return

    try:
        guess = int(message.text.strip())
        if not 1 <= guess <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введи число 1–100")
        return

    game = active_games[user_id]
    game["tries"] += 1

    # 💰 Админ с везением платит 0 монет
    if infinite_luck:
        balance = user["balance"]
    else:
        balance = user["balance"] - 5

    update_quest_progress(user_id, "play_guess")

    # 🍀 С везением — всегда победа
    if infinite_luck or guess == game["number"]:
        exp_gain = 10
        inv = parse_list(user["inventory"])
        if "double_exp" in inv:
            exp_gain *= 2
            inv.remove("double_exp")

        exp = user["exp"] + exp_gain
        level = user["level"]
        while exp >= 100:
            exp -= 100
            level += 1

        update_user(
            user_id,
            balance=balance + 50,
            exp=exp,
            level=level,
            wins=user["wins"] + 1,
            total_games=user["total_games"] + 1,
            inventory=",".join(inv),
        )
        ach = check_achievements(user_id)
        del active_games[user_id]
        await state.clear()

        text = (
            f"🎉 <b>Победа!</b>\n\n"
            f"Число: <b>{game['number']}</b> | Попыток: <b>{game['tries']}</b>\n"
            f"💰 +50 | ⭐ +{exp_gain}\n"
            f"Баланс: <b>{balance + 50}</b>"
        )
        if infinite_luck:
            text += "\n\n🍀 <i>Сработало бесконечное везение!</i>"
        if ach:
            text += f"\n\n🏅 Достижения: {', '.join(ach)}"
        await message.answer(text, reply_markup=main_menu(user_id), parse_mode="HTML")
    else:
        hint = "📈 Больше" if guess < game["number"] else "📉 Меньше"
        update_user(user_id, balance=balance, losses=user["losses"] + 1)
        await message.answer(
            f"{hint}!\n💰 Осталось: <b>{balance}</b> | Попыток: {game['tries']}",
            reply_markup=game_menu(),
            parse_mode="HTML",
        )


# ================== РУЛЕТКА ==================
@dp.callback_query(F.data == "roulette")
async def cb_roulette(call: CallbackQuery):
    user = get_user(call.from_user.id)
    infinite_luck = has_infinite_luck(call.from_user.id)

    if user["balance"] < 20 and not infinite_luck:
        await call.answer("❌ Нужно 20 монет!", show_alert=True)
        return

    inv = parse_list(user["inventory"])
    lucky = "lucky_charm" in inv

    if infinite_luck:
        prize, win = 500, True  # всегда джекпот
    else:
        roll = random.random()
        if roll < 0.40: prize, win = 0, False
        elif roll < 0.65: prize, win = 20, True
        elif roll < 0.80: prize, win = 40, True
        elif roll < 0.90: prize, win = 60, True
        elif roll < 0.97: prize, win = 100, True
        else: prize, win = 500, True

    if lucky and win:
        prize = int(prize * 1.2)

    # 💰 Админ с везением не платит за вращение
    cost = 0 if infinite_luck else 20
    new_balance = user["balance"] - cost + prize

    update_user(
        call.from_user.id,
        balance=new_balance,
        roulette_spins=user["roulette_spins"] + 1,
    )
    update_quest_progress(call.from_user.id, "spin_roulette")
    ach = check_achievements(call.from_user.id)

    if win:
        text = f"🎰 <b>Рулетка</b>\n\n🎉 Выигрыш: <b>{prize}</b>!\n💰 Баланс: <b>{new_balance}</b>"
    else:
        text = f"🎰 <b>Рулетка</b>\n\n😢 Пусто!\n💰 Баланс: <b>{new_balance}</b>"
    if infinite_luck:
        text += "\n\n🍀 <i>Сработало бесконечное везение!</i>"
    if ach:
        text += f"\n\n🏅 Достижения: {', '.join(ach)}"

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎰 Ещё раз", callback_data="roulette")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
            ]
        ),
        parse_mode="HTML",
    )
    await call.answer()


# ================== МАГАЗИН ==================
@dp.callback_query(F.data == "shop")
async def cb_shop(call: CallbackQuery):
    await call.message.edit_text(
        "🛒 <b>Магазин</b>\n\nВыбирай предмет:",
        reply_markup=shop_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy(call: CallbackQuery):
    key = call.data[4:]
    items = get_shop_items()
    if key not in items:
        await call.answer("❌ Товар не найден", show_alert=True)
        return

    item = items[key]
    user = get_user(call.from_user.id)
    infinite_luck = has_infinite_luck(call.from_user.id)

    if user["balance"] < item["price"] and not infinite_luck:
        await call.answer(f"❌ Нужно {item['price']} монет!", show_alert=True)
        return

    inv = parse_list(user["inventory"])
    inv.append(key)

    # 💰 Админ с везением покупает бесплатно
    cost = 0 if infinite_luck else item["price"]

    update_user(
        call.from_user.id,
        balance=user["balance"] - cost,
        inventory=",".join(inv),
        purchases=user["purchases"] + 1,
    )
    update_quest_progress(call.from_user.id, "buy_item")
    ach = check_achievements(call.from_user.id)

    text = f"✅ Куплено: <b>{item['name']}</b>\n💰 Остаток: <b>{user['balance'] - cost}</b>"
    if infinite_luck:
        text += "\n\n🍀 <i>Бесплатно благодаря везению!</i>"
    if ach:
        text += f"\n\n🏅 Достижения: {', '.join(ach)}"
    await call.answer(text, show_alert=True)


# ================== ДОСТИЖЕНИЯ ==================
@dp.callback_query(F.data == "achiev")
async def cb_achiev(call: CallbackQuery):
    user = get_user(call.from_user.id)
    earned = parse_list(user["achievements"])
    lines = [f"🏅 <b>Достижения</b> ({len(earned)}/{len(ACHIEVEMENTS)})\n"]
    for key, a in ACHIEVEMENTS.items():
        mark = "✅" if key in earned else "🔒"
        lines.append(f"{mark} <b>{a['name']}</b> — {a['desc']}")
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()


# ================== ЗАДАНИЯ ==================
@dp.callback_query(F.data == "quests")
async def cb_quests(call: CallbackQuery):
    tasks = get_daily_quests(call.from_user.id)
    if not tasks:
        await call.answer("Нет заданий", show_alert=True)
        return

    lines = ["📋 <b>Дневные задания</b>\n"]
    for i, t in enumerate(tasks, 1):
        status = "✅" if t["claimed"] else ("🎁" if t["done"] else "⏳")
        lines.append(
            f"{status} {t['desc']}\n"
            f"    Прогресс: {t['progress']}/{t['target']} | 💰{t['reward']}"
        )

    rows = []
    for i, t in enumerate(tasks):
        if t["done"] and not t["claimed"]:
            rows.append([InlineKeyboardButton(text=f"🎁 Забрать #{i+1}", callback_data=f"claim_{i}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back")])

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("claim_"))
async def cb_claim(call: CallbackQuery):
    idx = int(call.data.split("_")[1])
    tasks = get_daily_quests(call.from_user.id)
    if idx >= len(tasks):
        await call.answer("❌ Ошибка", show_alert=True)
        return

    t = tasks[idx]
    if not t["done"] or t["claimed"]:
        await call.answer("❌ Задание не готово", show_alert=True)
        return

    t["claimed"] = True
    user = get_user(call.from_user.id)
    update_user(
        call.from_user.id,
        balance=user["balance"] + t["reward"],
        daily_quests=json.dumps(tasks),
    )
    await call.answer(f"🎁 +{t['reward']} монет!", show_alert=True)
    await cb_quests(call)


# ================== PVP ==================
@dp.callback_query(F.data == "pvp")
async def cb_pvp(call: CallbackQuery):
    text = "⚔️ <b>PvP-бои</b>\n\nСоздай игру со ставкой — победитель забирает банк!"
    await call.message.edit_text(text, reply_markup=pvp_menu_kb(), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "pvp_create")
async def cb_pvp_create(call: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.waiting_pvp_bet)
    await call.message.edit_text(
        "💰 Введи ставку (минимум 50 монет):",
        reply_markup=back_kb("pvp"),
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(GameStates.waiting_pvp_bet, F.text)
async def pvp_bet_input(message: Message, state: FSMContext):
    try:
        bet = int(message.text.strip())
        if bet < 50:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введи число от 50")
        return

    user = get_user(message.from_user.id)
    infinite_luck = has_infinite_luck(message.from_user.id)

    if user["balance"] < bet and not infinite_luck:
        await message.answer("❌ Недостаточно монет!")
        return

    # 💰 Админ с везением не платит
    cost = 0 if infinite_luck else bet
    update_user(message.from_user.id, balance=user["balance"] - cost)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pvp_games (creator_id, bet, status) VALUES (?, ?, 'waiting')",
        (message.from_user.id, bet),
    )
    game_id = cur.lastrowid
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ Игра #{game_id} создана!\n💰 Ставка: {bet}\n\nЖдём соперника...",
        reply_markup=main_menu(message.from_user.id),
    )


@dp.callback_query(F.data == "pvp_list")
async def cb_pvp_list(call: CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT game_id, creator_id, bet FROM pvp_games WHERE status='waiting' LIMIT 10")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await call.answer("😔 Нет открытых игр", show_alert=True)
        return

    lines = ["📜 <b>Открытые PvP-игры:</b>\n"]
    rows_kb = []
    for gid, cid, bet in rows:
        lines.append(f"#{gid} — создатель: <code>{cid}</code> | 💰{bet}")
        rows_kb.append([InlineKeyboardButton(text=f"⚔️ Присоединиться к #{gid}", callback_data=f"join_{gid}")])
    rows_kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pvp")])

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_kb),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data == "pvp_join")
async def cb_pvp_join_redirect(call: CallbackQuery):
    await cb_pvp_list(call)


@dp.callback_query(F.data.startswith("join_"))
async def cb_join(call: CallbackQuery, state: FSMContext):
    game_id = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT creator_id, bet, status FROM pvp_games WHERE game_id=?", (game_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await call.answer("❌ Игра не найдена", show_alert=True)
        return
    creator_id, bet, status = row
    if status != "waiting":
        await call.answer("❌ Игра уже занята", show_alert=True)
        return
    if creator_id == call.from_user.id:
        await call.answer("❌ Нельзя играть с собой!", show_alert=True)
        return

    user = get_user(call.from_user.id)
    infinite_luck = has_infinite_luck(call.from_user.id)

    if user["balance"] < bet and not infinite_luck:
        await call.answer(f"❌ Нужно {bet} монет!", show_alert=True)
        return

    cost = 0 if infinite_luck else bet
    update_user(call.from_user.id, balance=user["balance"] - cost)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE pvp_games SET opponent_id=?, status='playing' WHERE game_id=?",
        (call.from_user.id, game_id),
    )
    conn.commit()
    conn.close()

    active_pvp[game_id] = {
        "creator_id": creator_id,
        "opponent_id": call.from_user.id,
        "bet": bet,
        "creator_number": None,
        "opponent_number": None,
        "secret": random.randint(1, 100),
    }

    await state.update_data(pvp_game_id=game_id)
    await state.set_state(GameStates.waiting_pvp_number)

    await call.message.edit_text(
        f"⚔️ Игра #{game_id} началась!\n💰 Банк: {bet*2}\n\n"
        f"Загадай число от 1 до 100:",
        parse_mode="HTML",
    )
    await call.answer()

    try:
        await bot.send_message(
            creator_id,
            f"⚔️ Твой PvP-матч #{game_id} начался!\n\n"
            f"Загадай число от 1 до 100 (ближе к секретному — победа):",
        )
    except Exception as e:
        print("Ошибка уведомления:", e)


@dp.message(GameStates.waiting_pvp_number, F.text)
async def pvp_opponent_number(message: Message, state: FSMContext):
    data = await state.get_data()
    game_id = data.get("pvp_game_id")
    if not game_id or game_id not in active_pvp:
        await message.answer("❗ Игра не активна")
        await state.clear()
        return

    try:
        num = int(message.text.strip())
        if not 1 <= num <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❗ Число 1–100")
        return

    active_pvp[game_id]["opponent_number"] = num
    await state.clear()
    await message.answer(f"✅ Твоё число: {num}. Ждём соперника...")

    await try_resolve_pvp(game_id)


@dp.message(F.text.regexp(r"^\d+$"))
async def pvp_creator_number(message: Message):
    for gid, g in list(active_pvp.items()):
        if g["creator_id"] == message.from_user.id and g["creator_number"] is None:
            try:
                num = int(message.text.strip())
                if not 1 <= num <= 100:
                    continue
            except ValueError:
                continue
            g["creator_number"] = num
            await message.answer(f"✅ Твоё число: {num}")
            await try_resolve_pvp(gid)
            return


async def try_resolve_pvp(game_id: int):
    g = active_pvp.get(game_id)
    if not g or g["creator_number"] is None or g["opponent_number"] is None:
        return

    secret = g["secret"]
    c_diff = abs(g["creator_number"] - secret)
    o_diff = abs(g["opponent_number"] - secret)

    creator = get_user(g["creator_id"])
    opponent = get_user(g["opponent_id"])
    prize = g["bet"] * 2

    # 🍀 Учёт бесконечного везения
    creator_luck = has_infinite_luck(g["creator_id"])
    opponent_luck = has_infinite_luck(g["opponent_id"])

    if creator_luck and not opponent_luck:
        winner, loser = g["creator_id"], g["opponent_id"]
        w_user = creator
    elif opponent_luck and not creator_luck:
        winner, loser = g["opponent_id"], g["creator_id"]
        w_user = opponent
    elif creator_luck and opponent_luck:
        winner = None  # оба везунчика — ничья
    elif c_diff < o_diff:
        winner, loser = g["creator_id"], g["opponent_id"]
        w_user = creator
    elif o_diff < c_diff:
        winner, loser = g["opponent_id"], g["creator_id"]
        w_user = opponent
    else:
        winner = None

    if winner is None:
        update_user(g["creator_id"], balance=creator["balance"] + g["bet"])
        update_user(g["opponent_id"], balance=opponent["balance"] + g["bet"])
        result_text = (
            f"🤝 <b>Ничья!</b>\n\n🎯 Секрет: <b>{secret}</b>\n"
            f"Ты: {g['creator_number']} | Соперник: {g['opponent_number']}\n"
            f"💰 Ставки возвращены."
        )
    else:
        update_user(winner, balance=w_user["balance"] + prize, pvp_wins=w_user["pvp_wins"] + 1)
        loser_user = opponent if winner == g["creator_id"] else creator
        update_user(loser, pvp_losses=loser_user["pvp_losses"] + 1)
        update_quest_progress(winner, "play_pvp")
        update_quest_progress(loser, "play_pvp")
        ach = check_achievements(winner)

        luck_note = ""
        if creator_luck or opponent_luck:
            luck_note = "\n🍀 <i>Сработало бесконечное везение!</i>"

        result_text = (
            f"🏆 <b>PvP #{game_id} завершён!</b>\n\n"
            f"🎯 Секрет: <b>{secret}</b>\n"
            f"👤 Создатель: {g['creator_number']} (разн. {c_diff})\n"
            f"⚔️ Соперник: {g['opponent_number']} (разн. {o_diff})\n"
            f"💰 Банк: <b>{prize}</b>{luck_note}"
        )
        if ach:
            result_text += f"\n🏅 {', '.join(ach)}"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE pvp_games SET status='finished' WHERE game_id=?", (game_id,))
    conn.commit()
    conn.close()
    del active_pvp[game_id]

    try:
        await bot.send_message(g["creator_id"], result_text, parse_mode="HTML")
        await bot.send_message(g["opponent_id"], result_text, parse_mode="HTML")
    except Exception as e:
        print("Ошибка отправки:", e)


# ================== АДМИН-ПАНЕЛЬ ==================
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        "👑 <b>Админ-панель</b>\n\nВыбери действие:",
        reply_markup=admin_kb(call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data == "adm_toggle_luck")
async def cb_adm_toggle_luck(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return

    new_val = toggle_admin_flag(call.from_user.id, "infinite_luck")
    log_admin(call.from_user.id, "toggle_luck", call.from_user.id, "ON" if new_val else "OFF")

    status = "включено 🟢" if new_val else "выключено 🔴"
    await call.answer(f"🍀 Бесконечное везение {status}", show_alert=True)

    # Обновляем клавиатуру
    await call.message.edit_reply_markup(reply_markup=admin_kb(call.from_user.id))


@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return

    s = get_stats()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE banned=1")
    banned = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pvp_games WHERE status='waiting'")
    open_pvp = cur.fetchone()[0]
    conn.close()

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{s['total_users']}</b>\n"
        f"🚫 Забанено: <b>{banned}</b>\n"
        f"💰 Всего монет: <b>{s['total_money']}</b>\n"
        f"⭐ Средний уровень: <b>{s['avg_level']}</b>\n"
        f"🏅 Всего побед: <b>{s['total_wins']}</b>\n"
        f"⚔️ PvP побед: <b>{s['total_pvp_wins']}</b>\n"
        f"📜 Открытых PvP: <b>{open_pvp}</b>"
    )
    await call.message.edit_text(text, reply_markup=back_kb("admin_panel"), parse_mode="HTML")
    await call.answer()


@dp.callback_query(F.data == "adm_give")
async def cb_adm_give(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_user_id_give)
    await state.update_data(adm_action="give")
    await call.message.edit_text(
        "💰 Введи <b>ID пользователя</b>, которому выдать монеты:",
        reply_markup=back_kb("admin_panel"),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data == "adm_take")
async def cb_adm_take(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_user_id_give)
    await state.update_data(adm_action="take")
    await call.message.edit_text(
        "💸 Введи <b>ID пользователя</b>, у которого забрать монеты:",
        reply_markup=back_kb("admin_panel"),
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(AdminStates.waiting_user_id_give)
async def adm_input_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Введи корректный ID (число)")
        return

    data = await state.get_data()
    await state.update_data(target_id=target_id, adm_action=data.get("adm_action", "give"))
    await state.set_state(AdminStates.waiting_amount_give)
    await message.answer("💰 Введи сумму:")


@dp.message(AdminStates.waiting_amount_give)
async def adm_input_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Введи положительное число")
        return

    data = await state.get_data()
    target_id = data["target_id"]
    action = data["adm_action"]

    target = get_user(target_id)
    if action == "give":
        update_user(target_id, balance=target["balance"] + amount)
        log_admin(message.from_user.id, "give_money", target_id, f"+{amount}")
        await message.answer(
            f"✅ Выдано {amount} монет <code>{target_id}</code>\n"
            f"💰 Новый баланс: {target['balance'] + amount}",
            reply_markup=main_menu(message.from_user.id),
            parse_mode="HTML",
        )
        try:
            await bot.send_message(target_id, f"💰 Админ выдал тебе <b>{amount}</b> монет!", parse_mode="HTML")
        except Exception:
            pass
    else:
        new_balance = max(0, target["balance"] - amount)
        update_user(target_id, balance=new_balance)
        log_admin(message.from_user.id, "take_money", target_id, f"-{amount}")
        await message.answer(
            f"✅ Забрано {amount} монет у <code>{target_id}</code>\n"
            f"💰 Новый баланс: {new_balance}",
            reply_markup=main_menu(message.from_user.id),
            parse_mode="HTML",
        )
        try:
            await bot.send_message(target_id, f"💸 Админ забрал у тебя <b>{amount}</b> монет.", parse_mode="HTML")
        except Exception:
            pass

    await state.clear()


@dp.callback_query(F.data == "adm_ban")
async def cb_adm_ban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_user_id_ban)
    await state.update_data(ban_action="ban")
    await call.message.edit_text("🚫 Введи ID пользователя для бана:")
    await call.answer()


@dp.callback_query(F.data == "adm_unban")
async def cb_adm_unban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_user_id_ban)
    await state.update_data(ban_action="unban")
    await call.message.edit_text("✅ Введи ID пользователя для разбана:")
    await call.answer()


@dp.message(AdminStates.waiting_user_id_ban)
async def adm_ban_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❗ Некорректный ID")
        return

    data = await state.get_data()
    action = data.get("ban_action", "ban")

    if action == "ban":
        update_user(target_id, banned=1)
        log_admin(message.from_user.id, "ban", target_id)
        await message.answer(
            f"🚫 Пользователь <code>{target_id}</code> забанен.",
            reply_markup=main_menu(message.from_user.id),
            parse_mode="HTML",
        )
        try:
            await bot.send_message(target_id, "🚫 Ты был забанен в боте.")
        except Exception:
            pass
    else:
        update_user(target_id, banned=0)
        log_admin(message.from_user.id, "unban", target_id)
        await message.answer(
            f"✅ Пользователь <code>{target_id}</code> разбанен.",
            reply_markup=main_menu(message.from_user.id),
            parse_mode="HTML",
        )
        try:
            await bot.send_message(target_id, "✅ Ты был разбанен!")
        except Exception:
            pass

    await state.clear()


@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_username_msg)
    await call.message.edit_text(
        "📢 Введи текст для рассылки всем пользователям:",
        reply_markup=back_kb("admin_panel"),
    )
    await call.answer()


@dp.message(AdminStates.waiting_username_msg)
async def adm_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text
    if not text:
        await message.answer("❗ Отправь текст")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE banned=0")
    users = [r[0] for r in cur.fetchall()]
    conn.close()

    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от админа:</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    log_admin(message.from_user.id, "broadcast", None, f"sent={sent}, failed={failed}")
    await message.answer(
        f"📢 Рассылка завершена!\n✅ Успешно: {sent}\n❌ Ошибок: {failed}",
        reply_markup=main_menu(message.from_user.id),
    )
    await state.clear()


@dp.callback_query(F.data == "adm_shop")
async def cb_adm_shop(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        "🛒 <b>Управление магазином</b>\n\nВыбери товар для редактирования цены:",
        reply_markup=admin_shop_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@dp.callback_query(F.data.startswith("adm_edit_"))
async def cb_adm_edit_item(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return

    key = call.data[9:]
    items = get_shop_items()
    if key not in items:
        await call.answer("❌ Товар не найден", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_shop_price)
    await state.update_data(edit_key=key)

    await call.message.edit_text(
        f"✏️ <b>{items[key]['name']}</b>\n"
        f"Текущая цена: {items[key]['price']}\n\n"
        f"Введи новую цену:",
        parse_mode="HTML",
    )
    await call.answer()


@dp.message(AdminStates.waiting_shop_price, F.text)
async def adm_edit_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❗ Некорректная цена")
        return

    data = await state.get_data()
    key = data.get("edit_key")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE shop_items SET price=? WHERE key=?", (price, key))
    conn.commit()
    conn.close()

    log_admin(message.from_user.id, "edit_shop_price", None, f"{key}={price}")
    await message.answer(
        f"✅ Цена товара <b>{key}</b> обновлена: {price}",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="HTML",
    )
    await state.clear()


@dp.callback_query(F.data == "adm_log")
async def cb_adm_log(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("🚫 Нет доступа", show_alert=True)
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT admin_id, action, target_id, details, timestamp FROM admin_log ORDER BY id DESC LIMIT 15")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        text = "📜 Лог пуст."
    else:
        lines = ["📜 <b>Последние действия</b>\n"]
        for aid, act, tid, det, ts in rows:
            t = ts[11:16]
            target = f" → {tid}" if tid else ""
            lines.append(f"[{t}] <code>{aid}</code> {act}{target} {det}")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_kb("admin_panel"), parse_mode="HTML")
    await call.answer()


# ================== ОБЩИЕ ==================
@dp.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    active_games.pop(call.from_user.id, None)
    await state.clear()
    await call.message.edit_text("❌ Отменено.", reply_markup=main_menu(call.from_user.id))
    await call.answer()


@dp.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery):
    await call.message.edit_text(
        "🎮 Главное меню", reply_markup=main_menu(call.from_user.id)
    )
    await call.answer()


# ================== ЗАПУСК ==================
async def main():
    init_db()
    print("🤖 Бот v2.2 запущен...")
    print(f"👑 Админов в списке: {len(ADMIN_IDS)}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")