import fs from "node:fs/promises";
import path from "node:path";
import {
  FileBlob,
  PresentationFile,
} from "/Users/chingyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workspace = "/Users/chingyu/Projects/RepoProof/tmp/ethics_pptx_confirmed_governance";
const source = path.join(workspace, "template-starter.pptx");
const output =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339_revised.pptx";
const renderDir = path.join(workspace, "final-render");
const layoutDir = path.join(workspace, "final-layout");

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

presentation.resolve("sh/65g3298r").text =
  "Participation-only (2%)  ·  human-approved  ·  pseudonymous  ·  local model  ·  individual opt-in  ·  cohort opt-out";

presentation.resolve("sh/f29gbyx0").text =
  "Students may opt out of cohort analytics via confidential Qualtrics before the quiz deadline; the 2% credit is unaffected.";

presentation.resolve("sh/cf2tcr61").text =
  "Operational data is deleted after 1 month. Individual research records require opt-in; cohort aggregate analytics use proposed CARE-approved opt-out.";
presentation.resolve("sh/yhkbe1o7").text =
  "Operational = teaching use, manually deleted after 1 month.   Individual research = opt-in.   Cohort analytics = proposed opt-out via Qualtrics by quiz deadline.";

const lifecycle = presentation.resolve("tb/8bm5cnad");
lifecycle.cells.set(
  1,
  2,
  "Manual deletion 1 month after deadline; no routine application backup",
);
lifecycle.cells.set(
  3,
  3,
  "Teaching use required; individual research retention requires opt-in",
);
lifecycle.cells.set(
  4,
  2,
  "De-identified cohort analysis retained 5 years on University RDS",
);
lifecycle.cells.set(
  4,
  3,
  "Proposed opt-out via confidential Qualtrics by quiz deadline; independent CARE staff processes exclusions",
);

presentation.resolve("sh/zedcfa9g").text =
  "Safeguards   participation-only (2%)  ·  human-approved  ·  SID stays within USYD  ·  local model only  ·  cohort opt-out via Qualtrics by quiz deadline  ·  report groups ≥ 5";
presentation.resolve("sh/l0vuh0rm").text =
  "CARE mapping   individual research retention → opt-in  ·  cohort analytics → proposed opt-out via Qualtrics  ·  independent staff processes exclusions  ·  2% unaffected";
presentation.resolve("sh/eh4jil4r").text =
  "Confirmed: AWS EC2 Sydney, encrypted EBS, sole current operator, manual deletion and no routine backup. Still implement full feature de-identification and confirm secure RDS transfer.";

presentation.resolve("sh/g72x4zyd").text =
  "Confirmed from repository documentation and operating decisions as at 29 July 2026";
presentation.resolve("sh/98rehwve").text =
  "DNS/domain: Squarespace · application and SQLite: AWS EC2, ap-southeast-2 Sydney · EBS encryption: enabled with alias/aws/ebs";
presentation.resolve("sh/1k7edwv2").text =
  "Current production access: student developer only, via shared-password creator session. Lecturer/CARE staff: no production access. Future app users need individual roles; AWS IAM is for infrastructure administrators only.";
presentation.resolve("sh/lgbepgvm").text =
  "Student developer manually deletes operational data 1 month after the deadline. No routine application backup. Temporary migration snapshot: delete after verification. Deletion log: planned.";
presentation.resolve("sh/6twve1oz").text =
  "Cohort opt-out: confidential Qualtrics by quiz deadline. Independent CARE staff holds SID ↔ RepoID ↔ FolderID mapping and processes exclusions. University RDS: 5 years. Incidents follow University Data Breach Policy.";

const page8Notes = presentation.resolve("nt/fu1gfa1s");
page8Notes.setText(
  "[Sources]\n- README.md\n- app/config.py\n- app/db.py\n- app/main.py\n- app/static/assess.html\n- CARE - Substudy (Prospective) Recruitment - optout v1b 2025-08-15.docx\n- University of Sydney Data Breach Policy 2023\n- User-confirmed AWS deployment and operating procedures (2026-07-29)",
);

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

const snapshot = await presentation.inspect({
  kind: "slide,textbox,table,notes",
  include: "id,slide,name,title,text,textPreview,bbox,rows,cols",
  maxChars: 100000,
});
await fs.writeFile(path.join(workspace, "final-inspect.ndjson"), snapshot.ndjson);

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(output);
console.log(output);
