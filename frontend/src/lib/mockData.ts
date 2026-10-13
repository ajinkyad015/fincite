import type { FinDocument, SubProcessSource } from "./types";

/* ------------------------------------------------------------------ */
/*  Seeded filings (as returned by GET /api/document/)                 */
/* ------------------------------------------------------------------ */

export const COMPANY_HUE: Record<string, string> = {
  RELIANCE: "#14436e",
  TCS: "#3d2e63",
  HDFCBANK: "#7e1e1b",
  INFY: "#6b5207",
  ITC: "#1e5631",
  DEFAULT: "#2a261a",
};

const ago = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

export const SEED_DOCUMENTS: FinDocument[] = [
  {
    id: "doc_reliance_ar24",
    filename: "reliance-industries-annual-report-fy2023-24.pdf",
    status: "ready",
    progress: 100,
    uploaded_at: ago(60 * 26),
    metadata: {
      company_name: "Reliance Industries Ltd",
      nse_symbol: "RELIANCE",
      document_type: "annual_report",
      fiscal_year: "FY2023-24",
      period: "Apr 2023 – Mar 2024",
      pages: 386,
      file_size: 24_800_000,
      language: "en",
    },
  },
  {
    id: "doc_tcs_ar24",
    filename: "tcs-annual-report-fy2023-24.pdf",
    status: "ready",
    progress: 100,
    uploaded_at: ago(60 * 49),
    metadata: {
      company_name: "Tata Consultancy Services Ltd",
      nse_symbol: "TCS",
      document_type: "annual_report",
      fiscal_year: "FY2023-24",
      period: "Apr 2023 – Mar 2024",
      pages: 268,
      file_size: 18_400_000,
      language: "en",
    },
  },
  {
    id: "doc_hdfcbank_q3fy25",
    filename: "hdfc-bank-q3-fy25-financial-results.pdf",
    status: "ready",
    progress: 100,
    uploaded_at: ago(60 * 5),
    metadata: {
      company_name: "HDFC Bank Ltd",
      nse_symbol: "HDFCBANK",
      document_type: "quarterly_results",
      fiscal_year: "FY2024-25",
      period: "Q3 · Oct – Dec 2024",
      pages: 42,
      file_size: 3_100_000,
      language: "en",
    },
  },
  {
    id: "doc_infy_concall_q2fy25",
    filename: "infosys-q2-fy25-earnings-call-transcript.pdf",
    status: "ready",
    progress: 100,
    uploaded_at: ago(60 * 73),
    metadata: {
      company_name: "Infosys Ltd",
      nse_symbol: "INFY",
      document_type: "concall_transcript",
      fiscal_year: "FY2024-25",
      period: "Q2 · Jul – Sep 2024",
      pages: 18,
      file_size: 940_000,
      language: "en",
    },
  },
  {
    id: "doc_itc_deck_24",
    filename: "itc-investor-presentation-nov-2024.pdf",
    status: "ready",
    progress: 100,
    uploaded_at: ago(60 * 120),
    metadata: {
      company_name: "ITC Ltd",
      nse_symbol: "ITC",
      document_type: "investor_presentation",
      fiscal_year: "FY2024-25",
      period: "H1 FY25 update",
      pages: 64,
      file_size: 7_600_000,
      language: "en",
    },
  },
];

/** Short excerpts used when the answer engine falls back to generic retrieval */
export const FALLBACK_EXCERPT: Record<string, { page: number; excerpt: string }> = {
  doc_reliance_ar24: {
    page: 199,
    excerpt:
      "The Company evaluates segment performance based on operating profit before finance costs, depreciation and exceptional items, measured consistently with the principles used in the consolidated financial statements.",
  },
  doc_tcs_ar24: {
    page: 121,
    excerpt:
      "Cash and cash equivalents comprise balances with banks and short-term deposits with an original maturity of three months or less, which are subject to an insignificant risk of changes in value.",
  },
  doc_hdfcbank_q3fy25: {
    page: 31,
    excerpt:
      "Provisions and contingencies for the quarter ended December 31, 2024 stood at ₹3,154 crore, which includes contingent provisions of approximately ₹800 crore as a matter of prudence.",
  },
  doc_infy_concall_q2fy25: {
    page: 12,
    excerpt:
      "We continue to invest in our sales organisation and in generative AI capabilities, with over 7,500 employees now trained on the Topaz platform across client delivery functions.",
  },
  doc_itc_deck_24: {
    page: 45,
    excerpt:
      "The Company's strategic focus remains on building future-ready portfolios, scaling digital-first capabilities and sustaining best-in-class capital allocation across each operating segment.",
  },
};

/* ------------------------------------------------------------------ */
/*  Research answer bank — matched by intent, cited to page            */
/* ------------------------------------------------------------------ */

export interface PlanStep {
  name: string;
  source: SubProcessSource;
  duration_ms: number;
  detail: string;
}

export interface SourceSeed {
  doc_id: string;
  page: number;
  excerpt: string;
  score: number;
}

export interface CannedAnswer {
  id: string;
  patterns: RegExp[];
  plan: PlanStep[];
  answer: string;
  sources: SourceSeed[];
}

const qp = (chunks: number, docs: number, kept: number): PlanStep[] => [
  {
    name: "Query understanding",
    source: "llm",
    duration_ms: 620,
    detail: "Rewrote question · resolved entities & fiscal periods",
  },
  {
    name: "Hybrid retrieval",
    source: "retrieval",
    duration_ms: 1180,
    detail: `${chunks} chunks from ${docs} document${docs > 1 ? "s" : ""} · dense + BM25`,
  },
  {
    name: "Rerank",
    source: "rerank",
    duration_ms: 740,
    detail: `Cross-encoder kept top ${kept} passages`,
  },
  {
    name: "Answer synthesis",
    source: "llm",
    duration_ms: 0,
    detail: "Grounded generation with inline citation",
  },
];

export const ANSWER_BANK: CannedAnswer[] = [
  {
    id: "reliance_revenue",
    patterns: [/reliance/i, /o2c|jio|retail.*revenue|segment/i],
    plan: qp(21, 3, 5),
    answer: `Reliance Industries reported **consolidated gross revenue of ₹10,00,122 crore (≈ $119.9 bn) for FY24**, up 2.6% year-on-year, with a record consolidated EBITDA of ₹1,78,677 crore (+16.1%) [1]. Profit after tax came in at **₹79,020 crore**, the highest in the company's history [2].

Growth was broad-based across segments, though the mix continues to shift decisively toward consumer businesses:

| Segment | FY24 Revenue (₹ crore) | YoY |
| --- | --- | --- |
| Oil-to-Chemicals (O2C) | 5,64,749 | +0.7% |
| Digital Services (Jio) | 1,32,938 | +11.4% |
| Retail | 3,06,786 | +17.8% |
| Oil & Gas (E&P) | 24,439 | +48.2% |

Retail crossed the **₹3 lakh crore** milestone driven by 1,840 net new store additions (79.1 mn sq ft) [3], while Jio's ARPU improved to **₹181.7/month** as 5G subscriber additions scaled past 108 million [1]. Management flagged oil & gas as the fastest-growing segment on the back of **KG-D6 production ramp-up**, with gas output reaching ~30% of India's domestic production [2].`,
    sources: [
      {
        doc_id: "doc_reliance_ar24",
        page: 132,
        excerpt:
          "Revenue from operations for the year ended March 31, 2024 was ₹10,00,122 crore ($119.9 billion) as compared to ₹9,74,864 crore in the previous year, an increase of 2.6%. EBITDA achieved a record ₹1,78,677 crore, up 16.1% year-on-year.",
        score: 0.94,
      },
      {
        doc_id: "doc_reliance_ar24",
        page: 141,
        excerpt:
          "Profit after tax for FY 2023-24 stood at ₹79,020 crore, higher by 7.3% over the previous year, the highest annual profit recorded by the Company. Oil & Gas segment EBITDA grew 48.2% with KG-D6 field sustaining production ramp-up.",
        score: 0.91,
      },
      {
        doc_id: "doc_reliance_ar24",
        page: 138,
        excerpt:
          "Reliance Retail added 1,840 new stores during the year taking total store count to 18,918 with an area of 79.1 million sq ft. Segment revenue crossed ₹3 lakh crore, registering growth of 17.8% over FY 2022-23.",
        score: 0.88,
      },
    ],
  },
  {
    id: "it_margins",
    patterns: [/tcs/i, /infosys|infy/i, /margin/i, /attrition|utilis|bench/i, /it\s+services|compare.*(tcs|infosys)|guidance/i],
    plan: qp(24, 3, 6),
    answer: `Margins are the clearest fault line between the two IT majors. **TCS held an EBIT margin of 24.6% in FY24 (-50bps YoY)**, while **Infosys operated at 20.7% in Q2 FY25** — a structural gap of roughly 390bps that both attribute to mix, pricing discipline and pyramid optimisation [1][2].

| Metric | TCS (FY24) | Infosys (Q2 FY25) |
| --- | --- | --- |
| Revenue | $29.1 bn | $3.99 bn (quarter) |
| EBIT margin | 24.6% | 20.7% |
| Growth (cc, YoY) | 6.8% | 3.1% |
| LTM attrition | 12.5% | 12.9% |

On the Q2 FY25 call, Infosys' CFO attributed the **20bps sequential margin expansion** to "Project Maximus benefits kicking in" — pricing, critical portfolio choices and lower on-site mix — while cautioning that Q3 carries wage-hike headwinds [2]. Infosys raised FY25 revenue guidance to **3.75–4.5% in constant currency**, retaining its 20–22% margin band [2].

TCS, meanwhile, framed FY24's compression as deliberate: absorbing the third tranche of wage hikes while protecting its long-standing **26–28% band aspiration** through utilisation of 85.1% and a deepening fresher pyramid [1][3]. Both firms signalled that **generative AI deal flow** (TCS: $900 mn pipeline; Infosys: Topaz-led wins) is now priced into large-deal TCV rather than dilutive pilots [1][2].`,
    sources: [
      {
        doc_id: "doc_tcs_ar24",
        page: 88,
        excerpt:
          "Operating margin (EBIT margin) for the year stood at 24.6%, a contraction of 50 basis points over the previous year, as the Company absorbed the full-year impact of salary increments while improving utilisation to 85.1% excluding trainees.",
        score: 0.93,
      },
      {
        doc_id: "doc_infy_concall_q2fy25",
        page: 6,
        excerpt:
          "Margins expanded 20 basis points sequentially to 20.7%, reflecting benefits of pricing, portfolio rationalisation and Project Maximus. We have increased our revenue guidance for FY25 to 3.75%–4.5% in constant currency, retaining the margin guidance of 20%–22%.",
        score: 0.92,
      },
      {
        doc_id: "doc_tcs_ar24",
        page: 92,
        excerpt:
          "The Company added 29,000 fresh graduates during the year, bringing the trainee-heavy pyramid to its most efficient structure since FY20. Long-term EBIT aspiration remains in the 26–28% band.",
        score: 0.84,
      },
    ],
  },
  {
    id: "hdfc_asset_quality",
    patterns: [/hdfc/i, /gnpa|npa|asset quality|slippage|credit cost|provision/i],
    plan: qp(18, 2, 5),
    answer: `HDFC Bank's asset quality **held firm through Q3 FY25**, with credit costs remaining benign despite a full basis-rate cycle passing through the merged book:

- **Gross NPA: 1.42%** of gross advances (vs 1.42% in Q2), stable quarter-on-quarter after the ebb of corp-book seasoning [1].
- **Net NPA: 0.46%** of net advances, with a **provision coverage ratio of ~70%** [1].
- Total slippages for the quarter were **₹8,800 crore**, of which recoveries and upgrades were ₹4,200 crore — implying net slippage of ~₹4,600 crore [2].
- Credit costs (ex-floating provisions) tracked at **~42 bps** annualised [1].

The bank carried **contingent and floating provisions of ₹10,900 crore (~1.6% of loans)** beyond the standard asset requirement, which management described as "a counter-cyclical buffer for the merged balance sheet" [2]. Retail agri and micro-LAP pockets showed the expected seasonal uptick in the 31–90 dpd bucket, but **no material concentration** was flagged in the quarter's disclosure [3].

Net interest margin was steady at **3.43%** (on total assets), and management reiterated that deposit growth of 15.9% YoY is being prioritised over loan growth (7.5% YoY) to normalise the post-merger credit-deposit ratio [1].`,
    sources: [
      {
        doc_id: "doc_hdfcbank_q3fy25",
        page: 9,
        excerpt:
          "Gross non-performing assets were at 1.42% of gross advances as on December 31, 2024 (1.42% as on September 30, 2024). Net non-performing assets were at 0.46% of net advances. Provision coverage ratio stood at 70.3%.",
        score: 0.95,
      },
      {
        doc_id: "doc_hdfcbank_q3fy25",
        page: 11,
        excerpt:
          "The Bank holds floating and contingent provisions of ₹10,900 crore, approximately 1.6% of gross loans, over and above regulatory requirements. Total slippages in the quarter were ₹8,800 crore, partly offset by recoveries and upgrades of ₹4,200 crore.",
        score: 0.9,
      },
      {
        doc_id: "doc_hdfcbank_q3fy25",
        page: 14,
        excerpt:
          "No material concentration risk was observed in the retail portfolio during the quarter. The 31–90 days past due bucket saw a seasonal increase in the agri and micro-LAP segments, consistent with prior-year trends.",
        score: 0.82,
      },
    ],
  },
  {
    id: "itc_fmcg",
    patterns: [/itc/i, /fmcg|aashirvaad|sunfeast|notebooks|biscuits/i],
    plan: qp(14, 2, 4),
    answer: `ITC's FMCG-Others segment delivered **revenue of ₹5,417 crore (+7.1% YoY) in H1 FY25**, with segment EBITDA margin expanding to **11.9%** — a ~110bps improvement over the prior year [1]. The deck attributes the resilience to three engines:

1. **Staples & biscuits** — Aashirvaad atta grew high-single-digits with the premium multigrain range outpacing base SKUs; Sunfeast held category leadership in creams and cookies despite gram inflation [1][2].
2. **Notebooks & stationery** — Classmate extended share gains, aided by the early school-season restock and premium launches [2].
3. **Personal care & hygiene** — Fiama and Savlon rebuilt volumes post the hygiene normalisation, with Fiama delivering a fifth consecutive quarter of double-digit growth [1].

Management highlighted that **60+ new-product launches** in H1 were concentrated in premium, health and convenience formats, and that *"discretionary categories are showing early signs of demand recovery led by urban markets"* [3]. Commodity tailwinds (wheat, edible oil, soap noodles) remain watch-items for H2 margin trajectory [2].`,
    sources: [
      {
        doc_id: "doc_itc_deck_24",
        page: 14,
        excerpt:
          "FMCG-Others segment revenue stood at ₹5,417 crore in H1 FY25, up 7.1% YoY. Segment EBITDA margin expanded by ~110 bps to 11.9%, driven by premiumisation, calibrated pricing actions and supply-chain efficiencies.",
        score: 0.93,
      },
      {
        doc_id: "doc_itc_deck_24",
        page: 16,
        excerpt:
          "Aashirvaad atta posted high-single-digit growth with the value-added portfolio outpacing the base range. Classmate notebooks strengthened market leadership. Wheat, edible oil and soap-noodle prices remain key input variables for H2.",
        score: 0.88,
      },
      {
        doc_id: "doc_itc_deck_24",
        page: 21,
        excerpt:
          "Over 60 new products were launched in H1 across premium, health and convenience formats. Discretionary categories are showing early signs of demand recovery led by urban markets, with rural demand stabilising.",
        score: 0.85,
      },
    ],
  },
];

/* ------------------------------------------------------------------ */
/*  Ticker strip (decorative market context)                           */
/* ------------------------------------------------------------------ */

export interface Tick {
  symbol: string;
  price: string;
  change: number;
}

export const TICKS: Tick[] = [
  { symbol: "NIFTY 50", price: "24,812.75", change: 0.62 },
  { symbol: "SENSEX", price: "81,224.55", change: 0.44 },
  { symbol: "RELIANCE", price: "3,024.10", change: 1.18 },
  { symbol: "TCS", price: "4,512.35", change: -0.42 },
  { symbol: "HDFCBANK", price: "1,742.60", change: 0.86 },
  { symbol: "INFY", price: "1,928.45", change: 2.05 },
  { symbol: "ITC", price: "512.30", change: -0.24 },
  { symbol: "BAJFINANCE", price: "7,845.00", change: 1.62 },
  { symbol: "TATAMOTORS", price: "1,012.85", change: -1.08 },
  { symbol: "NIFTY BANK", price: "52,144.20", change: 0.31 },
  { symbol: "USDINR", price: "83.94", change: -0.06 },
  { symbol: "BRENT", price: "82.41", change: 0.88 },
];

/* ------------------------------------------------------------------ */
/*  Suggested questions for the empty state                            */
/* ------------------------------------------------------------------ */

export interface Suggestion {
  question: string;
  tags: string[];
}

export const SUGGESTIONS: Suggestion[] = [
  {
    question: "What was Reliance's consolidated revenue in FY24, and which segment grew fastest?",
    tags: ["RELIANCE", "FY24 AR"],
  },
  {
    question: "Compare TCS and Infosys operating margins and commentary",
    tags: ["TCS", "INFY", "Margins"],
  },
  {
    question: "How is HDFC Bank's asset quality trending this quarter?",
    tags: ["HDFCBANK", "Q3 FY25"],
  },
  {
    question: "What growth drivers is ITC flagging in its FMCG business?",
    tags: ["ITC", "Investor deck"],
  },
];
