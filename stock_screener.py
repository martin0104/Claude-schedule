if __name__ == "__main__":
    import os
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("請設定 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")

    def send_telegram(message: str):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        TG_MAX_LEN = 4096
        chunks = [message[i:i + TG_MAX_LEN] for i in range(0, len(message), TG_MAX_LEN)]
        for chunk in chunks:
            try:
                resp = requests.post(url, json={"chat_id": CHAT_ID, "text": chunk}, timeout=10)
                resp.raise_for_status()
            except requests.RequestException as e:
                log.error("Telegram 發送失敗: %s", e)

    send_telegram("⏳ 台股選股開始執行，請稍候...")

    try:
        report = run_and_get_report(max_workers=15)
        send_telegram(report)
    except Exception as e:
        send_telegram(f"❌ 選股執行失敗: {e}")
