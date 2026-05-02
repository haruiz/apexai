import { access, cp, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const uiRoot = resolve(root, "..");
const source = resolve(uiRoot, "out");
const target = resolve(uiRoot, "../src/apexai/ui/static");

if (!(await exists(resolve(target, "index.html")))) {
  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });
  await cp(source, target, { recursive: true });
}

await writeFile(resolve(target, ".gitkeep"), "");

console.log(`Static UI is available at ${target}`);

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}
