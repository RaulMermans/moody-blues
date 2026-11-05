// Mirrors backend/moody_blues/contracts/containment.py.
export type ContainmentAttempt = {
  attempt_id: string;
  attempted: string;
  boundary: string;
  held: boolean;
  observed: string;
  exit_code: number | null;
  run_status: string;
  duration_ms: number;
  cleaned_up: boolean;
  host_unaffected: boolean;
  host_check: string;
};

export type ContainmentReport = {
  schema_version: "mb-containment/1";
  status: "PASS" | "FAIL";
  generated_at: string;
  git_commit: string | null;
  host: {
    environment: "vultr_hosted" | "local_development";
    instance_id: string | null;
    region: string | null;
    architecture: string;
    kernel: string;
    operating_system: string;
    docker_version: string;
    cgroup_version: string;
    cgroup_driver: string;
    default_runtime: string;
    runtimes: string[];
    security_options: string[];
    image: string;
    image_id: string | null;
  };
  attempts: ContainmentAttempt[];
  effective_checks: { name: string; status: "PASS" | "FAIL"; detail: string }[];
  leftover_containers: number;
  limitations: string[];
  sha256: string;
};
