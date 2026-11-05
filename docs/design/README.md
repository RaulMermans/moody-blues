# Design

The visual identity for MOODY BLUES: **Reality Fracture × Forensic Brutalism**.

| Document | Covers |
|---|---|
| [direction.md](direction.md) | The concept, the three studies, why A with parts of C, and the visual principles |
| [tokens.md](tokens.md) | Every design token and how to use it |
| [components.md](components.md) | The primitives, their typed inputs, and what each may never do |
| [accessibility-and-motion.md](accessibility-and-motion.md) | Accessibility results and the motion language |

Status: **prototype**. Nothing here is in the product yet. The lab is a local route set that does not
exist in a production build ([ADR 0009](../adr/0009-design-lab-isolation.md)).

```bash
make dev-backend    # the lab reads the real evidence API
make design-lab     # http://localhost:3010/design-lab
make test-design    # build the lab, then run its browser tests
```

To refresh the images in [screenshots/](screenshots/):
`MOODY_DESIGN_SHOTS=1 make test-design`.
