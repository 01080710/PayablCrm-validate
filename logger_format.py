from zoneinfo import ZoneInfo
from datetime import datetime
import logging ,json ,sys
import time ,uuid

class JsonFormatter(logging.Formatter):
    """
    將 LogRecord 轉成 JSON，支援動態 extra fields。
    """
    def format(self, record):

        log_record = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        reserved = logging.LogRecord("", "", "", "", "", "", "", "").__dict__.keys()

        for key, value in record.__dict__.items():
            if key not in reserved:
                log_record[key] = value

        return json.dumps(log_record, ensure_ascii=False)


# ---------- Adapter（支援 extra merge）----------
class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        merged = {**self.extra, **extra}
        kwargs["extra"] = merged
        return msg, kwargs

    # ---------- 商業友善 log ----------
    def ok(self, msg, **extra):
        self.info(msg, extra={**extra, "status": "ok"})

    def fail(self, msg, **extra):
        self.error(msg, extra={**extra, "status": "fail"})

    def metric(self, msg, **extra):
        self.info(msg, extra=extra)


# ---------- Timer ----------
class LogTimer:
    """
    用於自動計算 duration
    """
    def __init__(self, logger, action):
        self.logger = logger
        self.action = action

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = round(time.time() - self.start, 2)
        if exc_type:
            self.logger.fail(
                f"{self.action} failed",
                duration=duration,
                error=str(exc_val)
            )
        else:
            self.logger.ok(
                f"{self.action} success",
                duration=duration
            )


# ---------- Logger Factory ----------
def get_logger(
    service: str = "etl",
    stage: str = "local",
    run_id: str = None,
    env: str = "prod",
):

    if run_id is None:
        run_id = (
            datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d%H%M%S")
            + "-" + str(uuid.uuid4())[:8]
        )

    logger = logging.getLogger("etl_logger")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    context = {
        "service": service,
        "stage": stage,
        "run_id": run_id,
        "env": env,
        "status": "ok",
    }

    return ContextAdapter(logger, context)



# Test Collection
logger = get_logger(service="cc_reconcile", stage="download")
logger.ok("Start download reports")
logger.metric('Davinci Retry',counts=3 ,total_counts =10)
logger.metric(
    "Payabl download complete",
    source="payabl"
)