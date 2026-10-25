# Copy to config.sh; keep credentials in /var/local/family-calendar/discovery.json (0600).
# Uses existing curl, OpenSSL and jq; no Python runtime is required.
# Store secrets on the private system partition; /mnt/us cannot enforce mode 0600.
DISCOVERY_CONFIG='/var/local/family-calendar/discovery.json'
CA_CERT='/mnt/us/family-calendar/ca-bundle.crt'
FBINK='/mnt/us/family-calendar/fbink'
# Demo only: explicitly set 1 to permit unencrypted HTTP image downloads.
# List API remains HTTPS. Leave disabled for normal use.
ALLOW_HTTP_DOWNLOAD=0
# Hide native clock/status bar while calendar runs; restore it on normal stop.
HIDE_STATUS_BAR=1
INTERVAL=1800
POWER_MODE=rtc
# 0 uses the default day/night slots; e.g. 300 tests a five-minute RTC cycle.
RTC_INTERVAL=0
# Optional existing linkss PNG entry; backup manually before enabling replacement.
SCREENSAVER_IMAGE=''
TIMEZONE=Asia/Shanghai
