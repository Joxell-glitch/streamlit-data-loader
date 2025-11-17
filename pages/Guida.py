import streamlit as st

st.set_page_config(page_title="Guida - Whale Monitor", page_icon="❓", layout="wide")

lang = st.session_state.get("lang", "it")

guida_it = """
# Guida all'utilizzo di Whale Monitor

Whale Monitor è una dashboard personale per tracciare grandi transazioni ("balene") sulle principali criptovalute.  
Di seguito troverai istruzioni e spiegazioni per interpretare i dati mostrati.

**Selezione della lingua:** Puoi scegliere Italiano o Inglese dal menu a sinistra (sezione *Lingua*). I testi dell'app si aggiorneranno di conseguenza.

## Sezioni della Dashboard:
- **Ultime transazioni delle balene:** Nella pagina principale vedrai una tabella aggiornata in tempo reale con le transazioni di valore superiore a 500.000 USD per i 5 asset principali (Bitcoin, Ethereum, Tether, BNB, USD Coin). Per ciascuna transazione vengono mostrati:
    - **Ora (UTC):** timestamp in tempo universale.
    - **Asset:** la criptovaluta (simbolo) e blockchain (ad esempio *BTC (Bitcoin)*, *ETH (Ethereum)*).
    - **Quantità:** l'ammontare di criptovaluta trasferito.
    - **Valore (USD):** il controvalore approssimativo in dollari.
    - **Da:** l'indirizzo mittente. Se è noto (ad esempio un exchange o un wallet identificato), viene mostrato il nome (es. *Binance*). Altrimenti viene visualizzato un estratto dell'indirizzo (primi e ultimi caratteri). Se l'indirizzo è un exchange, vedrai la dicitura "(exchange)" accanto.
    - **A:** l'indirizzo destinatario, formattato analogamente a "Da".
    - **Note:** eventuali annotazioni automatiche. Ad esempio, *"Grande deposito su exchange!"* indica che la transazione è un trasferimento verso un exchange (possibile segnale di vendita imminente); *"Grande prelievo da exchange!"* indica movimento da un exchange verso un wallet esterno (possibile accumulo). 

- **Allerta Pattern:** Se l'app rileva un pattern sospetto (ad esempio molti depositi su exchange in un breve lasso di tempo), verrà mostrato un riquadro di avviso (in giallo) con la descrizione (*Pattern Alert*). Questo ti informa di un'attività anomala che potrebbe precedere movimenti di mercato importanti.

- **Aggiornamento dati:** Di default l'auto-aggiornamento è attivo (ogni 15 secondi). Puoi disattivarlo togliendo la spunta a *"Aggiornamento automatico"* nel menu, oppure forzare un refresh immediato cliccando *"Aggiorna adesso"*. L'orario dell'ultimo aggiornamento effettuato è indicato sopra la tabella.

## Notifiche WhatsApp:
Se hai configurato le credenziali Twilio nell'app (vedi README), Whale Monitor invierà un messaggio WhatsApp al tuo numero quando si verifica un pattern critico (es. un'allerta importante). Cerca sul tuo WhatsApp messaggi dal mittente Twilio Sandbox.

*Nota:* Assicurati di aver inserito il tuo numero di telefono in formato internazionale corretto nelle variabili d'ambiente (ad esempio `TWILIO_WHATSAPP_TO="+39XXXXXXXX"`). Senza configurazione, l'app non invierà notifiche esterne.

## Interpretazione dei segnali:
- **Depositi su exchange (rosso):** Quando vedi molte transazioni evidenziate come *"Grande deposito su exchange"*, significa che grandi holder stanno muovendo fondi verso gli exchange. Questo spesso precede una fase di vendita che può far calare il prezzo dell'asset. Tienilo d'occhio: se succede improvvisamente, potrebbe esserci una notizia non ancora pubblica o preparativi per una vendita coordinata.
- **Prelievi da exchange (verde):** Al contrario, quando le balene spostano fondi fuori dagli exchange (verso wallet privati o cold storage), tendono a non vendere nel breve termine. Molti prelievi possono indicare fiducia nell'asset o accumulo, un segnale potenzialmente rialzista.
- **Attività multipla di balene:** L'allerta *"Attività inusuale di più balene!"* compare quando diversi movimenti significativi avvengono ravvicinati. Questo potrebbe indicare un evento di mercato imminente. Ad esempio, se 3-4 balene trasferiscono Bitcoin su Binance nell'arco di 10 minuti, è un forte segnale di potenziale pressione di vendita.
- **Stablecoin in movimento:** Sebbene questa dashboard si concentri su 5 asset, due di essi sono stablecoin (USDT e USDC). Grossi trasferimenti di stablecoin verso exchange potrebbero segnalare che i trader stanno preparando capitale per acquistare altre crypto (potenzialmente rialzista per il mercato crypto in generale). Viceversa, uscita di stablecoin da exchange può significare che stanno ritirando denaro (prendendo profitto).

## Limitazioni:
- **Copertura transazioni:** Prendiamo in considerazione solo transazioni sopra i 500k USD, quindi se un whale trasferisce una somma inferiore non apparirà.
- **Dati in tempo reale:** La frequenza di aggiornamento è 15s per evitare di sovraccaricare le API gratuite. Potrebbero sfuggire transazioni se avvengono moltissime in poco tempo.
- **Indirizzi sconosciuti:** Non tutti i wallet sono identificati; la mancanza di un tag non implica che non sia importante, solo che Whale Alert non sa di chi sia quel wallet.
- **Nessuna certezza sul mercato:** I segnali mostrati vanno interpretati con cautela. Non è garantito che un deposito su exchange porti a un calo di prezzo; è solo un indizio.

## Configurazione:
- **Chiave API Whale Alert:** fornisci la tua API key tramite variabile `WHALE_ALERT_KEY` o `streamlit/secrets.toml`.
- **Credenziali Twilio (WhatsApp):** imposta `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WHATSAPP_TO` (e verifica `TWILIO_WHATSAPP_FROM`).
- Conserva le credenziali nei secrets per maggiore sicurezza.

**Buon monitoraggio!** Combina queste informazioni con altre analisi per decisioni più consapevoli.
"""

guida_en = """
# Guide to Using Whale Monitor

*Whale Monitor* is a personal dashboard to track large cryptocurrency transactions ("whales") on major coins.  
Below are instructions and explanations to interpret the data.

**Language selection:** You can switch between Italian and English from the sidebar (*Language* selector). All interface text will update accordingly.

## Dashboard Sections:
- **Latest Whale Transactions:** The main page shows a real-time table with transactions above 500,000 USD for Bitcoin, Ethereum, Tether, BNB, and USD Coin. Each row includes time, asset, amount, value in USD, sender, receiver, and automatic notes (e.g., deposits/withdrawals on exchanges).
- **Pattern Alert:** When the app detects suspicious activity (many exchange deposits in a short time), a warning box highlights it so you can react quickly.
- **Data Refresh:** Auto-refresh runs every 15 seconds. Disable it from the sidebar or click *"Refresh now"* for an immediate update. The last refresh time appears above the table.

## WhatsApp Notifications:
Configure Twilio credentials (see README) and the app will notify you on WhatsApp when a critical pattern triggers. Without configuration, external alerts are disabled.

## Interpreting Signals:
- **Exchange deposits:** Often precede selling pressure and possible price drops.
- **Exchange withdrawals:** Usually indicate accumulation or storage, a potentially bullish sign.
- **Multiple whale activity:** Several large moves close together may hint at a market event.
- **Stablecoins:** Large flows of USDT/USDC into exchanges can signal upcoming buying; outflows can signal profit taking.

## Limitations:
- Focus on transactions above $500k (smaller ones are ignored).
- Refresh every 15s (heavy activity might still miss some data).
- Unknown wallet owners remain unlabeled.
- Signals are indicators, not guarantees.

## Configuration:
- Provide `WHALE_ALERT_KEY` for API access.
- Set Twilio WhatsApp credentials for notifications.
- Store secrets securely via environment variables or Streamlit secrets.

**Happy monitoring!** Use this dashboard along with other market tools and news sources.
"""

if lang == "it":
    st.markdown(guida_it)
else:
    st.markdown(guida_en)
