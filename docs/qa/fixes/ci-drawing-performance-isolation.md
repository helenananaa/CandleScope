# Isolate the drawing command latency gate

The macOS CI job ran the 512-entity drawing command benchmark alongside three other test files. Its wall-clock measurements included time waiting for CPU resources. On the unchanged main baseline, GitHub Intel recorded p95 values of 3.976, 3.743 and 4.090ms under four-file concurrency, then 0.324, 0.305 and 0.458ms in isolated runs. One 36-command sample took 184.35ms wall time but only 19.16ms of thread CPU time.

Diagnostic evidence: https://github.com/helenananaa/CandleScope/actions/runs/38841474868

`run-frontend-tests.mjs` discovers the complete selection, runs functional files with the requested concurrency, waits for their processes to exit, and then runs the drawing command performance test alone. Both stages contribute to the final exit status. The existing 1ms wall-clock threshold, three measurement attempts, and synchronous/correctness assertions remain unchanged.

The default, serial, drawing, and area/profile frontend test commands use this scheduler. `npm run test:performance` also runs the gate directly. Discovery still includes nested TSX, colocated TypeScript, and script tests, while expansion inside Node avoids Windows command-line length limits.

Runner regressions exercise process-exit ordering, overlapping discovery patterns, failure propagation from either stage, and empty/invalid selections. Hosted runners can still have occasional external scheduling outliers; isolation removes competition from our own functional test processes.
