# Whale Monitor Dashboard

Personal Streamlit web-app to track large on-chain transactions ("whale" moves) for Bitcoin (BTC) and Ethereum (ETH). The dashboard highlights potential insider-like patterns so you can keep an eye on unusual activity. Interface and user guide are bilingual (Italian/English).

## Features
- Data provided by the [Blockchair](https://blockchair.com/api/docs) API (free plan). Assets covered: BTC and ETH.
- Sidebar slider to pick the minimum USD value (100k → 10M) applied to tables, analytics, and notifications.
- Live monitoring of high-value transfers (native + USD value, explorer links, coinbase flag).
- Advanced pattern detection per chain: super-whales (≥$10M), 30-minute volume spikes (≥$50M USD), and 30-minute activity spikes (≥5 tx).
- Whale flow line chart (10-minute buckets) and UTC heatmap of activity.
- WhatsApp notifications via Twilio secrets—sent only when new patterns appear.
- Italian/English UI plus localized help page describing the above features.

## Setup
1. Install dependencies: `pip install -r requirements.txt`.
2. Run locally with `streamlit run app.py`.
3. Optional Streamlit secrets / environment variables:
   - `TWILIO_SID`
   - `TWILIO_TOKEN`
   - `TWILIO_WHATSAPP_TO` (digits only; the app prefixes `whatsapp:` automatically)
   - `TWILIO_WHATSAPP_FROM` (defaults to the Twilio sandbox sender)
   - `AUTO_REFRESH_SECONDS` (default 180 seconds, minimum 60 to respect Blockchair limits)

The dashboard automatically refreshes every 3 minutes to stay within the ~1000 requests/day allowance of the free Blockchair tier. You can disable auto-refresh from the sidebar or trigger a manual reload anytime.

## Notes
- Only BTC and ETH chains are monitored.
- Signals (super-whales, volume spikes, activity spikes) are statistical hints, **not** financial advice.
- WhatsApp alerts trigger only when a new pattern signature is detected versus the previous refresh.
