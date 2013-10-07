#!/usr/bin/env python

import os
import signal
from subprocess import STDOUT
import subprocess
import git
from gi.repository import Gdk, Gtk, GObject, GLib, Pango, GdkPixbuf, Gio
GObject.threads_init()
home = os.path.expanduser("~")

SCHEMA = "com.linuxmint.git-monkey"

BUILD_KEY = "build-command"

if False:
    BUILDER_FILE = "/usr/lib/git-monkey/git-monkey.glade"
else:
    BUILDER_FILE = "/home/mtwebster/bin/git-monkey/usr/lib/git-monkey/git-monkey.glade"

STATE_NONE = -1

STATE_BUILDING = 2
STATE_REBASING = 3
STATE_CLEANING = 4
STATE_RESETTING = 5
STATE_NEW_BRANCH_IN_PROGRESS = 6
STATE_PULL_REQUEST_IN_PROGRESS = 7

STATE_NEW_BRANCH_QUEUED = 8
STATE_CLEAN_QUEUED = 9
STATE_RESET_QUEUED = 10
STATE_BUILD_QUEUED = 11
STATE_REBASE_QUEUED = 12
STATE_PULL_REQUEST_QUEUED = 13

STATE_NEW_BRANCH_DONE = 14
STATE_RESETTED = 15
STATE_BUILT = 16
STATE_REBASED = 17
STATE_CLEANED = 18
STATE_PULL_REQUEST_CHECKED_OUT = 19

JOB_BUILD = 1
JOB_REBASE = 2
JOB_RESET = 3
JOB_CLEAN = 4
JOB_NEW_BRANCH = 5
JOB_CHECKOUT_PR = 6

def get_first(iterable, default=None):
    if iterable:
        for item in iterable:
            return item
    return default

class GitRepo(git.Repo):
    def __init__(self, dir, upstream_remote, upstream_branch):
        git.Repo.__init__(self, dir)
        self.can_make = False
        self.name = os.path.split(dir)[1]
        self.dir = dir
        self.upstream_remote = upstream_remote
        self.upstream_branch = upstream_branch
        self.state = STATE_NONE

class Job:
    def __init__(self, repo, job_type, output_callback, finished_callback):
        self.repo = repo
        self.type = job_type
        self.output_callback = output_callback
        self.finished_callback = finished_callback
        self.process = None
        self.new_branch_name = ""
        self.aborted = False

    def clean(self):
        self.repo.state = STATE_CLEANING
        cmd = "git clean -fdx"
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def reset(self):
        self.repo.state = STATE_RESETTING
        cmd = "git reset --hard"
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def rebase(self):
        self.repo.state = STATE_REBASING
        cmd = "git pull --rebase %s %s" % (self.repo.upstream_remote, self.repo.upstream_branch)

        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def build(self):
        self.repo.state = STATE_BUILDING
        self.process = subprocess.Popen("dpkg-buildpackage -j$((    $(cat /proc/cpuinfo | grep processor | wc -l)+1    ))", shell=True, cwd=self.repo.dir, stdout = subprocess.PIPE, stderr = STDOUT, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def new_branch(self):
        self.repo.state = STATE_NEW_BRANCH_IN_PROGRESS
        cmd = "git checkout -b %s" % (self.new_branch_name)
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)
        self.new_branch_name = ""

    def pull_request(self):
        self.repo.state = STATE_PULL_REQUEST_IN_PROGRESS
        cmd = "git fetch %s refs/pull/%s/head:%s && git checkout %s" % (self.repo.upstream_remote, self.new_branch_name, self.new_branch_name, self.new_branch_name)
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True, preexec_fn=os.setsid)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)
        self.new_branch_name = ""

class JobManager:
    def __init__(self, model):
        self.jobs = []
        self.busy = False
        self.current_job = None
        self.model = model
        GObject.timeout_add(500, self.process_next_job)

    def find_and_abort(self, repo):
        if self.current_job != None:
            if self.current_job.repo == repo:
                if self.current_job.process:
                    os.killpg(self.current_job.process.pid, signal.SIGTERM)
                    self.current_job.aborted = True
        to_remove = []
        for job in self.jobs:
            if job.repo == repo:
                to_remove.append(job)
        for rem in to_remove:
            rem.aborted = True
            self.jobs.remove(rem)
        repo.state = STATE_NONE

    def add_job(self, job):
        self.jobs.append(job)

    def get_job_from_stack(self):
        job = get_first(self.jobs)
        if job:
            self.jobs.remove(job)
        return job

    def model_signal_update(self, model, path, row_iter, data):
        self.model.row_changed(path, row_iter)

    def process_next_job(self):
        self.model.foreach(self.model_signal_update, None)
        if self.busy:
            self.current_job.process.poll()
            if self.current_job.process.returncode is None:
                return True
            else:
                self.busy = False
                GObject.idle_add(self.current_job.finished_callback, self.current_job)
                self.current_job = None
        job = self.get_job_from_stack()
        if job:
            self.current_job = job
            self.do_job_work(job)
        return True

    def do_job_work(self, job):
        self.busy = True
        if job.type == JOB_CLEAN:
            job.clean()
        elif job.type == JOB_RESET:
            job.reset()
        elif job.type == JOB_REBASE:
            job.rebase()
        elif job.type == JOB_BUILD:
            job.build()
        elif job.type == JOB_NEW_BRANCH:
            job.new_branch()
        elif job.type == JOB_CHECKOUT_PR:
            job.pull_request()

class Main:
    def __init__(self):
        self.config_path = os.path.join(home, ".git-monkey")
        if os.path.exists(self.config_path):
            self.start()
        else:
            self.end()

    def end(self):
        print """
              git-monkey: a simple repo manager for debian-based projects.

              To use, you need file in your home folder called ".git-monkey".

              Within it, you put entries like this:

              /home/mtwebster/bin/cinnamon, mint, master
              /home/mtwebster/bin/cinnamon-session, origin, master

              That is, 

              <path-to-git-project>   ,  <upstream remote name>  ,  <upstream tracking branch>

              There's a sample that has the current cinnamon stack in /usr/lib/git-monkey - 
              copy to your home, change the folder names, and rename to .git-monkey

              """
        quit()

    def start(self):
        self.builder = Gtk.Builder()
        self.builder.add_from_file(BUILDER_FILE)
        self.treebox = self.builder.get_object("treebox")
        self.window = self.builder.get_object("window")
        self.clean_button = self.builder.get_object("clean")
        self.reset_button = self.builder.get_object("reset")
        self.rebase_button = self.builder.get_object("rebase")
        self.term_button = self.builder.get_object("terminal")
        self.full_build_button = self.builder.get_object("build")
        self.output_scroller = self.builder.get_object("scroller")
        self.output = self.builder.get_object("output_view")
        self.new_branch = self.builder.get_object("new_branch")
        self.pull_request_button = self.builder.get_object("pull_request")
        self.master_button = self.builder.get_object("master")
        self.prefs_dialog = self.builder.get_object("prefs_dialog")

        self.treeview = Gtk.TreeView()
        self.model = Gtk.TreeStore(object, str, str, str, str, GdkPixbuf.Pixbuf)
        self.combo_model = Gtk.ListStore(str, str)

        self.busy = False
        self.job_manager = JobManager(self.model)

        color = Gdk.RGBA()
        Gdk.RGBA.parse(color, "black")
        self.output.override_background_color(Gtk.StateFlags.NORMAL, color)
        Gdk.RGBA.parse(color, "#00CC00")

        fontdesc = Pango.FontDescription("monospace")
        self.output.override_font(fontdesc)

        self.output.override_color(Gtk.StateFlags.NORMAL, color)
        self.window.connect("destroy", Gtk.main_quit)
        self.branch_combo = self.builder.get_object("branch_combo")
        self.branch_combo_changed_id = self.branch_combo.connect ("changed", self.on_branch_combo_changed)

        self.builder.connect_signals(self)

        cell = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("Abort", cell)
        column.set_cell_data_func(cell, self.abort_func)
        column.set_max_width(50)
        self.treeview.append_column(column)

        column = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), markup=1)
        column.set_min_width(200)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Current Branch", Gtk.CellRendererText(), markup=2)
        column.set_min_width(200)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Default Upstream", Gtk.CellRendererText(), markup=4)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Status", Gtk.CellRendererText(), markup=3)
        column.set_min_width(200)
        self.treeview.append_column(column)
        cell = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Activity", cell)
        column.set_cell_data_func(cell, self.activity_func)
        self.treeview.append_column(column)
        self.current_repo = None

        self.parse_dirs()

        self.treeview.set_model(self.model)
        self.branch_combo.set_model(self.combo_model)
        cell = Gtk.CellRendererText()
        self.branch_combo.pack_start(cell, True)
        self.branch_combo.add_attribute(cell, "text", 0)

        self.treebox.add(self.treeview)
        self.treeview.get_selection().connect("changed", lambda x: self.selection_changed());
        self.treeview.connect('button_press_event', self.on_button_press_event)

        self.setup_prefs()

        self.window.show_all()

    def activity_func(self, column, cell, model, iter, data=None):
        repo = model.get_value(iter, 0)

        if repo.state == STATE_NONE:
            cell.set_property("text", "")

        elif repo.state == STATE_BUILD_QUEUED:
            cell.set_property("text", "Build queued")
        elif repo.state == STATE_BUILDING:
            cell.set_property("text", "Building...")
        elif repo.state == STATE_BUILT:
            cell.set_property("text", "Build finished")

        elif repo.state == STATE_REBASE_QUEUED:
            cell.set_property("text", "Rebase queued")
        elif repo.state == STATE_REBASING:
            cell.set_property("text", "Rebasing...")
        elif repo.state == STATE_REBASED:
            cell.set_property("text", "Rebased")

        elif repo.state == STATE_CLEAN_QUEUED:
            cell.set_property("text", "Clean queued")
        elif repo.state == STATE_CLEANING:
            cell.set_property("text", "Cleaning...")
        elif repo.state == STATE_CLEANED:
            cell.set_property("text", "Cleaned")

        elif repo.state == STATE_RESET_QUEUED:
            cell.set_property("text", "Reset queued")
        elif repo.state == STATE_RESETTING:
            cell.set_property("text", "Resetting...")
        elif repo.state == STATE_RESETTED:
            cell.set_property("text", "Reset finished")

        elif repo.state == STATE_NEW_BRANCH_QUEUED:
            cell.set_property("text", "New branch queued")
        elif repo.state == STATE_NEW_BRANCH_IN_PROGRESS:
            cell.set_property("text", "Making new branch...")
        elif repo.state == STATE_NEW_BRANCH_DONE:
            cell.set_property("text", "New branch made")

        elif repo.state == STATE_PULL_REQUEST_QUEUED:
            cell.set_property("text", "Pull request checkout queued")
        elif repo.state == STATE_PULL_REQUEST_IN_PROGRESS:
            cell.set_property("text", "Checking out pull request...")
        elif repo.state == STATE_PULL_REQUEST_CHECKED_OUT:
            cell.set_property("text", "Pull request checked out")

    def abort_func(self, column, cell, model, iter, data=None):
        repo = model.get_value(iter, 0)
        if repo.state == STATE_NONE or repo.state >= STATE_NEW_BRANCH_DONE:
            cell.set_property("stock-id", "")
        else:
            cell.set_property("stock-id", "gtk-no")

    def on_button_press_event(self, widget, event):
        if event.button == 1:
            data=widget.get_path_at_pos(int(event.x),int(event.y))
            if data:
                path, column, x, y = data
                if column.get_property('title')=="Abort":
                    iter = self.model.get_iter(path)
                    repo = self.model.get_value(iter, 0)
                    self.job_manager.find_and_abort(repo)

    def parse_dirs(self):
        self.model.clear()
        file = open(self.config_path)
        raw = file.read()
        lines = raw.split("\n")
        file.close()
        for line in lines:
            try:
                d, remote, remote_branch = line.replace(" ", "").split(",")
                if not os.path.exists(d):
                    continue
                repo = GitRepo(d, remote, remote_branch)

                iter = self.model.insert_before(None, None)
                self.model.set_value(iter, 0, repo)
                self.model.set_value(iter, 1, repo.name)
                self.model.set_value(iter, 2, repo.head.reference.name)
                self.model.set_value(iter, 3, self.grab_repo_status(repo))
                us_string = "%s/%s" % (repo.upstream_remote, repo.upstream_branch)
                self.model.set_value(iter, 4, us_string)
            except ValueError:
                pass
        self.clean_button.set_sensitive(False)
        self.reset_button.set_sensitive(False)
        self.term_button.set_sensitive(False)
        self.new_branch.set_sensitive(False)
        self.rebase_button.set_sensitive(False)
        self.pull_request_button.set_sensitive(False)

    def update_repos(self):
        row_iter = self.model.get_iter_first()
        while row_iter != None:
            repo = self.model.get_value(row_iter, 0)
            self.model.set_value(row_iter, 2, repo.head.reference.name)
            self.model.set_value(row_iter, 3, self.grab_repo_status(repo))
            row_iter = self.model.iter_next(row_iter)
        self.clean_button.set_sensitive(len(self.current_repo.untracked_files) != 0)
        self.reset_button.set_sensitive(self.current_repo.is_dirty())
        self.master_button.set_sensitive(self.current_repo.head.reference.name != self.current_repo.upstream_branch)


    def grab_repo_status(self, repo):
        untracked = len(repo.untracked_files) != 0
        dirty = repo.is_dirty()
        if not untracked and not dirty:
            return "<b><span color='#01DF01'>Clean</span></b>"
        elif untracked and dirty:
            return "<b><span color='#DF0101'>Uncommitted | Untracked</span></b>"
        elif untracked and not dirty:
            return "<b><span color='#DF0101'>Untracked</span></b>"
        elif dirty and not untracked:
            return "<b><span color='#DF0101'>Uncommitted</span></b>"

    def update_branch_combo(self, repo):
        self.combo_model.clear()
        current_iter = None
        for head in repo.heads:
            iter = self.combo_model.insert_before(None, None)
            self.combo_model.set_value(iter, 0, head.name)
            self.combo_model.set_value(iter, 1, head.name)
            if repo.head.reference.name == head.name:
                current_iter = iter
        if current_iter is not None:
            self.branch_combo.handler_block(self.branch_combo_changed_id)
            self.branch_combo.set_active_iter(current_iter)
            self.branch_combo.handler_unblock(self.branch_combo_changed_id)

    def selection_changed(self):
        model, treeiter = self.treeview.get_selection().get_selected()
        if treeiter:
            repo = self.model.get_value(treeiter, 0)
            self.current_repo = repo
            self.update_branch_combo(repo)
            self.clean_button.set_sensitive(len(repo.untracked_files) != 0)
            self.reset_button.set_sensitive(repo.is_dirty())
            self.term_button.set_sensitive(True)
            self.full_build_button.set_sensitive(True)
            self.new_branch.set_sensitive(True)
            self.rebase_button.set_sensitive(True)
            self.pull_request_button.set_sensitive(True)
            self.master_button.set_sensitive(repo.head.reference.name != repo.upstream_branch)

    def on_branch_combo_changed (self, widget):
        tree_iter = widget.get_active_iter()
        if tree_iter != None:
            new_branch = self.combo_model[tree_iter][1]
            try:
                self.current_repo.git.checkout(new_branch)
                self.current_repo.state = STATE_NONE
            except git.exc.GitCommandError, detail:
                self.inform_error("Could not change branches - you probably have uncommitted changes", str(detail))
            self.update_repos()

    def on_refresh_clicked(self, button):
        self.parse_dirs()

    def on_clean_clicked(self, button):
        self.current_repo.state = STATE_CLEAN_QUEUED
        job = Job(self.current_repo, JOB_CLEAN, self.write_to_buffer, self.job_finished_callback)
        self.job_manager.add_job(job)

    def on_reset_clicked(self, button):
        self.current_repo.state = STATE_RESET_QUEUED
        job = Job(self.current_repo, JOB_RESET, self.write_to_buffer, self.job_finished_callback)
        self.job_manager.add_job(job)

    def on_rebase_clicked(self, button):
        self.current_repo.state = STATE_REBASE_QUEUED
        job = Job(self.current_repo, JOB_REBASE, self.write_to_buffer, self.job_finished_callback)
        self.job_manager.add_job(job)

    def on_build_clicked(self, button):
        self.current_repo.state = STATE_BUILD_QUEUED
        job = Job(self.current_repo, JOB_BUILD, self.write_to_buffer, self.job_finished_callback)
        self.job_manager.add_job(job)

    def on_new_branch_clicked(self, button):
        new_branch = self.ask_new_branch_name("Enter a name for your new branch:")
        if new_branch is not None:
            self.current_repo.state = STATE_NEW_BRANCH_QUEUED
            job = Job(self.current_repo, JOB_NEW_BRANCH, self.write_to_buffer, self.job_finished_callback)
            job.new_branch_name = new_branch
            self.job_manager.add_job(job)

    def on_pull_request_clicked(self, button):
        model, treeiter = self.treeview.get_selection().get_selected()
        if treeiter:
            name = self.model.get_value(treeiter, 1)
        number = self.ask_pull_request_number("Enter the pull request number to checkout for <b>%s</b>" % (name))
        if number is not None:
            self.current_repo_state = STATE_PULL_REQUEST_QUEUED
            job = Job(self.current_repo, JOB_CHECKOUT_PR, self.write_to_buffer, self.job_finished_callback)
            job.new_branch_name = number
            self.job_manager.add_job(job)

    def on_terminal_clicked(self, button):
        subprocess.Popen("gnome-terminal", cwd=self.current_repo.dir, shell=True)

    def on_master_clicked(self, button):
        try:
            self.current_repo.git.checkout(self.current_repo.upstream_branch)
            self.current_repo.state = STATE_NONE
        except git.exc.GitCommandError, detail:
            self.inform_error("Could not change branches - you probably have uncommitted changes", str(detail))
        self.update_repos()
        self.update_branch_combo(self.current_repo)

    def on_build_all_clicked(self, button):
        row_iter = self.model.get_iter_first()
        while row_iter != None:
            self.current_repo = self.model.get_value(row_iter, 0)
            self.on_build_clicked(None)
            row_iter = self.model.iter_next(row_iter)

    def on_rebase_all_clicked(self, button):
        row_iter = self.model.get_iter_first()
        while row_iter != None:
            self.current_repo = self.model.get_value(row_iter, 0)
            self.on_rebase_clicked(None)
            row_iter = self.model.iter_next(row_iter)

    def on_clean_reset_all_clicked(self, button):
        row_iter = self.model.get_iter_first()
        while row_iter != None:
            self.current_repo = self.model.get_value(row_iter, 0)
            self.on_reset_clicked(None)
            self.on_clean_clicked(None)
            row_iter = self.model.iter_next(row_iter)

    def on_prefs_button_clicked(self, button):
        self.prefs_dialog.present()

    def write_to_buffer(self, fd, condition):
        if condition == GLib.IO_IN:
            char = fd.readline()
            buf = self.output.get_buffer()
            iter = buf.get_end_iter()
            buf.insert(iter, char)
            iter = buf.get_end_iter()
            self.output.scroll_to_iter(iter, .2, False, 0, 0)
            # adj = self.output.get_vadjustment()
            # if adj.get_value() >= adj.get_upper() - adj.get_page_size() - 200.0:
            # adj.set_value(adj.get_upper())
            return True
        else:
            return False

    def job_finished_callback(self, job):
        if not job.aborted:
            if job.type == JOB_RESET:
                job.repo.state = STATE_RESETTED
            elif job.type == JOB_CLEAN:
                job.repo.state = STATE_CLEANED
            elif job.type == JOB_REBASE:
                job.repo.state = STATE_REBASED
            elif job.type == JOB_BUILD:
                job.repo.state = STATE_BUILT
            elif job.type == JOB_NEW_BRANCH:
                job.repo.state = STATE_NEW_BRANCH_DONE
            elif job.type == JOB_CHECKOUT_PR:
                job.repo.state = STATE_PULL_REQUEST_CHECKED_OUT
        self.update_repos()
        self.update_branch_combo(job.repo)
        return False

    def ask(self, msg):
        dialog = Gtk.MessageDialog(None,
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.YES_NO,
                                   None)
        dialog.set_default_size(400, 200)
        dialog.set_markup(msg)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def ask_new_branch_name(self, msg):
        dialog = Gtk.MessageDialog(None,
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.OK_CANCEL,
                                   None)
        dialog.set_default_size(400, 200)
        dialog.set_markup(msg)
        entry = Gtk.Entry()
        entry.set_placeholder_text("New branch name...")
        box = dialog.get_message_area()
        box.pack_start(entry, False, False, 3)
        dialog.show_all()
        response = dialog.run()
        raw_str = entry.get_text().strip()
        dialog.destroy()
        valid = " " not in raw_str
        if response == Gtk.ResponseType.OK:
            if valid and raw_str != "":
                return raw_str
            else:
                self.inform_error("Invalid branch name - no spaces allowed", "")
                return None
        else:
            return None

    def ask_pull_request_number(self, msg):
        dialog = Gtk.MessageDialog(None,
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.OK_CANCEL,
                                   None)
        dialog.set_default_size(400, 200)
        dialog.set_markup(msg)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Pull request number...")
        box = dialog.get_message_area()
        box.pack_start(entry, False, False, 3)
        dialog.show_all()
        response = dialog.run()
        raw_str = entry.get_text().strip()
        dialog.destroy()
        valid = " " not in raw_str
        try:
            value = int(raw_str)
        except ValueError:
            valid = False
        
        if response == Gtk.ResponseType.OK:
            if valid and raw_str != "":
                return raw_str
            else:
                self.inform_error("Invalid pull request number", "")
                return None
        else:
            return None


    def inform_error(self, msg, detail):
        dialog = Gtk.MessageDialog(None,
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.ERROR,
                                   Gtk.ButtonsType.OK,
                                   None)
        dialog.set_default_size(400, 200)
        dialog.set_markup(msg)
        dialog.format_secondary_markup(detail)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return

    def inform(self, msg, detail):
        dialog = Gtk.MessageDialog(None,
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.INFO,
                                   Gtk.ButtonsType.OK,
                                   None)
        dialog.set_default_size(400, 200)
        dialog.set_markup(msg)
        dialog.format_secondary_markup(detail)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return

    def on_prefs_close_clicked(self, button):
        self.prefs_dialog.hide()

    def setup_prefs(self):
        self.settings_build_entry = self.builder.get_object("settings_build_entry")
        self.settings = Gio.Settings.new(SCHEMA)
        self.settings.bind(BUILD_KEY, self.settings_build_entry, "text", Gio.Settings.BindFlags.DEFAULT)

if __name__ == "__main__":
    Main()
    GObject.threads_init()
    Gtk.main()
