"""Sample Finviz-shaped data used across the test suite.

These mirror the structures the real ``finviz`` functions return, so the
provider and brain can be exercised end-to-end without any network access.
"""

# A fundamentals snapshot resembling finviz.get_stock("AAPL"). Only the keys
# the brain actually reads need to be realistic.
AAPL_FUNDAMENTALS = {
    "Ticker": "AAPL",
    "Company": "Apple Inc.",
    "Sector": "Technology",
    "Industry": "Consumer Electronics",
    "Country": "USA",
    "Price": "195.12",
    "Change": "1.45%",
    "P/E": "31.50",
    "Forward P/E": "27.80",
    "PEG": "2.40",
    "P/S": "8.10",
    "P/B": "45.20",
    "ROE": "150.10%",
    "ROA": "28.40%",
    "Profit Margin": "25.30%",
    "Oper. Margin": "30.10%",
    "EPS next Y": "8.50%",
    "EPS next 5Y": "10.20%",
    "Sales Q/Q": "4.90%",
    "Recom": "1.90",
    "Target Price": "230.00",
    "RSI (14)": "62.30",
    "SMA50": "3.20%",
    "SMA200": "9.80%",
    "52W High": "-2.10%",
    "52W Low": "38.50%",
    "Perf Quarter": "12.40%",
    "Perf Year": "28.10%",
    "Debt/Eq": "1.80",
    "Current Ratio": "0.99",
    "Quick Ratio": "0.85",
    "Short Float": "0.70%",
    "Dividend %": "0.45%",
}

# A weaker, more cautious profile (overbought, expensive, downgraded).
RISKY_FUNDAMENTALS = {
    "Ticker": "RISK",
    "Company": "Risky Corp.",
    "Price": "12.00",
    "Change": "-4.20%",
    "P/E": "120.00",
    "PEG": "5.10",
    "P/B": "12.00",
    "ROE": "-8.00%",
    "Profit Margin": "-15.00%",
    "EPS next 5Y": "-5.00%",
    "Recom": "4.30",
    "Target Price": "9.00",
    "RSI (14)": "78.00",
    "SMA200": "-22.00%",
    "52W Low": "3.00%",
    "Debt/Eq": "3.40",
    "Current Ratio": "0.60",
    "Short Float": "18.00%",
}

AAPL_NEWS = [
    ("Jun-30-26 09:15AM", "Apple surges as iPhone sales beat expectations", "https://x/1", "Reuters"),
    ("Jun-30-26 08:02AM", "Analysts raise Apple price target after strong quarter", "https://x/2", "Bloomberg"),
    ("Jun-29-26 04:30PM", "Apple announces record services growth", "https://x/3", "CNBC"),
    ("Jun-29-26 11:00AM", "Apple faces lawsuit over App Store fees", "https://x/4", "WSJ"),
    ("Jun-28-26 02:15PM", "Apple unveils new product lineup", "https://x/5", "TheVerge"),
]

NEGATIVE_NEWS = [
    ("Jun-30-26 09:15AM", "Company plunges on earnings miss", "https://x/1", "Reuters"),
    ("Jun-30-26 08:02AM", "Analysts downgrade after weak guidance", "https://x/2", "Bloomberg"),
    ("Jun-29-26 04:30PM", "Lawsuit and investigation weigh on shares", "https://x/3", "CNBC"),
]

AAPL_RATINGS = [
    {"Date": "Jun-30-26", "Status": "Upgrade", "Analyst": "Morgan Stanley", "Rating": "Buy", "Price": "$200 → $215"},
    {"Date": "Jun-15-26", "Status": "Reiterated", "Analyst": "Goldman", "Rating": "Buy", "Price": "$210"},
]

AAPL_INSIDER = [
    {"Insider Trading": "COOK TIM", "Relationship": "CEO", "Date": "Jun 20", "Transaction": "Buy", "Cost": "190.00", "#Shares": "1000"},
    {"Insider Trading": "MAESTRI LUCA", "Relationship": "CFO", "Date": "Jun 10", "Transaction": "Sale", "Cost": "188.00", "#Shares": "500"},
    {"Insider Trading": "LEVINSON ART", "Relationship": "Director", "Date": "Jun 05", "Transaction": "Buy", "Cost": "185.00", "#Shares": "2000"},
]
