import asyncio
import base64
import hmac
import hashlib
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, time as dt_time

import mysql.connector
import requests
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from config.env import st
# Local fixed column schema (decoupled from other modules)
EXTENDED_COLUMNS = [
    "action", "date", "dstcountry", "dstip", "dstport",
    "eventtype", "ipaddr", "msg", "srccountry", "srcip",
    "utmtype", "time", "user", "category", "hostname",
    "service", "url", "httpagent", "level", "threat"
]


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "mhe_email.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="MHE Email Service")


def _sign(payload: Dict, secret: str) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(data + b"." + sig).decode("utf-8")
    return token


def _unsign(token: str, secret: str) -> Optional[Dict]:
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        data, _, sig = raw.rpartition(b".")
        good = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def send_email_smtp(to_emails: List[str], subject: str, body: str) -> bool:
    """Send email via SMTP (supports SSL/TLS/plain)"""
    if not to_emails:
        logger.warning("No recipients provided")
        return False
    
    try:
        # Use EmailMessage for simpler API
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content(body)
        msg["From"] = st.SMTP_FROM
        msg["To"] = ", ".join(to_emails)
        msg["Subject"] = subject
        
        # Choose SMTP mode
        if getattr(st, "SMTP_USE_SSL", False):
            server = smtplib.SMTP_SSL(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
        else:
            server = smtplib.SMTP(st.SMTP_HOST, st.SMTP_PORT, timeout=getattr(st, "SMTP_TIMEOUT", 10))
            if st.SMTP_USE_TLS:
                server.starttls()
        
        if st.SMTP_USER and st.SMTP_PASSWORD:
            server.login(st.SMTP_USER, st.SMTP_PASSWORD)
        
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent to {to_emails}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_emails}: {e}")
        return False


def query_utmlogs_by_user_and_day(login: str, date_start: datetime, date_end: datetime) -> List[Tuple]:
    try:
        cnx = mysql.connector.connect(**st.mysql_config)
        cursor = cnx.cursor()
        # Select all columns from EXTENDED_COLUMNS
        cols_sql = ", ".join([f"`{c}`" for c in EXTENDED_COLUMNS])
        cursor.execute(
            f"""
            SELECT {cols_sql}
            FROM UTMLogs
            WHERE `user` = %s AND STR_TO_DATE(CONCAT(`date`, ' ', `time`), '%Y-%m-%d %H:%i:%s') BETWEEN %s AND %s
            ORDER BY `date` ASC, `time` ASC
            """,
            (login, date_start, date_end),
        )
        rows = cursor.fetchall()
        cursor.close()
        cnx.close()
        return rows
    except Exception as e:
        logger.error(f"DB query failed for {login}: {e}")
        return []


def render_html_table(rows: List[Tuple]) -> str:
    if not rows:
        return "<p>No records</p>"
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{(c if c is not None else '')}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table border='1' cellpadding='4' cellspacing='0'><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def gen_csv(rows: List[Tuple]) -> str:
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXTENDED_COLUMNS)
    for row in rows:
        writer.writerow([c if c is not None else "" for c in row])
    return output.getvalue()


def gen_excel(rows: List[Tuple]) -> bytes:
    # HTML-based .xls that Excel/LibreOffice open without python deps
    thead = "".join(f"<th>{h}</th>" for h in EXTENDED_COLUMNS)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{(c if c is not None else '')}</td>" for c in row) + "</tr>"
        for row in rows
    )
    html = f"""<html><head><meta charset='UTF-8'></head>
<body><table border='1'><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></body></html>"""
    return html.encode("utf-8")


def render_html_page(login: str, date_str: str, rows: List[Tuple], token: str) -> str:
    download_csv_url = f"/download/csv?token={token}"
    download_xlsx_url = f"/download/excel?token={token}"
    controls = (
        f"<div class=\"controls\">"
        f"<a class=\"btn\" href=\"{download_csv_url}\">Скачать CSV</a>"
        f"<a class=\"btn btn-primary\" href=\"{download_xlsx_url}\">Скачать Excel</a>"
        f"</div>"
    )
    table_html = render_html_table(rows)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset=\"UTF-8\" />
  <title>Отчёт для {login}</title>
  <link rel=\"stylesheet\" href=\"/static/report.css\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <style>/* fallback minimal styles if CSS missing */ body{{font-family:Arial,Helvetica,sans-serif;margin:20px}}</style>
  </head>
<body>
  <h2>Отчёт о событиях безопасности для {login} ({date_str})</h2>
  {controls}
  {table_html}
</body>
</html>"""


def calculate_next_run_time() -> datetime:
    """Calculate next scheduled run time at 08:00 system local time."""
    target_time = dt_time(8, 0)
    now = datetime.now()
    next_run = datetime.combine(now.date(), target_time)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


def send_daily_reports() -> Dict:
    """Для каждого пользователя проверяем логи за вчера 08:00 + 24 часа.
    Если логов нет — письмо о том, что событий нет. Если логи есть — письмо с шифр. ссылкой.
    """
    today_local = datetime.now().date()
    window_start = datetime.combine(today_local - timedelta(days=1), dt_time(8, 0))
    window_end = window_start + timedelta(days=1)
    yesterday_str = (today_local - timedelta(days=1)).strftime("%Y-%m-%d")

    # Fetch logins+emails from LDAP service
    try:
        ldap_url = f"http://{st.MHE_LDAP_HOST}:{st.MHE_LDAP_PORT}/list"
        resp = requests.get(ldap_url, timeout=10)
        payload = resp.json() if resp.ok else {"users": []}
        user_items = payload.get("users", [])
    except Exception as e:
        logger.error(f"LDAP list request failed: {e}")
        user_items = []

    sent: Dict[str, str] = {}
    for item in user_items:
        login = str(item.get("login", "")).strip()
        emails = [str(x).strip() for x in item.get("emails", []) if str(x).strip()]
        if not login or not emails:
            continue

        rows = query_utmlogs_by_user_and_day(login, window_start, window_end)
        if not rows:
            subject = f"[UTM] Нет событий безопасности за {yesterday_str}"
            body = f"События безопасности для абонента {login} за {yesterday_str} отсутствуют."
            if send_email_smtp(emails, subject, body):
                sent[login] = subject
            else:
                logger.error(f"Failed to send 'no events' email to {login}")
            continue

        token = _sign({"login": login, "date": yesterday_str}, st.EMAIL_TOKEN)
        report_url = f"http://{st.MHE_EMAIL_HOST}:{st.MHE_EMAIL_PORT}/report?token={token}"
        subject = f"[UTM] Отчёт о событиях безопасности за {yesterday_str}"
        body = f"Отчёт о событиях безопасности для абонента {login} за {yesterday_str}: {report_url}"

        if send_email_smtp(emails, subject, body):
            sent[login] = subject
        else:
            logger.error(f"Failed to send report link to {login}")

    return {"date": yesterday_str, "processed": len(user_items), "sent": sent}


async def daily_report_scheduler():
    """Background task that sends reports daily at scheduled time"""
    logger.info("Daily report scheduler started")
    
    # First run immediately on startup
    logger.info("Sending reports on startup...")
    try:
        result = send_daily_reports()
        logger.info(f"Startup report sent: {result}")
    except Exception as e:
        logger.error(f"Error sending startup reports: {e}")
    
    # Then schedule daily runs
    while True:
        try:
            next_run = calculate_next_run_time()
            wait_seconds = (next_run - datetime.now()).total_seconds()
            logger.info(f"Next report scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S')} (in {wait_seconds:.0f} seconds)")
            
            await asyncio.sleep(wait_seconds)
            
            logger.info("Sending scheduled daily reports...")
            result = send_daily_reports()
            logger.info(f"Daily reports sent: {result}")
        except Exception as e:
            logger.error(f"Error in daily scheduler: {e}")
            await asyncio.sleep(60)  # Retry in 1 minute on error


# Note: When running via uvicorn CLI (e.g., `uvicorn core.mhe_email:app`),
# you may want to enable the scheduler via a startup hook. In this module,
# we explicitly run server and scheduler in parallel under __main__.


@app.get("/report", response_class=HTMLResponse)
def report(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload:
        return HTMLResponse("<h3>Invalid token</h3>", status_code=400)
    login = payload.get("login")
    date_str = payload.get("date")  # YYYY-MM-DD
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return HTMLResponse("<h3>Invalid date</h3>", status_code=400)

    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    html_table = render_html_table(rows)
    return HTMLResponse(f"<h2>Report for {login} ({date_str})</h2>" + html_table)


@app.get("/download/csv")
def download_csv(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload:
        return JSONResponse({"error": "invalid token"}, status_code=400)
    login = payload.get("login")
    date_str = payload.get("date")
    day = datetime.strptime(date_str, "%Y-%m-%d")
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    csv_text = gen_csv(rows)
    return StreamingResponse(iter([csv_text.encode("utf-8")]), media_type="text/csv")

@app.get("/download/excel")
def download_excel(token: str = Query(...)):
    payload = _unsign(token, st.EMAIL_TOKEN)
    if not payload:
        return JSONResponse({"error": "invalid token"}, status_code=400)
    login = payload.get("login")
    date_str = payload.get("date")
    day = datetime.strptime(date_str, "%Y-%m-%d")
    rows = query_utmlogs_by_user_and_day(login, day, day + timedelta(days=1))
    data = gen_excel(rows)
    return StreamingResponse(iter([data]), media_type="application/vnd.ms-excel", headers={
        "Content-Disposition": f"attachment; filename=utm_report_{login}_{date_str}.xls"
    })

@app.get("/health")
def health():
    return {"status": "ok", "service": "mhe_email"}

if __name__ == "__main__":
    import uvicorn
    import asyncio

    async def _run():
        # Run uvicorn server and daily scheduler in parallel
        config = uvicorn.Config(app, host="0.0.0.0", port=80, log_config=None, loop="asyncio")
        server = uvicorn.Server(config)

        server_task = asyncio.create_task(server.serve())
        scheduler_task = asyncio.create_task(daily_report_scheduler())

        done, pending = await asyncio.wait(
            {server_task, scheduler_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        # Cancel the other task if one finishes/errors
        for t in pending:
            t.cancel()

    asyncio.run(_run())


