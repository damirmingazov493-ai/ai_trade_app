import asyncio
import os
import aiohttp
import time
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from supabase import create_client, Client

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ База данных Supabase подключена")
except Exception as e:
    supabase = None
    print(f"❌ Ошибка БД: {e}")

KRAKEN_PAIRS = {
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ADA": "ADAUSD", "DOGE": "XDGUSD", "DOT": "DOTUSD", "AVAX": "AVAXUSD",
    "LINK": "LINKUSD", "MATIC": "MATICUSD", "LTC": "LTCUSD", "BCH": "BCHUSD",
    "ATOM": "ATOMUSD", "UNI": "UNIUSD", "TON": "TONUSD", "TRX": "TRXUSD",
    "NEAR": "NEARUSD", "SHIB": "SHIBUSD", "PEPE": "PEPEUSD", "FIL": "FILUSD"
}

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

# --- ФОНОВЫЙ СКАНЕР УВЕДОМЛЕНИЙ ---
async def check_alerts():
    print("🚀 Сканер уведомлений запущен...")
    while True:
        if supabase:
            try:
                res = supabase.table("alerts").select("*").eq("is_active", True).execute()
                alerts = res.data
                
                if alerts:
                    async with aiohttp.ClientSession() as session:
                        for alert in alerts:
                            sym = alert['symbol']
                            pair = KRAKEN_PAIRS.get(sym, f"{sym}USD")
                            url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
                            
                            async with session.get(url) as response:
                                data = await response.json()
                                if not data.get("error"):
                                    result_key = [k for k in data["result"].keys() if k != "last"][0]
                                    current_price = float(data["result"][result_key]["c"][0])
                                    
                                    target = float(alert['target_price'])
                                    condition = alert['condition']
                                    # Если last_price пустой, берем текущую цену
                                    last_price = float(alert.get('last_price') or current_price) 
                                    
                                    triggered = False
                                    
                                    # ЛОГИКА ПЕРЕСЕЧЕНИЯ
                                    if condition == 'above' and last_price < target and current_price >= target:
                                        triggered = True
                                    elif condition == 'below' and last_price > target and current_price <= target:
                                        triggered = True
                                        
                                    if triggered:
                                        text = (
                                            f"🔔 <b>СРАБОТАЛО УВЕДОМЛЕНИЕ!</b>\n\n"
                                            f"Монета: <b>{sym}</b>\n"
                                            f"Цена достигла: <b>${format_price(current_price)}</b>\n"
                                            f"Ваша цель: {condition} ${format_price(target)}"
                                        )
                                        await bot.send_message(chat_id=alert['user_id'], text=text, parse_mode="HTML")
                                        # Отключаем после срабатывания
                                        supabase.table("alerts").update({"is_active": False}).eq("id", alert['id']).execute()
                                    else:
                                        # Обновляем last_price для следующей итерации
                                        supabase.table("alerts").update({"last_price": current_price}).eq("id", alert['id']).execute()
            except Exception as e:
                print(f"Ошибка сканера: {e}")
                
        await asyncio.sleep(30)

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
                candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in raw_klines]
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
                if json_data.get("error"): return web.json_response({"error": "Не найдено"}, status=404)

        result_key = [k for k in json_data["result"].keys() if k != "last"][0]
        closes = [float(k[4]) for k in json_data["result"][result_key]]
        current_price = closes[-1]
        rsi = calculate_rsi(closes)
        sma20 = calculate_sma(closes, 20)
        f_price, f_sma = format_price(current_price), format_price(sma20)

        if rsi < 30 and current_price < sma20:
            verdict, color = f"📈 <b>{symbol}: Перепроданность.</b> Рекомендация: <b>LONG</b>.", "#00ff88"
        elif rsi > 70 and current_price > sma20:
            verdict, color = f"📉 <b>{symbol}: Перекупленность.</b> Рекомендация: <b>SHORT</b>.", "#ff3366"
        elif current_price > sma20:
            verdict, color = f"🚀 <b>{symbol}: Бычий тренд.</b> Рекомендация: <b>LONG</b>.", "#00ff88"
        elif current_price < sma20:
            verdict, color = f"⚠️ <b>{symbol}: Медвежий тренд.</b> Рекомендация: <b>SHORT</b>.", "#ff3366"
        else:
            verdict, color = f"⚖️ <b>{symbol}: Флэт.</b> Лучше подождать.", "#00f0ff"

        analysis_html = f"""
            <div style="color: {color}; margin-bottom: 8px; font-size: 16px;">{verdict}</div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px;">
                📊 RSI: <b>{rsi:.2f}</b> | MA: <b>${f_sma}</b><br>💰 Цена: <b>${f_price}</b>
            </div>"""
        return web.json_response({"analysis": analysis_html})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# --- API УВЕДОМЛЕНИЙ ---
async def handle_get_alerts(request):
    user_id = request.query.get('user_id')
    if not user_id or user_id == '0' or not supabase: return web.json_response([])
    try:
        res = supabase.table("alerts").select("*").eq("user_id", int(user_id)).eq("is_active", True).execute()
        return web.json_response(res.data)
    except Exception as e:
        return web.json_response([])

async def handle_create_alert(request):
    if not supabase: return web.json_response({"error": "База не подключена"}, status=500)
    data = await request.json()
    
    symbol = data.get('symbol', '').upper()
    target_price = float(data.get('target_price'))
    condition = data.get('condition')
    user_id = int(data.get('user_id'))

    # Получаем текущую цену, чтобы запомнить её при создании
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    current_price = 0
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
            async with session.get(url) as response:
                tick_data = await response.json()
                if not tick_data.get("error"):
                    result_key = [k for k in tick_data["result"].keys() if k != "last"][0]
                    current_price = float(tick_data["result"][result_key]["c"][0])
    except: pass

    try:
        supabase.table("alerts").insert({
            "user_id": user_id,
            "symbol": symbol,
            "target_price": target_price,
            "condition": condition,
            "is_active": True,
            "last_price": current_price 
        }).execute()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def handle_delete_alert(request):
    if not supabase: return web.json_response({"error": "База не подключена"}, status=500)
    alert_id = request.query.get('id')
    try:
        supabase.table("alerts").delete().eq("id", int(alert_id)).execute()
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/candles', handle_candles)
    app.router.add_get('/api/analyze', handle_analyze)
    app.router.add_get('/api/alerts', handle_get_alerts)
    app.router.add_post('/api/alerts', handle_create_alert)
    app.router.add_delete('/api/alerts', handle_delete_alert)
    
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]])
    await message.answer("Приложение обновлено! Логика уведомлений исправлена.", reply_markup=keyboard)

async def main():
    await start_web_server()
    asyncio.create_task(check_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())