#!/usr/bin/env python3
"""qnxprobe GUI: a tkinter window over qnxprobe.py.

Standard library only, like the tool it drives, so it installs nothing. The
window has two halves:

  Report / Extract   runs qnxprobe.py as a subprocess with the same options the
                     command line takes, streams the report into the window as
                     it is printed, and reads the --progress JSON stream on
                     stderr to drive the progress bar. The report is byte for
                     byte what the command line prints.

  Contents           opens the image read-only in this process, finds each
                     volume through qnxprobe.volumes(), the callable form of
                     the report's own discovery, and browses it through the
                     same walker classes the extractor uses. Directories load
                     when expanded, and one file at a time can be saved out.

The image is never written to. Both halves open it "rb".

    python3 qnxprobe_gui.py                    open the window
    python3 qnxprobe_gui.py image.img ...      open it with these images added
    python3 qnxprobe_gui.py --check-discovery image.img ...
                                               no window: prove qnxprobe.volumes(),
                                               which the Contents pane and the
                                               LEAPP tools read images through,
                                               names the same volumes the report does
    python3 qnxprobe_gui.py --cli ...          run qnxprobe's own command line;
                                               this is how the window starts
                                               the tool, and it is what makes a
                                               single frozen executable work
"""

import os
import sys
import json
import queue
import threading
import subprocess
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qnxprobe as q                                   # noqa: E402



def probe_command():
    """How to start the command line tool as a subprocess.

    Frozen into one executable (PyInstaller) there is no qnxprobe.py beside us
    and sys.executable is this program, so the window re-enters itself with
    --cli, which runs qnxprobe's own command line entry point in that process.
    The unfrozen case takes the same route so it is the path that gets tested.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli"]
    return [sys.executable, os.path.abspath(__file__), "--cli"]


def run_cli(argv):
    """Run qnxprobe.py's command line with these arguments, in this process."""
    sys.argv = ["qnxprobe.py"] + list(argv)
    runpy.run_module("qnxprobe", run_name="__main__", alter_sys=False)
def check_discovery(paths):
    """Prove qnxprobe.volumes() names what main() reports. Returns exit status.

    Parses the report main() prints for the two lines that name a volume and
    its kind, and requires the discovered set to equal it. A brute-scan-only
    report has no walkable volume, and discovery correctly returns nothing.
    """
    import io
    import re
    import contextlib
    bad = 0
    for path in paths:
        with q.open_image(path) as fh:
            size = q.image_size(fh)
            found = {(v["label"], v["kind"]) for v in q.volumes(fh, size)
                     if v["kind"] != "extended container"}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            q.main(path)
        reported = set()
        for line in buf.getvalue().splitlines():
            m = re.match(r"  CONFIRMED qnx6 filesystem on (.+?)  \[", line)
            if m and m.group(1) != "image start":
                # main() probes offset 0 under the label "image start" as well as
                # under whatever region starts there, so a whole-disk qnx6 is
                # reported twice. Only the region-labelled copy has a base to
                # walk, so only that one can be in the discovered set.
                reported.add((m.group(1), "qnx6"))
            m = re.match(r"    (\S.*?)   \S+ [KMGT]?i?B?\s+->  (.+)$", line)
            if m and "extended partition container" not in m.group(2):
                reported.add((m.group(1), m.group(2).strip()))
        ok = found == reported
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {path}  {len(found)} volume(s)")
        if not ok:
            for item in sorted(reported - found):
                print(f"       reported, not discovered: {item}")
            for item in sorted(found - reported):
                print(f"       discovered, not reported: {item}")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def run_window(initial_paths):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    root.title(f"qnxprobe {q.QNXPROBE_VERSION}")
    root.geometry("1100x760")
    root.minsize(820, 560)

    state = dict(proc=None, fh=None, volumes=[], nodes={}, image_path=None)

    # ---- top: images ------------------------------------------------------
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Images").grid(row=0, column=0, sticky="nw")
    images = tk.Listbox(top, height=4, selectmode="extended", exportselection=False)
    images.grid(row=0, column=1, sticky="ew", padx=(6, 6))
    top.columnconfigure(1, weight=1)
    btns = ttk.Frame(top)
    btns.grid(row=0, column=2, sticky="n")

    def add_images():
        for p in filedialog.askopenfilenames(title="Disk image, partition image or raw dump"):
            p = os.path.normpath(os.path.abspath(p))
            if p not in images.get(0, "end"):
                images.insert("end", p)
        refresh_image_combo()

    def remove_images():
        for i in reversed(images.curselection()):
            images.delete(i)
        refresh_image_combo()

    ttk.Button(btns, text="Add...", command=add_images).pack(fill="x")
    ttk.Button(btns, text="Remove", command=remove_images).pack(fill="x", pady=(4, 0))

    # ---- options ----------------------------------------------------------
    opts = ttk.LabelFrame(root, text="Options (same as the command line)", padding=8)
    opts.pack(fill="x", padx=8)
    v_list = tk.BooleanVar(value=False)
    v_triage = tk.BooleanVar(value=False)
    v_depth = tk.StringVar(value="2")
    v_max = tk.StringVar(value="400")
    v_scan = tk.StringVar(value="256")
    v_only = tk.StringVar(value="")
    v_exclude = tk.StringVar(value="")
    v_zip = tk.StringVar(value="")

    ttk.Checkbutton(opts, text="--list contents", variable=v_list).grid(row=0, column=0, sticky="w")
    ttk.Label(opts, text="--depth").grid(row=0, column=1, sticky="e")
    ttk.Entry(opts, textvariable=v_depth, width=5).grid(row=0, column=2, sticky="w")
    ttk.Label(opts, text="--list-max").grid(row=0, column=3, sticky="e")
    ttk.Entry(opts, textvariable=v_max, width=7).grid(row=0, column=4, sticky="w")
    ttk.Checkbutton(opts, text="--triage", variable=v_triage).grid(row=0, column=5, sticky="w", padx=(12, 0))
    ttk.Label(opts, text="--scan-limit MiB").grid(row=0, column=6, sticky="e", padx=(12, 0))
    ttk.Entry(opts, textvariable=v_scan, width=6).grid(row=0, column=7, sticky="w")

    ttk.Label(opts, text="--only").grid(row=1, column=0, sticky="e", pady=(6, 0))
    ttk.Entry(opts, textvariable=v_only, width=24).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Label(opts, text="--exclude (comma separated)").grid(row=1, column=3, columnspan=2, sticky="e", pady=(6, 0))
    ttk.Entry(opts, textvariable=v_exclude, width=36).grid(row=1, column=5, columnspan=3, sticky="ew", pady=(6, 0))

    ttk.Label(opts, text="--extract OUT.zip").grid(row=2, column=0, sticky="e", pady=(6, 0))
    ttk.Entry(opts, textvariable=v_zip).grid(row=2, column=1, columnspan=6, sticky="ew", pady=(6, 0))

    def pick_zip():
        p = filedialog.asksaveasfilename(title="Extraction zip", defaultextension=".zip",
                                         filetypes=[("zip", "*.zip")], confirmoverwrite=False)
        if p:
            v_zip.set(p)

    ttk.Button(opts, text="Choose...", command=pick_zip).grid(row=2, column=7, sticky="w", pady=(6, 0), padx=(6, 0))
    for c in (1, 5, 6):
        opts.columnconfigure(c, weight=1)

    # ---- actions ----------------------------------------------------------
    act = ttk.Frame(root, padding=(8, 6))
    act.pack(fill="x")
    b_report = ttk.Button(act, text="Run report")
    b_extract = ttk.Button(act, text="Extract to zip")
    b_cancel = ttk.Button(act, text="Cancel", state="disabled")
    b_report.pack(side="left")
    b_extract.pack(side="left", padx=(6, 0))
    b_cancel.pack(side="left", padx=(6, 0))
    progress = ttk.Progressbar(act, mode="determinate", length=260)
    progress.pack(side="right")
    status = ttk.Label(act, text="ready", anchor="e")
    status.pack(side="right", padx=(0, 10), fill="x", expand=True)

    # ---- notebook ---------------------------------------------------------
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    rep = ttk.Frame(nb)
    nb.add(rep, text="Report")
    mono = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10) if sys.platform == "win32" else ("DejaVu Sans Mono", 10)
    text = tk.Text(rep, wrap="none", font=mono)
    ys = ttk.Scrollbar(rep, orient="vertical", command=text.yview)
    xs = ttk.Scrollbar(rep, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set, state="disabled")
    text.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    rep.rowconfigure(0, weight=1)
    rep.columnconfigure(0, weight=1)

    con = ttk.Frame(nb)
    nb.add(con, text="Contents")
    cbar = ttk.Frame(con, padding=(0, 6))
    cbar.pack(fill="x")
    ttk.Label(cbar, text="Image").pack(side="left")
    combo = ttk.Combobox(cbar, state="readonly", width=60)
    combo.pack(side="left", padx=6, fill="x", expand=True)
    b_load = ttk.Button(cbar, text="Load contents")
    b_load.pack(side="left")
    b_save = ttk.Button(cbar, text="Save selected file...", state="disabled")
    b_save.pack(side="left", padx=(6, 0))

    # Created and Accessed fill where the walker keeps instants for them, which
    # is NTFS through stamps(); every other reader carries only the modified
    # time, so those two stay blank there rather than show a date nothing read.
    # A FAT32 or exFAT walker keeps readings rather than instants, so for it
    # the three (UTC) columns stay blank and the readings go in the last column
    # as stored, the way GLEAPP's gallery shows the same file.
    tree = ttk.Treeview(con, columns=("kind", "size", "mtime", "created", "accessed", "recorded"),
                        selectmode="browse")
    tree.heading("#0", text="Name")
    tree.heading("kind", text="Kind")
    tree.heading("size", text="Size")
    tree.heading("mtime", text="Modified (UTC)")
    tree.heading("created", text="Created (UTC)")
    tree.heading("accessed", text="Accessed (UTC)")
    tree.heading("recorded", text="Recorded (as stored)")
    tree.column("#0", width=520, stretch=True)
    tree.column("kind", width=110, stretch=False)
    tree.column("size", width=110, anchor="e", stretch=False)
    tree.column("mtime", width=170, stretch=False)
    tree.column("created", width=110, stretch=False)
    tree.column("accessed", width=110, stretch=False)
    tree.column("recorded", width=420, stretch=False)
    tys = ttk.Scrollbar(con, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tys.set)
    tree.pack(side="left", fill="both", expand=True)
    tys.pack(side="right", fill="y")

    def refresh_image_combo():
        vals = list(images.get(0, "end"))
        combo["values"] = vals
        if vals and combo.get() not in vals:
            combo.set(vals[0])
        if not vals:
            combo.set("")

    def append_text(s):
        text.configure(state="normal")
        text.insert("end", s)
        text.see("end")
        text.configure(state="disabled")

    def clear_text():
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.configure(state="disabled")

    # ---- subprocess driver ------------------------------------------------
    q_out = queue.Queue()
    q_con = queue.Queue()

    def build_args(extract):
        paths = list(images.get(0, "end"))
        if not paths:
            messagebox.showinfo("qnxprobe", "Add at least one image first.")
            return None
        args = probe_command() + ["--progress"]
        try:
            args += ["--scan-limit", str(int(v_scan.get()))]
            if v_list.get():
                args += ["--list", "--depth", str(int(v_depth.get())),
                         "--list-max", str(int(v_max.get()))]
        except ValueError:
            messagebox.showerror("qnxprobe", "depth, list-max and scan-limit must be whole numbers.")
            return None
        if v_triage.get():
            args.append("--triage")
        if v_only.get().strip():
            args += ["--only", v_only.get().strip()]
        for x in v_exclude.get().split(","):
            if x.strip():
                args += ["--exclude", x.strip()]
        if extract:
            zp = v_zip.get().strip()
            if not zp:
                messagebox.showinfo("qnxprobe", "Choose where the extraction zip goes.")
                return None
            if os.path.exists(zp):
                messagebox.showerror("qnxprobe", f"Refusing to overwrite an existing file:\n{zp}")
                return None
            args += ["--extract", zp]
        return args + paths

    def pump(stream, tag):
        for line in iter(stream.readline, b""):
            q_out.put((tag, line.decode("utf-8", "replace")))
        q_out.put((tag, None))

    def start(extract):
        args = build_args(extract)
        if args is None:
            return
        clear_text()
        shown = ["qnxprobe.py"] + args[args.index("--cli") + 1:]
        append_text("$ " + " ".join(a if " " not in a else f'"{a}"' for a in shown) + "\n\n")
        progress["value"] = 0
        status["text"] = "running..."
        for b in (b_report, b_extract):
            b["state"] = "disabled"
        b_cancel["state"] = "normal"
        try:
            state["proc"] = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            messagebox.showerror("qnxprobe", f"could not start qnxprobe.py: {exc}")
            finish()
            return
        state["open_streams"] = 2
        threading.Thread(target=pump, args=(state["proc"].stdout, "out"), daemon=True).start()
        threading.Thread(target=pump, args=(state["proc"].stderr, "err"), daemon=True).start()
        root.after(50, poll)

    def poll():
        try:
            while True:
                tag, line = q_out.get_nowait()
                if line is None:
                    state["open_streams"] -= 1
                    continue
                if tag == "out":
                    append_text(line)
                else:
                    try:
                        j = json.loads(line)
                        tb = j.get("total_bytes") or 0
                        if tb:
                            progress["value"] = 100.0 * j.get("bytes", 0) / tb
                        status["text"] = (f"{j.get('volume', '')}: {j.get('files', 0):,} of "
                                          f"{j.get('total_files', 0):,} files, "
                                          f"{q.human(j.get('bytes', 0))} of {q.human(tb)}")
                    except ValueError:
                        append_text(line)                # stderr that is not progress
        except queue.Empty:
            pass
        p = state["proc"]
        if p is not None and (p.poll() is None or state["open_streams"] > 0):
            root.after(50, poll)
            return
        rc = p.returncode if p is not None else None
        finish(rc)

    def finish(rc=None):
        for b in (b_report, b_extract):
            b["state"] = "normal"
        b_cancel["state"] = "disabled"
        if rc == 0:
            progress["value"] = 100
            status["text"] = "done"
        elif rc is None:
            status["text"] = "not started"
        elif rc < 0:
            status["text"] = "cancelled"
        else:
            status["text"] = f"qnxprobe.py exited {rc}"
        state["proc"] = None

    def cancel():
        p = state["proc"]
        if p is not None and p.poll() is None:
            p.terminate()
            append_text("\n[cancelled; a partial zip, if any, is not a complete extraction]\n")

    b_report.configure(command=lambda: start(False))
    b_extract.configure(command=lambda: start(True))
    b_cancel.configure(command=cancel)

    # ---- contents pane ----------------------------------------------------
    def close_image():
        if state["fh"] is not None:
            try:
                state["fh"].close()
            except OSError:
                pass
        state.update(fh=None, volumes=[], nodes={}, image_path=None)
        tree.delete(*tree.get_children())
        b_save["state"] = "disabled"

    def load_contents():
        path = combo.get()
        if not path:
            messagebox.showinfo("qnxprobe", "Add an image and pick it in the list.")
            return
        close_image()
        b_load["state"] = "disabled"
        status["text"] = f"reading {os.path.basename(path)} ..."

        def work():
            # Tk is not thread safe, so the worker only reads; the result is
            # picked up by poll_contents() on the main thread.
            try:
                fh = q.open_image(path)          # one file, or a split set joined
                q_con.put(("ok", path, fh, q.volumes(fh, q.image_size(fh))))
            except Exception as exc:
                q_con.put(("err", path, None, str(exc)))
        threading.Thread(target=work, daemon=True).start()
        root.after(50, poll_contents)

    def poll_contents():
        try:
            kind, path, fh, payload = q_con.get_nowait()
        except queue.Empty:
            root.after(50, poll_contents)
            return
        if kind == "ok":
            show_volumes(path, fh, payload)
        else:
            messagebox.showerror("qnxprobe", f"could not read {path}:\n{payload}")
            done_loading()

    def done_loading():
        b_load["state"] = "normal"
        status["text"] = "ready"

    def show_volumes(path, fh, vols):
        state.update(fh=fh, volumes=vols, image_path=path)
        for i, v in enumerate(vols):
            label = f"{v['label']}   {v['kind']}   ({v['name']})" if v["name"] else f"{v['label']}   {v['kind']}"
            if v.get("walker") is not None and v.get("note"):
                label += f"   [{v['note']}]"     # a walked volume that cannot be read here
            iid = tree.insert("", "end", text=label,
                              values=("volume", q.human(v["size"]), v.get("detail", "")[:60], "", "", ""),
                              open=False)
            w = v.get("walker")
            if w is not None:
                state["nodes"][iid] = (i, w.root, True, None)
                tree.insert(iid, "end", text="loading...", values=("", "", "", "", "", ""))
            else:
                tree.insert(iid, "end", text=v.get("note", "no contents"), values=("", "", "", "", "", ""))
        done_loading()
        if not vols:
            status["text"] = "no partition or volume found in this image"

    def expand(_event=None):
        iid = tree.focus()
        node = state["nodes"].get(iid)
        if node is None or not node[2]:
            return
        kids = tree.get_children(iid)
        if not (len(kids) == 1 and tree.item(kids[0], "text") == "loading..."):
            return
        tree.delete(*kids)
        vi, ino, _isdir, _ = node
        w = state["volumes"][vi]["walker"]
        try:
            readings = hasattr(w, "listdir_records")
            entries = list(w.listdir_records(ino)) if readings \
                else [(name, cino, None) for name, cino in w.listdir(ino)]
        except Exception as exc:
            tree.insert(iid, "end", text=f"could not list: {exc}", values=("", "", "", "", "", ""))
            return
        for name, cino, recorded in entries:
            ent = w.entry(cino)
            if not ent:
                continue
            mode, size, mtime = ent
            isdir = (mode & 0o170000) == q.S_IFDIR     # a block device shares the S_IFDIR bit
            islink = (mode & q.S_IFLNK) == q.S_IFLNK
            isreg = (mode & 0o170000) == 0o100000
            kind = "dir" if isdir else "link" if islink else "file" if isreg else "special"
            created = accessed = 0
            if hasattr(w, "stamps"):
                created, _modified, accessed = w.stamps(cino)
            cid = tree.insert(iid, "end", text=name,
                              values=(kind, "" if isdir else q.human(size),
                                      "" if readings else q._fmt_time(mtime),
                                      q._fmt_time(created) if created else "",
                                      q._fmt_time(accessed) if accessed else "",
                                      "; ".join(f"{k} {v}" for k, v in (recorded or {}).items() if v)))
            state["nodes"][cid] = (vi, cino, isdir, size if isreg else None)
            if isdir:
                tree.insert(cid, "end", text="loading...", values=("", "", "", "", "", ""))

    def selected(_event=None):
        node = state["nodes"].get(tree.focus())
        b_save["state"] = "normal" if node and not node[2] and node[3] is not None else "disabled"

    def save_file():
        iid = tree.focus()
        node = state["nodes"].get(iid)
        if not node or node[2] or node[3] is None:
            return
        vi, ino, _d, size = node
        w = state["volumes"][vi]["walker"]
        out = filedialog.asksaveasfilename(title="Save file as", initialfile=tree.item(iid, "text"))
        if not out:
            return
        try:
            n = 0
            with open(out, "wb") as f:
                for chunk in w.read_file(ino, size):
                    f.write(chunk)
                    n += len(chunk)
            status["text"] = f"saved {n:,} bytes to {out}"
            if n != size:
                messagebox.showwarning("qnxprobe", f"wrote {n:,} bytes but the entry records {size:,}")
        except Exception as exc:
            messagebox.showerror("qnxprobe", f"could not save: {exc}")

    tree.bind("<<TreeviewOpen>>", expand)
    tree.bind("<<TreeviewSelect>>", selected)
    tree.bind("<Double-1>", lambda e: save_file() if b_save["state"] == "normal" else None)
    b_load.configure(command=load_contents)
    b_save.configure(command=save_file)

    def on_close():
        cancel()
        close_image()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # Absolute from the start: the subprocess and the frozen build's re-entry
    # must not depend on whatever the working directory happens to be.
    for p in initial_paths:
        if os.path.exists(p):
            images.insert("end", os.path.abspath(p))
    refresh_image_combo()
    root.mainloop()


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--cli":
        run_cli(argv[1:])
        sys.exit(0)
    if argv and argv[0] == "--check-discovery":
        paths = argv[1:]
        missing = [p for p in paths if not os.path.exists(p)]
        if not paths or missing:
            sys.exit("usage: qnxprobe_gui.py --check-discovery IMAGE [IMAGE ...]"
                     + (f"\nnot found: {', '.join(missing)}" if missing else ""))
        sys.exit(check_discovery(paths))
    run_window(argv)
