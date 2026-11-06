# Design

The visual identity for MOODY BLUES: **Beautifully Wrong**, editorial precision with controlled distortion.

| Document | Covers |
|---|---|
| [direction.md](direction.md) | The concept, what changed from Sprint 10 and why, and the visual principles |
| [reality-comparison.md](reality-comparison.md) | The UX specification of the investigation screen, including every copy rule |
| [tokens.md](tokens.md) | Every design token and how to use it |
| [components.md](components.md) | The primitives, their typed inputs, and what each may never do |
| [accessibility-and-motion.md](accessibility-and-motion.md) | Accessibility results and the motion rules |

Status: **in the product on `sprint/11-beautifully-wrong`**, not deployed. The system lives in
`frontend/src/design/` and every product screen reads its tokens. The local design lab now holds one
specimen page, and it does not exist in a production build ([ADR 0009](../adr/0009-design-lab-isolation.md),
[ADR 0010](../adr/0010-design-system-in-the-product.md)).

```bash
make dev-backend    # the screens read the real evidence API
make design-lab     # http://localhost:3010/design-lab/system
make test-design    # browser, rule, axe and WebKit checks on the real recorded evidence
```

To refresh the images in [screenshots/sprint-11/](screenshots/sprint-11/):
`MOODY_DESIGN_SHOTS=1 make test-design`. The images directly in `screenshots/` are the Sprint 10 record.
