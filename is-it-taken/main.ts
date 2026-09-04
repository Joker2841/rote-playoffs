#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: is-it-taken
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/is-it-taken
 * description: 'Answers the question worth asking before you write a line: has someone already published this. The public registry went from 242 plays to 411 in twenty-four hours, so nobody can hold it in their head, and rote play search answers one query at a time using the words you happened to choose. This fans your idea out into a dozen queries drawn from its own content words, so a play that solves the same problem in different vocabulary still surfaces, then ranks what comes back by how close it actually is rather than by how popular it is. A play with forty downloads that shares one incidental word is not a collision; a play with three downloads whose name is your idea is. It returns one of four verdicts. Already built, when something matches closely enough that you should read it before writing anything. Crowded, when there is no exact match but enough adjacent work that yours has to differ in a way a stranger can see. Adjacent work exists, when one or two are close enough to read first. And nothing close found, which is deliberately not phrased as proof: matching here is lexical, two people can describe the same idea in words that share nothing, and a confident all clear from a word matcher would be the most damaging thing this could say. So the limit is printed in the output every time, along with any query that failed, because a failed query is not an empty result. I built this after losing several hours to exactly this mistake: I published a play that already existed under the same name, by an author a day ahead of me, because my own registry survey used the vocabulary of the ideas I had already chosen rather than the one I later built. Read-only. It searches the public registry through rote, reads nothing local, writes nothing, and needs no credentials.'
 * provenance:
 *   author: sai0000 <jokerbj2841@gmail.com>
 *   url: https://github.com/Joker2841/rote-playoffs
 * license: MIT
 * tags:
 * - domain-rote-plays
 * - audience-play-authors
 * - job-duplicate-check
 * - registry
 * - idea-validation
 * - before-you-build
 * - search
 * - discovery
 * - prior-art
 * - hackathon
 * - tool-shell
 * - effect-read-only
 * parameters:
 * - name: idea
 *   type: string
 *   required: true
 *   description: 'What you are about to build, in a sentence. Plain words work better than a name: describe the problem it solves, not what you would call it.'
 * - name: format
 *   type: string
 *   required: false
 *   default: text
 *   valid_values:
 *   - text
 *   - json
 *   description: text for the human verdict, json for a machine-readable one suitable for gating a build script.
 * metadata:
 *   version: 0.1.0
 *   rote_version: 0.78.0
 *   status: released
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   requires_sessions: false
 *   contract:
 *     atomic: true
 *     composable: true
 *     input:
 *       type: none
 *     output:
 *       format: text
 *       destination: stdout
 *   discoverability:
 *     tags:
 *     - domain-rote-plays
 *     - audience-play-authors
 *     - job-duplicate-check
 *     - registry
 *     - idea-validation
 *     - before-you-build
 *     - search
 *     - discovery
 *     - prior-art
 *     - hackathon
 *     - tool-shell
 *     - effect-read-only
 * presentation_fixtures:
 *   search_registry: resources/presentation-fixtures/search_registry/fixture.yaml
 *   assess_overlap: resources/presentation-fixtures/assess_overlap/fixture.yaml
 *   render_verdict: resources/presentation-fixtures/render_verdict/fixture.yaml
 * steps:
 *   search_registry:
 *     type: process.exec
 *     timeout_ms: 900000
 *     argv:
 *     - python3
 *     - '@resource{search_registry.py}'
 *     - $idea
 *   assess_overlap:
 *     type: process.exec
 *     timeout_ms: 120000
 *     depends_on:
 *     - search_registry
 *     argv:
 *     - python3
 *     - '@resource{assess_overlap.py}'
 *     - '@search_registry{.stdout.text}'
 *   render_verdict:
 *     type: process.exec
 *     timeout_ms: 60000
 *     depends_on:
 *     - assess_overlap
 *     argv:
 *     - python3
 *     - '@resource{render_verdict.py}'
 *     - '@assess_overlap{.stdout.text}'
 *     - $format
 * ---
 */

const presentationSdk = await import("__ROTE_PRESENTATION_SDK__").catch((cause) => {
  throw new Error(
    "This is a rote steps presentation program. Run it with `rote play run <name>`.",
    { cause },
  );
});
const { FlowOutput, loadPresentationContext, stepName } = presentationSdk;

const out = new FlowOutput();
const ctx = await loadPresentationContext();

// A search that did not complete is never presented as an empty registry.
// "nothing similar exists" and "the search failed" must not read alike here.
function stdoutOf(step: ReturnType<typeof ctx.step>): string | null {
  if (step.outcome.status !== "completed" && step.outcome.status !== "restored") return null;
  const body = step.outcome.output.body as { stdout?: { text?: string } } | undefined;
  return body?.stdout?.text ?? null;
}

function statusOf(step: ReturnType<typeof ctx.step>): string {
  switch (step.outcome.status) {
    case "completed":
    case "restored": return "ok";
    case "skipped": return `skipped: ${step.outcome.output.reason}`;
    case "failed": return `failed: ${step.outcome.output.message}`;
    case "blocked": return `blocked: ${step.outcome.output.reason}`;
    default: return "unknown";
  }
}

const search = ctx.step(stepName("search_registry"));
const assess = ctx.step(stepName("assess_overlap"));
const verdictStep = ctx.step(stepName("render_verdict"));

const rendered = stdoutOf(verdictStep);
let assessment: Record<string, unknown> | null = null;
const assessText = stdoutOf(assess);
if (assessText !== null) {
  try { assessment = JSON.parse(assessText) as Record<string, unknown>; } catch { assessment = null; }
}

if (rendered !== null) {
  out.human(rendered);
} else {
  out.human(
    "The verdict could not be rendered, so treat this as no answer rather than a clear one. " +
      `search_registry ${statusOf(search)}; ` +
      `assess_overlap ${statusOf(assess)}; ` +
      `render_verdict ${statusOf(verdictStep)}.`,
  );
}

const verdict = typeof assessment?.verdict === "string" ? assessment.verdict : null;
const same = Array.isArray(assessment?.same_idea) ? assessment.same_idea.length : 0;
const adjacent = Array.isArray(assessment?.adjacent) ? assessment.adjacent.length : 0;
out.summary(
  verdict === null
    ? "Idea check did not complete"
    : `${verdict}: ${same} already do this, ${adjacent} adjacent`,
);

out.result({
  run_id: ctx.run.run_id,
  idea: assessment?.idea ?? null,
  verdict,
  same_idea: assessment?.same_idea ?? [],
  adjacent: assessment?.adjacent ?? [],
  candidates_examined: assessment?.candidate_count ?? null,
  queries_failed: assessment?.queries_failed ?? [],
  stages: {
    search_registry: statusOf(search),
    assess_overlap: statusOf(assess),
    render_verdict: statusOf(verdictStep),
  },
});
