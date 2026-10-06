# Render by Blocks
# Copyright (C) 2026 Pipafoguete
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.

bl_info = {
    "name": "Render by Blocks",
    "author": "Pipafoguete",
    "version": (2, 1, 0),
    "blender": (5, 2, 0),
    "location": "Properties > Output > Render by Blocks",
    "description": "Automatically renders animations in blocks, with normal mode or safe pause mode and optional joining.",
    "category": "Render",
}


# ============================================================
# IMPORTS
# ============================================================

import bpy
import os
import re
import json
import time
import shutil
import subprocess


# ============================================================
# EDITABLE SETTINGS
# ============================================================

ADDON_NAME = "Render by Blocks"
ADDON_AUTHOR = "Gabe"
ADDON_VERSION = (2, 1, 0)

# ------------------------------------------------------------
# FOLDER
# ------------------------------------------------------------

FOLDER_NAME = "RENDER_BLOCOS"
DEFAULT_PATH = f"//{FOLDER_NAME}"
TEMP_NAME = ".RPB_TEMP"
VIDEOS_SUBFOLDER_NAME = "VIDEOS"

# ------------------------------------------------------------
# VIDEOS
# ------------------------------------------------------------

VIDEO_PREFIX = "Video_"
VIDEO_EXTENSION = ".mp4"
COMPLETE_VIDEO_NAME = "Video_COMPLETO.mp4"

# ------------------------------------------------------------
# AUXILIARY FILES
# ------------------------------------------------------------

FFMPEG_LIST_NAME = "lista_blocos.txt"
MANIFEST_NAME = "manifesto_blocos.json"

# ------------------------------------------------------------
# DEFAULTS
# ------------------------------------------------------------

DEFAULT_START_FRAME = 1
DEFAULT_END_FRAME = 250
DEFAULT_FRAMES_PER_BLOCK = 100

# ------------------------------------------------------------
# TEMPORARY VIDEO
# ------------------------------------------------------------

VIDEO_CODEC = "libx264"
VIDEO_CRF = "18"
VIDEO_PRESET = "medium"
VIDEO_PIXEL_FORMAT = "yuv420p"

# ------------------------------------------------------------
# SHORTCUT
# ------------------------------------------------------------

RENDER_SHORTCUT_KEY = "R"
RENDER_SHORTCUT_CTRL = True
RENDER_SHORTCUT_ALT = True
RENDER_SHORTCUT_SHIFT = False
RENDER_SHORTCUT_TEXT = "Ctrl + Alt + R"

PAUSE_SHORTCUT_KEY = "P"
PAUSE_SHORTCUT_CTRL = True
PAUSE_SHORTCUT_ALT = True
PAUSE_SHORTCUT_SHIFT = False
PAUSE_SHORTCUT_TEXT = "Ctrl + Alt + P"

# ------------------------------------------------------------
# INTERFACE TEXTS
# ------------------------------------------------------------

TITLE_SETTINGS = "Settings"
TITLE_SELECTION = "Selection"
TITLE_BLOCKS = "Blocks"
TITLE_STATUS = "Status"
TITLE_COMPLETE_VIDEO = "Complete video"
TITLE_RENDER_CONTROL = "Render control"

TEXT_RENDER = "Render selected"
TEXT_STOP = "Stop rendering"
TEXT_PAUSE = "Pause after completed frame"
TEXT_RESUME = "Resume"
TEXT_CANCEL_PAUSE = "Cancel pause"
TEXT_REFRESH = "Refresh blocks"
TEXT_SELECT_ALL = "Select all"
TEXT_DESELECT_ALL = "Deselect all"
TEXT_SELECT_MISSING = "Select missing only"
TEXT_JOIN = "Join all blocks"
TEXT_MANUAL_MODE = "Manual Mode (Safe Pause Mode)"
TEXT_AUTOMATIC_MODE = "Automatic Mode (Normal Mode)"
TEXT_AUTO_JOIN = "Automatically join when finished"


# ============================================================
# INTERNAL STATE
# ============================================================

ORIGINAL_SETTINGS = {}
RENDER_START_TIME = {}
ACTIVE = {}
KEYMAP_ITEMS = {}


# ============================================================
# UI REDRAW AND EXECUTION
# ============================================================

def tag_redraw_ui():
    """Forces a visual refresh of all Properties panels."""
    try:
        wm = bpy.context.window_manager
        if not wm:
            return
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
    except Exception:
        pass


def execute_render_with_context():
    """Executes rendering while ensuring the correct window context."""
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm and wm.windows else None
    
    if not window:
        bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
        return

    screen = window.screen
    area = next((a for a in screen.areas if a.type == 'PROPERTIES'), screen.areas[0] if screen.areas else None)
    region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None

    with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
        bpy.ops.render.render("INVOKE_DEFAULT", animation=True)


# ============================================================
# BLOCK
# ============================================================

class RPB_Block(bpy.types.PropertyGroup):
    number: bpy.props.IntProperty()
    start_frame: bpy.props.IntProperty()
    end_frame: bpy.props.IntProperty()
    exists: bpy.props.BoolProperty(default=False)
    selected: bpy.props.BoolProperty(default=True)


# ============================================================
# PATHS
# ============================================================

def project_folder():
    try:
        path = bpy.path.abspath("//")
    except Exception:
        path = ""
    return os.path.abspath(path or os.getcwd())


def output_folder(scene):
    configured = (getattr(scene, "rpb_output_folder", "") or "").strip()
    if not configured:
        configured = DEFAULT_PATH

    try:
        path = bpy.path.abspath(configured)
    except Exception:
        path = configured

    if not path:
        path = os.path.join(project_folder(), FOLDER_NAME)

    return os.path.abspath(os.path.normpath(path))


def ensure_output_folder(scene):
    path = output_folder(scene)
    os.makedirs(path, exist_ok=True)

    if not os.path.isdir(path):
        raise RuntimeError(f"The folder does not exist: {path}")

    return path


def videos_folder(scene):
    """Dedicated folder where all MP4 videos generated by the add-on are stored."""
    path = os.path.join(output_folder(scene), VIDEOS_SUBFOLDER_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def temp_root(scene):
    path = os.path.join(ensure_output_folder(scene), TEMP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def temp_segment(scene, block, fragment):
    path = os.path.join(
        temp_root(scene),
        f"B{block:04d}_F{fragment:04d}",
    )
    os.makedirs(path, exist_ok=True)
    return path


def video_path(scene, block):
    return os.path.join(
        videos_folder(scene),
        f"{VIDEO_PREFIX}{block:02d}{VIDEO_EXTENSION}",
    )


def fragment_path(scene, block, fragment):
    return os.path.join(
        videos_folder(scene),
        f"{VIDEO_PREFIX}{block:02d}.{fragment}{VIDEO_EXTENSION}",
    )


def complete_path(scene):
    return os.path.join(videos_folder(scene), COMPLETE_VIDEO_NAME)


def concat_path(scene):
    return os.path.join(output_folder(scene), FFMPEG_LIST_NAME)


def manifest_path(scene):
    return os.path.join(output_folder(scene), MANIFEST_NAME)


# ============================================================
# EXTERNAL AND INTERNAL FFMPEG
# ============================================================

def ffmpeg_path(scene=None):
    """Finds the FFmpeg executable in the UI, system, or Blender."""
    if scene and hasattr(scene, "rpb_ffmpeg_path"):
        custom_path = getattr(scene, "rpb_ffmpeg_path", "").strip()
        if custom_path:
            abs_path = bpy.path.abspath(custom_path)
            if os.path.isfile(abs_path):
                return abs_path

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg

    blender_dir = os.path.dirname(bpy.app.binary_path)
    possible_paths = [
        os.path.join(blender_dir, "ffmpeg.exe"),
        os.path.join(blender_dir, "ffmpeg"),
        os.path.join(blender_dir, "extern", "ffmpeg", "ffmpeg.exe"),
    ]
    for p in possible_paths:
        if os.path.isfile(p):
            return p

    return None


def run_ffmpeg(args):
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )


# ============================================================
# VIDEOS AND FRAGMENTS
# ============================================================

def fragments(scene, block):
    folder = videos_folder(scene)
    rx = re.compile(rf"^{re.escape(VIDEO_PREFIX)}{block:02d}\.(\d+)\.mp4$")
    found = []

    try:
        if not os.path.isdir(folder):
            return []

        for name in os.listdir(folder):
            match = rx.match(name)
            if not match:
                continue

            path = os.path.join(folder, name)
            if os.path.isfile(path):
                found.append((int(match.group(1)), path))

    except Exception:
        pass

    return sorted(found, key=lambda item: item[0])


def next_fragment(scene, block):
    found = fragments(scene, block)
    return max((number for number, _ in found), default=0) + 1


# ============================================================
# MANIFEST
# ============================================================

def load_manifest(scene):
    path = manifest_path(scene)
    if not os.path.isfile(path):
        return {"version": 1, "blocks": {}}

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Invalid manifest.")

        data.setdefault("version", 1)
        data.setdefault("blocks", {})

        if not isinstance(data["blocks"], dict):
            data["blocks"] = {}

        return data

    except Exception as error:
        print("[Render by Blocks] Error reading manifest:", error)
        return {"version": 1, "blocks": {}}


def save_manifest(scene, data):
    path = manifest_path(scene)
    temporary = path + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()

    os.replace(temporary, path)


def add_manifest_segment(scene, block, fragment, start, end, path):
    data = load_manifest(scene)
    block_data = data["blocks"].setdefault(str(block), {"fragments": {}})
    block_data.setdefault("fragments", {})

    fps = 0.0
    try:
        fps = float(scene.render.fps) / float(scene.render.fps_base)
    except Exception:
        fps = 0.0

    block_data["fragments"][str(fragment)] = {
        "file": os.path.basename(path),
        "start_frame": int(start),
        "end_frame": int(end),
        "frame_count": int(end - start + 1),
        "fps": fps,
        "created": time.time(),
    }

    save_manifest(scene, data)


def add_manifest_normal(scene, block, start, end, path):
    data = load_manifest(scene)
    data["blocks"][str(block)] = {
        "start_frame": int(start),
        "end_frame": int(end),
        "complete_file": os.path.basename(path),
        "fragments": {},
    }
    save_manifest(scene, data)


def remove_manifest_block(scene, block):
    data = load_manifest(scene)
    if str(block) in data.get("blocks", {}):
        del data["blocks"][str(block)]
        save_manifest(scene, data)


def get_manifest_fragments(scene, block):
    data = load_manifest(scene)
    return data.get("blocks", {}).get(str(block), {}).get("fragments", {})


# ============================================================
# FILE VERIFICATION
# ============================================================

def valid_file(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def block_complete(scene, block_obj):
    normal = video_path(scene, block_obj.number)
    if valid_file(normal):
        return True

    data = get_manifest_fragments(scene, block_obj.number)
    if not data:
        return False

    expected = block_obj.start_frame

    for number in sorted(int(key) for key in data.keys()):
        info = data.get(str(number), {})
        filename = info.get("file", "")
        path = os.path.join(videos_folder(scene), filename)

        if not valid_file(path):
            return False

        try:
            start = int(info["start_frame"])
            end = int(info["end_frame"])
        except Exception:
            return False

        if start != expected or end < start:
            return False

        expected = end + 1

    return expected == block_obj.end_frame + 1


def refresh_blocks(scene):
    if not hasattr(scene, "rpb_blocks"):
        return

    # In Manual Mode, blocks belong to the user.
    # Never regenerate the list automatically.
    if getattr(scene, "rpb_mode", "AUTOMATICO") == "MANUAL":
        for block in scene.rpb_blocks:
            block.exists = block_complete(scene, block)
        return

    # Automatic Mode: rebuilds blocks from start/end/size.
    previous_selection = {block.number: block.selected for block in scene.rpb_blocks}
    scene.rpb_blocks.clear()

    try:
        start_frame = int(scene.rpb_start_frame)
        end_frame = int(scene.rpb_end_frame)
        size = max(1, int(scene.rpb_block_size))
    except Exception:
        return

    if end_frame < start_frame:
        return

    current = start_frame
    number = 1

    while current <= end_frame:
        block = scene.rpb_blocks.add()
        block.number = number
        block.start_frame = current
        block.end_frame = min(current + size - 1, end_frame)
        block.exists = block_complete(scene, block)
        block.selected = previous_selection.get(number, not block.exists)

        current += size
        number += 1


def save_settings(scene):
    data = {
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "filepath": scene.render.filepath,
        "file_format": scene.render.image_settings.file_format,
        "media_type": getattr(scene.render.image_settings, "media_type", None),
        "ffmpeg": {},
    }

    try:
        for prop in scene.render.ffmpeg.bl_rna.properties:
            if prop.identifier == "rna_type" or prop.is_readonly:
                continue
            if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                try:
                    data["ffmpeg"][prop.identifier] = getattr(scene.render.ffmpeg, prop.identifier)
                except Exception:
                    pass
    except Exception:
        pass

    return data


def restore_settings(scene, data):
    if not data:
        return

    try:
        scene.frame_start = data["frame_start"]
        scene.frame_end = data["frame_end"]
        scene.frame_current = data["frame_current"]
        scene.render.filepath = data["filepath"]
        media_type = data.get("media_type")
        if media_type:
            try:
                scene.render.image_settings.media_type = media_type
            except Exception:
                pass
        scene.render.image_settings.file_format = data["file_format"]
    except Exception:
        pass

    for key, value in data.get("ffmpeg", {}).items():
        try:
            setattr(scene.render.ffmpeg, key, value)
        except Exception:
            pass


def configure_ffmpeg_normal(scene, output):
    # Blender 5.x separates the media type (IMAGE/VIDEO) from the format.
    # First switch to VIDEO to enable FFmpeg formats.
    try:
        scene.render.image_settings.media_type = "VIDEO"
    except Exception:
        pass

    try:
        scene.render.image_settings.file_format = "FFMPEG_VIDEO"
    except Exception:
        scene.render.image_settings.file_format = "FFMPEG"

    scene.render.filepath = output

    try:
        scene.render.ffmpeg.format = "MPEG4"
    except Exception:
        pass

    try:
        scene.render.ffmpeg.codec = "H264"
    except Exception:
        pass


def configure_png(scene, folder):
    # Blender 5.x: while media_type is VIDEO, PNG does not appear
    # among the allowed enums. Switch to IMAGE before setting PNG.
    try:
        scene.render.image_settings.media_type = "IMAGE"
    except Exception:
        pass

    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(folder, "frame_######")


# ============================================================
# PAUSE MODE ENCODER
# ============================================================

def encode_segment(scene, folder, start, end, output):
    ff = ffmpeg_path(scene)
    if not ff:
        raise RuntimeError("FFmpeg was not found. Install FFmpeg on your system or set its path in the panel.")

    fps = float(scene.render.fps) / float(scene.render.fps_base)
    count = int(end - start + 1)
    input_pattern = os.path.join(folder, "frame_%06d.png")

    command = [
        ff,
        "-y",
        "-framerate", f"{fps:.12g}",
        "-start_number", str(start),
        "-i", input_pattern,
        "-frames:v", str(count),
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", VIDEO_PRESET,
        "-pix_fmt", VIDEO_PIXEL_FORMAT,
        "-movflags", "+faststart",
        output,
    ]

    result = run_ffmpeg(command)

    if result.returncode != 0:
        raise RuntimeError("FFmpeg failed to finalize the fragment:\n" + result.stderr[-4000:])

    if not valid_file(output):
        raise RuntimeError("The MP4 was not created correctly.")


def cleanup_segment(folder):
    if not folder:
        return
    try:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    except Exception as error:
        print("[Render by Blocks] Could not delete temporary files:", error)


# ============================================================
# RENDER STATE
# ============================================================

def exact_last_frame(state):
    return int(state.get("last_written", state["start"] - 1))


def scene_from_pointer(pointer):
    for scene in bpy.data.scenes:
        try:
            if scene.as_pointer() == pointer:
                return scene
        except Exception:
            pass
    return None


def finish(scene, restore=True):
    pointer = scene.as_pointer()

    scene.rpb_rendering = False
    scene.rpb_paused = False
    scene.rpb_pause_requested = False
    scene.rpb_current_block = 0

    ACTIVE.pop(pointer, None)
    settings = ORIGINAL_SETTINGS.pop(pointer, None)

    if restore and settings:
        restore_settings(scene, settings)

    RENDER_START_TIME.pop(pointer, None)
    refresh_blocks(scene)
    tag_redraw_ui()


# ============================================================
# BLOCK SELECTION
# ============================================================

def find_first(scene):
    for block in scene.rpb_blocks:
        if not block.selected:
            continue
        if scene.rpb_skip_existing and block_complete(scene, block):
            continue
        return block
    return None


def find_next(scene):
    for block in scene.rpb_blocks:
        if block.number <= scene.rpb_current_block or not block.selected:
            continue
        if scene.rpb_skip_existing and block_complete(scene, block):
            continue
        return block
    return None


def find_block_by_number(scene, number):
    for block in scene.rpb_blocks:
        if block.number == number:
            return block
    return None


# ============================================================
# PAUSE MODE RESUME
# ============================================================

def contiguous_resume(scene, block):
    data = get_manifest_fragments(scene, block.number)
    if not data:
        return None

    expected = block.start_frame
    last = None

    for number in sorted(int(key) for key in data.keys()):
        info = data.get(str(number), {})
        path = os.path.join(videos_folder(scene), info.get("file", ""))

        if not valid_file(path):
            break

        try:
            start = int(info["start_frame"])
            end = int(info["end_frame"])
        except Exception:
            break

        if start != expected or end < start:
            break

        last = end
        expected = end + 1

    if last is not None and last < block.end_frame:
        return last

    return None


# ============================================================
# FRAGMENT FINALIZATION
# ============================================================

def finalize_segment(scene, end_frame):
    pointer = scene.as_pointer()
    state = ACTIVE.get(pointer)

    if not state or state.get("finalizing"):
        return False

    state["finalizing"] = True
    end_frame = min(int(end_frame), int(state["block_end"]))

    if end_frame < state["start"]:
        cleanup_segment(state.get("temp", ""))
        state["finalizing"] = False
        return False

    try:
        encode_segment(scene, state["temp"], state["start"], end_frame, state["output"])

        if state["fragment"]:
            add_manifest_segment(scene, state["block"], state["fragment"], state["start"], end_frame, state["output"])
        else:
            add_manifest_normal(scene, state["block"], state["start"], end_frame, state["output"])

        cleanup_segment(state["temp"])
        state["finalizing"] = False
        return True

    except Exception as error:
        state["finalizing"] = False
        scene.rpb_status = f"ERROR finalizing {os.path.basename(state['output'])}: {error}"
        print("[Render by Blocks] Error finalizing fragment:", error)
        tag_redraw_ui()
        return False


# ============================================================
# START NEXT BLOCK / FRAGMENT
# ============================================================

def schedule_start_next(pointer):
    def timer_callback():
        scene = scene_from_pointer(pointer)
        if scene and scene.rpb_rendering:
            start_next(scene)
        return None

    bpy.app.timers.register(timer_callback, first_interval=0.1)


def start_next(scene):
    if not scene.rpb_rendering:
        return

    pointer = scene.as_pointer()
    active_state = ACTIVE.get(pointer)

    if scene.rpb_mode == "MANUAL" and scene.rpb_paused and active_state and active_state.get("mode") == "pause":
        block = find_block_by_number(scene, active_state["block"])
        if block is None:
            scene.rpb_status = "Paused block was not found."
            finish(scene)
            return

        start_frame = active_state["start"]
        fragment_number = active_state["next_fragment"]
    else:
        block = find_first(scene) if scene.rpb_current_block == 0 else find_next(scene)

        if block is None:
            scene.rpb_status = "Rendering completed!"
            finish(scene)

            if scene.rpb_auto_join:
                refresh_blocks(scene)
                if all(block_complete(scene, item) for item in scene.rpb_blocks):
                    if not ffmpeg_path(scene):
                        scene.rpb_status = (
                            "Rendering completed! All blocks are ready, but FFmpeg "
                            "was not found to create Video_COMPLETO.mp4."
                        )
                    else:
                        try:
                            count, _ = join_videos_files(scene)
                            scene.rpb_status = f"Rendering completed! Complete video created with {count} parts."
                        except Exception as error:
                            scene.rpb_status = f"Automatic joining failed: {error}"
                else:
                    scene.rpb_status = "Rendering completed. Some blocks are missing; video was not joined."

            tag_redraw_ui()
            return

        start_frame = block.start_frame
        fragment_number = 0

    try:
        ensure_output_folder(scene)
    except Exception as error:
        scene.rpb_status = f"Folder error: {error}"
        finish(scene)
        return

    if not scene.rpb_mode == "MANUAL":
        output = video_path(scene, block.number)
        remove_manifest_block(scene, block.number)

        if os.path.isfile(output):
            try:
                os.remove(output)
            except Exception:
                pass

        scene.rpb_current_block = block.number
        scene.frame_start = block.start_frame
        scene.frame_end = block.end_frame

        configure_ffmpeg_normal(scene, output)

        ACTIVE[pointer] = {
            "mode": "normal",
            "block": block.number,
            "block_start": block.start_frame,
            "block_end": block.end_frame,
            "start": block.start_frame,
            "output": output,
        }

        scene.rpb_status = f"RENDERING • Block {block.number} • Frames {block.start_frame}-{block.end_frame}"
        tag_redraw_ui()

        try:
            execute_render_with_context()
        except Exception as error:
            scene.rpb_status = f"Error starting render: {error}"
            finish(scene)

        return

    if not (active_state and active_state.get("paused") and active_state.get("block") == block.number):
        resume_frame = contiguous_resume(scene, block)
        if resume_frame is not None:
            start_frame = resume_frame + 1
            fragment_number = next_fragment(scene, block.number)

    if start_frame > block.end_frame:
        scene.rpb_current_block = block.number
        ACTIVE.pop(pointer, None)
        scene.rpb_paused = False
        schedule_start_next(pointer)
        return

    if fragment_number == 0:
        output = video_path(scene, block.number)
        remove_manifest_block(scene, block.number)
        if os.path.isfile(output):
            try:
                os.remove(output)
            except Exception:
                pass
    else:
        output = fragment_path(scene, block.number, fragment_number)

    temporary_folder = temp_segment(scene, block.number, fragment_number)
    cleanup_segment(temporary_folder)
    os.makedirs(temporary_folder, exist_ok=True)

    scene.rpb_current_block = block.number
    scene.frame_start = start_frame
    scene.frame_end = block.end_frame

    configure_png(scene, temporary_folder)

    ACTIVE[pointer] = {
        "mode": "pause",
        "block": block.number,
        "block_start": block.start_frame,
        "block_end": block.end_frame,
        "start": start_frame,
        "fragment": fragment_number,
        "output": output,
        "temp": temporary_folder,
        "last_written": start_frame - 1,
        "paused": False,
        "next_fragment": fragment_number if fragment_number else 1,
        "finalizing": False,
    }

    scene.rpb_paused = False
    frag_str = f".{fragment_number}" if fragment_number else ""
    scene.rpb_status = f"RENDERING • Block {block.number}{frag_str} • Frames {start_frame}-{block.end_frame}"
    tag_redraw_ui()

    try:
        execute_render_with_context()
    except Exception as error:
        scene.rpb_status = f"Error starting render: {error}"
        cleanup_segment(temporary_folder)
        finish(scene)


# ============================================================
# PAUSE
# ============================================================

def schedule_cancel(pointer):
    def cancel_callback():
        scene = scene_from_pointer(pointer)
        state = ACTIVE.get(pointer)

        if not scene or not state or not scene.rpb_rendering or not scene.rpb_pause_requested:
            return None

        try:
            bpy.ops.render.render_cancel()
        except Exception as error:
            print("[Render by Blocks] Error cancelling for pause:", error)

        return None

    try:
        bpy.app.timers.register(cancel_callback, first_interval=0.05)
    except Exception:
        cancel_callback()


def request_pause(scene):
    if not scene.rpb_rendering or scene.rpb_paused or scene.rpb_pause_requested:
        return

    pointer = scene.as_pointer()
    state = ACTIVE.get(pointer)

    if not state or state.get("mode") != "pause":
        return

    scene.rpb_pause_requested = True
    scene.rpb_status = "PAUSE REQUESTED • finishing the frame currently being written..."
    tag_redraw_ui()
    schedule_cancel(pointer)


# ============================================================
# HANDLERS
# ============================================================

def render_write(scene_or_depsgraph, *args):
    scene = getattr(scene_or_depsgraph, "scene", scene_or_depsgraph)
    if not hasattr(scene, "rpb_rendering") or not scene.rpb_rendering:
        return

    pointer = scene.as_pointer()
    state = ACTIVE.get(pointer)

    if not state or state.get("mode") != "pause":
        return

    frame = int(scene.frame_current)
    if state["start"] <= frame <= state["block_end"]:
        state["last_written"] = frame

    tag_redraw_ui()

    if scene.rpb_pause_requested:
        schedule_cancel(pointer)


def render_complete(scene_or_depsgraph, *args):
    scene = getattr(scene_or_depsgraph, "scene", scene_or_depsgraph)
    if not hasattr(scene, "rpb_rendering") or not scene.rpb_rendering:
        return

    pointer = scene.as_pointer()
    state = ACTIVE.get(pointer)

    if not state:
        return

    if state.get("mode") == "normal":
        output = state["output"]
        block_number = state["block"]

        if not valid_file(output):
            scene.rpb_status = f"Block {block_number} finished, but the MP4 was not created correctly."
            finish(scene)
            return

        add_manifest_normal(scene, block_number, state["start"], state["block_end"], output)
        ACTIVE.pop(pointer, None)
        scene.rpb_status = f"Block {block_number} completed."
        refresh_blocks(scene)
        
        schedule_start_next(pointer)
        return

    block_end = state["block_end"]
    if not finalize_segment(scene, block_end):
        finish(scene)
        return

    block_number = state["block"]
    ACTIVE.pop(pointer, None)
    scene.rpb_pause_requested = False
    scene.rpb_paused = False

    scene.rpb_status = f"Block {block_number} completed."
    refresh_blocks(scene)
    
    schedule_start_next(pointer)


def render_cancel(scene_or_depsgraph, *args):
    scene = getattr(scene_or_depsgraph, "scene", scene_or_depsgraph)
    if not hasattr(scene, "rpb_rendering") or not scene.rpb_rendering:
        return

    pointer = scene.as_pointer()
    state = ACTIVE.get(pointer)

    if not state:
        return

    if state.get("mode") == "normal":
        output = state.get("output")
        try:
            if output and os.path.isfile(output):
                os.remove(output)
        except Exception:
            pass

        scene.rpb_status = "Rendering stopped. The incomplete MP4 was discarded."
        finish(scene)
        return

    if not scene.rpb_pause_requested:
        cleanup_segment(state.get("temp", ""))
        scene.rpb_status = "Rendering stopped."
        finish(scene)
        return

    last = exact_last_frame(state)

    if last < state["start"]:
        state["paused"] = True
        state["next_fragment"] = state["fragment"] if state["fragment"] else 1
        scene.rpb_pause_requested = False
        scene.rpb_paused = True
        scene.rpb_status = f"PAUSED • no new frame completed. Resume starts at {state['start']}"
        tag_redraw_ui()
        return

    if state["fragment"] == 0:
        state["fragment"] = 1
        state["output"] = fragment_path(scene, state["block"], 1)
        state["next_fragment"] = 1

    if not finalize_segment(scene, last):
        return

    block_number = state["block"]
    current_fragment = state["fragment"]
    next_fragment_number = current_fragment + 1
    next_start = last + 1

    if next_start > state["block_end"]:
        ACTIVE.pop(pointer, None)
        scene.rpb_pause_requested = False
        scene.rpb_paused = False
        scene.rpb_status = f"Block {block_number} completed."
        refresh_blocks(scene)
        schedule_start_next(pointer)
        return

    next_temp = temp_segment(scene, block_number, next_fragment_number)
    cleanup_segment(next_temp)
    os.makedirs(next_temp, exist_ok=True)

    ACTIVE[pointer] = {
        "mode": "pause",
        "block": block_number,
        "block_start": state["block_start"],
        "block_end": state["block_end"],
        "start": next_start,
        "fragment": next_fragment_number,
        "output": fragment_path(scene, block_number, next_fragment_number),
        "temp": next_temp,
        "last_written": next_start - 1,
        "paused": True,
        "next_fragment": next_fragment_number,
        "finalizing": False,
    }

    scene.rpb_pause_requested = False
    scene.rpb_paused = True
    scene.rpb_status = (
        f"PAUSED • Block {block_number}.{current_fragment} saved through frame {last} • "
        f"Resume starts at {next_start}"
    )

    refresh_blocks(scene)


def finish_stop(scene):
    try:
        bpy.ops.render.render_cancel()
    except Exception:
        pass

    finish(scene)
    scene.rpb_status = "Rendering stopped."
    tag_redraw_ui()


# ============================================================
# OPERATORS
# ============================================================

class RPB_OT_Refresh(bpy.types.Operator):
    bl_idname = "rpb.refresh"
    bl_label = TEXT_REFRESH

    def execute(self, context):
        refresh_blocks(context.scene)
        context.scene.rpb_status = "Block list updated."
        return {"FINISHED"}


class RPB_OT_SelectAll(bpy.types.Operator):
    bl_idname = "rpb.select_all"
    bl_label = TEXT_SELECT_ALL

    def execute(self, context):
        for block in context.scene.rpb_blocks:
            block.selected = True
        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_DeselectAll(bpy.types.Operator):
    bl_idname = "rpb.deselect_all"
    bl_label = TEXT_DESELECT_ALL

    def execute(self, context):
        for block in context.scene.rpb_blocks:
            block.selected = False
        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_SelectMissing(bpy.types.Operator):
    bl_idname = "rpb.select_missing"
    bl_label = TEXT_SELECT_MISSING

    def execute(self, context):
        scene = context.scene
        for block in scene.rpb_blocks:
            block.selected = not block_complete(scene, block)
        scene.rpb_status = "Selected blocks that are not complete."
        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_Render(bpy.types.Operator):
    bl_idname = "rpb.render"
    bl_label = TEXT_RENDER

    def execute(self, context):
        scene = context.scene

        if scene.rpb_rendering:
            self.report({"WARNING"}, "A rendering is already active.")
            return {"CANCELLED"}

        refresh_blocks(scene)
        if not any(block.selected for block in scene.rpb_blocks):
            self.report({"WARNING"}, "No blocks selected.")
            return {"CANCELLED"}

        if scene.rpb_mode == "MANUAL" and not ffmpeg_path(scene):
            self.report({"ERROR"}, "Manual Mode (Safe Pause) requires FFmpeg. Set the executable path or install it on the system.")
            return {"CANCELLED"}

        try:
            ensure_output_folder(scene)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        pointer = scene.as_pointer()
        ORIGINAL_SETTINGS[pointer] = save_settings(scene)

        scene.rpb_rendering = True
        scene.rpb_paused = False
        scene.rpb_pause_requested = False
        scene.rpb_current_block = 0
        scene.rpb_status = "Preparing rendering • " + ("MANUAL MODE" if scene.rpb_mode == "MANUAL" else "AUTOMATIC MODE")

        RENDER_START_TIME[pointer] = time.time()
        start_next(scene)
        return {"FINISHED"}


class RPB_OT_TogglePause(bpy.types.Operator):
    bl_idname = "rpb.toggle_pause"
    bl_label = TEXT_PAUSE

    def execute(self, context):
        scene = context.scene

        if not scene.rpb_mode == "MANUAL":
            self.report({"INFO"}, "Enable 'Manual Mode' to use pause.")
            return {"CANCELLED"}

        if scene.rpb_paused:
            state = ACTIVE.get(scene.as_pointer())
            if not state:
                self.report({"ERROR"}, "Pause state not found.")
                return {"CANCELLED"}

            scene.rpb_paused = False
            scene.rpb_rendering = True
            scene.rpb_status = f"Resuming at frame {state['start']}..."
            start_next(scene)
            return {"FINISHED"}

        if not scene.rpb_rendering:
            self.report({"WARNING"}, "No rendering is active.")
            return {"CANCELLED"}

        if scene.rpb_pause_requested:
            scene.rpb_pause_requested = False
            scene.rpb_status = "Pause cancelled. Rendering continues."
            tag_redraw_ui()
            return {"FINISHED"}

        request_pause(scene)
        return {"FINISHED"}


class RPB_OT_Stop(bpy.types.Operator):
    bl_idname = "rpb.stop"
    bl_label = TEXT_STOP

    def execute(self, context):
        scene = context.scene
        if not scene.rpb_rendering:
            return {"CANCELLED"}

        scene.rpb_pause_requested = False
        finish_stop(scene)
        return {"FINISHED"}


# ============================================================
# JOIN VIDEOS
# ============================================================

def collect_join_files(scene):
    files = []
    for block in scene.rpb_blocks:
        normal = video_path(scene, block.number)
        if valid_file(normal):
            files.append(normal)
            continue

        files.extend(path for _, path in fragments(scene, block.number) if valid_file(path))
    return files


def validate_continuity(scene):
    data = load_manifest(scene)
    ordered = []
    errors = []

    for block in scene.rpb_blocks:
        normal = video_path(scene, block.number)

        if valid_file(normal):
            info = data.get("blocks", {}).get(str(block.number), {})
            try:
                manifest_start = int(info.get("start_frame", block.start_frame))
                manifest_end = int(info.get("end_frame", block.end_frame))

                if manifest_start != block.start_frame or manifest_end != block.end_frame:
                    errors.append(f"Block {block.number}: manifest does not match the current range.")
            except Exception:
                pass

            ordered.append(normal)
            continue

        info = data.get("blocks", {}).get(str(block.number), {})
        fragment_data = info.get("fragments", {})

        if not fragment_data:
            errors.append(f"Block {block.number}: no file.")
            continue

        expected = block.start_frame
        items = []

        for number in sorted(int(key) for key in fragment_data.keys()):
            item = fragment_data.get(str(number), {})
            path = os.path.join(videos_folder(scene), item.get("file", ""))

            if not valid_file(path):
                errors.append(f"Block {block.number}: fragment .{number} does not exist.")
                continue

            try:
                start = int(item["start_frame"])
                end = int(item["end_frame"])
            except Exception:
                errors.append(f"Block {block.number}: fragment .{number} has an invalid manifest.")
                continue

            items.append((number, path, start, end))

        if not items:
            continue

        for number, path, start, end in items:
            if end < start:
                errors.append(f"Block {block.number}: fragment .{number} has an invalid range.")
                continue

            if start != expected:
                if start > expected:
                    errors.append(f"Block {block.number}: frames {expected}-{start - 1} are missing before fragment .{number}.")
                else:
                    errors.append(f"Block {block.number}: overlap in fragment .{number} ({start}-{end}).")

            expected = end + 1
            ordered.append(path)

        if expected <= block.end_frame:
            errors.append(f"Block {block.number}: frames {expected}-{block.end_frame} are missing.")
        elif expected > block.end_frame + 1:
            errors.append(f"Block {block.number}: coverage exceeds the expected end.")

    if errors:
        return False, errors

    return True, ordered


def write_concat_file(path, files):
    with open(path, "w", encoding="utf-8") as file:
        for video in files:
            normalized = os.path.abspath(video).replace("\\", "/").replace("'", "'\\''")
            file.write(f"file '{normalized}'\n")


def join_videos_files(scene):
    ff = ffmpeg_path(scene)
    if not ff:
        raise RuntimeError(
            "FFmpeg was not found on the system or at the configured path.\n"
            "Select the path to the 'ffmpeg.exe' executable in the add-on panel."
        )

    ensure_output_folder(scene)
    refresh_blocks(scene)

    if scene.rpb_verify_continuity:
        valid, data = validate_continuity(scene)
        if not valid:
            preview = "\n".join(data[:12]) if data else "Unknown error."
            if len(data) > 12:
                preview += f"\n... and {len(data) - 12} more error(s)."
            raise RuntimeError("There are gaps or overlaps in the sequence:\n" + preview)
        files = data
    else:
        files = collect_join_files(scene)

    if not files:
        raise RuntimeError("No videos found to join.")

    list_file = concat_path(scene)
    output = complete_path(scene)

    write_concat_file(list_file, files)

    try:
        command = [ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output]
        result = run_ffmpeg(command)

        if result.returncode != 0:
            raise RuntimeError("FFmpeg could not join the files.\n" + result.stderr[-4000:])

        if not valid_file(output):
            raise RuntimeError("Video_COMPLETO.mp4 was not created correctly.")

        return len(files), output
    finally:
        try:
            if os.path.isfile(list_file):
                os.remove(list_file)
        except Exception:
            pass



class RPB_OT_AddBlock(bpy.types.Operator):
    bl_idname = "rpb.add_block"
    bl_label = "Add block"
    bl_description = "Creates a manual block"

    def execute(self, context):
        scene = context.scene
        if scene.rpb_mode != "MANUAL":
            self.report({"WARNING"}, "Switch to Manual Mode.")
            return {"CANCELLED"}

        block = scene.rpb_blocks.add()
        block.number = len(scene.rpb_blocks)

        if len(scene.rpb_blocks) == 1:
            block.start_frame = scene.frame_start
        else:
            block.start_frame = scene.rpb_blocks[-2].end_frame + 1

        block.end_frame = min(block.start_frame + 99, scene.frame_end)
        block.selected = True
        block.exists = block_complete(scene, block)
        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_RemoveBlock(bpy.types.Operator):
    bl_idname = "rpb.remove_block"
    bl_label = "Remove block"

    index: bpy.props.IntProperty()

    def execute(self, context):
        scene = context.scene
        if scene.rpb_mode != "MANUAL":
            return {"CANCELLED"}
        if self.index < 0 or self.index >= len(scene.rpb_blocks):
            return {"CANCELLED"}

        scene.rpb_blocks.remove(self.index)

        for number, block in enumerate(scene.rpb_blocks, start=1):
            block.number = number

        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_ClearManualBlocks(bpy.types.Operator):
    bl_idname = "rpb.clear_manual_blocks"
    bl_label = "Clear blocks"

    def execute(self, context):
        scene = context.scene
        if scene.rpb_mode != "MANUAL":
            return {"CANCELLED"}

        scene.rpb_blocks.clear()
        scene.rpb_status = "Manual blocks cleared."
        tag_redraw_ui()
        return {"FINISHED"}


class RPB_OT_JoinVideos(bpy.types.Operator):
    bl_idname = "rpb.join_videos"
    bl_label = TEXT_JOIN

    def execute(self, context):
        scene = context.scene

        if scene.rpb_rendering:
            self.report({"WARNING"}, "Stop rendering before joining.")
            return {"CANCELLED"}

        try:
            count, output = join_videos_files(scene)
        except Exception as error:
            scene.rpb_status = f"Error joining: {error}"
            print("[Render by Blocks] Error joining:", error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        scene.rpb_status = f"Complete video created! {count} parts."
        tag_redraw_ui()
        self.report({"INFO"}, f"{COMPLETE_VIDEO_NAME} created.")
        return {"FINISHED"}


# ============================================================
# INTERFACE PANEL
# ============================================================

class RPB_PT_Main(bpy.types.Panel):
    bl_label = ADDON_NAME
    bl_idname = "RPB_PT_Main"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "output"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        manual = scene.rpb_mode == "MANUAL"

        total = len(scene.rpb_blocks)
        completed = sum(bool(block.exists) for block in scene.rpb_blocks)
        selected = sum(bool(block.selected) for block in scene.rpb_blocks)

        # ========================================================
        # 1. OUTPUT
        # ========================================================
        output = layout.box()
        output.label(text="1. OUTPUT", icon="FILE_FOLDER")

        col = output.column(align=True)
        col.prop(scene, "rpb_output_folder", text="Folder")
        col.prop(scene, "rpb_ffmpeg_path", text="FFmpeg")

        has_ffmpeg = bool(ffmpeg_path(scene))
        if has_ffmpeg:
            ok = col.row()
            ok.label(text="FFmpeg detected", icon="CHECKMARK")
        else:
            warn = col.row()
            warn.alert = True
            warn.label(text="FFmpeg not detected — required to join MP4s", icon="ERROR")

        # ========================================================
        # 2. MODE
        # ========================================================
        mode_box = layout.box()
        mode_box.label(text="2. SPLIT MODE", icon="RENDER_ANIMATION")
        mode_box.prop(scene, "rpb_mode", expand=True)

        if manual:
            info = mode_box.box()
            info.label(text="Manual", icon="PAUSE")
            info.label(text="Create the blocks and define the Start/End of each one.")
            info.prop(scene, "rpb_skip_existing", text="Skip already completed blocks")
        else:
            info = mode_box.box()
            info.label(text="Automatic", icon="PLAY")

            row = info.row(align=True)
            row.prop(scene, "rpb_start_frame", text="Start")
            row.prop(scene, "rpb_end_frame", text="End")
            info.prop(scene, "rpb_block_size", text="Frames per block")
            info.prop(scene, "rpb_skip_existing", text="Skip already completed blocks")

        # ========================================================
        # 3. BLOCKS
        # ========================================================
        blocks_box = layout.box()
        blocks_box.label(text="3. BLOCKS", icon="SEQUENCE")

        summary = blocks_box.row()
        summary.label(text=f"{completed}/{total} ready")
        summary.label(text=f"{selected} selected")

        if manual:
            row = blocks_box.row(align=True)
            row.operator("rpb.add_block", text="Add block", icon="ADD")
            row.operator("rpb.clear_manual_blocks", text="Clear", icon="TRASH")
        else:
            row = blocks_box.row(align=True)
            row.operator("rpb.refresh", text="Refresh", icon="FILE_REFRESH")
            row.operator("rpb.select_all", text="All", icon="CHECKBOX_HLT")
            row.operator("rpb.select_missing", text="Missing", icon="RESTRICT_RENDER_OFF")

        if total == 0:
            empty = blocks_box.box()
            empty.label(text="No blocks created.", icon="INFO")
            if manual:
                empty.label(text="Click 'Add block'.")
        else:
            for i, block in enumerate(scene.rpb_blocks):
                block_box = blocks_box.box()

                if block.exists:
                    icon = "CHECKMARK"
                    status = "Ready"
                elif fragments(scene, block.number):
                    icon = "FILE"
                    status = "Fragmented"
                else:
                    icon = "TIME"
                    status = "Pending"

                top = block_box.row(align=True)
                top.prop(block, "selected", text="")
                top.label(text=f"Block {block.number:02d} — {status}", icon=icon)

                if manual:
                    row = block_box.row(align=True)
                    row.prop(block, "start_frame", text="Start")
                    row.prop(block, "end_frame", text="Fim")
                    remove = row.operator("rpb.remove_block", text="", icon="X")
                    remove.index = i
                else:
                    block_box.label(text=f"Frames: {block.start_frame} – {block.end_frame}")

                found = fragments(scene, block.number)
                if found:
                    parts = ", ".join(f".{number}" for number, _ in found)
                    block_box.label(text=f"Saved parts: {parts}", icon="FILE")

        # ========================================================
        # 4. OPTIONS
        # ========================================================
        options = layout.box()
        options.label(text="4. OPTIONS", icon="SETTINGS")
        options.prop(scene, "rpb_auto_join", text="Automatically join when finished")
        options.prop(scene, "rpb_verify_continuity", text="Verify continuity when joining")

        # ========================================================
        # 5. CONTROL
        # ========================================================
        control = layout.box()
        control.label(text="5. CONTROL", icon="PLAY")

        if scene.rpb_rendering:
            control.label(text=scene.rpb_status, icon="TIME")
            control.label(text=f"Block {scene.rpb_current_block} / {total}  •  Frame {scene.frame_current}")

            if manual:
                if scene.rpb_paused:
                    control.operator("rpb.toggle_pause", text=TEXT_RESUME, icon="PLAY")
                elif scene.rpb_pause_requested:
                    control.operator("rpb.toggle_pause", text=TEXT_CANCEL_PAUSE, icon="LOOP_BACK")
                else:
                    control.operator("rpb.toggle_pause", text=TEXT_PAUSE, icon="PAUSE")

            control.operator("rpb.stop", text=TEXT_STOP, icon="CANCEL")
        else:
            row = control.row()
            row.scale_y = 1.4
            row.operator("rpb.render", text=TEXT_RENDER, icon="RENDER_ANIMATION")
            control.label(text=f"Shortcut: {RENDER_SHORTCUT_TEXT}", icon="EVENT_R")
            if manual:
                control.label(text=f"Pause/resume: {PAUSE_SHORTCUT_TEXT}", icon="PAUSE")

        # ========================================================
        # 6. STATUS
        # ========================================================
        status_box = layout.box()
        status_box.label(text="6. STATUS", icon="INFO")
        status_box.label(text=scene.rpb_status)

        # ========================================================
        # 7. COMPLETE VIDEO
        # ========================================================
        join = layout.box()
        join.label(text="7. COMPLETE VIDEO", icon="SEQ_SEQUENCER")
        join.label(text="Joins the MP4s without rendering again.")
        join.operator("rpb.join_videos", text=TEXT_JOIN, icon="SEQ_SEQUENCER")


# ============================================================
# REGISTRATION AND PROPERTIES
# ============================================================

def update_blocks(self, context):
    if context and hasattr(context, "scene") and hasattr(context.scene, "rpb_blocks"):
        refresh_blocks(context.scene)


def update_ffmpeg_path(self, context):
    tag_redraw_ui()


# RENDER MODE CALLBACK

def update_mode(self, context):
    if not context:
        return

    scene = context.scene

    if scene.rpb_mode == "MANUAL":
        if len(scene.rpb_blocks) == 0:
            block = scene.rpb_blocks.add()
            block.number = 1
            block.start_frame = scene.frame_start
            block.end_frame = min(scene.frame_start + 99, scene.frame_end)
            block.selected = True
    else:
        refresh_blocks(scene)

    tag_redraw_ui()

def register_properties():
    bpy.types.Scene.rpb_blocks = bpy.props.CollectionProperty(type=RPB_Block)
    bpy.types.Scene.rpb_start_frame = bpy.props.IntProperty(name="Start frame", default=DEFAULT_START_FRAME, min=0, update=update_blocks)
    bpy.types.Scene.rpb_end_frame = bpy.props.IntProperty(name="End frame", default=DEFAULT_END_FRAME, min=1, update=update_blocks)
    bpy.types.Scene.rpb_block_size = bpy.props.IntProperty(name="Frames per block", default=DEFAULT_FRAMES_PER_BLOCK, min=1, update=update_blocks)
    bpy.types.Scene.rpb_output_folder = bpy.props.StringProperty(name="Output folder", default=DEFAULT_PATH, subtype="DIR_PATH")
    
    bpy.types.Scene.rpb_ffmpeg_path = bpy.props.StringProperty(
        name="FFmpeg path",
        default="",
        subtype="FILE_PATH",
        description="Manual path to the FFmpeg executable (e.g. ffmpeg.exe)",
        update=update_ffmpeg_path
    )
    
    bpy.types.Scene.rpb_skip_existing = bpy.props.BoolProperty(name="Skip existing", default=True)
    
    # RENDER MODE
    bpy.types.Scene.rpb_mode = bpy.props.EnumProperty(
        name="Mode",
        description="Choose how the blocks will be rendered.",
        items=[
            ("AUTOMATICO", "Automatic", "Renders each block directly to MP4.", "PLAY", 0),
            ("MANUAL", "Manual", "Renders with temporary PNG + FFmpeg and allows safe pauses.", "PAUSE", 1),
        ],
        default="AUTOMATICO",
        update=update_mode,
    )

    bpy.types.Scene.rpb_auto_join = bpy.props.BoolProperty(name="Automatically join when finished", description="Automatically creates Video_COMPLETO.mp4 when all blocks are complete.", default=True)
    bpy.types.Scene.rpb_verify_continuity = bpy.props.BoolProperty(name="Verify continuity", description="Checks for gaps and overlaps before joining the videos.", default=True)
    bpy.types.Scene.rpb_rendering = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.rpb_paused = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.rpb_pause_requested = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.rpb_current_block = bpy.props.IntProperty(default=0)
    bpy.types.Scene.rpb_status = bpy.props.StringProperty(default="Ready.")


def unregister_properties():
    properties = (
        "rpb_blocks", "rpb_start_frame", "rpb_end_frame", "rpb_block_size",
        "rpb_output_folder", "rpb_ffmpeg_path", "rpb_skip_existing", "rpb_mode",
        "rpb_auto_join", "rpb_verify_continuity", "rpb_rendering",
        "rpb_paused", "rpb_pause_requested", "rpb_current_block", "rpb_status",
    )
    for name in properties:
        try:
            delattr(bpy.types.Scene, name)
        except Exception:
            pass


classes = (
    RPB_Block,
    RPB_OT_Refresh,
    RPB_OT_SelectAll,
    RPB_OT_DeselectAll,
    RPB_OT_SelectMissing,
    RPB_OT_AddBlock,
    RPB_OT_RemoveBlock,
    RPB_OT_ClearManualBlocks,
    RPB_OT_Render,
    RPB_OT_TogglePause,
    RPB_OT_Stop,
    RPB_OT_JoinVideos,
    RPB_PT_Main,
)


def register_keymap():
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon if wm else None
        if not kc:
            return

        km = kc.keymaps.new(name="Window", space_type="EMPTY")

        # Ctrl + Alt + R = Render
        kmi_render = km.keymap_items.new(
            "rpb.render",
            RENDER_SHORTCUT_KEY,
            "PRESS",
            ctrl=RENDER_SHORTCUT_CTRL,
            alt=RENDER_SHORTCUT_ALT,
            shift=RENDER_SHORTCUT_SHIFT,
        )
        KEYMAP_ITEMS["render"] = (km, kmi_render)

        # Ctrl + Alt + P = Pause/resume in Manual Mode
        kmi_pause = km.keymap_items.new(
            "rpb.toggle_pause",
            PAUSE_SHORTCUT_KEY,
            "PRESS",
            ctrl=PAUSE_SHORTCUT_CTRL,
            alt=PAUSE_SHORTCUT_ALT,
            shift=PAUSE_SHORTCUT_SHIFT,
        )
        KEYMAP_ITEMS["pause"] = (km, kmi_pause)

    except Exception as error:
        print("[Render by Blocks] Shortcut error:", error)

def unregister_keymap():
    for km, kmi in list(KEYMAP_ITEMS.values()):
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    KEYMAP_ITEMS.clear()


def initialize():
    try:
        for scene in bpy.data.scenes:
            if not scene.rpb_output_folder.strip():
                scene.rpb_output_folder = DEFAULT_PATH

            if scene.rpb_start_frame == DEFAULT_START_FRAME and scene.rpb_end_frame == DEFAULT_END_FRAME:
                scene.rpb_start_frame = scene.frame_start
                scene.rpb_end_frame = scene.frame_end

            if not scene.rpb_status:
                scene.rpb_status = "Ready."

            if not scene.rpb_rendering:
                scene.rpb_paused = False
                scene.rpb_pause_requested = False

            if scene.rpb_mode == "MANUAL" and len(scene.rpb_blocks) == 0:
                block = scene.rpb_blocks.add()
                block.number = 1
                block.start_frame = scene.frame_start
                block.end_frame = min(scene.frame_start + 99, scene.frame_end)
                block.selected = True

            refresh_blocks(scene)

        print("[Render by Blocks] Initialization completed.")
    except Exception as error:
        print("[Render by Blocks] Initialization error:", error)

    if bpy.app.timers.is_registered(initialize):
        bpy.app.timers.unregister(initialize)


def register_handlers():
    if render_write not in bpy.app.handlers.render_write:
        bpy.app.handlers.render_write.append(render_write)
    if render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(render_complete)
    if render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(render_cancel)


def unregister_handlers():
    for handler, collection in (
        (render_write, bpy.app.handlers.render_write),
        (render_complete, bpy.app.handlers.render_complete),
        (render_cancel, bpy.app.handlers.render_cancel),
    ):
        try:
            while handler in collection:
                collection.remove(handler)
        except Exception:
            pass


def register():
    registered_classes = []
    properties_registered = False

    try:
        bpy.utils.register_class(RPB_Block)
        registered_classes.append(RPB_Block)

        register_properties()
        properties_registered = True

        for cls in classes[1:]:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)

        register_handlers()
        register_keymap()

        try:
            if not bpy.app.timers.is_registered(initialize):
                bpy.app.timers.register(initialize, first_interval=0.5)
        except Exception as error:
            print("[Render by Blocks] Timer error:", error)

        print("=" * 60)
        print("[Render by Blocks] ADD-ON REGISTERED SUCCESSFULLY")
        print(f"[Render by Blocks] Version: {ADDON_VERSION}")
        print("=" * 60)

    except Exception as error:
        print("=" * 60)
        print("[Render by Blocks] ERROR REGISTERING ADD-ON")
        print(f"[Render by Blocks] {type(error).__name__}: {error}")
        print("=" * 60)

        unregister_handlers()
        unregister_keymap()

        try:
            if bpy.app.timers.is_registered(initialize):
                bpy.app.timers.unregister(initialize)
        except Exception:
            pass

        if properties_registered:
            unregister_properties()

        for cls in reversed(registered_classes):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass

        raise


def unregister():
    try:
        if bpy.app.timers.is_registered(initialize):
            bpy.app.timers.unregister(initialize)
    except Exception:
        pass

    unregister_keymap()
    unregister_handlers()

    ORIGINAL_SETTINGS.clear()
    RENDER_START_TIME.clear()
    ACTIVE.clear()

    unregister_properties()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    print("[Render by Blocks] Add-on unregistered.")


if __name__ == "__main__":
    register()
