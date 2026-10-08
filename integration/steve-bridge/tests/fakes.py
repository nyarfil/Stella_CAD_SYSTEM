"""Fake Fusion application used with the vendored STEVE code. No real Fusion needed."""
import queue
import threading
import types

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


class Collection:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


class Event:
    def __init__(self):
        self.handlers = []

    def add(self, handler):
        self.handlers.append(handler)
        return True

    def remove(self, handler):
        self.handlers.remove(handler)
        return True


class Design:
    productType = "DesignProductType"

    def __init__(self):
        self.rootComponent = types.SimpleNamespace(name="root")
        self.unitsManager = types.SimpleNamespace(defaultLengthUnits="mm")
        self.allComponents = Collection()
        self.userParameters = Collection()
        self.log = []  # what a script "modified"; used to observe rollback decisions


class Document:
    def __init__(self, name):
        self.name = name
        self.isValid = True
        self.isSaved = False
        self.isModified = False
        self.design = Design()
        self.products = Collection([self.design])


class Definition:
    def __init__(self, app):
        self.app = app
        self.commandCreated = Event()
        self.name = ""
        self.isValid = True

    def execute(self):
        command = types.SimpleNamespace(execute=Event(), destroy=Event(), isAutoExecute=False,
                                        isExecutedWhenPreEmpted=True)
        for handler in list(self.commandCreated.handlers):
            handler.notify(types.SimpleNamespace(command=command))
        exec_args = types.SimpleNamespace(executeFailed=False, executeFailedMessage="")
        for handler in list(command.execute.handlers):
            handler.notify(exec_args)
        self.app.execute_failed_flags.append(exec_args.executeFailed)  # True => Fusion would roll back
        reason = 2 if exec_args.executeFailed else 1
        for handler in list(command.destroy.handlers):
            handler.notify(types.SimpleNamespace(terminationReason=reason))
        return True

    def deleteMe(self):
        self.isValid = False


class Viewport:
    width, height = 800, 600

    def refresh(self):
        pass

    def saveAsImageFile(self, path, width, height):
        with open(path, "wb") as handle:
            handle.write(PNG)
        return True


class FakeApp:
    """Events fire on one dedicated 'main thread', like Fusion's custom events."""

    def __init__(self, documents, drop_events=False):
        self.documents = Collection(documents)
        self.data = types.SimpleNamespace(marker="cloud-data")
        self.activeDocument = documents[0] if documents else None
        self.execute_failed_flags = []
        self.activeViewport = Viewport()
        self.documentActivated, self.documentClosed = Event(), Event()
        self._events = {}
        self._drop = drop_events
        self._jobs = queue.Queue()
        definitions = types.SimpleNamespace(addButtonDefinition=lambda *a: Definition(self))
        self.userInterface = types.SimpleNamespace(
            commandDefinitions=definitions, commandTerminated=Event(), activeCommand="SelectCommand",
            activeWorkspace=types.SimpleNamespace(id="FusionSolidEnvironment"),
            activeSelections=Collection())
        self.main_thread = threading.Thread(target=self._pump, daemon=True)
        self.main_thread.start()

    @property
    def activeProduct(self):
        return self.activeDocument.design if self.activeDocument else None

    def registerCustomEvent(self, event_id):
        self._events[event_id] = Event()
        return self._events[event_id]

    def unregisterCustomEvent(self, event_id):
        self._events.pop(event_id, None)

    def fireCustomEvent(self, event_id):
        if not self._drop:
            self._jobs.put(event_id)

    def switch_to(self, document):
        self.activeDocument = document

    def _pump(self):
        while True:
            event_id = self._jobs.get()
            if event_id is None:
                return
            for handler in list(self._events.get(event_id, Event()).handlers):
                handler.notify(None)

    def stop(self):
        self._jobs.put(None)
