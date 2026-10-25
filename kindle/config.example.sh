# Copy to config.sh and replace the URL with a signed Kodo private download URL.
# Keep the entire URL quoted. Renew it before its recorded expiry date.
CALENDAR_URL='https://YOUR_KODO_DOMAIN/family-calendar/YOUR_SCREEN_ID/latest.png?e=EXPIRY&token=SIGNED_DOWNLOAD_TOKEN'
# Unix seconds, exactly matching e. Legacy configs may omit this to derive it.
URL_EXPIRES_AT='EXPIRY'
# Trusted CA bundle for the HTTPS domain, not a generated self-signed certificate.
CA_CERT='/mnt/us/family-calendar/ca-bundle.crt'
FBINK='/mnt/us/family-calendar/fbink'
INTERVAL=1800
