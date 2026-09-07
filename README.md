# DRYDOCK

**Agentic pipeline generation and validation harness. Client feed specs in, tested ingestion pipelines out, and nothing sails without a signature.**

A LangGraph state machine plans, generates, sandbox-tests and repairs a data ingestion
pipeline from a client's file specification, then stops at a human approval gate. The
planner gathers evidence through MCP tools; the evaluator is a deterministic six-check
harness; the loop is bounded and every step is checkpointed and replayable.

<!-- metrics:start -->
<!-- metrics:end -->

*Body written in T-008.*
