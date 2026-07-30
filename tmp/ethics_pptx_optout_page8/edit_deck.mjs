import fs from "node:fs/promises";
import path from "node:path";
import {
  FileBlob,
  PresentationFile,
} from "/Users/chingyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const workspace = "/Users/chingyu/Projects/RepoProof/tmp/ethics_pptx_optout_page8";
const source =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339_revised.pptx";
const output =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339_revised.pptx";
const renderDir = path.join(workspace, "final-render");
const layoutDir = path.join(workspace, "final-layout");

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

presentation.resolve("sh/f29gbyx0").text =
  "Students may opt out of cohort aggregate analytics; the 2% participation credit is unaffected.";

presentation.resolve("sh/cf2tcr61").text =
  "Original submissions are deleted after 1 month. Individual research records require opt-in; approved cohort aggregates may use opt-out.";
presentation.resolve("sh/yhkbe1o7").text =
  "Operational = required for teaching, deleted after 1 month.   Individual research = opt-in.   Cohort aggregate analytics = proposed opt-out, subject to CARE approval.";

const lifecycle = presentation.resolve("tb/8bm5cnad");
lifecycle.cells.set(
  4,
  3,
  "Proposed opt-out for cohort aggregate analytics; subject to CARE approval; no effect on 2%",
);
lifecycle.cells.set(
  4,
  2,
  "De-identified aggregate analysis retained 5 years on RDS",
);

presentation.resolve("sh/l0vuh0rm").text =
  "CARE mapping   individual research retention → opt-in  ·  cohort aggregate analytics → proposed opt-out (approval pending)  ·  2% unaffected  ·  5 yrs on RDS";

const slide8 = presentation.slides.items[6].duplicate();
const duplicateSnapshot = await presentation.inspect({
  kind: "textbox,notes",
  include: "id,slide,name,text",
  maxChars: 100000,
});
const duplicateItems = duplicateSnapshot.ndjson
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line))
  .filter((item) => item.slide === 8);
const byName = new Map(
  duplicateItems
    .filter((item) => item.kind === "textbox")
    .map((item) => [item.name, item.id]),
);
const setByName = (name, text) => {
  const id = byName.get(name);
  if (!id) throw new Error(`Missing slide 8 textbox: ${name}`);
  presentation.resolve(id).text = text;
};

setByName("Text 0", "Deployment & governance checklist");
setByName(
  "Text 1",
  "Known from repository documentation; ? = not documented or not yet decided",
);
setByName(
  "Text 3",
  "Known architecture   FastAPI  ·  SQLite (WAL)  ·  local project directory  ·  manual delete APIs  ·  events store derived metadata, not raw code",
);
setByName(
  "Text 5",
  "Privacy mode   LOCAL_ONLY can disable OpenAI  ·  local LLM receives structured evidence only  ·  instructor reviews questions before release",
);

setByName("Text 8", "Hosting & data location");
setByName(
  "Text 9",
  "Live URL: repoproof.chingyu.site · hosting provider: ? · data region: ? · production server/DB location: ? · encryption at rest: ?",
);
setByName("Text 12", "Access & role separation");
setByName(
  "Text 13",
  "Creator access: shared password + HMAC-signed HttpOnly session (8 h) + IP login throttle. Per-user roles: none. Student developer / lecturer / CARE staff permissions: ?",
);
setByName("Text 16", "Deletion & backups");
setByName(
  "Text 17",
  "Manual project and attempt deletion APIs exist. Automatic 1-month deletion: ? · backup location: ? · backup deletion evidence: ?",
);
setByName("Text 20", "Research operations");
setByName(
  "Text 21",
  "Current UI records research opt-in. Cohort opt-out control/workflow: ? · independent CARE de-identification/export: ? · secure RDS transfer: ? · incident plan: ? · student-code/IP wording: ?",
);

const slide8Notes = duplicateItems.find((item) => item.kind === "notes");
if (slide8Notes) {
  presentation.resolve(slide8Notes.id).setText(
    "[Sources]\n- README.md\n- app/config.py\n- app/db.py\n- app/main.py\n- docs/解釋.md\n- docs/flow/2 Project Intake.md\n- docs/flow/6 Structured Path.md\n- docs/flow/7 Persistence.md\n- docs/flow/8-2 Take and Score.md",
  );
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
