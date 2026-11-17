#!/usr/bin/env python3
"""
Phishing Campaign Sender — Mailgun batch send with per-recipient personalisation.
Credential capture is handled by Spearhook at tms.5thpilartakafull.com.
Tracking (opens + clicks) is handled by Mailgun — view results in Mailgun Analytics.

Usage:
  python3 send_campaign.py recipients.csv
  python3 send_campaign.py recipients.csv --dry-run
  python3 send_campaign.py recipients.csv --api-key mg-key-xxxx

CSV format (header required):
  email,first_name,deadline_date
  haris.ahmed@5thpillartakaful.com,Haris,30-11-2026
  sara.khan@5thpillartakaful.com,Sara,30-11-2026
"""

import csv
import sys
import time
import json
import argparse
import requests
from pathlib import Path
from datetime import datetime

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
MAILGUN_API_KEY  = "YOUR_MAILGUN_API_KEY_HERE"   # replace before running
MAILGUN_DOMAIN   = "5thpilartakafull.com"
SENDER_NAME      = "HR Department"
SENDER_EMAIL     = f"info@{MAILGUN_DOMAIN}"
SUBJECT          = "Action Required: Q4 2026 Fuel Allowance — Identity Verification"
LANDING_URL      = "https://tms.5thpilartakafull.com/login"
DEFAULT_DEADLINE = "30-11-2026"
BATCH_SIZE       = 50    # recipients per Mailgun API call (max 1000, 50 is safe)
DELAY_SECONDS    = 2     # pause between batches to avoid rate limits
# ──────────────────────────────────────────────────────────────────────────────

EMAIL_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body{margin:0;padding:20px;background-color:#f4f4f4;}
  .wrapper{max-width:620px;margin:0 auto;background:#ffffff;border:1px solid #e0e0e0;
           font-family:Calibri,'Segoe UI',Arial,sans-serif;font-size:14px;color:#333;}
  .hdr{background-color:#1a3a5c;padding:20px 30px;text-align:center;}
  .hdr h2{color:#fff;margin:0;font-size:17px;font-weight:bold;}
  .hdr p{color:#f4c842;margin:6px 0 0;font-size:13px;}
  .body{padding:30px;line-height:1.7;}
  .body p{margin:0 0 14px 0;}
  .btn{display:inline-block;background-color:#f4a300;color:#000!important;
       text-decoration:none;padding:13px 32px;border-radius:4px;
       font-weight:bold;font-size:14px;margin:10px 0 20px;}
  .notice{background:#fdf6ec;border-left:4px solid #f4a300;
          padding:14px 16px;margin:20px 0;font-size:13px;color:#555;}
  .tbl{width:100%;border-collapse:collapse;font-size:13px;margin:16px 0;}
  .tbl td{padding:8px 12px;border:1px solid #e0e0e0;}
  .tbl td:first-child{background:#f9f9f9;font-weight:bold;width:40%;color:#444;}
  .red{font-weight:bold;color:#c0392b;}
  hr{border:none;border-top:1px solid #e0e0e0;margin:24px 0;}
  .sig{border-collapse:collapse;width:100%;}
  .sig-logo{padding-right:20px;border-right:1px solid #ccc;vertical-align:top;
            text-align:center;width:130px;}
  .sig-logo img{width:110px;height:auto;display:block;margin:0 auto;}
  .sig-det{padding-left:20px;vertical-align:top;}
  .sig-name{font-size:15px;font-weight:bold;color:#1a1a1a;margin-bottom:4px;}
  .sig-title{font-size:13px;color:#555;margin-bottom:10px;}
  .sig-row{font-size:12px;margin-bottom:5px;color:#333;}
  .sig-row a{color:#1155cc;text-decoration:underline;}
  .lbl{font-weight:bold;text-decoration:underline;}
  .tel{font-weight:bold;text-decoration:underline;color:#777;}
  .ftr{background:#f9f9f9;padding:12px 30px;text-align:center;
       font-size:11px;color:#999;border-top:1px solid #e0e0e0;}
</style>
</head>
<body>
<div class="wrapper">
  <div class="hdr">
    <h2>&#9981;&nbsp; Q4 2026 Fuel Allowance &mdash; Identity Verification Required</h2>
    <p>HR &amp; Payroll Department &nbsp;|&nbsp; 5th Pillar Family Takaful Limited</p>
  </div>
  <div class="body">
    <p>Dear %recipient.first_name%,</p>
    <p>We are pleased to inform you that the <strong>Q4 2026 Fuel Allowance</strong>
    disbursement has been approved for eligible staff members. To process your allowance,
    the Payroll team is required to verify your identity details against HR records.</p>
    <div class="notice">
      &#9888;&#65039; <strong>Action Required by
      <span class="red">%recipient.deadline%</span>:</strong>
      Please complete the identity verification using the link below. Employees who do
      not verify before the deadline will not be included in this disbursement cycle
      and will need to reapply next quarter.
    </div>
    <p>Please have the following ready before clicking the link:</p>
    <table class="tbl">
      <tr><td>Employee ID</td><td>Your TMS Employee ID (e.g. EMP-00123)</td></tr>
      <tr><td>CNIC Number</td><td>13-digit National Identity Card number (without dashes)</td></tr>
    </table>
    <p style="text-align:center;margin-top:24px;">
      <a href="__LANDING_URL__" class="btn">
        &#9981;&nbsp; Verify Identity &amp; Claim Allowance &rarr;
      </a>
    </p>
    <p>The verification takes less than two minutes. Your allowance will be processed
    within <strong>3&ndash;5 working days</strong> of a successful submission.</p>
    <p>If you have any questions, please contact the HR team directly by phone or
    in person. <strong>Do not reply to this email</strong> &mdash; this mailbox
    is not monitored.</p>
    <p>Thank you for your cooperation.</p>
    <p>Warm regards,<br>
    <strong>HR &amp; Payroll Department</strong><br>
    5th Pillar Family Takaful Limited</p>
    <hr>
    <table class="sig" cellpadding="0" cellspacing="0">
      <tr>
        <td class="sig-logo">
          <img src="https://5thpilartakafull.com/assets/images/logos/logo_email.png"
               alt="5th Pillar Family Takaful">
        </td>
        <td class="sig-det">
          <div class="sig-name">Muhammad Zyad Akhter</div>
          <div class="sig-title">Manager IT Infrastructure</div>
          <div class="sig-row"><span class="lbl">Address:</span>
            Suite # 01-06, Second Floor, Emerald Tower, Clifton 5, Karachi</div>
          <div class="sig-row"><span class="tel">Tel:</span> 021-36492824</div>
          <div class="sig-row"><span class="lbl">Email:</span>
            <a href="mailto:ziyad.akhter@5thpillartakaful.com">
              ziyad.akhter@5thpillartakaful.com</a></div>
          <div class="sig-row"><span class="lbl">Website:</span>
            <a href="https://5thpillartakaful.com">5thpillartakaful.com</a></div>
        </td>
      </tr>
    </table>
  </div>
  <div class="ftr">
    This email and any attachments are confidential and intended solely for the
    named recipient(s).<br>
    &copy; 2026 5th Pillar Family Takaful Limited. All rights reserved.
  </div>
</div>
</body>
</html>
"""


def load_recipients(csv_path: str) -> list:
    """
    Load and validate recipients from CSV.
    Required columns: email, first_name
    Optional column:  deadline_date  (falls back to DEFAULT_DEADLINE)
    """
    recipients = []
    errors = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Validate headers
        required = {"email", "first_name"}
        if not required.issubset(set(reader.fieldnames or [])):
            print(f"[ERROR] CSV must have columns: email, first_name")
            print(f"        Found: {reader.fieldnames}")
            sys.exit(1)

        for i, row in enumerate(reader, start=2):  # start=2 (row 1 = header)
            email      = row.get("email", "").strip().lower()
            first_name = row.get("first_name", "").strip()
            deadline   = row.get("deadline_date", "").strip() or DEFAULT_DEADLINE

            if not email:
                errors.append(f"  Row {i}: missing email — skipped")
                continue
            if "@" not in email:
                errors.append(f"  Row {i}: invalid email '{email}' — skipped")
                continue
            if not first_name:
                errors.append(f"  Row {i}: missing first_name for {email} — skipped")
                continue

            recipients.append({
                "email":      email,
                "first_name": first_name,
                "deadline":   deadline,
            })

    if errors:
        print(f"\n[!] {len(errors)} row(s) skipped:")
        for e in errors:
            print(e)

    return recipients


def send_batch(batch: list, html: str, dry_run: bool) -> dict:
    """
    Send one batch via Mailgun batch send API.
    recipient-variables enables per-recipient %recipient.KEY% substitution.
    """
    to_list = [r["email"] for r in batch]

    recipient_vars = {
        r["email"]: {
            "first_name": r["first_name"],
            "deadline":   r["deadline"],
        }
        for r in batch
    }

    if dry_run:
        for r in batch:
            print(f"    [DRY] {r['email']} — Dear {r['first_name']}, deadline {r['deadline']}")
        return {"dry_run": True}

    resp = requests.post(
        f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
        auth=("api", MAILGUN_API_KEY),
        data={
            "from":                f"{SENDER_NAME} <{SENDER_EMAIL}>",
            "to":                  to_list,
            "subject":             SUBJECT,
            "html":                html,
            "recipient-variables": json.dumps(recipient_vars),
            # Mailgun tracking
            "o:tracking":          "yes",
            "o:tracking-clicks":   "yes",
            "o:tracking-opens":    "yes",
            # Tag for filtering in Mailgun Analytics
            "o:tag":               ["phishing-sim", "fuel-allowance-q4-2026"],
        },
        timeout=30,
    )

    return {
        "status_code": resp.status_code,
        "body":        resp.json() if resp.content else {},
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fuel Allowance Campaign Sender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv_file",  help="Path to recipients CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview substitutions without sending")
    parser.add_argument("--api-key", metavar="KEY",
                        help="Mailgun API key (overrides script default)")
    args = parser.parse_args()

    global MAILGUN_API_KEY
    if args.api_key:
        MAILGUN_API_KEY = args.api_key

    if MAILGUN_API_KEY == "YOUR_MAILGUN_API_KEY_HERE" and not args.dry_run:
        print("[ERROR] Set your Mailgun API key in the script or pass --api-key")
        sys.exit(1)

    if not Path(args.csv_file).exists():
        print(f"[ERROR] File not found: {args.csv_file}")
        sys.exit(1)

    # Inject landing URL into HTML
    html = EMAIL_HTML.replace("__LANDING_URL__", LANDING_URL)

    print(f"\n{'='*55}")
    print(f"  Fuel Allowance Campaign Sender")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}")
    print(f"  Domain:   {MAILGUN_DOMAIN}")
    print(f"  From:     {SENDER_NAME} <{SENDER_EMAIL}>")
    print(f"  Landing:  {LANDING_URL}")
    print(f"  Mode:     {'DRY RUN' if args.dry_run else 'LIVE SEND'}")
    print(f"{'='*55}\n")

    # Load
    print(f"[*] Loading {args.csv_file}...")
    recipients = load_recipients(args.csv_file)
    print(f"[*] {len(recipients)} valid recipients\n")

    if not recipients:
        print("[ERROR] No valid recipients — aborting.")
        sys.exit(1)

    # Batch and send
    batches = [
        recipients[i : i + BATCH_SIZE]
        for i in range(0, len(recipients), BATCH_SIZE)
    ]

    sent_ok = 0
    sent_fail = 0

    for idx, batch in enumerate(batches, 1):
        print(f"[>] Batch {idx}/{len(batches)}  ({len(batch)} recipients)")
        result = send_batch(batch, html, dry_run=args.dry_run)

        if result.get("dry_run"):
            sent_ok += len(batch)
        elif result["status_code"] in (200, 202):
            sent_ok += len(batch)
            msg_id = result["body"].get("id", "N/A")
            print(f"    ✓ Accepted — Mailgun ID: {msg_id}")
        else:
            sent_fail += len(batch)
            print(f"    ✗ FAILED — HTTP {result['status_code']}: {result['body']}")

        if idx < len(batches):
            print(f"    (waiting {DELAY_SECONDS}s before next batch)")
            time.sleep(DELAY_SECONDS)

    # Summary
    print(f"\n{'='*55}")
    print(f"  DONE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Sent OK : {sent_ok}")
    print(f"  Failed  : {sent_fail}")
    print(f"  Total   : {len(recipients)}")
    if not args.dry_run and sent_ok:
        print(f"\n  View results:")
        print(f"  https://app.mailgun.com/app/analytics")
        print(f"  Filter by tag: fuel-allowance-q4-2026")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
