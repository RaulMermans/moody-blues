import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import path from "node:path";

const ARTIFACTS = "frontend/.e2e-worlds/artifacts";

export default function seed() {
  const root = path.resolve(__dirname, "../..");
  rmSync(path.join(root, ARTIFACTS), { recursive: true, force: true });
  execFileSync("uv", ["run", "python", "-m", "tests.external.seed_worlds_ui", ARTIFACTS], { cwd: root, stdio: "inherit" });
}
