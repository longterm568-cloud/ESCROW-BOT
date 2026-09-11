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
GROUP_CHAT_ID = -1004307826630
# Put your group's public username or invite link here:
GROUP_LINK = os.environ.get("GROUP_LINK", "https://t.me/c/4307826630") 
UPI_ID = "9226486684@fam"
PAYEE_NAME = "aurexpay"

deals = {}
user_state = {}

# ----------------- FLASK SERVER (24/7 UPTIME) ----------------- #
app = Flask(__name__)

@app.route("/")
def home():
    return "Aura Vault Escrow Bot is Online and Healthy!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ----------------- HELPERS ----------------- #
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
            "🔒 Both parties must click agree before deal is posted."
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

        await query.message.reply_text("✅ You agreed to the Terms & Conditions!")

        # Once BOTH parties agree in DM
        if deal["creator_agreed"] and deal["joiner_agreed"] and not deal.get("posted_to_group", False):
            deal["posted_to_group"] = True
            total_payable = deal["amount"] + deal["fee"]

            # 1. Fetch Group Admins to mention
            admin_mentions = []
            try:
                admins = await context.bot.get_chat_administrators(GROUP_CHAT_ID)
                for admin in admins:
                    if not admin.user.is_bot:
                        if admin.user.username:
                            admin_mentions.append(f"@{admin.user.username}")
                        else:
                            admin_mentions.append(f"<a href='tg://user?id={admin.user.id}'>{admin.user.first_name}</a>")
            except Exception as e:
                print(f"Error fetching group admins: {e}")

            mentions_text = " ".join(admin_mentions) if admin_mentions else "Admins"

            # 2. Form to post in group
            group_deal_form = (
                f"🛡️ <b>NEW ESCROW DEAL CONFIRMED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>Deal ID:</b> <code>{deal_id}</code>\n"
                f"💰 <b>Deal Amount:</b> ₹{deal['amount']:.2f}\n"
                f"⚡ <b>Escrow Fee:</b> ₹{deal['fee']:.2f}\n"
                f"💳 <b>Total Payable:</b> ₹{total_payable:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛒 <b>Buyer:</b> <a href='tg://user?id={deal['buyer_id']}'>{deal.get('buyer_name', 'Buyer')}</a> (<code>{deal['buyer_id']}</code>)\n"
                f"🏷️ <b>Seller:</b> <a href='tg://user?id={deal['seller_id']}'>{deal.get('seller_name', 'Seller')}</a> (<code>{deal['seller_id']}</code>)\n\n"
                f"📜 <b>Terms & Conditions:</b>\n{deal['terms']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📢 <b>Attention Admins:</b> {mentions_text}\n"
                f"<i>Both parties have officially agreed. Awaiting payment receipt.</i>"
            )

            # Try to get active invite link if not set
            group_url = GROUP_LINK
            try:
                chat = await context.bot.get_chat(GROUP_CHAT_ID)
                if chat.username:
                    group_url = f"https://t.me/{chat.username}"
                elif chat.invite_link:
                    group_url = chat.invite_link
            except Exception as e:
                print(f"Could not retrieve dynamic invite link: {e}")

            # Post & Pin in Group
            try:
                sent_msg = await context.bot.send_message(
                    chat_id=GROUP_CHAT_ID,
                    text=group_deal_form,
                    parse_mode="HTML"
                )
                await context.bot.pin_chat_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=sent_msg.message_id
                )
            except Exception as e:
                print(f"Error posting/pinning to group: {e}")

            group_button_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 View Deal in Group", url=group_url)]
            ])

            # 3. Send Locked Payment QR & Group Notification to BUYER
            qr_img = generate_upi_qr(UPI_ID, PAYEE_NAME, total_payable, deal_id)
            buyer_caption = (
                f"🔒 <b>DEAL ACTIVE — PAYMENT REQUIRED</b>\n\n"
                f"📢 <b>Your deal has been successfully posted and pinned in the group!</b>\n\n"
                f"🏷️ <b>Deal ID:</b> <code>{deal_id}</code>\n"
                f"💰 <b>Deal Amount:</b> ₹{deal['amount']:.2f}\n"
                f"🛡️ <b>Escrow Fee:</b> ₹{deal['fee']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💳 <b>TOTAL PAYABLE:</b> <code>₹{total_payable:.2f}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
                f"👤 <b>Payee Name:</b> <code>{PAYEE_NAME}</code>\n\n"
                f"<i>Scan the QR code to complete payment. Tap below to check the group post:</i>"
            )
            try:
                await context.bot.send_photo(
                    chat_id=deal["buyer_id"],
                    photo=qr_img,
                    caption=buyer_caption,
                    reply_markup=group_button_markup,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Buyer QR error: {e}")

            # 4. Notify SELLER with group link in DM
            seller_msg = (
                f"⏳ <b>Deal <code>{deal_id}</code> has been confirmed!</b>\n\n"
                f"📢 <b>Your deal has been updated and pinned in the escrow group!</b>\n\n"
                f"The buyer has received the payment QR code.\n"
                f"⚠️ <b>Hold on:</b> Do NOT send any account/assets until payment is verified by Admin."
            )
            try:
                await context.bot.send_message(
                    chat_id=deal["seller_id"],
                    text=seller_msg,
                    reply_markup=group_button_markup,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Seller notify error: {e}")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    if user_id not in user_state:
        return

    state = user_state[user_id]
    step = state.get("step")

    if step == "awaiting_amount":
        try:
            amt = float(text)
            if amt <= 0:
                await update.message.reply_text("Enter a valid amount greater than 0.")
                return
            state["amount"] = amt
            state["fee"] = calculate_fee(amt)
            state["step"] = "awaiting_terms"
            await update.message.reply_text(
                "📜 Please enter the <b>Terms and Conditions</b> of this deal (e.g. delivery timeframe, rules):",
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number (e.g. 500).")

    elif step == "awaiting_terms":
        deal_id = str(uuid.uuid4())[:8].upper()

        deals[deal_id] = {
            "creator_id": user_id,
            "creator_name": user.first_name,
            "creator_role": state["creator_role"],
            "amount": state["amount"],
            "fee": state["fee"],
            "terms": text,
            "creator_agreed": False,
            "joiner_id": None,
            "joiner_name": None,
            "joiner_agreed": False,
            "buyer_id": user_id if state["creator_role"] == "buyer" else None,
            "buyer_name": user.first_name if state["creator_role"] == "buyer" else None,
            "seller_id": user_id if state["creator_role"] == "seller" else None,
            "seller_name": user.first_name if state["creator_role"] == "seller" else None,
            "posted_to_group": False,
        }
        user_state.pop(user_id, None)

        msg = (
            f"🎉 <b>Deal Created Successfully!</b>\n\n"
            f"🏷️ <b>Deal ID:</b> <code>{deal_id}</code>\n"
            f"💰 <b>Amount:</b> ₹{deals[deal_id]['amount']:.2f}\n"
            f"⚡ <b>Fee:</b> ₹{deals[deal_id]['fee']:.2f}\n"
            f"📜 <b>Terms & Conditions:</b>\n{text}\n\n"
            f"➡️ Share this <b>Deal ID</b> with the other party so they can join via bot DM."
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    elif step == "awaiting_deal_id":
        deal_id = text.upper()
        if deal_id not in deals:
            await update.message.reply_text("❌ Invalid Deal ID. Please verify and try again.")
            return

        deal = deals[deal_id]
        if deal["creator_id"] == user_id:
            await update.message.reply_text("⚠️ You cannot join your own deal.")
            return

        deal["joiner_id"] = user_id
        deal["joiner_name"] = user.first_name
        if deal["creator_role"] == "buyer":
            deal["seller_id"] = user_id
            deal["seller_name"] = user.first_name
        else:
            deal["buyer_id"] = user_id
            deal["buyer_name"] = user.first_name

        user_state.pop(user_id, None)

        summary = (
            f"🤝 <b>Deal Terms Review (ID: <code>{deal_id}</code>)</b>\n\n"
            f"💰 <b>Deal Amount:</b> ₹{deal['amount']:.2f}\n"
            f"⚡ <b>Escrow Fee:</b> ₹{deal['fee']:.2f}\n"
            f"💳 <b>Total Payable:</b> ₹{(deal['amount'] + deal['fee']):.2f}\n\n"
            f"📜 <b>Terms & Conditions:</b>\n{deal['terms']}\n\n"
            f"<i>Please read the terms carefully and tap below to accept:</i>"
        )
        kb = [[InlineKeyboardButton("✅ Agree to Terms & Conditions", callback_data=f"agree_{deal_id}")]]
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
            print(f"Error sending terms to creator: {e}")

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
