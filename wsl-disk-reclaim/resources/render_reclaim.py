#!/usr/bin/env python3
"""Join the probes into a reclaim briefing that ends in commands.

Order matters here. Freeing space inside the distro does nothing to the file
Windows sees until the image is compacted, and compacting before freeing
reclaims almost nothing. Reporting the two halves without that ordering is how
people conclude the whole exercise does not work.
"""
import json
import sys
import textwrap
import time

BAR = "#"
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def load(source):
    text = (source or "").strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError as error:
            return {"_unavailable": "unparsable probe output: %s" % error}
    try:
        with open(source, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        return {"_unavailable": str(error)}


def gb(value):
    if not value:
        return "     -"
    return "%6.2f GB" % (value / 1024 ** 3)


def argument(index, default):
    if len(sys.argv) <= index:
        return default
    raw = sys.argv[index].strip()
    return default if not raw or raw.startswith("$") else raw


def main():
    if len(sys.argv) < 4:
        print("usage: render_reclaim.py <platform> <images> <consumers> [format]",
              file=sys.stderr)
        return 2

    platform = load(sys.argv[1])
    images = load(sys.argv[2])
    consumers = load(sys.argv[3])
    output_format = argument(4, "text").lower()
    if output_format not in ("text", "json"):
        print("format must be text or json", file=sys.stderr)
        return 2

    probes = [("platform", platform), ("images", images), ("consumers", consumers)]
    ok = [name for name, data in probes if "_unavailable" not in data]
    findings = list(images.get("findings", [])) + list(consumers.get("findings", []))
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 9), -(f.get("bytes") or 0)))

    distro = platform.get("wsl_distro_name", "your-distro")
    sparse = (images.get("wsl_sparse") or {}).get("available")

    if output_format == "json":
        print(json.dumps({
            "schema": "wsl-disk-reclaim/v1",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "applicable": platform.get("applicable", False),
            "distro": distro,
            "windows_total_bytes": images.get("windows_total_bytes"),
            "distro_bytes": images.get("distro_bytes"),
            "docker_bytes": images.get("docker_bytes"),
            "inside_used_bytes": (images.get("inside") or {}).get("used_bytes"),
            "distro_reclaimable_bytes": images.get("distro_reclaimable_bytes"),
            "inside_reclaimable_bytes": consumers.get("measured_total_bytes"),
            "incomplete_measurements": consumers.get("incomplete", []),
            "findings": findings,
            "probes_ok": ok,
        }, indent=2, sort_keys=True))
        return 0

    lines = []
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    lines.append("WSL DISK RECLAIM" + " " * 37 + stamp + " UTC")
    lines.append("")
    lines.append("  probes    " + BAR * (8 * len(ok)) + " " * (8 * (3 - len(ok)))
                 + "  %d/3 ok" % len(ok))
    lines.append("")

    if not platform.get("applicable", False):
        lines.append("VERDICT  Not applicable. This is not WSL, so there is no image to reclaim.")
        print("\n".join(lines))
        return 0

    total = images.get("windows_total_bytes") or 0
    lines.append("VERDICT  WSL is holding %s of your Windows disk." % gb(total).strip())
    inside_free = consumers.get("measured_total_bytes") or 0
    distro_gap = images.get("distro_reclaimable_bytes") or 0
    lines.append("  %s already freed inside and not returned to Windows"
                 % gb(distro_gap).strip())
    lines.append("  %s sitting in caches that can be cleared" % gb(inside_free).strip())
    lines.append("")

    lines.append("ON THE WINDOWS SIDE")
    for image in images.get("images", []):
        if image.get("kind") == "swap":
            continue
        lines.append("  %s  %-8s %s" % (gb(image.get("bytes")), image.get("kind", "?"),
                                        image.get("path", "")))
    inside = images.get("inside") or {}
    lines.append("  %s  %-8s reported in use by the distro itself"
                 % (gb(inside.get("used_bytes")), "inside"))
    lines.append("")

    lines.append("INSIDE THE DISTRO")
    measured = [c for c in consumers.get("consumers", []) if c.get("state") == "measured"]
    measured.sort(key=lambda c: -(c.get("bytes") or 0))
    if not measured:
        lines.append("  nothing measurable was found")
    for consumer in measured:
        if not consumer.get("bytes"):
            continue
        nested = ("  (counted inside %s)" % consumer["contained_by"]) if consumer.get("contained_by") else ""
        lines.append("  %s  %s%s" % (gb(consumer["bytes"]), consumer["label"], nested))
    for label in consumers.get("incomplete", []):
        lines.append("  %s  %s" % ("   n/a", label + " (not measured)"))
    lines.append("")

    lines.append("HOW TO RECLAIM, IN THIS ORDER")
    lines.append("  Freeing space inside does not shrink the Windows file. Compacting")
    lines.append("  before freeing reclaims almost nothing. Do both, in this order.")
    lines.append("")
    lines.append("  1. free it inside the distro")
    seen = set()
    for finding in findings:
        remedy = finding.get("remedy")
        if not remedy or remedy in seen:
            continue
        seen.add(remedy)
        marker = "     " if finding.get("routine") else "     ~ "
        lines.append("%s%s" % (marker, remedy))
    if not seen:
        lines.append("     nothing above the reporting threshold")
    lines.append("     (lines marked ~ are judgement calls, not routine cleanup)")
    lines.append("")
    lines.append("  2. then hand the freed space back to Windows")
    if sparse == "yes":
        lines.append("     wsl --manage %s --set-sparse true      (from Windows)" % distro)
    else:
        lines.append("     wsl --shutdown                          (from Windows)")
        lines.append("     then compact the .vhdx with diskpart or Optimize-VHD")
    if (images.get("docker_bytes") or 0) > 0:
        lines.append("")
        lines.append("  3. docker keeps its own disk, handled separately")
        lines.append("     docker system df          see what is actually live")
        lines.append("     docker system prune       free it inside docker's disk")
    lines.append("")

    lines.append("SCOPE")
    lines.append("  Read-only. Nothing here is deleted or compacted; every action above")
    lines.append("  is for you to run. Sizes are what the filesystem reports now, and a")
    lines.append("  measurement that did not finish is listed as not measured rather")
    lines.append("  than counted as zero.")
    lines.append("")

    lines.append("STAGES")
    for name, data in probes:
        lines.append("  %s  %-10s %s" % (BAR * 8, name,
                                         "ok" if "_unavailable" not in data else "unavailable"))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
