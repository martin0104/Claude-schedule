import json
import logging
import os
from datetime import datetime

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCHEDULES_FILE = os.path.join(os.path.dirname(__file__), "schedules.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Telegram 單則訊息上限
TG_MAX_LEN = 4096


def send_telegram_message(message: str) -> bool:
    """發送訊息，超過 4096 字自動分段"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [message[i:i + TG_MAX_LEN] for i in range(0, len(message), TG_MAX_LEN)]
    success = True
    for chunk in chunks:
        payload = {"chat_id": CHAT_ID, "text": chunk}
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("訊息發送成功: %s", chunk[:50])
        except requests.RequestException as e:
            logger.error("訊息發送失敗: %s", e)
            success = False
    return success


def make_sender(message: str):
    def _send():
        send_telegram_message(message)
    return _send


def run_stock_screener():
    """執行台股選股並將結果傳送至 Telegram"""
    logger.info("開始執行台股突破選股...")
    send_telegram_message("⏳ 台股選股開始執行，請稍候...")

    try:
        from stock_screener import run_and_get_report
        report = run_and_get_report(max_workers=15)
        send_telegram_message(report)
        logger.info("選股完成，報告已送出")
    except Exception as e:
        err_msg = f"❌ 選股執行失敗: {e}"
        logger.error(err_msg)
        send_telegram_message(err_msg)


def load_schedules(scheduler: BlockingScheduler):
    with open(SCHEDULES_FILE, encoding="utf-8") as f:
        schedules = json.load(f)

    for item in schedules:
        job_id = item["id"]
        message = item["message"]
        job_type = item["type"]

        if job_type == "cron":
            trigger = CronTrigger(
                hour=item.get("hour", 0),
                minute=item.get("minute", 0),
                second=item.get("second", 0),
            )
            scheduler.add_job(make_sender(message), trigger, id=job_id, replace_existing=True)
            logger.info(
                "已加入 cron 排程 [%s] 每天 %02d:%02d",
                job_id, item.get("hour", 0), item.get("minute", 0),
            )

        elif job_type == "once":
            run_at = datetime.strptime(item["run_at"], "%Y-%m-%d %H:%M:%S")
            if run_at <= datetime.now():
                logger.warning("排程 [%s] 的時間已過，跳過。", job_id)
                continue
            trigger = DateTrigger(run_date=run_at)
            scheduler.add_job(make_sender(message), trigger, id=job_id, replace_existing=True)
            logger.info("已加入一次性排程 [%s] 於 %s", job_id, run_at)

        else:
            logger.warning("未知排程類型 [%s]: %s", job_id, job_type)


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("請設定 .env 中的 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")

    scheduler = BlockingScheduler(timezone="Asia/Taipei")

    # ── 固定排程：每天 19:00 執行台股選股 ──
    scheduler.add_job(
        run_stock_screener,
        CronTrigger(hour=19, minute=0, timezone="Asia/Taipei"),
        id="daily_stock_screen",
        replace_existing=True,
    )
    logger.info("已加入台股選股排程：每天 19:00 (Asia/Taipei)")

    # ── schedules.json 自訂排程 ──
    load_schedules(scheduler)

    logger.info("排程系統啟動，共載入 %d 個排程。", len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("排程系統已停止。")


if __name__ == "__main__":
    main()
