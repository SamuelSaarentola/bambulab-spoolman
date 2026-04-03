import json
import os
import Spoolman.spoolman_filament as spoolman_filament
from helper_logs import logger
from SlicerIntegration.slicer_watcher import get_pending_slot_weights, clear_pending_slot_weights

class PrintTask:
  def __init__(self):
      self.model_name = None
      self.task_id = None
      self.job_id = None
      self.ams_mapping = None
      self.total_weight = 0
      self.start_time = None
      self.end_time = None
      self.teoric_filaments = None
      self.reported_filament = None
      self.init_percent = 0
      self.percent_complete = 0
      self.status = None
      self.image_cover_url = None

  def to_dict(self):
      """Convert the PrintTask object to a dictionary."""
      return {
          "model_name": self.model_name,
          "task_id": self.task_id,
          "job_id": self.job_id,
          "total_weight": self.total_weight,
          "start_time": self.start_time,
          "end_time": self.end_time,
          "teoric_filaments": self.teoric_filaments,
          "reported_filament": self.reported_filament,
          "init_percent": self.init_percent,
          "percent_complete": self.percent_complete,
          "status": self.status,
          "image_cover_url": self.image_cover_url
      }
      
  def CleanTask(self):
      """Clean the task object."""
      self.model_name = None
      self.task_id = None
      self.job_id = None
      self.total_weight = 0
      self.start_time = None
      self.end_time = None
      self.teoric_filaments = None
      self.reported_filament = None
      self.init_percent = 0
      self.percent_complete = 0
      self.status = None
      self.image_cover_url = None
      
  def ReportAndSaveTask(self, ams_slot_filament_ids: dict = {}):
      """Save the task to a task.txt file as a JSON object.

      Priority:
      1. Slicer data (3mf watcher) + AMS slot mapping from MQTT → per-colour tracking
      2. Bambu Cloud teoric_filaments → material-level tracking (fallback)
      """
      file_name = "task.txt"
      if self.percent_complete != 0:
          if self.percent_complete == 100:
              logger.log_info("Complete task")
              multiplier = 1.0
          else:
              logger.log_error("Incomplete task")
              try:
                  multiplier = (self.percent_complete - self.init_percent) / (100 - self.init_percent)
              except Exception:
                  multiplier = 1.0
                  logger.log_error("Error calculating multiplier, defaulting to 1")
              logger.log_info(f"Using multiplier: {multiplier}")

          slicer_slot_weights = get_pending_slot_weights()

          if slicer_slot_weights and ams_slot_filament_ids:
              # Per-colour tracking from 3mf + AMS MQTT slot mapping
              logger.log_info("Using slicer 3mf data for per-colour filament reporting")
              self.reported_filament = []
              for slot_index, planned_weight in slicer_slot_weights.items():
                  filament_id = ams_slot_filament_ids.get(slot_index)
                  if not filament_id:
                      logger.log_error(f"No filament_id for slot {slot_index}, skipping")
                      continue
                  actual_weight = multiplier * planned_weight
                  saved = spoolman_filament.RegisterFilament(filament_id, actual_weight)
                  if saved:
                      self.reported_filament.append({
                          "slot": slot_index,
                          "filamentId": filament_id,
                          "weight": actual_weight
                      })
              clear_pending_slot_weights()

          elif self.teoric_filaments:
              # Fallback: cloud-based material-level tracking
              logger.log_info("Using Bambu Cloud data for filament reporting (no slicer data)")
              self.reported_filament = []
              for filament in self.teoric_filaments:
                  filament["weight"] = multiplier * filament["weight"]
                  saved_filament = spoolman_filament.RegisterFilament(filament["filamentId"], filament["weight"])
                  if saved_filament:
                      self.reported_filament.append(filament)
          else:
              logger.log_error("No filament data available (no slicer 3mf and no cloud data)")
      
      # Load existing tasks if the file exists
      if os.path.exists(file_name):
          with open(file_name, "r") as file:
              try:
                  tasks = json.load(file)
              except json.JSONDecodeError:
                  # If the file is corrupted or empty, start with an empty list
                  tasks = []
      else:
          tasks = []
      
      # Append the current task
      tasks.append(self.to_dict())
      
      # Save back to the file
      with open(file_name, "w") as file:
          json.dump(tasks, file, indent=4)
      
      logger.log_info(f"Task saved successfully to {file_name}.")