# infrastructure/

How the system is deployed (§13, §15) — infra-as-code only, no application logic.

- `docker/` — Dockerfiles per service (api, worker, frontend).
- `terraform/` — cloud resources, networking, secrets-manager wiring (later slice).
- `k8s/` — deployment manifests / Helm charts (later slice).
