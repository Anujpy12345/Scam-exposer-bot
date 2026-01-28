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

# File Path
USERS_FILE = '/tmp/users.json'

# States
ASK_USERNAME, ASK_DESCRIPTION, ASK_AMOUNT, ASK_PROOF_LINK = range(4)

user_states = {}
reports = {}

# --- DATABASE ---
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_users(users):
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(list(users), f)
    except: pass

all_users = load_users()

# --- HANDLERS (Unmodified Logic) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in all_users:
        all_users.add(user_id)
        save_users(all_users)
    user_states[user_id] = ASK_USERNAME
    reports[user_id] = {} 
    await update.effective_message.reply_text("Welcome! Step 1: Send Scammer's @Username:")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text
    state = user_states.get(user_id)
    if state is None: return

    if state == ASK_USERNAME:
        reports[user_id]['scammer'] = text
        user_states[user_id] = ASK_DESCRIPTION
        await update.message.reply_text("Step 2: Describe incident:")
    elif state == ASK_DESCRIPTION:
        reports[user_id]['description'] = text
        user_states[user_id] = ASK_AMOUNT
        await update.message.reply_text("Step 3: Enter Amount:")
    elif state == ASK_AMOUNT:
        reports[user_id]['amount'] = text
        user_states[user_id] = ASK_PROOF_LINK
        await update.message.reply_text("Step 4: Send Proof Link:")
    elif state == ASK_PROOF_LINK:
        if not (text.startswith("http") or text.startswith("t.me")):
            await update.message.reply_text("❌ Invalid link!")
            return
        reports[user_id]['proof_link'] = text
        await submit_to_admin(update, context)

async def submit_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report = reports.get(user_id)
    if not report: return
    caption = f"🕵️ Scammer: {report['scammer']}\n💰 Amount: {report['amount']}\n📝 Info: {report['description']}"
    kb = [[InlineKeyboardButton("🔍 Proof", url=report['proof_link'])],
          [InlineKeyboardButton("✅ Accept", callback_data=f"approve_{user_id}"),
           InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]]
    await context.bot.send_message(ADMIN_USER_ID, caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Sent to admin.")
    user_states.pop(user_id, None)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, r_user_id = query.data.split('_')
    r_user_id = int(r_user_id)
    report = reports.get(r_user_id)
    if action == "approve" and report:
        post = f"🚨 *SCAMMER ALERT*\n\n🕵️ Scammer: {report['scammer']}\n💰 Amount: {report['amount']}"
        btns = [[InlineKeyboardButton("🖼️ Proof", url=report['proof_link'])]]
        await context.bot.send_message(CHANNEL_ID, post, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(btns))
        await query.edit_message_text(f"{query.message.text}\n\n✅ Approved")
    elif action == "reject":
        await query.edit_message_text(f"{query.message.text}\n\n❌ Rejected")
    await query.answer()

# --- VERCEL INTEGRATION ---
app = Flask(__name__)
# Initialize ptb_app globally
ptb_app = ApplicationBuilder().token(API_TOKEN).build()

async def setup_ptb():
    # Registration of handlers
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    ptb_app.add_handler(CallbackQueryHandler(handle_callback))
    await ptb_app.initialize()

# This is the trick to run async inside sync Flask on Vercel
@app.route('/', methods=['POST', 'GET'])
def webhook():
    if request.method == 'POST':
        try:
            # Create a new event loop for each request
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Setup and Process
            loop.run_until_complete(setup_ptb())
            update = Update.de_json(request.get_json(force=True), ptb_app.bot)
            loop.run_until_complete(ptb_app.process_update(update))
            return 'ok', 200
        except Exception as e:
            logger.error(f"Error: {e}")
            return str(e), 500
    return 'Bot is Running', 200
