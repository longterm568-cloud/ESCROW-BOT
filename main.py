import os
import random
import string
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# --- WEB SERVER FOR 24/7 CLOUD HOSTING ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Escrow Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- BOT CONFIGURATION ---
BOT_TOKEN = "8853931522:AAEjBv2p_pOLtA0ifEzB2l-3dj9B9sTwZVg"
FORCE_JOIN_CHAT_ID = -1004307826630
FORCE_JOIN_LINK = "https://t.me/+z8rX6PzVvr42MzY0"
ADMIN_IDS = [7630097130, 8429660971]

deals = {}
(ROLE_SELECT, AMOUNT_INPUT, PARTNER_INPUT, JOIN_CODE_INPUT) = range(4)

def generate_deal_code():
    return "ESC-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_JOIN_CHAT_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Create Deal", callback_data="btn_create_deal")],
        [InlineKeyboardButton("🤝 Enter In Deal", callback_data="btn_enter_deal")],
        [InlineKeyboardButton("🔙 Back", callback_data="btn_back")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_member = await check_membership(user.id, context)

    if not is_member:
        keyboard = [
            [InlineKeyboardButton("📢 Join Escrow Group", url=FORCE_JOIN_LINK)],
            [InlineKeyboardButton("✅ I Have Joined", callback_data="check_joined")],
        ]
        text = "⚠️ **Access Restricted!**\n\nYou must join our official Escrow group first before using this bot."
        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ConversationHandler.END

    text = f"👋 Welcome, {user.first_name}!\n\nOfficial Escrow Bot. Choose an option below:"
    if update.message:
        await update.message.reply_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await check_membership(query.from_user.id, context):
        await query.message.edit_text("✅ Verification successful!\n\nChoose an option below:", reply_markup=get_main_menu())
    else:
        await query.answer("❌ You have not joined the group yet!", show_alert=True)

async def create_deal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🛒 Seller", callback_data="role_seller"), InlineKeyboardButton("💰 Buyer", callback_data="role_buyer")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="btn_back")],
    ]
    await query.message.edit_text("Are you the **Seller** or **Buyer**?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ROLE_SELECT

async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = "Seller" if query.data == "role_seller" else "Buyer"
    context.user_data["deal_creator_role"] = role
    await query.message.edit_text(f"You selected: **{role}**\n\nEnter the **Deal Amount** in ₹ (e.g. `500`):", parse_mode="Markdown")
    return AMOUNT_INPUT

async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount <= 0: raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number:")
        return AMOUNT_INPUT

    context.user_data["deal_amount"] = amount
    partner_role = "Buyer" if context.user_data["deal_creator_role"] == "Seller" else "Seller"
    await update.message.reply_text(f"Deal Amount: **₹{amount:g}**\n\nEnter the **Telegram Username** of the {partner_role} (e.g. `@username`):", parse_mode="Markdown")
    return PARTNER_INPUT

async def partner_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partner_username = update.message.text.strip()
    creator = update.effective_user
    amount = context.user_data["deal_amount"]
    role = context.user_data["deal_creator_role"]
    code = generate_deal_code()

    deals[code] = {
        "code": code,
        "creator_id": creator.id,
        "creator_username": f"@{creator.username}" if creator.username else creator.first_name,
        "creator_role": role,
        "partner_username": partner_username,
        "partner_id": None,
        "amount": amount,
        "creator_agreed": False,
        "partner_agreed": False,
        "status": "WAITING_PARTNER",
    }

    msg = (
        "✅ **Deal Created Successfully!**\n\n"
        f"🏷 **Deal Code:** `{code}` (Tap to copy)\n"
        f"💵 **Amount:** ₹{amount:g}\n"
        f"👤 **Your Role:** {role}\n"
        f"🎯 **Target Partner:** {partner_username}\n\n"
        "👉 Share this code with your deal partner. They must click **Enter In Deal** in the bot and enter this code."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_menu())
    return ConversationHandler.END

async def enter_deal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Paste your **Deal Code** (e.g., `ESC-XXXXXX`):")
    return JOIN_CODE_INPUT

async def join_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user = update.effective_user

    if code not in deals or deals[code]["status"] != "WAITING_PARTNER":
        await update.message.reply_text("❌ Invalid code or deal already active. Please check the code.")
        return JOIN_CODE_INPUT

    deal = deals[code]
    deal["partner_id"] = user.id
    deal["partner_name"] = f"@{user.username}" if user.username else user.first_name
    deal["status"] = "PENDING_AGREEMENT"

    fee = round(deal["amount"] * 0.02, 2)
    total = deal["amount"] + fee

    summary = (
        f"🤝 **Deal Found: `{code}`**\n\n"
        f"• **Deal Amount:** ₹{deal['amount']:g}\n"
        f"• **Middleman Fee (2%):** ₹{fee:g}\n"
        f"• **Total Payable:** ₹{total:g}\n"
        f"• **Party 1 ({deal['creator_role']}):** {deal['creator_username']}\n"
        f"• **Party 2:** {deal['partner_name']}\n\n"
        "⚠️ **Terms:** 2% MM fee is charged. Both parties must tap **Agree & Continue**."
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Agree & Continue", callback_data=f"agree_{code}")]])

    await update.message.reply_text(summary, reply_markup=markup, parse_mode="Markdown")
    try:
        await context.bot.send_message(chat_id=deal["creator_id"], text=f"🔔 {deal['partner_name']} has entered the deal!\n\n" + summary, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass
    return ConversationHandler.END

async def handle_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split("_")[1]
    if code not in deals: return

    deal = deals[code]
    if query.from_user.id == deal["creator_id"]:
        deal["creator_agreed"] = True
    elif query.from_user.id == deal["partner_id"]:
        deal["partner_agreed"] = True

    await query.message.edit_text("✅ You have agreed to the terms! Waiting for the other party...")

    if deal["creator_agreed"] and deal["partner_agreed"]:
        deal["status"] = "ACTIVE"
        fee = round(deal["amount"] * 0.02, 2)
        active_msg = (
            f"🎉 **DEAL IS NOW ACTIVE!**\n\n"
            f"🏷 **Deal Code:** `{code}`\n"
            f"💰 **Amount:** ₹{deal['amount']:g}\n"
            f"🛡 **MM Fee (2%):** ₹{fee:g}\n\n"
            "Official admin has been notified to supervise this trade. Do not deal outside!"
        )
        await context.bot.send_message(chat_id=deal["creator_id"], text=active_msg, parse_mode="Markdown")
        await context.bot.send_message(chat_id=deal["partner_id"], text=active_msg, parse_mode="Markdown")

        alert = (
            f"🚨 **NEW ESCROW DEAL ACTIVE** 🚨\n\n"
            f"• **Code:** `{code}`\n"
            f"• **Amount:** ₹{deal['amount']:g}\n"
            f"• **2% Fee:** ₹{fee:g}\n"
            f"• **Party A:** {deal['creator_username']} (ID: `{deal['creator_id']}`)\n"
            f"• **Party B:** {deal['partner_name']} (ID: `{deal['partner_id']}`)\n"
            f"• **Action Required:** Supervising admin take charge."
        )
        for admin in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin, text=alert, parse_mode="Markdown")
            except Exception:
                pass

async def back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("Choose an option below:", reply_markup=get_main_menu())
    return ConversationHandler.END

def main():
    threading.Thread(target=run_web, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))
    app.add_handler(CallbackQueryHandler(back_button, pattern="^btn_back$"))
    app.add_handler(CallbackQueryHandler(handle_agreement, pattern="^agree_"))

    create_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_deal_start, pattern="^btn_create_deal$")],
        states={
            ROLE_SELECT: [CallbackQueryHandler(role_selected, pattern="^role_")],
            AMOUNT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered)],
            PARTNER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, partner_entered)],
        },
        fallbacks=[CallbackQueryHandler(back_button, pattern="^btn_back$"), CommandHandler("start", start)],
    )

    enter_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(enter_deal_start, pattern="^btn_enter_deal$")],
        states={
            JOIN_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, join_code_received)],
        },
        fallbacks=[CallbackQueryHandler(back_button, pattern="^btn_back$"), CommandHandler("start", start)],
    )

    app.add_handler(create_conv)
    app.add_handler(enter_conv)
    app.run_polling()

if __name__ == "__main__":
    main()
