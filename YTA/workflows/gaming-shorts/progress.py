"""Local, monotonic timing and throttled progress; no optional dependencies."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

CURRENT = None


def timestamp():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec='seconds')


def duration_text(seconds):
    if seconds is None:
        return 'Calculating...'
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


class Stage:
    def __init__(self, name, total=None, unit='items', category=None, clock=time.perf_counter,
                 emit=print, interval=2., recorder=None):
        self.name, self.total, self.unit = name, total, unit
        self.category = category or name
        self.clock, self.emit, self.interval = clock, emit, interval
        self.recorder = recorder
        self.started = clock()
        self.cpu_started = time.process_time()
        self.details = {}
        self.started_at = timestamp()
        self.done = 0.
        self.last = -float('inf')
        self.finished = False

    def snapshot(self):
        elapsed = max(0., self.clock()-self.started)
        speed = self.done/elapsed if elapsed > 0 and self.done > 0 else None
        percent = 100*min(1., self.done/self.total) if self.total else None
        eta = max(0., self.total-self.done)/speed if self.total and speed and elapsed >= 1 else None
        cpu = max(0., time.process_time()-self.cpu_started)
        return dict(name=self.name, category=self.category, started_at=self.started_at,
                    elapsed_seconds=elapsed, processed=self.done, total=self.total, unit=self.unit,
                    percent=percent, speed_per_second=speed, eta_seconds=eta,
                    python_cpu_seconds=cpu, python_cpu_percent_one_core=100*cpu/elapsed if elapsed else None,
                    logical_cpu_count=os.cpu_count(), details=self.details)

    def update(self, done=None, force=False):
        if done is not None:
            self.done = max(self.done, min(done, self.total) if self.total else done)
        now = self.clock()
        if not force and now-self.last < self.interval:
            return
        self.last = now
        s = self.snapshot()
        amount = f'{s["percent"]:.0f}%' if s['percent'] is not None else 'Calculating...'
        count = f'{self.done:.1f}/{self.total:g} {self.unit}' if self.total else f'{self.done:g} {self.unit}'
        speed = f'{s["speed_per_second"]:.2f} {self.unit}/s' if s['speed_per_second'] else 'Calculating...'
        self.emit(f'{self.name} | {amount} | {count} | elapsed {duration_text(s["elapsed_seconds"])}'
                  f' | speed {speed} | ETA {duration_text(s["eta_seconds"])}', flush=True)

    def __enter__(self):
        self.emit(f'{self.name} | started {self.started_at}', flush=True)
        self.update(force=True)
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None and self.total:
            self.done = self.total
        self.update(force=True)
        result = self.snapshot()
        result['status'] = 'complete' if kind is None else ('interrupted' if issubclass(kind, KeyboardInterrupt) else 'failed')
        self.emit(f'{self.name} | {result["status"]} | actual {result["elapsed_seconds"]:.3f}s', flush=True)
        self.finished = True
        if self.recorder:
            self.recorder.stages.append(result)


def stage(name, total=None, unit='items', category=None):
    return Stage(name, total, unit, category, recorder=CURRENT)


def peak_memory():
    """Python-process high water mark. Child FFmpeg memory is not included."""
    try:
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged',
                                                      'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL('psapi', use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.peak
        else:
            import resource
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(value if sys.platform == 'darwin' else value*1024)
    except (ImportError, OSError, AttributeError):
        pass
    return None


def child_cpu_seconds(process):
    """CPU used by this finished encoder on Windows, while its process handle is open."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        values=[wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        if kernel.GetProcessTimes(wintypes.HANDLE(int(process._handle)),*[ctypes.byref(v) for v in values]):
            return sum((v.dwHighDateTime<<32)+v.dwLowDateTime for v in values[2:])/1e7
    except (OSError,AttributeError,TypeError,ValueError):
        pass
    return None


class Session:
    def __init__(self, directory, resume=False, clock=time.perf_counter):
        self.directory, self.clock = Path(directory), clock
        self.started, self.started_at = clock(), timestamp()
        self.stages, self.counts, self.cache_hits = [], {}, []
        self.resume = resume
        self.ended = None
        self.counts = {'rendered_this_invocation': 0, 'candidates': 0}
        path = self.directory/'metrics.json'
        self.history = json.loads(path.read_text(encoding='utf-8')).get('runs', []) if path.exists() else []

    def snapshot(self, status='running'):
        totals = {}
        for item in self.stages:
            totals[item['category']] = totals.get(item['category'], 0.)+item['elapsed_seconds']
        renders = [s['elapsed_seconds'] for s in self.stages if s['category']=='Rendering' and s['status']=='complete']
        return dict(started_at=self.started_at, status=status, resume=self.resume,
                    wall_seconds=max(0., (self.ended if self.ended is not None else self.clock())-self.started), stage_seconds=totals,
                    accumulated_stage_seconds=sum(totals.values()), stages=self.stages,
                    counts=self.counts, cache_hits=self.cache_hits,
                    render_seconds=dict(average=sum(renders)/len(renders) if renders else None,
                                        fastest=min(renders) if renders else None, slowest=max(renders) if renders else None),
                    python_peak_memory_bytes=peak_memory(),
                    memory_scope='Python process lifetime high water mark; excludes FFmpeg/FFprobe children')

    def document(self, status='running'):
        current = self.snapshot(status)
        runs = self.history+[current]
        return dict(schema_version=1, current_run=current, runs=runs,
                    cumulative_wall_seconds=sum(r['wall_seconds'] for r in runs),
                    timing_note='Wall time includes overhead. Stage totals may overlap when stages are nested. Historical runs exclude idle time.')

    def save(self, status='running'):
        document = self.document(status)
        pending = self.directory/'metrics.json.tmp'
        pending.write_text(json.dumps(document, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        pending.replace(self.directory/'metrics.json')
        return document

    def summary(self, status):
        current = self.save(status)['current_run']
        print('\nStage | Actual seconds', flush=True)
        for name, seconds in current['stage_seconds'].items():
            print(f'{name} | {seconds:.3f}', flush=True)
        print(f'Total wall-clock time | {current["wall_seconds"]:.3f}', flush=True)
        print('Counts: '+json.dumps(self.counts), flush=True)
        print('Render seconds: '+json.dumps(current['render_seconds']), flush=True)
        print('Cache/skips: '+(', '.join(self.cache_hits) or 'none'), flush=True)
        print(f'Python peak memory bytes: {current["python_peak_memory_bytes"]} (children excluded)', flush=True)


@contextmanager
def session(recorder):
    global CURRENT
    previous, CURRENT = CURRENT, recorder
    try:
        yield recorder
    finally:
        CURRENT = previous


def checked_output(command, label, category='Verification'):
    """Heartbeat for operations with no meaningful percentage; reap on interrupt."""
    with stage(label, category=category) as meter, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        process = subprocess.Popen(command, stdout=output, stderr=error)
        try:
            while True:
                try:
                    code = process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    meter.update()
            output.seek(0); error.seek(0)
            result = output.read()
            if code:
                raise RuntimeError(error.read()[-3000:].decode('utf-8', 'replace'))
            return result
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def decode_check(executable, path, duration):
    """FFmpeg's measured output time supplies progress for a complete decode."""
    command = [executable, '-v', 'error', '-xerror', '-nostdin', '-progress', 'pipe:1',
               '-i', str(path), '-f', 'null', '-']
    with stage('Output verification: full decode', duration, 'seconds', 'Verification') as meter, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True)
        try:
            for line in process.stdout:
                if line.startswith('out_time_us='):
                    try:
                        meter.update(float(line.split('=', 1)[1])/1e6)
                    except ValueError:
                        pass
            if process.wait():
                errors.seek(0)
                raise RuntimeError(errors.read()[-3000:].decode('utf-8', 'replace'))
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()
