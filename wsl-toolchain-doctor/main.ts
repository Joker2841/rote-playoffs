#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: wsl-toolchain-doctor
 * version: 0.2.0
 * description: 'Answers one question on a WSL machine: which of the commands you type are not the program you think they are. Windows directories are appended to the Linux PATH by default and interop makes Windows executables reachable, so three unrelated failures look identical in a terminal and only one of them is shadowing. A command can resolve to an extensionless Windows shim and run as a Windows program with Windows path semantics, which is why docker with a bind mount hands a Windows client a Linux path it cannot see. A command can fail to resolve at all while its .exe sits on PATH, so the shell reports command not found about a tool that is plainly installed. Or it can be a symlink into /mnt/wsl left by a Docker Desktop style integration, which fills that path only while it is running: the directory listing shows the tool, running it finds nothing, and a Windows copy further down PATH silently takes over. Separating those three is the point, because the fix for each is different. It names the exact winning path and what it beat, then reports the configuration that caused it: appendWindowsPath, drive mounts without the metadata option so chmod appears to succeed and does nothing, case-insensitive mounts that collapse two tracked files into one, and whether your home and project sit on the slow 9p filesystem. It reports the PATH of the shell that invoked it and says so, because a diagnostic that hides its own scope is worth less than none. Read-only by construction: it parses configuration and stat data, tests case sensitivity by reading two spellings of a directory that already exists rather than writing probe files, repairs nothing, carries no credentials, and needs only python3. On a host that is not WSL it returns a single applicability verdict instead of inventing findings.'
 * provenance:
 *   author: sai0000 <jokerbj2841@gmail.com>
 *   url: https://github.com/Joker2841/rote-playoffs/tree/main/wsl-toolchain-doctor
 * license: MIT
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/wsl-toolchain-doctor
 * parameters:
 * - name: commands
 *   type: string
 *   required: false
 *   default: ''
 *   description: Optional comma-separated extra command names to check, for example poetry,rbenv,deno. The built-in watchlist already covers the common toolchain.
 * - name: path_override
 *   type: string
 *   required: false
 *   default: ''
 *   description: A PATH string to inspect instead of this shell's own. Paste the PATH from a login shell, an editor terminal, or a CI runner to ask the question about that environment rather than this one.
 * - name: format
 *   type: string
 *   required: false
 *   default: text
 *   valid_values:
 *   - text
 *   - json
 *   description: text for the human briefing, json for a machine-readable report suitable for piping into other tooling.
 * - name: min_severity
 *   type: string
 *   required: false
 *   default: info
 *   valid_values:
 *   - high
 *   - medium
 *   - low
 *   - info
 *   description: Lowest severity to report. Counts always cover every severity, so filtering never makes an unchecked machine look clean.
 * tags:
 * - wsl
 * - wsl2
 * - domain-cross-platform
 * - tool-shell
 * - effect-read-only
 * - path
 * - toolchain
 * - diagnostics
 * - windows-interop
 * metadata:
 *   rote_version: 0.78.0
 *   version: 0.2.2
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
 *     - wsl
 *     - wsl2
 *     - domain-cross-platform
 *     - tool-shell
 *     - effect-read-only
 *     - path
 *     - toolchain
 *     - diagnostics
 *     - windows-interop
 * presentation_fixtures:
 *   detect_platform: resources/presentation-fixtures/detect_platform/fixture.yaml
 *   resolve_commands: resources/presentation-fixtures/resolve_commands/fixture.yaml
 *   read_configuration: resources/presentation-fixtures/read_configuration/fixture.yaml
 *   render_briefing: resources/presentation-fixtures/render_briefing/fixture.yaml
 * steps:
 *   detect_platform:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_platform.py}'
 *   resolve_commands:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_shadow.py}'
 *     - $commands
 *     - $path_override
 *     timeout_ms: 120000
 *   read_configuration:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_traps.py}'
 *   render_briefing:
 *     type: process.exec
 *     depends_on:
 *     - detect_platform
 *     - resolve_commands
 *     - read_configuration
 *     argv:
 *     - python3
 *     - '@resource{render.py}'
 *     - '@detect_platform{.stdout.text}'
 *     - '@resolve_commands{.stdout.text}'
 *     - '@read_configuration{.stdout.text}'
 *     - $format
 *     - $min_severity
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

// Each probe writes one JSON document to stdout. A step that did not complete
// is reported as such rather than being silently treated as empty, because the
// whole point of this play is to distinguish "checked and clean" from
// "never looked", and a missing probe is the second one.
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

const platform = ctx.step(stepName("detect_platform"));
const commands = ctx.step(stepName("resolve_commands"));
const configuration = ctx.step(stepName("read_configuration"));
const briefing = ctx.step(stepName("render_briefing"));

const rendered = stdoutOf(briefing);

function parse(step: ReturnType<typeof ctx.step>): Record<string, unknown> | null {
  const text = stdoutOf(step);
  if (text === null) return null;
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

const platformData = parse(platform);
const commandData = parse(commands);
const configurationData = parse(configuration);

const findings = [
  ...((commandData?.findings as Array<Record<string, unknown>>) ?? []),
  ...((configurationData?.findings as Array<Record<string, unknown>>) ?? []),
];
const counted = (severity: string) =>
  findings.filter((finding) => finding.severity === severity).length;

if (rendered !== null) {
  out.human(rendered);
} else {
  out.human(
    "The briefing could not be rendered. Stage status: " +
      `detect_platform ${statusOf(platform)}; ` +
      `resolve_commands ${statusOf(commands)}; ` +
      `read_configuration ${statusOf(configuration)}; ` +
      `render_briefing ${statusOf(briefing)}.`,
  );
}

const applicable = platformData?.applicable === true;
out.summary(
  applicable
    ? `${counted("high")} high, ${counted("medium")} medium on ${platformData?.flavour ?? "wsl"}`
    : "Not WSL: no findings apply",
);

out.result({
  run_id: ctx.run.run_id,
  applicable,
  flavour: platformData?.flavour ?? null,
  severity_counts: {
    high: counted("high"),
    medium: counted("medium"),
    low: counted("low"),
    info: counted("info"),
  },
  findings,
  stages: {
    detect_platform: statusOf(platform),
    resolve_commands: statusOf(commands),
    read_configuration: statusOf(configuration),
    render_briefing: statusOf(briefing),
  },
});
