import {
  FileBlob,
  PresentationFile,
} from "/Users/chingyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const presentation = await PresentationFile.importPptx(
  await FileBlob.load(
    "/Users/chingyu/Projects/RepoProof/tmp/ethics_pptx_confirmed_governance/template-starter.pptx",
  ),
);
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,table,notes",
  include: "id,slide,name,title,text,textPreview,bbox,rows,cols",
  maxChars: 100000,
});
console.log(snapshot.ndjson);
