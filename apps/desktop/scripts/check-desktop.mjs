import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = { ...process.env, RUSTUP_TOOLCHAIN: process.env.RUSTUP_TOOLCHAIN ?? '1.90.0' };

function hostTriple() {
  const result = spawnSync('rustc', ['-vV'], { encoding: 'utf8', env });
  const match = /^host:\s*(\S+)/m.exec(result.stdout ?? '');
  return match?.[1] ?? '';
}

const triple = hostTriple();
if (!triple) {
  console.error('Unable to determine Rust host triple.');
  process.exit(1);
}
const extension = process.platform === 'win32' ? '.exe' : '';
const binaries = path.join(root, 'src-tauri', 'binaries');
const stub = path.join(binaries, `aibox-server-${triple}${extension}`);
let createdStub = false;
if (!existsSync(stub)) {
  mkdirSync(binaries, { recursive: true });
  writeFileSync(stub, 'AIBox compile-check placeholder');
  createdStub = true;
}

const result = spawnSync(
  'cargo',
  ['check', '--manifest-path', path.join('src-tauri', 'Cargo.toml')],
  { cwd: root, stdio: 'inherit', env },
);

if (createdStub) {
  try {
    unlinkSync(stub);
  } catch {
    // Best-effort cleanup; the file is ignored by git.
  }
}
process.exit(result.status ?? 1);
