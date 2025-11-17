# Whale Alert Personal Dashboard

This is a personal web application (Streamlit-based) that tracks large cryptocurrency transactions ("whale" transactions) for the top 5 cryptocurrencies. It highlights potential insider trading patterns to anticipate price movements. The app supports English and Italian languages.

**Features:**
- Live monitoring of big transactions (>$500k) for BTC, ETH, USDT, BNB, USDC.
- Alerts for unusual activity (e.g. large exchange deposits/withdrawals).
- WhatsApp notifications for critical alerts (via Twilio API).
- Bilingual interface (Italian/English) with an Italian user guide.

**Usage:**
- Provide your Whale Alert API key and Twilio credentials as environment variables or in `streamlit/secrets.toml`.
- Deploy the app via Streamlit or run locally with `streamlit run app.py`.
- Use the sidebar to switch language or open the Guide (Guida) for instructions.

*This project is for personal use. Data provided by Whale Alert API (free tier).* 
