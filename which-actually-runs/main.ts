#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: which-actually-runs
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/which-actually-runs
 * description: 'Answers one question on any Unix machine: when you type a command, which copy actually runs, and what did it beat. Four unrelated causes produce that same symptom and none of them announce themselves. A version manager puts a shim ahead of the system copy, which is correct until two of them fight or a shim points at a version you uninstalled. Homebrew installs to /opt/homebrew on Apple silicon and /usr/local on Intel while the system copy stays in /usr/bin, so the winner depends on a PATH order nobody set on purpose. Under WSL the Windows PATH is appended, so a command can run as a Windows program, or fail to resolve while its .exe sits on PATH. And an integration such as Docker Desktop drops symlinks that resolve only while it is running. This names the winning path for every watched command, what it beat, and which cause explains it, then reads your shell startup files to show which line put each directory on PATH, because knowing that nvm beats Homebrew does not tell you which file to edit. Read-only: it parses startup files as text without ever sourcing them, so a malformed rc file cannot execute anything, and a line assigning a secret-looking name is reported as present but never echoed.'
 * provenance:
 *   author: sai0000 <jokerbj2841@gmail.com>
 *   url: https://github.com/Joker2841/rote-playoffs
 * license: MIT
 * tags:
 * - shell
 * - path
 * - toolchain
 * - diagnostics
 * - version-manager
 * - nvm
 * - pyenv
 * - homebrew
 * - wsl
 * - macos
 * - developer-environment
 * - tool-shell
 * - domain-developer-workflow
 * - effect-read-only
 * parameters:
 * - name: commands
 *   type: string
 *   required: false
 *   default: ''
 *   description: Comma-separated extra command names to check, beyond the built-in list of thirty-odd common tools.
 * - name: path_override
 *   type: string
 *   required: false
 *   default: ''
 *   description: A PATH string to inspect instead of this shell's own. Paste the PATH from a login shell, an editor terminal or a CI runner to ask about that environment rather than this one.
 * - name: format
 *   type: string
 *   required: false
 *   default: text
 *   valid_values:
 *   - text
 *   - json
 *   description: text for the human briefing, json for a machine-readable report.
 * metadata:
 *   version: 0.1.2
 *   rote_version: 0.78.0
 *   status: released
 *   kind: atomic
 *   flow_type: parallel
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
 *     - shell
 *     - path
 *     - toolchain
 *     - diagnostics
 *     - version-manager
 *     - nvm
 *     - pyenv
 *     - homebrew
 *     - wsl
 *     - macos
 *     - developer-environment
 *     - tool-shell
 *     - domain-developer-workflow
 *     - effect-read-only
 * presentation_fixtures:
 *   resolve_commands: resources/presentation-fixtures/resolve_commands/fixture.yaml
 *   read_shell_config: resources/presentation-fixtures/read_shell_config/fixture.yaml
 *   render_report: resources/presentation-fixtures/render_report/fixture.yaml
 * steps:
 *   resolve_commands:
 *     type: process.exec
 *     timeout_ms: 180000
 *     argv:
 *     - python3
 *     - '@resource{probe_shadow.py}'
 *     - $commands
 *     - $path_override
 *   read_shell_config:
 *     type: process.exec
 *     timeout_ms: 60000
 *     argv:
 *     - python3
 *     - '@resource{read_shell_config.py}'
 *   render_report:
 *     type: process.exec
 *     timeout_ms: 60000
 *     depends_on:
 *     - resolve_commands
 *     - read_shell_config
 *     argv:
 *     - python3
 *     - '@resource{render_report.py}'
 *     - '@resolve_commands{.stdout.text}'
 *     - '@read_shell_config{.stdout.text}'
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

// A probe that did not complete is reported as such, never as an empty result.
// "checked and clean" and "never checked" must not read the same way.
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

function parse(step: ReturnType<typeof ctx.step>): Record<string, unknown> | null {
  const text = stdoutOf(step);
  if (text === null) return null;
  try { return JSON.parse(text) as Record<string, unknown>; } catch { return null; }
}

const commands = ctx.step(stepName("resolve_commands"));
const shellConfig = ctx.step(stepName("read_shell_config"));
const report = ctx.step(stepName("render_report"));

const rendered = stdoutOf(report);
const commandData = parse(commands);
const configData = parse(shellConfig);

if (rendered !== null) {
  out.human(rendered);
} else {
  out.human(
    "The report could not be rendered. Stage status: " +
      `resolve_commands ${statusOf(commands)}; ` +
      `read_shell_config ${statusOf(shellConfig)}; ` +
      `render_report ${statusOf(report)}.`,
  );
}

const findings = [
  ...((commandData?.findings as Array<Record<string, unknown>>) ?? []),
  ...((configData?.findings as Array<Record<string, unknown>>) ?? []),
];
const count = (severity: string) => findings.filter((f) => f.severity === severity).length;
const host = (commandData?.host as Record<string, unknown>) ?? {};

out.summary(
  `${count("high")} high, ${count("medium")} medium on ${host.flavour ?? "this host"}`,
);

out.result({
  run_id: ctx.run.run_id,
  host,
  path_entry_count: commandData?.path_entry_count ?? null,
  path_source: commandData?.path_source ?? null,
  version_managers_on_path: commandData?.version_managers_on_path ?? [],
  severity_counts: { high: count("high"), medium: count("medium"), low: count("low") },
  findings,
  stages: {
    resolve_commands: statusOf(commands),
    read_shell_config: statusOf(shellConfig),
    render_report: statusOf(report),
  },
});
