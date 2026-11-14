import asyncio
import os
import aiohttp
import time
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словарь популярных монет (Kraken использует XBT для Биткоина и XDG для Догикоина)
KRAKEN_PAIRS = {
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ADA": "ADAUSD", "DOGE": "XDGUSD", "DOT": "DOTUSD", "AVAX": "AVAXUSD",
    "LINK": "LINKUSD", "MATIC": "MATICUSD", "LTC": "LTCUSD", "BCH": "BCHUSD",
    "ATOM": "ATOMUSD", "UNI": "UNIUSD", "TON": "TONUSD", "TRX": "TRXUSD",
    "NEAR": "NEARUSD", "SHIB": "SHIBUSD", "PEPE": "PEPEUSD", "FIL": "FILUSD"
}

# Функция для красивого форматирования цены (для ИИ)
def format_price(price):
    if price < 0.0001: return f"{price:.8f}"
    if price < 0.01: return f"{price:.6f}"
    if price < 1: return f"{price:.4f}"
    return f"{price:,.2f}"

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains, losses = 0, 0
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0: gains += diff
        else: losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0: return 100.0
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

def calculate_sma(prices, period=20):
    if len(prices) < period: return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

# --- ВЕБ-СЕРВЕР ---
async def handle_index(request):
    return web.FileResponse('./index.html')

async def handle_candles(request):
    interval = request.query.get('interval', '60')
    symbol = request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
            async with session.get(url) as response:
                json_data = await response.json()
                if json_data.get("error"):
                    return web.json_response({"error": f"Монета {symbol} не найдена"}, status=404)
                
                result_key = [k for k in json_data["result"].keys() if k != "last"][0]
                raw_klines = json_data["result"][result_key]
                
                candles = []
                for k in raw_klines:
                    candles.append({
                        "time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4])
                    })
                return web.json_response(candles)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_analyze(request):
    interval = request.query.get('interval', '60')
    symbol = request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
            async with session.get(url) as response:
                json_data = await response.json()
                if json_data.get("error"):
                    return web.json_response({"error": f"Монета {symbol} не найдена"}, status=404)

        result_key = [k for k in json_data["result"].keys() if k != "last"][0]
        raw_klines = json_data["result"][result_key]
        
        closes = [float(k[4]) for k in raw_klines]
        current_price = closes[-1]
        rsi = calculate_rsi(closes)
        sma20 = calculate_sma(closes, 20)

        f_price = format_price(current_price)
        f_sma = format_price(sma20)

        if rsi < 30 and current_price < sma20:
            verdict = f"📈 <b>{symbol}: Перепроданность.</b> Ждем отскок. Рекомендация: <b>LONG</b>."
            color = "#00ff88"
        elif rsi > 70 and current_price > sma20:
            verdict = f"📉 <b>{symbol}: Перекупленность.</b> Ждем коррекцию. Рекомендация: <b>SHORT</b>."
            color = "#ff3366"
        elif current_price > sma20:
            verdict = f"🚀 <b>{symbol}: Бычий тренд.</b> Цена выше MA. Рост продолжается."
            color = "#00ff88"
        elif current_price < sma20:
            verdict = f"⚠️ <b>{symbol}: Медвежий тренд.</b> Цена ниже MA. Падение продолжается."
            color = "#ff3366"
        else:
            verdict = f"⚖️ <b>{symbol}: Флэт.</b> Рынок замер."
            color = "#00f0ff"

        analysis_html = f"""
            <div style="color: {color}; margin-bottom: 8px; font-size: 16px;">{verdict}</div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px;">
                📊 RSI: <b>{rsi:.2f}</b> | MA: <b>${f_sma}</b><br>
                💰 Цена: <b>${f_price}</b>
            </div>
        """
        return web.json_response({"analysis": analysis_html})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/candles', handle_candles)
    app.router.add_get('/api/analyze', handle_analyze)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Сервер на порту {port}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    base_url = os.getenv("WEBAPP_URL", "https://google.com")
    web_app_url = f"{base_url}?v={int(time.time())}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]
    ])
    await message.answer("Терминал обновлен. Введи тикер любой монеты!", reply_markup=keyboard)

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())