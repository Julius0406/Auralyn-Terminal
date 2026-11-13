"""Exact GUI controller methods against EXPLICIT TEST DOUBLES, not a real GUI.

Covers stale results, button permissions, dialogs, double-clicks and the fact
that commands are never pasted into the current terminal. Real GUI tests are
separate, optional tests in test_gtk_smoke.py.
"""
import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import threading
import unittest
from unittest.mock import Mock

from auralyn_terminal.settings import DEFAULTS
from auralyn_terminal.web_sources import public_url, WebError
from auralyn_terminal.smart_catalog import ENTRIES, get_action
from auralyn_terminal.smart_search import Answer, from_entry, rejected
from auralyn_terminal.local_ai import valid_model_name, AIError
from test_ui_logic import Widget

ROOT=Path(__file__).resolve().parent.parent


class W(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sensitive=True
        self._entry=None
        self.texts=[]
        self.running=False
    @classmethod
    def new_from_icon_name(cls, *args): return cls()
    @classmethod
    def new_with_entry(cls, *args): return cls()
    @classmethod
    def new_with_label(cls, *args): return cls()
    def set_text(self, value):
        self.label=value
        for name,callback,args in self.signals:
            if name=='changed': callback(self, *args)
    def get_text(self): return self.label
    def set_label(self, value): self.label=value
    def set_sensitive(self, value): self.sensitive=value
    def get_sensitive(self): return self.sensitive
    def grab_focus(self): self.focused=True
    def set_visible(self, value): self.visible=value
    def get_child(self):
        if self._entry is None: self._entry=W()
        return self._entry
    def append_text(self, value): self.texts.append(value)
    def remove_all(self): self.texts=[]
    def set_active(self, index):
        self.active=index
        if self.texts and isinstance(index, int) and 0<=index<len(self.texts):
            self.get_child().set_text(self.texts[index])
    def popup(self): self.visible=True
    def popdown(self):
        self.visible=False
        for name,callback,args in self.signals:
            if name=='closed':callback(self, *args)
    def start(self): self.running=True
    def stop(self): self.running=False


class Dialog(W):
    @property
    def window(self): return None
    @window.setter
    def window(self, value): raise RuntimeError('field is not writable')


clipboard=Mock()
Gtk=NS(Popover=W, Dialog=Dialog, Box=W, Label=W, Entry=W, SearchEntry=W, Button=W,
       ScrolledWindow=W, Separator=W, Spinner=W, Switch=W, ComboBoxText=W, LinkButton=W,
       Align=NS(START=0,CENTER=1,END=2), Orientation=NS(VERTICAL=1),
       PopoverConstraint=NS(WINDOW=0), PositionType=NS(BOTTOM=0),
       PolicyType=NS(NEVER=0,AUTOMATIC=1), IconSize=NS(BUTTON=0), ReliefStyle=NS(NONE=0),
       ResponseType=NS(CLOSE=-7,OK=-5,CANCEL=-6),
       Clipboard=NS(get=lambda _:clipboard))
Gdk=NS(SELECTION_CLIPBOARD=0,KEY_Escape=65307)
Pango=NS(WrapMode=NS(WORD_CHAR=0))
GLib=NS(idle_add=lambda callback,*args: callback(*args))


def load_ui_class(name, extra=None):
    tree=ast.parse((ROOT/'auralyn_terminal/smart_ui.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='label']
    nodes += [n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name]
    worker=Mock()
    client=Mock()
    scope=dict(Gtk=Gtk,Gdk=Gdk,GLib=GLib,Pango=Pango,Path=Path,threading=threading,
               Answer=Answer, SearchWorker=Mock(return_value=worker),
               OllamaClient=Mock(return_value=client), valid_model_name=valid_model_name,
               AIError=AIError, ENTRIES=ENTRIES,get_action=get_action, public_url=public_url,
               WebError=WebError, read_web_key=Mock(return_value=""), save_web_key=Mock())
    scope.update(extra or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                 str(ROOT/'auralyn_terminal/smart_ui.py'),'exec'),scope)
    return scope[name],worker,client


def owner():
    page=NS(cwd='/tmp/original-folder',closed=False,terminal=Mock())
    return NS(settings=dict(DEFAULTS),current=Mock(return_value=page),
              get_allocated_width=Mock(return_value=1100),get_allocated_height=Mock(return_value=720),
              launch_smart_action=Mock(),open_settings=Mock(),open_ai_settings=Mock(),change_setting=Mock(),smart_popover=None)


class SmartPopoverControllerTests(unittest.TestCase):
    def setUp(self):
        Popover,self.worker,_=load_ui_class('SmartPopover')
        self.owner=owner();self.view=Popover(self.owner,W());self.view.open()
    def search(self, q='Wie viel RAM ist frei?', answer=None):
        self.view.entry.set_text(q);self.view._search()
        if answer is not None:self.view._receive(self.view._serial,answer)

    def test_open_does_not_search_or_execute(self):
        self.worker.submit.assert_not_called()
        self.owner.launch_smart_action.assert_not_called()
        self.assertFalse(self.view.execute_button.get_sensitive())
        self.assertEqual(self.view.mode_label.label,'OFFLINE')

    def test_search_only_submits_question_without_terminal_contents(self):
        self.search()
        self.worker.submit.assert_called_once_with(self.view._serial,'Wie viel RAM ist frei?',False,'qwen3:4b')
        self.owner.launch_smart_action.assert_not_called()
        self.owner.current().terminal.feed_child.assert_not_called()

    def test_enter_in_search_field_searches_not_executes(self):
        self.view.entry.set_text('Wie viel RAM ist frei?')
        for name, callback,args in self.view.entry.signals:
            if name=='activate':callback(self.view.entry,*args)
        self.worker.submit.assert_called_once()
        self.owner.launch_smart_action.assert_not_called()

    def test_answer_renders_short_text_and_button(self):
        self.search(answer=from_entry(ENTRIES['memory.usage']))
        self.assertEqual(self.view.command_label.label,'free -h')
        self.assertTrue(self.view.execute_button.get_sensitive())
        self.assertFalse(self.view.spinner.running)
        self.owner.launch_smart_action.assert_not_called()

    def test_button_passes_only_catalogue_id_and_original_cwd(self):
        self.search(answer=from_entry(ENTRIES['memory.usage']))
        self.view._execute()
        self.owner.launch_smart_action.assert_called_once_with('memory.usage','/tmp/original-folder')
        self.owner.current().terminal.feed_child.assert_not_called()

    def test_double_click_never_launches_twice(self):
        self.search(answer=from_entry(ENTRIES['memory.usage']))
        self.view._execute();self.view._execute()
        self.assertEqual(self.owner.launch_smart_action.call_count,1)

    def test_typing_invalidates_permission_and_old_reply(self):
        self.search(answer=from_entry(ENTRIES['memory.usage']))
        serial=self.view._serial
        self.view.entry.set_text('Neue Frage')
        self.view._receive(serial,from_entry(ENTRIES['system.update']))
        self.view._execute()
        self.assertIsNone(self.view._answer)
        self.owner.launch_smart_action.assert_not_called()

    def test_hidden_or_closed_reply_is_ignored(self):
        self.search();serial=self.view._serial
        self.view.popdown()
        self.view._receive(serial,from_entry(ENTRIES['memory.usage']))
        self.assertIsNone(self.view._answer)

    def test_destroy_closes_worker(self):
        self.view.destroy()
        self.worker.close.assert_called_once()
        self.assertTrue(self.view._destroyed)

    def test_refusal_is_exact_and_has_no_execution_button(self):
        self.search('Wie alt ist Elon Musk?',rejected())
        self.assertEqual(self.view.answer_label.label,'Anfrage Abgelehnt')
        self.assertFalse(self.view.command_row.get_visible())
        self.assertFalse(self.view.execute_button.get_sensitive())
        self.view._execute()
        self.owner.launch_smart_action.assert_not_called()

    def test_altered_visible_command_cannot_be_executed(self):
        self.search(answer=replace(from_entry(ENTRIES['memory.usage']),command='sudo rm -rf /'))
        self.assertFalse(self.view.execute_button.get_sensitive())
        self.view._execute()
        self.owner.launch_smart_action.assert_not_called()

    def test_ui_action_checked_against_catalogue(self):
        self.search(answer=from_entry(ENTRIES['app.transparency']))
        self.view._ui_action()
        self.owner.open_settings.assert_called_once()
        self.owner.launch_smart_action.assert_not_called()

    def test_invalid_ui_action_not_called(self):
        self.search(answer=replace(from_entry(ENTRIES['files.cwd']),ui='settings'))
        self.view._ui_action()
        self.owner.open_settings.assert_not_called()

    def test_copy_does_not_run(self):
        clipboard.reset_mock()
        self.search(answer=from_entry(ENTRIES['memory.usage']))
        self.view._copy()
        clipboard.set_text.assert_called_once_with('free -h',-1)
        self.owner.launch_smart_action.assert_not_called()

    def test_ai_optin_is_visible_and_passed_to_worker(self):
        self.owner.settings.update(smart_ai_enabled=True,smart_ai_model='local:small')
        self.search()
        self.assertEqual(self.view.mode_label.label,'LOKALE KI')
        self.worker.submit.assert_called_with(self.view._serial,'Wie viel RAM ist frei?',True,'local:small')

    def test_escape_hides_search(self):
        self.assertTrue(self.view._key(None,NS(keyval=Gdk.KEY_Escape)))
        self.assertFalse(self.view.get_visible())


class LocalAIDialogControllerTests(unittest.TestCase):
    def setUp(self):
        DialogType,_,self.client=load_ui_class('LocalAIDialog')
        self.owner=owner();self.view=DialogType(self.owner)

    def test_constructor_avoids_readonly_window_field(self):
        self.assertIs(self.view._owner_window,self.owner)
        self.assertIsNone(self.view.window)

    def test_no_network_just_by_opening_dialog(self):
        self.client.list_models.assert_not_called()

    def test_model_save_validates_and_persists_name(self):
        self.view.models.get_child().set_text('local:small')
        self.view._apply()
        self.owner.change_setting.assert_called_once_with('smart_ai_model','local:small')

    def test_cloud_model_is_not_saved(self):
        self.view.models.get_child().set_text('qwen-cloud')
        self.view._apply()
        self.owner.change_setting.assert_not_called()

    def test_delayed_model_list_after_destroy_is_ignored(self):
        self.view.destroy()
        self.view._models_received(0,['test:small'],'')
        self.assertNotIn('test:small',self.view.models.texts)


def load_main_method(name, gtk):
    tree=ast.parse((ROOT/'auralyn_terminal/app.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    scope={'get_action':get_action,'Gtk':gtk}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 str(ROOT/'auralyn_terminal/app.py'),'exec'),scope)
    return scope[name]


class MainWindowBoundaryTests(unittest.TestCase):
    def setup(self, response=-5):
        dialog=Mock();dialog.run.return_value=response
        gtk=NS(MessageDialog=Mock(return_value=dialog),MessageType=NS(WARNING=0),
               ButtonsType=NS(NONE=0),ResponseType=NS(OK=-5,CANCEL=-6))
        return load_main_method('launch_smart_action',gtk),NS(destroying=False,add_tab=Mock()),gtk

    def test_readonly_launches_fresh_tab_by_id_without_pasting(self):
        launch,obj,gtk=self.setup()
        self.assertTrue(launch(obj,'memory.usage','/tmp'))
        obj.add_tab.assert_called_once_with('/tmp',smart_action='memory.usage')
        gtk.MessageDialog.assert_not_called()

    def test_update_requires_confirmation(self):
        launch,obj,gtk=self.setup()
        self.assertTrue(launch(obj,'system.update','/tmp'))
        gtk.MessageDialog.return_value.run.assert_called_once()
        obj.add_tab.assert_called_once_with('/tmp',smart_action='system.update')

    def test_cancel_does_not_create_tab(self):
        launch,obj,gtk=self.setup(-6)
        self.assertFalse(launch(obj,'system.update','/tmp'))
        obj.add_tab.assert_not_called()

    def test_bad_id_or_destroyed_window_does_not_execute(self):
        launch,obj,gtk=self.setup()
        self.assertFalse(launch(obj,'anything; rm -rf /','/tmp'))
        obj.destroying=True
        self.assertFalse(launch(obj,'memory.usage','/tmp'))
        obj.add_tab.assert_not_called()

    def test_header_pack_order_places_magnifier_inward_of_info(self):
        source=(ROOT/'auralyn_terminal/app.py').read_text()
        gear=source.index('header.pack_end(button("emblem-system-symbolic"')
        info=source.index('header.pack_end(button("help-about-symbolic"')
        search=source.index('header.pack_end(self.smart_button)')
        self.assertLess(gear,info);self.assertLess(info,search)
        self.assertIn('system-search-symbolic',source)


if __name__ == '__main__':
    unittest.main()
