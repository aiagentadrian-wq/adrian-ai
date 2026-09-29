"""Opt-in trading research monitor. Run one cycle per invocation; no automatic email by default."""
import argparse
import asyncio
import hashlib
import json
from html import escape
import os
import sqlite3
import ssl
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import trading_division as td
import trading_lab as lab
import trading_chat_bridge as bridge
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
# Load local secrets only; never store SMTP credentials in GitHub.
for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines() if (ROOT / ".env").exists() else []:
    if line and not line.lstrip().startswith("#") and "=" in line:
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())
DB = ROOT / "trading_monitor.db"
TZ = ZoneInfo("America/Toronto")
RECIPIENT = os.getenv('REPORT_TO','')
INTERVAL_MINUTES = 15
MAX_ALERTS_PER_DAY = 2
ALERT_COOLDOWN_HOURS = 6

def now_local():
    return datetime.now(TZ)

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, at_utc TEXT NOT NULL, symbol TEXT NOT NULL, close REAL, candle_time TEXT, rsi REAL, source TEXT, payload TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, period TEXT NOT NULL, digest TEXT NOT NULL, at_utc TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(kind,period,digest))")
    return c

def symbols():
    # The existing application DB remains the source of truth for the watchlist.
    path = ROOT / "command_center.db"
    if not path.exists():
        return []
    try:
        with sqlite3.connect(path) as c:
            saved=[r[0] for r in c.execute("SELECT symbol FROM trading_watchlist ORDER BY added_utc DESC LIMIT 8")]
            configured=[s.strip().upper() for s in os.getenv('TRADING_UNIVERSE',bridge.DEFAULT_UNIVERSE).split(',') if lab.SYMBOL.fullmatch(s.strip().upper())]
            return list(dict.fromkeys(saved+configured))[:8]
    except sqlite3.Error:
        return []

async def collect(names):
    rows = []
    for symbol in names:
        entry = {"symbol": symbol, "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": []}
        try:
            market = await td.market(symbol, "1day", 100)
            candle = market["candles"][-1]
            metrics = lab.indicators(market["candles"])
            entry.update(source=market["source"], retrieved_utc=market["retrieved_utc"],
                         candle_time=candle["time"], last_candle_close=candle["close"],
                         metrics=metrics, feed_note=market.get("note", ""))
        except Exception as exc:
            entry["errors"].append("Market source unavailable: " + type(exc).__name__)
        try:
            news = await td.news(symbol)
            entry["news"] = news.get("articles", [])[:5]
        except Exception as exc:
            entry["errors"].append("News source unavailable: " + type(exc).__name__)
        rows.append(entry)
        await asyncio.sleep(.25)
    return rows

def record(rows):
    with connect() as c:
        for row in rows:
            if "last_candle_close" not in row:
                continue
            metrics = row.get("metrics", {})
            c.execute("INSERT INTO observations(at_utc,symbol,close,candle_time,rsi,source,payload) VALUES(?,?,?,?,?,?,?)",
                      (row["checked_utc"], row["symbol"], row["last_candle_close"], row["candle_time"],
                       metrics.get("rsi14"), row["source"], json.dumps(row, default=str)))

def format_report(kind, rows, local):
    heading = "Morning research" if kind == "morning" else "Next-day preparation" if kind == "next_day" else "Material market alert"
    lines = [heading + " | " + local.strftime("%Y-%m-%d %H:%M %Z"),
             "Research only. No trade instructions, guaranteed returns, or live executable quotes.",
             "Horizon: watch for the next session; multi-day or longer holding periods require separate verified analysis.",
             "Candidates are watchlist research subjects, not buy recommendations.", ""]
    if not rows:
        lines.append("Watchlist empty. Add tickers in Trading Division. No candidates were invented.")
    for row in rows:
        lines.append(row["symbol"] + " | checked UTC: " + row["checked_utc"])
        if "last_candle_close" in row:
            lines.append("Last returned candle close: " + str(row["last_candle_close"]) +
                         " | candle: " + str(row["candle_time"]) + " | retrieved UTC: " + row["retrieved_utc"] +
                         " | provider: " + row["source"])
            lines.append("Indicators: " + json.dumps(row.get("metrics", {}), default=str))
            lines.append("Why monitor: assess price trend and volatility against dated evidence; no directional conclusion is implied.")
            lines.append("Risks: stale feed, volatility, liquidity and event-driven price gaps. Recheck before acting.")
            lines.append("Feed limitation: " + row.get("feed_note", ""))
        for item in row.get("news", []):
            # Exclude unrelated broad-search hits; headlines are not verified facts.
            headline = (str(item.get("title") or "") + " " + str(item.get("description") or "")).lower()
            if row["symbol"].lower() not in headline and not any(term in headline for term in {"AAPL": ("apple", "iphone"), "MSFT": ("microsoft",), "AMD": ("advanced micro devices",), "SHOP": ("shopify",), "SOFI": ("sofi",), "PLTR": ("palantir",)}.get(row["symbol"], ())):
                continue
            lines.append("News: " + str(item.get("published_at")) + " | " + str(item.get("source")) +
                         " | " + str(item.get("title")) + " | " + str(item.get("url")))
        lines.extend(row["errors"])
        lines.append("")
    lines.append("Headlines are attributed publisher claims, not independent verification or market consensus.")
    lines.append("No trained ML forecast is implied. Verify events, company filings and source independence separately.")
    return "\n".join(lines)

def html_report(subject, body):
    """Email-safe HTML companion to the plain-text research report."""
    parts = []
    for line in body.splitlines():
        safe = escape(line)
        if not line.strip():
            parts.append('<div style="height:10px"></div>')
        elif ' | checked UTC:' in line:
            parts.append('<h2 style="color:#f1d49b;border-top:1px solid #494338;padding-top:18px">'+safe+'</h2>')
        elif line.startswith(('Last returned candle close:', 'Indicators:')):
            parts.append('<div style="padding:12px;background:#252b34;border-left:3px solid #d5ad65;margin:8px 0;overflow-wrap:anywhere">'+safe+'</div>')
        elif line.startswith('News: '):
            import re
            match = re.search(r'https://[^\\s]+', line)
            if match:
                safe = escape(line[:match.start()]) + ' <a style="color:#eac783" href="' + escape(match.group(0), quote=True) + '">Read source</a>'
            parts.append('<p style="border-bottom:1px solid #3b4149;padding-bottom:9px">'+safe+'</p>')
        else:
            parts.append('<p style="margin:8px 0">'+safe+'</p>')
    return ('<!doctype html><html><body style="background:#10151b;color:#e5e7eb;font:14px/1.6 Arial,sans-serif;margin:0">'
            '<div style="max-width:680px;margin:auto;padding:24px"><div style="border:1px solid #6c5430;border-radius:12px;overflow:hidden">'
            '<div style="background:#20252d;padding:24px;border-bottom:2px solid #d5ad65"><div style="color:#d5ad65;letter-spacing:2px;font-size:12px">ADRIAN.AI / TRADING INTELLIGENCE</div>'
            '<h1 style="font-size:25px;color:#fff;margin:8px 0">'+escape(subject)+'</h1></div>'
            '<div style="padding:22px;overflow-wrap:anywhere">'+''.join(parts)+'</div>'
            '<div style="padding:18px 22px;background:#20252d;color:#b7bec8;font-size:12px">Research only. No live orders or guaranteed returns. Verify dated source information.</div>'
            '</div></div></body></html>')

def send_email(subject, body):
    host, user, password, sender = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM"))
    if not all((host, user, password, sender)):
        raise RuntimeError("SMTP configuration missing; no email sent")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, RECIPIENT, subject
    message.set_content(body)
    message.add_alternative(html_report(subject, body), subtype='html')
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(user, password)
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("Recipient refused")

def deliver(kind, period, subject, body, allow_send):
    digest = hashlib.sha256(body.encode()).hexdigest()
    with connect() as c:
        existing = c.execute("SELECT status FROM deliveries WHERE kind=? AND period=? AND digest=?",
                             (kind, period, digest)).fetchone()
        if existing and existing["status"] == "sent":
            return "already sent"
        if not allow_send:
            return "preview only; no email sent"
        # Reserve before sending to prevent overlapping task invocations from double sending.
        try:
            c.execute("INSERT INTO deliveries(kind,period,digest,at_utc,status) VALUES(?,?,?,?,?)",
                      (kind, period, digest, datetime.now(timezone.utc).isoformat(), "pending"))
        except sqlite3.IntegrityError:
            return "existing delivery record; review before retry"
    try:
        send_email(subject, body)
    except Exception:
        with connect() as c:
            c.execute("UPDATE deliveries SET status='failed' WHERE kind=? AND period=? AND digest=?",
                      (kind, period, digest))
        raise
    with connect() as c:
        c.execute("UPDATE deliveries SET status='sent' WHERE kind=? AND period=? AND digest=?",
                  (kind, period, digest))
    return "sent"

def material_alerts(rows, local):
    # A dated daily candle change >= 5% is a transparent screening trigger,
    # not a verified cause or a trading recommendation. Never alert on stale candles.
    found = []
    for row in rows:
        if "last_candle_close" not in row:
            continue
        candle_date = str(row["candle_time"])[:10]
        if candle_date != local.date().isoformat():
            continue
        change = row.get("metrics", {}).get("change_1bar_pct")
        if isinstance(change, (float, int)) and abs(change) >= 5:
            found.append(row)
    return found

async def cycle(kind, allow_send=False, force=False):
    local = now_local()
    if kind == "monitor" and (local.weekday() >= 5 or not (local.replace(hour=9, minute=30, second=0, microsecond=0) <= local <= local.replace(hour=16, minute=0, second=0, microsecond=0))):
        return {"status": "outside regular US market hours; no email"}
    if kind in ("morning", "next_day") and local.weekday() >= 5 and not force:
        return {"status": "weekend; no scheduled report"}
    if kind in ('morning','next_day'):
        @contextmanager
        def research_db():
            with sqlite3.connect(ROOT/'command_center.db') as c:
                c.row_factory=sqlite3.Row
                yield c
        evidence=await bridge.research('Compare today\'s candidates',research_db)
        body=bridge.briefing(evidence).replace('**','')
        subject='ADRIAN.AI | '+('Morning comparison' if kind=='morning' else 'Next-session comparison')
        outcome=deliver(kind,local.date().isoformat(),subject,body,allow_send)
        return {'status':outcome,'email_sent':outcome=='sent','preview':body if not allow_send else None}
    rows = await collect(symbols())
    record(rows)
    if kind == "monitor":
        rows = material_alerts(rows, local)
        if not rows:
            return {"status": "observations saved; no qualifying alert", "email_sent": False}
        with connect() as c:
            since = (datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)).isoformat()
            today = local.date().isoformat()
            if c.execute("SELECT COUNT(*) FROM deliveries WHERE kind='alert' AND status IN ('pending','sent') AND period LIKE ?", (today + "%",)).fetchone()[0] >= MAX_ALERTS_PER_DAY:
                return {"status": "daily alert cap reached", "email_sent": False}
            rows = [r for r in rows if not c.execute("SELECT 1 FROM deliveries WHERE kind='alert' AND status IN ('pending','sent') AND period LIKE ? AND at_utc>=?", (today + ":" + r["symbol"] + "%", since)).fetchone()]
        if not rows:
            return {"status": "alert cooldown active", "email_sent": False}
        outcomes = []
        for row in rows:
            period = local.date().isoformat() + ":" + row["symbol"]
            body = format_report("alert", [row], local)
            outcomes.append(deliver("alert", period, "ADRIAN.AI | Material move: " + row["symbol"], body, allow_send))
        return {"status": outcomes, "email_sent": "sent" in outcomes}
    body = format_report(kind, rows, local)
    outcome = deliver(kind, local.date().isoformat(), "ADRIAN.AI | " + ("Morning research" if kind == "morning" else "Next-day preparation"), body, allow_send)
    return {"status": outcome, "email_sent": outcome == "sent", "preview": body if not allow_send else None}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("monitor", "morning", "next_day"))
    parser.add_argument("--send", action="store_true", help="Explicitly enable SMTP delivery after owner approval")
    parser.add_argument("--force", action="store_true", help="Preview scheduled reports on weekends")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(cycle(args.kind, args.send, args.force)), indent=2, default=str))
