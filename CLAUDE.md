# Stock Screener Routine

## 任務
每天執行台股突破選股，並將結果推送至 Telegram。

## 執行步驟
1. 安裝相依套件：`pip install -r requirements.txt`
2. 執行選股：`python stock_screener.py -o /tmp/report.txt`
3. 讀取 `/tmp/report.txt` 的內容
4. 用 requests 呼叫 Telegram Bot API 發送報告

## 環境變數
- `TELEGRAM_BOT_TOKEN`：Telegram bot token
- `TELEGRAM_CHAT_ID`：目標 chat ID

## 注意
- 執行完成後不需要 commit 任何檔案
- 如果選股失敗，發送錯誤訊息到 Telegram
