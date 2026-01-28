import logging
import json
import os
import asyncio
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler, ContextTypes
)

# --- CONFIGURATION ---
API_TOKEN = os.environ.get('API_TOKEN')
ADMIN_USER_ID = 6899720377
CHANNEL_ID = '@Scammerawarealert'

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USERS_FILE = '/tmp/users.json'
ASK_USERNAME, ASK_DESCRIPTION, ASK_AMOUNT, ASK_PROOF_LINK = range(4)

user_states = {}
reports = {}

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f: return set(json.load(f))
        except: return set()
    return set()

def save_users(users):
    try:
        with open(USERS_FILE, 'w') as f: json.dump(list(users), f)
    except: pass

all_users = load_users()

# --- HANDLERS (EXACT ORIGINAL LOGIC) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return
    user_id = update.effective_user.id
    if user_id not in all_users:
        all_users.add(user_id)
        save_users(all_users)
    user_states[user_id] = ASK_USERNAME
    reports[user_id] = {} 
    await update.effective_message.reply_text(
        "Welcome to Scammer Report Bot! 👮\n\n"
        "Step 1: Send the Scammer's @Username (or name if username is not available):"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = user_states.get(user_id)
    if state is None: return

    if state == ASK_USERNAME:
        reports[user_id]['scammer'] = text
        user_states[user_id] = ASK_DESCRIPTION
        await update.message.reply_text("Step 2: Describe the scam incident in detail:")
    elif state == ASK_DESCRIPTION:
        reports[user_id]['description'] = text
        user_states[user_id] = ASK_AMOUNT
        await update.message.reply_text("Step 3: Enter the Scammed Amount (e.g. $100 or ₹5000):")
    elif state == ASK_AMOUNT:
        reports[user_id]['amount'] = text
        user_states[user_id] = ASK_PROOF_LINK
        await update.message.reply_text("Step 4: Send the Proof Link.\n\nCreate a channel, upload proofs, and send the link here:")
    elif state == ASK_PROOF_LINK:
        if not (text.lower().startswith("http") or text.lower().startswith("t.me")):
            await update.message.reply_text("❌ Invalid link! Send a valid URL (https://... or t.me/...)")
            return
        reports[user_id]['proof_link'] = text
        await submit_to_admin(update, context)

async def submit_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report = reports.get(user_id)
    if not report: return
    admin_caption = (f"📩 *New Scam Report Submitted*\n\n👤 *Reporter:* [Click here](tg://user?id={user_id})\n🕵️ *Scammer:* {report['scammer']}\n💰 *Amount:* {report['amount']}\n📝 *Description:* {report['description']}")
    keyboard = [[InlineKeyboardButton("🔍 View Proofs", url=report['proof_link'])],
                [InlineKeyboardButton("✅ Accept", callback_data=f"approve_{user_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]]
    await context.bot.send_message(ADMIN_USER_ID, admin_caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    await update.message.reply_text("✅ Your report has been sent to Admin for review.")
    user_states.pop(user_id, None)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, r_user_id = query.data.split('_')
    r_user_id = int(r_user_id)
    report = reports.get(r_user_id)
    if action == "approve":
        if not report:
            await query.answer("Report data lost!", show_alert=True)
            return
        channel_post = (f"➖➖➖➖➖➖➖➖➖➖➖➖➖➖\n🚨 *SCAMMER ALERT*\n➖➖➖➖➖➖➖➖➖➖➖➖➖➖\n\n🕵️ *Scammer:* {report['scammer']}\n💰 *Scammed Amount:* {report['amount']}\n📝 *Details:* {report['description']}\n\n⚠️ *Stay alert and don't deal with them!*")
        btns = [[InlineKeyboardButton("🖼️ View Proofs", url=report['proof_link'])], [InlineKeyboardButton("👤 Reported By", url=f"tg://user?id={r_user_id}")]]
        await context.bot.send_message(CHANNEL_ID, channel_post, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(btns))
        try: await context.bot.send_message(r_user_id, "✅ Your report has been approved and posted on @Scammerawarealert.")
        except: pass
        await query.edit_message_text(f"{query.message.text}\n\n✅ *Status: Approved*", parse_mode='Markdown')
    elif action == "reject":
        try: await context.bot.send_message(r_user_id, "❌ Your report was rejected by the admin.")
        except: pass
        await query.edit_message_text(f"{query.message.text}\n\n❌ *Status: Rejected*", parse_mode='Markdown')
    await query.answer()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_USER_ID:
        await update.message.reply_text(f"📊 *Total Users:* {len(all_users)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID or not context.args: return
    msg, count = " ".join(context.args), 0
    for u_id in list(all_users):
        try:
            await context.bot.send_message(u_id, msg)
            count += 1
        except: pass
    await update.message.reply_text(f"📢 Broadcast sent to {count} users.")

# --- VERCEL INTEGRATION ---
app = Flask(__name__)
# Global application instance
bot_app = ApplicationBuilder().token(API_TOKEN).build()

@app.route('/', methods=['POST', 'GET'])
async def v_handler():
    if request.method == 'POST':
        try:
            # Initialize bot if not initialized
            if not bot_app.handlers:
                bot_app.add_handler(CommandHandler("start", start))
                bot_app.add_handler(CommandHandler("stats", stats))
                bot_app.add_handler(CommandHandler("broadcast", broadcast))
                bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
                bot_app.add_handler(CallbackQueryHandler(handle_callback))
            
            update = Update.de_json(request.get_json(force=True), bot_app.bot)
            async with bot_app:
                await bot_app.process_update(update)
            return 'ok', 200
        except Exception as e:
            logger.error(f"Error: {e}")
            return str(e), 500 # This will show the error in browser for debugging
    return 'Bot is active', 200
