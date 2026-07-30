import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source =
  "/Users/chingyu/Projects/RepoProof/docs/ethics/RepoProof_Ethics_COMP5339.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,table,notes,layout",
  include: "id,slide,name,title,text,textPreview,bbox,rows,cols,isPlaceholder",
  maxChars: 100000,
});
console.log(snapshot.ndjson);
