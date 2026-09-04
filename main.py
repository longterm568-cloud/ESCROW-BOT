import os
import io
import threading
import uuid
from flask import Flask
import qrcode
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8429660971
UPI_ID = "9226486684@fam"
PAYEE_NAME = "aurexpay"

deals = {}
user_state = {}

# ----------------- FLASK SERVER (KEEPS BOT ONLINE) ----------------- #
app = Flask(__name__)

@app.route("/")
def home():
    return "Aura Vault Escrow Bot is Online and Healthy!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- CALCULATION & QR GENERATION ----------------- #
def calculate_fee(amount: float) -> float:
    if amount <= 500:
        return 20.0
    elif amount <= 2000:
        return 40.0
    elif amount <= 5000:
        return 70.0
    else:
        return round(amount * 0.02, 2)

def generate_upi_qr(upi_id: str, name: str, amount: float, deal_id: str) -> io.BytesIO:
    # Locked NPCI format for UPI apps
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount:.2f}&cu=INR&tn=Deal_{deal_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = io.BytesIO()
    bio.name = f"qr_{deal_id}.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# ----------------- BOT HANDLERS ----------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("➕ Create Deal", callback_data="create_deal")],
        [InlineKeyboardButton("🤝 Enter In Deal", callback_data="enter_deal")],
        [InlineKeyboardButton("ℹ️ Escrow Rules & Fees", callback_data="rules")],
    ]
    text = (
        f"👋 <b>Welcome, {user.first_name}!</b>\n\n"
        f"Welcome to <b>Aura Vault Escrow Bot</b> 🛡️\n"
        f"Choose an option below to begin:"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "rules":
        rules = (
            "📜 <b>Aura Vault Fee Chart:</b>\n"
            "• ₹1 – ₹500: ₹20\n"
            "• ₹501 – ₹2,000: ₹40\n"
            "• ₹2,001 – ₹5,000: ₹70\n"
            "• Above ₹5,000: 2%\n\n"
            "🔒 Both parties must click agree before release."
        )
        await query.message.reply_text(rules, parse_mode="HTML")

    elif query.data == "create_deal":
        user_state[user_id] = {"step": "awaiting_role"}
        kb = [
            [InlineKeyboardButton("I am Buyer 🛒", callback_data="role_buyer")],
            [InlineKeyboardButton("I am Seller 🏷️", callback_data="role_seller")],
        ]
        await query.message.reply_text("Are you the <b>Buyer</b> or <b>Seller</b>?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif query.data in ["role_buyer", "role_seller"]:
        role = "buyer" if query.data == "role_buyer" else "seller"
        user_state[user_id] = {"step": "awaiting_amount", "creator_role": role}
        await query.message.reply_text("💵 Enter the <b>Deal Amount in INR</b> (e.g. 500):", parse_mode="HTML")

    elif query.data == "enter_deal":
        user_state[user_id] = {"step": "awaiting_deal_id"}
        await query.message.reply_text("🔑 Send the <b>Deal ID</b>:", parse_mode="HTML")

    elif query.data.startswith("agree_"):
        deal_id = query.data.split("_")[1]
        if deal_id not in deals:
            await query.message.reply_text("❌ Deal not found or expired.")
            return

        deal = deals[deal_id]
        if user_id == deal["creator_id"]:
            deal["creator_agreed"] = True
        elif user_id == deal["joiner_id"]:
            deal["joiner_agreed"] = True

        await query.message.reply_text("✅ You agreed to the deal terms!")

        # Once both parties agree
        if deal["creator_agreed"] and deal["joiner_agreed"] and not deal.get("notified_admin", False):
            deal["notified_admin"] = True
            total_payable = deal["amount"] + deal["fee"]

            # 1. Alert Admin
            admin_msg = (
                f"🚨 <b>NEW DEAL READY FOR PAYMENT</b>\n\n"
                f"🏷️ <b>Deal ID:</b> <code>{deal_id}</code>\n"
                f"💰 <b>Deal Amount:</b> ₹{deal['amount']:.2f}\n"
                f"⚡ <b>Fee:</b> ₹{deal['fee']:.2f}\n"
                f"💳 <b>Total Expected:</b> ₹{total_payable:.2f}\n\n"
                f"👤 <b>Buyer ID:</b> <code>{deal['buyer_id']}</code>\n"
                f"👤 <b>Seller ID:</b> <code>{deal['seller_id']}</code>\n"
                f"📝 <b>Terms:</b> {deal['description']}"
            )
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
            except Exception as e:
                print(f"Admin alert error: {e}")

            # 2. Send Locked QR Code to Buyer
            qr_img = generate_upi_qr(UPI_ID, PAYEE_NAME, total_payable, deal_id)
            buyer_caption = (
                f"🔒 <b>DEAL CONFIRMED — PAYMENT REQUIRED</b>\n\n"
                f"🏷️ <b>Deal ID:</b> <code>{deal_id}</code>\n"
                f"💰 <b>Deal Amount:</b> ₹{deal['amount']:.2f}\n"
                f"🛡️ <b>Escrow Fee:</b> ₹{deal['fee']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💳 <b>TOTAL PAYABLE:</b> <code>₹{total_payable:.2f}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
                f"👤 <b>Payee Name:</b> <code>{PAYEE_NAME}</code>\n\n"
                f"<i>Scan the QR code with PhonePe, Google Pay, or Paytm. The exact amount is locked.</i>"
            )
            try:
                await context.bot.send_photo(chat_id=deal["buyer_id"], photo=qr_img, caption=buyer_caption, parse_mode="HTML")
            except Exception as e:
                print(f"Buyer QR error: {e}")

            # 3. Inform Seller
            seller_msg = (
                f"⏳ <b>Both parties agreed to Deal <code>{deal_id}</code>!</b>\n\n"
                f"The buyer has received the locked payment QR.\n"
                f"<b>Wait for Admin verification</b> before delivering any assets."
            )
            try:
                await context.bot.send_message(chat_id=deal["seller_id"], text=seller_msg, parse_mode="HTML")
            except Exception as e:
                print(f"Seller notify error: {e}")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_state:
        return

    state = user_state[user_id]
    step = state.get("step")

    if step == "awaiting_amount":
        try:
            amt = float(text)
            if amt <= 0:
                await update.message.reply_text("Enter a valid number above 0.")
                return
            state["amount"] = amt
            state["fee"] = calculate_fee(amt)
            state["step"] = "awaiting_desc"
            await update.message.reply_text("📝 Enter a short description of what is being exchanged:")
        except ValueError:
            await update.message.reply_text("❌ Please enter numbers only (e.g. 1200).")

    elif step == "awaiting_desc":
        state["description"] = text
        deal_id = str(uuid.uuid4())[:8].upper()

        deals[deal_id] = {
            "creator_id": user_id,
            "creator_role": state["creator_role"],
            "amount": state["amount"],
            "fee": state["fee"],
            "description": text,
            "creator_agreed": False,
            "joiner_id": None,
            "joiner_agreed": False,
            "buyer_id": user_id if state["creator_role"] == "buyer" else None,
            "seller_id": user_id if state["creator_role"] == "seller" else None,
            "notified_admin": False
        }
        user_state.pop(user_id, None)

        msg = (
            f"🎉 <b>Deal Created!</b>\n\n"
            f"🏷️ <b>Deal ID:</b> <code>{deal_id}</code>\n"
            f"💰 <b>Amount:</b> ₹{deals[deal_id]['amount']:.2f}\n"
            f"⚡ <b>Fee:</b> ₹{deals[deal_id]['fee']:.2f}\n"
            f"📝 <b>Terms:</b> {text}\n\n"
            f"Send this Deal ID to the other party so they can join."
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    elif step == "awaiting_deal_id":
        deal_id = text.upper()
        if deal_id not in deals:
            await update.message.reply_text("❌ Invalid Deal ID. Please re-check.")
            return

        deal = deals[deal_id]
        if deal["creator_id"] == user_id:
            await update.message.reply_text("⚠️ You cannot join your own deal.")
            return

        deal["joiner_id"] = user_id
        if deal["creator_role"] == "buyer":
            deal["seller_id"] = user_id
        else:
            deal["buyer_id"] = user_id

        user_state.pop(user_id, None)

        summary = (
            f"🤝 <b>Deal Summary (<code>{deal_id}</code>)</b>\n\n"
            f"💰 <b>Amount:</b> ₹{deal['amount']:.2f}\n"
            f"⚡ <b>Fee:</b> ₹{deal['fee']:.2f}\n"
            f"💳 <b>Total Payable:</b> ₹{(deal['amount'] + deal['fee']):.2f}\n"
            f"📝 <b>Terms:</b> {deal['description']}\n\n"
            f"Both parties must click the button below to confirm:"
        )
        kb = [[InlineKeyboardButton("✅ Agree to Deal", callback_data=f"agree_{deal_id}")]]
        markup = InlineKeyboardMarkup(kb)

        await update.message.reply_text(summary, reply_markup=markup, parse_mode="HTML")
        try:
            await context.bot.send_message(
                chat_id=deal["creator_id"],
                text=f"👤 The other party has joined!\n\n{summary}",
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(e)

# ----------------- MAIN RUNNER ----------------- #
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Escrow Bot is running...")
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
