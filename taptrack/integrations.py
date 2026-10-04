"""Sponsor integrations wired to the bridge: FinchNode record + write-back queue.
(Fetch.ai agent and Photon notifications run as separate processes; see agent/.)"""
import logging
import threading

from . import config, finchnode

log = logging.getLogger("taptrack.integrations")


def apply_patient(p: dict | None):
    """Use the FinchNode record for the displayed name and (if it has a levodopa order) the dose schedule."""
    if not p:
        return
    if p.get("name"):
        config.PATIENT_NAME = p["name"]
    if p.get("schedule_source", "").startswith("FinchNode"):
        config.DOSE_TIMES = p["dose_times"]


def register(bridge, store, publish):
    def load():
        p = finchnode.load_patient(store)
        apply_patient(p)
        if p:
            publish({"type": "patient", "patient": p})

    if config.FINCHNODE_ENABLED:
        apply_patient(store.get_setting("patient"))  # cached copy immediately
        threading.Thread(target=load, daemon=True, name="finchnode-load").start()

    def on_check(row):
        if row.get("score") is not None:
            finchnode.queue_writeback(store, row)

    bridge.listeners.append(on_check)
