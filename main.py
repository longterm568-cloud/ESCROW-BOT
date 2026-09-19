import os
import re
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "8853931522:AAEjBv2p_pOLtA0ifEzB2l-3dj9B9sTwZVg"

# Active deals storage
active_deals = {}

# ----------------- FLASK SERVER (24/7 UPTIME) ----------------- #
app = Flask(__name__)

@app.route("/")
def home():
    return "Escrow Bot is Online and Healthy!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- HELPER FUNCTIONS ----------------- #
async def get_admin_mentions(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        mentions = []
        for admin in admins:
            if not admin.user.is_bot:
                if admin.user.username:
                    mentions.append(f"@{admin.user.username}")
                else:
                    mentions.append(f"<a href='tg://user?id={admin.user.id}'>{admin.user.first_name}</a>")
        return " ".join(mentions) if mentions else "Admins"
    except Exception as e:
        print(f"Error fetching admins: {e}")
        return "Admins"

# ----------------- HANDLERS ----------------- #
async def send_empty_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    admins_text = await get_admin_mentions(context, chat_id)

    form_text = (
        "📋 <b>AURA VAULT ESCROW FORM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Deal amount : \n"
        "Buyer username : \n"
        "Seller username : \n"
        "Deal product/service : \n"
        "Expected time to complete deal : \n\n"
        "Note : ⚠️ <b>escrow fees are non refundable</b> ⚠️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Admins:</b> {admins_text}\n\n"
        "<i>Copy this form, fill in the details, and send it in this group.</i>"
    )
    await update.message.reply_text(form_text, parse_mode="HTML")

async def parse_and_process_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    # Check if message contains form keywords
    if "deal amount" in text.lower() and "buyer username" in text.lower() and "seller username" in text.lower():
        # Extract usernames using regex
        buyer_match = re.search(r"buyer username\s*:\s*@?([a-zA-Z0-9_]+)", text, re.IGNORECASE)
        seller_match = re.search(r"seller username\s*:\s*@?([a-zA-Z0-9_]+)", text, re.IGNORECASE)

        if not buyer_match or not seller_match:
            await update.message.reply_text("⚠️ Please provide valid usernames (@username) for both Buyer and Seller.")
            return

        buyer_uname = buyer_match.group(1).lower()
        seller_uname = seller_match.group(1).lower()

        # Pin the user's filled form
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            print(f"Pin error: {e}")

        # Store deal state
        deal_id = str(message_id)
        active_deals[deal_id] = {
            "buyer_uname": buyer_uname,
            "seller_uname": seller_uname,
            "buyer_agreed": False,
            "seller_agreed": False,
            "form_message_id": message_id
        }

        # Send Agree buttons in reply
        keyboard = [
            [
                InlineKeyboardButton(f"🛒 @{buyer_uname} (Agree)", callback_data=f"agree_buyer_{deal_id}"),
                InlineKeyboardButton(f"🏷️ @{seller_uname} (Agree)", callback_data=f"agree_seller_{deal_id}")
            ]
        ]
        await update.message.reply_text(
            "🤝 <b>Both Agree?</b>\nBoth parties must click their respective button to confirm terms:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    current_username = (user.username or "").lower()

    if not data.startswith("agree_"):
        return

    parts = data.split("_")
    role = parts[1]      # "buyer" or "seller"
    deal_id = parts[2]

    if deal_id not in active_deals:
        await query.answer("❌ This deal has expired or completed.", show_alert=True)
        return

    deal = active_deals[deal_id]

    if role == "buyer":
        if current_username != deal["buyer_uname"]:
            await query.answer("❌ Only the designated Buyer can click this button!", show_alert=True)
            return
        if deal["buyer_agreed"]:
            await query.answer("You have already agreed.", show_alert=True)
            return
        deal["buyer_agreed"] = True
        await query.answer("✅ Buyer agreed!")

    elif role == "seller":
        if current_username != deal["seller_uname"]:
            await query.answer("❌ Only the designated Seller can click this button!", show_alert=True)
            return
        if deal["seller_agreed"]:
            await query.answer("You have already agreed.", show_alert=True)
            return
        deal["seller_agreed"] = True
        await query.answer("✅ Seller agreed!")

    # Update button labels to show checkmark on agreement
    buyer_status = "✅" if deal["buyer_agreed"] else "🛒"
    seller_status = "✅" if deal["seller_agreed"] else "🏷️"

    updated_keyboard = [
        [
            InlineKeyboardButton(f"{buyer_status} @{deal['buyer_uname']}", callback_data=f"agree_buyer_{deal_id}"),
            InlineKeyboardButton(f"{seller_status} @{deal['seller_uname']}", callback_data=f"agree_seller_{deal_id}")
        ]
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(updated_keyboard))

    # Check if both parties have agreed
    if deal["buyer_agreed"] and deal["seller_agreed"]:
        chat_id = query.message.chat.id
        admins_text = await get_admin_mentions(context, chat_id)

        completion_msg = (
            f"🎉 <b>DEAL CONFIRMED BY BOTH PARTIES!</b>\n\n"
            f"🛒 <b>Buyer:</b> @{deal['buyer_uname']} ✅\n"
            f"🏷️ <b>Seller:</b> @{deal['seller_uname']} ✅\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Attention Admins:</b> {admins_text}\n"
            f"Both parties have agreed to the terms. Please take over and provide payment details."
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=completion_msg,
            reply_to_message_id=deal["form_message_id"],
            parse_mode="HTML"
        )
        # Clear deal from memory
        active_deals.pop(deal_id, None)

# ----------------- MAIN FUNCTION ----------------- #
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    # Form trigger (matches 'form' or command /form)
    app_bot.add_handler(CommandHandler("form", send_empty_form))
    app_bot.add_handler(MessageHandler(filters.Regex(r"(?i)^\s*form\s*$"), send_empty_form))

    # Filled form detector
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, parse_and_process_form))

    # Agreement button handler
    app_bot.add_handler(CallbackQueryHandler(button_callback))

    print("Escrow Bot is running...")
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
