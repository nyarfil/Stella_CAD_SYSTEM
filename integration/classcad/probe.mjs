import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(process.argv[2] ?? path.join(here, 'verification'));
const client = new Client({ name: 'stella-classcad-isolated-probe', version: '0.1.0' });
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.join(here, 'node_modules/@classcad/mcp/dist/server.js')],
  env: { ...process.env, CLASSCAD_ENGINE: 'wasm', CLASSCAD_VIEWER_OPEN: '0', CLASSCAD_AUTH_NO_BROWSER: '1' },
  stderr: 'pipe',
});
let diagnostics = '';
transport.stderr?.on('data', data => { diagnostics += String(data); });
try {
  await mkdir(output, { recursive: true });
  await client.connect(transport);
  const inventory = await client.listTools();
  await writeFile(path.join(output, 'tools.json'), JSON.stringify(inventory, null, 2));
  console.log(JSON.stringify({ connected: true, toolCount: inventory.tools.length, tools: inventory.tools.map(t => t.name) }));
  if (process.argv.includes('--build')) {
    const call = async (name, args) => {
      const result = await client.callTool({ name, arguments: args }, undefined, { timeout: 120000 });
      const text = (result.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      if (result.isError) throw new Error(`${name}: ${text.slice(0, 1200)}`);
      return { text, isError: Boolean(result.isError) };
    };
    const docs = await call('docs', { keys: ['recipes/parametric-part', 'v1.part.create', 'v1.part.box', 'v1.part.calculateMassProperties'] });
    await writeFile(path.join(output, 'method-docs.txt'), docs.text);
    await call('use_session', { engine: 'wasm' });
    const script = `const { result: part } = await api.v1.part.create({ name: 'Stella isolated box probe' });\nawait api.v1.part.box({ id: part, length: 20, width: 10, height: 5 });\nconst { result: mass } = await api.v1.part.calculateMassProperties({ id: part });\nreturn { part, volume_mm3: mass.volume, expected_volume_mm3: 1000 };`;
    await writeFile(path.join(output, 'request.js'), script);
    const built = await call('run_script', { script, label: 'Stella isolated 20x10x5 mm probe', timeoutMs: 60000 });
    const safeText = built.text.replace(/https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/\S+/g, '[private session link]');
    await writeFile(path.join(output, 'build-result.txt'), safeText);
    console.log(JSON.stringify({ stage: 'build', result: safeText }));
    const saved = await call('save', { format: 'STP', path: path.join(output, 'box.step') });
    await writeFile(path.join(output, 'save-result.txt'), saved.text);
    await call('snapshot', { outDir: output, label: 'box', width: 600, height: 450, view: 'iso', annotate: true, recalc: false });
    console.log(JSON.stringify({ stage: 'export', step: path.join(output, 'box.step'), snapshot: 'box' }));
  }
} catch (error) {
  console.error(JSON.stringify({ connected: false, error: error.message }));
  process.exitCode = 1;
} finally {
  await client.close();
  // Diagnostics can contain authentication links; do not persist or print them.
}
