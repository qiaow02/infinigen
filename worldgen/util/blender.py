from collections import defaultdict
from math import prod
from contextlib import nullcontext
import logging

from pathlib import Path
import gin

import bpy
import mathutils
import bmesh
import numpy as np
from tqdm import tqdm

from . import math as mutil
from .logging import Suppress

logger = logging.getLogger(__name__)

def get_all_bpy_data_targets():
    D = bpy.data
    return [
        D.objects, D.collections, D.movieclips, D.particles,
        D.meshes, D.curves, D.armatures, D.node_groups
    ]
class ViewportMode:

    def __init__(self, obj, mode):
        self.obj = obj
        self.mode = mode

    def __enter__(self):
        self.orig_active = bpy.context.active_object
        bpy.context.view_layer.objects.active = self.obj
        self.orig_mode = bpy.context.object.mode
        bpy.ops.object.mode_set(mode=self.mode)
    def __exit__(self, *args):
        bpy.context.view_layer.objects.active = self.obj
        bpy.ops.object.mode_set(mode=self.orig_mode)
        bpy.context.view_layer.objects.active = self.orig_active

class CursorLocation:

    def __init__(self, loc):
        self.loc = loc
        self.saved = None

    def __enter__(self):
        self.saved = bpy.context.scene.cursor.location
        bpy.context.scene.cursor.location = self.loc

    def __exit__(self, *_):
        bpy.context.scene.cursor.location = self.saved

class SelectObjects:

    def __init__(self, objects, active=0):
        self.objects = list(objects) if hasattr(objects, '__iter__') else [objects]
        self.active = active

        self.saved_objs = None
        self.saved_active = None

    def __enter__(self):
        self.saved_objects = list(bpy.context.selected_objects)
        self.saved_active = bpy.context.active_object
        select_none()
        select(self.objects)

        if len(self.objects):
            if isinstance(self.active, int):
                bpy.context.view_layer.objects.active = self.objects[self.active]
            else:
                bpy.context.view_layer.objects.active = self.active

    def __exit__(self, *_):

        # our saved selection / active objects may have been deleted, update them to only include valid ones
        def enforce_not_deleted(o):
            try:
                return o if o.name in bpy.data.objects else None
            except ReferenceError:
                return None
            
        self.saved_objects = [enforce_not_deleted(o) for o in self.saved_objects]
        self.saved_objects = [o for o in self.saved_objects if o is not None]

        select_none()
        select(self.saved_objects)
        if self.saved_active is not None:
            bpy.context.view_layer.objects.active = enforce_not_deleted(self.saved_active)

class DisableModifiers:

    def __init__(self, objs, keep=[]):
        self.objs = objs if isinstance(objs, list) else [objs]
        self.keep = keep
        self.modifiers_disabled = []

    def __enter__(self):
        for o in self.objs:
            for m in o.modifiers:
                if not m.show_viewport or m in self.keep:
                    continue
                self.modifiers_disabled.append(m)
                m.show_viewport = False

    def __exit__(self, *_):
        for m in self.modifiers_disabled:
            m.show_viewport = True

class TemporaryObject:

    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        return self.obj

    def __exit__(self, *_):
        if self.obj.name in bpy.data.objects:


    if keep_names is None:
        keep_names = [[]] * len(targets)

    for t, orig in zip(targets, keep_names):
        for o in t:
            if keep_in_use and o.users > 0:
                continue
            if o.name in orig:
                continue
            if '(no gc)' in o.name:
                continue
            if verbose:
                print(f'Garbage collecting {o} from {t}')
            t.remove(o)

class GarbageCollect:

    def __init__(self, targets=None, keep_in_use=True, keep_orig=True, verbose=False):
        self.targets = targets or get_all_bpy_data_targets()
        self.keep_orig = keep_orig

    def __enter__(self):
        self.names = [set(o.name for o in t) for t in self.targets]

    def __exit__(self, *_):

def select_none():
    if bpy.context.active_object is not None:
        bpy.context.active_object.select_set(False)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)

def select(objs):
    select_none()
    if not isinstance(objs, list):
        objs = [objs]
    for o in objs:
        o.select_set(True)

def delete(objs):
    if not isinstance(objs, list):
        objs = [objs]
    select_none()
    select(objs)
    with Suppress():
        bpy.ops.object.delete()

def traverse_children(obj, fn):
    fn(obj)
    for obj in obj.children:
        fn(obj)

def iter_object_tree(obj):
    yield obj
    for c in obj.children:
        yield from iter_object_tree(c)

def get_collection(name, reuse=True):
    if reuse and name in bpy.data.collections:
        return bpy.data.collections[name]
    else:
        col = bpy.data.collections.new(name=name)
        bpy.context.scene.collection.children.link(col)
        return col

def unlink(obj):
    if not isinstance(obj, list):
        obj = [obj]
    for o in obj:
        for c in list(bpy.data.collections) + [bpy.context.scene.collection]:
            if o.name in c.objects:
                c.objects.unlink(o)
def put_in_collection(obj, collection, exclusive=True):
    if exclusive:
        unlink(obj)
    collection.objects.link(obj)


def group_in_collection(objs, name: str, reuse=True, **kwargs):
    '''
    objs: List of (None | Blender Object | List[Blender Object])
    '''

    collection = get_collection(name, reuse=reuse)

    for obj in objs:
        if obj is None:
            continue
        if not isinstance(obj, list):
            obj = [obj]
        for child in obj:
            traverse_children(child, lambda obj: put_in_collection(obj, collection, **kwargs))

    return collection


def group_toplevel_collections(keyword, hide_viewport=False, hide_render=False, reuse=True):
    scenecol = bpy.context.scene.collection
    matches = [c for c in scenecol.children if c.name.startswith(keyword) and keyword != c.name]

    parent = get_collection(keyword, reuse=reuse)
    if not parent.name in scenecol.children:
        scenecol.children.link(parent)

    for c in matches:
        scenecol.children.unlink(c)
        parent.children.link(c)

    parent.hide_viewport = hide_viewport
    parent.hide_render = hide_render


def spawn_empty(name, disp_type='PLAIN_AXES', s=0.1):
    empty = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(empty)
    empty.empty_display_size = s
    empty.empty_display_type = disp_type
    return empty


    if edges is None:
        edges = []

    mesh = bpy.data.meshes.new(name=name)
    mesh.from_pydata(pts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj

def spawn_vert(name='vert'):
    return spawn_point_cloud(name, np.zeros((1, 3)))

def spawn_line(name, pts):
    idxs = np.arange(len(pts))
    edges = np.stack([idxs[:-1], idxs[1:]], axis=-1)
    return spawn_point_cloud(name, pts, edges=edges)

def spawn_plane(**kwargs):
    name = kwargs.pop('name', None)
    bpy.ops.mesh.primitive_plane_add(
        enter_editmode=False,
        align='WORLD',
        **kwargs
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj

def spawn_cube(**kwargs):
    name = kwargs.pop('name', None)
    bpy.ops.mesh.primitive_cube_add(
        enter_editmode=False,
        align='WORLD',
        **kwargs
    )
    obj = bpy.context.active_object
    if name is not None:
        obj.name = name
    return obj

    D = bpy.data
    if targets is None:
        targets = get_all_bpy_data_targets()

    if materials:
        targets.append(D.materials)

    for t in targets:
        if t in keep:
            continue
        for o in t:
            if o in keep or o.name in keep:
                continue
            t.remove(o)

    with Suppress():
        bpy.ops.ptcache.free_bake_all()


    mesh = bpy.data.meshes.new('Capsule')
    obj = bpy.data.objects.new('Capsule', mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    for v in bm.verts:
        if v.co.z > 0:
            v.co.z += height

    bm.to_mesh(mesh)
    bm.free()
    select_none()
    obj.select_set(True)
    bpy.ops.object.shade_smooth()

    return obj


    deg = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(object.evaluated_get(deg), depsgraph=deg)

    new_obj = bpy.data.objects.new(object.name + "_mesh", me)
    context.collection.objects.link(new_obj)

    for o in context.selected_objects:
        o.select_set(False)

    new_obj.matrix_world = object.matrix_world
    new_obj.select_set(True)
    context.view_layer.objects.active = new_obj

    return new_obj

def get_camera_res():
    d *= bpy.context.scene.render.resolution_percentage / 100.0
    return d

def set_geomod_inputs(mod, inputs: dict):
    assert mod.type == 'NODES'
    for k, v in inputs.items():
        soc = mod.node_group.inputs[k]
        if isinstance(soc.default_value, (float, int)):
            v = type(soc.default_value)(v)

        try:
            mod[soc.identifier] = v
        except TypeError as e:
            print(f'Error incurred while assigning {v} with {type(v)=} to {soc.identifier=} of {mod.name=}')
            raise e

def modify_mesh(obj, type, apply=True, name=None, return_mod=False, ng_inputs=None, show_viewport=None,
    if name is None:
        name = f'modify_mesh({type}, **{kwargs})'
    if show_viewport is None:
        show_viewport = not apply

    mod = obj.modifiers.new(name, type)
    mod.show_viewport = show_viewport

    if mod is None:
        raise ValueError(f'modifer.new() returned None, ensure {obj.type=} is valid for modifier {type=}')

    for k, v in kwargs.items():
        setattr(mod, k, v)
    if ng_inputs is not None:
        assert type == 'NODES'
        assert 'node_group' in kwargs
        set_geomod_inputs(mod, ng_inputs)

    if apply:
        apply_modifiers(obj, mod=mod)

    if return_mod:
        return obj, mod if not apply else None
    else:
        return obj
def constrain_object(obj, type, **kwargs):
    c = obj.constraints.new(type=type)
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c
def apply_transform(obj, loc=False, rot=True, scale=True):
    with SelectObjects(obj):
        bpy.ops.object.transform_apply(location=loc, rotation=rot, scale=scale)


    path = Path(path)

    ext = path.parts[-1].split('.')[-1]
    ext = ext.lower().strip()

    funcs = {
        'obj': bpy.ops.import_scene.obj,
        'fbx': bpy.ops.import_scene.fbx,
        'stl': bpy.ops.import_mesh.stl,

    if ext not in funcs:

    select_none()
    with Suppress():
        funcs[ext](filepath=str(path), **kwargs)

    if len(bpy.context.selected_objects) > 1:
    return bpy.context.selected_objects[0]

def boolean(objs, mode='UNION', verbose=False):
    keep, *rest = list(objs)

    if verbose:
        rest = tqdm(rest, desc=f'butil.boolean({keep.name}..., {mode=})')
    with SelectObjects(keep):
        for target in rest:
            if len(target.modifiers) != 0:

            mod = keep.modifiers.new(type='BOOLEAN', name='butil.boolean()')
            mod.operation = mode
            bpy.ops.object.modifier_apply(modifier=mod.name)

    return keep

def split_object(obj, mode='LOOSE'):
    select_none()
    select(obj)
    bpy.ops.mesh.separate(type=mode)
    return list(bpy.context.selected_objects)

def move_modifier(obj, mod, i):
    with SelectObjects(obj):


    if check_attributes:
        # make sure objs[0] has slots to recieve all the attributes of objs[1:]
        join_target = objs[0]
        for obj in objs:
            for att in obj.data.attributes:
                if att.name in join_target.data.attributes:
                    target_att = join_target.data.attributes[att.name]
                    assert att.data_type == target_att.data_type
                    assert att.domain == target_att.domain
                else:
    select(objs)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    return bpy.context.active_object
def apply_modifiers(obj, mod=None, quiet=True):
    if mod is None:
        mod = list(obj.modifiers)
    if not isinstance(mod, list):
        mod = [mod]
    for i, v in enumerate(mod):
        if isinstance(v, str):
            mod[i] = obj.modifiers[v]
    con = Suppress() if quiet else nullcontext()
    with SelectObjects(obj), con:
        for m in mod:
            bpy.ops.object.modifier_apply(modifier=m.name)

def recalc_normals(obj, inside=False):
    with ViewportMode(obj, mode='EDIT'):
        bpy.ops.mesh.select_all()
        bpy.ops.mesh.normals_make_consistent(inside=inside)


    if verbose:
        print(f"Saving .blend to {path} ({'with' if autopack else 'without'} textures)")
    with Suppress():
        if autopack:
            bpy.ops.file.autopack_toggle()
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        if autopack:
            bpy.ops.file.autopack_toggle()


    if not isinstance(objs, list):
        objs = objs
    objs = [o for o in objs if o.type == 'MESH']

    size = sum(len(o.data.vertices) for o in objs)
    if include_origins:
        size += len(objs)
    kd = mathutils.kdtree.KDTree(size)

    i = 0
    for o in objs:
        for v in o.data.vertices:
            assert i < size
            i += 1
        if include_origins:
            kd.insert(o.location, i)
            i += 1

    kd.balance()

    return kd

def merge_by_distance(obj, face_size):
    with SelectObjects(obj), ViewportMode(obj, mode='EDIT'), Suppress():
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=face_size)

def origin_set(objs, mode, **kwargs):
    with SelectObjects(objs):
        bpy.ops.object.origin_set(type=mode, **kwargs)
        
                bpy.ops.object.modifier_apply(modifier=m.name)

def avg_approx_vol(objects):
    return np.mean([prod(list(o.dimensions)) for o in objects])

def parent_to(a, b, type='OBJECT', keep_transform=False, no_inverse=False, no_transform=False):
    select_none()
    with SelectObjects([a, b], active=1):
        if no_inverse:
            bpy.ops.object.parent_no_inverse_set(keep_transform=keep_transform)
        else:
            bpy.ops.object.parent_set(type=type, keep_transform=keep_transform)

    if no_transform:
        a.location = (0,0,0)
        a.rotation_euler = (0,0,0)

    assert a.parent is b

def apply_matrix_world(obj, verts: np.array):
    return mutil.dehomogenize(mutil.homogenize(verts) @ np.array(obj.matrix_world).T)

def surface_area(obj: bpy.types.Object):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    return area

def approve_all_drivers():

    # 'Touch' every driver in the file so that blender trusts them

    n = 0

    for o in bpy.data.objects:
        if o.animation_data is None:
            continue
        for d in o.animation_data.drivers:
            d.driver.expression = d.driver.expression
            n += 1

    logging.warning(f'Re-initialized {n} as trusted. Do not run infinigen on untrusted blend files. ')

    