"""
Curated supply-chain, customer, and strategic-partner edges for S&P 500
and closely related non-S&P 500 names (e.g. TSM, ASML).

Edge format:
  (source, target, type, weight_0_to_1, plain-English label)

Types:
  "supplies_to"  — source is an upstream supplier to target
  "competes_with" — symmetric rivalry (stored once, queried both ways)
  "major_customer" — source is a meaningful revenue customer of target
  "strategic_partner" — JV, licensing, deep alliance

Weights reflect importance of the relationship:
  0.9-1.0 = existential / single-source dependency
  0.7-0.89 = significant / top-3 revenue relationship
  0.5-0.69 = meaningful but not dominant
  0.3-0.49 = notable but one of many
"""

EDGES: list[tuple[str, str, str, float, str]] = [

    # ── SEMICONDUCTOR SUPPLY CHAIN ──────────────────────────────────────────
    # Equipment → Fabs (ASML/AMAT/LRCX/KLAC are the "picks-and-shovels" layer)
    ("ASML",  "TSM",   "supplies_to",    1.0,  "Sole supplier of EUV lithography machines; TSM cannot manufacture leading-edge chips without ASML"),
    ("ASML",  "INTC",  "supplies_to",    0.9,  "Intel's foundry build-out is ASML-dependent for EUV"),
    ("ASML",  "MU",    "supplies_to",    0.7,  "EUV needed for advanced DRAM nodes"),
    ("AMAT",  "TSM",   "supplies_to",    0.85, "Deposition/etch equipment for TSMC fabs"),
    ("AMAT",  "MU",    "supplies_to",    0.8,  "Process equipment for Micron memory fabs"),
    ("AMAT",  "INTC",  "supplies_to",    0.8,  "Equipment for Intel's IDM/foundry fabs"),
    ("AMAT",  "WDC",   "supplies_to",    0.6,  "NAND flash fab equipment"),
    ("LRCX",  "TSM",   "supplies_to",    0.85, "Etch and deposition for leading-edge TSMC nodes"),
    ("LRCX",  "MU",    "supplies_to",    0.8,  "Critical etch steps in DRAM manufacturing"),
    ("LRCX",  "INTC",  "supplies_to",    0.75, "Etch equipment for Intel fabs"),
    ("KLAC",  "TSM",   "supplies_to",    0.8,  "Yield management and process control"),
    ("KLAC",  "MU",    "supplies_to",    0.75, "Defect inspection for memory fabs"),
    ("KLAC",  "INTC",  "supplies_to",    0.7,  "Process control for Intel fabs"),

    # Fabs → Fabless chip designers
    ("TSM",   "NVDA",  "supplies_to",    0.95, "TSMC fabricates ~100% of NVIDIA's GPUs and AI accelerators"),
    ("TSM",   "AMD",   "supplies_to",    0.92, "TSMC fabricates AMD CPUs and GPUs"),
    ("TSM",   "AAPL",  "supplies_to",    0.90, "TSMC fabricates Apple's A-series (iPhone) and M-series (Mac) chips"),
    ("TSM",   "QCOM",  "supplies_to",    0.85, "TSMC fabricates Snapdragon mobile SoCs"),
    ("TSM",   "AVGO",  "supplies_to",    0.8,  "TSMC fabricates Broadcom networking and RF chips"),
    ("INTC",  "MSFT",  "supplies_to",    0.6,  "Intel CPUs in a significant share of Azure servers and Surface devices"),
    ("INTC",  "DELL",  "supplies_to",    0.7,  "Intel CPUs in Dell servers and PCs"),
    ("INTC",  "HPE",   "supplies_to",    0.7,  "Intel CPUs in HPE ProLiant servers"),

    # Fabless → end customers (AI/cloud)
    ("NVDA",  "MSFT",  "supplies_to",    0.85, "NVIDIA H100/H200 GPUs power Azure AI and OpenAI infrastructure"),
    ("NVDA",  "GOOGL", "supplies_to",    0.8,  "NVIDIA GPUs in Google Cloud and DeepMind training clusters"),
    ("NVDA",  "META",  "supplies_to",    0.8,  "Meta's AI training (Llama models) runs on NVIDIA clusters"),
    ("NVDA",  "AMZN",  "supplies_to",    0.75, "AWS uses NVIDIA GPUs for EC2 accelerated instances"),
    ("NVDA",  "ORCL",  "supplies_to",    0.6,  "Oracle Cloud Infrastructure deploys NVIDIA GPUs"),
    ("AMD",   "MSFT",  "supplies_to",    0.65, "AMD Instinct MI300 GPUs in Azure; EPYC CPUs in Azure servers"),
    ("AMD",   "META",  "supplies_to",    0.55, "Meta testing AMD AI accelerators as NVIDIA alternative"),
    ("AMD",   "GOOGL", "supplies_to",    0.5,  "Google Cloud offers AMD EPYC instances"),
    ("QCOM",  "AAPL",  "supplies_to",    0.6,  "Qualcomm supplies 5G modems to iPhone (transitioning to Apple in-house)"),
    ("AVGO",  "AAPL",  "supplies_to",    0.8,  "Broadcom supplies WiFi/Bluetooth chips and custom AI accelerators to Apple"),
    ("AVGO",  "GOOGL", "supplies_to",    0.7,  "Broadcom develops custom AI TPU chips for Google"),

    # Memory
    ("MU",    "DELL",  "supplies_to",    0.6,  "Micron DRAM and NAND in Dell servers and PCs"),
    ("MU",    "HPE",   "supplies_to",    0.6,  "Micron memory in HPE server platforms"),
    ("MU",    "NVDA",  "supplies_to",    0.7,  "Micron HBM (High Bandwidth Memory) in NVIDIA AI GPUs"),

    # Networking
    ("ANET",  "MSFT",  "supplies_to",    0.85, "Arista is a top networking vendor for Azure hyperscale data centers"),
    ("ANET",  "META",  "supplies_to",    0.8,  "Arista switches backbone Meta's data center networks"),
    ("ANET",  "GOOGL", "supplies_to",    0.6,  "Arista networking in Google Cloud"),
    ("ANET",  "AMZN",  "supplies_to",    0.55, "Arista in AWS data center deployments"),
    ("CSCO",  "T",     "supplies_to",    0.6,  "Cisco routers/switches in AT&T's network infrastructure"),
    ("CSCO",  "VZ",    "supplies_to",    0.6,  "Cisco networking gear in Verizon infrastructure"),

    # ── CLOUD / AI INFRASTRUCTURE ───────────────────────────────���───────────
    ("EQIX",  "MSFT",  "supplies_to",    0.75, "Equinix data centers colocate Azure infrastructure globally"),
    ("EQIX",  "AMZN",  "supplies_to",    0.75, "Equinix colocates AWS direct connect and edge nodes"),
    ("EQIX",  "GOOGL", "supplies_to",    0.7,  "Equinix data centers host Google Cloud interconnects"),
    ("EQIX",  "META",  "supplies_to",    0.6,  "Equinix colocates Meta's distributed infrastructure"),
    ("DLR",   "MSFT",  "supplies_to",    0.65, "Digital Realty data centers leased to Microsoft"),
    ("DLR",   "AMZN",  "supplies_to",    0.6,  "Digital Realty wholesale data center space for AWS"),
    ("AMT",   "T",     "supplies_to",    0.85, "American Tower cell towers leased to AT&T (largest tenant)"),
    ("AMT",   "VZ",    "supplies_to",    0.85, "American Tower towers leased to Verizon"),
    ("AMT",   "TMUS",  "supplies_to",    0.8,  "American Tower towers leased to T-Mobile"),
    ("CCI",   "T",     "supplies_to",    0.8,  "Crown Castle towers and fiber leased to AT&T"),
    ("CCI",   "VZ",    "supplies_to",    0.8,  "Crown Castle towers leased to Verizon"),
    ("CCI",   "TMUS",  "supplies_to",    0.75, "Crown Castle towers leased to T-Mobile"),

    # ── MOBILE / CONSUMER ELECTRONICS ───────────────────────────────────────
    ("AAPL",  "QCOM",  "major_customer", 0.8,  "Apple is Qualcomm's largest 5G modem customer (multi-year agreement)"),
    ("AAPL",  "AVGO",  "major_customer", 0.75, "Apple accounts for ~20% of Broadcom revenue"),
    ("AAPL",  "AMAT",  "major_customer", 0.4,  "Apple indirectly drives AMAT demand via TSMC capacity buildout"),

    # ── ENTERPRISE SOFTWARE ──────────────────────────────────────────────────
    ("CRM",   "MSFT",  "competes_with",  0.7,  "Salesforce CRM vs Microsoft Dynamics 365"),
    ("CRM",   "ORCL",  "competes_with",  0.6,  "Salesforce vs Oracle CX/Siebel"),
    ("NOW",   "MSFT",  "competes_with",  0.6,  "ServiceNow ITSM vs Microsoft IT tools"),
    ("WDAY",  "ORCL",  "competes_with",  0.75, "Workday HCM/ERP vs Oracle HCM Cloud"),
    ("WDAY",  "SAP",   "competes_with",  0.8,  "Workday vs SAP SuccessFactors in HR cloud"),
    ("ORCL",  "MSFT",  "competes_with",  0.65, "Oracle Database vs SQL Server; OCI vs Azure"),
    ("ACN",   "IBM",   "competes_with",  0.7,  "Accenture vs IBM consulting and IT services"),
    ("CTSH",  "ACN",   "competes_with",  0.65, "Cognizant vs Accenture IT services"),

    # ── PAYMENTS ────────────────────────────────────────────────────────────
    ("V",     "MA",    "competes_with",  0.95, "Visa vs Mastercard — direct global payment network duopoly"),
    ("V",     "AXP",   "competes_with",  0.7,  "Visa vs Amex in US credit card payments"),
    ("MA",    "AXP",   "competes_with",  0.7,  "Mastercard vs Amex in credit cards"),
    ("PYPL",  "V",     "competes_with",  0.6,  "PayPal digital wallet competes with Visa in online payments"),
    ("PYPL",  "MA",    "competes_with",  0.6,  "PayPal vs Mastercard in digital payments"),
    ("FIS",   "FISV",  "competes_with",  0.8,  "FIS vs Fiserv in financial technology/processing"),
    ("FIS",   "GPN",   "competes_with",  0.7,  "FIS vs Global Payments in merchant acquiring"),
    ("FISV",  "GPN",   "competes_with",  0.7,  "Fiserv vs Global Payments in merchant services"),

    # ── BANKING ─────────────────────────────────────────────────────────────
    ("JPM",   "BAC",   "competes_with",  0.9,  "JPMorgan vs Bank of America — largest US banks"),
    ("JPM",   "WFC",   "competes_with",  0.85, "JPMorgan vs Wells Fargo in consumer/commercial banking"),
    ("JPM",   "C",     "competes_with",  0.8,  "JPMorgan vs Citigroup in global banking"),
    ("JPM",   "GS",    "competes_with",  0.75, "JPMorgan vs Goldman Sachs in investment banking"),
    ("JPM",   "MS",    "competes_with",  0.7,  "JPMorgan vs Morgan Stanley in wealth management and IB"),
    ("BAC",   "WFC",   "competes_with",  0.85, "Bank of America vs Wells Fargo in US retail banking"),
    ("BAC",   "C",     "competes_with",  0.8,  "Bank of America vs Citigroup"),
    ("GS",    "MS",    "competes_with",  0.9,  "Goldman Sachs vs Morgan Stanley — investment banking / wealth"),
    ("SPGI",  "MCO",   "competes_with",  0.95, "S&P Global vs Moody's — credit ratings duopoly"),
    ("ICE",   "CME",   "competes_with",  0.85, "Intercontinental Exchange vs CME Group — futures/derivatives exchanges"),
    ("BLK",   "STT",   "competes_with",  0.7,  "BlackRock vs State Street in institutional asset management and ETFs"),

    # ── HEALTH INSURANCE ────────────────────────────────────────────────────
    ("UNH",   "CVS",   "competes_with",  0.85, "UnitedHealth (Optum) vs CVS (Aetna) in managed care"),
    ("UNH",   "CI",    "competes_with",  0.8,  "UnitedHealth vs Cigna in commercial health insurance"),
    ("UNH",   "HUM",   "competes_with",  0.75, "UnitedHealth vs Humana in Medicare Advantage"),
    ("UNH",   "ELV",   "competes_with",  0.8,  "UnitedHealth vs Elevance (Anthem) in managed care"),
    ("CVS",   "CI",    "competes_with",  0.7,  "CVS/Aetna vs Cigna in employer health plans"),
    ("CVS",   "ELV",   "competes_with",  0.75, "CVS/Aetna vs Elevance in commercial insurance"),
    ("HUM",   "ELV",   "competes_with",  0.7,  "Humana vs Elevance in Medicare and commercial insurance"),

    # ── PHARMACEUTICALS / BIOTECH ────────────────────────────────────────────
    # GLP-1 / obesity drugs
    ("LLY",   "NVO",   "competes_with",  0.95, "Eli Lilly (Zepbound/Mounjaro) vs Novo Nordisk (Ozempic/Wegovy) — GLP-1 duopoly"),
    # Oncology/immunology
    ("ABBV",  "LLY",   "competes_with",  0.6,  "AbbVie vs Eli Lilly in immunology (JAK inhibitors)"),
    ("ABBV",  "MRK",   "competes_with",  0.7,  "AbbVie vs Merck in oncology and immunology"),
    ("ABBV",  "PFE",   "competes_with",  0.65, "AbbVie vs Pfizer in immunology and oncology"),
    ("MRK",   "PFE",   "competes_with",  0.8,  "Merck vs Pfizer — broad pharma competition (vaccines, oncology)"),
    ("MRK",   "BMY",   "competes_with",  0.75, "Merck Keytruda vs BMS Opdivo — checkpoint inhibitor rivalry"),
    ("PFE",   "BMY",   "competes_with",  0.7,  "Pfizer vs Bristol-Myers Squibb in oncology"),
    ("AMGN",  "ABBV",  "competes_with",  0.65, "Amgen vs AbbVie in biosimilars and immunology"),
    ("AMGN",  "REGN",  "competes_with",  0.65, "Amgen vs Regeneron in biologics"),
    ("VRTX",  "AMGN",  "competes_with",  0.4,  "Vertex vs Amgen in rare disease biologics"),

    # CRO / life sciences tools
    ("TMO",   "DHR",   "competes_with",  0.8,  "Thermo Fisher vs Danaher in life science instruments and reagents"),
    ("TMO",   "A",     "competes_with",  0.7,  "Thermo Fisher vs Agilent in analytical instruments"),
    ("DHR",   "A",     "competes_with",  0.65, "Danaher vs Agilent in life science tools"),
    ("IQV",   "CRL",   "competes_with",  0.8,  "IQVIA vs Charles River Laboratories in clinical research outsourcing"),

    # Medtech
    ("MDT",   "ABT",   "competes_with",  0.8,  "Medtronic vs Abbott in cardiac devices and diagnostics"),
    ("MDT",   "BSX",   "competes_with",  0.85, "Medtronic vs Boston Scientific in interventional cardiology"),
    ("MDT",   "SYK",   "competes_with",  0.7,  "Medtronic vs Stryker in orthopedics and neuro"),
    ("ABT",   "BSX",   "competes_with",  0.75, "Abbott vs Boston Scientific in electrophysiology"),
    ("SYK",   "ZBH",   "competes_with",  0.8,  "Stryker vs Zimmer Biomet in orthopedic implants"),
    ("SYK",   "BSX",   "competes_with",  0.65, "Stryker vs Boston Scientific across surgical devices"),

    # ── ENERGY SUPPLY CHAIN ──────────────────────────────────────────────────
    # E&P
    ("XOM",   "CVX",   "competes_with",  0.9,  "ExxonMobil vs Chevron — integrated oil majors"),
    ("XOM",   "COP",   "competes_with",  0.75, "ExxonMobil vs ConocoPhillips in E&P"),
    ("CVX",   "COP",   "competes_with",  0.75, "Chevron vs ConocoPhillips in upstream oil"),
    ("COP",   "EOG",   "competes_with",  0.8,  "ConocoPhillips vs EOG Resources in US shale E&P"),
    ("COP",   "DVN",   "competes_with",  0.75, "ConocoPhillips vs Devon Energy in US shale"),
    ("EOG",   "DVN",   "competes_with",  0.8,  "EOG vs Devon Energy in Permian/Eagle Ford shale"),
    # Oilfield services (revenue tied to E&P capex)
    ("SLB",   "XOM",   "major_customer", 0.5,  "ExxonMobil is a major SLB services customer globally"),
    ("SLB",   "CVX",   "major_customer", 0.5,  "Chevron is a top SLB oilfield services customer"),
    ("SLB",   "HAL",   "competes_with",  0.9,  "Schlumberger vs Halliburton — oilfield services duopoly"),
    ("SLB",   "BKR",   "competes_with",  0.75, "Schlumberger vs Baker Hughes in oilfield services"),
    ("HAL",   "BKR",   "competes_with",  0.8,  "Halliburton vs Baker Hughes in completion services"),
    # Refiners (buy crude, sell gasoline/diesel)
    ("PSX",   "MPC",   "competes_with",  0.85, "Phillips 66 vs Marathon Petroleum in US refining"),
    ("PSX",   "VLO",   "competes_with",  0.85, "Phillips 66 vs Valero in refining and marketing"),
    ("MPC",   "VLO",   "competes_with",  0.85, "Marathon vs Valero — large US independent refiners"),
    # Midstream (pipelines)
    ("KMI",   "WMB",   "competes_with",  0.8,  "Kinder Morgan vs Williams Companies in natural gas pipelines"),
    ("KMI",   "OKE",   "competes_with",  0.75, "Kinder Morgan vs ONEOK in gas gathering and transport"),
    ("WMB",   "OKE",   "competes_with",  0.75, "Williams vs ONEOK in natural gas midstream"),

    # ── DEFENSE ──────────────────────────────────────────────────────────────
    ("LMT",   "RTX",   "competes_with",  0.85, "Lockheed Martin vs RTX in fighter jets, missiles, space"),
    ("LMT",   "NOC",   "competes_with",  0.8,  "Lockheed vs Northrop Grumman in advanced defense systems"),
    ("LMT",   "GD",    "competes_with",  0.75, "Lockheed vs General Dynamics in defense platforms"),
    ("RTX",   "NOC",   "competes_with",  0.75, "RTX vs Northrop in missiles, sensors, and air defense"),
    ("RTX",   "GD",    "competes_with",  0.7,  "RTX vs General Dynamics in defense electronics"),
    ("NOC",   "GD",    "competes_with",  0.75, "Northrop vs General Dynamics in cyber, ships, and systems"),
    # Defense supply chain: airlines / aerospace
    ("GE",    "RTX",   "competes_with",  0.8,  "GE Aerospace vs Pratt & Whitney (RTX) in commercial jet engines"),
    ("GE",    "BA",    "supplies_to",    0.7,  "GE Aerospace engines on Boeing's 737 MAX and wide-body jets"),
    ("RTX",   "BA",    "supplies_to",    0.7,  "Pratt & Whitney (RTX) engines on Boeing and Airbus aircraft"),
    ("BA",    "UAL",   "supplies_to",    0.75, "Boeing aircraft in United Airlines fleet"),
    ("BA",    "DAL",   "supplies_to",    0.65, "Boeing aircraft in Delta fleet"),
    ("BA",    "LUV",   "supplies_to",    0.95, "Southwest flies exclusively Boeing 737s"),
    ("BA",    "AAL",   "supplies_to",    0.75, "Boeing aircraft in American Airlines fleet"),

    # ── RETAIL / CONSUMER STAPLES ────────────────────────────────────────────
    ("WMT",   "COST",  "competes_with",  0.8,  "Walmart vs Costco in mass-market retail"),
    ("WMT",   "TGT",   "competes_with",  0.85, "Walmart vs Target in US discount retail"),
    ("WMT",   "AMZN",  "competes_with",  0.85, "Walmart vs Amazon in e-commerce and retail"),
    ("COST",  "TGT",   "competes_with",  0.7,  "Costco vs Target in household goods"),
    ("COST",  "AMZN",  "competes_with",  0.7,  "Costco vs Amazon Prime in subscription retail"),
    ("TGT",   "AMZN",  "competes_with",  0.8,  "Target vs Amazon in general merchandise"),
    ("KR",    "WMT",   "competes_with",  0.8,  "Kroger vs Walmart in grocery"),
    ("KR",    "COST",  "competes_with",  0.65, "Kroger vs Costco in grocery and fresh food"),

    # ── CONSUMER STAPLES BRANDS ──────────────────────────────────────────────
    ("KO",    "PEP",   "competes_with",  0.95, "Coca-Cola vs PepsiCo — direct beverage rivalry"),
    ("PG",    "CL",    "competes_with",  0.8,  "Procter & Gamble vs Colgate-Palmolive in personal care"),
    ("PG",    "KMB",   "competes_with",  0.75, "P&G vs Kimberly-Clark in household products"),
    ("MO",    "PM",    "competes_with",  0.85, "Altria (US Marlboro) vs Philip Morris International"),
    ("MO",    "PM",    "strategic_partner", 0.8, "Altria and PMI share Marlboro brand rights (US vs international)"),
    ("MDLZ",  "GIS",   "competes_with",  0.7,  "Mondelez vs General Mills in packaged snacks and cereals"),
    ("MDLZ",  "HSY",   "competes_with",  0.75, "Mondelez vs Hershey in chocolate and confectionery"),
    ("HSY",   "GIS",   "competes_with",  0.5,  "Hershey vs General Mills in snack foods"),

    # ── FOOD SERVICE / RESTAURANTS ───────────────────────────────────────────
    ("MCD",   "YUM",   "competes_with",  0.8,  "McDonald's vs Yum! Brands (KFC/Taco Bell/Pizza Hut) in QSR"),
    ("MCD",   "SBUX",  "competes_with",  0.6,  "McDonald's (McCafé) vs Starbucks in breakfast and coffee"),
    ("MCD",   "CMG",   "competes_with",  0.65, "McDonald's vs Chipotle in fast-casual dining"),
    ("SBUX",  "CMG",   "competes_with",  0.5,  "Starbucks vs Chipotle in fast-casual and digital loyalty"),
    ("YUM",   "CMG",   "competes_with",  0.6,  "Yum! Brands vs Chipotle in fast-casual Mexican food"),

    # ── MEDIA / STREAMING ────────────────────────────────────────────────────
    ("NFLX",  "DIS",   "competes_with",  0.85, "Netflix vs Disney+ in streaming"),
    ("NFLX",  "CMCSA", "competes_with",  0.7,  "Netflix vs Peacock (Comcast) in streaming"),
    ("NFLX",  "WBD",   "competes_with",  0.75, "Netflix vs Max (Warner Bros Discovery) in streaming"),
    ("NFLX",  "AMZN",  "competes_with",  0.7,  "Netflix vs Amazon Prime Video in streaming"),
    ("DIS",   "CMCSA", "competes_with",  0.75, "Disney vs Comcast/NBCUniversal in content and theme parks"),
    ("DIS",   "WBD",   "competes_with",  0.7,  "Disney vs Warner Bros Discovery in content and streaming"),
    ("PARA",  "WBD",   "competes_with",  0.7,  "Paramount+ vs Max in streaming"),
    ("PARA",  "NFLX",  "competes_with",  0.6,  "Paramount vs Netflix in streaming content"),

    # ── TELECOM ──────────────────────────────────────────────────────────────
    ("T",     "VZ",    "competes_with",  0.9,  "AT&T vs Verizon — major US wireless carriers"),
    ("T",     "TMUS",  "competes_with",  0.9,  "AT&T vs T-Mobile in wireless subscribers"),
    ("VZ",    "TMUS",  "competes_with",  0.9,  "Verizon vs T-Mobile in 5G network competition"),
    ("CMCSA", "CHTR",  "competes_with",  0.85, "Comcast vs Charter in US cable/broadband"),
    ("CMCSA", "T",     "competes_with",  0.6,  "Comcast broadband vs AT&T Fiber in home internet"),

    # ── SEARCH / ADVERTISING ───────────────────────��────────────────────────
    ("GOOGL", "META",  "competes_with",  0.85, "Alphabet vs Meta in digital advertising"),
    ("GOOGL", "MSFT",  "competes_with",  0.7,  "Google Search vs Microsoft Bing in search and AI assistants"),
    ("GOOGL", "AMZN",  "competes_with",  0.65, "Google Cloud vs AWS; YouTube vs Prime Video"),
    ("META",  "SNAP",  "competes_with",  0.7,  "Meta (Instagram/WhatsApp) vs Snap in social media"),
    ("META",  "PINS",  "competes_with",  0.6,  "Meta vs Pinterest in visual social media and advertising"),

    # ── TRAVEL / HOSPITALITY ─────────────────────────────────────────────────
    ("BKNG",  "EXPE",  "competes_with",  0.9,  "Booking Holdings vs Expedia in online travel agencies"),
    ("BKNG",  "ABNB",  "competes_with",  0.7,  "Booking vs Airbnb in short-term accommodation"),
    ("EXPE",  "ABNB",  "competes_with",  0.65, "Expedia vs Airbnb in alternative accommodations"),
    ("MAR",   "HLT",   "competes_with",  0.9,  "Marriott vs Hilton in global hotel chains"),

    # ── AIRLINES (compete + share macro fuel exposure) ────────────────────��──
    ("UAL",   "DAL",   "competes_with",  0.85, "United vs Delta in major US legacy carriers"),
    ("UAL",   "AAL",   "competes_with",  0.85, "United vs American Airlines"),
    ("DAL",   "AAL",   "competes_with",  0.85, "Delta vs American Airlines"),
    ("LUV",   "UAL",   "competes_with",  0.7,  "Southwest vs United in domestic routes"),
    ("LUV",   "DAL",   "competes_with",  0.7,  "Southwest vs Delta in domestic routes"),

    # ── AUTOMOTIVE / EV ─────────────────────────────��────────────────────────
    ("TSLA",  "F",     "competes_with",  0.8,  "Tesla vs Ford in EV market — Mustang Mach-E vs Model Y"),
    ("TSLA",  "GM",    "competes_with",  0.8,  "Tesla vs General Motors in EV transition"),
    ("F",     "GM",    "competes_with",  0.9,  "Ford vs GM in US automotive market"),

    # ── HOME IMPROVEMENT / CONSTRUCTION ─────────────────────────────────────
    ("HD",    "LOW",   "competes_with",  0.95, "Home Depot vs Lowe's — home improvement retail duopoly"),

    # ── APPAREL / ATHLETIC ───────────────────────────────────────────────────
    ("NKE",   "LULU",  "competes_with",  0.75, "Nike vs Lululemon in premium athletic apparel"),
    ("NKE",   "UA",    "competes_with",  0.7,  "Nike vs Under Armour in performance sportswear"),
    ("LULU",  "UA",    "competes_with",  0.7,  "Lululemon vs Under Armour in athletic apparel"),

    # ── INDUSTRIALS / RAILROADS ──────────────────────────────────────────────
    ("UNP",   "CSX",   "competes_with",  0.8,  "Union Pacific vs CSX in US Class I railroads"),
    ("UNP",   "NSC",   "competes_with",  0.8,  "Union Pacific vs Norfolk Southern"),
    ("CSX",   "NSC",   "competes_with",  0.85, "CSX vs Norfolk Southern in Eastern US rail freight"),

    # ── LOGISTICS ──────────────────────────────────────────────────────────���─
    ("FDX",   "UPS",   "competes_with",  0.9,  "FedEx vs UPS in express and ground parcel delivery"),
    ("FDX",   "AMZN",  "competes_with",  0.65, "FedEx vs Amazon Logistics in last-mile delivery"),
    ("UPS",   "AMZN",  "competes_with",  0.65, "UPS vs Amazon Logistics; Amazon is also a UPS customer"),

    # ── DIVERSIFIED INDUSTRIALS ──────────────────────────────────────────────
    ("HON",   "MMM",   "competes_with",  0.7,  "Honeywell vs 3M in industrial and specialty materials"),
    ("HON",   "EMR",   "competes_with",  0.75, "Honeywell vs Emerson Electric in process automation"),
    ("HON",   "ROK",   "competes_with",  0.7,  "Honeywell vs Rockwell Automation in factory automation"),
    ("EMR",   "ROK",   "competes_with",  0.8,  "Emerson vs Rockwell Automation in industrial control systems"),
    ("CAT",   "DE",    "competes_with",  0.6,  "Caterpillar vs Deere in heavy equipment (construction overlap)"),

    # ── UTILITIES ────────────────────────────────────────────────────────────
    ("NEE",   "DUK",   "competes_with",  0.7,  "NextEra vs Duke Energy — large US utilities"),
    ("NEE",   "SO",    "competes_with",  0.65, "NextEra vs Southern Company"),
    ("DUK",   "SO",    "competes_with",  0.75, "Duke Energy vs Southern Company in Southeast utility territory"),
    ("NEE",   "D",     "competes_with",  0.6,  "NextEra vs Dominion Energy"),

    # ── MATERIALS ────────────────────────────────────────────────────────────
    ("LIN",   "APD",   "competes_with",  0.9,  "Linde vs Air Products — industrial gases duopoly"),
    ("NEM",   "GOLD",  "competes_with",  0.9,  "Newmont vs Barrick Gold — largest gold miners"),
    ("FCX",   "SCCO",  "competes_with",  0.85, "Freeport-McMoRan vs Southern Copper in copper mining"),
    ("DOW",   "LYB",   "competes_with",  0.8,  "Dow vs LyondellBasell in commodity chemicals"),
    ("DOW",   "DD",    "competes_with",  0.7,  "Dow vs DuPont in specialty and commodity chemicals"),

    # ── REAL ESTATE (REITs) ──────────────────────────────────────────────────
    ("AMT",   "CCI",   "competes_with",  0.9,  "American Tower vs Crown Castle — cell tower REIT duopoly"),
    ("EQIX",  "DLR",   "competes_with",  0.85, "Equinix vs Digital Realty — data center REIT rivalry"),

    # ── INDEX / RATING AGENCIES ─────────────────────────────────────────────���
    ("SPGI",  "MCO",   "competes_with",  0.95, "S&P Global vs Moody's — bond rating and data duopoly"),
    ("SPGI",  "MSCI",  "competes_with",  0.6,  "S&P Global vs MSCI in financial indices and analytics"),
]
