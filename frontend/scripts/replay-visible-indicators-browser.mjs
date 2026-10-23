/** Reuse the owned browser harness for replay viewport/lifecycle checks. */
process.argv.push("--replay-visible");
await import("./frontend-script-integration.mjs");
