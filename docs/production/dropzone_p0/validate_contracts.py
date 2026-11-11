#!/usr/bin/env python3
"""Static validation for the Dropzone P0 production contracts.

This validates data and cross-file references only. It does not create assets and
cannot prove mesh clearance, vertex weights, rendered appearance, PICO frame time,
or XR comfort. Those require the geometry/runtime gates in 制作规格.md.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
FILES = {
    "scene": ROOT / "scene_components.json",
    "rig": ROOT / "rig_contract.json",
    "anim": ROOT / "animation_tracks.json",
    "mission": ROOT / "mission_graph.json",
}


class Validator:
    def __init__(self) -> None:
        self.checks = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    def warn(self, condition: bool, message: str) -> None:
        if not condition:
            self.warnings.append(message)

    def unique(self, values: Iterable[str], label: str) -> None:
        vals = list(values)
        self.check(len(vals) == len(set(vals)), f"{label}: duplicate IDs: {sorted({v for v in vals if vals.count(v) > 1})}")


def walk_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def close(a: float, b: float, eps: float = 1e-6) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=eps)


def main() -> int:
    v = Validator()
    docs: dict[str, Any] = {}
    for key, path in FILES.items():
        try:
            docs[key] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            v.check(False, f"{path.name}: JSON parse failed: {exc}")
    if len(docs) != len(FILES):
        return finish(v)

    scene, rig_doc, anim, mission = (docs[k] for k in ("scene", "rig", "anim", "mission"))
    v.check(scene.get("export_freeze", {}).get("may_export_now") is False, "scene: export freeze must remain in force")
    v.check(scene.get("units") == "meter", "scene: units must be meter")
    v.check(scene.get("coordinate_space", {}).get("left") == "+X", "scene: left side must be +X")
    v.check(scene.get("coordinate_space", {}).get("front") == "+Z", "scene: front must be +Z")

    assets = scene["assets"]
    asset_by_id = {a["asset_id"]: a for a in assets}
    v.unique((a["asset_id"] for a in assets), "assets")
    components = [c | {"asset_id": a["asset_id"]} for a in assets for c in a.get("components", [])]
    component_by_id = {c["component_id"]: c for c in components}
    v.unique((c["component_id"] for c in components), "components")
    material_ids = set(scene["materials"])
    for asset in assets:
        v.check(set(asset.get("materials_used", [])) <= material_ids, f"{asset['asset_id']}: unknown material in materials_used")
        v.check(len(asset.get("materials_used", [])) <= asset["material_budget"], f"{asset['asset_id']}: material budget exceeded")
    for c in components:
        bbox = c["bbox_m"]
        calculated = [bbox["max"][i] - bbox["min"][i] for i in range(3)]
        v.check(all(close(calculated[i], c["dimensions_m"][i]) for i in range(3)), f"{c['component_id']}: dimensions do not match bbox")
        v.check(set(c["materials"]) <= material_ids, f"{c['component_id']}: unknown material")
        v.check(set(c["materials"]) <= set(asset_by_id[c["asset_id"]]["materials_used"]), f"{c['component_id']}: material outside asset whitelist")
        v.check("collision" in c and "lod" in c, f"{c['component_id']}: collision and LOD are required")

    mecha_asset = asset_by_id["mecha_793"]
    mecha_components = [c for c in components if c["asset_id"] == "mecha_793"]
    mecha = rig_doc["rigs"]["mecha_793"]
    bones = mecha["bones"]
    bone_by_name = {b["name"]: b for b in bones}
    v.unique((b["name"] for b in bones), "mecha bones")
    required = mecha["required_exact_bone_names"]
    v.check(len(bones) == 18 == mecha["bone_count"], "mecha: exactly 18 bones required")
    v.check(set(bone_by_name) == set(required), "mecha: bone names differ from required_exact_bone_names")
    for b in bones:
        parent = b["parent"]
        v.check(parent == "mecha_root" or parent in bone_by_name, f"bone {b['name']}: invalid parent {parent}")
        if parent in bone_by_name:
            parent_head = bone_by_name[parent]["head_world_m"]
        else:
            parent_head = [0.0, 0.0, 0.0]
        expected_local = [b["head_world_m"][i] - parent_head[i] for i in range(3)]
        v.check(all(close(expected_local[i], b["head_parent_local_m"][i]) for i in range(3)), f"bone {b['name']}: parent-local head inconsistent")
        limits = b.get("rotation_limits_xyz_deg", {})
        for axis in "xyz":
            if axis in limits:
                v.check(limits[axis][0] <= limits[axis][1], f"bone {b['name']}: invalid {axis} limits")

    bindings = mecha["mesh_bindings"]
    bound_components = [c for group in bindings for c in group["components"]]
    v.unique(bound_components, "mesh binding components")
    v.check(set(bound_components) == {c["component_id"] for c in mecha_components}, "mecha: mesh_bindings must cover every mecha component exactly once")
    binding_for = {c: group["bone"] for group in bindings for c in group["components"]}
    for c in mecha_components:
        v.check(c["bind_bone"] in bone_by_name, f"{c['component_id']}: unknown bind bone")
        v.check(binding_for.get(c["component_id"]) == c["bind_bone"], f"{c['component_id']}: scene/rig bind bone mismatch")
    bbox = mecha_asset["world_bbox_target_m"]
    v.check(close(bbox["max"][1] - bbox["min"][1], 7.93), "mecha: target height must be 7.93 m")
    v.check(close(bbox["min"][1], 0.0), "mecha: target foot minimum must be y=0")
    width = bbox["max"][0] - bbox["min"][0]
    height = bbox["max"][1] - bbox["min"][1]
    depth = bbox["max"][2] - bbox["min"][2]
    v.check(abs(width / height - 0.561) <= 0.005, "mecha: width/height outside 0.561 ± 0.005")
    v.check(abs(depth / width - 0.625) <= 0.005, "mecha: depth/width outside 0.625 ± 0.005")

    auxiliary_nodes: dict[str, dict[str, Any]] = {}
    for rig_name in ("cockpit_controls", "drop_container"):
        nodes = rig_doc["rigs"][rig_name]["nodes"]
        v.unique((n["name"] for n in nodes), f"{rig_name} nodes")
        for node in nodes:
            auxiliary_nodes[node["name"]] = node
        names = {n["name"] for n in nodes}
        for node in nodes:
            parent = node.get("parent")
            v.check(parent is None or parent in names or parent == "ChestSocket", f"{rig_name}/{node['name']}: invalid parent {parent}")
    for c in components:
        if c["asset_id"] in ("cockpit_human_scale", "drop_container"):
            v.check(c["node_id"] in auxiliary_nodes, f"{c['component_id']}: unknown rigid node {c['node_id']}")

    instances = scene["scene_instances"]
    instance_by_id = {i["instance_id"]: i for i in instances}
    v.unique((i["instance_id"] for i in instances), "scene instances")
    for inst in instances:
        v.check(inst["asset_id"] in asset_by_id, f"instance {inst['instance_id']}: unknown asset")
        v.check(all(close(x, 1.0) for x in inst["scale"]), f"instance {inst['instance_id']}: runtime rescale is forbidden")
        if "component_id" in inst:
            v.check(inst["component_id"] in component_by_id, f"instance {inst['instance_id']}: unknown component")
        if "initial_clip" in inst:
            v.check(inst["initial_clip"] in {c["clip_id"] for c in anim["clips"]}, f"instance {inst['instance_id']}: unknown initial clip")
    route = scene["route"]
    route_nodes = {n["id"] for n in route["nodes"]}
    v.check(len(route_nodes) == len(route["nodes"]), "route: duplicate node IDs")
    v.check(route["goal_node"] in route_nodes, "route: invalid goal node")
    for edge in route["edges"]:
        v.check(edge["from"] in route_nodes and edge["to"] in route_nodes, "route: edge references unknown node")
        v.check(edge["clear_width_m"] >= 3.6, "route: clear width below 3.6 m")
    v.check("HARD_ROUTE_STRIP" in instance_by_id, "route: physical hard-route mesh instance is missing")
    soil_inst = instance_by_id["SOFT_SOIL"]
    soil_bbox = component_by_id[soil_inst["component_id"]]["bbox_m"]
    soil_min_x = soil_bbox["min"][0] + soil_inst["position_m"][0]
    soil_max_x = soil_bbox["max"][0] + soil_inst["position_m"][0]
    soil_min_z = soil_bbox["min"][2] + soil_inst["position_m"][2]
    soil_max_z = soil_bbox["max"][2] + soil_inst["position_m"][2]
    positions = {n["id"]: n["position_m"] for n in route["nodes"]}
    for edge in route["edges"]:
        a, b = positions[edge["from"]], positions[edge["to"]]
        for step in range(101):
            t = step / 100.0
            x, z = a[0] + (b[0] - a[0]) * t, a[2] + (b[2] - a[2]) * t
            inside = soil_min_x <= x <= soil_max_x and soil_min_z <= z <= soil_max_z
            v.check(not inside, f"route: {edge['from']}->{edge['to']} centerline crosses SOFT_SOIL at t={t:.2f}")

    clips = anim["clips"]
    clip_by_id = {c["clip_id"]: c for c in clips}
    v.unique((c["clip_id"] for c in clips), "animation clips")
    valid_targets = set(bone_by_name) | set(auxiliary_nodes) | set(instance_by_id) | {"mecha_root"}
    socket_names = {s["name"] for s in mecha["sockets"]}
    for clip in clips:
        duration = float(clip["duration_s"])
        for track in clip.get("tracks", []):
            target = track["target"]
            v.check(target in valid_targets, f"{clip['clip_id']}: unknown animation target {target}")
            keys = track["keys"]
            times = [float(k["t"]) for k in keys]
            v.check(times == sorted(times), f"{clip['clip_id']}/{target}: key times decrease")
            v.check(all(0.0 <= t <= duration + 1e-6 for t in times), f"{clip['clip_id']}/{target}: key outside duration")
            if track["channel"] == "rotation_euler_xyz_deg":
                for key in keys:
                    values = key["v"]
                    if target in bone_by_name:
                        limits = bone_by_name[target].get("rotation_limits_xyz_deg", {})
                        for i, axis in enumerate("xyz"):
                            if axis in limits:
                                lo, hi = limits[axis]
                                v.check(lo - 1e-6 <= values[i] <= hi + 1e-6, f"{clip['clip_id']}/{target}@{key['t']}: {axis}={values[i]} outside {lo}..{hi}")
                    elif target in auxiliary_nodes:
                        node = auxiliary_nodes[target]
                        axis = node.get("axis", "none")
                        if axis in "XYZ" and "limits_deg" in node:
                            idx = "XYZ".index(axis)
                            lo, hi = node["limits_deg"]
                            v.check(lo - 1e-6 <= values[idx] <= hi + 1e-6, f"{clip['clip_id']}/{target}@{key['t']}: angle outside {lo}..{hi}")
        for event in clip.get("events", []):
            v.check(0.0 <= float(event["t"]) <= duration + 1e-6, f"{clip['clip_id']}: event outside duration")
            if "instance_id" in event:
                v.check(event["instance_id"] in instance_by_id, f"{clip['clip_id']}: event references unknown instance {event['instance_id']}")
            if "socket" in event:
                v.check(event["socket"] in socket_names, f"{clip['clip_id']}: event references unknown socket {event['socket']}")
        swarm = clip.get("procedural_swarm", {})
        for socket in swarm.get("source_sockets", []):
            v.check(socket in socket_names, f"{clip['clip_id']}: unknown swarm source socket {socket}")
        for constraint in clip.get("contact_constraints", []):
            v.check(constraint["socket"] in socket_names, f"{clip['clip_id']}: unknown contact socket")
            v.check(constraint["target_instance"] in instance_by_id, f"{clip['clip_id']}: unknown contact target instance")
    for control in anim["input_driven_controls"]:
        v.check(control["node"] in auxiliary_nodes, f"input control {control['interaction_id']}: unknown node")

    states = mission["states"]
    state_by_id = {s["state_id"]: s for s in states}
    v.unique((s["state_id"] for s in states), "mission states")
    v.check(mission["initial_state"] in state_by_id, "mission: invalid initial state")
    for state in states:
        start, end = state["nominal_window_s"]
        v.check(0 <= start < end <= 420 or state.get("branch") is True, f"{state['state_id']}: invalid nominal window")
        for tr in state.get("transitions", []):
            v.check(tr["to"] in state_by_id, f"{state['state_id']}: unknown transition {tr['to']}")
        for action in state.get("on_input", []):
            v.check(action["input"] in mission["input_definitions"], f"{state['state_id']}: undefined input {action['input']}")
            if "next" in action:
                v.check(action["next"] in state_by_id, f"{state['state_id']}: unknown on_input next {action['next']}")
    adjacency = {s["state_id"]: set() for s in states}
    for state in states:
        adjacency[state["state_id"]].update(t["to"] for t in state.get("transitions", []))
        adjacency[state["state_id"]].update(a["next"] for a in state.get("on_input", []) if "next" in a)
    reachable = {mission["initial_state"]}
    frontier = [mission["initial_state"]]
    while frontier:
        current = frontier.pop()
        for nxt in adjacency.get(current, set()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    v.check(reachable == set(state_by_id), f"mission: unreachable states: {sorted(set(state_by_id) - reachable)}")
    for obj in walk_objects(mission):
        if "clip_id" in obj:
            v.check(obj["clip_id"] in clip_by_id, f"mission: unknown clip reference {obj['clip_id']}")
        if "instance_id" in obj:
            v.check(obj["instance_id"] in instance_by_id, f"mission: unknown instance reference {obj['instance_id']}")
    checkpoints = mission["checkpoints"]
    checkpoint_ids = {c["checkpoint_id"] for c in checkpoints}
    v.unique((c["checkpoint_id"] for c in checkpoints), "checkpoints")
    for state in states:
        v.check(state["checkpoint_id"] in checkpoint_ids, f"{state['state_id']}: unknown checkpoint")
    for cp in checkpoints:
        v.check(cp["state_id"] in state_by_id, f"{cp['checkpoint_id']}: unknown restore state")
        v.check(cp["route_node"] in route_nodes, f"{cp['checkpoint_id']}: unknown route node")
        for clip_id, time_s in cp["clip_states"].items():
            v.check(clip_id in clip_by_id, f"{cp['checkpoint_id']}: unknown clip {clip_id}")
            if clip_id in clip_by_id:
                v.check(0.0 <= time_s <= clip_by_id[clip_id]["duration_s"], f"{cp['checkpoint_id']}: invalid sample time for {clip_id}")

    main_states = sorted((s for s in states if not s.get("branch")), key=lambda s: s["nominal_window_s"][0])
    v.check(main_states[0]["nominal_window_s"][0] == 0, "timeline: must start at 0")
    v.check(main_states[-1]["nominal_window_s"][1] == mission["nominal_total_duration_s"], "timeline: wrong final time")
    for previous, current in zip(main_states, main_states[1:]):
        v.check(previous["nominal_window_s"][1] == current["nominal_window_s"][0], f"timeline: gap/overlap between {previous['state_id']} and {current['state_id']}")
    v.check({s["scene"] for s in states} == {f"S{i:02d}" for i in range(8)}, "timeline: S00–S07 must all be present")

    thermal = mission["thermal_model"]
    arrival = thermal["after_clear_percent"] + thermal["move_complete_add"] + thermal["l1_deploy_add"] + thermal["jammer_during_l1_add"]
    v.check(close(arrival, thermal["nominal_arrival_with_jammer"]), "thermal: arrival arithmetic mismatch")
    v.check(close(arrival + thermal["bus_base_peak_add"] + thermal["bus_concurrent_jammer_peak_add"], thermal["forecast_with_jammer"]), "thermal: jammer-on forecast mismatch")
    v.check(close(arrival + thermal["bus_base_peak_add"], thermal["forecast_without_jammer"]), "thermal: jammer-off forecast mismatch")

    scene_interactions = {c["interaction_id"] for c in components if "interaction_id" in c}
    for interaction_id in scene_interactions:
        v.check(interaction_id in mission["input_definitions"], f"scene interaction {interaction_id}: absent from mission input definitions")
    for control in anim["input_driven_controls"]:
        v.check(control["interaction_id"] in scene_interactions, f"animated control {control['interaction_id']}: no scene interaction component")
    for socket in mecha["sockets"]:
        if socket["name"] == "SeatAnchor":
            v.check(close(socket["position_parent_local_m"][1], 1.15), "SeatAnchor: eye height must remain human-scale 1.15 m")

    v.check(len(mission["acceptance_tests"]) >= 11, "mission: M01–M11 acceptance tests required")
    v.warn(False, "Static checks do not validate Blender geometry, actual vertex weights, rendering, PICO performance, or comfort.")
    return finish(v)


def finish(v: Validator) -> int:
    report = {
        "contract_id": "steel_ridge.dropzone.p0",
        "validation_level": "static_json_and_cross_file_references",
        "checks_run": v.checks,
        "errors": v.errors,
        "warnings": v.warnings,
        "passed": not v.errors,
        "geometry_and_runtime_validation": "not_run",
    }
    report_path = ROOT / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not v.errors else 1


if __name__ == "__main__":
    sys.exit(main())
