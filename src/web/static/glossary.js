// Plain-English glossary for first-year investors.
// Click any underlined term in a brief to see the definition.

const GLOSSARY = {
  "market cap": "The total dollar value of a company's shares. Share price × number of shares outstanding. A rough measure of company size.",
  "large-cap": "A company worth more than about $10 billion. Generally more stable, slower-growing.",
  "mid-cap": "A company worth roughly $2–10 billion. Between large-cap stability and small-cap growth.",
  "small-cap": "A company worth less than about $2 billion. Often more volatile, with more room to grow or fail.",
  "volatility": "How much a stock's price swings up and down. High volatility means bigger moves in both directions.",
  "beta": "How much a stock moves compared to the overall market. Beta of 1 moves with the market; 1.5 is 50% more jumpy; 0.5 is half as jumpy.",
  "eps": "Earnings per share — the company's profit divided by its number of shares. Higher is generally better.",
  "revenue": "The total money a company brought in from sales before subtracting any costs. Also called the 'top line.'",
  "net income": "A company's profit after subtracting all costs and taxes. Also called the 'bottom line.'",
  "guidance": "The company's own estimate of future revenue or profit. Raised guidance usually lifts the stock; cut guidance usually drags it down.",
  "forward p/e": "Price-to-earnings ratio using expected future profits. Tells you how much investors are paying today for each dollar of expected earnings.",
  "p/e ratio": "Price divided by earnings per share. A rough measure of how expensive a stock is relative to its profits.",
  "price-to-earnings": "Stock price divided by earnings per share. A rough measure of how expensive a stock is relative to its profits.",
  "hyperscaler": "A very large cloud computing provider like Amazon AWS, Microsoft Azure, or Google Cloud. Big buyers of AI chips and data-center gear.",
  "hyperscalers": "Very large cloud computing providers like Amazon AWS, Microsoft Azure, and Google Cloud. Big buyers of AI chips and data-center gear.",
  "analyst consensus": "The average opinion of Wall Street analysts who cover a stock — usually their combined estimates of future earnings or price targets.",
  "price target": "An analyst's estimate of where a stock's price will be in about 12 months. Not a guarantee, just an informed guess.",
  "upgrade": "When an analyst raises their rating on a stock (e.g. from hold to buy). Often moves the price short-term.",
  "downgrade": "When an analyst lowers their rating on a stock. Often pushes the price down short-term.",
  "buyback": "When a company uses its own cash to buy back its own shares. Reduces share count, which tends to lift earnings per share.",
  "share buyback": "When a company uses its own cash to buy back its own shares. Reduces share count, which tends to lift earnings per share.",
  "dividend": "A regular cash payment a company makes to its shareholders, usually quarterly. Expressed as dollars per share.",
  "dividend yield": "Annual dividend divided by the stock price, shown as a percent. Roughly what you'd earn in cash per year from the dividend alone.",
  "ipo": "Initial public offering — when a private company first sells shares to the public.",
  "10-k": "A company's annual report filed with the SEC. The most detailed disclosure of financials, risks, and strategy.",
  "10-q": "A company's quarterly report filed with the SEC. Less detailed than a 10-K but still unaudited financials.",
  "8-k": "A filing companies submit when something material happens between quarterly reports — CEO change, acquisition, big contract.",
  "gross margin": "Revenue minus the direct cost of making the product, shown as a percent of revenue. Higher = more pricing power.",
  "operating margin": "Profit from core operations as a percent of revenue, before interest and taxes. A measure of operational efficiency.",
  "free cash flow": "Cash a company generates after paying to run and maintain the business. What's left over for dividends, buybacks, or growth.",
  "fed": "The U.S. Federal Reserve — the central bank. Sets short-term interest rates, which ripple through the whole economy and stock market.",
  "federal reserve": "The U.S. central bank. Sets short-term interest rates, which ripple through the whole economy and stock market.",
  "inflation": "The rate at which prices of goods and services rise over time. High inflation often leads the Fed to raise rates, which tends to pressure stocks.",
  "cpi": "Consumer Price Index — the main U.S. inflation gauge. Reported monthly, watched closely by markets.",
  "10-year yield": "The interest rate on 10-year U.S. government bonds. A benchmark for long-term borrowing costs and a key rival to stocks.",
  "yield curve": "The chart of interest rates across bond maturities. When short rates exceed long rates ('inverted'), it's often a recession signal.",
  "insider buying": "When executives or directors buy their own company's stock. Often read as a confidence signal, since insiders know the business best.",
  "insider selling": "When executives or directors sell their own company's stock. Can be routine (scheduled plans) or a warning sign — context matters.",
  "drawdown": "The drop from a stock's peak to its low point. A '30% drawdown' means the price fell 30% from its high.",
  "max drawdown": "The biggest peak-to-trough drop in a stock's price over a given period. A measure of worst-case pain.",
  "sharpe ratio": "A measure of how much return a stock gave per unit of risk taken. Higher is better; above 1 is generally solid.",
  "moat": "A company's durable competitive advantage — brand, scale, switching costs — that keeps rivals from eating its lunch.",
  "float": "The number of shares actually available for the public to trade, excluding shares held by insiders and major stakeholders.",
  "short interest": "The percent of a stock's float that's been sold short (bet against). High short interest can fuel sharp squeezes up or down.",
  "earnings": "A company's profits for a period. Reported quarterly; the stock usually reacts hard to surprises vs. estimates.",
  "earnings beat": "When a company reports earnings higher than analysts expected. Usually a positive catalyst.",
  "earnings miss": "When a company reports earnings lower than analysts expected. Usually a negative catalyst.",
  "catalyst": "An event that moves a stock — earnings, a product launch, a regulatory decision, a macro data release.",
  "sector": "A broad category of businesses (Technology, Healthcare, Energy, etc.). Stocks in the same sector often move together.",
  "index": "A basket of stocks used as a benchmark, like the S&P 500 (500 biggest U.S. companies). Used to gauge 'the market' as a whole.",
  "s&p 500": "An index of the 500 largest U.S. public companies. The standard benchmark for U.S. stocks as a whole.",
  "etf": "Exchange-traded fund — a basket of stocks (or bonds) that trades like a single stock. Cheap way to buy broad exposure.",
  "bull market": "A period of rising stock prices, usually defined as a 20%+ gain from recent lows.",
  "bear market": "A period of falling stock prices, usually defined as a 20%+ drop from recent highs.",
  "correction": "A drop of 10%+ from recent highs. Less severe than a bear market.",
  "cost basis": "What you originally paid for a stock, per share. Used to calculate your gain or loss when you sell.",
  "unrealized p&l": "Paper gain or loss on stocks you still hold. Becomes real only when you sell.",
  "realized p&l": "Gain or loss you've locked in by selling. What actually shows up on your taxes.",
  "valuation": "How expensive a stock looks relative to its earnings, revenue, or cash flow. High valuation = priced for a lot of future growth.",
  "overvalued": "Priced above what the underlying business seems to justify, by some measure. A subjective judgment.",
  "undervalued": "Priced below what the underlying business seems to justify. Again subjective, depends on the measure used.",
};

// Walk text nodes under rootEl and wrap the FIRST occurrence of each glossary
// term (case-insensitive, word-boundary) in a <span class="gloss-term">.
function annotateGlossary(rootEl) {
  if (!rootEl) return;

  const terms = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
  const used = new Set();
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function collectTextNodes(node) {
    const out = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        let p = n.parentNode;
        while (p && p !== node.parentNode) {
          const tag = (p.tagName || '').toLowerCase();
          if (tag === 'a' || tag === 'code' || tag === 'pre' || tag === 'script' || tag === 'style') return NodeFilter.FILTER_REJECT;
          if (p.classList && p.classList.contains('gloss-term')) return NodeFilter.FILTER_REJECT;
          if (p === rootEl) break;
          p = p.parentNode;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    let cur;
    while ((cur = walker.nextNode())) out.push(cur);
    return out;
  }

  const queue = collectTextNodes(rootEl);

  while (queue.length) {
    const node = queue.shift();
    if (!node.parentNode) continue;
    const text = node.nodeValue;

    let best = null;
    for (const term of terms) {
      if (used.has(term)) continue;
      const re = new RegExp('(^|[^A-Za-z0-9])(' + escRe(term) + ')(?=$|[^A-Za-z0-9])', 'i');
      const m = text.match(re);
      if (!m) continue;
      const idx = m.index + m[1].length;
      if (!best || idx < best.idx) best = { term, idx, len: m[2].length, match: m[2] };
    }
    if (!best) continue;

    const before = text.slice(0, best.idx);
    const matched = text.slice(best.idx, best.idx + best.len);
    const after = text.slice(best.idx + best.len);

    const span = document.createElement('span');
    span.className = 'gloss-term';
    span.dataset.term = best.term;
    span.textContent = matched;

    const frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    frag.appendChild(span);
    const tail = document.createTextNode(after);
    frag.appendChild(tail);

    node.parentNode.replaceChild(frag, node);
    used.add(best.term);

    if (after) queue.push(tail);
  }
}

// Click handling — one delegated listener, one live popover.
function installGlossaryPopover() {
  if (window.__glossPopoverInstalled) return;
  window.__glossPopoverInstalled = true;

  let current = null;

  function close() {
    if (current) { current.remove(); current = null; }
  }

  document.addEventListener('click', (e) => {
    const term = e.target.closest && e.target.closest('.gloss-term');
    if (!term) { close(); return; }
    e.preventDefault();
    e.stopPropagation();
    close();

    const key = term.dataset.term;
    const defn = GLOSSARY[key];
    if (!defn) return;

    const pop = document.createElement('div');
    pop.className = 'gloss-popover';
    pop.innerHTML = `
      <button class="gloss-close" aria-label="Close">×</button>
      <div class="gloss-popover-term"></div>
      <div class="gloss-popover-defn"></div>
    `;
    pop.querySelector('.gloss-popover-term').textContent = term.textContent;
    pop.querySelector('.gloss-popover-defn').textContent = defn;
    document.body.appendChild(pop);

    const r = term.getBoundingClientRect();
    const pw = Math.min(320, window.innerWidth - 24);
    pop.style.width = pw + 'px';
    // Position above the term, clamped within viewport
    let left = r.left + window.scrollX + r.width / 2 - pw / 2;
    left = Math.max(12 + window.scrollX, Math.min(left, window.scrollX + window.innerWidth - pw - 12));
    const ph = pop.offsetHeight;
    let top = r.top + window.scrollY - ph - 10;
    if (top < window.scrollY + 8) top = r.bottom + window.scrollY + 10;
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';

    current = pop;
    pop.querySelector('.gloss-close').addEventListener('click', (ev) => {
      ev.stopPropagation();
      close();
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });

  window.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
}

installGlossaryPopover();

window.GLOSSARY = GLOSSARY;
window.annotateGlossary = annotateGlossary;
