---
name: expert-interview-openspec
description: "Run a two-expert project interview, record decisions and risks, and translate approved decisions into OpenSpec artifacts. Use when planning, reviewing, or correcting a portfolio project."
---

# Expert Interview + OpenSpec

Use this skill to turn a vague project idea or an implementation checkpoint into an evidence-backed decision record.

## Roles

- **Technical architect:** validates data flow, feasibility, safety, observability, and reproducibility.
- **Portfolio reviewer:** challenges user value, job relevance, demonstrable evidence, and overclaims.
- **User:** approves scope, priorities, and any external or irreversible action.

## Workflow

1. Inspect the project and state factual findings separately from proposed decisions.
2. Run a concise cross-examination: architect proposes; reviewer challenges; architect responds with a verification method.
3. Record decisions, evidence, constraints, exclusions, risks, and unresolved questions using [the framework](references/interview-framework.md).
4. Do not advance when there is a P0 issue: unverified data rights, a broken end-to-end path, unsupported quality claims, missing source-to-citation traceability, or a required external credential.
5. Ask the user only for a decision, permission, credential setup, or priority that cannot be discovered locally. Otherwise implement the approved next task autonomously.
6. After approval, map the record to OpenSpec:
   - Why and impact → `proposal.md`
   - observable promises → `specs/*/spec.md`
   - design choices, alternatives, risks → `design.md`
   - verifiable work → `tasks.md`
7. Before declaring a milestone complete, run relevant tests and OpenSpec strict validation. Report verified facts, remaining risks, and the next autonomous action.

## Guardrails

- Never present synthetic fixtures, metadata-only catalogs, or untested designs as production-quality evidence.
- Keep secrets out of chat, source control, logs, and generated reports. Use local environment variables for credentials.
- Preserve project scope unless the user explicitly approves a change. If an issue changes scope materially, explain it and request direction.
