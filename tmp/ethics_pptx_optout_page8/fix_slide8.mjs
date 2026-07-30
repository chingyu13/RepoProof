import fs from "node:fs/promises";
import {
  FileBlob,
  PresentationFile,
} from "/Users/chingyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const source =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339_revised.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await presentation.inspect({
  kind: "textbox",
  include: "id,slide,name,text",
  maxChars: 100000,
});
const items = snapshot.ndjson
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line))
  .filter((item) => item.slide === 8);
const byName = new Map(items.map((item) => [item.name, item.id]));

presentation.resolve(byName.get("Text 17")).text =
  "Manual deletion APIs exist. Automatic 1-month deletion: ? · backup location and deletion evidence: ?";
presentation.resolve(byName.get("Text 21")).text =
  "UI currently records opt-in. Cohort opt-out control: ? · CARE de-identification/export: ? · RDS transfer: ? · incident plan: ? · code/IP wording: ?";

const slide8 = presentation.slides.items[7];
const png = await presentation.export({ slide: slide8, format: "png", scale: 1 });
await fs.writeFile(
  "/Users/chingyu/Projects/RepoProof/tmp/ethics_pptx_optout_page8/final-render/slide-08.png",
  new Uint8Array(await png.arrayBuffer()),
);
const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(source);
