# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {'name': 'Showcase', 'author': 'Ricardo Lugaresi', 'version': (1, 0, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Showcase',
           'description': 'Vídeos y fotos de producto de una pieza en un clic: estudio, luces y cámara automáticos',
           'category': 'Render'}

import bpy

from . import common, studio

PRESET_ITEMS = [('TURNTABLE', 'Giro 360', 'Vuelta completa a velocidad constante'),
                ('SHOWROOM', 'Vitrina', 'Vuelta completa acercándose poco a poco'),
                ('HERO', 'Detalle', 'Media vuelta lenta y cerca, para enseñar detalles')]
ASPECT_ITEMS = [('SQUARE', 'Cuadrado', 'Feed de Instagram y LinkedIn (1080 × 1080)'),
                ('VERTICAL', 'Vertical', 'Reels, Stories, TikTok, estados de WhatsApp (1080 × 1920)'),
                ('HORIZONTAL', 'Horizontal', 'Web, YouTube y presentaciones (1920 × 1080)')]
FONDO_ITEMS = [('LIGHT', 'Claro', 'Estudio gris claro'),
               ('DARK', 'Oscuro', 'Negro de la marca')]
COLOR_ITEMS = [('ORIGINAL', 'Sus colores', 'Los materiales que ya tiene la pieza'),
               ('FILAMENT', 'Filamento', 'Un color de filamento para toda la pieza')]
CALIDAD_ITEMS = [('DRAFT', 'Prueba', 'Rápido, a media resolución, para ver cómo queda'),
                 ('FINAL', 'Final', 'Resolución completa y más calidad')]


class ShowcaseProps(bpy.types.PropertyGroup):
    preset: bpy.props.EnumProperty(name='Vídeo', items=PRESET_ITEMS, default='TURNTABLE')
    aspecto: bpy.props.EnumProperty(name='Formato', items=ASPECT_ITEMS, default='SQUARE')
    segundos: bpy.props.FloatProperty(name='Duración (s)', default=6.0, min=2.0, max=30.0, step=50, precision=1)
    fps: bpy.props.EnumProperty(name='FPS', items=[('24', '24', ''), ('30', '30', ''), ('60', '60', '')], default='30')
    fondo: bpy.props.EnumProperty(name='Fondo', items=FONDO_ITEMS, default='LIGHT')
    modo_color: bpy.props.EnumProperty(name='Color', items=COLOR_ITEMS, default='ORIGINAL')
    color: bpy.props.FloatVectorProperty(name='Color del filamento', subtype='COLOR', size=3, min=0, max=1,
                                         default=(0.55, 0.55, 0.55))
    marca: bpy.props.StringProperty(name='Marca de agua', default='Ricardo Lugaresi · ricardolugaresi.com')
    calidad: bpy.props.EnumProperty(name='Calidad', items=CALIDAD_ITEMS, default='FINAL')
    carpeta: bpy.props.StringProperty(name='Carpeta', subtype='DIR_PATH', default='//showcase/')
    done: bpy.props.StringProperty()


def _montar(context):
    p = context.scene.showcase_props
    objs = studio.piezas(context)
    context.scene['showcase_fondo'] = p.fondo
    cam = studio.montar_estudio(context, objs, p.preset, p.aspecto, p.segundos, int(p.fps), p.fondo, p.marca)
    return objs, cam


def _vista_camara(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            sp = area.spaces.active
            sp.region_3d.view_perspective = 'CAMERA'
            sp.shading.type = 'MATERIAL'
            break


# ---------------------------------------------------------------- operadores
class RENDER_OT_showcase_setup(bpy.types.Operator):
    """Monta el estudio y la cámara alrededor de la pieza para ver cómo quedará"""
    bl_idname = 'render.showcase_setup'; bl_label = 'Vista previa'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        try:
            objs, _cam = _montar(context)
        except studio.ShowcaseError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        _vista_camara(context)
        context.scene.frame_set(1)
        context.scene.showcase_props.done = 'Estudio listo: pulsa Espacio para ver el movimiento'
        self.report({'INFO'}, context.scene.showcase_props.done)
        return {'FINISHED'}


_estado = {}


def _fin_render(scene, *_args):
    """Restaura la escena al terminar (o cancelar) el render del vídeo."""
    previo = _estado.pop('render', None)
    color = _estado.pop('color', None)
    if previo is not None:
        studio.restaurar_render(scene, previo)
    if color is not None:
        studio.restaurar_color(color)
    for lista in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        while _fin_render in lista:
            lista.remove(_fin_render)
    ruta = _estado.pop('ruta', None)
    if ruta:
        scene.showcase_props.done = f'Vídeo guardado: {ruta}'


class RENDER_OT_showcase_video(bpy.types.Operator):
    """Graba el vídeo de la pieza con el preset elegido (MP4)"""
    bl_idname = 'render.showcase_video'; bl_label = 'Grabar vídeo'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context) and 'render' not in _estado

    def execute(self, context):
        p = context.scene.showcase_props
        try:
            objs, _cam = _montar(context)
        except studio.ShowcaseError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        carpeta = studio.carpeta_salida(p.carpeta)
        ruta = studio.ruta_unica(carpeta, studio.nombre_salida(objs, p.preset, p.aspecto, True))
        scene = context.scene
        _estado['color'] = studio.aplicar_color(objs, p.color) if p.modo_color == 'FILAMENT' else None
        _estado['render'] = studio.preparar_render(scene, ruta, True, p.calidad)
        _estado['ruta'] = str(ruta)
        bpy.app.handlers.render_complete.append(_fin_render)
        bpy.app.handlers.render_cancel.append(_fin_render)
        p.done = f'Grabando… {ruta.name}'
        if bpy.app.background:
            bpy.ops.render.render(animation=True)
            _fin_render(scene)
        else:
            bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        return {'FINISHED'}


class RENDER_OT_showcase_photo(bpy.types.Operator):
    """Saca una foto de producto (PNG) con el mismo estudio"""
    bl_idname = 'render.showcase_photo'; bl_label = 'Foto'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context) and 'render' not in _estado

    def execute(self, context):
        p = context.scene.showcase_props
        try:
            objs, _cam = _montar(context)
        except studio.ShowcaseError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        scene = context.scene
        carpeta = studio.carpeta_salida(p.carpeta)
        ruta = studio.ruta_unica(carpeta, studio.nombre_salida(objs, p.preset, p.aspecto, False))
        color = studio.aplicar_color(objs, p.color) if p.modo_color == 'FILAMENT' else None
        previo = studio.preparar_render(scene, ruta, False, p.calidad)
        frame = scene.frame_current
        try:
            scene.frame_set(max(1, scene.frame_end // 8))
            bpy.ops.render.render(write_still=True)
        finally:
            scene.frame_set(frame)
            studio.restaurar_render(scene, previo)
            if color is not None:
                studio.restaurar_color(color)
        p.done = f'Foto guardada: {ruta}'
        self.report({'INFO'}, p.done)
        return {'FINISHED'}


class RENDER_OT_showcase_clear(bpy.types.Operator):
    """Quita el estudio (suelo, luces y cámara). La pieza no se ha tocado"""
    bl_idname = 'render.showcase_clear'; bl_label = 'Quitar estudio'; bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mundo = context.scene.get('showcase_mundo_previo')
        studio.quitar_estudio()
        if mundo is not None:
            context.scene.world = bpy.data.worlds.get(mundo) if mundo else None
        w = bpy.data.worlds.get('Showcase_mundo')
        if w is not None and w.users == 0:
            bpy.data.worlds.remove(w)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'PERSP'
        context.scene.showcase_props.done = ''
        return {'FINISHED'}


class RENDER_OT_showcase_open(bpy.types.Operator):
    """Abre la carpeta donde se guardan los vídeos y fotos"""
    bl_idname = 'render.showcase_open'; bl_label = 'Abrir carpeta'

    def execute(self, context):
        carpeta = studio.carpeta_salida(context.scene.showcase_props.carpeta)
        bpy.ops.wm.path_open(filepath=str(carpeta))
        return {'FINISHED'}


# ---------------------------------------------------------------- panel
class VIEW3D_PT_showcase(bpy.types.Panel):
    bl_label = 'Showcase'; bl_idname = 'VIEW3D_PT_showcase'; bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'; bl_category = 'Showcase'

    def draw(self, context):
        layout = self.layout
        p = context.scene.showcase_props
        if common.draw_mode_warning(layout, context):
            return
        try:
            objs = studio.piezas(context)
        except studio.ShowcaseError:
            objs = []

        box = layout.box()
        box.label(text='1 · Pieza', icon='OBJECT_DATA')
        if not objs:
            r = box.row(); r.alert = True; r.label(text='Selecciona la pieza', icon='ERROR')
        else:
            box.label(text=objs[0].name + (f' + {len(objs) - 1}' if len(objs) > 1 else ''), icon='MESH_DATA')
        box.row().prop(p, 'modo_color', expand=True)
        if p.modo_color == 'FILAMENT':
            box.prop(p, 'color', text='')

        box = layout.box()
        box.label(text='2 · Vídeo', icon='CAMERA_DATA')
        box.row().prop(p, 'preset', expand=True)
        box.row().prop(p, 'aspecto', expand=True)
        box.row().prop(p, 'fondo', expand=True)
        r = box.row(align=True); r.prop(p, 'segundos'); r.prop(p, 'fps', text='')
        box.prop(p, 'marca')
        box.operator('render.showcase_setup', icon='HIDE_OFF')

        box = layout.box()
        box.label(text='3 · Grabar', icon='RENDER_ANIMATION')
        box.row().prop(p, 'calidad', expand=True)
        box.prop(p, 'carpeta', text='')
        col = box.column(); col.scale_y = 1.6
        col.operator('render.showcase_video', icon='RENDER_ANIMATION')
        r = box.row(align=True)
        r.operator('render.showcase_photo', icon='RENDER_STILL')
        r.operator('render.showcase_open', icon='FILE_FOLDER')
        layout.operator('render.showcase_clear', icon='X')
        if p.done:
            col = layout.column(); col.scale_y = .8
            col.label(text=p.done, icon='CHECKMARK')
        layout.label(text='La pieza no se toca: gira la cámara.', icon='INFO')


classes = (ShowcaseProps, RENDER_OT_showcase_setup, RENDER_OT_showcase_video, RENDER_OT_showcase_photo,
           RENDER_OT_showcase_clear, RENDER_OT_showcase_open, VIEW3D_PT_showcase)


def register():
    common.register_classes(classes, 'showcase_props', ShowcaseProps)


def unregister():
    for lista in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        while _fin_render in lista:
            lista.remove(_fin_render)
    common.unregister_classes(classes, 'showcase_props')
