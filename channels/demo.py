#!/usr/bin/env python3
"""Five calls, so you can see what the channels return. Run from this directory."""
from datetime import datetime
from channels import send_sms, send_voice, send_email

at = datetime(2026, 3, 2, 10, 0)
print(send_sms('555-401-2288', 'Your appointment is on Monday at 10:00.', at))
print(send_sms('555-214-9004', 'Your appointment is on Monday at 10:00.', at))   # landline
print(send_sms('', 'Your appointment is on Monday at 10:00.', at))
print(send_voice('555-401-2288', 'Appointment reminder.', at))
print(send_email('maria.delgado@example.net', 'Appointment reminder.', at))
print('\nSee outbox.jsonl for the log.')
