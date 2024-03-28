import logging
import os
import requests
import json
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters, JobQueue
from telegram import CallbackQuery
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Replace with your API token from the .env file
API_TOKEN = os.getenv('API_TOKEN')

jupiter_baseurl = "https://jup.ag/swap"

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define stages as constants for clarity in state management
ENTER_TARGET_PROFIT, ENTER_STOP_LOSS, ENTER_WALLET_ADDRESS, ENTER_SOL_AMOUNT = range(4)

new_tokens_for_price_check = []

def get_db_connection():
    return psycopg2.connect(
        dbname='telegram_bot_db',
        user='postgres',
        password='jupiter',
        host='localhost'
    )

def add_user(telegram_id, wallet_address):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO users (telegram_id, wallet_address) VALUES (%s, %s)',
                        (telegram_id, wallet_address))

def get_user(telegram_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM users WHERE telegram_id = %s', (telegram_id,))
            return cur.fetchone()

def start(update: Update, context: CallbackContext) -> None:
    user_chat_id = update.message.chat_id
    # Initialize a set in the bot's context if it doesn't exist
    if 'subscribed_users' not in context.bot_data:
        context.bot_data['subscribed_users'] = set()
    # Add the user's chat ID to the set
    context.bot_data['subscribed_users'].add(user_chat_id)
    # add_user("1234", "123124")
    keyboard = [
        [InlineKeyboardButton("🛠️ Setup", callback_data='start_setup'),
        InlineKeyboardButton("🛒 Buy Tokens", callback_data='buy'),
        InlineKeyboardButton("💰 Sell Tokens", callback_data='sell')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Welcome to the trading bot. Use the buttons to configure your trading parameters or buy/sell.', reply_markup=reply_markup)

def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    context.user_data['current_action'] = query.data  # Track the current action

    if query.data in ['start_setup', 'buy', 'sell']:
        # Directly handle actions without additional user input
        actions_without_input = {
            'start_setup': setup_buttons,
            'buy': buy_from_button,
            'sell': sell_from_button
        }
        actions_without_input[query.data](update, context)
    else:
        action_messages = {
            'enter_target_profit': "Please enter your target profit percentage. This will determine the profit level at which the bot will attempt to sell the tokens.",
            'enter_stop_loss': "Please enter your stop-loss percentage. This helps in minimizing losses by setting a threshold at which the bot will sell the tokens if the prices fall.",
            'enter_wallet_address': "Please enter your wallet address. The bot will use this address for trading tokens.",
            'enter_sol_amount': "Please enter the amount of SOL you wish to use for trading. This amount will be used to purchase tokens."
        }
        # Actions that require further user input
        if query.data == 'enter_target_profit':
            context.user_data['current_action'] = ENTER_TARGET_PROFIT
        elif query.data == 'enter_stop_loss':
            context.user_data['current_action'] = ENTER_STOP_LOSS
        elif query.data == 'enter_wallet_address':
            context.user_data['current_action'] = ENTER_WALLET_ADDRESS
        elif query.data == 'enter_sol_amount':
            context.user_data['current_action'] = ENTER_SOL_AMOUNT

        query.message.reply_text(f"{action_messages[query.data]}")

def handle_user_input(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    current_action = context.user_data.get('current_action')
    user_id = update.effective_user.id  # User's Telegram ID as unique identifier

    # Load or initialize user settings
    try:
        with open('user_settings.json', 'r') as file:
            user_settings = json.load(file)
    except FileNotFoundError:
        user_settings = {}

    if str(user_id) not in user_settings:
        user_settings[str(user_id)] = {
            'target_profit': None,
            'stop_loss': None,
            'wallet_address': None,
            'sol_amount': None
        }

    # Define the response message template
    response_template = "{} {} successfully."

    # Determine action and respond accordingly
    action_responses = {
        ENTER_TARGET_PROFIT: ('target_profit', "Target profit"),
        ENTER_STOP_LOSS: ('stop_loss', "Stop loss"),
        ENTER_WALLET_ADDRESS: ('wallet_address', "Wallet address"),
        ENTER_SOL_AMOUNT: ('sol_amount', "SOL amount"),
    }

    setting_key, setting_name = action_responses.get(current_action, (None, "Setting"))
    current_value = user_settings[str(user_id)].get(setting_key)

    # Determine if we are saving a new setting or updating an existing one
    action_word = "updated" if current_value is not None else "saved"

    # Update the user setting
    user_settings[str(user_id)][setting_key] = text
    response_message = response_template.format(setting_name, action_word)

    # Save updated settings
    with open('user_settings.json', 'w') as file:
        json.dump(user_settings, file, indent=4)

    update.message.reply_text(response_message)



def setup_buttons(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("📈 Set Target Profit %", callback_data='enter_target_profit')],
        [InlineKeyboardButton("📉 Set Stop Loss %", callback_data='enter_stop_loss')],
        [InlineKeyboardButton("🔑 Set Wallet Address", callback_data='enter_wallet_address')],
        [InlineKeyboardButton("💎 Set SOL Amount", callback_data='enter_sol_amount')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Determine if this was called via a button or a command
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
        # Acknowledge the callback query
        update.callback_query.answer()
        # Reply to the callback query
        update.callback_query.message.reply_text('Please choose:', reply_markup=reply_markup)
    else:
        chat_id = update.message.chat_id
        # Reply to the command
        update.message.reply_text('Please choose:', reply_markup=reply_markup)

def check_for_new_tokens(context: CallbackContext):
    global new_tokens_for_price_check    
    response = requests.get('https://token.jup.ag/strict')
    if response.status_code == 200:
        current_tokens = response.json()
        current_token_ids = set(token['address'] for token in current_tokens)
        try:
            with open('previous_token_ids.json', 'r') as f:
                previous_token_ids = set(json.load(f))
        except FileNotFoundError:
            previous_token_ids = set()

        new_tokens = [token for token in current_tokens if token['address'] not in previous_token_ids]
        new_tokens_for_price_check += new_tokens  # Update the global variable with new tokens
        
        if new_tokens:
            for token in new_tokens:
                message = '🌟✨ New token detected! 📊 Monitoring price... 📈\n\n'
                message += (
                    f"🚀 *Token Name*: {token.get('name', 'N/A')}\n"
                    f"🔖 *Symbol*: {token['symbol']}\n"
                    f"💠 *ID*: `{token['address']}`\n"
                    "─────────────────────────\n"
                )
                for user_id in context.bot_data.get('subscribed_users', []):
                    context.bot.send_message(chat_id=user_id, text=message)
            
            # Update 'previous_token_ids.json' with current tokens to avoid notifying these as new next time
            with open('previous_token_ids.json', 'w') as f:
                json.dump(list(current_token_ids), f)
    else:
        print("Failed to fetch token list")

def monitor_token_prices(context: CallbackContext):
    global new_tokens_for_price_check
    if not new_tokens_for_price_check or len(new_tokens_for_price_check) >= 1000:  # If there are no new tokens to check, skip the price monitoring
        return
    # Construct the list of token IDs from the last 30 new tokens, or fewer if less than 30 are available
    token_ids = [token['symbol'] for token in new_tokens_for_price_check[-30:]]
    message = "🔔 *Latest Token Prices Update* 🔔\n\n"
    # Now you can proceed to fetch and handle prices for these tokens as needed
    # Example: (Adjust according to how you want to use or display the price data)
    for token_id in token_ids:
        price_api_url = f"https://price.jup.ag/v4/price?ids=SOL&vsToken={token_id}"
        response = requests.get(price_api_url)
        
        if response.status_code == 200:
            try:
                data = response.json()['data'].get('SOL', 'N/A')
                prices = data.get('price', 'N/A')
                mintSymbol = data.get('mintSymbol', 'N/A')
                vsTokenSymbol = data.get('vsTokenSymbol', 'N/A')
                
                # Format the price and escape Markdown characters
                formatted_price = f"{float(prices):,.2f}" if prices != 'N/A' else 'N/A'
                formatted_price = formatted_price
                
                # Append each token's price info to the message
                message += (
                    f"📊 *Pair*: `{mintSymbol}` / `{vsTokenSymbol}`\n"
                    f"💲 *Price*: `{formatted_price}`\n\n"
                )
            except Exception as e:
                print()
                print(f"error: {e}")
        else:
            logger.error(f"Failed to fetch prices for token {token_id}")
    # Since the message is constructed with all necessary escapes, it's ready to be sent
    
    for user_id in context.bot_data.get('subscribed_users', []):
        try:
            context.bot.send_message(chat_id=user_id, text=message, parse_mode='MarkdownV2')
        except Exception as e:
            print(f"error: {e}")
def setup_periodic_tasks(job_queue: JobQueue):
    print('okay')
    # Set interval for checking new tokens and monitoring their prices as needed
    job_queue.run_repeating(check_for_new_tokens, interval=10, first=50)  # every minute
    job_queue.run_repeating(monitor_token_prices, interval=20, first=55)  # every 5 minutes

def buy_from_button(update: Update, context: CallbackContext) -> None:
    # Check if the update is from a button click or a command
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
        # Acknowledge the callback query
        update.callback_query.answer()
        # Reply to the callback query
        text = 'Buying new token pair...'
        update.callback_query.message.reply_text(text)
    else:
        chat_id = update.message.chat_id
        # Reply to the command
        text = 'Buying new token pair...'
        update.message.reply_text(text)
    
    # Perform the API request here
    # Example: Fetch and display number of tokens available for trading
    response = requests.get('https://token.jup.ag/all')
    
    if response.status_code == 200:
        tokens_count = len(response.json())
        followup_text = f'Token pair information retrieved. There are {tokens_count} tokens available for trading.'
    else:
        followup_text = 'Failed to fetch token pair information. Please try again later.'
    
    # Use context.bot.send_message to send follow-up messages if needed
    context.bot.send_message(chat_id=chat_id, text=followup_text)


def sell_from_button(update: Update, context: CallbackContext) -> None:
    # Check if the update is from a button click or a command
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
        # Acknowledge the callback query
        update.callback_query.answer()
        # Reply to the callback query
        text = 'Selling token pair...'
        update.callback_query.message.reply_text(text)
    else:
        chat_id = update.message.chat_id
        # Reply to the command
        text = 'Selling token pair...'
        update.message.reply_text(text)

def cancel(update: Update, context: CallbackContext) -> None:
    update.callback_query.message.reply_text('Setup cancelled.')
    context.user_data.clear()  # Clear the user_data to reset the state

def error(update: Update, context: CallbackContext) -> None:
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main() -> None:
    updater = Updater(API_TOKEN, use_context=True)
    dp = updater.dispatcher    
    updater.bot.request.timeout = 30  # Adjust this value as needed
    # Setup periodic tasks
    setup_periodic_tasks(updater.job_queue)

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("buy", buy_from_button))  # Command handler for /buy
    dp.add_handler(CommandHandler("sell", sell_from_button))  # Command handler for /buy
    dp.add_handler(CommandHandler("setup", setup_buttons))  # Command handler for /buy
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_user_input))
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()