#!/usr/bin/env python3
"""Create an EasyHybrid exchange JSON containing only frames on an MEP.

Input MEP tables are whitespace-separated with X, Y, energy, and a window tag
such as ``0.28``. The tag selects the matching frame from an exchange JSON.
Coordinate sidecars are referenced in place; they are not copied.
"""

import argparse
import json
import math
import os
import re
import sys


WINDOW_PATTERN = re.compile(r"^(\d+)\.(\d+)$")


def window_id(value):
    """Normalize tags like 0.9 to the coordinate-frame stem 00.09."""
    match = WINDOW_PATTERN.match(str(value).strip())
    if not match:
        raise ValueError("Invalid MEP window tag {!r}; expected values like 0.28.".format(value))
    return "{:02d}.{:02d}".format(int(match.group(1)), int(match.group(2)))


def read_mep_table(path):
    points = []
    energy_unit = None
    with open(path, "r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "!")):
                continue
            fields = stripped.split()
            try:
                x, y, energy = (float(fields[i]) for i in range(3))
            except (ValueError, IndexError):
                if line_number == 1 and len(fields) >= 3:
                    unit_match = re.search(r"\(([^)]+)\)", fields[2])
                    if unit_match:
                        energy_unit = unit_match.group(1)
                    continue
                raise ValueError("Invalid MEP row {} in {}: {}".format(line_number, path, stripped))
            if len(fields) < 4:
                raise ValueError("MEP row {} has no window tag.".format(line_number))
            if not all(math.isfinite(value) for value in (x, y, energy)):
                raise ValueError("Non-finite X/Y/energy value on MEP row {}.".format(line_number))
            points.append({"x": x, "y": y, "energy": energy,
                           "window": window_id(fields[-1])})
    if not points:
        raise ValueError("No MEP points were found in {}.".format(path))
    return points, energy_unit


def extract_mep(exchange_path, mep_path, output_path):
    exchange_path = os.path.abspath(exchange_path)
    mep_path = os.path.abspath(mep_path)
    output_path = os.path.abspath(output_path)
    with open(exchange_path, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("format") != "easyhybrid-pdynamo-exchange":
        raise ValueError("Input JSON is not an EasyHybrid pDynamo exchange manifest.")

    points, energy_unit = read_mep_table(mep_path)
    frames = {}
    for frame in manifest.get("snapshots", []):
        stem = os.path.splitext(os.path.basename(frame.get("file", "")))[0]
        if WINDOW_PATTERN.match(stem):
            key = window_id(stem)
            if key in frames:
                raise ValueError("The exchange manifest has more than one frame named {}.".format(key))
            frames[key] = frame

    missing = sorted(set(point["window"] for point in points) - set(frames))
    if missing:
        raise ValueError("MEP windows are missing from the exchange trajectory: {}".format(
            ", ".join(missing)))

    exchange_dir = os.path.dirname(exchange_path)
    output_dir = os.path.dirname(output_path)
    selected_frames = []
    for point in points:
        source_frame = frames[point["window"]]
        coordinate_file = source_frame.get("coordinate_file")
        if not coordinate_file:
            raise ValueError("Exchange frame {} has no coordinate sidecar.".format(point["window"]))
        source_coordinates = os.path.realpath(os.path.join(exchange_dir, coordinate_file))
        if os.path.commonpath([os.path.realpath(exchange_dir), source_coordinates]) != os.path.realpath(exchange_dir):
            raise ValueError("Frame sidecar escapes the exchange folder: {}".format(coordinate_file))
        if not os.path.isfile(source_coordinates):
            raise ValueError("Missing coordinates for MEP window {}: {}".format(
                point["window"], source_coordinates))
        output_frame = dict(source_frame)
        output_frame["coordinate_file"] = os.path.relpath(source_coordinates, output_dir)
        selected_frames.append(output_frame)

    result = dict(manifest)
    result["snapshots"] = selected_frames
    result["mep_path"] = {
        "source_file": os.path.basename(mep_path),
        "energy_unit": energy_unit,
        "points": [dict(index=index, **point,
                         frame=frames[point["window"]].get("file"))
                   for index, point in enumerate(points)],
    }
    result["source_manifest"] = os.path.basename(exchange_path)

    os.makedirs(output_dir, exist_ok=True)
    temporary_path = output_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary_path, output_path)
    print("Wrote {} MEP points to {}".format(len(points), output_path))


def main():
    parser = argparse.ArgumentParser(
        description="Extract tagged MEP frames from an exchange manifest into an importable MEP JSON.")
    parser.add_argument("exchange_json", help="full EasyHybrid exchange manifest")
    parser.add_argument("mep_table", help="MEP table with X Y energy window columns")
    parser.add_argument("output_json", help="output MEP exchange manifest")
    args = parser.parse_args()
    try:
        extract_mep(args.exchange_json, args.mep_table, args.output_json)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("MEP export failed: {}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
