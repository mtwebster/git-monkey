#!/usr/bin/env python

import git
from gi.repository import Gtk, Gio

SCHEMA = "com.linuxmint.git-monkey"

KEY_BUILD = "build-command"
KEY_REPOS = "repos"

if False:
    BUILDER_FILE = "/usr/lib/git-monkey/repo-edit.glade"
else:
    BUILDER_FILE = "/home/mtwebster/bin/git-monkey/usr/lib/git-monkey/repo-edit.glade"


class EditRepo:
    def __init__(self, dir = None, upstream_remote = None, upstream_branch = None):
        self.builder = Gtk.Builder()
        self.builder.add_from_file(BUILDER_FILE)

        self.window = self.builder.get_object("window")
        self.ok_button = self.builder.get_object("ok_button")
        self.cancel_button = self.builder.get_object("cancel_button")
        self.folder_button = self.builder.get_object("folder_button")
        self.us_remote_combo = self.builder.get_object("us_remote_combo")
        self.us_branch_combo = self.builder.get_object("us_branch_combo")

        self.remote_model = Gtk.ListStore(str)
        self.us_remote_combo.set_model(self.remote_model)
        cell = Gtk.CellRendererText()
        self.us_remote_combo.pack_start(cell, True)
        self.us_remote_combo.add_attribute(cell, "text", 0)

        self.branch_model = Gtk.ListStore(str)
        self.us_branch_combo.set_model(self.branch_model)
        cell = Gtk.CellRendererText()
        self.us_branch_combo.pack_start(cell, True)
        self.us_branch_combo.add_attribute(cell, "text", 0)

        self.builder.connect_signals(self)

        self.dir = dir
        self.upstream_remote = upstream_remote
        self.upstream_branch = upstream_branch
        self.repo = None

        if self.dir is not None:
            self.folder_button.set_label(self.dir)
            self.repo = git.Repo(self.dir)
            if self.upstream_remote is not None:
                self.setup_upstream_remote()
                if self.upstream_branch is not None:
                    self.setup_upstream_branch()
                    self.ok_button.set_sensitive(True)

        self.window.show_all()

    def on_folder_picked_callback(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            self.dir = dialog.get_filename()
            try:
                self.repo = git.Repo(self.dir)
                self.folder_button.set_label(self.dir)
                self.setup_upstream_remote()
            except Exception, detail:
                self.inform_error("Not a valid git folder!", str(detail))
        dialog.destroy()

    def on_folder_button_clicked(self, widget):
        dialog = Gtk.FileChooserDialog("Select git folder",
                                           self.window.get_toplevel(),
                                           Gtk.FileChooserAction.SELECT_FOLDER,
                                           (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        dialog.set_destroy_with_parent(True)

        dialog.connect("response", self.on_folder_picked_callback)

        dialog.show()

    def setup_upstream_remote(self):
        self.remote_model.clear()

        active_iter = None
        for remote in self.repo.remotes:
            iter = self.remote_model.insert_before(None, None)
            self.remote_model.set_value(iter, 0, remote.name)
            if self.upstream_remote is not None and remote.name == self.upstream_remote:
                active_iter = iter
        self.us_remote_combo.set_sensitive(True)
        if active_iter:
            self.us_remote_combo.set_active_iter(active_iter)

    def on_us_remote_combo_changed(self, widget):
        iter = widget.get_active_iter()
        if iter != None:
            self.upstream_remote = self.remote_model[iter][0]
            self.setup_upstream_branch()

    def setup_upstream_branch(self):
        self.branch_model.clear()

        active_iter = None
        remote = self.repo.remotes[self.upstream_remote]
        for branch in remote.refs:
            iter = self.branch_model.insert_before(None, None)
            name = branch.name.replace("%s/" % (self.upstream_remote), "")
            self.branch_model.set_value(iter, 0, name)
            if self.upstream_branch is not None and name == self.upstream_branch:
                active_iter = iter
        self.us_branch_combo.set_sensitive(True)
        if active_iter:
            self.us_branch_combo.set_active_iter(active_iter)

    def on_us_branch_combo_changed(self, widget):
        iter = widget.get_active_iter()
        if iter != None:
            self.upstream_branch = self.branch_model[iter][0]
            self.ok_button.set_sensitive(True)

    def on_ok_button_clicked(self, button):
        settings = Gio.Settings.new(SCHEMA)
        repo_list = settings.get_strv(KEY_REPOS)

        existing = False

        for item in repo_list:
            name, remote, branch = item.split(":")
            if name == self.dir:
                existing = True
                break
        if existing:
            repo_list.remove(item)
        out = "%s:%s:%s" % (self.dir, self.upstream_remote, self.upstream_branch)
        repo_list.append(out)
        settings.set_strv(KEY_REPOS, repo_list)
        self.window.destroy()

    def on_cancel_button_clicked(self, button):
        self.window.destroy()























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