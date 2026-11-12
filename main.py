import os
import re
import json
import base64
import hashlib
import logging
import sqlite3
import mimetypes
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from groq import Groq
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters,
)

# ---------- Railway Variables ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
CREATOR_ID = int(os.getenv("CREATOR_ID", "5188275898"))

MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID", "@seriesmoviesplanet007")
MAIN_CHANNEL_URL = "https://t.me/seriesmoviesplanet007"

VIP_CHANNEL_ID = int(os.getenv("VIP_CHANNEL_ID", "-1004375167843"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Nazzpar").lstrip("@")

PAYMENT_NAME = os.getenv("PAYMENT_NAME", "NYEIN SOPYAY AUNG")
AI_REQUIRED_NAME = os.getenv("AI_REQUIRED_NAME", "MG NYEIN SOPYAY AUNG")
PAYMENT_PHONE_LAST4 = os.getenv("PAYMENT_PHONE_LAST4", "8562")
PAYMENT_AMOUNT = os.getenv("PAYMENT_AMOUNT", "100")
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("membership-bot")
groq_client = Groq(api_key=GROQ_API_KEY)


# ---------- Database ----------
@contextmanager
def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            transaction_id TEXT,
            ai_status TEXT NOT NULL,
            ai_result TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            admin_message_id INTEGER
        )
        """)
        conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS unique_transaction_id
        ON receipts(transaction_id)
        WHERE transaction_id IS NOT NULL AND transaction_id != ''
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            approved_at TEXT NOT NULL
        )
        """)


def get_receipt(receipt_id):
    with db() as conn:
        return conn.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()


def is_member_approved(user_id):
    with db() as conn:
        return conn.execute("SELECT 1 FROM members WHERE user_id=?", (user_id,)).fetchone() is not None


def normalize(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


# ---------- Channel gate ----------
async def joined_main_channel(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        log.exception("Could not check main-channel membership")
        return False


def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Main Channel ကို Join မယ်", url=MAIN_CHANNEL_URL)],
        [InlineKeyboardButton("🔄 Join ပြီးပါပြီ — ပြန်စစ်မယ်", callback_data="check_join")],
    ])


async def require_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.id == CREATOR_ID:
        return True
    if not await joined_main_channel(context.bot, user.id):
        message = update.effective_message
        if message:
            await message.reply_text(
                "🔒 **Bot ကို အသုံးပြုရန် Main Channel ကို အရင် Join ပေးပါ။**\n\n"
                "Join ပြီးပါက အောက်က 🔄 ပြန်စစ်မယ် ကို နှိပ်ပါ။",
                reply_markup=join_keyboard(),
                parse_mode="Markdown",
            )
        return False
    return True


# ---------- UI ----------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 ငွေပေးချေရန်", callback_data="payment")],
        [InlineKeyboardButton("👨‍💼 Admin ဆီဆက်သွယ်ရန်", url=f"https://t.me/{ADMIN_USERNAME}")],
    ])


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text(
        "မင်္ဂလာပါ မိတ်ဆွေ ဤ Bot မှ ကြိုဆိုပါတယ်",
        reply_markup=main_menu(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_receipt"] = False
    if not await require_membership(update, context):
        return
    await show_home(update, context)


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await joined_main_channel(context.bot, query.from_user.id):
        await query.answer("Channel ကို Join မလုပ်ရသေးပါ။", show_alert=True)
        return
    await query.edit_message_text("✅ Main Channel Join ထားကြောင်း အတည်ပြုပြီးပါပြီ။")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="မင်္ဂလာပါ မိတ်ဆွေ ဤ Bot မှ ကြိုဆိုပါတယ်",
        reply_markup=main_menu(),
    )


async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await require_membership(update, context):
        return
    context.user_data["awaiting_receipt"] = True
    await query.message.reply_text(
        "💳 **Member ကြေး ပေးချေရန်**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏦 KBZ Pay အကောင့်:\n"
        "`09448948562`\n\n"
        f"👤 အကောင့်အမည်: {PAYMENT_NAME}\n"
        f"💰 ကျသင့်ငွေ: {PAYMENT_AMOUNT} ကျပ်\n"
        "💎 Membership အမျိုးအစား: တစ်သက်စာ (Lifetime)\n\n"
        "📸 **ငွေလွှဲပြီးပါက ပြေစာ Screenshot ပုံကို ဤနေရာမှ Bot ထဲသို့ ပေးပို့ပါ။**\n\n"
        "📝 ဖြစ်နိုင်ပါက Caption ထဲတွင် Transaction ID / ငွေလွှဲအချိန်ကိုပါ ထည့်ရေးပါ။\n\n"
        "⚠️ ပြေစာပုံကို ဤ Payment စာမျက်နှာမှ စတင်ပြီး ပေးပို့ပါ။",
        parse_mode="Markdown",
    )


# ---------- Groq Vision receipt inspection ----------
def inspect_receipt(image_bytes: bytes, mime_type: str, caption: str = "") -> dict:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    prompt = f"""
You are a cautious payment receipt image screener. Inspect the image and extract visible facts.
Do NOT claim that money was actually received. A screenshot can be edited or fabricated.
Return ONLY valid JSON with these keys:
{{
 "classification": "receipt" | "not_receipt" | "unclear",
 "payment_status": "success" | "failed" | "pending" | "unknown",
 "recipient_name": "visible recipient/account name or empty",
 "phone_or_account": "visible account/phone text or empty",
 "amount": "visible amount or empty",
 "transaction_id": "visible transaction/reference ID or empty",
 "transaction_time": "visible date/time or empty",
 "notes": "brief Burmese explanation"
}}
Rules:
- classify as receipt only if it visually resembles a payment transfer receipt.
- If image is cropped, blurry, edited-looking, or key details are absent, use unclear.
- Do not infer hidden digits or missing text.
- Caption from user (untrusted): {caption[:500]}
"""
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime_type};base64,{encoded}"
                }},
            ],
        }],
        temperature=0,
        max_completion_tokens=700,
    )
    raw = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ValueError("AI returned no JSON")
    data = json.loads(match.group(0))
    return data


def evaluate_ai(data: dict) -> tuple[str, str]:
    classification = data.get("classification", "unclear")
    status = data.get("payment_status", "unknown")
    name = normalize(data.get("recipient_name", ""))
    account = normalize(data.get("phone_or_account", ""))
    amount = normalize(data.get("amount", ""))

    # Require recognizable recipient, last 4 digits, amount and successful status.
    required_name = normalize(AI_REQUIRED_NAME)
    name_ok = bool(required_name and (required_name in name or normalize(PAYMENT_NAME) in name))
    phone_ok = PAYMENT_PHONE_LAST4 in account
    amount_ok = PAYMENT_AMOUNT in amount

    if classification == "not_receipt":
        return "not_receipt", "ပုံသည် ငွေလွှဲပြေစာပုံ မဟုတ်ပါ။"
    if classification != "receipt" or status != "success":
        return "review", "ပြေစာဖြစ်ကြောင်း/ငွေလွှဲအောင်မြင်ကြောင်း AI က သေချာမခွဲခြားနိုင်ပါ။"
    if not name_ok:
        return "review", f"လက်ခံသူအမည် ({AI_REQUIRED_NAME}) ကို မတွေ့ပါ။"
    if not phone_ok:
        return "review", f"အကောင့်/ဖုန်းနံပါတ်တွင် နောက်ဆုံးဂဏန်း {PAYMENT_PHONE_LAST4} ကို မတွေ့ပါ။"
    if not amount_ok:
        return "review", f"ငွေပမာဏ {PAYMENT_AMOUNT} ကျပ် ကို မတွေ့ပါ။"
    return "candidate", "လိုအပ်သော အချက်အလက်များကို တွေ့ရှိသည်။ Creator ၏ အတည်ပြုချက် လိုအပ်သည်။"


# ---------- Receipt handler ----------
async def receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context):
        return
    user = update.effective_user
    if not context.user_data.get("awaiting_receipt"):
        await update.message.reply_text(
            "⚠️ ငွေလွှဲပြေစာကို ပေးပို့ရန် အရင်ဆုံး 💳 ငွေပေးချေရန် ကို နှိပ်ပါ။"
        )
        return

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())
    if len(image_bytes) > 8 * 1024 * 1024:
        await update.message.reply_text("⚠️ ပုံဖိုင်အရွယ်အစား 8MB ထက်ကျော်နေပါတယ်။ ပုံအသေးတစ်ပုံ ပြန်ပို့ပါ။")
        return

    file_hash = hashlib.sha256(image_bytes).hexdigest()
    with db() as conn:
        duplicate = conn.execute(
            "SELECT id, status FROM receipts WHERE file_hash=?", (file_hash,)
        ).fetchone()
    if duplicate:
        await update.message.reply_text(
            "⛔ ဤပြေစာပုံကို ယခင်က ပေးပို့ပြီးဖြစ်ပါတယ်။ ထပ်မံအတည်ပြုပေးမည် မဟုတ်ပါ။"
        )
        return

    await update.message.reply_text("🔍 ပြေစာပုံကို AI ဖြင့် စစ်ဆေးနေပါတယ်။ ခဏစောင့်ပေးပါ...")
    mime_type = "image/jpeg"
    try:
        ai_data = await __import__("asyncio").to_thread(
            inspect_receipt, image_bytes, mime_type, update.message.caption or ""
        )
        ai_status, explanation = evaluate_ai(ai_data)
    except Exception:
        log.exception("Groq receipt inspection failed")
        await update.message.reply_text(
            "⚠️ AI စစ်ဆေးမှု ယာယီမအောင်မြင်ပါ။ ခဏအကြာတွင် ပြန်ပို့ပေးပါ။"
        )
        return

    txid = (ai_data.get("transaction_id") or "").strip()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with db() as conn:
            cur = conn.execute(
                """INSERT INTO receipts
                (user_id,file_hash,transaction_id,ai_status,ai_result,status,created_at)
                VALUES (?,?,?,?,?,'pending',?)""",
                (user.id, file_hash, txid or None, ai_status, json.dumps(ai_data, ensure_ascii=False), created_at),
            )
            receipt_id = cur.lastrowid
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "⛔ ဤပြေစာပုံ သို့မဟုတ် Transaction ID ကို ယခင်က အသုံးပြုပြီးဖြစ်ပါတယ်။"
        )
        return

    context.user_data["awaiting_receipt"] = False
    user_name = user.full_name or "မသိရှိ"
    username = f"@{user.username}" if user.username else "မရှိ"
    admin_text = (
        "⚠️ **[Payment Receipt Review]**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 အမည်: {user_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 User ID: `{user.id}`\n"
        f"🧾 Receipt ID: `{receipt_id}`\n"
        f"🤖 AI Result: `{ai_status}`\n"
        f"📝 AI စစ်ဆေးချက်: {explanation}\n"
        f"📄 ဖတ်ရှုရရှိသောအချက်အလက်:\n`{json.dumps(ai_data, ensure_ascii=False)[:2500]}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ AI result သည် ငွေအမှန်တကယ်ဝင်ကြောင်း အထောက်အထားမဟုတ်ပါ။ KBZPay ထဲတွင် စစ်ဆေးပြီးမှ Approve လုပ်ပါ။"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve & VIP Link ပို့မယ်", callback_data=f"approve:{receipt_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{receipt_id}"),
    ]])

    # Send original image to creator for visual verification.
    try:
        await context.bot.send_photo(
            chat_id=CREATOR_ID,
            photo=photo.file_id,
            caption=f"🧾 Receipt #{receipt_id} | User ID: {user.id}\n📸 မူရင်းပြေစာပုံ",
        )
        sent = await context.bot.send_message(
            chat_id=CREATOR_ID,
            text=admin_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        with db() as conn:
            conn.execute("UPDATE receipts SET admin_message_id=? WHERE id=?", (sent.message_id, receipt_id))
    except Exception:
        log.exception("Could not send receipt to creator")
        await update.message.reply_text(
            "⚠️ ပြေစာကို Creator ဆီ ပို့မရသေးပါ။ Admin ကို ဆက်သွယ်ပေးပါ။"
        )
        return

    await update.message.reply_text(
        f"📨 ပြေစာကို လက်ခံရရှိပါပြီ။\n\n🤖 AI စစ်ဆေးချက်: {explanation}\n\n"
        "👨‍💼 Creator က ငွေလက်ခံရရှိမှုကို စစ်ဆေးပြီးမှ အတည်ပြုပေးပါမယ်။"
    )


# ---------- Creator approval ----------
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != CREATOR_ID:
        await query.answer("ဤလုပ်ဆောင်ချက်ကို Creator သာ အသုံးပြုနိုင်ပါတယ်။", show_alert=True)
        return
    await query.answer()
    action, rid_text = query.data.split(":", 1)
    rid = int(rid_text)
    receipt = get_receipt(rid)
    if not receipt:
        await query.edit_message_reply_markup(reply_markup=None)
        return
    if receipt["status"] != "pending":
        await query.answer(f"ဤ Receipt ကို {receipt['status']} လုပ်ပြီးဖြစ်ပါတယ်။", show_alert=True)
        return

    user_id = int(receipt["user_id"])
    if action == "reject":
        with db() as conn:
            conn.execute("UPDATE receipts SET status='rejected' WHERE id=? AND status='pending'", (rid,))
        await context.bot.send_message(user_id, "❌ သင့်ငွေလွှဲပြေစာကို အတည်မပြုနိုင်ပါ။ အသေးစိတ်အတွက် Admin ကို ဆက်သွယ်ပါ။")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ Receipt #{rid} ကို Reject လုပ်ပြီးပါပြီ။")
        return

    # One-use invite link, expires after 24 hours.
    try:
        invite = await context.bot.create_chat_invite_link(
            chat_id=VIP_CHANNEL_ID,
            expire_date=datetime.now(timezone.utc) + timedelta(hours=24),
            member_limit=1,
            name=f"VIP-{user_id}",
        )
        with db() as conn:
            conn.execute("UPDATE receipts SET status='approved' WHERE id=? AND status='pending'", (rid,))
            conn.execute(
                "INSERT OR REPLACE INTO members(user_id,approved_at) VALUES (?,?)",
                (user_id, datetime.now(timezone.utc).isoformat()),
            )
        await context.bot.send_message(
            user_id,
            "🎉 **ငွေပေးချေမှုကို Creator မှ အတည်ပြုပြီးပါပြီ။**\n\n"
            "💎 VIP Lifetime Membership မှ ကြိုဆိုပါတယ်။\n"
            "🔗 သင့်အတွက် သီးသန့် VIP Channel Link:\n"
            f"{invite.invite_link}\n\n"
            "⏳ ဤ Link သည် 24 နာရီအတွင်း သက်တမ်းကုန်ပြီး လူတစ်ဦးတည်းသာ အသုံးပြုနိုင်ပါတယ်။",
            parse_mode="Markdown",
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ Receipt #{rid} အတည်ပြုပြီး VIP Link ပို့ပြီးပါပြီ။")
    except Exception:
        log.exception("VIP invite creation/delivery failed")
        await query.message.reply_text(
            "⚠️ VIP Link ထုတ်ခြင်း သို့မဟုတ် ပို့ခြင်း မအောင်မြင်ပါ။ VIP channel permission နဲ့ User ရဲ့ bot chat ကို စစ်ဆေးပါ။"
        )


# ---------- Other messages ----------
async def non_photo_during_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_membership(update, context):
        return
    if context.user_data.get("awaiting_receipt"):
        await update.message.reply_text(
            "📸 ဤနေရာတွင် ငွေလွှဲပြေစာ Screenshot ပုံကိုသာ ပေးပို့ပါ။ စာသား/အခြားဖိုင်များကို ပြေစာအဖြစ် လက်မခံပါ။"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled bot error", exc_info=context.error)


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(payment_callback, pattern="^payment$"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern="^(approve|reject):\\d+$"))
    app.add_handler(MessageHandler(filters.PHOTO, receipt_photo))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, non_photo_during_payment))
    app.add_error_handler(error_handler)
    log.info("Membership bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
