// Builds docs/Claims_Assistant_Panel_Deck.pptx (the ten-minute panel presentation).
//
//   cd <scratch folder> && npm init -y && npm install pptxgenjs
//   node <repo>/scripts/build_deck.js <repo>      (set NODE_PATH to the scratch node_modules)
//
// Every number on the slides comes from the FACTS block below, which mirrors docs/VALIDATION.md,
// docs/MODEL_CARD.md and docs/SYNAPT_INTEGRATION.md. Update FACTS, not the layout, when results change.
const path = require("path");
const pptxgen = require("pptxgenjs");

const REPO = path.resolve(process.argv[2] || ".");
const OUT = path.join(REPO, "docs", "Claims_Assistant_Panel_Deck.pptx");

const FACTS = {
  backendTests: 905,
  frontendTests: 171,
  golden: "4 of 4",
  deepeval: "12 of 12 metrics ran, 8 pass",
  deepevalDetail: "",
  // The data split in Synapt, measured from its graph on 13 October 2026 (docs/SYNAPT_INTEGRATION.md).
  split: {
    cardShareOfChunks: "99.6%", // the 20 claim-card documents' share of the provider's chunks
    cardLinks: 55, // graph links from the 10,020 card chunks
    sopLinks: 135, // graph links from the 17 procedure chunks
    sops: 17, procedures: 21, steps: 93, tickets: "2,000",
  },
};

const THEME = {
  name: "Claims Panel",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0B2530", lt1: "FFFFFF", dk2: "0E4A57", lt2: "E6F4F1",
    accent1: "0E7C86", accent2: "F2A93B", accent3: "D9534F",
    accent4: "3E6D8F", accent5: "3A8F5C", accent6: "6D5BA8",
    hlink: "0E7C86", folHlink: "6D5BA8",
  },
};
const INK = "0B2530", TEAL = "0E7C86", TEAL_DK = "0E4A57", MINT = "E6F4F1";
const AMBER = "F2A93B", ROSE = "D9534F", SLATE = "5A6B73", WHITE = "FFFFFF";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "AI-Powered Insurance Claims Assistant: panel presentation";
pres.author = "Sai Chaithanya Reddy Yedururi";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: INK },
  objects: [],
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, color: "9FB3BA", fontSize: 11 },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: WHITE },
  slideNumber: { x: 12.2, y: 6.95, w: 0.6, h: 0.3, color: SLATE, fontSize: 11 },
  objects: [
    { text: { text: "AI-Powered Insurance Claims Assistant", options: { x: 0.6, y: 6.95, w: 6, h: 0.3, fontSize: 11, color: SLATE, margin: 0 } } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.95, fontSize: 32, bold: true, color: C.text1, align: "left", valign: "middle", margin: 0 }, text: "" } },
  ],
});

let n = 0;
const section = (t) => pres.addSection({ title: t });

// ---------- helpers ----------
function badge(slide, x, y, label, fill = TEAL, size = 0.5) {
  slide.addShape(pres.ShapeType.ellipse, { x, y, w: size, h: size, fill: { color: fill }, line: { color: fill }, objectName: `badge ${label}` });
  slide.addText(String(label), { x, y, w: size, h: size, align: "center", valign: "middle", fontSize: 16, bold: true, color: WHITE, margin: 0, isTextBox: true });
}
function card(slide, x, y, w, h, fill = MINT) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill },
    shadow: { type: "outer", color: "000000", opacity: 0.12, blur: 8, offset: 2, angle: 90 },
  });
}
function notes(slide, text) { slide.addNotes(text); }

// =============== 1. Title ===============
section("Opening");
let s = pres.addSlide({ masterName: "DARK", sectionTitle: "Opening" });
s.addText("AI-Powered Insurance Claims Assistant", { x: 0.8, y: 1.55, w: 11.6, h: 1.1, fontFace: "Cambria", fontSize: 44, bold: true, color: WHITE, margin: 0, isTextBox: true });
s.addText("Evidence-led investigation over 100 million claims, with Synapt knowledge and a human review gate", { x: 0.8, y: 2.75, w: 10.5, h: 0.9, fontSize: 22, color: "CFE3E6", margin: 0, isTextBox: true });
[["100 million", "claims queried in place"], [`${FACTS.split.tickets}`, "tickets in Synapt"], ["8 stages", "and one human gate"]].forEach(([big, small], i) => {
  const x = 0.8 + i * 4.0;
  s.addShape(pres.ShapeType.roundRect, { x, y: 4.45, w: 3.7, h: 1.6, rectRadius: 0.12, fill: { color: TEAL_DK }, line: { color: TEAL_DK } });
  s.addText(big, { x: x + 0.3, y: 4.6, w: 3.1, h: 0.8, fontFace: "Cambria", fontSize: 34, bold: true, color: AMBER, margin: 0, isTextBox: true });
  s.addText(small, { x: x + 0.3, y: 5.4, w: 3.1, h: 0.5, fontSize: 16, color: WHITE, margin: 0, isTextBox: true });
});
s.addText("Capstone panel  |  10 minutes", { x: 0.8, y: 6.7, w: 6, h: 0.35, fontSize: 14, color: "9FB3BA", margin: 0, isTextBox: true });
notes(s, "(0:30) Claims teams review historical claims by hand. This assistant finds comparable claims among 100 million, brings in Synapt's procedures, estimates three things, and writes a cited brief that a person reviews. It never approves, denies or pays a claim. Everything I show today ran live on the real dataset and the real Synapt provider.");

// =============== 2. Questions ===============
section("Problem and design");
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem and design" });
s.addText("Three questions every handler asks", { placeholder: "title" });
const qs = [
  ["Has a similar claim been processed, and how did it end?", "Filters, keyword, numeric and Synapt semantic ranks are fused over 100 million claims. Outcomes shown, with the rule that only already-settled claims count.", "Hybrid retrieval"],
  ["What makes claims larger, or slower to resolve?", "Amount and resolution models explain themselves: the direction of each effect, and what moved this claim from a typical one.", "Explainable models"],
  ["Does it resemble claims flagged as fraud?", "A fraud-flag model, the flag rate among the closest historical claims, and an audited priority score. A signal to investigate, never a verdict.", "Risk and priority"],
];
qs.forEach(([q, a, tag], i) => {
  const x = 0.6 + i * 4.16, y = 1.6;
  card(s, x, y, 3.81, 4.55);
  badge(s, x + 0.3, y + 0.3, i + 1);
  s.addText(q, { x: x + 0.3, y: y + 0.95, w: 3.25, h: 1.45, fontSize: 20, bold: true, color: INK, valign: "top", margin: 0, isTextBox: true });
  s.addText(a, { x: x + 0.3, y: y + 2.45, w: 3.25, h: 1.5, fontSize: 14, color: SLATE, valign: "top", margin: 0, isTextBox: true });
  s.addText(tag, { x: x + 0.3, y: y + 4.0, w: 3.25, h: 0.35, fontSize: 14, bold: true, color: TEAL, margin: 0, isTextBox: true });
});
s.addText("Nothing here approves, denies or pays a claim. The handler decides.", { x: 0.6, y: 6.4, w: 12.1, h: 0.4, fontSize: 18, italic: true, color: TEAL_DK, margin: 0, isTextBox: true });
notes(s, "(1:00) These are the three questions in the brief. Each maps to a capability, and I will show all three working. The sentence at the bottom is a design rule enforced in code: a validator blocks any recommendation that approves, denies, pays, or calls something proven fraud.");

// =============== 3. Architecture ===============
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem and design" });
s.addText("One service, three stores, one human gate", { placeholder: "title" });
s.addImage({ path: path.join(REPO, "docs", "architecture.png"), x: 0.6, y: 1.4, w: 8.2, h: 5.51, objectName: "Architecture diagram", altText: "Architecture: UI, FastAPI, LangGraph workflow, Parquet, Synapt, models, NVIDIA NIM, SQLite and the feedback loop" });
const side = [
  ["Parquet, 100M rows", "Authoritative for filters, similar claims, every number shown, and model training."],
  ["Synapt, over MCP", "Procedures as documents (the knowledge graph), past claims in its ticket store, reviewed lessons."],
  ["Human gate", "LangGraph pauses; the handler accepts or revises. Acceptance is blocked on failed validation."],
];
side.forEach(([h, t], i) => {
  const y = 1.55 + i * 1.75;
  badge(s, 9.2, y, i + 1, i === 2 ? AMBER : TEAL, 0.45);
  s.addText(h, { x: 9.85, y: y - 0.02, w: 2.9, h: 0.45, fontSize: 18, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(t, { x: 9.85, y: y + 0.45, w: 2.9, h: 1.05, fontSize: 14, color: SLATE, valign: "top", margin: 0, isTextBox: true });
});
notes(s, "(1:15) A handler uses the React UI served by one FastAPI service. A LangGraph workflow runs eight stages and pauses for a person. Three stores each do what they can: the Parquet file is the authority for the 100 million claims, Synapt holds knowledge, SQLite holds runs and audit. Synapt holds procedures as documents, from which it builds the knowledge graph, and a sample of settled claims in its ticket store; the 100 million claims stay in Parquet. Models write the brief; a second, different model judges it.");

// =============== 4. Retrieval ===============
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem and design" });
s.addText("Hybrid search over 100 million claims in 3 to 5 seconds", { placeholder: "title" });
[["100,000,000", "claims, queried in place by DuckDB"], ["3 to 5 s", "per filtered, fused search"], ["2.52 GB", "one Parquet file, SHA256-verified"]].forEach(([big, small], i) => {
  const y = 1.55 + i * 1.5;
  card(s, 0.6, y, 4.3, 1.3);
  s.addText(big, { x: 0.85, y: y + 0.12, w: 3.8, h: 0.65, fontFace: "Cambria", fontSize: 32, bold: true, color: TEAL_DK, margin: 0, isTextBox: true });
  s.addText(small, { x: 0.85, y: y + 0.78, w: 3.8, h: 0.4, fontSize: 14, color: SLATE, margin: 0, isTextBox: true });
});
const steps = [
  ["SQL filters and candidates", "Type, state, status, amount, history. Only claims settled before this one was filed qualify."],
  ["Synapt semantic ranking", "Past claims in Synapt's ticket store closest to this one; looked up under the same filters, so nothing bypasses them."],
  ["Reciprocal-rank fusion", "Keyword 1, numeric similarity 1, Synapt 0.5. The five closest come first."],
  ["Related by meaning", "Up to three more that Synapt ranks similar, labelled with their Synapt rank."],
];
steps.forEach(([h, t], i) => {
  const y = 1.55 + i * 1.05;
  badge(s, 5.4, y, i + 1, TEAL, 0.42);
  s.addText(h, { x: 6.0, y: y - 0.04, w: 6.7, h: 0.4, fontSize: 18, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(t, { x: 6.0, y: y + 0.36, w: 6.7, h: 0.55, fontSize: 14, color: SLATE, valign: "top", margin: 0, isTextBox: true });
});
card(s, 5.4, 5.85, 7.33, 0.95, "FDF1DC");
s.addText([
  { text: "Measured, not assumed. ", options: { bold: true, color: INK } },
  { text: "Keyword IDF ranked a $3,393 New Jersey claim above exact $8,500 Texas matches. Removed, with a regression test.", options: { color: INK } },
], { x: 5.6, y: 5.9, w: 6.95, h: 0.85, fontSize: 15, valign: "middle", margin: 0, isTextBox: true });
notes(s, "(1:30) Search never loads the file into memory. DuckDB scans it and only a few hundred candidates reach Python. Two rules matter: a comparable claim must have been settled before the new claim was filed, and the pending rows store their duration as NaN, not null, which the SQL handles. During live testing I found the keyword leg ranked Synapt's odd outliers above exact matches, because IDF rewards rare terms. I removed IDF and added a regression test that fails on the old behaviour.");

// =============== 5. Synapt ===============
section("Synapt");
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Synapt" });
s.addText("Synapt: the right data in the right store", { placeholder: "title" });
const blocks = [
  ["Documents", `${FACTS.split.sops} handling procedures. Synapt builds the knowledge graph from them: ${FACTS.split.procedures} procedures, ${FACTS.split.steps} ordered steps. Cited as evidence.`],
  ["Was wrong", "Claim rows were stored as text cards beside the procedures. Review feedback said the split was wrong, and the graph agreed."],
  ["Tickets", `${FACTS.split.tickets} settled past claims in the ticket store. The claim is sent as one ticket; the closest past claims come back.`],
];
blocks.forEach(([h, t], i) => {
  const y = 1.5 + i * 1.7;
  card(s, 0.6, y, 5.6, 1.5, i === 1 ? "FBE7E5" : MINT);
  s.addText(h, { x: 0.85, y: y + 0.12, w: 2.4, h: 0.4, fontSize: 18, bold: true, color: i === 1 ? ROSE : TEAL_DK, margin: 0, isTextBox: true });
  s.addText(t, { x: 0.85, y: y + 0.52, w: 5.1, h: 0.95, fontSize: 14, color: INK, valign: "top", margin: 0, isTextBox: true });
});
[
  [FACTS.split.cardShareOfChunks, "of the provider's chunks were claim cards"],
  [`${FACTS.split.cardLinks} vs ${FACTS.split.sopLinks}`, "graph links: 10,020 card chunks vs 17 procedures"],
  ["13 Oct", "cards deleted; claims moved to the ticket store"],
].forEach(([big, small], i) => {
  const y = 1.5 + i * 1.5;
  card(s, 6.55, y, 6.2, 1.3);
  s.addText(big, { x: 6.8, y: y + 0.12, w: 5.7, h: 0.65, fontFace: "Cambria", fontSize: 30, bold: true, color: TEAL_DK, margin: 0, isTextBox: true });
  s.addText(small, { x: 6.8, y: y + 0.78, w: 5.7, h: 0.4, fontSize: 14, color: SLATE, margin: 0, isTextBox: true });
});
s.addText("Ticket labels never beat the majority class on this data, so they are not shown; the past claims are used only to rank.", { x: 6.55, y: 6.0, w: 6.2, h: 0.8, fontSize: 14, italic: true, color: TEAL_DK, valign: "top", margin: 0, isTextBox: true });
notes(s, "(1:15) Synapt has two stores for two kinds of content. Documents are for knowledge: the seventeen procedures, from which Synapt builds the graph of procedures and ordered steps that every brief cites. Settled claims are cases with outcomes, which is what the ticket store is for. I first put ten thousand claim rows into the documents as text cards. The review said that split was wrong, and the graph shows why: the cards were 99.6 percent of the chunks but gave 55 graph links, against 135 from seventeen procedures. So I uploaded two thousand settled claims through the Ticketing source, checked that the procedures and graph were untouched, and deleted the cards. Now the passage retriever sends the claim as one ticket, ticket-only mode, no model call, and the closest past claims are looked up in Parquet under the handler's filters. I measured the ticket labels against the majority class and they add nothing, so the app does not show them.");

// =============== 6. Live demo ===============
section("Demo and evidence");
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo and evidence" });
s.addText("Live: an auto-theft claim, from intake to a reviewed lesson", { placeholder: "title" });
const demo = [
  ["Intake", "Pick the example, or type a claim. Invalid input is refused with a clear reason."],
  ["Brief in about 15 s", "Cited gap: a police report, from a Synapt procedure. Documents are only ever 'reported available'."],
  ["Priority 55 of 100, High", "Each point attributed: amount, 17-day delay, 3 prior claims, a gap, the fraud signal."],
  ["Independent review", "A second model judges the brief in the background and appears when ready."],
  ["Review, feedback, promote", "Accepted lessons become cited evidence next time, and are ingested into Synapt."],
];
demo.forEach(([h, t], i) => {
  const y = 1.5 + i * 1.07;
  badge(s, 0.6, y, i + 1, i === 4 ? AMBER : TEAL, 0.45);
  s.addText(h, { x: 1.3, y: y - 0.05, w: 4.9, h: 0.4, fontSize: 18, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(t, { x: 1.3, y: y + 0.36, w: 4.9, h: 0.65, fontSize: 14, color: SLATE, valign: "top", margin: 0, isTextBox: true });
});
s.addImage({ path: path.join(REPO, "docs", "screenshots", "live-priority-and-judge.jpg"), x: 6.95, y: 1.5, w: 5.78, h: 5.25, objectName: "Live screenshot: priority and independent review", altText: "Handling priority High 55 of 100 with five attributed factors, and an independent review reporting no concerns" });
notes(s, "(1:45) Switch to the running app. Submit the Auto theft example. It returns in about fifteen seconds. Point at: the police-report gap cited to a Synapt procedure; the priority score where every point is attributed; and the independent review, which arrives afterwards because it runs in the background. Then accept the brief, rate it, promote the lesson as the administrator, and run the claim again to show the lesson cited as evidence.");

// =============== 7. Models ===============
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo and evidence" });
s.addText("Predictions a handler can interrogate", { placeholder: "title" });
[
  ["Amount", "28% lower error", "MAE $16,072 vs $22,364 baseline. The 90% interval covers 90.1%."],
  ["Resolution time", "9% lower error", "MAE 6.58 vs 7.22 days. Interval covers 89.8%."],
  ["Fraud flag", "4x the baseline", "PR-AUC 0.32 vs 0.08; precision 56%, recall 31%."],
].forEach(([h, big, t], i) => {
  const x = 0.6 + i * 4.16;
  card(s, x, 1.5, 3.81, 2.35);
  s.addText(h, { x: x + 0.3, y: 1.62, w: 3.2, h: 0.4, fontSize: 16, bold: true, color: TEAL, margin: 0, isTextBox: true });
  s.addText(big, { x: x + 0.3, y: 2.05, w: 3.3, h: 0.7, fontFace: "Cambria", fontSize: 28, bold: true, color: INK, margin: 0, isTextBox: true });
  s.addText(t, { x: x + 0.3, y: 2.8, w: 3.25, h: 0.95, fontSize: 14, color: SLATE, valign: "top", margin: 0, isTextBox: true });
});
s.addText("Why this estimate: what the models learned, and what moved this claim", { x: 0.6, y: 4.1, w: 12.1, h: 0.45, fontSize: 20, bold: true, color: INK, margin: 0, isTextBox: true });
[
  "Fraud score falls with tenure (0.23 at six months to 0.05 at eleven years) and rises with claim size, the pattern the dataset describes.",
  "Resolution time tracks filing delay: about 13 days after a one-day delay, about 25 after thirteen.",
  "Amount: business claims average about $107,000 against $17,000 for renters.",
  "Per claim: each feature is swapped for a typical value to show how far it moved this estimate. Associations, not causes.",
].forEach((t, i) => {
  const y = 4.65 + i * 0.5;
  s.addShape(pres.ShapeType.ellipse, { x: 0.65, y: y + 0.13, w: 0.14, h: 0.14, fill: { color: TEAL }, line: { color: TEAL } });
  s.addText(t, { x: 0.95, y, w: 11.7, h: 0.45, fontSize: 14, color: INK, valign: "middle", margin: 0, isTextBox: true });
});
notes(s, "(1:00) Models are trained on a repeatable 200,000-row sample of the 100 million, split by filing date so the test period is strictly later. The 3,000-row slice I started with made the fraud model weak; the larger sample made it useful. The explanations are the part to emphasise: global direction of effect, in plain language, and for each claim what moved its estimate. All associations, none causal.");

// =============== 8. Evaluation, guardrails, loop ===============
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo and evidence" });
s.addText("Evaluated, guarded and learning", { placeholder: "title" });
const cols = [
  ["Evaluated", TEAL, [
    `Golden cases: ${FACTS.golden} on the live system`,
    `DeepEval: ${FACTS.deepeval}`,
    "Independent LLM judge on every live brief",
    `${FACTS.backendTests} backend and ${FACTS.frontendTests} UI tests`,
  ]],
  ["Guarded", ROSE, [
    "7 of 7 invalid inputs refused",
    "Every finding must cite a supplied source",
    "A brief claiming a document was 'provided' is held for review",
    "Decision language is blocked",
  ]],
  ["Learning", AMBER, [
    "Rate an accepted brief",
    "Administrator promotes the lesson",
    "Cited as evidence next time, and ingested into Synapt",
    "Answer ratings sent to Synapt as feedback",
  ]],
];
cols.forEach(([h, color, items], i) => {
  const x = 0.6 + i * 4.16;
  card(s, x, 1.5, 3.81, 4.35);
  badge(s, x + 0.3, 1.8, i + 1, color, 0.5);
  s.addText(h, { x: x + 0.95, y: 1.8, w: 2.6, h: 0.5, fontSize: 22, bold: true, color: INK, valign: "middle", margin: 0, isTextBox: true });
  s.addText(items.map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < items.length - 1 } })), {
    x: x + 0.3, y: 2.6, w: 3.3, h: 3.1, fontSize: 15, color: INK, valign: "top", paraSpaceAfter: 10, margin: 0, isTextBox: true,
  });
});
s.addText("Evaluation, the guardrail catch and the feedback loop were exercised on the live system, not only in unit tests.", { x: 0.6, y: 6.1, w: 12.1, h: 0.6, fontSize: 16, italic: true, color: TEAL_DK, valign: "middle", margin: 0, isTextBox: true });
notes(s, "(1:15) Three kinds of assurance. Evaluated: golden cases and DeepEval, plus a second model judging every live brief. Guarded: strict input checks, mandatory citations, and a validator that caught the model writing that a document had been provided when only its name was received; the brief was held for manual review, and a prompt fix cut that from one in four to none in four. Learning: handler feedback becomes cited evidence, and a handler's rating of Synapt's answer goes back to Synapt as feedback.");

// =============== 9. Limits ===============
section("Close");
s = pres.addSlide({ masterName: "DARK", sectionTitle: "Close" });
s.addText("Honest limits, and what comes next", { x: 0.8, y: 0.6, w: 11.7, h: 0.9, fontFace: "Cambria", fontSize: 38, bold: true, color: WHITE, margin: 0, isTextBox: true });
const lim = [
  ["Limits", AMBER, [
    "Synthetic data: no claim of real-world accuracy",
    "Synapt's ticket store holds 2,000 of 100 million claims: a mild ranking signal",
    "Fraud recall is 31%: a screening aid, not a detector",
    "The judge is advisory and probabilistic",
  ]],
  ["Next", "7FD1C7", [
    "Episode mining over the ticket store (not yet run)",
    "A larger ticket store, with its ranking re-measured",
    "DeepEval over real handler runs, not only golden cases",
    "Single sign-on, MFA and multi-tenant isolation",
  ]],
];
lim.forEach(([h, color, items], i) => {
  const x = 0.8 + i * 6.0;
  s.addShape(pres.ShapeType.roundRect, { x, y: 1.85, w: 5.6, h: 3.75, rectRadius: 0.12, fill: { color: TEAL_DK }, line: { color: TEAL_DK } });
  s.addText(h, { x: x + 0.35, y: 2.05, w: 4.9, h: 0.5, fontSize: 24, bold: true, color, margin: 0, isTextBox: true });
  s.addText(items.map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < items.length - 1 } })), {
    x: x + 0.35, y: 2.75, w: 4.95, h: 2.9, fontSize: 16, color: WHITE, valign: "top", paraSpaceAfter: 10, margin: 0, isTextBox: true,
  });
});
s.addText("Evidence informs. A person decides.", { x: 0.8, y: 6.2, w: 11.7, h: 0.6, fontFace: "Cambria", fontSize: 28, italic: true, color: AMBER, margin: 0, isTextBox: true });
notes(s, "(0:30) The limits are real and documented. The data is synthetic. Synapt's ticket store holds two thousand claims, not a hundred million, so its ranking leg is a mild signal, and episode mining over those tickets has not run yet. The fraud model is a screening aid. Next steps are about scale and about evaluating on real handler runs. Close on the design principle: evidence informs, a person decides. Questions.");

pres.writeFile({ fileName: OUT }).then(async () => {
  // Writing the theme palette into the deck needs the helper that ships with the PowerPoint skill
  // (set PPTX_SKILL_DIR to its folder). Without it the deck is still complete: every colour except
  // the title text is an explicit hex value, and titles fall back to Office's default dark text.
  try {
    const { applyTheme } = require(path.join(process.env.PPTX_SKILL_DIR || "", "scripts", "apply_theme.js"));
    await applyTheme(OUT, THEME);
    console.log("theme applied");
  } catch (e) {
    console.warn("theme not applied (set PPTX_SKILL_DIR to enable):", e.code || e.message);
  }
  console.log("wrote", OUT);
}).catch((e) => { console.error(e); process.exit(1); });
