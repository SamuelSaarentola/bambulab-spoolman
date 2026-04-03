import os
import shutil
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from helper_logs import logger

WATCH_DIR = "slicer_input"
DONE_DIR = os.path.join(WATCH_DIR, "processed")
POLL_INTERVAL = 10  # seconds

# Shared state: slot_index (1-based int) -> total weight in grams (float)
# Set when a new 3mf is parsed, cleared by bambu_printer after print completes.
_pending_slot_weights: dict[int, float] = {}
_lock = threading.Lock()


def get_pending_slot_weights() -> dict[int, float]:
    with _lock:
        return _pending_slot_weights.copy()


def clear_pending_slot_weights():
    with _lock:
        _pending_slot_weights.clear()


def parse_3mf(path: str) -> dict[int, float]:
    """
    Parse Metadata/slice_info.config from a Bambu Studio .3mf file.
    Returns {slot_index: total_grams} where total_grams = used_g + flush_weight.
    - used_g      : plastic deposited (model + wipe tower for this filament)
    - flush_weight: purge/colour-change waste
    Both are consumed from the physical spool.
    """
    slot_weights: dict[int, float] = {}
    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            config_path = next(
                (n for n in names if n.lower().endswith("slice_info.config")), None
            )
            if config_path is None:
                logger.log_error(f"Slicer: slice_info.config not found in {path}")
                return {}

            with z.open(config_path) as f:
                root = ET.parse(f).getroot()

            for plate in root.findall("plate"):
                for fil in plate.findall("filament"):
                    slot_id = int(fil.get("id", 0))
                    used_g = float(fil.get("used_g", 0))
                    flush_g = float(fil.get("flush_weight", 0))
                    if slot_id > 0:
                        slot_weights[slot_id] = used_g + flush_g

    except zipfile.BadZipFile:
        logger.log_error(f"Slicer: {path} is not a valid zip/3mf file")
    except Exception as e:
        logger.log_error(f"Slicer: failed to parse {path}: {e}")

    return slot_weights


def _process_file(path: str):
    logger.log_info(f"Slicer: processing {os.path.basename(path)}")
    slot_weights = parse_3mf(path)

    if slot_weights:
        with _lock:
            _pending_slot_weights.clear()
            _pending_slot_weights.update(slot_weights)
        logger.log_info(f"Slicer: slot weights stored {slot_weights}")
    else:
        logger.log_error(f"Slicer: no filament data found in {os.path.basename(path)}")

    # Move to processed/ regardless so it won't be picked up again
    os.makedirs(DONE_DIR, exist_ok=True)
    dest = os.path.join(DONE_DIR, os.path.basename(path))
    # Avoid name collision
    if os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(DONE_DIR, f"{base}_{int(time.time())}{ext}")
    shutil.move(path, dest)
    logger.log_info(f"Slicer: moved to {dest}")


def _watch_loop():
    os.makedirs(WATCH_DIR, exist_ok=True)
    logger.log_info(f"Slicer watcher started, watching '{WATCH_DIR}' every {POLL_INTERVAL}s")
    while True:
        try:
            for fname in os.listdir(WATCH_DIR):
                if fname.lower().endswith(".3mf"):
                    full_path = os.path.join(WATCH_DIR, fname)
                    if os.path.isfile(full_path):
                        _process_file(full_path)
        except Exception as e:
            logger.log_error(f"Slicer watcher error: {e}")
        time.sleep(POLL_INTERVAL)


def start_thread():
    threading.Thread(target=_watch_loop, daemon=True).start()
