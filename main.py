import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ ДЛЯ АНАЛИЗА ---
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

# ПРОКСИ ДЛЯ ГРАФИКА (теперь через BingX)
async def handle_candles(request):
    interval = request.query.get('interval', '1h')
    try:
        async with aiohttp.ClientSession() as session:
            # Публичный эндпоинт BingX для свечей
            url = f"https://open-api.bingx.com/openApi/spot/v2/market/kline?symbol=BTC-USDT&interval={interval}&limit=100"
            async with session.get(url) as response:
                if response.status != 200:
                    return web.json_response({"error": "BingX API error"}, status=500)
                json_data = await response.json()
                
                # BingX возвращает данные в поле "data"
                if json_data.get("code") != 0:
                    return web.json_response({"error": json_data.get("msg", "BingX error")}, status=500)
                
                # Возвращаем массив свечей
                return web.json_response(json_data["data"])
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# Анализ для ИИ (тоже через BingX)
async def handle_analyze(request):
    try:
        data = await request.json()
        interval = data.get('interval', '1h')
    except:
        interval = '1h'

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://open-api.bingx.com/openApi/spot/v2/market/kline?symbol=BTC-USDT&interval={interval}&limit=100"
            async with session.get(url) as response:
                json_data = await response.json()
                if json_data.get("code") != 0:
                    return web.json_response({"analysis": f"❌ Ошибка BingX: {json_data.get('msg')}"}, status=500)

        # Извлекаем цены закрытия (close)
        klines = json_data["data"]
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1]
        
        rsi = calculate_rsi(closes)
        sma20 = calculate_sma(closes, 20)

        if rsi < 30 and current_price < sma20:
            verdict = "📈 <b>Перепроданность.</b> Ждем отскок. Рекомендация: <b>LONG</b>."
            color = "#00ff88"
        elif rsi > 70 and current_price > sma20:
            verdict = "📉 <b>Перекупленность.</b> Ждем коррекцию. Рекомендация: <b>SHORT</b>."
            color = "#ff3366"
        elif current_price > sma20:
            verdict = "🚀 <b>Бычий тренд.</b> Цена выше MA. Рост продолжается."
            color = "#00ff88"
        elif current_price < sma20:
            verdict = "⚠️ <b>Медвежий тренд.</b> Цена ниже MA. Падение продолжается."
            color = "#ff3366"
        else:
            verdict = "⚖️ <b>Флэт.</b> Рынок замер."
            color = "#00f0ff"

        analysis_html = f"""
            <div style="color: {color}; margin-bottom: 8px; font-size: 16px;">{verdict}</div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px;">
                📊 RSI: <b>{rsi:.2f}</b> | MA: <b>${sma20:,.2f}</b><br>
                💰 Цена: <b>${current_price:,.2f}</b>
            </div>
        """
        return web.json_response({"analysis": analysis_html})
    except Exception as e:
        return web.json_response({"analysis": f"❌ Ошибка: {str(e)}"}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/candles', handle_candles)
    app.router.add_post('/api/analyze', handle_analyze)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Сервер на порту {port}")

# --- БОТ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    import time
    base_url = os.getenv("WEBAPP_URL", "https://google.com")
    web_app_url = f"{base_url}?v={int(time.time())}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]
    ])
    await message.answer("Терминал обновлен. Жми кнопку!", reply_markup=keyboard)

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())