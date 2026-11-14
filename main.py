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

# --- ФУНКЦИИ ДЛЯ РЕАЛЬНОГО АНАЛИЗА ---

# Расчет RSI (Индекса относительной силы)
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = 0, 0
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0: gains += diff
        else: losses -= diff
    
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# Расчет скользящей средней (SMA)
def calculate_sma(prices, period=20):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

# --- ВЕБ-СЕРВЕР ---

async def handle_index(request):
    return web.FileResponse('./index.html')

async def handle_analyze(request):
    try:
        # Получаем таймфрейм от клиента (по умолчанию 1h)
        data = await request.json()
        interval = data.get('interval', '1h')
    except:
        interval = '1h'

    try:
        # Идем на биржу Binance за реальными данными
        async with aiohttp.ClientSession() as session:
            url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit=100"
            async with session.get(url) as response:
                if response.status != 200:
                    return web.json_response({"error": "Ошибка Binance API"}, status=500)
                klines = await response.json()

        # Извлекаем цены закрытия (close)
        closes = [float(k[4]) for k in klines]
        current_price = closes[-1]
        
        # Считаем индикаторы
        rsi = calculate_rsi(closes)
        sma20 = calculate_sma(closes, 20)

        # Логика вердикта (Искусственный интеллект на правилах)
        if rsi < 30 and current_price < sma20:
            verdict = "📈 <b>Сильная перепроданность.</b> Возможен отскок. Рекомендация: <b>LONG</b>."
            color = "#00ff88"
        elif rsi > 70 and current_price > sma20:
            verdict = "📉 <b>Сильная перекупленность.</b> Высокий риск коррекции. Рекомендация: <b>SHORT</b>."
            color = "#ff3366"
        elif current_price > sma20:
            verdict = "🚀 <b>Бычий тренд.</b> Цена выше скользящей средней. Тренд вверх."
            color = "#00ff88"
        elif current_price < sma20:
            verdict = "⚠️ <b>Медвежий тренд.</b> Цена ниже скользящей средней. Тренд вниз."
            color = "#ff3366"
        else:
            verdict = "⚖️ <b>Флэт.</b> Рынок консолидируется. Лучше подождать."
            color = "#00f0ff"

        # Формируем красивый ответ для фронтенда
        analysis_html = f"""
            <div style="color: {color}; margin-bottom: 8px; font-size: 16px;">{verdict}</div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 8px;">
                📊 RSI (14): <b>{rsi:.2f}</b><br>
                📉 MA (20): <b>${sma20:,.2f}</b><br>
                💰 Текущая цена: <b>${current_price:,.2f}</b>
            </div>
        """

        return web.json_response({"analysis": analysis_html})

    except Exception as e:
        print(f"Ошибка при анализе: {e}")
        return web.json_response({"analysis": f"❌ Ошибка сервера: {str(e)}"}, status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/analyze', handle_analyze)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")

# --- ТЕЛЕГРАМ БОТ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    import time
    base_url = os.getenv("WEBAPP_URL", "https://google.com")
    web_app_url = f"{base_url}?v={int(time.time())}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]
    ])
    
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        "Терминал обновлен. Теперь сервер делает реальный анализ 24/7.",
        reply_markup=keyboard
    )

async def main():
    await start_web_server()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())