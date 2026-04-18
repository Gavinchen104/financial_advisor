"""
Macro factor definitions and sector-level sensitivity mappings.

direction: "inverse" means rising indicator is negative for that sector/stock.
           "positive" means rising indicator is a tailwind.
strength: 0.0–1.0 importance of this factor for the sector.
"""

# Key macro indicators with yfinance-tradeable tickers
MACRO_FACTORS: dict[str, dict] = {
    "US_10Y_YIELD": {
        "name": "US 10-Year Treasury Yield",
        "yfinance_ticker": "^TNX",
        "unit": "% yield",
        "description": (
            "The benchmark risk-free rate. Rising yields increase the discount rate used to "
            "value future earnings, compressing P/E multiples on high-growth stocks. "
            "Also makes dividend-paying stocks (utilities, REITs) relatively less attractive."
        ),
    },
    "FED_FUNDS_RATE_PROXY": {
        "name": "US 13-Week Treasury Bill (Fed Funds Proxy)",
        "yfinance_ticker": "^IRX",
        "unit": "% yield",
        "description": (
            "Short end of the yield curve; closely tracks the Federal Reserve's policy rate. "
            "Banks profit when the spread between short-term borrowing costs and long-term "
            "lending rates (net interest margin) is wide."
        ),
    },
    "YIELD_CURVE_10Y2Y": {
        "name": "US 10Y-2Y Yield Spread (Yield Curve)",
        "yfinance_ticker": "^TNX",  # approximation; true spread requires ^TNX minus ^IRX2
        "unit": "basis points",
        "description": (
            "The spread between 10-year and 2-year Treasury yields. When inverted (negative), "
            "it historically predicts recession within 12-18 months. Steep curve benefits banks "
            "(borrow short, lend long). Flat/inverted curve squeezes bank margins."
        ),
    },
    "VIX": {
        "name": "CBOE Volatility Index (VIX)",
        "yfinance_ticker": "^VIX",
        "unit": "index points",
        "description": (
            "Market's 30-day expected volatility derived from S&P 500 options. "
            "Often called the 'fear gauge.' VIX above 30 signals high fear; below 15 signals complacency. "
            "Spikes in VIX trigger risk-off flows into bonds and defensive sectors."
        ),
    },
    "WTI_CRUDE_OIL": {
        "name": "WTI Crude Oil (front-month futures)",
        "yfinance_ticker": "CL=F",
        "unit": "USD per barrel",
        "description": (
            "West Texas Intermediate crude oil price. Direct input cost for airlines, chemicals, and plastics. "
            "Higher oil prices expand margins for E&P companies and oilfield services but squeeze "
            "consumer discretionary spending power."
        ),
    },
    "USD_INDEX": {
        "name": "US Dollar Index (DXY)",
        "yfinance_ticker": "DX-Y.NYB",
        "unit": "index points",
        "description": (
            "Measures the USD against a basket of major currencies. A strong dollar makes "
            "US exports more expensive abroad, reducing the dollar-value of international revenue "
            "for US multinationals (tech, pharma, industrials). "
            "Typically inverse to commodities priced in USD."
        ),
    },
    "GOLD": {
        "name": "Gold (front-month futures)",
        "yfinance_ticker": "GC=F",
        "unit": "USD per troy oz",
        "description": (
            "Flight-to-safety asset. Rises during geopolitical stress, inflation fears, or dollar weakness. "
            "Directly impacts gold miners (NEM). Generally moves inverse to real interest rates."
        ),
    },
    "COPPER": {
        "name": "Copper (front-month futures)",
        "yfinance_ticker": "HG=F",
        "unit": "USD per lb",
        "description": (
            "'Dr. Copper' — historically one of the best leading indicators of global economic health "
            "due to its use in construction, EVs, and electronics. "
            "Falling copper prices often signal slowing global demand."
        ),
    },
    "NATURAL_GAS": {
        "name": "Natural Gas (front-month futures)",
        "yfinance_ticker": "NG=F",
        "unit": "USD per MMBtu",
        "description": (
            "Key fuel for power generation and industrial processes. "
            "High natural gas prices help E&P and midstream companies but hurt utilities "
            "and energy-intensive manufacturers."
        ),
    },
    "SP500": {
        "name": "S&P 500 Index",
        "yfinance_ticker": "^GSPC",
        "unit": "index points",
        "description": "Broad US equity market benchmark. All S&P 500 stocks show strong positive beta to this index.",
    },
}

# Sector-level macro sensitivity map
# Format: sector_name → list of {factor_id, direction, strength, reason}
SECTOR_MACRO_SENSITIVITY: dict[str, list[dict]] = {
    "Information Technology": [
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.85,
         "reason": "High-P/E growth stocks are duration assets; rising rates compress multiples severely"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.75,
         "reason": "Large multinationals (AAPL, MSFT, GOOGL) earn 40-60% of revenue internationally"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.7,
         "reason": "Risk-off rotation out of high-beta tech into bonds"},
        {"factor": "COPPER",              "direction": "positive", "strength": 0.4,
         "reason": "Copper strength signals economic growth, lifting enterprise IT spending"},
    ],
    "Communication Services": [
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.7,
         "reason": "Growth-heavy sector (GOOGL, META, NFLX) sensitive to discount rate changes"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.65,
         "reason": "GOOGL and META earn substantial international advertising revenue"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.65,
         "reason": "Risk-off selling hits growth-oriented names in this sector"},
    ],
    "Consumer Discretionary": [
        {"factor": "WTI_CRUDE_OIL",       "direction": "inverse",  "strength": 0.7,
         "reason": "High oil prices reduce household disposable income, cutting discretionary spending"},
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.65,
         "reason": "Higher rates increase mortgage and auto loan costs, hurting big-ticket purchases"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.6,
         "reason": "Consumer confidence falls in high-volatility environments"},
        {"factor": "COPPER",              "direction": "positive", "strength": 0.5,
         "reason": "Copper as economic indicator; strong economy lifts consumer spending"},
    ],
    "Consumer Staples": [
        {"factor": "VIX",                 "direction": "positive", "strength": 0.7,
         "reason": "Defensive sector: investors rotate into staples during market stress"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.6,
         "reason": "PG, KO, PEP earn large international revenues"},
        {"factor": "WTI_CRUDE_OIL",       "direction": "inverse",  "strength": 0.5,
         "reason": "Oil is an input cost (packaging, logistics) and squeeze on consumer budgets"},
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.55,
         "reason": "Staples are often held as bond proxies for yield; higher rates reduce their relative appeal"},
    ],
    "Health Care": [
        {"factor": "VIX",                 "direction": "positive", "strength": 0.6,
         "reason": "Healthcare is defensive; outperforms in recessions and risk-off periods"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.6,
         "reason": "Big pharma (MRK, PFE, LLY) sell globally; strong USD reduces translated earnings"},
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.4,
         "reason": "Some healthcare growth names (biotech) are rate-sensitive, but sector broadly defensive"},
    ],
    "Financials": [
        {"factor": "US_10Y_YIELD",        "direction": "positive", "strength": 0.85,
         "reason": "Banks earn net interest margin (NIM); higher long-term rates expand NIM"},
        {"factor": "FED_FUNDS_RATE_PROXY","direction": "positive", "strength": 0.8,
         "reason": "Rising Fed funds rate directly increases bank lending rates and NIM"},
        {"factor": "YIELD_CURVE_10Y2Y",   "direction": "positive", "strength": 0.9,
         "reason": "Steep yield curve = banks borrow cheap short-term, lend dear long-term"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.6,
         "reason": "Market stress increases loan losses and credit concerns for banks"},
        {"factor": "COPPER",              "direction": "positive", "strength": 0.5,
         "reason": "Strong economy reduces credit losses and lifts loan demand"},
    ],
    "Industrials": [
        {"factor": "COPPER",              "direction": "positive", "strength": 0.75,
         "reason": "Copper is a leading indicator of industrial activity and capex cycles"},
        {"factor": "WTI_CRUDE_OIL",       "direction": "inverse",  "strength": 0.55,
         "reason": "Oil is an input cost for many industrial processes and logistics"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.65,
         "reason": "Industrials (CAT, HON, BA) generate large international revenues; strong USD hurts"},
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.5,
         "reason": "Higher rates increase cost of capital for capex-heavy industrial companies"},
    ],
    "Energy": [
        {"factor": "WTI_CRUDE_OIL",       "direction": "positive", "strength": 0.95,
         "reason": "Oil price is the primary revenue and earnings driver for E&P companies"},
        {"factor": "NATURAL_GAS",         "direction": "positive", "strength": 0.7,
         "reason": "Natural gas prices drive earnings for gas-weighted E&P and midstream companies"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.6,
         "reason": "Oil is priced in USD globally; strong dollar suppresses oil prices"},
        {"factor": "COPPER",              "direction": "positive", "strength": 0.5,
         "reason": "Global growth indicator; strong economy lifts energy demand"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.5,
         "reason": "Risk-off events compress oil demand expectations"},
    ],
    "Materials": [
        {"factor": "COPPER",              "direction": "positive", "strength": 0.85,
         "reason": "Copper is a core product (FCX) and economic bellwether for the materials sector"},
        {"factor": "GOLD",                "direction": "positive", "strength": 0.7,
         "reason": "Gold price directly drives earnings for gold miners (NEM)"},
        {"factor": "USD_INDEX",           "direction": "inverse",  "strength": 0.75,
         "reason": "Commodities are priced in USD; strong dollar makes them more expensive abroad"},
        {"factor": "WTI_CRUDE_OIL",       "direction": "inverse",  "strength": 0.5,
         "reason": "Energy is a major input cost for chemicals and materials processing"},
        {"factor": "NATURAL_GAS",         "direction": "inverse",  "strength": 0.6,
         "reason": "Natural gas is a feedstock for chemicals (DOW, LYB) and energy for smelting"},
    ],
    "Real Estate": [
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.95,
         "reason": "REITs are valued as yield instruments; rising rates make their dividends less attractive and raise cap rates"},
        {"factor": "FED_FUNDS_RATE_PROXY","direction": "inverse",  "strength": 0.85,
         "reason": "Higher short-term rates increase floating-rate debt costs for leveraged REITs"},
        {"factor": "VIX",                 "direction": "inverse",  "strength": 0.55,
         "reason": "Market stress raises REIT risk premiums"},
        {"factor": "COPPER",              "direction": "positive", "strength": 0.5,
         "reason": "Economic growth drives real estate demand and occupancy rates"},
    ],
    "Utilities": [
        {"factor": "US_10Y_YIELD",        "direction": "inverse",  "strength": 0.90,
         "reason": "Utilities are bond proxies; investors sell them when Treasury yields rise"},
        {"factor": "VIX",                 "direction": "positive", "strength": 0.75,
         "reason": "Utilities are the most defensive sector; bought heavily during market panics"},
        {"factor": "NATURAL_GAS",         "direction": "inverse",  "strength": 0.7,
         "reason": "Natural gas is the primary fuel cost for power generation; higher prices squeeze margins"},
        {"factor": "WTI_CRUDE_OIL",       "direction": "inverse",  "strength": 0.5,
         "reason": "Oil is an input cost for fuel oil-fired generators"},
    ],
}

# Company-specific macro overrides (supplement or override sector defaults)
COMPANY_MACRO_OVERRIDES: dict[str, list[dict]] = {
    "NEM":  [{"factor": "GOLD",      "direction": "positive", "strength": 0.95,
              "reason": "Newmont is the world's largest gold miner; gold price is the primary earnings driver"}],
    "FCX":  [{"factor": "COPPER",    "direction": "positive", "strength": 0.95,
              "reason": "Freeport-McMoRan derives ~80% of revenue from copper"}],
    "XOM":  [{"factor": "WTI_CRUDE_OIL", "direction": "positive", "strength": 0.9,
              "reason": "ExxonMobil's earnings highly correlated to oil realizations"}],
    "CVX":  [{"factor": "WTI_CRUDE_OIL", "direction": "positive", "strength": 0.9,
              "reason": "Chevron earnings track oil prices closely"}],
    "UAL":  [{"factor": "WTI_CRUDE_OIL", "direction": "inverse", "strength": 0.9,
              "reason": "Jet fuel is United's largest operating expense (~20-25% of costs)"}],
    "DAL":  [{"factor": "WTI_CRUDE_OIL", "direction": "inverse", "strength": 0.9,
              "reason": "Jet fuel is Delta's largest operating expense"}],
    "LUV":  [{"factor": "WTI_CRUDE_OIL", "direction": "inverse", "strength": 0.9,
              "reason": "Southwest's fuel costs directly track crude oil"}],
    "AAL":  [{"factor": "WTI_CRUDE_OIL", "direction": "inverse", "strength": 0.9,
              "reason": "American Airlines is highly leveraged to fuel costs"}],
    "SLB":  [{"factor": "WTI_CRUDE_OIL", "direction": "positive", "strength": 0.85,
              "reason": "Oil company capex (SLB's revenue) tracks oil prices with a lag"}],
    "HAL":  [{"factor": "WTI_CRUDE_OIL", "direction": "positive", "strength": 0.85,
              "reason": "E&P capex — Halliburton's revenue driver — follows oil prices"}],
    "MU":   [{"factor": "COPPER",    "direction": "positive", "strength": 0.6,
              "reason": "Memory chip pricing cycles correlate with global electronics and industrial demand"}],
    "TSLA": [{"factor": "COPPER",    "direction": "positive", "strength": 0.7,
              "reason": "Each EV uses 3-4x more copper than ICE vehicles; copper cost is material to Tesla margins"}],
    "NEE":  [{"factor": "NATURAL_GAS", "direction": "inverse", "strength": 0.6,
              "reason": "NextEra's Florida Power & Light burns significant gas for generation"},
             {"factor": "US_10Y_YIELD", "direction": "inverse", "strength": 0.9,
              "reason": "NEE is viewed as a bond proxy; rising rates hurt its premium valuation"}],
    "BRK.B":[{"factor": "US_10Y_YIELD", "direction": "positive", "strength": 0.7,
              "reason": "Berkshire benefits via GEICO (float investment income) and bank holdings (BAC, AXP) when rates rise"}],
}
