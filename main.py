import asyncio
import os
import aiohttp
import time
import random
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
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) # Твой Telegram ID для уведомлений

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    supabase = None

KRAKEN_PAIRS = {
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ADA": "ADAUSD", "DOGE": "XDGUSD", "DOT": "DOTUSD", "AVAX": "AVAXUSD",
    "LINK": "LINKUSD", "MATIC": "MATICUSD", "LTC": "LTCUSD", "BCH": "BCHUSD",
    "ATOM": "ATOMUSD", "UNI": "UNIUSD", "TON": "TONUSD", "TRX": "TRXUSD",
    "NEAR": "NEARUSD", "SHIB": "SHIBUSD", "PEPE": "PEPEUSD", "FIL": "FILUSD"
}

# Хранилище текущего состояния консолидаций
consolidation_state = {} 

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

# --- СКАНЕР БОКОВИКОВ ---
async def scan_consolidations():
    print("🚀 Скринер боковиков запущен...")
    
    # Исключаем PEPE и SHIB, так как у них могут быть проблемы с точностью
    scan_symbols = [sym for sym in KRAKEN_PAIRS.keys() if sym not in ["PEPE", "SHIB"]]
    
    while True:
        found_count = 0
        for symbol in scan_symbols:
            pair = KRAKEN_PAIRS.get(symbol)
            if not pair: continue
            
            try:
                async with aiohttp.ClientSession() as session:
                    # Берем 30 часовых свечей
                    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=60"
                    async with session.get(url) as response:
                        data = await response.json()
                        if data.get("error"): continue
                        
                        result_key = [k for k in data["result"].keys() if k != "last"][0]
                        candles = data["result"][result_key]
                        
                        if len(candles) < 25: continue
                        
                        # Берем 20 ЗАКРЫТЫХ свечей (исключаем текущую, которая еще формируется)
                        closed_candles = candles[:-1]
                        recent_candles = closed_candles[-20:]
                        
                        highs = [float(c[2]) for c in recent_candles]
                        lows = [float(c[3]) for c in recent_candles]
                        
                        max_high = max(highs)
                        min_low = min(lows)
                        current_price = float(candles[-1][4])
                        
                        # Разница между макс и мин в %
                        range_pct = ((max_high - min_low) / min_low) * 100
                        
                        # Если размах меньше 5% за 20 часов — это боковик
                        is_flat = range_pct < 5.0
                        
                        prev_state = consolidation_state.get(symbol, {"is_flat": False, "max_high": 0, "min_low": 0})
                        
                        if is_flat:
                            found_count += 1
                            consolidation_state[symbol] = {
                                "is_flat": True, 
                                "max_high": max_high, 
                                "min_low": min_low,
                                "price": current_price,
                                "range_pct": range_pct
                            }
                        else:
                            # Логика пробоя
                            if prev_state["is_flat"]:
                                direction = "ВВЕРХ 🚀" if current_price > prev_state["max_high"] else "ВНИЗ 📉"
                                if ADMIN_ID:
                                    msg = (f"⚡️ <b>ПРОБОЙ БОКОВИКА!</b>\n\n"
                                           f"Монета: <b>{symbol}</b>\n"
                                           f"Направление: <b>{direction}</b>\n"
                                           f"Цена: {format_price(current_price)}\n"
                                           f"Границы были: {format_price(prev_state['min_low'])} - {format_price(prev_state['max_high'])}")
                                    try: await bot.send_message(ADMIN_ID, msg, parse_mode="HTML")
                                    except: pass
                            
                            consolidation_state[symbol] = {"is_flat": False}
                            
            except Exception as e:
                print(f"Ошибка сканирования {symbol}: {e}")
            
            await asyncio.sleep(1) # Пауза между запросами (чтобы Kraken не забанил)
            
        print(f"✅ Сканирование завершено. Найдено в боковике: {found_count}")
        await asyncio.sleep(900) # Ждем 15 минут перед новым сканированием

# --- ФОНОВЫЙ СКАНЕР УВЕДОМЛЕНИЙ ---
async def check_alerts():
    while True:
        if supabase:
            try:
                res = supabase.table("alerts").select("*").eq("is_active", True).execute()
                for alert in res.data:
                    sym, pair = alert['symbol'], KRAKEN_PAIRS.get(alert['symbol'], f"{alert['symbol']}USD")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"https://api.kraken.com/0/public/Ticker?pair={pair}") as response:
                            data = await response.json()
                            if not data.get("error"):
                                result_key = [k for k in data["result"].keys() if k != "last"][0]
                                current_price = float(data["result"][result_key]["c"][0])
                                target = float(alert['target_price'])
                                condition = alert['condition']
                                last_price = float(alert.get('last_price') or current_price)
                                
                                triggered = (condition == 'above' and last_price < target and current_price >= target) or \
                                            (condition == 'below' and last_price > target and current_price <= target)
                                            
                                if triggered:
                                    text = f"🔔 <b>ЦЕНА ДОСТИГЛА ЦЕЛИ!</b>\n\nМонета: <b>{sym}</b>\nЦена: <b>${format_price(current_price)}</b>"
                                    await bot.send_message(chat_id=alert['user_id'], text=text, parse_mode="HTML")
                                    supabase.table("alerts").update({"is_active": False}).eq("id", alert['id']).execute()
                                else:
                                    supabase.table("alerts").update({"last_price": current_price}).eq("id", alert['id']).execute()
            except Exception as e: pass
        await asyncio.sleep(30)

# --- ВЕБ-СЕРВЕР ---
async def handle_index(request):
    return web.FileResponse('./index.html')

async def handle_get_consolidations(request):
    result = []
    for sym, state in consolidation_state.items():
        if state.get("is_flat"):
            result.append({
                "symbol": sym,
                "price": state["price"],
                "max_high": state["max_high"],
                "min_low": state["min_low"],
                "range_pct": state["range_pct"]
            })
    # Сортируем по самому узкому диапазону
    result.sort(key=lambda x: x["range_pct"])
    return web.json_response(result)

async def handle_candles(request):
    interval, symbol = request.query.get('interval', '60'), request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}") as response:
                json_data = await response.json()
                if json_data.get("error"): return web.json_response({"error": "Нет данных"}, status=404)
                result_key = [k for k in json_data["result"].keys() if k != "last"][0]
                candles = [{"time": int(k[0]), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in json_data["result"][result_key]]
                return web.json_response(candles)
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_volume_profile(request):
    interval, symbol = request.query.get('interval', '60'), request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}") as response:
                json_data = await response.json()
                if json_data.get("error"): return web.json_response({"error": "Нет данных"}, status=404)
        result_key = [k for k in json_data["result"].keys() if k != "last"][0]
        raw = json_data["result"][result_key]
        highs, lows = [float(k[2]) for k in raw], [float(k[3]) for k in raw]
        min_p, max_p = min(lows), max(highs)
        if max_p == min_p: return web.json_response([])
        bins = 50
        bin_size = (max_p - min_p) / bins
        profile = {i: 0 for i in range(bins)}
        for k in raw:
            start_bin = int((float(k[3]) - min_p) / bin_size)
            end_bin = int((float(k[2]) - min_p) / bin_size)
            if end_bin >= bins: end_bin = bins - 1
            vol_per_bin = float(k[6]) / (end_bin - start_bin + 1) if end_bin > start_bin else float(k[6])
            for b in range(start_bin, end_bin + 1): profile[b] += vol_per_bin
        sorted_bins = sorted(profile.items(), key=lambda x: x[1], reverse=True)[:3]
        return web.json_response([{"price": min_p + (b * bin_size) + (bin_size / 2), "volume": v} for b, v in sorted_bins])
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_analyze(request):
    interval, symbol = request.query.get('interval', '60'), request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}") as response:
                json_data = await response.json()
                if json_data.get("error"): return web.json_response({"error": "Нет данных"}, status=404)
        result_key = [k for k in json_data["result"].keys() if k != "last"][0]
        raw = json_data["result"][result_key]
        closes, highs, lows = [float(k[4]) for k in raw], [float(k[2]) for k in raw], [float(k[3]) for k in raw]
        current_price, rsi, sma20 = closes[-1], calculate_rsi(closes), calculate_sma(closes, 20)
        
        trend, color, targets = 'FLAT', "#8b5cf6", []
        recent_highs, recent_lows = sorted(highs[-20:], reverse=True), sorted(lows[-20:])
        macro_highs, macro_lows = sorted(highs[-50:], reverse=True), sorted(lows[-50:])

        if (rsi < 40 and current_price < sma20) or (current_price < sma20 * 0.98):
            trend, color = 'SHORT', "#f43f5e"
            verdict = f"📉 <b>{symbol}: Медвежий тренд.</b> Ищем стопы внизу."
            t1 = recent_lows[0] if recent_lows else current_price * 0.98
            t2 = macro_lows[0] if macro_lows else current_price * 0.95
            targets = [{"price": t1, "label": "Цель 1 (Стопы)"}, {"price": t2, "label": "Цель 2 (Дно)"}]
        elif (rsi > 60 and current_price > sma20) or (current_price > sma20 * 1.02):
            trend, color = 'LONG', "#10b981"
            verdict = f"🚀 <b>{symbol}: Бычий тренд.</b> Ищем стопы вверху."
            t1 = recent_highs[0] if recent_highs else current_price * 1.02
            t2 = macro_highs[0] if macro_highs else current_price * 1.05
            targets = [{"price": t1, "label": "Цель 1 (Стопы)"}, {"price": t2, "label": "Цель 2 (Пик)"}]
        else:
            verdict = f"⚖️ <b>{symbol}: Флэт.</b> Лучше подождать."

        analysis_html = f"<div style='color: {color}; margin-bottom: 8px; font-size: 16px;'>{verdict}</div><div style='font-size: 12px; color: #64748b; margin-top: 10px; border-top: 1px solid rgba(0,0,0,0.1); padding-top: 8px;'>📊 RSI: <b>{rsi:.2f}</b> | MA: <b>${format_price(sma20)}</b><br>💰 Цена: <b>${format_price(current_price)}</b></div>"
        return web.json_response({"analysis": analysis_html, "trend": trend, "targets": targets, "color": color})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_orderbook(request):
    symbol = request.query.get('symbol', 'BTC').upper()
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    binance_symbol = f"{symbol}USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.kraken.com/0/public/Depth?pair={pair}&count=100") as response:
                json_data = await response.json()
                if json_data.get("error"): return web.json_response({"error": "Нет данных"}, status=404)
        result_key = [k for k in json_data["result"].keys() if k != "last"][0]
        book = json_data["result"][result_key]
        bids = [[float(item[0]), float(item[1])] for item in book["bids"]]
        asks = [[float(item[0]), float(item[1])] for item in book["asks"]]
        if not bids or not asks: return web.json_response({"error": "Стакан пуст"}, status=404)
        mid_price = (bids[0][0] + asks[0][0]) / 2
        buy_vol, sell_vol = 0, 0
        for p, v in bids:
            if p >= mid_price * 0.98: buy_vol += v
        for p, v in asks:
            if p <= mid_price * 1.02: sell_vol += v
        total = buy_vol + sell_vol
        buy_pct = int((buy_vol / total) * 100) if total > 0 else 50
        sell_pct = 100 - buy_pct
        largest_bid = max(bids, key=lambda x: x[1]) if bids else [0, 0]
        largest_ask = max(asks, key=lambda x: x[1]) if asks else [0, 0]
        
        oi_change = 0.0
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={binance_symbol}&intervalTime=1h&limit=2") as oi_res:
                    if oi_res.status == 200:
                        oi_data = await oi_res.json()
                        if oi_data.get("retCode") == 0 and len(oi_data["result"]["list"]) >= 2:
                            oi_list = oi_data["result"]["list"]
                            oi_new = float(oi_list[0]["openInterest"])
                            oi_old = float(oi_list[1]["openInterest"])
                            oi_change = round(((oi_new - oi_old) / oi_old) * 100, 1)
        except: pass
        
        return web.json_response({
            "current_price": mid_price, "buy_percent": buy_pct, "sell_percent": sell_pct,
            "largest_bid_price": largest_bid[0], "largest_bid_vol": largest_bid[1],
            "largest_ask_price": largest_ask[0], "largest_ask_vol": largest_ask[1],
            "oi_change": oi_change
        })
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_get_alerts(request):
    user_id = request.query.get('user_id')
    if not user_id or not supabase: return web.json_response([])
    try:
        res = supabase.table("alerts").select("*").eq("user_id", int(user_id)).eq("is_active", True).execute()
        return web.json_response(res.data)
    except: return web.json_response([])

async def handle_create_alert(request):
    if not supabase: return web.json_response({"error": "База не подключена"}, status=500)
    data = await request.json()
    symbol, target, cond, user_id = data.get('symbol', '').upper(), float(data.get('target_price')), data.get('condition'), int(data.get('user_id'))
    pair = KRAKEN_PAIRS.get(symbol, f"{symbol}USD")
    current_price = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.kraken.com/0/public/Ticker?pair={pair}") as response:
                tick = await response.json()
                if not tick.get("error"):
                    current_price = float(tick["result"][[k for k in tick["result"].keys() if k != "last"][0]]["c"][0])
    except: pass
    try:
        supabase.table("alerts").insert({"user_id": user_id, "symbol": symbol, "target_price": target, "condition": cond, "is_active": True, "last_price": current_price}).execute()
        return web.json_response({"status": "ok"})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def handle_delete_alert(request):
    if not supabase: return web.json_response({"error": "База не подключена"}, status=500)
    try:
        supabase.table("alerts").delete().eq("id", int(request.query.get('id'))).execute()
        return web.json_response({"status": "ok"})
    except Exception as e: return web.json_response({"error": str(e)}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/candles', handle_candles)
    app.router.add_get('/api/volume_profile', handle_volume_profile)
    app.router.add_get('/api/analyze', handle_analyze)
    app.router.add_get('/api/orderbook', handle_orderbook)
    app.router.add_get('/api/alerts', handle_get_alerts)
    app.router.add_post('/api/alerts', handle_create_alert)
    app.router.add_delete('/api/alerts', handle_delete_alert)
    app.router.add_get('/api/screener', handle_get_consolidations)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    web_app_url = f"{os.getenv('WEBAPP_URL', 'https://google.com')}?v={int(time.time())}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]])
    await message.answer("Приложение обновлено! Скринер теперь сканирует 18 монет.", reply_markup=keyboard)

async def main():
    await start_web_server()
    asyncio.create_task(check_alerts())
    asyncio.create_task(scan_consolidations())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())