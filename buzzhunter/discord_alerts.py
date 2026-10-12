"""Send best-effort Discord webhook notifications without logging secrets."""
import os
import logging
import requests

log = logging.getLogger('buzzhunter.discord')

def send_alert(message):
    url = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    if not url.startswith(('https://discord.com/api/webhooks/', 'https://discordapp.com/api/webhooks/')):
        log.warning('Discord webhook is missing or invalid')
        return False
    try:
        response = requests.post(url, json={'content': str(message)[:1900], 'allowed_mentions': {'parse': []}}, timeout=8)
        response.raise_for_status()
        log.info('Discord alert delivered')
        return True
    except requests.RequestException as exc:
        log.warning('Discord alert failed: %s', type(exc).__name__)
        return False
