"""Background jobs for the pipeline: every wait longer than a blink runs as a job, so the user always
sees a progress bar (panel + status bar) and Blender never looks hung.

A job is a chain of steps: command-line programs (polled, output parsed for % / [n/N]) and Python
steps. A Python step may be a generator: it runs in slices of SLICE seconds on the main thread and
yields its progress (0-1, or (0-1, "what it is doing")), so Blender redraws between slices.
One job runs at a time; Cancel stops the generator / kills the whole process tree."""
import inspect
import os
import queue
import re
import subprocess
import sys
import threading
import time

import bpy

PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
FRACTION = re.compile(r"\[(\d+)\s*/\s*(\d+)\]")      # COLMAP: "Processed file [12/112]"
SLICE = 0.1             # seconds of Python work per timer tick
_job = None


class Step:
    """argv: a command (list), or a Python callable taking the job (main thread). A callable that
    returns a generator runs in slices; each yield gives the progress of the step."""

    def __init__(self, label, argv, cwd=None, env=None, weight=1.0, ok_codes=(0,)):
        self.label, self.argv, self.cwd, self.env, self.weight, self.ok_codes = label, argv, cwd, env, weight, ok_codes


class Job:
    def __init__(self, name, steps, on_done=None, log_path=None, on_line=None):
        self.name, self.steps, self.on_done, self.log_path, self.on_line = name, steps, on_done, log_path, on_line
        self.index = -1
        self.state = "idle"            # running / done / failed / cancelled
        self.error = ""
        self.step_pct = 0.0
        self.lines = []
        self.started = time.time()
        self.proc = None
        self._q = queue.Queue()
        self._log = None
        self._call = None              # Python step waiting for the next tick
        self._gen = None               # generator of the running Python step
        self.detail = ""               # what the Python step is doing now
        self.data = {}                 # scratch space for the steps

    # -- progress
    @property
    def percent(self):
        total = sum(s.weight for s in self.steps) or 1
        done = sum(s.weight for s in self.steps[:max(self.index, 0)])
        cur = self.steps[self.index].weight * self.step_pct / 100 if 0 <= self.index < len(self.steps) else 0
        return min(100.0, 100.0 * (done + cur) / total) if self.state == "running" else (
            100.0 if self.state == "done" else 0.0)

    @property
    def stage(self):
        return self.steps[self.index].label if 0 <= self.index < len(self.steps) else ""

    def log(self, line):
        self.lines.append(line)
        del self.lines[:-300]
        if self._log:
            self._log.write(line + "\n")
            self._log.flush()

    # -- running
    def _next(self):
        self.index += 1
        self.step_pct = 0.0
        self.detail = ""
        if self.index >= len(self.steps):
            self._end("done")
            return
        st = self.steps[self.index]
        self.log(f"=== {st.label}")
        if callable(st.argv):
            self._call = st             # runs on the next tick, after the panel shows the stage
            return
        # "{key}" arguments are filled from job.data, set by the steps before (e.g. the chosen model)
        argv = [str(a).format(**self.data) if str(a).startswith("{") else str(a) for a in st.argv]
        self.log("> " + " ".join(f'"{a}"' if " " in a else a for a in argv))
        env = dict(os.environ)
        env.update(st.env or {})
        try:
            self.proc = subprocess.Popen(
                argv, cwd=st.cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.error = f"{st.label}: could not start {argv[0]} ({e})"
            self.log("ERROR " + self.error)
            self._end("failed")
            return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        for line in proc.stdout:
            self._q.put(line.rstrip("\r\n"))
        self._q.put(None)

    def _python(self):
        """Run the current Python step for at most SLICE seconds."""
        st = self.steps[self.index]
        t0 = time.time()
        try:
            if self._gen is None:
                self._call = None
                r = st.argv(self)
                if not inspect.isgenerator(r):
                    self._next()
                    return self.state == "running"
                self._gen = r
            while time.time() - t0 < SLICE:
                v = next(self._gen)
                if isinstance(v, tuple):
                    v, self.detail = v
                if v is not None:
                    self.step_pct = max(0.0, min(100.0, 100.0 * float(v)))
        except StopIteration:
            self._gen = None
            self._next()
        except Exception as e:
            self._gen = None
            self.error = f"{st.label}: {e}"
            self.log("ERROR " + self.error)
            self._end("failed")
        return self.state == "running"

    def poll(self):
        """Advance the Python step, or read new output and move on when the process ended.
        Returns True while running."""
        if self.state != "running":
            return False
        if self._call is not None or self._gen is not None:
            return self._python()
        if self.proc is None:
            return self.state == "running"
        while True:
            try:
                line = self._q.get_nowait()
            except queue.Empty:
                break
            if line is None:            # output closed: wait for the exit code
                code = self.proc.wait()
                self.proc = None
                st = self.steps[self.index]
                if code not in st.ok_codes:
                    self.error = f"{st.label} failed (exit code {code})"
                    self.log("ERROR " + self.error)
                    self._end("failed")
                    return False
                self._next()
                return self.state == "running"
            for part in line.split("\r"):
                if not part.strip():
                    continue
                self.log(part)
                m = PERCENT.findall(part)
                f = FRACTION.findall(part)
                if m:
                    self.step_pct = max(0.0, min(100.0, float(m[-1])))
                elif f and int(f[-1][1]):
                    self.step_pct = min(100.0, 100.0 * int(f[-1][0]) / int(f[-1][1]))
                if self.on_line:
                    try:
                        self.on_line(self, part)
                    except Exception:
                        pass
        return True

    def cancel(self):
        if self.proc is not None:
            kill_tree(self.proc)
            self.proc = None
        if self._gen is not None:
            self._gen.close()
            self._gen = None
        self._call = None
        self.error = "cancelled"
        self._end("cancelled")

    def _end(self, state):
        self.state = state
        self.log(f"=== {self.name}: {state}" + (f" ({self.error})" if self.error and state != "cancelled" else "")
                 + f", {time.time() - self.started:.0f} s")
        if self._log:
            self._log.close()
            self._log = None


def kill_tree(proc):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.kill()


def current():
    return _job


def busy():
    return _job is not None and _job.state == "running"


def start(job):
    """Run job in the background. Refuses while another job runs."""
    global _job
    if busy():
        raise RuntimeError(f"'{_job.name}' is still running")
    _job = job
    if job.log_path:
        os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
        job._log = open(job.log_path, "a", encoding="utf-8")
    job.state = "running"
    job.started = time.time()
    job.log(f"=== {job.name} started {time.strftime('%Y-%m-%d %H:%M:%S')}")
    job._next()
    if job.state == "running":
        bpy.app.timers.register(_tick, first_interval=0.25)
    else:
        _finish(job)
    return job


def cancel():
    if busy():
        _job.cancel()
        _finish(_job)


def label(job):
    """'Build Scene · Cameras · IMG_3240 · 62%'."""
    return " · ".join(p for p in (job.name, job.stage, job.detail, f"{job.percent:.0f}%") if p)


def _redraw():
    """Repaint the sidebar and put the progress in the status bar (seen even with the sidebar closed)."""
    job = _job
    text = label(job) + "   (Cancel in the Scan Pipeline panel)" if job and job.state == "running" else None
    for win in bpy.context.window_manager.windows if bpy.context.window_manager else []:
        try:
            win.workspace.status_text_set(text)
        except (AttributeError, RuntimeError):
            pass
        for area in win.screen.areas:
            if area.type in ("VIEW_3D", "STATUSBAR"):
                area.tag_redraw()


def run_or_start(job):
    """Start in the background (UI), or run to the end (background mode / tests)."""
    return run_blocking(job) if bpy.app.background else start(job)


def ui_override():
    """Context for operators called from a job tick (timers have no window): the first window
    with a 3D view."""
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region)
    return bpy.context.temp_override()


ON_FINISH = []          # called with every finished job (e.g. the step status refresh)


def _finish(job):
    if job.on_done:
        try:
            job.on_done(job)
        except Exception as e:
            job.log(f"ERROR in on_done: {e}")
            job.error = job.error or str(e)
            job.state = "failed" if job.state == "done" else job.state
    for f in ON_FINISH:
        try:
            f(job)
        except Exception as e:
            job.log(f"ERROR in ON_FINISH: {e}")
    _redraw()


def _tick():
    job = _job
    if job is None or job.state != "running":
        return None
    try:
        running = job.poll()
    except Exception as e:
        job.error = str(e)
        job._end("failed")
        running = False
    _redraw()
    if not running:
        _finish(job)
        return None
    return 0.01 if job._call is not None or job._gen is not None else 0.5


def run_blocking(job, timeout=None):
    """Run a job to the end without timers (background mode / tests)."""
    global _job
    _job = job
    if job.log_path:
        os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
        job._log = open(job.log_path, "a", encoding="utf-8")
    job.state = "running"
    job._next()
    t0 = time.time()
    while job.poll():
        if job._call is None and job._gen is None:
            time.sleep(0.2)
        if timeout and time.time() - t0 > timeout:
            job.cancel()
    _finish(job)
    return job


def draw_progress(layout):
    """Progress bar + stage + Cancel for the running job, or the last result line."""
    job = _job
    if job is None:
        return
    if job.state == "running":
        row = layout.row(align=True)
        row.progress(factor=job.percent / 100.0, text=label(job))
        row.operator("livinglacquer.pipe_cancel_job", text="", icon="CANCEL")
        if job.proc is not None and job.lines:
            layout.label(text=job.lines[-1][:90])
    elif job.state in ("failed", "cancelled"):
        layout.label(text=f"{job.name}: {job.error or job.state}", icon="ERROR")


class LIVINGLACQUER_OT_PipeCancelJob(bpy.types.Operator):
    """Stop the running pipeline job (the process and everything it started)"""
    bl_idname = "livinglacquer.pipe_cancel_job"
    bl_label = "Cancel"

    def execute(self, context):
        cancel()
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeShowLog(bpy.types.Operator):
    """Open the log of the last pipeline job in a text editor block"""
    bl_idname = "livinglacquer.pipe_show_log"
    bl_label = "Show Log"

    def execute(self, context):
        if _job is None:
            return {"CANCELLED"}
        txt = bpy.data.texts.get("LivingLacquer Log") or bpy.data.texts.new("LivingLacquer Log")
        txt.clear()
        txt.write("\n".join(_job.lines))
        self.report({"INFO"}, "Log written to the text block 'LivingLacquer Log' (Text Editor)")
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeCancelJob, LIVINGLACQUER_OT_PipeShowLog)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    if busy():
        _job.cancel()
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
