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

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# File to store user IDs for broadcast
USERS_FILE = '/tmp/users.json'

# States for conversation
ASK_USERNAME, ASK_DESCRIPTION, ASK_AMOUNT, ASK_PROOF_LINK = range(4)

# Temporary memory storage
user_states = {}
reports = {}

# --- DATABASE FUNCTIONS ---
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_users(users):
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(list(users), f)
    except:
        pass

all_users = load_users()

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: return
    user_id = update.effective_user.id
    
    # Save user for broadcast
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
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip() # Sirf extra space hatane ke liye
    state = user_states.get(user_id)

    if state is None:
        return

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
        await update.message.reply_text(
            "Step 4: Send the Proof Link.\n\n"
            "Create a channel, upload proofs, and send the link here:"
        )

    elif state == ASK_PROOF_LINK:
        # FIX: Added .lower() so it accepts T.me, https:// etc.
        if not (text.lower().startswith("http") or text.lower().startswith("t.me")):
            await update.message.reply_text("❌ Invalid link! Send a valid URL (https://... or t.me/...)")
            return
            
        reports[user_id]['proof_link'] = text
        await submit_to_admin(update, context)

# --- SUBMISSION TO ADMIN ---
async def submit_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report = reports.get(user_id)

    if not report: return

    admin_caption = (
        f"📩 *New Scam Report Submitted*\n\n"
        f"👤 *Reporter:* [Click here](tg://user?id={user_id})\n"
        f"🕵️ *Scammer:* {report['scammer']}\n"
        f"💰 *Amount:* {report['amount']}\n"
        f"📝 *Description:* {report['description']}"
    )

    keyboard = [
        [InlineKeyboardButton("🔍 View Proofs", url=report['proof_link'])],
        [InlineKeyboardButton("✅ Accept", callback_data=f"approve_{user_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")]
    ]
    
    await context.bot.send_message(
        ADMIN_USER_ID, 
        admin_caption, 
        parse_mode='Markdown', 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text("✅ Your report has been sent to Admin for review.")
    user_states.pop(user_id, None)

# --- CALLBACK HANDLER (ADMIN ACTIONS) ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, r_user_id = data.split('_')
    r_user_id = int(r_user_id)
    
    report = reports.get(r_user_id)
    
    if action == "approve":
        if not report:
            await query.answer("Report data lost! Admin cannot approve.", show_alert=True)
            return

        channel_post = (
            f"➖➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            f"🚨 *SCAMMER ALERT*\n"
            f"➖➖➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            f"🕵️ *Scammer:* {report['scammer']}\n"
            f"💰 *Scammed Amount:* {report['amount']}\n"
            f"📝 *Details:* {report['description']}\n\n"
            f"⚠️ *Stay alert and don't deal with them!*"
        )

        channel_buttons = [
            [InlineKeyboardButton("🖼️ View Proofs", url=report['proof_link'])],
            [InlineKeyboardButton("👤 Reported By", url=f"tg://user?id={r_user_id}")]
        ]

        await context.bot.send_message(
            CHANNEL_ID, 
            channel_post, 
            parse_mode='Markdown', 
            reply_markup=InlineKeyboardMarkup(channel_buttons)
        )

        try:
            # USER KO MESSAGE YAHAN JATA HAI (SAME TEXT)
            await context.bot.send_message(r_user_id, "✅ Your report has been approved and posted on @Scammerawarealert.")
        except: pass
        
        await query.edit_message_text(f"{query.message.text}\n\n✅ *Status: Approved*", parse_mode='Markdown')
        reports.pop(r_user_id, None)
        
    elif action == "reject":
        try:
            await context.bot.send_message(r_user_id, "❌ Your report was rejected by the admin.")
        except: pass
        await query.edit_message_text(f"{query.message.text}\n\n❌ *Status: Rejected*", parse_mode='Markdown')
        reports.pop(r_user_id, None)

    await query.answer()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: return
    await update.message.reply_text(f"📊 *Total Users:* {len(all_users)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast message")
        return

    msg = " ".join(context.args)
    count = 0
    for u_id in list(all_users):
        try:
            await context.bot.send_message(u_id, msg)
            count += 1
        except: pass
    await update.message.reply_text(f"📢 Broadcast sent to {count} users.")

# --- VERCEL WRAPPER ---
app = Flask(__name__)
bot_application = ApplicationBuilder().token(API_TOKEN).build()

bot_application.add_handler(CommandHandler("start", start))
bot_application.add_handler(CommandHandler("stats", stats))
bot_application.add_handler(CommandHandler("broadcast", broadcast))
bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
bot_application.add_handler(CallbackQueryHandler(handle_callback))

@app.route('/', methods=['POST', 'GET'])
async def v_handler():
    if request.method == 'POST':
        update = Update.de_json(request.get_json(force=True), bot_application.bot)
        async with bot_application:
            await bot_application.process_update(update)
        return 'ok', 200
    return 'Bot is active', 200
