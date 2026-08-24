import bmesh
import bpy
from bpy.types import Operator
from collections import deque


UV_CONNECT_EPS = 1e-5
STACK_IOU = 0.85
STACK_SIGNATURE = 0.8
UV_QUANT = 500
V_OFFSET = 1.0


def _iter_target_meshes(context):
    seen = set()
    objects = list(context.selected_objects)
    active = context.view_layer.objects.active
    if active is not None and active not in objects:
        objects.append(active)

    for obj in objects:
        if obj is None:
            continue
        if obj.type == "MESH" and obj.data not in seen:
            seen.add(obj.data)
            yield obj
        elif obj.type == "ARMATURE":
            candidates = list(obj.children_recursive)
            for other in getattr(context.scene, "objects", []):
                if other.type != "MESH":
                    continue
                for modifier in other.modifiers:
                    if modifier.type == "ARMATURE" and modifier.object == obj:
                        candidates.append(other)
                        break
            for child in candidates:
                if child.type == "MESH" and child.data not in seen:
                    seen.add(child.data)
                    yield child


def _uvs_match(loop_a, loop_b, uv_layer):
    ua = loop_a[uv_layer].uv
    ub = loop_b[uv_layer].uv
    return abs(ua.x - ub.x) < UV_CONNECT_EPS and abs(ua.y - ub.y) < UV_CONNECT_EPS


def _edge_uv_connected(face_a, face_b, edge, uv_layer):
    loops_a = [loop for loop in face_a.loops if loop.vert in edge.verts]
    loops_b = [loop for loop in face_b.loops if loop.vert in edge.verts]
    if len(loops_a) != 2 or len(loops_b) != 2:
        return False
    for loop_a in loops_a:
        loop_b = next((loop for loop in loops_b if loop.vert == loop_a.vert), None)
        if loop_b is None or not _uvs_match(loop_a, loop_b, uv_layer):
            return False
    return True


def _uv_islands(bm, uv_layer):
    bm.faces.ensure_lookup_table()
    visited = [False] * len(bm.faces)
    islands = []

    for start in bm.faces:
        if visited[start.index]:
            continue
        island = []
        queue = deque([start])
        visited[start.index] = True
        while queue:
            face = queue.popleft()
            island.append(face)
            for edge in face.edges:
                for other in edge.link_faces:
                    if visited[other.index]:
                        continue
                    if _edge_uv_connected(face, other, edge, uv_layer):
                        visited[other.index] = True
                        queue.append(other)
        islands.append(island)
    return islands


def _island_bbox(faces, uv_layer):
    min_u = min_v = float("inf")
    max_u = max_v = float("-inf")
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            min_u = min(min_u, uv.x)
            min_v = min(min_v, uv.y)
            max_u = max(max_u, uv.x)
            max_v = max(max_v, uv.y)
    if min_u == float("inf"):
        return None
    return (min_u, min_v, max_u, max_v)


def _bbox_iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max((ax1 - ax0) * (ay1 - ay0), 1e-12)
    area_b = max((bx1 - bx0) * (by1 - by0), 1e-12)
    return inter / (area_a + area_b - inter)


def _uv_signature(faces, uv_layer):
    points = set()
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            points.add((round(uv.x * UV_QUANT), round(uv.y * UV_QUANT)))
    return points


def _signature_jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _islands_are_stacked(bbox_a, bbox_b, signature_a, signature_b):
    if bbox_a is None or bbox_b is None:
        return False
    if _bbox_iou(bbox_a, bbox_b) < STACK_IOU:
        return False
    return _signature_jaccard(signature_a, signature_b) >= STACK_SIGNATURE


def _island_centroid_3d(faces):
    verts = set()
    for face in faces:
        verts.update(face.verts)
    if not verts:
        return (0.0, 0.0, 0.0)
    count = len(verts)
    return (
        sum(vert.co.x for vert in verts) / count,
        sum(vert.co.y for vert in verts) / count,
        sum(vert.co.z for vert in verts) / count,
    )


def _group_stacked_islands(bboxes, signatures):
    parent = list(range(len(bboxes)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i in range(len(bboxes)):
        if bboxes[i] is None:
            continue
        for j in range(i + 1, len(bboxes)):
            if _islands_are_stacked(bboxes[i], bboxes[j], signatures[i], signatures[j]):
                union(i, j)

    groups = {}
    for i in range(len(bboxes)):
        groups.setdefault(find(i), []).append(i)
    return [members for members in groups.values() if len(members) > 1]


def _offset_island(faces, uv_layer, delta_v):
    for face in faces:
        for loop in face.loops:
            loop[uv_layer].uv.y += delta_v


def unstack_uvs_on_mesh(obj):
    mesh = obj.data
    if not mesh.uv_layers:
        return 0

    in_edit = obj.mode == "EDIT"
    if in_edit:
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
    else:
        bm = bmesh.new()
        bm.from_mesh(mesh)

    moved = 0
    active_uv = mesh.uv_layers.active
    if bm.faces and active_uv is not None:
        uv_layer = bm.loops.layers.uv.get(active_uv.name)
        if uv_layer is not None:
            islands = _uv_islands(bm, uv_layer)
            bboxes = [_island_bbox(island, uv_layer) for island in islands]
            signatures = [_uv_signature(island, uv_layer) for island in islands]
            for group in _group_stacked_islands(bboxes, signatures):
                group.sort(key=lambda index: _island_centroid_3d(islands[index]))
                for island_index in group[1:]:
                    _offset_island(islands[island_index], uv_layer, V_OFFSET)
                    moved += 1

    if in_edit:
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

    return moved


class SUB_OP_unstack_uv_islands(Operator):
    bl_idname = "sub.unstack_uv_islands"
    bl_label = "Unstack UV Islands"
    bl_description = (
        "Move truly stacked UV copies up by 1 UV unit. Packed neighbors stay put."
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(True for _ in _iter_target_meshes(context))

    def execute(self, context):
        meshes = list(_iter_target_meshes(context))
        if not meshes:
            self.report({"WARNING"}, "Select a mesh or an armature with mesh children.")
            return {"CANCELLED"}

        meshes_changed = 0
        islands_moved = 0
        skipped_no_uv = 0

        for obj in meshes:
            if not obj.data.uv_layers:
                skipped_no_uv += 1
                continue
            moved = unstack_uvs_on_mesh(obj)
            if moved:
                meshes_changed += 1
                islands_moved += moved

        if islands_moved:
            self.report(
                {"INFO"},
                f"Unstacked {islands_moved} UV island(s) on {meshes_changed} mesh(es).",
            )
        elif skipped_no_uv == len(meshes):
            self.report({"WARNING"}, "Selected meshes have no UV maps.")
        else:
            self.report({"INFO"}, "No stacked UV islands found.")
        return {"FINISHED"}


def register():
    bpy.utils.register_class(SUB_OP_unstack_uv_islands)


def unregister():
    bpy.utils.unregister_class(SUB_OP_unstack_uv_islands)
