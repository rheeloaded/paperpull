---
target: PaperPull control panel vs Apple HIG
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/jacobmcmillan/Documents/PaperPull/_dev/wt-design-refresh/gui/static/index.html"
target_fingerprint: "sha256:c814d3b0484677e6f942af6c52b158060e6b594a7394e30e87b06686c1b5e362"
target_path: /Users/jacobmcmillan/Documents/PaperPull/_dev/wt-design-refresh/gui/static/index.html
timestamp: 2026-11-07T21-48-40Z
slug: gui-static-index-html
---
# PaperPull control panel critique (Apple HIG lens), 2026-11-07
Method: dual-agent (A: design review, B: detector + browser)
Score 26/40 (Acceptable). H1 3, H2 3, H3 3, H4 2, H5 3, H6 2, H7 2, H8 2, H9 3, H10 3.
Specificity: copy is authored; visual layer is generic SaaS (letter-avatar tiles with meaningless hashed tints, tinted icon tiles on summary cards, pill chips/stepper/filters, card-per-section, same #2f6fe0 accent in both themes, solid blue Start on every row).
Detector: source 0; rendered 6 (nested-cards x3 false positive on .seg; straggler x2 advisory; line-length x1 real on account-page step paragraph ~104ch). Overlay blocked by app CSP.
Priority issues:
- P1 Generic decoration: letter tiles, icon tiles, pills -> quieter
- P1 Button hierarchy: filled primary on every row -> distill
- P1 Long flat provider list with repeated row sentence, no search -> distill/onboard (81-row state partly a dev-checkout artifact)
- P2 Settings card soup, per-section Save, slug selects -> layout (grouped inset list)
- P2 Row menu 9 two-line items; Esc loses focus -> harden
- P2 Off-grid spacing (10/14/18/22), dark accent not adapted, hardcoded runbar colors -> polish
