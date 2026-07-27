# CellWiki Domain Context

This file defines the product language used by implementation modules, tests, and architecture decisions.

## Core concepts

- **Project**: one isolated CellWiki knowledge workspace. Sources, formal knowledge, runtime state, indexes, memories, and backups never cross project scope implicitly.
- **SourceRecord**: the immutable identity and lifecycle metadata of an imported paper, document, or registered network source.
- **ParsedDocument**: a rebuildable, page-aware representation derived from a SourceRecord.
- **Claim**: a normalized scientific statement with one or more verifiable EvidenceReferences.
- **EvidenceReference**: a locator that resolves a Claim back to a registered SourceRecord and an exact page, block, section, or excerpt.
- **Formal knowledge**: approved extraction and curation data. It is the truth source for Wiki projection, search, and graph derivations.
- **Wiki projection**: rebuildable Markdown generated from formal knowledge. Generated content and human curation remain distinguishable.
- **ChangeSet**: the only proposal format allowed to change formal knowledge. A ChangeSet requires approval and CentralWriter verification.
- **ReviewItem**: a conflict, evidence gap, memory candidate, research candidate, or semantic finding that requires deterministic validation or human judgment.
- **AgentRun**: a durable execution with explicit state, budget, events, checkpoint, and approval continuation.
- **SearchIndex**: a disposable SQLite FTS5 projection over Wiki pages, entities, claims, sources, evidence, and findings.
- **KnowledgeGraph**: a disposable graph projection over formal extraction and ontology data. Every material edge keeps its Claim and SourceRecord provenance.
- **MemoryCandidate**: an Agent proposal for non-secret preference, project rule, episode summary, or reliable operating knowledge. It is not memory until admitted by MemoryStore policy.
- **Episode**: an auditable summary of one AgentRun's outcome, decisions, recalled memory IDs, and unresolved work. It never becomes formal scientific knowledge.
- **StableMemory**: a project-scoped, admitted preference or operating rule with confidence, expiry, provenance, and conflict state.
- **SemanticSnapshot**: a disposable retrieval projection over formal knowledge; deleting it cannot change the Wiki.
- **ResearchCandidate**: external metadata or content registered as a SourceRecord and proposed as candidate Evidence. It cannot publish directly.
- **L2Finding**: a non-mutating semantic warning about contradictions, unsupported statement strength, singleton evidence, or missing context.

## Invariants

1. Formal knowledge changes only through `ChangeSet -> Approval -> CentralWriter -> Verification`.
2. SearchIndex, KnowledgeGraph, and SemanticSnapshot are derived and fully rebuildable.
3. Source files and user projects live outside the installation directory in release builds.
4. Local write, Agent run, approval, memory mutation, research, and lifecycle requests require the current desktop bearer token in release mode.
5. Memory and Research never store hidden chain-of-thought and never bypass source registration or approval.
6. Scientific text is not silently translated when the application language changes.
7. Ingest, Lint, and formal publication observe a project-scoped KnowledgeSnapshot; a stale ChangeSet cannot write after the formal knowledge version changes.
8. Query defaults to the formal stable knowledge projection; candidate and review state is not silently presented as published knowledge.
