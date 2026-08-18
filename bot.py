# 🤖 ربات فروش VPN — نسخه فول اپشن (قیمت ماهانه ۶۷ هزار)
# تنظیمات حساس فقط از متغیرهای محیطی خوانده می‌شوند.

# ================= بقیه کد (دست نزن) =================
import asyncio, logging, uuid, random, os
from datetime import datetime, timedelta, date
import aiosqlite
from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
                           KeyboardButton, InlineKeyboardButton as IB, InlineKeyboardMarkup as IKM)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

ADMIN_IDS = []
for raw_admin_id in os.getenv("ADMIN_IDS", "").split(","):
    raw_admin_id = raw_admin_id.strip()
    if raw_admin_id:
        try:
            ADMIN_IDS.append(int(raw_admin_id))
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS must be a comma-separated list of numeric Telegram IDs") from exc
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS must contain at least one Telegram ID")

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "").strip()

DB_PATH = "vpn_bot.db"
BACK = "🔙 منوی اصلی"
BACK_ADMIN = "🔙 پنل ادمین"

PRICE_PER_MONTH = 67000          # 💰 قیمت هر ماه
MONTHS = {"۱ ماهه 📅": 1, "۲ ماهه 📅": 2, "۳ ماهه 📅": 3}
COUNTRIES = [("🇩🇪 آلمان", "germany"), ("🇺🇸 آمریکا", "usa"),
             ("🇳🇱 هلند", "netherlands"), ("🇫🇷 فرانسه", "france")]
RENEW_DAYS = {"تمدید ۷ روزه 📅": 7, "تمدید ۱۵ روزه 📅": 15, "تمدید ۳۰ روزه 📅": 30}

def is_admin(tg_id):
    return tg_id in ADMIN_IDS

def fmt_price(n):
    return f"{int(n):,}"

def btn(text, style=None):
    try:
        if style:
            return KeyboardButton(text=text, style=style)
    except TypeError:
        pass
    return KeyboardButton(text=text)

def rkb(rows, placeholder=None):
    return ReplyKeyboardMarkup(
        keyboard=[[btn(t[0], t[1]) if isinstance(t, tuple) else btn(t) for t in row] for row in rows],
        resize_keyboard=True, is_persistent=True, input_field_placeholder=placeholder,
    )

def main_kb(is_admin_=False):
    rows = [
        [("خرید سرویس جدید 🛒", "primary"), ("سرویسهای من 📦", "success")],
        [("تمدید سرویس 🔄", "primary"), ("اکانت تست رایگان 🎁", "success")],
        [("کیف پول 👛", "success"), ("افزایش موجودی 💳", "primary")],
        [("تعرفه 💎", "primary"), ("چرخ شانس 🎡", "success")],
        [("کد تخفیف 🏷️", "success"), ("دعوت دوستان 👥", "primary")],
        [("آموزش اتصال 📖", "primary"), ("پشتیبانی SOS 📞", "danger")],
        [("حساب کاربری 👤", "primary"), ("درباره ربات ℹ️", "primary")],
    ]
    if is_admin_:
        rows.append([("⚙️ پنل ادمین", "primary")])
    return rkb(rows, placeholder="یک گزینه انتخاب کن...")

ADMIN_KB = rkb([
    [("📊 آمار", "primary"), ("📦 مدیریت پلنها", "success")],
    [("📋 سفارشات", "primary"), ("💳 تراکنشها", "success")],
    [("🏷️ مدیریت کد تخفیف", "success"), ("📣 ارسال همگانی", "primary")],
    [("👥 کاربران", "primary"), ("⚙️ تنظیمات", "success")],
    [("💾 پشتیبانگیری", "primary"), (BACK, "danger")],
])

def svc_btn(s):
    return f"🔑 {s['name'] or s['plan_name'] or 'سرویس'} — تا {s['expire_date'][:10]}"

def renew_btn(s):
    return f"🔄 {s['name'] or s['plan_name'] or 'سرویس'} — تا {s['expire_date'][:10]}"

# ---------------- دیتابیس ----------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT, full_name TEXT,
            balance REAL NOT NULL DEFAULT 0,
            referral_code TEXT UNIQUE, referred_by INTEGER,
            bonus_paid INTEGER NOT NULL DEFAULT 0,
            trial_used INTEGER NOT NULL DEFAULT 0,
            is_blocked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, description TEXT,
            days INTEGER NOT NULL, traffic_gb REAL NOT NULL,
            price REAL NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, plan_id INTEGER,
            price REAL NOT NULL, discount INTEGER NOT NULL DEFAULT 0,
            payment_method TEXT DEFAULT 'card', receipt TEXT,
            status TEXT DEFAULT 'pending',
            type TEXT DEFAULT 'purchase',
            renew_service_id INTEGER,
            days INTEGER,
            location TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            paid_at TEXT
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, plan_id INTEGER,
            name TEXT, config TEXT, expire_date TEXT,
            traffic_used REAL NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS wallet_txs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, amount REAL NOT NULL,
            type TEXT, status TEXT DEFAULT 'pending',
            receipt TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS discounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL, percent INTEGER NOT NULL,
            max_uses INTEGER NOT NULL DEFAULT 1,
            used_count INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        """)
        for alt in ("ALTER TABLE users ADD COLUMN trial_used INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE orders ADD COLUMN type TEXT DEFAULT 'purchase'",
                    "ALTER TABLE orders ADD COLUMN renew_service_id INTEGER",
                    "ALTER TABLE orders ADD COLUMN days INTEGER",
                    "ALTER TABLE orders ADD COLUMN location TEXT",
                    "ALTER TABLE services ADD COLUMN name TEXT"):
            try:
                await db.execute(alt)
            except Exception:
                pass
        await db.commit()

async def q(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

async def q1(sql, params=()):
    rows = await q(sql, params)
    return rows[0] if rows else None

async def exec(sql, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        await db.commit()
        return cur.lastrowid

async def ensure_user(tg_id, username, full_name):
    u = await q1("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
    if not u:
        await exec("INSERT INTO users (telegram_id, username, full_name, referral_code) VALUES (?,?,?,?)",
                   (tg_id, username, full_name, f"ref{tg_id}"))
        return await q1("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
    await exec("UPDATE users SET username=?, full_name=? WHERE telegram_id=?", (username, full_name, tg_id))
    return u

async def get_user(tg_id):
    return await q1("SELECT * FROM users WHERE telegram_id=?", (tg_id,))

async def get_all_users():
    return await q("SELECT telegram_id FROM users WHERE is_blocked=0")

async def count_users():
    return (await q1("SELECT COUNT(*) as c FROM users"))["c"]

async def add_balance(tg_id, amount):
    await exec("UPDATE users SET balance = balance + ? WHERE telegram_id=?", (amount, tg_id))

async def deduct_balance(tg_id, amount):
    await exec("UPDATE users SET balance = balance - ? WHERE telegram_id=?", (amount, tg_id))

async def apply_referral(tg_id, code):
    user = await get_user(tg_id)
    if not user or user["referred_by"] or not code or code == user["referral_code"]:
        return
    referrer = await q1("SELECT * FROM users WHERE referral_code=?", (code,))
    if referrer:
        await exec("UPDATE users SET referred_by=? WHERE telegram_id=?", (referrer["id"], tg_id))

async def apply_referral_bonus(tg_id, price):
    user = await get_user(tg_id)
    if not user or not user["referred_by"] or user["bonus_paid"]:
        return
    bonus = int(price * 10 / 100)
    if bonus > 0:
        rt = await q1("SELECT telegram_id FROM users WHERE id=?", (user["referred_by"],))
        if rt:
            await add_balance(rt["telegram_id"], bonus)
            await create_wallet_tx(rt["telegram_id"], bonus, "commission", "approved")
    await exec("UPDATE users SET bonus_paid=1 WHERE id=?", (user["id"],))

async def get_active_plans():
    return await q("SELECT * FROM plans WHERE is_active=1 ORDER BY price")

async def get_all_plans():
    return await q("SELECT * FROM plans ORDER BY price")

async def get_plan(pid):
    return await q1("SELECT * FROM plans WHERE id=?", (pid,))

async def create_plan(name, desc, days, traffic, price):
    return await exec("INSERT INTO plans (name, description, days, traffic_gb, price) VALUES (?,?,?,?,?)",
                      (name, desc, days, traffic, price))

async def toggle_plan(pid):
    await exec("UPDATE plans SET is_active = 1 - is_active WHERE id=?", (pid,))

async def delete_plan(pid):
    await exec("DELETE FROM plans WHERE id=?", (pid,))

async def create_order(user_id, plan_id, price, discount, method, receipt, type_="purchase",
                       renew_service_id=None, days=None, location=None):
    return await exec("INSERT INTO orders (user_id, plan_id, price, discount, payment_method, receipt, type, renew_service_id, days, location) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (user_id, plan_id, price, discount, method, receipt, type_, renew_service_id, days, location))

async def get_order(oid):
    return await q1("SELECT o.*, u.full_name, p.name as plan_name FROM orders o LEFT JOIN users u ON o.user_id=u.telegram_id LEFT JOIN plans p ON o.plan_id=p.id WHERE o.id=?", (oid,))

async def get_pending_orders():
    return await q("SELECT o.*, u.full_name, p.name as plan_name FROM orders o LEFT JOIN users u ON o.user_id=u.telegram_id LEFT JOIN plans p ON o.plan_id=p.id WHERE o.status='pending' ORDER BY o.id DESC")

async def approve_order(oid):
    await exec("UPDATE orders SET status='approved', paid_at=datetime('now','localtime') WHERE id=?", (oid,))

async def reject_order(oid):
    await exec("UPDATE orders SET status='rejected' WHERE id=?", (oid,))

async def order_stats():
    return await q1("SELECT COUNT(*) as cnt, COALESCE(SUM(price),0) as rev FROM orders WHERE status='approved'")

async def create_service(user_id, plan_id, config, expire_date, name=None):
    return await exec("INSERT INTO services (user_id, plan_id, config, expire_date, name) VALUES (?,?,?,?,?)",
                      (user_id, plan_id, config, expire_date, name))

async def get_user_services(tg_id):
    return await q("SELECT s.*, p.name as plan_name FROM services s LEFT JOIN plans p ON s.plan_id=p.id WHERE s.user_id=? AND s.is_active=1 ORDER BY s.id DESC", (tg_id,))

async def get_service(sid):
    return await q1("SELECT s.*, p.name as plan_name FROM services s LEFT JOIN plans p ON s.plan_id=p.id WHERE s.id=?", (sid,))

async def extend_service(sid, days):
    svc = await get_service(sid)
    if not svc:
        return None
    try:
        base = datetime.strptime(svc["expire_date"], "%Y-%m-%d %H:%M")
    except Exception:
        base = datetime.now()
    new_exp = (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    await exec("UPDATE services SET expire_date=? WHERE id=?", (new_exp, sid))
    return new_exp

async def count_active_services():
    return (await q1("SELECT COUNT(*) as c FROM services WHERE is_active=1 AND expire_date > datetime('now','localtime')"))["c"]

async def create_wallet_tx(user_id, amount, type_, status, receipt=None):
    return await exec("INSERT INTO wallet_txs (user_id, amount, type, status, receipt) VALUES (?,?,?,?,?)",
                      (user_id, amount, type_, status, receipt))

async def get_wallet_tx(txid):
    return await q1("SELECT * FROM wallet_txs WHERE id=?", (txid,))

async def get_pending_wallet_txs():
    return await q("SELECT w.*, u.full_name FROM wallet_txs w LEFT JOIN users u ON w.user_id=u.telegram_id WHERE w.status='pending' ORDER BY w.id DESC")

async def approve_wallet_tx(txid):
    await exec("UPDATE wallet_txs SET status='approved' WHERE id=?", (txid,))

async def reject_wallet_tx(txid):
    await exec("UPDATE wallet_txs SET status='rejected' WHERE id=?", (txid,))

async def get_discount(code):
    return await q1("SELECT * FROM discounts WHERE code=?", (code,))

async def get_codes():
    return await q("SELECT * FROM discounts ORDER BY id DESC")

async def create_code(code, percent, max_uses):
    return await exec("INSERT INTO discounts (code, percent, max_uses) VALUES (?,?,?)", (code, percent, max_uses))

async def increment_code(cid):
    await exec("UPDATE discounts SET used_count = used_count + 1 WHERE id=?", (cid,))

async def set_setting(key, value):
    await exec("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

async def get_setting(key):
    r = await q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else None

# ---------------- تحویل سرویس ----------------
async def make_config(user_id, plan, location=None):
    # 🔌 اینجا بعداً به پنل مرزبان وصل میشه
    host = (location or plan["name"]).replace(" ", "").lower()
    return f"vless://{uuid.uuid4().hex}@{host}.example.com:443?security=tls&type=ws#VPN-{user_id}"

async def finalize_order(user_id, order_id, plan, price, method, days=None, location=None):
    await approve_order(order_id)
    config = await make_config(user_id, plan, location)
    dur = days or plan["days"]
    expire = (datetime.now() + timedelta(days=dur)).strftime("%Y-%m-%d %H:%M")
    name = f"{location} | {dur} روزه" if location else plan["name"]
    svc_id = await create_service(user_id, plan["id"], config, expire, name)
    if method == "wallet":
        await deduct_balance(user_id, price)
        await create_wallet_tx(user_id, -price, "spend", "approved")
    await apply_referral_bonus(user_id, price)
    return svc_id

# ---------------- میدلور ----------------
class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and user.id:
            row = await ensure_user(user.id, user.username, user.full_name)
            if row and row["is_blocked"]:
                return None
        return await handler(event, data)

# ---------------- روت اصلی ----------------
router = Router()

class UserStates(StatesGroup):
    wait_receipt = State()
    wait_discount_code = State()
    wait_charge_amount = State()
    wait_charge_receipt = State()
    wait_renew_receipt = State()
    wait_support = State()

class AdminStates(StatesGroup):
    plan_name = State()
    plan_desc = State()
    plan_days = State()
    plan_traffic = State()
    plan_price = State()
    add_code = State()
    add_code_percent = State()
    add_code_uses = State()
    broadcast = State()
    lookup_user = State()
    charge_amount = State()
    set_card = State()
    set_support = State()
    order_id = State()
    tx_id = State()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        await apply_referral(message.from_user.id, args[1])
    await message.answer(f"سلام {message.from_user.full_name} عزیز! 🌟\nبه ربات فروش VPN خوش اومدی 🚀\nاز منوی پایین انتخاب کن 👇",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("منوی اصلی 👇", reply_markup=main_kb(is_admin(message.from_user.id)))

@router.message(F.text == BACK)
async def back_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("منوی اصلی 👇", reply_markup=main_kb(is_admin(message.from_user.id)))

@router.message(F.text == BACK_ADMIN)
async def back_admin(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ دسترسی نداری!", reply_markup=main_kb(False))
        return
    await message.answer("⚙️ پنل مدیریت 👇", reply_markup=ADMIN_KB)

# ---------- خرید (۱/۲/۳ ماه → ۴ لوکیشن) ----------
PAY_KB = rkb([
    [("💳 پرداخت کارت به کارت", "primary")],
    [("👛 پرداخت با کیف پول", "success")],
    [("🏷️ کد تخفیف", "success"), (BACK, "danger")],
])

@router.message(F.text == "خرید سرویس جدید 🛒")
async def buy_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛒 <b>چند ماهه میخوای؟</b> 👇\n📊 حجم: ♾️ نامحدود در همه پلنها",
                         reply_markup=rkb([
                             [("۱ ماهه 📅", "success"), ("۲ ماهه 📅", "success")],
                             [("۳ ماهه 📅", "primary")],
                             [(BACK, "danger")],
                         ]))

@router.message(F.text.in_(MONTHS.keys()))
async def buy_months(message: Message, state: FSMContext):
    months = MONTHS[message.text]
    price = PRICE_PER_MONTH * months
    await state.update_data(months=months)
    rows = [[(f"{flag} {name}", "primary")] for flag, name in COUNTRIES]
    rows.append([(BACK, "danger")])
    await message.answer(f"📅 مدت: <b>{months} ماهه</b> | 💰 قیمت: <b>{fmt_price(price)} تومان</b>\n"
                         f"📊 حجم: ♾️ نامحدود\n━━━━━━━━━━━━━━━\n🌍 <b>لوکیشن مورد نظرت رو انتخاب کن:</b>",
                         reply_markup=rkb(rows))

@router.message(F.text.in_({f"{flag} {name}" for flag, name in COUNTRIES}))
async def buy_country(message: Message, state: FSMContext):
    data = await state.get_data()
    months = data.get("months")
    if not months:
        await message.answer("اول تعداد ماه رو انتخاب کن 👇", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    loc_label = message.text
    loc_slug = dict((f"{f} {n}", s) for f, n, s in [(f, n, s) for f, n in COUNTRIES for s in [n]])[loc_label]
    price = PRICE_PER_MONTH * months
    discount = data.get("discount", 0)
    final_price = int(price * (100 - discount) / 100)
    await state.update_data(location=loc_label, loc_slug=loc_slug)
    await message.answer(f"🌍 <b>لوکیشن: {loc_label}</b>\n📅 مدت: <b>{months} ماهه</b>\n"
                         f"📊 حجم: <b>♾️ نامحدود</b>\n"
                         f"{'🏷️ تخفیف: ' + str(discount) + '٪' if discount else ''}\n"
                         f"💰 قیمت: <b>{fmt_price(final_price)} تومان</b>\n━━━━━━━━━━━━━━━\nروش پرداخت رو انتخاب کن 👇",
                         reply_markup=PAY_KB)

# ---------- پرداخت ----------
@router.message(F.text == "💳 پرداخت کارت به کارت")
async def pay_card(message: Message, state: FSMContext):
    data = await state.get_data()
    months = data.get("months")
    if not months:
        await message.answer("اول یک سرویس انتخاب کن 👇", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    discount = data.get("discount", 0)
    price = int(PRICE_PER_MONTH * months * (100 - discount) / 100)
    await state.set_state(UserStates.wait_receipt)
    await state.update_data(months=months, discount=discount)
    await message.answer(
        f"💳 <b>پرداخت کارت به کارت</b>\n💰 مبلغ: <b>{fmt_price(price)} تومان</b>\n"
        f"{'🏷️ تخفیف: ' + str(discount) + '٪' if discount else ''}\n━━━━━━━━━━━━━━━\n"
        f"🟡 شماره کارت: <code>{CARD_NUMBER}</code>\n👤 به نام: <b>{CARD_HOLDER}</b>\n━━━━━━━━━━━━━━━\n"
        f"📸 بعد از واریز، عکس فیش یا کد پیگیری رو بفرست 👇",
        reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_receipt)
async def receive_receipt(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    data = await state.get_data()
    months = data.get("months")
    discount = data.get("discount", 0)
    price = int(PRICE_PER_MONTH * months * (100 - discount) / 100)
    location = data.get("location", "")
    receipt = message.text or message.caption or "📎 فایل"
    oid = await create_order(message.from_user.id, None, price, discount, "card", receipt,
                             days=months * 30, location=location)
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_message(admin,
                f"🆕 <b>سفارش خرید #{oid}</b>\n👤 کاربر: {message.from_user.full_name} (id: <code>{message.from_user.id}</code>)\n"
                f"🌍 لوکیشن: {location}\n📅 مدت: {months} ماهه\n💰 مبلغ: {fmt_price(price)} تومان\n🧾 رسید: {receipt}")
        except Exception:
            pass
    await message.answer("✅ سفارشت ثبت شد!\nبعد از تایید ادمین، سرویست فعال و کانفیگ برات ارسال میشه 📩",
                         reply_markup=main_kb(is_admin(message.from_user.id)))
    await state.clear()

@router.message(F.text == "👛 پرداخت با کیف پول")
async def pay_wallet(message: Message, state: FSMContext):
    data = await state.get_data()
    months = data.get("months")
    if not months:
        await message.answer("اول یک سرویس انتخاب کن 👇", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    discount = data.get("discount", 0)
    price = int(PRICE_PER_MONTH * months * (100 - discount) / 100)
    user = await get_user(message.from_user.id)
    if user["balance"] < price:
        await message.answer("❌ موجودی کیف پول کافی نیست! از «افزایش موجودی 💳» شارژ کن",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    location = data.get("location", "")
    days = months * 30
    plan = {"id": 0, "name": f"{location} | {months} ماهه", "days": days, "traffic_gb": 0, "price": price}
    oid = await create_order(message.from_user.id, None, price, discount, "wallet", "—",
                             days=days, location=location)
    svc_id = await finalize_order(message.from_user.id, oid, plan, price, "wallet", days=days, location=location)
    svc = await get_service(svc_id)
    await message.answer(f"✅ پرداخت با موفقیت انجام شد! 🎉\n🎉 سرویس <b>{svc['name']}</b> فعال شد!\n📅 انقضا: {svc['expire_date']}\n\n🔑 <b>کانفیگ شما:</b>\n<code>{svc['config']}</code>",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- کد تخفیف ----------
@router.message(F.text == "🏷️ کد تخفیف")
async def discount_start(message: Message, state: FSMContext):
    await state.set_state(UserStates.wait_discount_code)
    await message.answer("🏷️ کد تخفیف رو وارد کن:", reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_discount_code)
async def discount_apply(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    code = (message.text or "").strip().upper()
    dc = await get_discount(code)
    if not dc or not dc["is_active"] or dc["used_count"] >= dc["max_uses"]:
        await message.answer("❌ کد تخفیف نامعتبر یا مصرفشده!", reply_markup=rkb([[(BACK, "danger")]]))
        return
    await increment_code(dc["id"])
    await state.update_data(discount=dc["percent"])
    data = await state.get_data()
    if data.get("months"):
        new_price = int(PRICE_PER_MONTH * data["months"] * (100 - dc["percent"]) / 100)
        await message.answer(f"✅ کد <b>{code}</b> با {dc['percent']}٪ تخفیف اعمال شد!\n💰 قیمت جدید: <b>{fmt_price(new_price)} تومان</b>",
                             reply_markup=PAY_KB)
    else:
        await message.answer(f"✅ کد <b>{code}</b> با {dc['percent']}٪ تخفیف اعمال شد!\nحالا برو سراغ «خرید سرویس جدید 🛒» 🚀",
                             reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- سرویسها ----------
@router.message(F.text == "سرویسهای من 📦")
async def my_services(message: Message, state: FSMContext):
    await state.clear()
    svcs = await get_user_services(message.from_user.id)
    if not svcs:
        await message.answer("هنوز سرویسی نداری 😔\nاز بخش «خرید سرویس جدید 🛒» یه سرویس بگیر!", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    rows = [[(svc_btn(s), "success")] for s in svcs]
    rows.append([("تمدید سرویس 🔄", "primary"), (BACK, "danger")])
    await message.answer("📦 <b>سرویسهای فعال تو:</b>\nبرای دیدن کانفیگ، روش بزن 👇", reply_markup=rkb(rows))

@router.message(F.text.startswith("🔑 "))
async def service_selected(message: Message):
    svcs = await get_user_services(message.from_user.id)
    for s in svcs:
        if message.text == svc_btn(s):
            await message.answer(f"🔑 <b>کانفیگ {s['name'] or s['plan_name'] or ''}</b>\n📅 انقضا: {s['expire_date']}\n\n<code>{s['config']}</code>")
            return

# ---------- تمدید سرویس ----------
@router.message(F.text == "تمدید سرویس 🔄")
async def renew_menu(message: Message, state: FSMContext):
    await state.clear()
    svcs = await get_user_services(message.from_user.id)
    if not svcs:
        await message.answer("اول باید سرویس داشته باشی! از «خرید سرویس جدید 🛒» شروع کن 😊",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    rows = [[(renew_btn(s), "primary")] for s in svcs]
    rows.append([(BACK, "danger")])
    await message.answer("🔄 <b>تمدید سرویس</b>\nروی سرویسی که میخوای تمدید کنی بزن 👇", reply_markup=rkb(rows))

@router.message(F.text.startswith("🔄 "))
async def renew_service_selected(message: Message, state: FSMContext):
    svcs = await get_user_services(message.from_user.id)
    for s in svcs:
        if message.text == renew_btn(s):
            await state.update_data(renew_svc_id=s["id"])
            await message.answer(f"🔄 تمدید <b>{s['name'] or s['plan_name'] or 'سرویس'}</b> (انقضا: {s['expire_date']})\nمدت تمدید رو انتخاب کن 👇",
                                 reply_markup=rkb([
                                     [("تمدید ۷ روزه 📅", "success")],
                                     [("تمدید ۱۵ روزه 📅", "success")],
                                     [("تمدید ۳۰ روزه 📅", "primary")],
                                     [(BACK, "danger")],
                                 ]))
            return

@router.message(F.text.in_(RENEW_DAYS.keys()))
async def renew_duration(message: Message, state: FSMContext):
    days = RENEW_DAYS[message.text]
    data = await state.get_data()
    if not data.get("renew_svc_id"):
        await message.answer("اول یک سرویس برای تمدید انتخاب کن", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    price = int(PRICE_PER_MONTH * days / 30)
    await state.update_data(renew_days=days, renew_price=price)
    await message.answer(f"🔄 تمدید <b>{days} روزه</b> سرویس\n💰 مبلغ: <b>{fmt_price(price)} تومان</b>\nروش پرداخت رو انتخاب کن 👇",
                         reply_markup=rkb([
                             [("💳 تمدید با کارت", "primary")],
                             [("👛 تمدید با کیف پول", "success")],
                             [(BACK, "danger")],
                         ]))

@router.message(F.text == "💳 تمدید با کارت")
async def renew_card(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("renew_svc_id"):
        await message.answer("اول یک سرویس برای تمدید انتخاب کن", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    await state.set_state(UserStates.wait_renew_receipt)
    await message.answer(
        f"💳 <b>پرداخت تمدید</b>\n💰 مبلغ: <b>{fmt_price(data['renew_price'])} تومان</b>\n━━━━━━━━━━━━━━━\n"
        f"🟡 شماره کارت: <code>{CARD_NUMBER}</code>\n👤 به نام: <b>{CARD_HOLDER}</b>\n━━━━━━━━━━━━━━━\n"
        f"📸 بعد از واریز، عکس فیش یا کد پیگیری رو بفرست 👇",
        reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_renew_receipt)
async def renew_receipt(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    data = await state.get_data()
    receipt = message.text or message.caption or "📎 فایل"
    oid = await create_order(message.from_user.id, None, data["renew_price"], 0, "card", receipt,
                             type_="renew", renew_service_id=data.get("renew_svc_id"), days=data["renew_days"])
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_message(admin,
                f"🔄 <b>درخواست تمدید #{oid}</b>\n👤 کاربر: {message.from_user.full_name} (id: <code>{message.from_user.id}</code>)\n"
                f"⏳ تمدید: {data['renew_days']} روزه\n💰 مبلغ: {fmt_price(data['renew_price'])} تومان\n🧾 رسید: {receipt}")
        except Exception:
            pass
    await message.answer("✅ درخواست تمدید ثبت شد!\nبعد از تایید ادمین، سرویست تمدید میشه 📩",
                         reply_markup=main_kb(is_admin(message.from_user.id)))
    await state.clear()

@router.message(F.text == "👛 تمدید با کیف پول")
async def renew_wallet(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("renew_svc_id"):
        await message.answer("اول یک سرویس برای تمدید انتخاب کن", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    user = await get_user(message.from_user.id)
    if user["balance"] < data["renew_price"]:
        await message.answer("❌ موجودی کیف پول کافی نیست! از «افزایش موجودی 💳» شارژ کن",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    oid = await create_order(message.from_user.id, None, data["renew_price"], 0, "wallet", "—",
                             type_="renew", renew_service_id=data.get("renew_svc_id"), days=data["renew_days"])
    await approve_order(oid)
    new_exp = await extend_service(data["renew_svc_id"], data["renew_days"])
    await deduct_balance(message.from_user.id, data["renew_price"])
    await create_wallet_tx(message.from_user.id, -data["renew_price"], "spend", "approved")
    await message.answer(f"✅ سرویست تمدید شد! 🎉\n📅 انقضای جدید: <b>{new_exp}</b>",
                         reply_markup=main_kb(is_admin(message.from_user.id)))
    await state.clear()

# ---------- تعرفه ----------
@router.message(F.text == "تعرفه 💎")
async def tariff_menu(message: Message, state: FSMContext):
    await state.clear()
    text = ("💎 <b>تعرفه سرویسها</b>\n━━━━━━━━━━━━━━━\n"
            f"📅 ۱ ماهه — <b>{fmt_price(PRICE_PER_MONTH)} تومان</b>\n"
            f"📅 ۲ ماهه — <b>{fmt_price(PRICE_PER_MONTH * 2)} تومان</b>\n"
            f"📅 ۳ ماهه — <b>{fmt_price(PRICE_PER_MONTH * 3)} تومان</b>\n"
            f"━━━━━━━━━━━━━━━\n📊 حجم: ♾️ <b>نامحدود</b> در همه پلنها\n"
            f"🌍 لوکیشنها: 🇩🇪 آلمان | 🇺🇸 آمریکا | 🇳🇱 هلند | 🇫🇷 فرانسه\n"
            f"⚡ پشتیبانی ۲۴/۷ | 🚀 سرعت بالا\n\nبرای خرید از «خرید سرویس جدید 🛒» استفاده کن 👇")
    await message.answer(text, reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- کیف پول ----------
@router.message(F.text == "کیف پول 👛")
async def wallet_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    await message.answer(f"👛 <b>کیف پول</b>\n💰 موجودی: <b>{fmt_price(user['balance'])} تومان</b>\n\nبا شارژ کیف پول، خرید سریعتر انجام میدی 🚀",
                         reply_markup=rkb([
                             [("افزایش موجودی 💳", "success")],
                             [(BACK, "danger")],
                         ]))

@router.message(F.text == "افزایش موجودی 💳")
async def charge_start(message: Message, state: FSMContext):
    await state.set_state(UserStates.wait_charge_amount)
    await message.answer("💰 مبلغ شارژ رو به <b>تومان</b> بنویس:", reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_charge_amount)
async def charge_amount(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    try:
        amount = int((message.text or "").replace(",", "").replace("تومان", "").strip())
    except ValueError:
        await message.answer("❌ لطفاً عدد صحیح بنویس (مثلاً 50000):")
        return
    if amount < 1000:
        await message.answer("❌ حداقل مبلغ شارژ ۱۰۰۰ تومانه:")
        return
    await state.update_data(charge_amount=amount)
    await state.set_state(UserStates.wait_charge_receipt)
    await message.answer(f"💳 مبلغ <b>{fmt_price(amount)} تومان</b> رو به کارت زیر واریز کن:\n\n🟡 <code>{CARD_NUMBER}</code>\n👤 {CARD_HOLDER}\n\n📸 بعدش عکس فیش یا کد پیگیری رو بفرست:",
                         reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_charge_receipt)
async def charge_receipt(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    data = await state.get_data()
    amount = data.get("charge_amount", 0)
    receipt = message.text or message.caption or "📎 فایل"
    txid = await create_wallet_tx(message.from_user.id, amount, "charge", "pending", receipt)
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_message(admin,
                f"💳 <b>درخواست شارژ کیف پول #{txid}</b>\n👤 کاربر: {message.from_user.full_name} (id: <code>{message.from_user.id}</code>)\n"
                f"💰 مبلغ: {fmt_price(amount)} تومان\n🧾 رسید: {receipt}")
        except Exception:
            pass
    await message.answer("✅ درخواست شارژ ثبت شد!\nبعد از تایید ادمین، موجودیت شارژ میشه 🕐",
                         reply_markup=main_kb(is_admin(message.from_user.id)))
    await state.clear()

# ---------- تست رایگان ----------
@router.message(F.text == "اکانت تست رایگان 🎁")
async def free_trial(message: Message):
    user = await get_user(message.from_user.id)
    if user["trial_used"]:
        await message.answer("❌ تو قبلاً تست رایگان گرفتی!\nبرای سرویس بیشتر از «خرید سرویس جدید 🛒» استفاده کن 😊",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    await exec("UPDATE users SET trial_used=1 WHERE telegram_id=?", (message.from_user.id,))
    plan = {"name": "Test", "days": 3}
    config = await make_config(message.from_user.id, plan)
    expire = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
    await create_service(message.from_user.id, 0, config, expire, "تست رایگان ۳ روزه 🎁")
    await message.answer(f"🎁 <b>اکانت تست رایگان (۳ روزه)</b> فعال شد! 🎉\n📅 انقضا: {expire}\n\n🔑 <b>کانفیگت:</b>\n<code>{config}</code>",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- چرخ شانس ----------
@router.message(F.text == "چرخ شانس 🎡")
async def spin_wheel(message: Message):
    user = await get_user(message.from_user.id)
    key = f"spin_{user['telegram_id']}"
    last = await get_setting(key)
    today = date.today().isoformat()
    if last == today:
        await message.answer("🎡 امروز دیگه چرخیدی! فردا دوباره بیا 😉", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    await set_setting(key, today)
    amount = random.choice([0, 10000, 20000, 50000])
    if amount:
        await add_balance(message.from_user.id, amount)
        await create_wallet_tx(message.from_user.id, amount, "bonus", "approved")
        await message.answer(f"🎉🎡 <b>چرخ شانس چرخید...</b>\n💰 برنده شدی: <b>{fmt_price(amount)} تومان</b>\nبه کیف پولت اضافه شد! 🚀",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
    else:
        await message.answer("😅 افسوس... این بار چیزی نبردی!\nفردا دوباره تلاش کن 🎯",
                             reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- دعوت دوستان ----------
@router.message(F.text == "دعوت دوستان 👥")
async def referral_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    bot_me = await message.bot.get_me()
    link = f"https://t.me/{bot_me.username}?start=ref{user['referral_code']}"
    await message.answer(f"🎁 <b>دعوت دوستان</b>\n\nلینک اختصاصی تو 👇\n<code>{link}</code>\n\n"
                         f"به ازای <b>اولین خرید</b> هر کسی که با لینک تو اومد، <b>۱۰٪ مبلغ خرید</b> به کیف پولت اضافه میشه 💰\n"
                         f"هرچی بیشتر دعوت کنی، بیشتر پول درمیاری! 🚀",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- آموزش اتصال ----------
@router.message(F.text == "آموزش اتصال 📖")
async def guide(message: Message, state: FSMContext):
    await state.clear()
    text = ("📖 <b>آموزش اتصال</b>\n\n"
            "1️⃣ اپ <b>v2rayNG</b> (اندروید) یا <b>Streisand</b> رو نصب کن.\n"
            "2️⃣ وارد بخش کانفیگ شو و گزینه «افزودن از کلیپبورد» رو بزن.\n"
            "3️⃣ لینک کانفیگت رو از «سرویسهای من 📦» کپی کن.\n"
            "4️⃣ ذخیره کن و وصل شو! 🚀\n\n"
            "📱 آیفون: اپ <b>Streisand</b> یا <b>V2Box</b> از اپاستور.\n"
            "💻 ویندوز: اپ <b>v2rayN</b>.")
    await message.answer(text, reply_markup=main_kb(is_admin(message.from_user.id)))

# ---------- پروفایل / درباره / پشتیبانی ----------
@router.message(F.text == "حساب کاربری 👤")
async def profile(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    svc_count = len(await get_user_services(message.from_user.id))
    await message.answer(f"👤 <b>پروفایل</b>\n━━━━━━━━━━━━━━━\n"
                         f"🆔 آیدی: <code>{user['telegram_id']}</code>\n📛 نام: {user['full_name'] or '—'}\n"
                         f"📅 تاریخ عضویت: {user['created_at'][:10]}\n💰 موجودی: {fmt_price(user['balance'])} تومان\n"
                         f"📦 سرویسهای فعال: {svc_count}\n🎁 کد معرف: <code>{user['referral_code']}</code>",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

@router.message(F.text == "درباره ربات ℹ️")
async def about(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("ℹ️ <b>درباره ربات</b>\n\n"
                         "🚀 ربات فروش VPN | نسخه ۳.۰ (فول اپشن)\n"
                         "✅ خرید و تمدید خودکار سرویس\n"
                         "✅ حجم نامحدود ♾️ در ۴ لوکیشن برتر دنیا\n"
                         "✅ کیف پول و شارژ آنلاین\n"
                         "✅ کد تخفیف و سیستم معرف\n"
                         "✅ تست رایگان و چرخ شانس\n"
                         "📞 پشتیبانی ۲۴/۷",
                         reply_markup=main_kb(is_admin(message.from_user.id)))

@router.message(F.text == "پشتیبانی SOS 📞")
async def support_start(message: Message, state: FSMContext):
    if SUPPORT_USERNAME:
        await message.answer(f"📞 برای پشتیبانی به <b>@{SUPPORT_USERNAME}</b> پیام بده 😊",
                             reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    await state.set_state(UserStates.wait_support)
    await message.answer("✍️ پیامت رو بنویس تا مستقیم به پشتیبانی ارسال بشه 👇", reply_markup=rkb([[(BACK, "danger")]]))

@router.message(UserStates.wait_support)
async def support_msg(message: Message, state: FSMContext):
    if message.text == BACK:
        await state.clear()
        await message.answer("لغو شد ❌", reply_markup=main_kb(is_admin(message.from_user.id)))
        return
    for admin in ADMIN_IDS:
        try:
            await message.forward(admin)
            await message.bot.send_message(admin, f"📩 پیام پشتیبانی از {message.from_user.full_name} (id: <code>{message.from_user.id}</code>)")
        except Exception:
            pass
    await message.answer("✅ پیامت ارسال شد! به زودی جواب میگیری 😊", reply_markup=main_kb(is_admin(message.from_user.id)))
    await state.clear()

# ================= پنل ادمین =================
@router.message(F.text == "⚙️ پنل ادمین")
async def admin_menu(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ دسترسی نداری!", reply_markup=main_kb(False))
        return
    await message.answer("⚙️ <b>پنل مدیریت</b>\nیکی از گزینهها رو انتخاب کن 👇", reply_markup=ADMIN_KB)

@router.message(F.text == "📊 آمار")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users = await count_users()
    ostats = await order_stats()
    svcs = await count_active_services()
    await message.answer(f"📊 <b>آمار ربات</b>\n━━━━━━━━━━━━━━━\n"
                         f"👥 کاربران: <b>{users}</b>\n🛒 سفارشهای موفق: <b>{ostats['cnt']}</b>\n"
                         f"💰 مجموع فروش: <b>{int(ostats['rev']):,} تومان</b>\n📦 سرویسهای فعال: <b>{svcs}</b>",
                         reply_markup=ADMIN_KB)

# ---------- مدیریت پلنها (برای استفادههای بعدی) ----------
@router.message(F.text == "📦 مدیریت پلنها")
async def admin_plans(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    plans = await get_all_plans()
    rows = [[(f"🛠 {p['name']} {'✅' if p['is_active'] else '⛔️'}", "primary")] for p in plans]
    rows.append([("➕ افزودن پلن", "success")])
    rows.append([(BACK_ADMIN, "danger")])
    await message.answer("📦 <b>پلنها:</b> (✅ فعال | ⛔️ غیرفعال)\nروی هر پلن بزن:", reply_markup=rkb(rows))

@router.message(F.text.startswith("🛠 "))
async def admin_plan_selected(message: Message, state: FSMContext):
    plans = await get_all_plans()
    for p in plans:
        if message.text == f"🛠 {p['name']} {'✅' if p['is_active'] else '⛔️'}":
            await state.update_data(admin_plan_id=p["id"])
            await message.answer(f"📦 <b>{p['name']}</b>\n📄 {p['description'] or '—'}\n"
                                 f"⏳ {p['days']} روز | 📊 {int(p['traffic_gb'])} گیگ | 💰 {int(p['price']):,} تومان\n"
                                 f"وضعیت: {'✅ فعال' if p['is_active'] else '⛔️ غیرفعال'}",
                                 reply_markup=rkb([
                                     [("🔄 فعال/غیرفعال", "success"), ("🗑 حذف پلن", "danger")],
                                     [(BACK_ADMIN, "danger")],
                                 ]))
            return

@router.message(F.text == "🔄 فعال/غیرفعال")
async def toggle_plan_cb(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    pid = data.get("admin_plan_id")
    if not pid:
        await message.answer("اول یک پلن انتخاب کن", reply_markup=ADMIN_KB)
        return
    await toggle_plan(pid)
    plan = await get_plan(pid)
    await message.answer(f"✅ پلن «{plan['name']}» حالا {'فعال' if plan['is_active'] else 'غیرفعال'} است", reply_markup=ADMIN_KB)
    await state.clear()

@router.message(F.text == "🗑 حذف پلن")
async def delete_plan_cb(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    pid = data.get("admin_plan_id")
    if not pid:
        await message.answer("اول یک پلن انتخاب کن", reply_markup=ADMIN_KB)
        return
    plan = await get_plan(pid)
    await delete_plan(pid)
    await message.answer(f"🗑 پلن «{plan['name']}» حذف شد.", reply_markup=ADMIN_KB)
    await state.clear()

@router.message(F.text == "➕ افزودن پلن")
async def add_plan_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.plan_name)
    await message.answer("📝 اسم پلن رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.plan_name)
async def add_plan_name(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    await state.update_data(name=message.text)
    await state.set_state(AdminStates.plan_desc)
    await message.answer("📄 توضیحات پلن (اگه نمیخوای، «-» بنویس):")

@router.message(AdminStates.plan_desc)
async def add_plan_desc(message: Message, state: FSMContext):
    await state.update_data(desc=message.text if message.text != "-" else "")
    await state.set_state(AdminStates.plan_days)
    await message.answer("⏳ مدت زمان به روز (مثلاً 30):")

@router.message(AdminStates.plan_days)
async def add_plan_days(message: Message, state: FSMContext):
    try:
        days = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ عدد صحیح وارد کن:")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.plan_traffic)
    await message.answer("📊 حجم ترافیک به گیگابایت (مثلاً 50):")

@router.message(AdminStates.plan_traffic)
async def add_plan_traffic(message: Message, state: FSMContext):
    try:
        traffic = float(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ عدد وارد کن:")
        return
    await state.update_data(traffic=traffic)
    await state.set_state(AdminStates.plan_price)
    await message.answer("💰 قیمت به تومان (مثلاً 150000):")

@router.message(AdminStates.plan_price)
async def add_plan_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.replace(",", "").strip())
    except (ValueError, AttributeError):
        await message.answer("❌ عدد وارد کن:")
        return
    data = await state.get_data()
    await create_plan(data["name"], data["desc"], data["days"], data["traffic"], price)
    await state.clear()
    await message.answer("✅ پلن اضافه شد!", reply_markup=ADMIN_KB)

# ---------- سفارشات ----------
@router.message(F.text == "📋 سفارشات")
async def admin_orders(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    orders = await get_pending_orders()
    if not orders:
        await message.answer("سفارش در انتظاری نیست ✅", reply_markup=ADMIN_KB)
        return
    for o in orders[:10]:
        typ = "🔄 تمدید" if o["type"] == "renew" else "🛒 خرید"
        item = f"{o['location'] or o['plan_name'] or '—'} | {o['days'] or '—'} روزه"
        await message.answer(f"{typ} <b>#{o['id']}</b>\n👤 {o['full_name'] or '—'} (id: <code>{o['user_id']}</code>)\n"
                             f"📦 {item}\n💰 {int(o['price']):,} تومان\n💳 روش: {o['payment_method']}\n"
                             f"🧾 رسید: {o['receipt']}\n🗓 {o['created_at']}")
    await message.answer("برای تایید یا رد، دکمه رو بزن و شماره سفارش رو بفرست 👇",
                         reply_markup=rkb([
                             [("✅ تایید سفارش", "success"), ("❌ رد سفارش", "danger")],
                             [(BACK_ADMIN, "danger")],
                         ]))

@router.message(F.text == "✅ تایید سفارش")
async def order_approve_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(order_action="approve")
    await state.set_state(AdminStates.order_id)
    await message.answer("🔢 شماره سفارش رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(F.text == "❌ رد سفارش")
async def order_reject_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(order_action="reject")
    await state.set_state(AdminStates.order_id)
    await message.answer("🔢 شماره سفارش رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.order_id)
async def order_action(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    try:
        oid = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ شماره سفارش عددی وارد کن:")
        return
    data = await state.get_data()
    order = await get_order(oid)
    if not order or order["status"] != "pending":
        await message.answer("❌ این سفارش وجود نداره یا قبلاً پردازش شده!")
        return
    if data.get("order_action") == "approve":
        if order["type"] == "renew":
            new_exp = await extend_service(order["renew_service_id"], order["days"] or 30)
            await approve_order(oid)
            try:
                await message.bot.send_message(order["user_id"], f"✅ تمدید سفارش <b>#{oid}</b> تایید شد!\n📅 انقضای جدید: <b>{new_exp}</b> 🎉")
            except Exception:
                pass
            await message.answer(f"✅ تمدید #{oid} تایید شد. انقضای جدید: {new_exp}", reply_markup=ADMIN_KB)
        else:
            if order["days"]:
                plan = {"id": 0, "name": f"{order['location'] or 'VPN'} | {order['days']} روزه",
                        "days": order["days"], "traffic_gb": 0, "price": order["price"]}
            else:
                plan = await get_plan(order["plan_id"])
            svc_id = await finalize_order(order["user_id"], oid, plan, order["price"], order["payment_method"],
                                          days=order["days"], location=order["location"])
            svc = await get_service(svc_id)
            try:
                await message.bot.send_message(order["user_id"], f"✅ سفارش <b>#{oid}</b> تایید شد!\n🎉 سرویس «{svc['name']}» فعاله\n📅 انقضا: {svc['expire_date']}\n🔑 کانفیگت 👇")
                await message.bot.send_message(order["user_id"], f"<code>{svc['config']}</code>")
            except Exception:
                pass
            await message.answer(f"✅ سفارش #{oid} تایید و سرویس صادر شد.", reply_markup=ADMIN_KB)
    else:
        await reject_order(oid)
        try:
            await message.bot.send_message(order["user_id"], f"❌ سفارش <b>#{oid}</b> رد شد.\nاگه سوالی داری به پشتیبانی پیام بده.")
        except Exception:
            pass
        await message.answer(f"❌ سفارش #{oid} رد شد.", reply_markup=ADMIN_KB)
    await state.clear()

# ---------- تراکنشها ----------
@router.message(F.text == "💳 تراکنشها")
async def admin_wallet(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    txs = await get_pending_wallet_txs()
    if not txs:
        await message.answer("درخواست شارژی نیست ✅", reply_markup=ADMIN_KB)
        return
    for t in txs[:10]:
        await message.answer(f"💳 <b>شارژ #{t['id']}</b>\n👤 {t['full_name'] or '—'} (id: <code>{t['user_id']}</code>)\n"
                             f"💰 {int(t['amount']):,} تومان\n🧾 رسید: {t['receipt']}")
    await message.answer("برای تایید یا رد، دکمه رو بزن و شماره تراکنش رو بفرست 👇",
                         reply_markup=rkb([
                             [("✅ تایید تراکنش", "success"), ("❌ رد تراکنش", "danger")],
                             [(BACK_ADMIN, "danger")],
                         ]))

@router.message(F.text == "✅ تایید تراکنش")
async def wallet_approve_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(tx_action="approve")
    await state.set_state(AdminStates.tx_id)
    await message.answer("🔢 شماره تراکنش رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(F.text == "❌ رد تراکنش")
async def wallet_reject_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(tx_action="reject")
    await state.set_state(AdminStates.tx_id)
    await message.answer("🔢 شماره تراکنش رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.tx_id)
async def wallet_action(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    try:
        txid = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ شماره تراکنش عددی وارد کن:")
        return
    data = await state.get_data()
    tx = await get_wallet_tx(txid)
    if not tx or tx["status"] != "pending":
        await message.answer("❌ این تراکنش وجود نداره یا قبلاً پردازش شده!")
        return
    if data.get("tx_action") == "approve":
        await approve_wallet_tx(txid)
        await add_balance(tx["user_id"], tx["amount"])
        try:
            await message.bot.send_message(tx["user_id"], f"✅ {int(tx['amount']):,} تومان به کیف پولت اضافه شد! 💰")
        except Exception:
            pass
        await message.answer(f"✅ شارژ #{txid} تایید شد.", reply_markup=ADMIN_KB)
    else:
        await reject_wallet_tx(txid)
        try:
            await message.bot.send_message(tx["user_id"], f"❌ درخواست شارژ #{txid} رد شد. برای پیگیری به پشتیبانی پیام بده.")
        except Exception:
            pass
        await message.answer(f"❌ شارژ #{txid} رد شد.", reply_markup=ADMIN_KB)
    await state.clear()

# ---------- کد تخفیف (ادمین) ----------
@router.message(F.text == "🏷️ مدیریت کد تخفیف")
async def admin_codes(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    codes = await get_codes()
    if not codes:
        await message.answer("🏷️ هنوز کدی نساختی!", reply_markup=rkb([[("➕ ساخت کد", "success")], [(BACK_ADMIN, "danger")]]))
        return
    text = "🏷️ <b>کدهای تخفیف:</b>\n"
    for c in codes:
        status = "✅" if c["is_active"] and c["used_count"] < c["max_uses"] else "⛔️"
        text += f"{status} <code>{c['code']}</code> — {c['percent']}٪ ({c['used_count']}/{c['max_uses']})\n"
    await message.answer(text, reply_markup=rkb([[("➕ ساخت کد", "success")], [(BACK_ADMIN, "danger")]]))

@router.message(F.text == "➕ ساخت کد")
async def code_add_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.add_code)
    await message.answer("🏷️ کد تخفیف (انگلیسی) رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.add_code)
async def code_add(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    await state.update_data(code=(message.text or "").strip().upper())
    await state.set_state(AdminStates.add_code_percent)
    await message.answer("📉 درصد تخفیف (مثلاً 20):")

@router.message(AdminStates.add_code_percent)
async def code_percent(message: Message, state: FSMContext):
    try:
        percent = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ عدد وارد کن:")
        return
    await state.update_data(percent=percent)
    await state.set_state(AdminStates.add_code_uses)
    await message.answer("🔢 حداکثر دفعات مصرف:")

@router.message(AdminStates.add_code_uses)
async def code_uses(message: Message, state: FSMContext):
    try:
        uses = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ عدد وارد کن:")
        return
    data = await state.get_data()
    await create_code(data["code"], data["percent"], uses)
    await state.clear()
    await message.answer("✅ کد تخفیف ساخته شد!", reply_markup=ADMIN_KB)

# ---------- ارسال همگانی ----------
@router.message(F.text == "📣 ارسال همگانی")
async def broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.broadcast)
    await message.answer("📣 متن پیام همگانی رو بفرست:\n(میتونه عکس/متن باشه)", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    users = await get_all_users()
    ok = fail = 0
    for u in users:
        try:
            await message.send_copy(chat_id=u["telegram_id"])
            ok += 1
        except Exception:
            fail += 1
    await message.answer(f"📣 ارسال همگانی انجام شد:\n✅ {ok} نفر | ❌ {fail} ناموفق", reply_markup=ADMIN_KB)
    await state.clear()

# ---------- کاربران ----------
@router.message(F.text == "👥 کاربران")
async def users_lookup_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.lookup_user)
    await message.answer("🔍 آیدی عددی کاربر رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.lookup_user)
async def users_lookup(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    try:
        uid = int(message.text)
    except (ValueError, TypeError):
        await message.answer("❌ آیدی عددی وارد کن:")
        return
    user = await get_user(uid)
    if not user:
        await message.answer("❌ کاربری با این آیدی پیدا نشد!")
        return
    await state.update_data(target_uid=uid)
    await message.answer(f"👤 <b>کاربر {uid}</b>\n📛 نام: {user['full_name'] or '—'}\n📅 عضویت: {user['created_at'][:10]}\n"
                         f"💰 موجودی: {int(user['balance']):,} تومان\n🚫 وضعیت: {'بلاک' if user['is_blocked'] else 'فعال'}",
                         reply_markup=rkb([
                             [("🚫 بلاک/آنبلاک", "danger"), ("💰 شارژ کاربر", "success")],
                             [(BACK_ADMIN, "danger")],
                         ]))

@router.message(F.text == "🚫 بلاک/آنبلاک")
async def toggle_block(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    if not uid:
        await message.answer("اول یک کاربر پیدا کن", reply_markup=ADMIN_KB)
        return
    user = await get_user(uid)
    if not user:
        return
    new_status = 0 if user["is_blocked"] else 1
    await exec("UPDATE users SET is_blocked=? WHERE telegram_id=?", (new_status, uid))
    await message.answer(f"کاربر {uid} {'🚫 بلاک شد' if new_status else '✅ آنبلاک شد'}", reply_markup=ADMIN_KB)
    await state.clear()

@router.message(F.text == "💰 شارژ کاربر")
async def charge_user_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    if not uid:
        await message.answer("اول یک کاربر پیدا کن", reply_markup=ADMIN_KB)
        return
    await state.set_state(AdminStates.charge_amount)
    await message.answer(f"💰 مبلغ شارژ برای کاربر <code>{uid}</code> به تومان:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.charge_amount)
async def charge_user_amount(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    try:
        amount = int(message.text.replace(",", "").strip())
    except (ValueError, AttributeError):
        await message.answer("❌ عدد وارد کن:")
        return
    data = await state.get_data()
    uid = data["target_uid"]
    await add_balance(uid, amount)
    await create_wallet_tx(uid, amount, "charge", "approved")
    try:
        await message.bot.send_message(uid, f"✅ {int(amount):,} تومان به کیف پولت اضافه شد! 💰")
    except Exception:
        pass
    await message.answer(f"✅ {int(amount):,} تومان برای کاربر {uid} شارژ شد.", reply_markup=ADMIN_KB)
    await state.clear()

# ---------- تنظیمات ----------
@router.message(F.text == "⚙️ تنظیمات")
async def settings_menu(message: Message, state: FSMContext):
    await state.clear()
    if not is_admin(message.from_user.id):
        return
    card = await get_setting("card_number") or CARD_NUMBER
    support = await get_setting("support_username") or SUPPORT_USERNAME or "تنظیم نشده"
    await message.answer(f"⚙️ <b>تنظیمات</b>\n💳 کارت: <code>{card}</code>\n📞 پشتیبانی: @{support}",
                         reply_markup=rkb([
                             [("💳 شماره کارت", "primary"), ("📞 یوزرنیم پشتیبانی", "success")],
                             [(BACK_ADMIN, "danger")],
                         ]))

@router.message(F.text == "💳 شماره کارت")
async def set_card_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.set_card)
    await message.answer("💳 شماره کارت جدید رو بفرست:", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.set_card)
async def set_card(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    await set_setting("card_number", message.text)
    await message.answer("✅ شماره کارت ذخیره شد!", reply_markup=ADMIN_KB)
    await state.clear()

@router.message(F.text == "📞 یوزرنیم پشتیبانی")
async def set_support_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.set_support)
    await message.answer("📞 یوزرنیم پشتیبانی رو بفرست (بدون @):", reply_markup=rkb([[(BACK_ADMIN, "danger")]]))

@router.message(AdminStates.set_support)
async def set_support(message: Message, state: FSMContext):
    if message.text == BACK_ADMIN:
        await state.clear(); await message.answer("لغو شد", reply_markup=ADMIN_KB); return
    await set_setting("support_username", (message.text or "").strip().replace("@", ""))
    await message.answer("✅ یوزرنیم پشتیبانی ذخیره شد!", reply_markup=ADMIN_KB)
    await state.clear()

# ---------- پشتیبانگیری ----------
@router.message(F.text == "💾 پشتیبانگیری")
async def backup_db(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        from aiogram.types import FSInputFile
        if os.path.exists(DB_PATH):
            await message.answer_document(FSInputFile(DB_PATH), caption="💾 پشتیبان دیتابیس")
        else:
            await message.answer("❌ فایل دیتابیس هنوز ساخته نشده!")
    except Exception:
        await message.answer("❌ خطا در ارسال پشتیبان", reply_markup=ADMIN_KB)

# ---------------- سرور کوچک برای Render (health check) ----------------
from aiohttp import web

async def health(request):
    return web.Response(text="Bot is running ✅")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ---------------- اجرا ----------------
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(UserMiddleware())
    dp.include_router(router)
    logging.basicConfig(level=logging.INFO)
    await start_web_server()
    print("🤖 ربات شروع به کار کرد! منتظر پیام هستم...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
