# Whale Monitor Dashboard

Personal Streamlit web-app to track large on-chain transactions ("whale" moves) for Bitcoin (BTC) and Ethereum (ETH). The dashboard highlights potential insider-like patterns so you can keep an eye on unusual activity. Interface and user guide are bilingual (Italian/English).

## Features
- Data source: [Blockchair](https://blockchair.com/api/docs) public API (free tier) for BTC and ETH transactions.
- Live monitoring of transfers ≥ $500k (native + USD value, explorer links, coinbase flag).
- Statistical pattern detection (super-whales ≥ $10M, whale clusters, hourly spikes).
- WhatsApp notifications for new alerts via Twilio (optional).
- Italian/English UI plus localized help page.

## Setup
1. Install dependencies: `pip install -r requirements.txt`.
2. Run locally with `streamlit run app.py`.
3. Optional environment variables / Streamlit secrets:
   - `TWILIO_SID`
   - `TWILIO_TOKEN`
   - `TWILIO_WHATSAPP_TO` (recipient number, digits only; the app prefixes `whatsapp:` automatically)
   - `TWILIO_WHATSAPP_FROM` (defaults to the Twilio sandbox sender)
   - `AUTO_REFRESH_SECONDS` (default 180 seconds, minimum 60 to respect Blockchair limits)

The dashboard automatically refreshes every 3 minutes to stay within the ~1000 requests/day allowance of the free Blockchair tier. You can disable auto-refresh from the sidebar or trigger a manual reload anytime.

## Notes
- Only BTC and ETH chains are monitored.
- Signals are statistical hints, **not** financial advice.
- WhatsApp alerts trigger only when a new pattern is detected versus the previous refresh, to avoid duplicates.
