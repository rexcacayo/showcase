# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Showcase: estudio fotográfico automático y vídeos predefinidos de una pieza.

La pieza no se toca: gira la cámara (con sus luces) alrededor de ella sobre un suelo
liso, así parece que la pieza gira en una peana. Los ajustes de render de la escena se
guardan antes y se restauran al terminar.
"""
import math
import os
from pathlib import Path

import bpy
from mathutils import Vector

COL = 'Showcase_estudio'
TAG = 'showcase'

ASPECTOS = {
    'SQUARE': (1080, 1080),       # feed de Instagram / LinkedIn
    'VERTICAL': (1080, 1920),     # Reels, Stories, TikTok, WhatsApp estados
    'HORIZONTAL': (1920, 1080),   # web, YouTube, presentaciones
}

# preset -> (grados que gira, distancia inicio, distancia fin, elevación inicio, elevación fin)
PRESETS = {
    'TURNTABLE': (360, 1.0, 1.0, 22, 22),
    'SHOWROOM': (360, 1.15, 0.80, 30, 14),
    'HERO': (140, 0.78, 0.68, 12, 20),
}

FONDOS = {
    'LIGHT': ((0.80, 0.80, 0.78), 1.0),
    'DARK': ((0.009, 0.010, 0.011), 1.0),     # negro de la marca (#17181A en sRGB)
}


class ShowcaseError(ValueError):
    pass


# ------------------------------------------------------------------ utilidades
def _motor(scene):
    ids = [e.identifier for e in scene.render.bl_rna.properties['engine'].enum_items]
    for e in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        if e in ids:
            return e
    return ids[0]


def piezas(context):
    objs = [o for o in context.selected_objects if o.type == 'MESH' and not o.get(TAG)]
    if not objs and context.active_object is not None and context.active_object.type == 'MESH' \
            and not context.active_object.get(TAG):
        objs = [context.active_object]
    if not objs:
        raise ShowcaseError('Selecciona la pieza (o varias, p. ej. antes y después).')
    return objs


def caja(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def carpeta_salida(path):
    if path.startswith('//') and not bpy.data.filepath:
        destino = Path.home() / 'Videos' / 'Showcase'
    else:
        destino = Path(bpy.path.abspath(path or '//showcase/'))
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _coleccion(context):
    col = bpy.data.collections.get(COL)
    if col is None:
        col = bpy.data.collections.new(COL)
        context.scene.collection.children.link(col)
    return col


def quitar_estudio():
    col = bpy.data.collections.get(COL)
    if col is not None:
        for o in list(col.objects):
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and getattr(data, 'users', 1) == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
                elif isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
        bpy.data.collections.remove(col)
    for m in [m for m in bpy.data.materials if m.get(TAG) and m.users == 0]:
        bpy.data.materials.remove(m)


def _material(nombre, color, rough=0.5):
    m = bpy.data.materials.get(nombre) or bpy.data.materials.new(nombre)
    m[TAG] = True
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = (*color[:3], 1.0)
        bsdf.inputs['Roughness'].default_value = rough
    m.diffuse_color = (*color[:3], 1.0)
    return m


def _ciclorama(r, seg=24):
    """Malla de fondo infinito: suelo que sube en curva hasta una pared, a lo largo de X.
    La cámara mira hacia +Y; la curva queda detrás de la pieza."""
    import bmesh
    F, B, R, H, W = 30 * r, 2.5 * r, 4 * r, 30 * r, 40 * r
    perfil = [(-F, 0.0), (B, 0.0)]
    for i in range(1, seg + 1):
        a = math.pi / 2 * i / seg
        perfil.append((B + R * math.sin(a), R * (1 - math.cos(a))))
    perfil.append((B + R, H))
    bm = bmesh.new()
    izq = [bm.verts.new((-W / 2, y, z)) for y, z in perfil]
    der = [bm.verts.new((W / 2, y, z)) for y, z in perfil]
    for i in range(len(perfil) - 1):
        bm.faces.new((izq[i], der[i], der[i + 1], izq[i + 1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new('Showcase_fondo')
    bm.to_mesh(me)
    bm.free()
    return me


def _marca_de_agua(texto, cam, cam_data, res, col, oscuro):
    """Texto centrado abajo, pegado a la cámara (siempre en el mismo sitio del encuadre)."""
    curva = bpy.data.curves.new('Showcase_marca', 'FONT')
    curva.body = texto
    curva.align_x = 'CENTER'
    curva.align_y = 'BOTTOM'
    obj = _objeto('Showcase_marca', curva, col, cam)
    prof = cam_data.clip_start * 20
    fov = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))
    ancho = 2 * prof * math.tan(fov / 2)
    if res[0] < res[1]:
        ancho *= res[0] / res[1]
    alto = ancho * res[1] / res[0]
    curva.size = ancho * 0.028 * (1.0 if res[0] >= res[1] else 1.6)
    obj.location = (0, -alto / 2 + alto * 0.035, -prof)
    m = bpy.data.materials.get('Showcase_marca') or bpy.data.materials.new('Showcase_marca')
    m[TAG] = True
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new('ShaderNodeEmission')
    color = (0.92, 0.92, 0.90) if oscuro else (0.12, 0.12, 0.12)
    em.inputs['Color'].default_value = (*color, 1.0)
    em.inputs['Strength'].default_value = 1.0
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(em.outputs[0], out.inputs[0])
    curva.materials.append(m)
    if hasattr(obj, 'visible_shadow'):
        obj.visible_shadow = False
    return obj


def _objeto(nombre, data, col, padre=None):
    o = bpy.data.objects.new(nombre, data)
    o[TAG] = True
    col.objects.link(o)
    if padre is not None:
        o.parent = padre
    return o


# ------------------------------------------------------------------ estudio
def montar_estudio(context, objs, preset='TURNTABLE', aspecto='SQUARE', segundos=6.0, fps=30,
                   fondo='LIGHT', marca=''):
    """Crea suelo, luces y cámara animada alrededor de las piezas. Devuelve la cámara."""
    quitar_estudio()
    scene = context.scene
    col = _coleccion(context)
    mn, mx = caja(objs)
    centro = (mn + mx) / 2
    radio = max((mx - mn).length / 2, 1e-6)
    alto = mx.z - mn.z

    # pivote en el centro de la pieza, a ras de suelo; la cámara y las luces cuelgan de él
    pivote = _objeto('Showcase_pivote', None, col)
    pivote.location = (centro.x, centro.y, mn.z)
    pivote.empty_display_size = radio * 0.2

    # fondo de estudio curvo (ciclorama) colgado del pivote: gira con la cámara, así
    # detrás de la pieza siempre hay fondo liso y nunca se ve el horizonte
    color_fondo, fuerza = FONDOS[fondo]
    me = _ciclorama(radio)
    suelo = _objeto('Showcase_fondo', me, col, pivote)
    suelo.location = (0, 0, -radio * 0.002)
    me.materials.append(_material('Showcase_fondo', color_fondo, 0.75))

    # mundo: color plano del fondo (se mezcla con el suelo: efecto de fondo infinito)
    world = bpy.data.worlds.get('Showcase_mundo') or bpy.data.worlds.new('Showcase_mundo')
    world[TAG] = True
    world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None)
    if bg is not None:
        bg.inputs['Color'].default_value = (*color_fondo, 1.0)
        bg.inputs['Strength'].default_value = fuerza * (0.25 if fondo == 'LIGHT' else 1.0)
    scene['showcase_mundo_previo'] = scene.world.name if scene.world else ''
    scene.world = world

    # cámara
    res = ASPECTOS[aspecto]
    cam_data = bpy.data.cameras.new('Showcase_camara')
    cam_data.lens = 60
    cam_data.sensor_fit = 'AUTO'
    cam_data.clip_start = radio * 0.01
    cam_data.clip_end = radio * 400
    cam = _objeto('Showcase_camara', cam_data, col, pivote)
    # campo de visión del lado más estrecho
    fov = 2 * math.atan(cam_data.sensor_width / (2 * cam_data.lens))
    if res[0] < res[1]:
        fov = 2 * math.atan(math.tan(fov / 2) * res[0] / res[1])
    dist_base = radio / math.sin(fov / 2) * 1.12

    grados, d0, d1, e0, e1 = PRESETS[preset]
    frames = max(2, int(round(segundos * fps)))
    objetivo = _objeto('Showcase_objetivo', None, col, pivote)
    objetivo.location = (0, 0, alto * 0.45)
    restr = cam.constraints.new('TRACK_TO')
    restr.target = objetivo
    restr.track_axis = 'TRACK_NEGATIVE_Z'
    restr.up_axis = 'UP_Y'

    def pos(dist, elev):
        e = math.radians(elev)
        return Vector((0, -dist * math.cos(e), alto * 0.45 + dist * math.sin(e)))

    cam.location = pos(dist_base * d0, e0)
    cam.keyframe_insert('location', frame=1)
    cam.location = pos(dist_base * d1, e1)
    cam.keyframe_insert('location', frame=frames)
    pivote.rotation_euler = (0, 0, math.radians(-25))
    pivote.keyframe_insert('rotation_euler', index=2, frame=1)
    pivote.rotation_euler = (0, 0, math.radians(-25 + grados))
    pivote.keyframe_insert('rotation_euler', index=2, frame=frames + (1 if grados == 360 else 0))
    _interpolacion(pivote, 'LINEAR')
    _interpolacion(cam, 'BEZIER')

    # luces (key, fill, rim) en el pivote: giran con la cámara
    d = dist_base
    for nombre, (az, el, k, size) in {
        'clave': (-40, 45, 1.0, 0.8), 'relleno': (55, 20, 0.35, 1.2), 'contra': (170, 50, 0.7, 0.6)
    }.items():
        ld = bpy.data.lights.new(f'Showcase_{nombre}', 'AREA')
        ld.shape = 'DISK'
        ld.size = radio * size * 2
        ld.energy = 60 * k * (d / 2.0) ** 2
        luz = _objeto(f'Showcase_luz_{nombre}', ld, col, pivote)
        a, e = math.radians(az), math.radians(el)
        luz.location = (d * math.sin(a) * math.cos(e), -d * math.cos(a) * math.cos(e),
                        alto * 0.45 + d * math.sin(e))
        tr = luz.constraints.new('TRACK_TO')
        tr.target = objetivo
        tr.track_axis = 'TRACK_NEGATIVE_Z'
        tr.up_axis = 'UP_Y'

    if marca:
        _marca_de_agua(marca, cam, cam_data, res, col, fondo == 'DARK')
    scene.camera = cam
    scene.frame_start = 1
    scene.frame_end = frames
    scene.render.fps = fps
    scene.render.resolution_x, scene.render.resolution_y = res
    return cam


def _interpolacion(obj, tipo):
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return
    curvas = getattr(ad.action, 'fcurves', None)
    if curvas is None:                         # Blender 5: acciones por capas
        curvas = []
        for layer in getattr(ad.action, 'layers', []):
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    curvas.extend(bag.fcurves)
    for fc in curvas:
        for k in fc.keyframe_points:
            k.interpolation = tipo
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)


# ------------------------------------------------------------------ color
def aplicar_color(objs, color):
    """Pone temporalmente el color del filamento. Devuelve lo necesario para restaurar."""
    mat = _material('Showcase_filamento', color, 0.55)
    previo = []
    for o in objs:
        slots = [s.material for s in o.material_slots]
        previo.append((o.name, slots, len(o.data.materials)))
        if not o.material_slots:
            o.data.materials.append(mat)
        for s in o.material_slots:
            s.material = mat
    return previo


def restaurar_color(previo):
    for nombre, slots, n_data in previo:
        o = bpy.data.objects.get(nombre)
        if o is None:
            continue
        while len(o.data.materials) > n_data:
            o.data.materials.pop()
        for s, m in zip(o.material_slots, slots):
            s.material = m


# ------------------------------------------------------------------ render
def preparar_render(scene, ruta, video, calidad='FINAL'):
    """Ajusta el render y devuelve un dict con lo que había para restaurarlo."""
    r = scene.render
    im = r.image_settings
    previo = {
        'engine': r.engine, 'filepath': r.filepath, 'pct': r.resolution_percentage,
        'format': im.file_format, 'stamp': r.use_stamp, 'film': r.film_transparent,
        'view': scene.view_settings.view_transform,
        'look': scene.view_settings.look,
    }
    if hasattr(im, 'media_type'):
        previo['media'] = im.media_type
    ee0 = getattr(scene, 'eevee', None)
    if ee0 is not None:
        previo['eevee'] = {a: getattr(ee0, a) for a in ('taa_render_samples', 'use_raytracing') if hasattr(ee0, a)}
    r.engine = _motor(scene)
    ee = getattr(scene, 'eevee', None)
    if ee is not None:
        for attr, val in (('taa_render_samples', 32 if calidad == 'FINAL' else 8),
                          ('use_shadows', True), ('use_raytracing', False)):
            if hasattr(ee, attr):
                try:
                    setattr(ee, attr, val)
                except (TypeError, AttributeError):
                    pass
    r.resolution_percentage = 100 if calidad == 'FINAL' else 50
    r.film_transparent = False
    try:
        scene.view_settings.view_transform = 'Standard'     # colores del filamento sin lavar
        scene.view_settings.look = 'None'
    except TypeError:
        pass
    if video:
        if hasattr(im, 'media_type'):
            im.media_type = 'VIDEO'
        im.file_format = 'FFMPEG'
        r.ffmpeg.format = 'MPEG4'
        r.ffmpeg.codec = 'H264'
        r.ffmpeg.constant_rate_factor = 'HIGH' if calidad == 'FINAL' else 'MEDIUM'
        r.ffmpeg.ffmpeg_preset = 'GOOD'
        r.ffmpeg.audio_codec = 'NONE'
    else:
        if hasattr(im, 'media_type'):
            im.media_type = 'IMAGE'
        im.file_format = 'PNG'
    r.filepath = str(ruta)
    r.use_stamp = False
    return previo


def restaurar_render(scene, previo):
    r = scene.render
    im = r.image_settings
    try:
        if 'media' in previo:
            im.media_type = previo['media']
        im.file_format = previo['format']
    except TypeError:
        pass
    r.engine = previo['engine']
    for a, v in previo.get('eevee', {}).items():
        try:
            setattr(scene.eevee, a, v)
        except (TypeError, AttributeError):
            pass
    r.filepath = previo['filepath']
    r.resolution_percentage = previo['pct']
    r.use_stamp = previo['stamp']
    r.film_transparent = previo['film']
    try:
        scene.view_settings.view_transform = previo['view']
        scene.view_settings.look = previo['look']
    except TypeError:
        pass
    mundo = scene.get('showcase_mundo_previo')
    if mundo is not None:
        scene.world = bpy.data.worlds.get(mundo) if mundo else None


def nombre_salida(objs, preset, aspecto, video):
    base = bpy.path.clean_name(objs[0].name)
    if video:
        return f'{base}_{preset.lower()}_{aspecto.lower()}.mp4'
    return f'{base}_foto_{aspecto.lower()}.png'


def ruta_unica(carpeta, nombre):
    p = carpeta / nombre
    stem, ext = os.path.splitext(nombre)
    i = 2
    while p.exists():
        p = carpeta / f'{stem}_{i}{ext}'
        i += 1
    return p
