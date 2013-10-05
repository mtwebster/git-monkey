#!/usr/bin/env python

import sys
import os
from subprocess import Popen, PIPE, STDOUT
import subprocess
import git
from gi.repository import Gdk, Gtk, GObject, GLib, Pango
GObject.threads_init()
home = os.path.expanduser("~")

STATE_NONE = -1
STATE_BUILDING = 1
STATE_REBASING = 2
STATE_BUILT = 3
STATE_REBASED = 4
STATE_CLEANED = 5
STATE_RESET = 6
STATE_BUILD_QUEUED = 7
STATE_REBASE_QUEUED = 8
STATE_CLEANING = 9
STATE_RESETTING = 10

JOB_BUILD = 1
JOB_REBASE = 2
JOB_RESET = 3
JOB_CLEAN = 4

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

    def clean(self):
        self.repo.state = STATE_CLEANING
        cmd = "git clean -fdx"
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def reset(self):
        self.repo.state = STATE_RESETTING
        cmd = "git reset --hard"
        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def rebase(self):
        self.repo.state = STATE_REBASING
        cmd = "git pull --rebase %s %s" % (self.repo.upstream_remote, self.repo.upstream_branch)

        self.process = subprocess.Popen(cmd, cwd=self.repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

    def build(self):
        self.repo.state = STATE_BUILDING
        self.process = subprocess.Popen("dpkg-buildpackage -j$((    $(cat /proc/cpuinfo | grep processor | wc -l)+1    ))", shell=True, cwd=self.repo.dir, stdout = subprocess.PIPE, stderr = STDOUT)
        GLib.io_add_watch(self.process.stdout,
                          GLib.IO_IN,
                          self.output_callback)

class JobManager:
    def __init__(self):
        self.jobs = []
        self.busy = False
        self.current_job = None
        GObject.timeout_add(500, self.process_next_job)

    def add_job(self, job):
        self.jobs.append(job)

    def get_job_from_stack(self):
        job = get_first(self.jobs)
        if job:
            self.jobs.remove(job)
        return job

    def process_next_job(self):
        print "process"
        if self.busy:
            self.current_job.process.poll()
            if self.current_job.process.returncode is None:
                return True
            else:
                self.busy = False
                GObject.idle_add(self.current_job.finished_callback, self.current_job)
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
        self.builder.add_from_file("/home/mtwebster/bin/git-monkey/usr/lib/git-monkey/git-monkey.glade")
        # self.builder.add_from_file("/usr/lib/git-monkey/git-monkey.glade")
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

        self.busy = False
        self.job_manager = JobManager()

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
        self.treeview = Gtk.TreeView()
        self.builder.connect_signals(self)
        column = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), markup=1)
        column.set_min_width(250)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Current Branch", Gtk.CellRendererText(), markup=2)
        column.set_min_width(250)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Default Upstream", Gtk.CellRendererText(), markup=4)
        self.treeview.append_column(column)
        column = Gtk.TreeViewColumn("Status", Gtk.CellRendererText(), markup=3)
        column.set_max_width(100)
        self.treeview.append_column(column)
        cell = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Activity", cell)
        column.set_cell_data_func(cell, self.activity_func)
        self.treeview.append_column(column)

        self.model = Gtk.TreeStore(object, str, str, str, str)
        self.combo_model = Gtk.ListStore(str, str)

        self.current_repo = None

        self.parse_dirs()

        self.treeview.set_model(self.model)
        self.branch_combo.set_model(self.combo_model)
        cell = Gtk.CellRendererText()
        self.branch_combo.pack_start(cell, True)
        self.branch_combo.add_attribute(cell, "text", 0)

        self.treebox.add(self.treeview)
        self.treeview.get_selection().connect("changed", lambda x: self.selection_changed());
        self.window.show_all()

    def activity_func(self, column, cell, model, iter, data=None):
        repo = model.get_value(iter, 0)

        if repo.state == STATE_NONE:
            cell.set_property("text", "")
        elif repo.state == STATE_BUILD_QUEUED:
            cell.set_property("text", "Build Queued")
        elif repo.state == STATE_BUILDING:
            cell.set_property("text", "Building...")
        elif repo.state == STATE_REBASING:
            cell.set_property("text", "Rebasing...")
        elif repo.state == STATE_BUILT:
            cell.set_property("text", "Build finished")
        elif repo.state == STATE_REBASED:
            cell.set_property("text", "Rebased")
        elif repo.state == STATE_CLEANED:
            cell.set_property("text", "Cleaned")
        elif repo.state == STATE_RESET:
            cell.set_property("text", "Reset")
        elif repo.state == STATE_REBASE_QUEUED:
            cell.set_property("text", "Rebase Queued")

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

    def update_repos(self):
        row_iter = self.model.get_iter_first()
        while row_iter != None:
            repo = self.model.get_value(row_iter, 0)
            self.model.set_value(row_iter, 2, repo.head.reference.name)
            self.model.set_value(row_iter, 3, self.grab_repo_status(repo))
            row_iter = self.model.iter_next(row_iter)

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

    def selection_changed(self):
        model, treeiter = self.treeview.get_selection().get_selected()
        if treeiter:
            repo = self.model.get_value(treeiter, 0)
            self.current_repo = repo
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
            self.clean_button.set_sensitive(len(repo.untracked_files) != 0)
            self.reset_button.set_sensitive(repo.is_dirty())
            self.term_button.set_sensitive(True)
            self.full_build_button.set_sensitive(True)
            self.new_branch.set_sensitive(True)
            self.rebase_button.set_sensitive(True)

    def on_branch_combo_changed (self, widget):
        tree_iter = widget.get_active_iter()
        if tree_iter != None:
            new_branch = self.combo_model[tree_iter][1]
            try:
                self.current_repo.git.checkout(new_branch)
                self.current_repo.state = STATE_NONE
            except git.exc.GitCommandError, detail:
                self.inform_error("Could not change branches - you probably have uncommitted changes", str(detail))
            self.parse_dirs()

    def on_refresh_clicked(self, button):
        self.parse_dirs()

    def on_clean_clicked(self, button):
        self.current_repo.state = STATE_CLEANING
        job = Job(self.current_repo, JOB_CLEAN, self.write_to_buffer, self.job_finished_callback)
        self.job_manager.add_job(job)

    def on_reset_clicked(self, button):
        self.current_repo.state = STATE_RESETTING
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

    def on_terminal_clicked(self, button):
        subprocess.Popen("gnome-terminal", cwd=self.current_repo.dir, shell=True)

    def on_new_branch_clicked(self,button):
        new_branch = self.ask_new_branch_name("Enter a name for your new branch:")
        if new_branch is not None:
            cmd = "git checkout -b %s" % (new_branch)
            process = subprocess.Popen(cmd, cwd=self.current_repo.dir, stdout=subprocess.PIPE, stderr=STDOUT, shell=True)
            GLib.io_add_watch(process.stdout,
                              GLib.IO_IN,
                              self.write_to_buffer )
        self.update_repos()

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
        if job.type == JOB_RESET:
            job.repo.state = STATE_RESET
        elif job.type == JOB_CLEAN:
            job.repo.state = STATE_CLEANED
        elif job.type == JOB_REBASE:
            job.repo.state = STATE_REBASED
        elif job.type == JOB_BUILD:
            job.repo.state = STATE_BUILT
        self.update_repos()
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
        if response == Gtk.ResponseType.OK and valid and raw_str != "":
            return raw_str
        elif not valid:
            self.inform_error("Invalid branch name - no spaces allowed", "")
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

if __name__ == "__main__":
    Main()
    GObject.threads_init()
    Gtk.main()
