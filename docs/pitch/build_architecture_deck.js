const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Roshan Rana";
pres.title = "DRYDOCK — AI Systems Architecture Review";

// Palette (shared house style)
const NAVY = "14213D", INK = "1B2A41", WHITE = "FFFFFF", ICE = "DCE7F5", MINT = "2EC4B6",
  GOLD = "F2B134", MUTED = "6B7A90", CARD = "F3F6FA", LINE = "C9D3E0", CARD_D = "1C2B4F", RED = "D64550";
const HF = "Cambria", BF = "Calibri";
const ASSETS = "C:/Code-Central/drydock/docs/assets/";

let n = 0;
function base(title, kicker) {
  const s = pres.addSlide();
  n += 1;
  s.background = { color: WHITE };
  if (kicker) s.addText(kicker.toUpperCase(), { x: 0.5, y: 0.28, w: 6, h: 0.25, fontFace: BF, fontSize: 10, bold: true, color: MINT, charSpacing: 2, isTextBox: true, margin: 0 });
  s.addText(title, { x: 0.5, y: 0.5, w: 9, h: 0.6, fontFace: HF, fontSize: 26, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  s.addText(`DRYDOCK · AI Systems Architecture Review · ${n}`, { x: 0.5, y: 5.25, w: 9, h: 0.25, fontFace: BF, fontSize: 8, color: MUTED, isTextBox: true, margin: 0 });
  return s;
}
function dark(title, sub) {
  const s = pres.addSlide();
  n += 1;
  s.background = { color: NAVY };
  s.addText(title, { x: 0.6, y: 1.9, w: 8.8, h: 0.9, fontFace: HF, fontSize: 34, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  if (sub) s.addText(sub, { x: 0.6, y: 2.85, w: 8.8, h: 0.6, fontFace: BF, fontSize: 15, italic: true, color: ICE, isTextBox: true, margin: 0 });
  return s;
}
function card(s, x, y, w, h, fill = CARD, line = LINE) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 0.75 }, rectRadius: 0.06 });
}
function box(s, x, y, w, h, title, body, opt = {}) {
  const fill = opt.fill || CARD, tcol = opt.tcol || NAVY, bcol = opt.bcol || INK, line = opt.line || LINE;
  card(s, x, y, w, h, fill, line);
  s.addText(title, { x: x + 0.1, y: y + 0.06, w: w - 0.2, h: 0.28, fontFace: BF, fontSize: opt.ts || 11, bold: true, color: tcol, isTextBox: true, margin: 0 });
  if (body) s.addText(body, { x: x + 0.1, y: y + 0.34, w: w - 0.2, h: h - 0.4, fontFace: BF, fontSize: opt.bs || 8.5, color: bcol, isTextBox: true, margin: 0, valign: "top" });
}
function arrow(s, x1, y1, x2, y2, color = MUTED, w = 1.25) {
  const flipH = x2 < x1, flipV = y2 < y1;
  s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.01, h: Math.abs(y2 - y1) || 0.01, line: { color, width: w, endArrowType: "triangle" }, flipH, flipV });
}
function bullets(s, items, x, y, w, h, fs = 11, color = INK) {
  s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })), { x, y, w, h, fontFace: BF, fontSize: fs, color, isTextBox: true, margin: 0, paraSpaceAfter: 4, valign: "top" });
}
function table(s, rows, x, y, w, colW, fs = 8.5, rowH) {
  const data = rows.map((r, i) => r.map((c) => ({ text: c, options: i === 0 ? { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: fs } : { fontSize: fs, color: INK } })));
  s.addTable(data, { x, y, w, colW, fontFace: BF, border: { type: "solid", pt: 0.5, color: LINE }, autoPage: false, rowH });
}
function imgFit(s, path, x, y, maxW, maxH, pw, ph) {
  const r = Math.min(maxW / pw, maxH / ph);
  const w = pw * r, h = ph * r;
  s.addImage({ path, x: x + (maxW - w) / 2, y, w, h });
  return { w, h };
}
function caption(s, text, x, y, w) {
  s.addText(text, { x, y, w, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 1 Title
{
  const s = pres.addSlide(); n += 1; s.background = { color: NAVY };
  s.addText("DRYDOCK", { x: 0.6, y: 1.35, w: 8, h: 0.9, fontFace: HF, fontSize: 48, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText("AI Systems Architecture Review", { x: 0.6, y: 2.25, w: 8, h: 0.5, fontFace: BF, fontSize: 22, color: ICE, isTextBox: true, margin: 0 });
  s.addText("Agentic pipeline generation and validation harness — client feed specs in, tested ingestion pipelines out, nothing sails without a signature", { x: 0.6, y: 2.8, w: 8.6, h: 0.6, fontFace: BF, fontSize: 13, italic: true, color: ICE, isTextBox: true, margin: 0 });
  s.addText("Release/ship date · 12 September 2026 · Roshan Rana", { x: 0.6, y: 4.6, w: 8.8, h: 0.3, fontFace: BF, fontSize: 10, color: MUTED, isTextBox: true, margin: 0 });
  s.addShape(pres.shapes.OVAL, { x: 8.2, y: 1.2, w: 1.1, h: 1.1, fill: { color: MINT }, line: { color: MINT } });
  s.addText("D", { x: 8.2, y: 1.2, w: 1.1, h: 1.1, fontFace: HF, fontSize: 40, bold: true, color: NAVY, align: "center", valign: "middle", isTextBox: true, margin: 0 });
}

// ---------- 2 Executive summary
{
  const s = base("Executive summary", "Overview");
  const cols = [
    ["What it is", ["A bounded LangGraph state machine that plans through MCP tools, generates a pipeline + Airflow DAG + field mapping from a client's feed specification, tests the result in a sandbox against six deterministic checks, repairs on failure, and stops at a real human gate before anything is published."], ],
    ["What it proves", ["The loop is provably bounded, auditable and resumable across processes: every step is a LangGraph checkpoint in SQLite, and the human-approval interrupt cannot be skipped by any flag, config or provider.", "6/6 corpus scenarios replay as declared; 5/5 adversarial pipelines are rejected; the gate runs offline in one command."]],
    ["Why it is enterprise-ready", ["Built through a gated, evidence-producing lifecycle: frozen LLD contracts, 12 task packs, code and security review, a documented three-layer sandbox hardened after an independent security review found real escapes."]],
  ];
  cols.forEach((c, i) => {
    const x = 0.5 + i * 3.05;
    card(s, x, 1.3, 2.9, 3.25);
    s.addText(c[0], { x: x + 0.15, y: 1.4, w: 2.6, h: 0.35, fontFace: HF, fontSize: 15, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    bullets(s, c[1], x + 0.15, 1.85, 2.6, 2.6, 10.5);
  });
  s.addText("Ask of the audience: agree the pilot scope (a recorded live-model run, the Docker sandbox as default, HMAC-signed approvals) and which provider (Ollama, vLLM, Bedrock, Anthropic) a first client's data perimeter should target.", { x: 0.5, y: 4.7, w: 9, h: 0.45, fontFace: BF, fontSize: 10.5, italic: true, color: INK, isTextBox: true, margin: 0 });
}

// ---------- 3 Problem and users
{
  const s = base("The problem and the users", "Context");
  box(s, 0.5, 1.3, 4.3, 1.75, "The onboarding problem", "Every client feed arrives with a specification that is nearly right and a sample file that is nearly what the specification describes. Someone reads both, writes a parser, runs it, finds the trailer row counted as data, fixes it, and asks a colleague to sign off in a chat message. The work is repetitive, the fixes are undocumented, and the sign-off leaves no evidence.", { bs: 10 });
  box(s, 5.2, 1.3, 4.3, 1.75, "The trust constraint", "Language models can write the parser; the question is whether anything they write can be trusted into a scheduler. DRYDOCK's answer: the model's output is a proposal, a deterministic harness is the judge, and a human is the only thing that can publish.", { bs: 10 });
  table(s, [
    ["Actor", "Needs", "Frequency"],
    ["Forward-deployed engineer", "A drafted, tested pipeline + DAG + mapping per client feed, with the repair history kept", "Per client onboarded"],
    ["Reviewer / approver", "Iteration reports with evidence, an approve/reject gate that cannot be bypassed", "On every run"],
    ["Platform / ops", "Deterministic gate offline; swappable model backend; no secrets in config", "Deploy / operate"],
    ["Automation / AI assistants", "The same build/inspect/approve surface over CLI, dashboard and MCP", "Ad hoc"],
  ], 0.5, 3.25, 9.0, [2.4, 5.0, 1.6], 9);
}

// ---------- 4 Solution at a glance
{
  const s = base("Solution at a glance", "Approach");
  const steps = [
    ["1", "Plan", "The Planner calls the drydock-sources MCP server: list_samples, peek_sample (<=5 lines) and profile_sample. Tool calls are recorded as evidence on the plan; the planner never receives the sample files."],
    ["2", "Generate", "Three files: a stdlib-only pipeline.py, an Airflow dag.py restricted to DAG/PythonOperator/>>, and a Harbormaster-compatible mapping.yaml."],
    ["3", "Evaluate & repair", "The artifact runs in a sandbox against six deterministic checks (H1-H6); failures feed back into the next generation, up to a fixed iteration budget."],
    ["4", "Gate & publish", "await_approval calls a real LangGraph interrupt(). A later approve/reject — from another process — resumes the checkpoint; publish writes deploy/<client>/ only after that."],
  ];
  steps.forEach((st, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.35, 2.15, 2.15, CARD_D, CARD_D);
    s.addShape(pres.shapes.OVAL, { x: x + 0.15, y: 1.5, w: 0.4, h: 0.4, fill: { color: MINT }, line: { color: MINT } });
    s.addText(st[0], { x: x + 0.15, y: 1.5, w: 0.4, h: 0.4, fontFace: BF, fontSize: 14, bold: true, color: NAVY, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.65, y: 1.52, w: 1.4, h: 0.36, fontFace: BF, fontSize: 12.5, bold: true, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(st[2], { x: x + 0.15, y: 2.0, w: 1.85, h: 1.4, fontFace: BF, fontSize: 8, color: ICE, isTextBox: true, margin: 0, valign: "top" });
    if (i < 3) arrow(s, x + 2.15, 2.4, x + 2.3, 2.4, MINT, 2);
  });
  box(s, 0.5, 3.75, 4.4, 1.3, "Surfaces", "CLI (typer): build, runs, show, approve, reject, replay. Dashboard (FastAPI + vanilla HTML/JS): runs, diffs, checkpoint history. DRYDOCK MCP server: build/inspect/approve as 7 tools. All four read and write through one graph.service.", { bs: 9.5 });
  box(s, 5.1, 3.75, 4.4, 1.3, "Deterministic by default, live by explicit act", "The fake provider drives the tests, the bench and CI: templates plus seeded fault injection, zero network calls. Ollama, vLLM, Bedrock and Anthropic are configuration files plus an environment variable, never a side effect of having a key present.", { bs: 9.5 });
}

// ---------- 5 System context (C4 L1)
{
  const s = base("System context", "Architecture · C4 level 1");
  const actors = [["Forward-deployed eng.", "CLI / dashboard"], ["Reviewer / approver", "dashboard / CLI"], ["AI assistant", "MCP host"]];
  actors.forEach((a, i) => { box(s, 0.5, 1.3 + i * 0.95, 1.8, 0.85, a[0], a[1], { bs: 8, ts: 10.5 }); arrow(s, 2.3, 1.72 + i * 0.95, 2.75, 2.85, MUTED, 1); });
  card(s, 2.8, 1.3, 3.5, 3.55, "EEF6F4", MINT);
  s.addText("DRYDOCK", { x: 2.95, y: 1.38, w: 3.2, h: 0.3, fontFace: HF, fontSize: 14, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  box(s, 2.95, 1.75, 3.2, 0.7, "Surfaces", "CLI · dashboard (FastAPI) · DRYDOCK MCP server", { bs: 8 });
  box(s, 2.95, 2.55, 3.2, 1.15, "LangGraph state machine", "load_spec -> plan -> generate -> evaluate -> await_approval [interrupt] -> publish, with repair and escalate branches", { bs: 8 });
  box(s, 2.95, 3.8, 3.2, 0.9, "SQLite (data/drydock.db)", "runs + iterations + LangGraph checkpoints, keyed by thread_id = run_id", { bs: 8 });
  box(s, 6.65, 1.3, 2.85, 0.85, "drydock-sources MCP server", "list_samples · peek_sample (<=5 lines) · profile_sample — the planner's only view of client data", { bs: 8 });
  box(s, 6.65, 2.3, 2.85, 0.85, "Model backend (swappable)", "fake (offline, default) · Ollama · vLLM · Bedrock · Anthropic — one Provider protocol", { bs: 8 });
  box(s, 6.65, 3.3, 2.85, 0.85, "deploy/<client>/", "pipeline.py, dag.py, mapping.yaml, approval.json — written only by publish, after approval", { bs: 8 });
  arrow(s, 6.3, 2.3, 6.65, 1.7, MUTED, 1); arrow(s, 6.3, 2.9, 6.65, 2.7, MUTED, 1); arrow(s, 6.3, 3.5, 6.65, 3.7, MUTED, 1);
  s.addText("The corpus (corpus/<client>/spec.md, samples/, manifest.json) is the only client-owned input; everything the model sees is mediated by the sources server, never handed as whole files.", { x: 0.5, y: 4.9, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 6 Component architecture (C4 L2)
{
  const s = base("Component architecture", "Architecture · C4 level 2");
  const groups = [
    { t: "Contracts & corpus", x: 0.5, items: [["models.py", "frozen Pydantic contracts"], ["corpus.py", "load spec/samples/manifest, verify sha256"], ["paths.py, errors.py", "env-driven paths, error taxonomy"]] },
    { t: "Providers & MCP", x: 2.85, items: [["providers/", "Protocol, FakeProvider, LLMProvider, backends"], ["mcp/sources_server.py", "the planner's tools"], ["mcp/toolbox.py", "sync facade over MCP session"], ["mcp/server.py", "DRYDOCK as 7 MCP tools"]] },
    { t: "Harness", x: 5.2, items: [["guard.py", "static AST allow/deny lists"], ["runner.py", "runtime jail, stdlib only"], ["sandbox.py", "process containment, docker mode"], ["checks.py", "H1..H6"]] },
    { t: "Graph & surfaces", x: 7.55, items: [["graph/nodes.py", "8 nodes, 1 conditional edge"], ["graph/service.py", "start_run, decide"], ["graph/store.py", "SQLite runs + iterations"], ["cli.py, dashboard/", "typer + FastAPI"]] },
  ];
  groups.forEach((g) => {
    card(s, g.x, 1.3, 2.15, 3.55);
    s.addText(g.t, { x: g.x + 0.1, y: 1.36, w: 2, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    g.items.forEach((it, i) => {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: g.x + 0.1, y: 1.72 + i * 0.82, w: 1.95, h: 0.74, fill: { color: WHITE }, line: { color: LINE, width: 0.75 }, rectRadius: 0.05 });
      s.addText(it[0], { x: g.x + 0.18, y: 1.75 + i * 0.82, w: 1.8, h: 0.24, fontFace: "Courier New", fontSize: 8.5, bold: true, color: NAVY, isTextBox: true, margin: 0 });
      s.addText(it[1], { x: g.x + 0.18, y: 1.98 + i * 0.82, w: 1.8, h: 0.42, fontFace: BF, fontSize: 7.5, color: INK, isTextBox: true, margin: 0, valign: "top" });
    });
  });
  arrow(s, 2.65, 3.1, 2.85, 3.1, MINT, 2); arrow(s, 5.0, 3.1, 5.2, 3.1, MINT, 2); arrow(s, 7.35, 3.1, 7.55, 3.1, MINT, 2);
  s.addText("Generated code never imports into the orchestrator: the harness copies pipeline.py and dag.py into a scratch directory and runs them in a fresh interpreter. models.py and the LLD are frozen contracts task packs code against without talking to each other.", { x: 0.5, y: 4.9, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 7 The critical flow: the bounded loop
{
  const s = base("The critical flow: plan, generate, evaluate, gate", "Architecture · critical flow");
  const stages = [
    ["load_spec", "parse spec.md's feed-contract block into a typed FeedSpec"],
    ["plan", "3 MCP tool calls to drydock-sources; evidence recorded on IngestionPlan.tool_calls"],
    ["generate", "render pipeline.py, dag.py, mapping.yaml from the plan + spec"],
    ["evaluate", "sandbox run, 6 checks; on repair the previous artifact + findings go back in"],
    ["fail, iter<N", "loop back to generate with the harness findings as context"],
    ["fail, iter==N", "escalate: run ends, nothing published, all iteration reports on disk"],
    ["pass -> await_approval", "a real LangGraph interrupt() — no path to publish skips it"],
    ["approve -> publish", "resume from another process; deploy/<client>/ written with approval.json"],
  ];
  stages.forEach((st, i) => {
    const col = i % 4, row = Math.floor(i / 4);
    const x = 0.5 + col * 2.3, y = 1.4 + row * 1.7;
    card(s, x, y, 2.15, 1.35, row === 0 ? CARD : "EEF6F4", row === 0 ? LINE : MINT);
    s.addText(`${i + 1}. ${st[0]}`, { x: x + 0.1, y: y + 0.08, w: 1.95, h: 0.3, fontFace: BF, fontSize: 10.5, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.1, y: y + 0.4, w: 1.95, h: 0.9, fontFace: BF, fontSize: 8, color: INK, isTextBox: true, margin: 0, valign: "top" });
    if (col < 3) arrow(s, x + 2.15, y + 0.67, x + 2.3, y + 0.67, MUTED, 1.25);
  });
  arrow(s, 9.0, 2.75, 9.0, 3.1, MUTED, 1.25);
  s.addText("Every node appends one line to runs/<run_id>/events.jsonl (node, iteration, ms, outcome). The bench replays all 5 flows (happy, self-heal, escalate, reject, cross-process resume) with a fixed seed.", { x: 0.5, y: 4.85, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 8 Core mechanism: the human gate cannot be disabled
{
  const s = base("The core mechanism: agents propose, the harness decides, a human disposes", "Design · the one idea");
  card(s, 0.5, 1.3, 4.6, 3.55, CARD_D, CARD_D);
  s.addText("await_approval — the actual gate", { x: 0.65, y: 1.38, w: 4.3, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: MINT, isTextBox: true, margin: 0 });
  s.addText([
    "def await_approval(self, state):",
    "    # ...mark AWAITING_APPROVAL, log event",
    "    answer = interrupt(",
    "        approval_payload(state)",
    "    )",
    "    decision, approver, note = (",
    "        parse_decision(answer, state)",
    "    )",
    "    store.update(",
    "        run_id, approved_by=approver,",
    "        decision_note=note,",
    "    )",
  ].join("\n"), { x: 0.65, y: 1.72, w: 4.3, h: 2.15, fontFace: "Courier New", fontSize: 8.5, color: WHITE, isTextBox: true, margin: 0, valign: "top" });
  s.addText("publish is reachable only through approve. No flag, config or provider skips it.", { x: 0.65, y: 3.95, w: 4.3, h: 0.75, fontFace: BF, fontSize: 9, italic: true, color: ICE, isTextBox: true, margin: 0 });
  const badges = [["Pass, iter 1", "the deterministic harness found nothing wrong — straight to the gate", MINT], ["Fail, then pass", "findings feed the next generation; repaired within the iteration budget", GOLD], ["Fail x N, escalate", "a spec that contradicts its sample cannot be fixed by better code — a person gets the contradiction, not a forced pass", RED]];
  badges.forEach((b, i) => {
    const y = 1.3 + i * 1.18;
    card(s, 5.4, y, 4.1, 1.05);
    s.addText(b[0], { x: 5.55, y: y + 0.06, w: 3.8, h: 0.3, fontFace: BF, fontSize: 11.5, bold: true, color: b[2], isTextBox: true, margin: 0 });
    s.addText(b[1], { x: 5.55, y: y + 0.36, w: 3.8, h: 0.65, fontFace: BF, fontSize: 8.5, color: INK, isTextBox: true, margin: 0, valign: "top" });
  });
  s.addText("The escalate scenario (meridian-legacy) is a wrong spec, not a broken generator: the pin is the client's asserted row count, so correct code fails three times and a person sees the contradiction. That is the behaviour a bank wants.", { x: 5.4, y: 4.9, w: 4.1, h: 0.35, fontFace: BF, fontSize: 8, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 9 Data architecture
{
  const s = base("Data architecture: corpus, run store, deploy", "Architecture · data");
  box(s, 0.5, 1.3, 2.9, 1.75, "Corpus (committed, pinned)", "corpus/<client>/spec.md, samples/*, manifest.json: sha256, expected rows, baseline stats, and the scenario's injected_defect / expected_outcome. corpus/_adversarial/<name>/ holds bad artifacts plus the check each must fail.", { bs: 8.5 });
  box(s, 0.5, 3.2, 2.9, 1.65, "Run store (SQLite)", "data/drydock.db: runs + iterations tables plus LangGraph's checkpoint tables, keyed by thread_id = run_id. Artifacts on disk under runs/<run_id>/iter-N/.", { bs: 8.5 });
  arrow(s, 3.4, 2.15, 4.1, 2.9, MINT, 2); arrow(s, 3.4, 4.0, 4.1, 3.2, MINT, 2);
  card(s, 4.1, 2.35, 2.2, 1.4, "EEF6F4", MINT);
  s.addText("Canonical schema", { x: 4.2, y: 2.42, w: 2, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: NAVY, isTextBox: true, margin: 0 });
  s.addText("trade_id\naccount_id\nvalue_date\namount\ncurrency\ncounterparty\ndescription", { x: 4.2, y: 2.72, w: 2, h: 1.0, fontFace: "Courier New", fontSize: 7.8, color: INK, isTextBox: true, margin: 0 });
  arrow(s, 6.3, 3.05, 6.95, 3.05, MINT, 2);
  box(s, 6.95, 1.3, 2.55, 3.55, "deploy/<client>/ (publish only)", "pipeline.py, dag.py, mapping.yaml, approval.json (who, when, sha256 of each file — an audit trail, not a signature). 5 clients published at ship: acme-treasury, blue-harbour-fx, kestrel-payments, northwind-custody, orion-prime.", { bs: 8.5 });
  s.addText("The manifest is the oracle, not a reference implementation: the corpus author's parser builds it offline, the harness never calls it at run time, so a generator cannot pass by reproducing it.", { x: 0.5, y: 4.95, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 10 Integration / provider design
{
  const s = base("Swappable model backends, one contract", "Architecture · providers");
  table(s, [
    ["Provider", "Backend", "Runs where", "Credential"],
    ["fake (default)", "templates + seeded fault injection", "in process", "none"],
    ["ollama", "openai_compat over httpx", "your machine", "OPENAI_API_KEY (any value)"],
    ["vllm", "openai_compat over httpx", "your GPU host", "OPENAI_API_KEY (server's key)"],
    ["bedrock", "boto3 converse API", "your AWS account", "AWS credential chain, AWS_REGION"],
    ["anthropic", "anthropic SDK", "Anthropic's API", "ANTHROPIC_API_KEY"],
  ], 0.5, 1.3, 9.0, [1.6, 3.0, 2.2, 2.2], 9);
  box(s, 0.5, 3.35, 4.4, 1.6, "Data perimeter (what leaves the process)", "Feed contract (columns, formats, quirks); column profiles (row count, amount total, null rates); sample name/size/sha256; at most 5 peeked raw lines per sample; on repair only, the previous artifact plus harness findings. Never sent: whole sample files, anything under deploy/, the SQLite store, credentials.", { bs: 8.5 });
  box(s, 5.1, 3.35, 4.4, 1.6, "The provider changes who writes the code, nothing else", "It changes nothing about the harness, the sandbox, the six checks, the iteration budget or the approval gate. configs/providers/*.yaml name a backend, a model and the environment variable holding a credential — never the credential itself.", { bs: 8.5 });
}

// ---------- 11 Design choices
{
  const s = base("Design choices and why", "Design decisions");
  table(s, [
    ["Decision", "Alternatives considered", "Why this one"],
    ["LangGraph + SQLite checkpointer (ADR-002)", "Hand-rolled state machine", "Interrupts, checkpoint history and cross-process resume are requirements, not conveniences; a hand-rolled machine (as a sibling repo found) does not give all three"],
    ["Python mcp 2.x, in-memory transport for tests (ADR-003)", "Always-stdio MCP, a mocked tool layer", "A real MCP session runs in the offline test suite with no spawned process; stdio only when the sources server runs standalone"],
    ["Airflow validated via a stub package (ADR-004)", "Install real Airflow; AST-only DAG check", "Installing Airflow costs minutes and hundreds of MB and is irrelevant to the skill being shown; a stub records the declared structure"],
    ["Raw backend adapters, not LangChain chat models (ADR-005)", "LangChain chat model wrappers", "Three adapters under 80 lines each behind one ChatBackend protocol make the local-vs-cloud story explicit and keep the base install small"],
    ["Fault injection lives in the corpus manifest (ADR-006)", "Fault injection in the generator itself", "Each scenario declares injected_defect / expected_outcome; the unfixable scenario is a spec that contradicts its sample, keeping the demo honest"],
    ["Three-layer sandbox (ADR-008)", "Static AST guard alone", "A security review showed the guard alone was not a boundary (an attribute hop reached os.system); defence in depth: guard, runtime jail, process containment"],
  ], 0.5, 1.3, 9.0, [2.7, 2.3, 4.0], 8);
}

// ---------- 12 Major features
{
  const s = base("Major features", "Product");
  const feats = [
    ["CLI (typer)", "build, runs, show, approve --approver, reject --note, replay --step N, serve, mcp, bench"],
    ["Review dashboard", "FastAPI JSON API + dependency-free HTML trace viewer: iteration timeline, findings, code tabs with diff, checkpoint list, approve/reject form"],
    ["DRYDOCK MCP server", "7 tools over stdio; approve/reject enforce the gate before RunService is called; a run started from an MCP client shows up in the CLI and dashboard"],
    ["Sources MCP server", "list_samples, peek_sample (<=5 lines, path traversal rejected), profile_sample — the planner's only view of client data"],
    ["Bench + results card", "6 corpus scenarios + 5 adversarial artifacts replayed with seed 42; metrics/headline.json drives the README table and metrics.svg; CI fails on drift"],
    ["Three-layer sandbox", "static AST guard, runtime jail (jailed open, capability-stripped os), process containment (tree kill, rlimits, Windows Job Object, optional Docker)"],
  ];
  feats.forEach((f, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    box(s, 0.5 + col * 3.05, 1.3 + row * 1.65, 2.9, 1.5, f[0], f[1], { bs: 8.5 });
  });
}

// ---------- 13 Screenshot: dashboard self-heal
{
  const s = base("The review dashboard: a self-heal run end to end", "Screenshots · dashboard (blue-harbour-fx)");
  imgFit(s, ASSETS + "01-dashboard-heal.png", 0.5, 1.25, 9.0, 3.65, 1440, 900);
  caption(s, "blue-harbour-fx iteration 1 parsed the trailer row as data and failed H2, H3 and H4; iteration 2 passed all six checks and the run is approved with 2/3 iterations spent.", 0.5, 4.95, 9);
}

// ---------- 14 Screenshot: findings evidence
{
  const s = base("Findings are evidence, not a verdict", "Screenshots · dashboard (blue-harbour-fx, iteration 1)");
  imgFit(s, ASSETS + "02-dashboard-findings.png", 0.5, 1.25, 5.6, 3.65, 1440, 900);
  box(s, 6.25, 1.25, 3.25, 1.7, "What you are looking at", "H2 schema and H3 completeness fail because the trailer row (a record-count footer) was parsed as a data row; H4 drift then shows 11 cascading findings — null rates and distinct counts thrown off by that one bad row.", { bs: 9 });
  box(s, 6.25, 3.1, 3.25, 1.8, "Why this matters", "This is exactly what feeds the repair: the generator's second attempt receives these findings, not a vague \"it failed\". The pinned baseline (14 rows) comes from a manifest the generator never sees.", { bs: 9 });
}

// ---------- 15 Screenshot: approval gate
{
  const s = base("The approval gate: checkpoints and the decision form", "Screenshots · dashboard (acme-treasury, awaiting approval)");
  imgFit(s, ASSETS + "03-dashboard-approval-gate.png", 0.5, 1.25, 9.0, 3.65, 1440, 900);
  caption(s, "acme-treasury's 6 recorded checkpoints — start, load_spec, plan, generate, evaluate — each a LangGraph checkpoint, replayable step by step; the decision form refuses to submit without a named approver.", 0.5, 4.95, 9);
}

// ---------- 16 Screenshot: the gate, run
{
  const s = base("The gate, run: one command, offline", "Screenshots · terminal (scripts/check.py)");
  imgFit(s, ASSETS + "04-terminal-gate.png", 0.5, 1.25, 9.0, 3.65, 1200, 612);
  caption(s, "uv run python scripts/check.py, captured during this review: ruff, mypy strict (host and Linux target), pytest with coverage, the bench replay of all 6 scenarios and 5 adversarial pipelines, and both drift checks.", 0.5, 4.95, 9);
}

// ---------- 17 Security and compliance
{
  const s = base("Security and compliance controls", "Enterprise readiness · controls");
  table(s, [
    ["Layer", "Threat", "Control", "Evidence"],
    ["1. Static AST guard", "Import of a dangerous module; an attribute hop to a real capability (os.path -> os.system)", "Import allowlist; attribute/name denylists; forbidden-call list; runs before anything executes", "test_guard_blocks_payload_before_execution"],
    ["2. Runtime jail", "Reads outside the scratch workdir leak host files into harness evidence, then into a repair prompt", "open/io.open confined to reads inside the workdir; capability-stripped os; poisoned dangerous modules; import finder", "test_*_outside_workdir_is_blocked"],
    ["3. Process containment", "A hung or forked child survives a timeout; unbounded memory", "Process-group/session kill on timeout; POSIX rlimits; Windows Job Object (512 MiB); Docker: read-only mount, --cap-drop ALL, --network none", "test_sleeping_child_tree_is_killed_on_timeout"],
  ], 0.5, 1.3, 9.0, [1.6, 3.2, 2.8, 1.4], 8);
  box(s, 0.5, 3.75, 4.4, 1.2, "What the security review found (2026-09-07)", "3 critical, 4 high, 2 medium findings against drydock.harness.evaluate, all closed before ship (T-012). pip-audit over the locked dependency set: 0 known vulnerabilities.", { bs: 9 });
  box(s, 5.1, 3.75, 4.4, 1.2, "Residual, stated plainly", "approval.json hashes are an audit trail, not a signature (M1). The Windows Job Object memory cap is best-effort; the wall-clock timeout is the backstop. The guard is name-based; layers 2 and 3 exist because of that.", { bs: 9 });
}

// ---------- 18 Enterprise readiness: process
{
  const s = base("How it was built: a gated, evidence-producing lifecycle", "Enterprise readiness · process");
  const gates = ["M0 skeleton", "M1 foundations", "M2 the loop", "M3 surfaces", "M4 evidence", "M5 ship"];
  gates.forEach((g, i) => {
    const x = 0.5 + i * 1.5;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.35, w: 1.42, h: 0.62, fill: { color: i < 5 ? CARD_D : "1E5C57" }, line: { color: i < 5 ? CARD_D : "1E5C57" }, rectRadius: 0.05 });
    s.addText(g, { x: x + 0.04, y: 1.37, w: 1.34, h: 0.58, fontFace: BF, fontSize: 8.5, bold: true, color: WHITE, align: "center", valign: "middle", isTextBox: true, margin: 0 });
  });
  const stats = [["12", "task packs (T-000..T-012), each scoped to disjoint files against a frozen LLD"], ["4", "parallel task waves, then an integration wave (T-011) reconciling 4 cross-component defects"], ["1", "independent security review; 3 critical + 4 high findings, all closed the same day (T-012)"], ["59", "LangGraph checkpoints replayed across the 6 bench scenarios, evidence for every KPI"]];
  stats.forEach((st, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 2.2, 2.15, 1.25);
    s.addText(st[0], { x: x + 0.12, y: 2.25, w: 1.9, h: 0.5, fontFace: HF, fontSize: 28, bold: true, color: GOLD, isTextBox: true, margin: 0 });
    s.addText(st[1], { x: x + 0.12, y: 2.75, w: 1.9, h: 0.65, fontFace: BF, fontSize: 8, color: INK, isTextBox: true, margin: 0, valign: "top" });
  });
  box(s, 0.5, 3.65, 4.4, 1.25, "Frozen contracts, disjoint scope", "models.py and the LLD are frozen; task agents touch only the files in their scope and stop at their pack's Handoff notes if they need more. Rule: files under 800 lines, functions under 50 where practical.", { bs: 9 });
  box(s, 5.1, 3.65, 4.4, 1.25, "One command validates everything", "ruff, ruff format, mypy --strict (host and the Linux CI target), pytest with an 80% coverage floor, the offline bench, and two drift guards (headline.json, the rendered card). CI runs the identical script on every push.", { bs: 9 });
}

// ---------- 19 Quality metrics (native chart)
{
  const s = base("Quality metrics from the gate", "Enterprise readiness · measurement");
  s.addChart(pres.charts.BAR, [{ name: "Value", labels: ["Scenarios as declared", "Healed / heal scenarios", "Adversarial rejected", "Coverage (÷100)"], values: [1.0, 1.0, 1.0, 0.9746] }], {
    x: 0.5, y: 1.3, w: 5.2, h: 3.5, barDir: "bar", chartColors: [MINT], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", dataLabelFontSize: 9, dataLabelColor: INK,
    catAxisLabelColor: INK, catAxisLabelFontSize: 9, valAxisLabelColor: MUTED, valAxisLabelFontSize: 8, valAxisMinVal: 0, valAxisMaxVal: 1.1, valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false, showTitle: true, title: "Ratios (1.0 = target met)", titleFontSize: 10, titleColor: NAVY,
  });
  table(s, [
    ["KPI", "Value", "How"],
    ["Tests / coverage", "505 / 97.46%", "check.py, this review"],
    ["Scenarios as declared", "6 / 6", "bench, seed 42"],
    ["Healed", "4 / 4", "4 heal scenarios"],
    ["Adversarial rejected", "5 / 5", "hand-written artifacts"],
    ["Mean iterations", "2.00", "per run, budget 3"],
    ["Checkpoints", "59", "across 6 bench runs"],
    ["Sandbox escape tests", "25", "test_sandbox_escapes.py"],
  ], 5.9, 1.3, 3.6, [1.5, 1.0, 1.1], 8);
  s.addText("First-pass rate is 1/6 by design: 4 of 6 corpus scenarios inject a defect on purpose so the self-heal path is exercised, and one (meridian-legacy) is built to escalate. Live-provider, Docker-sandbox and real-Airflow rows on the results card are pending — no recorded run exists yet.", { x: 0.5, y: 4.9, w: 9, h: 0.35, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 20 Quirks and limitations
{
  const s = base("Quirks and known limitations (stated, not hidden)", "Honesty");
  const q = [
    ["The bench measures the harness, not a model", "The fake provider is template-driven with scenario-declared defects; it says nothing about any real model's code quality. Live-provider accuracy is pending until a recorded run exists."],
    ["Docker sandbox mode is untested by the bench", "The bench always uses subprocess mode, so its numbers are byte-identical with or without a Docker daemon; the docker=... kind is covered by dedicated tests, not by the headline KPIs."],
    ["Airflow is a stub offline", "Generated DAGs are validated against a package that records structure at import; whether they load in a real scheduler is checked only by the opt-in docker compose --profile airflow target, and that result is pending."],
    ["approval.json is an audit trail, not a signature (M1)", "Its sha256 hashes record what was approved and by whom but are not tamper-evident; anyone who can write deploy/<client>/ can rewrite both the artifact and its recorded hash."],
    ["Windows memory cap is best-effort (H4)", "The Job Object caps committed memory at 512 MiB; if the ctypes call fails, only the wall-clock timeout backstops a memory bomb, which then ends as a timeout rather than a MemoryError."],
    ["The corpus is synthetic", "Six clients and five adversarial cases exercise every branch of the graph and every check; they are not a survey of real feed formats."],
    ["The canonical schema is fixed at 7 columns", "trade_id, account_id, value_date, amount, currency, counterparty, description. Real clients would extend it; that is unbuilt."],
    ["No multi-tenant auth", "The dashboard and the MCP server are local, single-operator tools; SSO or per-tenant isolation is not built."],
  ];
  q.forEach((it, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    box(s, 0.5 + col * 4.6, 1.3 + row * 0.9, 4.45, 0.82, it[0], it[1], { bs: 7.8, ts: 9.5 });
  });
}

// ---------- 21 Cost and performance
{
  const s = base("Cost, performance and operability", "Enterprise readiness · operations");
  const cards = [["0 tokens", "the fake provider drives the bench and CI; a live provider records tokens per call but none has been run yet"], ["2.00", "mean generate/evaluate iterations per run against a budget of 3"], ["30 s / 5 s", "sandbox timeout per sample / H5 latency budget per sample, both configurable"], ["59", "LangGraph checkpoints across 6 bench runs — every step persisted and replayable"]];
  cards.forEach((c, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.15, 1.35);
    s.addText(c[0], { x: x + 0.12, y: 1.35, w: 1.9, h: 0.5, fontFace: HF, fontSize: 22, bold: true, color: GOLD, isTextBox: true, margin: 0 });
    s.addText(c[1], { x: x + 0.12, y: 1.87, w: 1.9, h: 0.75, fontFace: BF, fontSize: 8, color: INK, isTextBox: true, margin: 0, valign: "top" });
  });
  box(s, 0.5, 2.85, 4.4, 2.0, "Operability", "* runbook.md: start/stop, common failures\n* replay <run_id> walks every checkpoint; --step N dumps state at that step\n* events.jsonl: one line per node (node, iteration, ms, outcome) + one llm_usage line per real-model call\n* Rollback is deleting deploy/<client>/; the run and its decision remain in SQLite and runs/", { bs: 9 });
  box(s, 5.1, 2.85, 4.4, 2.0, "What a live run would add to this page", "Prompt/completion tokens and latency per model call, written to events.jsonl by LLMProvider's on_usage callback. No aggregated cost figure exists in the repository today because no live run has been recorded; when one is, the sum over events.jsonl is the figure to report.", { bs: 9 });
}

// ---------- 22 Roadmap
{
  const s = base("Roadmap", "Next steps");
  const phases = [["Now", "Recorded", ["6/6 scenarios, 5/5 adversarial, 505 tests, 97.46% coverage, all offline with the fake provider"]], ["Next", "A live-model run", ["Record one build with Ollama or vLLM and publish its accuracy/cost/latency as an observed figure, replacing the pending row"]], ["Next", "Docker sandbox as a bench input", ["Run the bench under sandbox=docker so the results card reflects the OS-level isolation boundary, not just subprocess mode"]], ["Backlog", "Hardening", ["HMAC-signed approvals (approval.json is presently an audit trail, not a signature); real-Airflow bench row; add DRYDOCK to the profile README"]]];
  phases.forEach((p, i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.15, 3.5, i === 0 ? "EEF6F4" : CARD, i === 0 ? MINT : LINE);
    s.addText(p[0], { x: x + 0.12, y: 1.36, w: 1.9, h: 0.28, fontFace: BF, fontSize: 9, bold: true, color: MINT, charSpacing: 1, isTextBox: true, margin: 0 });
    s.addText(p[1], { x: x + 0.12, y: 1.62, w: 1.9, h: 0.6, fontFace: HF, fontSize: 13, bold: true, color: NAVY, isTextBox: true, margin: 0 });
    bullets(s, p[2], x + 0.12, 2.3, 1.9, 2.4, 9);
  });
  s.addText("Per STATE.md's backlog: none of the next steps are load-bearing for the current, offline gate — they add recorded evidence, not new architecture.", { x: 0.5, y: 4.95, w: 9, h: 0.3, fontFace: BF, fontSize: 9, italic: true, color: MUTED, isTextBox: true, margin: 0 });
}

// ---------- 23 Appendix: decision log
{
  const s = base("Appendix A — Decision log (abridged)", "Appendix");
  table(s, [
    ["ID", "Decision", "Consequence"],
    ["ADR-000", "Design gates self-approved by the orchestrating agent, under the owner's autonomy instruction, for an interview-ready repo fast", "Every gate artifact still exists and is reviewable after the fact"],
    ["ADR-001", "Name: DRYDOCK — a vessel is tested and inspected before the harbour", "Sets the metaphor: Harbormaster controls what enters the harbour, DRYDOCK decides what is seaworthy"],
    ["ADR-002", "LangGraph with a SQLite checkpointer", "Interrupts, checkpoint history and cross-process resume as first-class, zero-infra features"],
    ["ADR-003", "Python mcp 2.x, in-memory transport for tests", "Planner tool calls exercised over a real MCP session with no spawned process in CI"],
    ["ADR-006", "Fault injection lives in the corpus manifest, not the generator", "Keeps the self-heal and escalate demos honest and published, not hard-coded into the model"],
    ["ADR-007", "Four Wave-1 integration reconciliations", "Tool kwarg mismatch, escalate pin, a shifted adversarial slice, and a split adversarial case — all fixed at integration, not before"],
    ["ADR-008", "Security findings drove a three-layer sandbox", "Static guard alone was shown not to be a boundary; guard + runtime jail + process containment closed it"],
  ], 0.5, 1.3, 9.0, [1.1, 4.3, 3.6], 8);
}

// ---------- 24 Appendix: process stats and lessons
{
  const s = base("Appendix B — Build statistics and lessons", "Appendix");
  table(s, [
    ["Item", "Value"],
    ["Task packs", "12 (T-000 .. T-012, including sandbox hardening)"],
    ["Wave schedule", "Wave 1 x4 parallel (corpus, harness, providers, sources MCP) -> Wave 2 x4 (graph, dashboard, MCP server, docs) -> Wave 3 x2 (bench, Airflow) -> Wave 4 (integration + ship)"],
    ["Code review", "approve, 0 critical, 0 high; 1 medium fixed (unbounded errors column), 1 low documented (unused SandboxTimeout)"],
    ["Security review", "3 critical, 4 high, 2 medium before T-012; all closed same day; pip-audit clean"],
    ["Tests / coverage at ship", "505 tests (98% per ship-report; 503 passed / 2 skipped / 97.46% observed in this review)"],
    ["Generated code lines", "1689 across the final pipeline.py, dag.py, mapping.yaml of the 6 bench runs"],
  ], 0.5, 1.3, 9.0, [3.0, 6.0], 8.5);
  box(s, 0.5, 3.75, 9.0, 1.15, "Lessons written into the decision log", "Integration-only defects surfaced where independently built components met (a tool kwarg mismatch, an escalate pin, a shifted adversarial slice) — reconciled in the integration wave, not before. The security review's own payloads are committed as regression tests, so a beaten guard cannot regress silently.", { bs: 9 });
}

// ---------- 25 Appendix: repository map
{
  const s = base("Appendix C — Repository map and how to run", "Appendix");
  s.addText(["drydock/          models.py, paths.py, errors.py, corpus.py", "  harness/        sandbox runner, six checks, stub airflow package", "  providers/      Provider protocol, FakeProvider, LLMProvider, backends", "  mcp/            sources server, toolbox, DRYDOCK's own MCP server", "  graph/          nodes, edges, checkpointer, run store, service API", "  dashboard/      FastAPI JSON API + dependency-free HTML viewer", "  cli.py, bench.py, events.py", "corpus/           six synthetic clients and five adversarial pipelines", "configs/providers/  fake, ollama, vllm, bedrock, anthropic", "metrics/          render.py, card.json, headline.json (bench-written)", "scripts/check.py  the gate: ruff, mypy, pytest, bench, drift checks", "docs/design/      requirements, HLD, LLD, execution plan, decision log", "docs/tasks/       T-000 .. T-012 task packs", "docs/ship-report.md, docs/security.md, docs/serving.md, docs/runbook.md"].join("\n"), { x: 0.5, y: 1.3, w: 5.6, h: 3.5, fontFace: "Courier New", fontSize: 7.3, color: INK, isTextBox: true, margin: 0, valign: "top" });
  card(s, 6.3, 1.3, 3.2, 3.55, CARD_D, CARD_D);
  s.addText("Run it", { x: 6.45, y: 1.38, w: 3, h: 0.3, fontFace: BF, fontSize: 11, bold: true, color: MINT, isTextBox: true, margin: 0 });
  s.addText(["uv sync", "uv run drydock build acme-treasury \\", "  --provider fake", "uv run drydock runs", "uv run drydock approve <run_id> \\", "  --approver <name>", "", "# dashboard", "uv run drydock serve --port 8601", "", "# the whole gate, identical to CI", "uv run python scripts/check.py"].join("\n"), { x: 6.45, y: 1.72, w: 3, h: 3.05, fontFace: "Courier New", fontSize: 8.3, color: WHITE, isTextBox: true, margin: 0, valign: "top" });
}

// ---------- 26 Close
{
  const s = dark("Questions", "DRYDOCK · roshanrana/drydock · 505 tests, 97.46% coverage, one offline gate · design docs and ship report in the repository");
}

pres.writeFile({ fileName: "C:/Code-Central/drydock/docs/pitch/drydock-architecture-deck.pptx" }).then((f) => console.log("wrote", f, "slides", n));
