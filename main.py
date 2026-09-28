import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------- CONFIGURATION ----------------- #
BOT_TOKEN = "8600761951:AAEIhkCcWvMxFexkrpHbWH_MPP2T42JbsMs"

# In-memory storage for deals
deals_db = {}

# ----------------- FEES CALCULATOR ----------------- #
def calculate_fee(amount: float):
    if amount < 50:
        return None, None
    elif 50 <= amount <= 300:
        fee = 10.0
    elif 300 < amount <= 1000:
        fee = round((amount * 0.02), 2)
    else:
        fee = round((amount * 0.03), 2)
    total = amount + fee
    return fee, total

# ----------------- FORM FILL HANDLER ----------------- #
async def handle_deal_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    amt_match = re.search(r"(?:amount|deal amount)[:\s]*([0-9]+)", text, re.IGNORECASE)
    buyer_match = re.search(r"(?:buyer)[:\s]*(@?\w+)", text, re.IGNORECASE)
    seller_match = re.search(r"(?:seller)[:\s]*(@?\w+)", text, re.IGNORECASE)

    if amt_match:
        amount = float(amt_match.group(1))
        if amount < 50:
            await update.message.reply_text("❌ Minimum deal amount is 50 ₹!")
            return

        fee, total = calculate_fee(amount)
        buyer = buyer_match.group(1) if buyer_match else "Not Mentioned"
        seller = seller_match.group(1) if seller_match else "Not Mentioned"

        form_msg_id = update.message.message_id
        deals_db[form_msg_id] = {
            "amount": amount,
            "fee": fee,
            "total": total,
            "buyer": buyer,
            "seller": seller,
            "admin": None,
            "status": "pending_admin_approval",
            "action": None
        }

        fee_info = (
            f"✅ <b>FORM RECEIVED!</b>\n\n"
            f"💰 <b>Deal Amount:</b> ₹{amount}\n"
            f"📊 <b>Escrow Fee:</b> ₹{fee}\n"
            f"💵 <b>Total Amount:</b> ₹{total}\n\n"
            f"👤 <b>Buyer:</b> {buyer}\n"
            f"👤 <b>Seller:</b> {seller}\n\n"
            f"⏳ <i>Waiting for Admin confirmation. Admin must reply to this form with <code>/+deal</code> to initiate.</i>"
        )
        await update.message.reply_text(fee_info, parse_mode="HTML")

# ----------------- ADMIN COMMAND /+deal ----------------- #
async def approve_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to the deal form message with /+deal!")
        return

    form_msg = update.message.reply_to_message
    form_id = form_msg.message_id
    admin_user = update.effective_user.mention_html()

    if form_id not in deals_db:
        deals_db[form_id] = {
            "amount": "N/A",
            "fee": "N/A",
            "total": "N/A",
            "buyer": "Buyer",
            "seller": "Seller",
            "admin": admin_user,
            "status": "active"
        }
    else:
        deals_db[form_id]["admin"] = admin_user
        deals_db[form_id]["status"] = "active"

    # Form pin karne
    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=form_id
        )
    except Exception as e:
        print(f"Pin Error: {e}")

    # Buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Release", callback_data=f"rel_{form_id}"),
            InlineKeyboardButton("❌ Refund", callback_data=f"ref_{form_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔒 <b>Deal Approved & Pinned by {admin_user}!</b>\n\n"
        f"• <b>Buyer:</b> Click <b>Release</b> after receiving the product/service.\n"
        f"• <b>Seller:</b> Click <b>Refund</b> in case of any cancellation.",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# ----------------- BUTTON CALLBACK ----------------- #
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    action, form_id_str = data.split("_")
    form_id = int(form_id_str)
    user = query.from_user.mention_html()

    deal = deals_db.get(form_id)
    if not deal:
        await query.edit_message_text("❌ Deal not found or expired.")
        return

    admin_tag = deal.get("admin", "Admin")

    if action == "rel":
        deal["action"] = "Release"
        await query.message.reply_text(
            f"📢 <b>Payment Release Requested!</b>\n\n"
            f"{user} clicked <b>Release</b>.\n"
            f"👉 <b>Seller: Please send your UPI ID here!</b>\n\n"
            f"Escrow Admin: {admin_tag}",
            parse_mode="HTML"
        )
    elif action == "ref":
        deal["action"] = "Refund"
        await query.message.reply_text(
            f"📢 <b>Payment Refund Requested!</b>\n\n"
            f"{user} clicked <b>Refund</b>.\n"
            f"👉 <b>Buyer: Please send your UPI ID here!</b>\n\n"
            f"Escrow Admin: {admin_tag}",
            parse_mode="HTML"
        )

# ----------------- DEAL CARD (/deal<number>) ----------------- #
async def deal_card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text.strip()
    match = re.match(r"^/deal(\d+)$", msg_text, re.IGNORECASE)
    if not match:
        return

    deal_number = match.group(1)

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Please reply to the original deal form with this command!")
        return

    target_id = update.message.reply_to_message.message_id
    deal = deals_db.get(target_id, {
        "amount": "N/A",
        "buyer": "Buyer",
        "seller": "Seller"
    })

    admin_name = update.effective_user.mention_html()

    card_text = (
        f"𝗗𝗘𝗔𝗟 𝗡𝗨𝗠𝗕𝗘𝗥 : #{deal_number}\n"
        f"𝗔𝗠𝗢𝗨𝗡𝗧 : ₹{deal['amount']}\n"
        f"𝗘𝗦𝗖𝗥𝗢𝗪𝗘𝗥 : {admin_name}\n"
        f"𝗕𝗨𝗬𝗘𝗥 : {deal['buyer']}\n"
        f"𝗦𝗘𝗟𝗟𝗘𝗥 : {deal['seller']}\n\n"
        f"𝗧𝗛𝗔𝗡𝗞𝗦 𝗙𝗢𝗥 𝗗𝗘𝗔𝗟𝗜𝗡𝗚 & 𝗧𝗥𝗨𝗦𝗧𝗜𝗡𝗚 𝗧𝗢 𝗨𝗦\n"
        f"𝗬𝗢𝗨𝗥𝗦  - @AUREXESROWS"
    )

    await update.message.reply_text(card_text, parse_mode="HTML")

# ----------------- MAIN RUNNER ----------------- #
def main():
    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("+deal", approve_deal))
    bot_app.add_handler(MessageHandler(filters.Regex(r"^/deal\d+"), deal_card_command))
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deal_form))

    print("Escrow Bot is running smoothly...")
    bot_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
