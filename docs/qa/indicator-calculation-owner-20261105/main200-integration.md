# Integrating merged seconds ownership

PR #200 was merged only after exact head1c429977/base18cd6f34 CI and its scoped
source/Native review. Current main is `a1302842a2a886d27025c73a1c5c151e07fe0fe1`.

Source `d61b3b7abc37ac89c9629640f2c9b123d103e043` merges that main into the
calculation-owner branch without conflicts. All eight owner-foundation source/
test files remain byte-identical to bfcb36b7; this does not qualify old frontend
or Native observations against the changed main200 transport/data code.

The actual combined runtime/ownership/patch/history-batch plus native-seconds
exchange suite passes **104 tests / 1 existing warning / zero skips**; retained
log: `main200-regression.log.gz`. This is a separate integrated run, not 81+23
claims from different revisions. All 39 original dirty QA files retain their
pre-edit SHA256 values. No new Native package or desktop run was performed.

HTTP/WS/frontend owner binding and original Native counter/negative-offset
acceptance are still required. #227 stays Draft. CI remains in the background.
