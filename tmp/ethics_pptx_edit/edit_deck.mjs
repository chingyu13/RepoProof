import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const workspace = "/Users/chingyu/Projects/RepoProof/tmp/ethics_pptx_edit";
const source = path.join(workspace, "template-starter.pptx");
const output =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339_revised.pptx";
const renderDir = path.join(workspace, "final-render");
const layoutDir = path.join(workspace, "final-layout");

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

function replaceAll(id, oldText, newText) {
  const target = presentation.resolve(id);
  target.text.replace(oldText, newText);
}

presentation.resolve("sh/bu9w7uxo").text = "RepoProof";

replaceAll("sh/i9w3u58v", "Equivalent alternative", "No academic disadvantage");
replaceAll(
  "sh/f29gbyx0",
  "Students who opt out of data retention still earn the 2% the same way.",
  "Declining research retention does not affect the 2% participation credit.",
);

const identityTable = presentation.resolve("tb/ju1grixg");
identityTable.cells.set(1, 0, "900000001");
identityTable.cells.set(2, 0, "900000002");
identityTable.cells.set(3, 0, "900000003");
identityTable.cells.set(4, 0, "900000004");

replaceAll(
  "sh/cf2tcr61",
  "The 2% is never tied to research data. At the 1-month cutoff, individual data is de-identified (not deleted); aggregates kept indefinitely.",
  "Original submissions are deleted after 1 month. Opt-in research records are then de-identified and retained on RDS for 5 years.",
);
replaceAll(
  "sh/yhkbe1o7",
  "Operational  = necessary for teaching, auto-deleted.    Opt-in retained  = evaluate & improve this unit (COMP5339), explicit consent, revocable, own deletion date.",
  "Operational = required for teaching and deleted after 1 month.   Research retained = explicit opt-in, de-identified at cutoff, 5 years on RDS.",
);

const lifecycle = presentation.resolve("tb/8bm5cnad");
const lifecycleRows = [
  [
    "Data",
    "Purpose",
    "Retention",
    "Consent",
    "Identifiability",
  ],
  [
    "Original submission\n(notebook / project files)",
    "Generate questions\nHandle quiz enquiries",
    "Delete 1 month after deadline, including backups",
    "Required for teaching; excluded from research without opt-in",
    "RepoID\n(pseudonymous)",
  ],
  [
    "Extracted structural features\n(no code text in 5-year set)",
    "Reproduce generation\nEvaluate COMP5339 tool",
    "Opt-in only: de-identify at 1 month; retain 5 years on RDS",
    "Explicit opt-in; withdraw before 1-month cutoff",
    "De-identified; remove IDs, filenames and student-defined symbols",
  ],
  [
    "Quiz answers\n(no mark impact)",
    "Immediate feedback\nDe-identified understanding analysis",
    "Operational: 1 month\nOpt-in research set: 5 years",
    "Teaching use required; research retention requires opt-in",
    "RepoID operationally; de-identified before analysis",
  ],
  [
    "De-identified learning analytics\n(reported in aggregate)",
    "Topic distributions\nTiming/performance and cross-semester trends",
    "Operational: 1 month\nOpt-in research set: 5 years",
    "Explicit opt-in for research retention",
    "Semester, topic, duration and completion-period bands; report groups ≥ 5",
  ],
  [
    "Optional Qualtrics survey",
    "Evaluate the learning experience",
    "Anonymous responses retained 5 years on RDS",
    "Explicit opt-in; withdraw before submission only",
    "Anonymous; never linked to RepoID",
  ],
];
for (let r = 0; r < lifecycleRows.length; r += 1) {
  for (let c = 0; c < lifecycleRows[r].length; c += 1) {
    lifecycle.cells.set(r, c, lifecycleRows[r][c]);
  }
}

replaceAll(
  "sh/87ipkzal",
  "What the retained data actually looks like",
  "Operational source data vs five-year research data",
);
replaceAll(
  "sh/u1kbu1ov",
  "assignment Folder student uploaded",
  "Operational submission — delete after 1 month",
);
replaceAll(
  "sh/47mt0b6x",
  "Purpose: for answering student concerns about assessment question\nDelete: 1 month after quiz deadline",
  "Purpose: generate questions and resolve enquiries\nDelete: 1 month after the quiz deadline, including backups",
);
replaceAll(
  "sh/j6dcr65c",
  "chunks of programming code",
  "Operational code chunks — delete after 1 month",
);
replaceAll(
  "sh/i54bylor",
  "student answer",
  "RepoID-linked answers — de-identify at cutoff",
);
replaceAll(
  "sh/cbe5g3ih",
  "feedback survey",
  "Anonymous Qualtrics survey",
);
replaceAll(
  "sh/dcnm98zm",
  "optional participation",
  "Explicit opt-in\nNo RepoID link\nWithdraw before submission\nRetain 5 years on RDS",
);
replaceAll(
  "sh/oryp8fah",
  "    c0  structure     -                  Project file structure\n    c1  imports       bank.py            Imports in bank.py\n    c2  module_var    bank.py            Constant MAX_DAILY_TRANSFER (bank.py)\n    c3  module_var    bank.py            Constant SUPPORT_URL (bank.py)\n    c4  class         bank.py            Class Transaction\n    c5  class         bank.py            Class Account\n    c6  function      bank.py            Function money (bank.py)\n    c7  function      bank.py            Function Account._record (bank.py)\n    c8  function      bank.py            Function Account.deposit (bank.py)\n    c9  function      bank.py            Function Account.withdraw (bank.py)\n   c10  function      bank.py            Function Account.statement (bank.py)\n   c11  function      bank.py            Function transfer (bank.py)\n   c12  source        BankService.java   Java file BankService.java (lines 1-70)\n   c13  flow          bank.py            Call flow from transfer (bank.py)\n   c14  callgraph     -                  Approximate call graph\n   c15  module_graph  -                  Module graph summary\n   c16  symbol_table  -                  Symbol table summary\n   c17  complexity    -                  Static complexity indicators\n   c18  sql_analysis  -                  SQL analysis summary",
  "FIVE-YEAR DE-IDENTIFIED FEATURE SET\n\n• project-structure counts\n• import counts and categories\n• class and function counts\n• module/call-graph summaries\n• control-flow indicators\n• complexity indicators\n• SQL feature counts\n• question topics and review outcomes\n\nRemoved before research analysis:\nSID · RepoID · filenames · student-defined symbols · comments · URLs · source text",
);
replaceAll(
  "sh/yhg7epsj",
  "{\n  \"id\": \"c6\",\n  \"kind\": \"function\",\n  \"title\": \"Function money (bank.py)\",\n  \"text\": \"Function money in bank.py (lines 14-22).\\nParameters: value.\\nDocstring: Normalize an input amount and reject values with more than two decimals.\\nCode:\\ndef money(value: str | int | Decimal) -> Decimal:\\n    \\\"\\\"\\\"Normalize an input amount and reject values with more than two decimals.\\\"\\\"\\\"\\n    try:\\n        amount = Decimal(str(value)).quantize(Decimal(\\\"0.01\\\"))\\n    except (InvalidOperation, ValueError) as exc:\\n        raise ValueError(f\\\"invalid money amount: {value!r}\\\") from exc\\n    if amount < 0:\\n        raise ValueError(\\\"amount cannot be negative\\\")\\n    return amount\",\n  \"file\": \"bank.py\",\n  \"start_line\": 14,\n  \"end_line\": 22,\n  \"snapshot\": \"local-test\",\n  \"evidence_types\": [\n    \"symbol_table\",\n    \"data_flow_graph\",\n    \"control_flow_graph\"\n  ]\n}",
  "{\n  \"study_record_id\": \"random-study-code\",\n  \"assignment\": \"A1\",\n  \"feature_counts\": {\n    \"modules\": 4,\n    \"classes\": 6,\n    \"functions\": 18,\n    \"call_edges\": 25\n  },\n  \"complexity_band\": \"moderate\",\n  \"question_topics\": [\"control flow\", \"data flow\"],\n  \"answers\": [\"A\", \"B\", \"C\", \"B\", \"A\"],\n  \"duration_band\": \"2–3 minutes\"\n}\n\nNo SID, RepoID, filename, symbol name, comment, URL or source text.",
);

presentation.resolve("sh/u1kbu1ov").text =
  "Operational submission";
presentation.resolve("sh/j6dcr65c").text =
  "Operational code chunks";
presentation.resolve("sh/i54bylor").text =
  "Answers at cutoff";
presentation.resolve("sh/cbe5g3ih").text =
  "Anonymous survey";
presentation.resolve("sh/47mt0b6x").text =
  "Purpose: generate questions and resolve enquiries\nDelete: 1 month after the quiz deadline, including backups";
presentation.resolve("sh/oryp8fah").text =
  "FIVE-YEAR DE-IDENTIFIED FEATURE SET\n\n• semester and assignment\n• question topic and response/correctness\n• broad duration band\n• early / middle / late completion-period band\n• project-structure and complexity counts\n• question-review outcomes\n\nSupports topic distributions, timing/performance analysis and comparisons across semesters.\n\nRemoved before research analysis:\nSID · RepoID · exact timestamp · filenames · symbols · comments · URLs · source text";
presentation.resolve("sh/yhg7epsj").text =
  "{\n  \"study_record_id\": \"random-study-code\",\n  \"semester\": \"2026-S2\",\n  \"assignment\": \"A1\",\n  \"question_topic\": \"control flow\",\n  \"response\": \"B\",\n  \"correct\": true,\n  \"duration_band\": \"2–3 minutes\",\n  \"completion_period\": \"middle\",\n  \"complexity_band\": \"moderate\"\n}\n\nLecturer reporting only:\n• topic-level response/correctness distributions\n• duration-band vs correctness distributions\n• early/middle/late group comparisons\n• semester trends and teaching-change comparisons\n• suppress or combine every subgroup with n < 5\n\nNo SID, RepoID, exact timestamp, filename, symbol, comment, URL or source text.";

replaceAll(
  "sh/dcbud0ra",
  "Covered by the CARE umbrella ethics (2025/HE001132) as a prospective sub-study",
  "Proposed for CARE umbrella coverage (2025/HE001132), subject to Working Party approval",
);
replaceAll(
  "sh/zedcfa9g",
  "Safeguards   participation-only (2%)  ·  human-approved  ·  SID never leaves USYD  ·  local model only  ·  withdraw by RepoID until the 1-month cutoff  ·  aggregate-only (min group ≥ 5)",
  "Safeguards   participation-only (2%)  ·  human-approved  ·  SID stays within USYD  ·  local model only  ·  withdraw by RepoID before cutoff  ·  aggregate reporting (groups ≥ 5)",
);
replaceAll(
  "sh/f2d0b6lc",
  "Student code & IP",
  "Data, code & hosting governance",
);
replaceAll(
  "sh/eh4jil4r",
  "Which PIS/Consent wording licenses retaining a de-identified representation to evaluate & improve this unit (COMP5339), including future semesters?",
  "Confirm consent for five-year cross-semester analysis, feature de-identification, hosting region, role-based access, backup deletion, incident response, and secure transfer to RDS.",
);

for (const [id, text] of [
  [
    "nt/ofy9wn61",
    "[Sources]\n- CARE - Substudy guidelines v1c 2026-05-13.docx\n- CARE - Substudy (Prospective) PIS v1b 2025-08-15.docx",
  ],
  [
    "nt/jyx0ra1s",
    "Identity separation — Students click a personalised link; their SID never reaches RepoProof\n\n[Sources]\n- CARE - Substudy guidelines v1c 2026-05-13.docx",
  ],
  [
    "nt/i107q5of",
    "[Sources]\n- CARE - Substudy guidelines v1c 2026-05-13.docx\n- CARE - Substudy (Prospective) PIS v1b 2025-08-15.docx",
  ],
  [
    "nt/x8f69ofe",
    "[Sources]\n- RepoProof proposed data-minimisation design\n- CARE - Substudy guidelines v1c 2026-05-13.docx",
  ],
  [
    "nt/gnmp4jqx",
    "[Sources]\n- CARE - Substudy guidelines v1c 2026-05-13.docx\n- CARE Umbrella Ethics - Sub-Study proposal (v1a).pdf",
  ],
]) {
  presentation.resolve(id).setText(text);
}

await fs.mkdir(renderDir, { recursive: true });
await fs.mkdir(layoutDir, { recursive: true });
for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  await writeBlob(
    path.join(renderDir, `${stem}.png`),
    await presentation.export({ slide, format: "png", scale: 1 }),
  );
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(layoutDir, `${stem}.layout.json`), await layout.text());
}
await writeBlob(
  path.join(workspace, "final-montage.webp"),
  await presentation.export({ format: "webp", montage: true, scale: 1 }),
);

const finalSnapshot = await presentation.inspect({
  kind: "slide,textbox,table,notes",
  include: "id,slide,name,title,text,textPreview,bbox,rows,cols",
  maxChars: 100000,
});
await fs.writeFile(path.join(workspace, "final-inspect.ndjson"), finalSnapshot.ndjson);

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(output);
console.log(output);
