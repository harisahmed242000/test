#!/usr/bin/env python3
"""
Email Warmer
============

Gradually builds sender reputation for a pool of mailboxes you own by
sending a slowly-increasing volume of mail between them, then having the
recipient side read/reply/rescue-from-spam like a real inbox would.

Usage:
    python warmer.py --run          # one pass: maybe send, always process inboxes
    python warmer.py --status       # show current ramp day / targets / counts
    python warmer.py --reset-today  # zero out today's sent counters (testing)

Intended to be invoked every 15-30 minutes via cron. Each invocation makes
an independent, randomized decision — it does not loop or sleep internally,
so it stays safe to run from cron without overlapping long-running jobs.

IMPORTANT:
  - Only ever list mailboxes you own / are authorized to use.
  - This sends real email. Start with base_daily_volume low.
  - Respect the receiving providers' ToS and anti-abuse rules.
"""

import argparse
import datetime
import email
import email.mime.text
import imaplib
import json
import logging
import os
import random
import smtplib
import sys
import time

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "templates"))
import content  # noqa: E402

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
WARMER_HEADER = "X-Warmer-Pool"  # custom header to identify our own traffic


# --------------------------------------------------------------------------- #
# Config / state
# --------------------------------------------------------------------------- #

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"Missing config.yaml — copy config.example.yaml to config.yaml first.")
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_state(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"per_account": {}}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def today_str():
    return datetime.date.today().isoformat()


def account_role(account):
    """Explicit role if set, else infer from which credential fields exist."""
    role = account.get("role")
    if role:
        return role
    has_smtp = bool(account.get("smtp_host"))
    has_imap = bool(account.get("imap_host"))
    if has_smtp and has_imap:
        return "both"
    if has_smtp:
        return "sender"
    if has_imap:
        return "receiver"
    sys.exit(f"Account {account.get('email')} has neither smtp_host nor imap_host set.")


def get_senders(accounts):
    return [a for a in accounts if account_role(a) in ("sender", "both")]


def get_receivers(accounts):
    return [a for a in accounts if account_role(a) in ("receiver", "both")]


def can_reply(account):
    """A receiver can only send a reply if it also has SMTP creds."""
    return bool(account.get("smtp_host"))


def get_account_state(state, email_addr):
    acc = state["per_account"].setdefault(
        email_addr, {"date": today_str(), "sent_today": 0, "total_sent": 0}
    )
    if acc["date"] != today_str():
        acc["date"] = today_str()
        acc["sent_today"] = 0
    return acc


# --------------------------------------------------------------------------- #
# Ramp schedule
# --------------------------------------------------------------------------- #

def ramp_target_for_today(settings):
    start = datetime.date.fromisoformat(settings["start_date"])
    days_elapsed = max(0, (datetime.date.today() - start).days)
    target = settings["base_daily_volume"] + days_elapsed * settings["daily_increment"]
    return min(target, settings["max_daily_volume"])


def in_business_hours(settings):
    offset = datetime.timedelta(hours=settings.get("timezone_offset_hours", 0))
    local_hour = (datetime.datetime.utcnow() + offset).hour
    return settings["business_hour_start"] <= local_hour < settings["business_hour_end"]


# --------------------------------------------------------------------------- #
# Message construction
# --------------------------------------------------------------------------- #

def build_message(sender_email, recipient_email):
    subject = random.choice(content.SUBJECTS)
    body = "\n\n".join([
        random.choice(content.OPENERS),
        random.choice(content.BODY_LINES),
        f"{random.choice(content.CLOSERS)}\n{sender_email.split('@')[0].title()}",
    ])
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg[WARMER_HEADER] = "1"  # lets our own IMAP pass recognize pool mail
    return msg


def build_reply(original_msg, sender_email, recipient_email):
    subject = original_msg.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    body = random.choice(content.REPLY_LINES)
    msg = email.mime.text.MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["In-Reply-To"] = original_msg.get("Message-ID", "")
    msg[WARMER_HEADER] = "1"
    return msg


# --------------------------------------------------------------------------- #
# SMTP / IMAP actions
# --------------------------------------------------------------------------- #

def send_smtp(account, msg):
    host, port = account["smtp_host"], account["smtp_port"]
    if account.get("smtp_use_ssl"):
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    try:
        server.login(account["smtp_username"], account["smtp_password"])
        server.sendmail(account["email"], [msg["To"]], msg.as_string())
    finally:
        server.quit()


def imap_connect(account):
    conn = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"])
    conn.login(account["imap_username"], account["imap_password"])
    return conn


def process_inbox(account, pool_emails, settings, logger):
    """Mark pool mail as read, reply to some of it."""
    try:
        conn = imap_connect(account)
    except Exception as e:
        logger.error(f"[{account['email']}] IMAP connect failed: {e}")
        return

    try:
        conn.select("INBOX")
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            return
        for num in data[0].split():
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            parsed = email.message_from_bytes(raw)
            from_addr = email.utils.parseaddr(parsed.get("From", ""))[1]

            is_pool_mail = from_addr in pool_emails or parsed.get(WARMER_HEADER) == "1"
            if not is_pool_mail:
                continue

            if random.random() < settings.get("mark_read_probability", 0.9):
                conn.store(num, "+FLAGS", "\\Seen")
                logger.info(f"[{account['email']}] marked read: msg from {from_addr}")

            if can_reply(account) and random.random() < settings.get("reply_probability", 0.3):
                time.sleep(random.uniform(1, 4))  # small human-like delay
                reply = build_reply(parsed, account["email"], from_addr)
                try:
                    send_smtp(account, reply)
                    logger.info(f"[{account['email']}] replied to {from_addr}")
                except Exception as e:
                    logger.error(f"[{account['email']}] reply send failed: {e}")
    finally:
        conn.logout()


def rescue_from_spam(account, pool_emails, settings, logger):
    """Move pool mail found in Spam/Junk back to Inbox — the single most
    useful signal for teaching a provider 'this sender is wanted'."""
    try:
        conn = imap_connect(account)
    except Exception as e:
        logger.error(f"[{account['email']}] IMAP connect failed (spam check): {e}")
        return

    try:
        typ, folders = conn.list()
        existing_folders = set()
        if typ == "OK":
            for line in folders:
                decoded = line.decode(errors="ignore")
                existing_folders.add(decoded.split('"')[-2] if '"' in decoded else decoded.split()[-1])

        for folder in settings.get("spam_folders", []):
            if existing_folders and folder not in existing_folders:
                continue
            typ, _ = conn.select(f'"{folder}"')
            if typ != "OK":
                continue
            typ, data = conn.search(None, "ALL")
            if typ != "OK":
                continue
            for num in data[0].split():
                typ, msg_data = conn.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                parsed = email.message_from_bytes(msg_data[0][1])
                from_addr = email.utils.parseaddr(parsed.get("From", ""))[1]
                if from_addr in pool_emails or parsed.get(WARMER_HEADER) == "1":
                    conn.copy(num, "INBOX")
                    conn.store(num, "+FLAGS", "\\Deleted")
                    logger.info(f"[{account['email']}] rescued from {folder}: {from_addr}")
            conn.expunge()
    finally:
        conn.logout()


# --------------------------------------------------------------------------- #
# Main run
# --------------------------------------------------------------------------- #

def setup_logger(path):
    logger = logging.getLogger("warmer")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(path)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger


def run_once(config):
    settings = config["settings"]
    accounts = config["accounts"]
    pool_emails = {a["email"] for a in accounts}
    senders = get_senders(accounts)
    receivers = get_receivers(accounts)
    logger = setup_logger(settings.get("log_file", "warmer.log"))
    state = load_state(settings.get("state_file", "state.json"))

    if not senders:
        logger.error("No sender accounts configured (role: sender/both) — nothing to send.")
    if not receivers:
        logger.error("No receiver accounts configured (role: receiver/both) — nothing to receive into.")

    if not in_business_hours(settings):
        logger.info("Outside business-hour window — skipping sends, still checking inboxes.")
    elif senders and receivers:
        target = ramp_target_for_today(settings)
        hours_in_window = settings["business_hour_end"] - settings["business_hour_start"]
        # Rough probability per invocation so volume spreads across the window
        # rather than firing all at once. Assumes ~3 invocations/hour (20-min cron).
        invocations_remaining_estimate = max(1, hours_in_window * 3)

        for sender in senders:
            acc_state = get_account_state(state, sender["email"])
            remaining = target - acc_state["sent_today"]
            if remaining <= 0:
                continue
            send_prob = min(1.0, remaining / invocations_remaining_estimate)
            if random.random() > send_prob:
                continue

            # Recipient is any receiver other than the sender itself
            # (relevant when an account has role "both").
            candidates = [r for r in receivers if r["email"] != sender["email"]]
            if not candidates:
                continue
            recipient = random.choice(candidates)
            msg = build_message(sender["email"], recipient["email"])
            try:
                send_smtp(sender, msg)
                acc_state["sent_today"] += 1
                acc_state["total_sent"] += 1
                logger.info(
                    f"[{sender['email']}] sent to {recipient['email']} "
                    f"({acc_state['sent_today']}/{target} today)"
                )
            except Exception as e:
                logger.error(f"[{sender['email']}] send failed: {e}")

        save_state(settings.get("state_file", "state.json"), state)

    # Always process receiver inboxes, regardless of send window.
    # (Sender-only accounts like a Mailgun domain have no mailbox to check.)
    for receiver in receivers:
        process_inbox(receiver, pool_emails, settings, logger)
        rescue_from_spam(receiver, pool_emails, settings, logger)


def print_status(config):
    settings = config["settings"]
    state = load_state(settings.get("state_file", "state.json"))
    target = ramp_target_for_today(settings)
    start = datetime.date.fromisoformat(settings["start_date"])
    days_elapsed = max(0, (datetime.date.today() - start).days)
    print(f"Ramp day: {days_elapsed}  |  Today's per-account target: {target}")
    for account in config["accounts"]:
        acc_state = get_account_state(state, account["email"])
        print(f"  {account['email']}: {acc_state['sent_today']}/{target} sent today, "
              f"{acc_state['total_sent']} all-time")


def reset_today(config):
    settings = config["settings"]
    state = load_state(settings.get("state_file", "state.json"))
    for email_addr in state["per_account"]:
        state["per_account"][email_addr]["sent_today"] = 0
        state["per_account"][email_addr]["date"] = today_str()
    save_state(settings.get("state_file", "state.json"), state)
    print("Today's counters reset.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--reset-today", action="store_true")
    args = parser.parse_args()

    cfg = load_config()

    if args.run:
        run_once(cfg)
    elif args.status:
        print_status(cfg)
    elif args.reset_today:
        reset_today(cfg)
