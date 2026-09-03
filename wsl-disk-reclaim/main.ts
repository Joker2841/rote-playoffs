#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: wsl-disk-reclaim
 * version: 0.1.0
 * description: 'Answers one question on a WSL machine: why is the Windows drive full when the distro says it is not. A WSL2 distro lives in a virtual disk that grows on demand and never shrinks on its own. Delete forty gigabytes inside the distro and the file Windows sees stays exactly as large as it ever got, because handing the space back requires an explicit compaction that nothing prompts you to run. df, run inside, reports only the inside view, so the missing space is invisible from the one place people look for it. This reports both numbers and the gap between them, per image rather than in aggregate, and that distinction is the point: the distro image can be compared against what the filesystem says it is using, while Docker Desktop keeps a separate disk whose interior is not visible from inside the distro, so folding it into one total would invent tens of gigabytes of reclaimable space that are not free. It then measures the caches inside that are worth clearing, marks the ones that nest so a parent and its child are never counted twice, and lists a measurement that did not finish as not measured rather than as zero. The output ends in commands, in the order that actually works: freeing space inside does nothing to the Windows file until the image is compacted, and compacting before freeing reclaims almost nothing, which is why people try one, see no change, and conclude the whole exercise is a myth. Read-only by construction: it stats files and runs du, deletes nothing, compacts nothing, carries no credentials, and needs only python3 and coreutils. Every suggested command is printed for a person to run, never executed. On a host that is not WSL it returns a single applicability verdict instead of inventing findings.'
 * provenance:
 *   author: sai0000 <jokerbj2841@gmail.com>
 *   url: https://github.com/Joker2841/rote-playoffs/tree/main/wsl-disk-reclaim
 * license: MIT
 * source: https://github.com/Joker2841/rote-playoffs/tree/main/wsl-disk-reclaim
 * parameters:
 * - name: format
 *   type: string
 *   required: false
 *   default: text
 *   valid_values:
 *   - text
 *   - json
 *   description: text for the human briefing, json for a machine-readable report suitable for piping into other tooling.
 * - name: threshold_mb
 *   type: string
 *   required: false
 *   default: '512'
 *   description: Smallest directory worth reporting, in megabytes. Everything is still measured; this only controls what is listed.
 * - name: extra_paths
 *   type: string
 *   required: false
 *   default: ''
 *   description: Comma-separated extra directories to measure, for example a node_modules tree or a dataset directory. No fixed list can know where those live on your machine.
 * tags:
 * - wsl
 * - wsl2
 * - domain-cross-platform
 * - tool-shell
 * - effect-read-only
 * - disk
 * - storage
 * - vhdx
 * - reclaim
 * metadata:
 *   rote_version: 0.78.0
 *   version: 0.1.1
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
 *     - disk
 *     - storage
 *     - vhdx
 *     - reclaim
 * presentation_fixtures:
 *   detect_platform: resources/presentation-fixtures/detect_platform/fixture.yaml
 *   measure_images: resources/presentation-fixtures/measure_images/fixture.yaml
 *   find_consumers: resources/presentation-fixtures/find_consumers/fixture.yaml
 *   render_reclaim: resources/presentation-fixtures/render_reclaim/fixture.yaml
 * steps:
 *   detect_platform:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_platform.py}'
 *   measure_images:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_images.py}'
 *     timeout_ms: 180000
 *   find_consumers:
 *     type: process.exec
 *     argv:
 *     - python3
 *     - '@resource{probe_consumers.py}'
 *     - $threshold_mb
 *     - $extra_paths
 *     timeout_ms: 300000
 *   render_reclaim:
 *     type: process.exec
 *     depends_on:
 *     - detect_platform
 *     - measure_images
 *     - find_consumers
 *     argv:
 *     - python3
 *     - '@resource{render_reclaim.py}'
 *     - '@detect_platform{.stdout.text}'
 *     - '@measure_images{.stdout.text}'
 *     - '@find_consumers{.stdout.text}'
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

// A stage that did not complete is reported as such rather than treated as
// empty. "measured and clean" and "never measured" must not read the same way
// when the whole point is telling someone how much space they can get back.
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

function parse(step: ReturnType<typeof ctx.step>): Record<string, unknown> | null {
  const text = stdoutOf(step);
  if (text === null) return null;
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

const platform = ctx.step(stepName("detect_platform"));
const imagesStep = ctx.step(stepName("measure_images"));
const consumersStep = ctx.step(stepName("find_consumers"));
const briefing = ctx.step(stepName("render_reclaim"));

const rendered = stdoutOf(briefing);
const platformData = parse(platform);
const imagesData = parse(imagesStep);
const consumersData = parse(consumersStep);

if (rendered !== null) {
  out.human(rendered);
} else {
  out.human(
    "The reclaim briefing could not be rendered. Stage status: " +
      `detect_platform ${statusOf(platform)}; ` +
      `measure_images ${statusOf(imagesStep)}; ` +
      `find_consumers ${statusOf(consumersStep)}; ` +
      `render_reclaim ${statusOf(briefing)}.`,
  );
}

const gib = (value: unknown) =>
  typeof value === "number" ? Math.round((value / 1024 ** 3) * 100) / 100 : null;

const applicable = platformData?.applicable === true;
out.summary(
  applicable
    ? `${gib(imagesData?.windows_total_bytes) ?? "?"} GB held on Windows, ` +
      `${gib(imagesData?.distro_reclaimable_bytes) ?? 0} GB not returned, ` +
      `${gib(consumersData?.measured_total_bytes) ?? 0} GB in clearable caches`
    : "Not WSL: no virtual disk to reclaim",
);

out.result({
  run_id: ctx.run.run_id,
  applicable,
  distro: platformData?.wsl_distro_name ?? null,
  windows_total_gib: gib(imagesData?.windows_total_bytes),
  distro_gib: gib(imagesData?.distro_bytes),
  docker_gib: gib(imagesData?.docker_bytes),
  distro_reclaimable_gib: gib(imagesData?.distro_reclaimable_bytes),
  inside_clearable_gib: gib(consumersData?.measured_total_bytes),
  incomplete_measurements: consumersData?.incomplete ?? [],
  stages: {
    detect_platform: statusOf(platform),
    measure_images: statusOf(imagesStep),
    find_consumers: statusOf(consumersStep),
    render_reclaim: statusOf(briefing),
  },
});
