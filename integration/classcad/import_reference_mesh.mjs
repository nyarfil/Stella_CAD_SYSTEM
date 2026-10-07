// Isolated ClassCAD import/export of supplied reference geometry, without edits.
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
if (source === output || path.extname(output).toLowerCase() !== '.step') throw Error('Separate STEP output required');
const payload = await readFile(source);
const digest = createHash('sha256').update(payload).digest('hex');
const client = new Client({name:'stella-isolated-reference-import',version:'0.1.0'});
const transport = new StdioClientTransport({
  command:process.execPath,
  args:[path.join(here,'node_modules/@classcad/mcp/dist/server.js')],
  env:{...process.env,CLASSCAD_ENGINE:'wasm',CLASSCAD_VIEWER_OPEN:'0',CLASSCAD_AUTH_NO_BROWSER:'1'},
  stderr:'pipe'
});
let diagnostics='';
transport.stderr?.on('data',data=>{diagnostics+=String(data);});
const call = async(name,args)=>{
  const result=await client.callTool({name,arguments:args},undefined,{timeout:120000});
  const text=(result.content??[]).filter(c=>c.type==='text').map(c=>c.text).join('\n');
  if(result.isError) throw Error(`${name}: ${text.slice(0,1500)}`);
  const firstLine=text.split('\n')[0];
  if(firstLine.startsWith('{')) {
    let semantic;
    try {semantic=JSON.parse(firstLine);} catch {}
    if(semantic?.ok===false || semantic?.success===false) throw Error(`${name}: ${firstLine.slice(0,1500)}`);
  }
  return text;
};
try {
  await mkdir(path.dirname(output),{recursive:true});
  await client.connect(transport);
  await call('use_session',{engine:'wasm'});
  const loaded=await call('load',{format:'STL',content:payload.toString('base64')});
  console.log(JSON.stringify({stage:'import',source:path.basename(source),sha256:digest,result:loaded}));
  const saved=await call('save',{format:'STP',path:output});
  if(createHash('sha256').update(await readFile(source)).digest('hex')!==digest) throw Error('Source changed');
  const report={source:path.basename(source),source_sha256:digest,output,
    output_sha256:createHash('sha256').update(await readFile(output)).digest('hex'),
    import_result:loaded,export_result:saved,
    scope:'Unmodified mesh import/export only; validity and geometry equivalence require separate inspection.'};
  await writeFile(output+'.import.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({stage:'export',output,sha256:report.output_sha256}));
} catch(error) {
  console.error(JSON.stringify({success:false,error:error.message}));process.exitCode=1;
} finally {await client.close();}
