#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: play-quality-doctor
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/play-quality-doctor
 * description: 'Runs rote''s own quality scorer across every Play you have, totals what each unsatisfied signal is costing you, and tells you what to type to clear it. rote play score is authoritative for one Play at a time; what it does not do is run over a whole shelf or rank the signals by total damage. This does that, and it computes nothing itself: run rote play score on any single Play and the numbers will match, because they are the same numbers. One signal is genuinely invisible without it. rote play validate reports only signals it rates as warnings, and frontmatter_completeness is rated info, so a Play can be marked down 0.125 for it while validate prints Pass and never mentions it. That was true of 5 of the 18 Plays installed when this was written. Two findings are also worth stating because their wording does not lead you to the fix: when frontmatter_completeness reports missing optional tags, the shape it wants is a top-level tags list, and tags under metadata.discoverability.tags do not count, which is exactly the shape rote workspace export generates. And provenance_url reads a top-level source field rather than provenance.url. Read-only, no network, no credentials.'
 * provenance:
 *   author: sai0000 <jokerbj2841@gmail.com>
 *   url: https://github.com/Joker2841/rote-playoffs
 * license: MIT
 * tags:
 * - domain-rote-plays
 * - audience-play-authors
 * - job-quality-audit
 * - quality-score
 * - rubric
 * - frontmatter
 * - tool-shell
 * - effect-read-only
 * - audience-developers
 * - domain-engineering
 * - developer-tools
 * - python
 * - no-credentials
 * - no-api-key
 * - offline
 * - local-only
 * parameters:
 * - name: play
 *   type: string
 *   required: false
 *   default: all
 *   description: 'What to audit: all for every locally installed package, an owner/name reference such as modiqo/hello, or a path to a play package directory.'
 * - name: flows_root
 *   type: string
 *   required: false
 *   default: ~/.rote/flows
 *   description: Directory holding installed packages. Point it at another rote store to audit that one instead.
 * - name: format
 *   type: string
 *   required: false
 *   default: text
 *   valid_values:
 *   - text
 *   - json
 *   description: text for the human report, json for a machine-readable one suitable for a release gate.
 * - name: min_score
 *   type: string
 *   required: false
 *   default: '1.0'
 *   description: Only list plays below this score. Totals still cover every audited play, so filtering never hides how many were checked.
 * metadata:
 *   version: 0.3.4
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
 *     - job-quality-audit
 *     - quality-score
 *     - rubric
 *     - frontmatter
 *     - tool-shell
 *     - effect-read-only
 *     - audience-developers
 *     - domain-engineering
 *     - developer-tools
 *     - python
 *     - no-credentials
 *     - no-api-key
 *     - offline
 *     - local-only
 * presentation_fixtures:
 *   locate_plays: resources/presentation-fixtures/locate_plays/fixture.yaml
 *   score_plays: resources/presentation-fixtures/score_plays/fixture.yaml
 *   render_report: resources/presentation-fixtures/render_report/fixture.yaml
 * steps:
 *   locate_plays:
 *     type: process.exec
 *     timeout_ms: 60000
 *     argv:
 *     - python3
 *     - '@resource{locate_plays.py}'
 *     - $play
 *     - $flows_root
 *   score_plays:
 *     type: process.exec
 *     timeout_ms: 900000
 *     depends_on:
 *     - locate_plays
 *     argv:
 *     - python3
 *     - '@resource{score_plays.py}'
 *     - '@locate_plays{.stdout.text}'
 *   render_report:
 *     type: process.exec
 *     timeout_ms: 60000
 *     depends_on:
 *     - score_plays
 *     argv:
 *     - python3
 *     - '@resource{render_report.py}'
 *     - '@score_plays{.stdout.text}'
 *     - $format
 *     - $min_score
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

// A stage that did not complete is reported as such rather than as an empty
// result. "audited and clean" and "never audited" must not read the same way
// in a tool whose whole purpose is telling you what went unreported.
function stdoutOf(step: ReturnType<typeof ctx.step>): string | null {
  if (step.outcome.status !== "completed" && step.outcome.status !== "restored") {
    return null;
  }
  const body = step.outcome.output.body as { stdout?: { text?: string } } | undefined;
  return body?.stdout?.text ?? null;
}

function statusOf(step: ReturnType<typeof ctx.step>): string {
  switch (step.outcome.status) {
    case "completed":
    case "restored":
      return "ok";
    case "skipped":
      return `skipped: ${step.outcome.output.reason}`;
    case "failed":
      return `failed: ${step.outcome.output.message}`;
    case "blocked":
      return `blocked: ${step.outcome.output.reason}`;
    default:
      return "unknown";
  }
}

const locate = ctx.step(stepName("locate_plays"));
const auditStep = ctx.step(stepName("score_plays"));
const report = ctx.step(stepName("render_report"));

const rendered = stdoutOf(report);
let audit: Record<string, unknown> | null = null;
const auditText = stdoutOf(auditStep);
if (auditText !== null) {
  try {
    audit = JSON.parse(auditText) as Record<string, unknown>;
  } catch {
    audit = null;
  }
}

if (rendered !== null) {
  out.human(rendered);
} else {
  out.human(
    "The quality report could not be rendered. Stage status: " +
      `locate_plays ${statusOf(locate)}; ` +
      `score_plays ${statusOf(auditStep)}; ` +
      `render_report ${statusOf(report)}.`,
  );
}

const capped = typeof audit?.capped === "number" ? audit.capped : null;
const total = typeof audit?.total === "number" ? audit.total : null;
out.summary(
  capped === null || total === null
    ? "Quality audit did not complete"
    : `${capped} of ${total} play(s) capped below 1.00`,
);

out.result({
  run_id: ctx.run.run_id,
  audited: total,
  capped,
  at_full_score: audit?.at_full ?? null,
  signal_cost: audit?.signal_cost ?? {},
  unresolved: audit?.unresolved ?? [],
  stages: {
    locate_plays: statusOf(locate),
    score_plays: statusOf(auditStep),
    render_report: statusOf(report),
  },
});
