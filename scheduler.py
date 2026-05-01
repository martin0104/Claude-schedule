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
)
logger = logging.getLogger(__name__)


def send_telegram_message(message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("訊息發送成功: %s", message[:50])
        return True
    except requests.RequestException as e:
        logger.error("訊息發送失敗: %s", e)
        return False


def make_sender(message: str):
    def _send():
        send_telegram_message(message)
    return _send


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
            logger.info("已加入 cron 排程 [%s] 每天 %02d:%02d", job_id, item.get("hour", 0), item.get("minute", 0))

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
    load_schedules(scheduler)

    logger.info("排程系統啟動，共載入 %d 個排程。", len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("排程系統已停止。")


if __name__ == "__main__":
    main()
