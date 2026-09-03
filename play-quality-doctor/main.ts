#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: play-quality-doctor
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/play-quality-doctor
 * description: 'Answers one question about a published Play: why is its quality score capped, when nothing is telling you. rote play validate prints a score, reports zero errors and zero warnings, says Pass, and stops. If the score is 0.65 it will not say which signal is unsatisfied, what it wanted instead, or what the missing field is worth. Six of the ten Plays this was first run against were capped, and every one of them validated clean. The rubric is not published, so this reconstructs it: the rules here were derived by mutating a Play that scored 1.00, removing one field at a time and reading the score back from validate, then refined against five published Plays: two were predicted correctly first time and three were mispredicted and revealed further signals, so the genuinely held-out evidence is two Plays, not five. One interaction is measured rather than assumed: with metadata.version absent, discoverability is not scored, so those weights do not simply add. One residual is unexplained, and the report says so. Two of the findings are counterintuitive enough to be worth stating up front. Tags declared under metadata.discoverability.tags do not satisfy the discoverability signal, and that is exactly the shape the workspace exporter generates, so a Play can carry nine tags and still lose the points. And the signal named provenance_url reads a top-level source field, not provenance.url, which is the field its name points at. This reports every unsatisfied signal with its weight, the exact edit that clears it, and a predicted score, for one Play or every Play installed locally. It is a model of the scorer rather than the scorer, and it says so: rote play validate stays authoritative, and where the two disagree the model is what is wrong. Read-only by construction. It reads frontmatter and nothing else, modifies no Play, needs no credentials and no network, and uses pyyaml only when it is already importable, falling back to a structural scan so that running it never requires installing anything.'
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
 *   description: Only list plays predicted below this score. Totals still cover every audited play, so filtering never hides how many were checked.
 * metadata:
 *   version: 0.2.0
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
 * presentation_fixtures:
 *   locate_plays: resources/presentation-fixtures/locate_plays/fixture.yaml
 *   audit_rubric: resources/presentation-fixtures/audit_rubric/fixture.yaml
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
 *   audit_rubric:
 *     type: process.exec
 *     timeout_ms: 120000
 *     depends_on:
 *     - locate_plays
 *     argv:
 *     - python3
 *     - '@resource{audit_rubric.py}'
 *     - '@locate_plays{.stdout.text}'
 *   render_report:
 *     type: process.exec
 *     timeout_ms: 60000
 *     depends_on:
 *     - audit_rubric
 *     argv:
 *     - python3
 *     - '@resource{render_report.py}'
 *     - '@audit_rubric{.stdout.text}'
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
const auditStep = ctx.step(stepName("audit_rubric"));
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
      `audit_rubric ${statusOf(auditStep)}; ` +
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
  signal_counts: audit?.signal_counts ?? {},
  parser: audit?.parser ?? null,
  unresolved: audit?.unresolved ?? [],
  stages: {
    locate_plays: statusOf(locate),
    audit_rubric: statusOf(auditStep),
    render_report: statusOf(report),
  },
});
