import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

for (const id of ["tb/ju1grixg", "tb/b61gnyx4", "tb/wrahg3ep", "tb/8bm5cnad", "tb/vedobmxw"]) {
  const table = presentation.resolve(id);
  console.log(`TABLE ${id}`);
  console.dir(table.getCell(0, 0), { depth: 4 });
  for (let r = 0; r < table.rows.length; r += 1) {
    const values = [];
    for (let c = 0; c < table.columns.length; c += 1) {
      values.push(table.getCell(r, c).text.toString());
    }
    console.log(JSON.stringify(values));
  }
}
