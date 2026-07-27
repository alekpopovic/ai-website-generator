import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import process from 'node:process';
import { URL, fileURLToPath } from 'node:url';

import { createClient } from '@hey-api/openapi-ts';

import { generatorConfig } from '../openapi-ts.config.mjs';

const packageRoot = resolve(fileURLToPath(new URL('..', import.meta.url)));
const committedDirectory = join(packageRoot, 'src', 'generated');
const temporaryRoot = await mkdtemp(join(tmpdir(), 'platform-api-client-'));
const temporaryDirectory = join(temporaryRoot, 'generated');

try {
  await createClient({
    ...generatorConfig,
    input: join(packageRoot, 'openapi.json'),
    output: { ...generatorConfig.output, path: temporaryDirectory },
  });
  const differences = await compareDirectories(committedDirectory, temporaryDirectory);
  if (differences.length > 0) {
    process.stderr.write(
      `Generated API client is stale (${differences.join(', ')}). Run task generate-api-client.\n`,
    );
    process.exitCode = 1;
  }
} finally {
  await rm(temporaryRoot, { force: true, recursive: true });
}

async function compareDirectories(left, right) {
  const leftFiles = await listFiles(left);
  const rightFiles = await listFiles(right);
  const paths = [...new Set([...leftFiles, ...rightFiles])].sort();
  const differences = [];
  for (const path of paths) {
    if (!leftFiles.includes(path) || !rightFiles.includes(path)) {
      differences.push(path);
      continue;
    }
    const [leftContent, rightContent] = await Promise.all([
      readFile(join(left, path), 'utf8'),
      readFile(join(right, path), 'utf8'),
    ]);
    if (leftContent !== rightContent) differences.push(path);
  }
  return differences;
}

async function listFiles(root) {
  const entries = await readdir(root, { recursive: true, withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile())
    .map((entry) => relative(root, join(entry.parentPath, entry.name)))
    .sort();
}
