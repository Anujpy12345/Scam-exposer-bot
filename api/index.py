import logging
import json
import os
import re
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

# --- PERSISTENT STORAGE FILES ---
STATES_FILE = '/tmp/user_states.json'
REPORTS_FILE = '/tmp/reports.json'

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
    with open(USERS_FILE, 'w') as f:
        json.dump(list(users), f)

def load_states():
    if os.path.exists(STATES_FILE):
        try:
            with open(STATES_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_states(states):
    with open(STATES_FILE, 'w') as f:
        json.dump(states, f)

def load_reports():
    if os.path.exists(REPORTS_FILE):
        try:
            with open(REPORTS_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_reports(reports):
    with open(REPORTS_FILE, 'w') as f:
        json.dump(reports, f)

# Load persistent data
all_users = load_users()
user_states = load_states()
reports = load_reports()

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: 
        return
    user_id = update.effective_user.id
    
    # Save user for broadcast
    if user_id not in all_users:
        all_users.add(user_id)
        save_users(all_users)

    user_states[user_id] = ASK_USERNAME
    reports[user_id] = {}
    
    # Save to files
    save_states(user_states)
    save_reports(reports)
    
    await update.effective_message.reply_text(
        "Welcome to Scammer Report Bot! 👮\n\n"
        "Step 1: Send the Scammer's @Username (or name if username is not available):"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Reload from files (in case another instance updated)
    global user_states, reports
    user_states = load_states()
    reports = load_reports()
    
    state = user_states.get(user_id)

    if state is None:
        # If user was in middle of process but state lost, restart
        user_states[user_id] = ASK_USERNAME
        reports[user_id] = {}
        save_states(user_states)
        save_reports(reports)
        
        await update.message.reply_text(
            "Welcome to Scammer Report Bot! 👮\n\n"
            "Step 1: Send the Scammer's @Username (or name if username is not available):"
        )
        return

    # State Machine Logic
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
        clean_text = text.lower().strip()
        
        # Check if it's a valid link (more flexible)
        is_valid = False
        
        # Case 1: Starts with http/https
        if clean_text.startswith(('http://', 'https://')):
            is_valid = True
        # Case 2: Starts with t.me/
        elif clean_text.startswith('t.me/'):
            is_valid = True
            # Ensure it has https:// prefix for storage
            if not clean_text.startswith('http'):
                text = 'https://' + clean_text
        # Case 3: Contains t.me/ anywhere (user might paste full URL with other text)
        elif 't.me/' in clean_text:
            is_valid = True
            # Extract just the link
            match = re.search(r'(https?://)?(t\.me/[\w-]+)', clean_text)
            if match:
                text = 'https://' + match.group(2) if not match.group(1) else match.group(0)
        # Case 4: User might send just username without t.me/
        elif clean_text.startswith('@'):
            is_valid = True
            text = f'https://t.me/{clean_text[1:]}'  # Remove @ and add t.me/
        
        if not is_valid:
            await update.message.reply_text(
                "❌ Invalid link! Send a valid Telegram link:\n"
                "• t.me/username\n"
                "• https://t.me/channel\n"
                "• @username (without space)"
            )
            return
            
        reports[user_id]['proof_link'] = text
        
        # Save before submitting
        save_states(user_states)
        save_reports(reports)
        
        await submit_to_admin(update, context)

    # Save state after each step
    save_states(user_states)
    save_reports(reports)

# --- SUBMISSION TO ADMIN ---
async def submit_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Reload reports to ensure we have latest
    global reports
    reports = load_reports()
    
    report = reports.get(user_id)

    if not report: 
        await update.message.reply_text("❌ Error: Report data not found. Please start again with /start")
        return

    admin_caption = (
        f"📩 *New Scam Report Submitted*\n\n"
        f"👤 *Reporter:* [Click here](tg://user?id={user_id})\n"
        f"🕵️ *Scammer:* {report['scammer']}\n"
        f"💰 *Amount:* {report['amount']}\n"
        f"📝 *Description:* {report['description']}"
    )

    # Keyboard layout requested: Row 1 (View Proof), Row 2 (Accept, Reject)
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
    
    # Clear user state but keep report for admin action
    global user_states
    user_states = load_states()
    user_states.pop(user_id, None)
    save_states(user_states)

# --- CALLBACK HANDLER (ADMIN ACTIONS) ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    try:
        action, r_user_id_str = data.split('_')
        r_user_id = int(r_user_id_str)
    except:
        await query.answer("Invalid callback data", show_alert=True)
        return
    
    # Reload reports to ensure we have latest data
    global reports
    reports = load_reports()
    
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
            await context.bot.send_message(r_user_id, "✅ Your report has been approved and posted on @Scammerawarealert.")
        except: 
            pass
        
        await query.edit_message_text(f"{query.message.text}\n\n✅ *Status: Approved*", parse_mode='Markdown')
        
        # Remove report after approval
        reports.pop(r_user_id, None)
        save_reports(reports)
        
    elif action == "reject":
        try:
            await context.bot.send_message(r_user_id, "❌ Your report was rejected by the admin.")
        except: 
            pass
        await query.edit_message_text(f"{query.message.text}\n\n❌ *Status: Rejected*", parse_mode='Markdown')
        
        # Remove report after rejection
        reports.pop(r_user_id, None)
        save_reports(reports)

    await query.answer()

# --- ADMIN COMMANDS ---
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: 
        return
    
    # Reload data
    global all_users
    all_users = load_users()
    
    await update.message.reply_text(f"📊 *Total Users:* {len(all_users)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID: 
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast message")
        return

    msg = " ".join(context.args)
    count = 0
    
    # Reload users
    global all_users
    all_users = load_users()
    
    for u_id in list(all_users):
        try:
            await context.bot.send_message(u_id, msg)
            count += 1
        except: 
            pass
    
    await update.message.reply_text(f"📢 Broadcast sent to {count} users.")

# --- VERCEL SERVERLESS WRAPPER ---
from telegram.ext import Application
import asyncio

application = None

async def setup_webhook():
    global application
    if application is None:
        application = ApplicationBuilder().token(API_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("broadcast", broadcast))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        await application.initialize()
        await application.start()
    return application

async def shutdown_webhook():
    global application
    if application:
        await application.stop()
        await application.shutdown()
        application = None

from http.server import BaseHTTPRequestHandler
import json as json_lib

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        update_json = json_lib.loads(post_data.decode('utf-8'))
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            app = loop.run_until_complete(setup_webhook())
            update = Update.de_json(update_json, app.bot)
            loop.run_until_complete(app.process_update(update))
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json_lib.dumps({"status": "ok"}).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json_lib.dumps({"error": str(e)}).encode())
        finally:
            loop.run_until_complete(shutdown_webhook())
            loop.close()
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running on Vercel. Set webhook to this URL.")

# For local testing only
if __name__ == '__main__':
    from http.server import HTTPServer
    server = HTTPServer(('localhost', 8000), handler)
    print("Local server running on port 8000")
    server.serve_forever()
